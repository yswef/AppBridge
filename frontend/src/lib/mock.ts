// In-browser mock of the Python backend, used by `npm run dev` outside pywebview.
import type { AppInfo, Device, Settings } from "./types";

const ok = <T,>(data: T) => Promise.resolve({ ok: true as const, data });

const settings: Settings = {
  library_dir: "C:\\Users\\me\\Documents\\AppBridge Library",
  language: "system",
  theme: "system",
  split_size_mb: 2048,
  include_install_bat: true,
  verify_before_install: true,
  show_system_apps: false,
};

export const mockDevices: Device[] = [
  {
    serial: "R58M12ABCDE",
    state: "device",
    model: "SM-A515F",
    manufacturer: "samsung",
    brand: "samsung",
    device: "a51",
    android_version: "14",
    sdk: 34,
    abi: "arm64-v8a",
    abis: "arm64-v8a,armeabi-v7a",
    free_bytes: 35_951_210_496,
    total_bytes: 118_000_000_000,
    usb: "1-1",
    label: "SM-A515F",
  },
  {
    serial: "8A7Y0CXYZ",
    state: "unauthorized",
    model: "",
    manufacturer: "",
    brand: "",
    device: "",
    android_version: "",
    sdk: 0,
    abi: "",
    abis: "",
    free_bytes: null,
    total_bytes: null,
    usb: "1-2",
    label: "8A7Y0CXYZ",
  },
];

export const mockState = { settings, devices: mockDevices };

export const mockApi = {
  get_app_info: () =>
    ok<AppInfo>({
      name: "AppBridge",
      version: "0.1.0-dev",
      adb_path: "C:\\Program Files\\AppBridge\\platform-tools\\adb.exe",
      adb_available: true,
      adb_version: "Android Debug Bridge version 1.0.41",
      data_dir: "C:\\Users\\me\\AppData\\Local\\AppBridge",
      log_dir: "C:\\Users\\me\\AppData\\Local\\AppBridge\\logs",
      portable: false,
      platform: "win32",
    }),
  get_settings: () => ok({ ...settings }),
  update_settings: (changes: Partial<Settings>) => {
    Object.assign(settings, changes);
    return ok({ ...settings });
  },
  list_devices: () => ok({ devices: mockState.devices, error: null }),
  refresh_devices: () => ok(true),
  export_logs: () => ok("C:\\Users\\me\\Desktop\\appbridge-logs.zip"),
  open_path: () => ok(true),
};
