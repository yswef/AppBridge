import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { call, onEvent } from "./api";
import type { ApiError, AppInfo, Device, Job, LibraryItem, Settings } from "./types";

const ACTIVE = new Set(["queued", "running", "waiting_device", "needs_decision"]);

interface Store {
  devices: Device[];
  devicesError: ApiError | null;
  settings: Settings | null;
  appInfo: AppInfo | null;
  jobs: Job[];
  activeJobs: Job[];
  library: LibraryItem[];
  libraryRoot: string;
  libraryLoaded: boolean;
  refreshDevices: () => Promise<void>;
  updateSettings: (changes: Partial<Settings>) => Promise<Settings>;
  reloadSettings: () => Promise<void>;
  reloadJobs: () => Promise<void>;
  reloadLibrary: () => Promise<void>;
  upsertJob: (job: Job) => void;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [devicesError, setDevicesError] = useState<ApiError | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [appInfo, setAppInfo] = useState<AppInfo | null>(null);
  const [jobsMap, setJobsMap] = useState<Record<string, Job>>({});
  const [library, setLibrary] = useState<LibraryItem[]>([]);
  const [libraryRoot, setLibraryRoot] = useState("");
  const [libraryLoaded, setLibraryLoaded] = useState(false);
  const jobsRef = useRef(jobsMap);
  jobsRef.current = jobsMap;

  const loadDevices = useCallback(async () => {
    try {
      const r = await call<{ devices: Device[]; error: ApiError | null }>("list_devices");
      setDevices(r.devices);
      setDevicesError(r.error);
    } catch {
      /* backend not ready */
    }
  }, []);

  const reloadJobs = useCallback(async () => {
    try {
      const list = await call<Job[]>("list_jobs");
      setJobsMap(Object.fromEntries(list.map((j) => [j.id, j])));
    } catch {
      /* ignore */
    }
  }, []);

  const reloadLibrary = useCallback(async () => {
    try {
      const r = await call<{ root: string; items: LibraryItem[] }>("library_list");
      setLibrary(r.items);
      setLibraryRoot(r.root);
    } catch {
      /* ignore */
    } finally {
      setLibraryLoaded(true);
    }
  }, []);

  const reloadSettings = useCallback(async () => {
    setSettings(await call<Settings>("get_settings"));
  }, []);

  const upsertJob = useCallback((job: Job) => {
    setJobsMap((m) => {
      if (!m[job.id] && !job) return m;
      return { ...m, [job.id]: job };
    });
  }, []);

  useEffect(() => {
    reloadSettings().catch(() => {});
    call<AppInfo>("get_app_info").then(setAppInfo).catch(() => {});
    loadDevices();
    reloadJobs();
    reloadLibrary();
    const offs = [
      onEvent("devices", (p) => setDevices(p as Device[])),
      onEvent("job:*", (p) => upsertJob(p as Job)),
      onEvent("library", () => reloadLibrary()),
    ];
    // Light polling as a fallback to push events.
    const devTimer = setInterval(loadDevices, 3000);
    const jobTimer = setInterval(() => {
      if (Object.values(jobsRef.current).some((j) => ACTIVE.has(j.state))) reloadJobs();
    }, 1500);
    return () => {
      offs.forEach((o) => o());
      clearInterval(devTimer);
      clearInterval(jobTimer);
    };
  }, [loadDevices, reloadJobs, reloadLibrary, reloadSettings, upsertJob]);

  const refreshDevices = useCallback(async () => {
    await call("refresh_devices");
    setTimeout(loadDevices, 800);
  }, [loadDevices]);

  const updateSettings = useCallback(async (changes: Partial<Settings>) => {
    const s = await call<Settings>("update_settings", changes);
    setSettings(s);
    return s;
  }, []);

  const jobs = useMemo(() => Object.values(jobsMap).sort((a, b) => b.created_at - a.created_at), [jobsMap]);
  const activeJobs = useMemo(() => jobs.filter((j) => ACTIVE.has(j.state)), [jobs]);

  const value = useMemo(
    () => ({
      devices,
      devicesError,
      settings,
      appInfo,
      jobs,
      activeJobs,
      library,
      libraryRoot,
      libraryLoaded,
      refreshDevices,
      updateSettings,
      reloadSettings,
      reloadJobs,
      reloadLibrary,
      upsertJob,
    }),
    [devices, devicesError, settings, appInfo, jobs, activeJobs, library, libraryRoot, libraryLoaded, refreshDevices,
      updateSettings, reloadSettings, reloadJobs, reloadLibrary, upsertJob],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStore outside provider");
  return v;
}
