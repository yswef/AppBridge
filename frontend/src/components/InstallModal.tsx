import { Smartphone, Upload } from "lucide-react";
import { useMemo, useState } from "react";
import { useI18n } from "../i18n";
import { ApiException, call } from "../lib/api";
import { useStore } from "../lib/store";
import type { Job, LibraryItem } from "../lib/types";
import { useToast } from "./toast";
import { AppIcon, Alert, Badge, Button, Modal, Switch } from "./ui";

export function InstallModal({ item, onClose, onStarted }: { item: LibraryItem; onClose: () => void; onStarted: () => void }) {
  const { t, fmtBytes, loc } = useI18n();
  const { devices, settings, upsertJob } = useStore();
  const toast = useToast();
  const ready = useMemo(() => devices.filter((d) => d.state === "device"), [devices]);
  const [picked, setPicked] = useState<Set<string>>(() => new Set(ready.map((d) => d.serial)));
  const [obb, setObb] = useState(true);
  const [data, setData] = useState(true);
  const [verify, setVerify] = useState(settings?.verify_before_install ?? true);
  const [busy, setBusy] = useState(false);

  const toggle = (s: string) =>
    setPicked((p) => {
      const n = new Set(p);
      if (n.has(s)) n.delete(s);
      else n.add(s);
      return n;
    });

  const serials = ready.filter((d) => picked.has(d.serial)).map((d) => d.serial);

  const start = async () => {
    setBusy(true);
    try {
      const jobs = await call<Job[]>("start_install", item.id, serials, { include_obb: obb, include_data: data, verify });
      jobs.forEach(upsertJob);
      toast(t("install.started", { n: jobs.length }));
      onStarted();
    } catch (e) {
      if (e instanceof ApiException) toast(loc(e.error.message), "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      wide
      title={t("install.title", { name: item.display_name })}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" icon={<Upload size={16} />} disabled={!serials.length} loading={busy} onClick={start}>
            {t("install.start", { n: serials.length })}
          </Button>
        </>
      }
    >
      <div className="row" style={{ marginBottom: 14 }}>
        <AppIcon src={item.icon} name={item.display_name} />
        <div className="col" style={{ gap: 0 }}>
          <strong>{item.display_name}</strong>
          <span className="small muted ltr" style={{ textAlign: "start" }}>
            {item.version_name} ({item.version_code}) · {fmtBytes(item.size)}
          </span>
        </div>
      </div>

      <h3 style={{ fontSize: 14, margin: "6px 0 8px" }}>{t("install.pickDevices")}</h3>
      {ready.length === 0 ? (
        <Alert tone="warn">{t("install.noDevices")}</Alert>
      ) : (
        <div className="col" style={{ gap: 8 }}>
          {ready.map((d) => (
            <label key={d.serial} className="card flat row" style={{ padding: 12, cursor: "pointer" }}>
              <input type="checkbox" checked={picked.has(d.serial)} onChange={() => toggle(d.serial)} style={{ width: 18, height: 18, accentColor: "var(--accent)" }} />
              <Smartphone size={18} />
              <div className="col" style={{ gap: 0, flex: 1 }}>
                <strong className="ltr" style={{ textAlign: "start" }}>{d.label || d.model}</strong>
                <span className="small muted">
                  {t("devices.android", { v: d.android_version })} · {t("common.free", { free: fmtBytes(d.free_bytes), total: fmtBytes(d.total_bytes) })}
                </span>
              </div>
              {d.free_bytes !== null && d.free_bytes < item.size * 1.5 && <Badge tone="warn">{t("devices.storage")}</Badge>}
            </label>
          ))}
        </div>
      )}

      <h3 style={{ fontSize: 14, margin: "18px 0 8px" }}>{t("install.options")}</h3>
      <div className="col" style={{ gap: 10 }}>
        {item.has_obb && (
          <label className="row small" style={{ justifyContent: "space-between" }}>
            <span>{t("install.opt.obb")}</span>
            <Switch on={obb} onChange={setObb} />
          </label>
        )}
        {item.has_data && (
          <label className="row small" style={{ justifyContent: "space-between" }}>
            <span>{t("install.opt.data")}</span>
            <Switch on={data} onChange={setData} />
          </label>
        )}
        <label className="row small" style={{ justifyContent: "space-between" }}>
          <span>{t("install.opt.verify")}</span>
          <Switch on={verify} onChange={setVerify} />
        </label>
      </div>
    </Modal>
  );
}
