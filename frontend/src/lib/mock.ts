// In-browser mock of the Python backend, used by `npm run dev` outside pywebview.
import { emitLocal } from "./api";
import type { AppDetails, AppInfo, Device, Job, LibraryItem, PhoneApp, Settings } from "./types";

const ok = <T,>(data: T) => new Promise<{ ok: true; data: T }>((r) => setTimeout(() => r({ ok: true, data }), 120));

const settings: Settings = {
  library_dir: "C:\\Users\\me\\Documents\\AppBridge Library",
  language: "system",
  theme: "system",
  split_size_mb: 2048,
  include_install_bat: true,
  verify_before_install: true,
  show_system_apps: false,
  welcome_done: false,
};

const device = (serial: string, model: string, extra: Partial<Device> = {}): Device => ({
  serial,
  state: "device",
  model,
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
  label: model,
  ...extra,
});

const devices: Device[] = [
  device("R58M12ABCDE", "SM-A515F"),
  device("ZY22ABCD12", "moto g42", { manufacturer: "motorola", android_version: "13", sdk: 33, free_bytes: 8_100_000_000, total_bytes: 64_000_000_000 }),
  { ...device("8A7Y0CXYZ", ""), state: "unauthorized", manufacturer: "", android_version: "", free_bytes: null, total_bytes: null, label: "8A7Y0CXYZ" },
];

const apps: PhoneApp[] = [
  ["com.dts.freefireth", "1.104.1", 2019117233, 812_000_000, 1_230_000_000, true],
  ["com.tencent.ig", "3.4.0", 19240, 1_050_000_000, 0, true],
  ["com.supercell.clashofclans", "16.354.13", 1635413, 290_000_000, 0, true],
  ["com.whatsapp", "2.24.21.6", 242114006, 112_000_000, 0, false],
  ["org.telegram.messenger", "11.2.2", 52232, 88_000_000, 0, false],
  ["com.instagram.android", "352.0.0.38.100", 377206395, 190_000_000, 0, false],
].map(([pkg, vn, vc, apk, obb, game]) => ({
  package: pkg as string,
  apk_path: `/data/app/~~x==/${pkg}-1==/base.apk`,
  system: false,
  game: game as boolean,
  version_name: vn as string,
  version_code: vc as number,
  apk_bytes: apk as number,
  obb_bytes: obb as number,
  data_bytes: null,
  split: true,
  in_library: pkg === "com.whatsapp",
}));

const library: LibraryItem[] = [
  {
    id: 1,
    package: "com.whatsapp",
    label: "WhatsApp",
    display_name: "WhatsApp",
    version_name: "2.24.21.6",
    version_code: 242114006,
    min_sdk: 21,
    target_sdk: 34,
    size: 112_000_000,
    created_at: "2026-09-28T18:22:00+00:00",
    status: "complete",
    path: "C:\\Users\\me\\Documents\\AppBridge Library\\com.whatsapp-242114006",
    icon: null,
    has_obb: false,
    has_data: false,
    apk_count: 4,
    file_count: 4,
    signer_sha256: ["3987d043d10aefaf5a8710b3671418fe57e0e19b653c9df82558feb5ffce5d44"],
    source_device: "SM-A515F",
    notes: ["internal_data_not_included"],
  },
];

const jobs: Record<string, Job> = {};

function newJob(kind: Job["kind"], pkg: string, serial: string, total: number, title?: string): Job {
  const id = Math.random().toString(16).slice(2, 14);
  const d = devices.find((x) => x.serial === serial);
  const job: Job = {
    id,
    kind,
    state: "running",
    title: title ?? pkg,
    package: pkg,
    serial,
    device_label: d?.label ?? "",
    item_id: null,
    progress: { phase: "scan", done: 0, total, speed: 0, eta: null, current: "", files_done: 0, files_total: 1240, },
    error: null,
    decision: null,
    warnings: [],
    created_at: Date.now() / 1000,
    finished_at: null,
    result: null,
    resumable: true,
  };
  jobs[id] = job;
  simulate(job);
  return job;
}

