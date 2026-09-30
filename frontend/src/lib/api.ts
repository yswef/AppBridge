import type { ApiError } from "./types";
import { mockApi } from "./mock";

type Resp<T> = { ok: true; data: T } | { ok: false; error: ApiError };

export class ApiException extends Error {
  error: ApiError;
  constructor(error: ApiError) {
    super(error.message?.en || error.code);
    this.error = error;
  }
}

declare global {
  interface Window {
    pywebview?: { api: Record<string, (...args: unknown[]) => Promise<unknown>> };
    __appbridgeEvent?: (e: { event: string; payload: unknown }) => void;
  }
}

let ready: Promise<"native" | "mock"> | null = null;

function waitForBackend(): Promise<"native" | "mock"> {
  if (ready) return ready;
  ready = new Promise((resolve) => {
    if (window.pywebview?.api) return resolve("native");
    const onReady = () => resolve("native");
    window.addEventListener("pywebviewready", onReady, { once: true });
    // Outside pywebview (npm run dev in a browser) fall back to a mock backend.
    setTimeout(() => {
      if (!window.pywebview?.api) {
        window.removeEventListener("pywebviewready", onReady);
        console.info("[AppBridge] pywebview not found - using mock backend");
        resolve("mock");
      }
    }, 1200);
  });
  return ready;
}

export async function isMock() {
  return (await waitForBackend()) === "mock";
}

export async function call<T>(method: string, ...args: unknown[]): Promise<T> {
  const mode = await waitForBackend();
  const fn =
    mode === "native"
      ? window.pywebview!.api[method]
      : (mockApi as unknown as Record<string, (...a: unknown[]) => Promise<unknown>>)[method];
  if (!fn) throw new ApiException(unknownError(`Unknown API method ${method}`));
  const resp = (await fn(...args)) as Resp<T>;
  if (!resp || typeof resp !== "object") throw new ApiException(unknownError("Empty response"));
  if (!resp.ok) throw new ApiException(resp.error);
  return resp.data;
}

function unknownError(detail: string): ApiError {
  return {
    code: "UNKNOWN",
    detail,
    params: {},
    message: { en: "An unexpected error occurred.", ar: "حدث خطأ غير متوقع." },
    hint: { en: "", ar: "" },
  };
}

type Listener = (payload: unknown) => void;
const listeners = new Map<string, Set<Listener>>();

window.__appbridgeEvent = ({ event, payload }) => {
  listeners.get(event)?.forEach((l) => l(payload));
};

export function onEvent(event: string, fn: Listener): () => void {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event)!.add(fn);
  return () => listeners.get(event)?.delete(fn);
}

export function emitLocal(event: string, payload: unknown) {
  window.__appbridgeEvent?.({ event, payload });
}
