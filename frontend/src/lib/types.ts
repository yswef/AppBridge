export type Lang = "ar" | "en";
export type Localized = { en: string; ar: string };

export interface ApiError {
  code: string;
  detail: string;
  params: Record<string, unknown>;
  message: Localized;
  hint: Localized;
}

export interface Device {
  serial: string;
  state: string;
  model: string;
  manufacturer: string;
  brand: string;
  device: string;
  android_version: string;
  sdk: number;
  abi: string;
  abis: string;
  free_bytes: number | null;
  total_bytes: number | null;
  usb: string;
  label: string;
}

export interface PhoneApp {
  package: string;
  apk_path: string;
  system: boolean;
  game: boolean;
  version_name: string;
  version_code: number;
  apk_bytes: number;
  obb_bytes: number;
  data_bytes: number | null;
  split: boolean;
  in_library: boolean;
}

export interface AppDetails {
  package: string;
  apks: { path: string; size: number }[];
  obb_bytes: number;
  obb_files: number;
  data_bytes: number | null;
  data_files: number | null;
  data_error: ApiError | null;
  version_name: string;
  version_code: number;
  target_sdk: number;
}

export type JobState =
  | "queued"
  | "running"
  | "waiting_device"
  | "needs_decision"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export interface JobProgress {
  phase: string;
  done: number;
  total: number;
  speed: number;
  eta: number | null;
  current: string;
  files_done: number;
  files_total: number;
}

export interface Decision {
  code: string;
  options: string[];
  error: ApiError | null;
  params?: Record<string, unknown>;
}

export interface Job {
  id: string;
  kind: "extract" | "install" | "export" | "import" | "verify";
  state: JobState;
  title: string;
  package: string;
  serial: string;
  device_label: string;
  item_id: number | null;
  progress: JobProgress;
  error: ApiError | null;
  decision: Decision | null;
  warnings: ApiError[];
  created_at: number;
  finished_at: number | null;
  result: Record<string, unknown> | null;
  resumable: boolean;
}

export interface LibraryItem {
  id: number;
  package: string;
  label: string;
  display_name: string;
  version_name: string;
  version_code: number;
  min_sdk: number;
  target_sdk: number;
  size: number;
  created_at: string;
  status: "complete" | "incomplete" | "missing";
  path: string;
  icon: string | null;
  has_obb: boolean;
  has_data: boolean;
  apk_count: number;
  file_count: number;
  signer_sha256: string[];
  source_device: string;
  notes: string[];
}

export interface Settings {
  library_dir: string;
  language: "system" | Lang;
  theme: "system" | "light" | "dark";
  split_size_mb: number;
  include_install_bat: boolean;
  verify_before_install: boolean;
  show_system_apps: boolean;
}

export interface AppInfo {
  name: string;
  version: string;
  adb_path: string;
  adb_available: boolean;
  adb_version: string;
  data_dir: string;
  log_dir: string;
  portable: boolean;
  platform: string;
}

export interface CheckResult {
  code: string;
  level: "ok" | "info" | "warning" | "error";
  message: Localized;
  hint: Localized;
  detail: string;
  params: Record<string, unknown>;
}

export interface Preflight {
  serial: string;
  device_label: string;
  checks: CheckResult[];
  installed_version_code: number | null;
  installed_version_name: string | null;
  can_install: boolean;
  needs_confirmation: string[];
  error?: ApiError;
}
