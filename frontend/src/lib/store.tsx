import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { call, onEvent } from "./api";
import type { ApiError, AppInfo, Device, Settings } from "./types";

interface Store {
  devices: Device[];
  devicesError: ApiError | null;
  settings: Settings | null;
  appInfo: AppInfo | null;
  refreshDevices: () => Promise<void>;
  updateSettings: (changes: Partial<Settings>) => Promise<Settings>;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [devicesError, setDevicesError] = useState<ApiError | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [appInfo, setAppInfo] = useState<AppInfo | null>(null);

  const loadDevices = useCallback(async () => {
    try {
      const r = await call<{ devices: Device[]; error: ApiError | null }>("list_devices");
      setDevices(r.devices);
      setDevicesError(r.error);
    } catch {
      /* backend not ready */
    }
  }, []);

  useEffect(() => {
    call<Settings>("get_settings").then(setSettings).catch(() => {});
    call<AppInfo>("get_app_info").then(setAppInfo).catch(() => {});
    loadDevices();
    const off = onEvent("devices", (p) => setDevices(p as Device[]));
    const timer = setInterval(loadDevices, 3000); // light polling as a fallback to push events
    return () => {
      off();
      clearInterval(timer);
    };
  }, [loadDevices]);

  const refreshDevices = useCallback(async () => {
    await call("refresh_devices");
    setTimeout(loadDevices, 800);
  }, [loadDevices]);

  const updateSettings = useCallback(async (changes: Partial<Settings>) => {
    const s = await call<Settings>("update_settings", changes);
    setSettings(s);
    return s;
  }, []);

  const value = useMemo(
    () => ({ devices, devicesError, settings, appInfo, refreshDevices, updateSettings }),
    [devices, devicesError, settings, appInfo, refreshDevices, updateSettings],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStore outside provider");
  return v;
}