function simulate(job: Job) {
  const phases = job.kind === "extract" ? ["apk", "obb", "data"] : job.kind === "install" ? ["verify", "install", "push_obb", "push_data"] : ["pack"];
  const step = job.progress.total / 60;
  const timer = setInterval(() => {
    if (job.state !== "running") {
      if (["cancelled", "paused", "failed"].includes(job.state)) clearInterval(timer);
      return;
    }
    const p = job.progress;
    p.done = Math.min(p.total, p.done + step * (0.6 + Math.random() * 0.8));
    p.speed = step * 2.5;
    p.eta = (p.total - p.done) / p.speed;
    p.phase = phases[Math.min(phases.length - 1, Math.floor((p.done / p.total) * phases.length))];
    p.files_done = Math.floor((p.done / p.total) * p.files_total);
    p.current = `/sdcard/Android/obb/${job.package}/main.${job.package}.obb`;
    if (p.done >= p.total) {
      job.state = "completed";
      job.finished_at = Date.now() / 1000;
      clearInterval(timer);
    }
    emitLocal(`job:${job.id}`, { ...job, progress: { ...p } });
  }, 400);
}

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
  choose_library_dir: () => ok(null),
  list_devices: () => ok({ devices, error: null }),
  refresh_devices: () => ok(true),
  export_logs: () => ok("C:\\Users\\me\\Desktop\\appbridge-logs.zip"),
  open_path: () => ok(true),
  list_apps: () => ok(apps),
  app_details: (_serial: string, pkg: string) => {
    const a = apps.find((x) => x.package === pkg)!;
    return ok<AppDetails>({
      package: pkg,
      apks: [
        { path: `/data/app/~~x==/${pkg}-1==/base.apk`, size: a.apk_bytes * 0.9 },
        { path: `/data/app/~~x==/${pkg}-1==/split_config.arm64_v8a.apk`, size: a.apk_bytes * 0.1 },
      ],
      obb_bytes: a.obb_bytes,
      obb_files: a.obb_bytes ? 2 : 0,
      data_bytes: a.game ? 2_400_000_000 : 0,
      data_files: a.game ? 5320 : 0,
      data_error: null,
      version_name: a.version_name,
      version_code: a.version_code,
      target_sdk: 33,
    });
  },
  start_extract: (serial: string, pkg: string) => ok(newJob("extract", pkg, serial, 4_400_000_000, "Free Fire")),
  list_jobs: () => ok(Object.values(jobs).map((j) => ({ ...j, progress: { ...j.progress } }))),
  job_action: (id: string, action: string) => {
    const j = jobs[id];
    if (action === "cancel") j.state = "cancelled";
    if (action === "pause") j.state = "paused";
    if (action === "resume") {
      j.state = "running";
      simulate(j);
    }
    return ok({ ...j });
  },
  job_decide: () => ok(true),
  clear_finished_jobs: () => {
    for (const [id, j] of Object.entries(jobs)) if (["completed", "failed", "cancelled"].includes(j.state)) delete jobs[id];
    return ok(true);
  },
  start_install: (itemId: number, serials: string[]) => {
    const it = library.find((x) => x.id === itemId)!;
    return ok(serials.map((s) => newJob("install", it.package, s, it.size, it.display_name)));
  },
  install_preflight: (_id: number, serials: string[]) =>
    ok(
      serials.map((s, i) => ({
        serial: s,
        device_label: s,
        installed_version_code: i ? 2029000000 : null,
        installed_version_name: i ? "1.105.0" : null,
        can_install: true,
        needs_confirmation: i ? ["downgrade"] : [],
        checks: [
          { code: "FILES_PRESENT", level: "ok", message: { en: "All files are present.", ar: "كل الملفات موجودة." }, hint: { en: "", ar: "" }, detail: "", params: {} },
          { code: "SPLITS_CONSISTENT", level: "ok", message: { en: "All APK parts are signed with the same certificate (v2).", ar: "كل أجزاء APK موقّعة بنفس الشهادة (v2)." }, hint: { en: "", ar: "" }, detail: "", params: {} },
          i
            ? { code: "DOWNGRADE", level: "warning", message: { en: "The phone has a newer version (1.105.0) than this copy (1.104.1).", ar: "الهاتف عليه إصدار أحدث (1.105.0) من هذه النسخة (1.104.1)." }, hint: { en: "Android refuses downgrades.", ar: "أندرويد يرفض التثبيت فوق إصدار أحدث." }, detail: "", params: {} }
            : { code: "NOT_INSTALLED", level: "info", message: { en: "Not installed on this phone — fresh install.", ar: "غير مثبت على هذا الهاتف — تثبيت جديد." }, hint: { en: "", ar: "" }, detail: "", params: {} },
          { code: "SPACE_OK", level: "ok", message: { en: "Enough free space (33.5 GB free, about 4.6 GB needed).", ar: "المساحة كافية (المتاح 33.5 GB والمطلوب قرابة 4.6 GB)." }, hint: { en: "", ar: "" }, detail: "", params: {} },
        ],
      })),
    ),
  start_verify: (id: number) => {
    const it = library.find((x) => x.id === id)!;
    return ok(newJob("verify", it.package, "", it.size, it.display_name));
  },
  export_bundle: (id: number) => {
    const it = library.find((x) => x.id === id)!;
    const j = newJob("export", it.package, "", it.size, it.display_name);
    j.result = { files: ["C:\\Users\\me\\Desktop\\WhatsApp 2.24.21.6.appbridge"] };
    return ok(j);
  },
  import_bundle: () => ok(newJob("import", "com.dts.freefireth", "", 4_400_000_000, "Free Fire 1.104.1.appbridge")),
  library_list: () => ok({ root: settings.library_dir, items: library }),
  library_rename: (id: number, name: string) => {
    const it = library.find((x) => x.id === id)!;
    it.display_name = name;
    return ok(it);
  },
  library_delete: (id: number) => {
    library.splice(library.findIndex((x) => x.id === id), 1);
    return ok(true);
  },
  library_open_folder: () => ok(""),
};
