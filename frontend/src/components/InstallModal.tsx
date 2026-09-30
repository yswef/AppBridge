import { AlertTriangle, CheckCircle2, Info, Smartphone, Upload, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useI18n } from "../i18n";
import { ApiException, call } from "../lib/api";
import { useStore } from "../lib/store";
import type { CheckResult, Job, LibraryItem, Preflight } from "../lib/types";
import { useToast } from "./toast";
import { AppIcon, Alert, Badge, Button, ErrorBox, Modal, Switch } from "./ui";

function CheckRow({ c }: { c: CheckResult }) {
  const { loc } = useI18n();
  const Icon = c.level === "ok" ? CheckCircle2 : c.level === "error" ? XCircle : c.level === "warning" ? AlertTriangle : Info;
  const color = c.level === "ok" ? "var(--ok)" : c.level === "error" ? "var(--err)" : c.level === "warning" ? "var(--warn)" : "var(--info)";
  return (
    <div className="row small" style={{ alignItems: "flex-start", gap: 8 }}>
      <Icon size={15} style={{ color, flex: "none", marginTop: 3 }} />
      <div>
        <div>{loc(c.message)}</div>
        {loc(c.hint) && <div className="faint">{loc(c.hint)}</div>}
      </div>
    </div>
  );
}

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
  const [pre, setPre] = useState<Record<string, Preflight>>({});
  const [checking, setChecking] = useState(false);
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});

  const toggle = (s: string) =>
    setPicked((p) => {
      const n = new Set(p);
      if (n.has(s)) n.delete(s);
      else n.add(s);
      return n;
    });

  const serials = ready.filter((d) => picked.has(d.serial)).map((d) => d.serial);
  const key = ready.map((d) => d.serial).join(",") + `|${obb}|${data}`;

  useEffect(() => {
    let alive = true;
    const all = ready.map((d) => d.serial);
    if (!all.length) return;
    setChecking(true);
    call<Preflight[]>("install_preflight", item.id, all, { include_obb: obb, include_data: data })
      .then((rs) => alive && setPre(Object.fromEntries(rs.map((r) => [r.serial, r]))))
      .catch(() => {})
      .finally(() => alive && setChecking(false));
    return () => {
      alive = false;
    };
  }, [key, item.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const blocked = serials.filter((s) => pre[s] && !pre[s].can_install);
  const unconfirmed = serials.filter((s) => pre[s]?.needs_confirmation.length && !confirmed[s]);
  const canStart = serials.length > 0 && !checking && blocked.length === 0 && unconfirmed.length === 0;

  const start = async () => {
    setBusy(true);
    try {
      const per_device = Object.fromEntries(serials.map((s) => [s, { replace_incompatible: !!confirmed[s] }]));
      const jobs = await call<Job[]>("start_install", item.id, serials, { include_obb: obb, include_data: data, verify, per_device });
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
          <Button variant="primary" icon={<Upload size={16} />} disabled={!canStart} loading={busy} onClick={start}>
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
            <div key={d.serial} className="card flat col" style={{ padding: 12, gap: 10 }}>
              <label className="row" style={{ cursor: "pointer" }}>
                <input type="checkbox" checked={picked.has(d.serial)} onChange={() => toggle(d.serial)} style={{ width: 18, height: 18, accentColor: "var(--accent)" }} />
                <Smartphone size={18} />
                <div className="col" style={{ gap: 0, flex: 1 }}>
                  <strong className="ltr" style={{ textAlign: "start" }}>{d.label || d.model}</strong>
                  <span className="small muted">
                    {t("devices.android", { v: d.android_version })} · {t("common.free", { free: fmtBytes(d.free_bytes), total: fmtBytes(d.total_bytes) })}
                  </span>
                </div>
                {!pre[d.serial] && checking ? (
                  <Badge><span className="spinner" style={{ width: 12, height: 12 }} />{t("install.check.running")}</Badge>
                ) : pre[d.serial] && !pre[d.serial].can_install ? (
                  <Badge tone="err">{t("install.blocked")}</Badge>
                ) : pre[d.serial]?.needs_confirmation.length ? (
                  <Badge tone="warn">{t("install.needsConfirmBadge")}</Badge>
                ) : pre[d.serial] ? (
                  <Badge tone="ok">{t("install.check.ok")}</Badge>
                ) : null}
              </label>
              {pre[d.serial] && picked.has(d.serial) && (
                <div className="col" style={{ gap: 6, paddingInlineStart: 28 }}>
                  {pre[d.serial].checks.map((c) => (
                    <CheckRow key={c.code} c={c} />
                  ))}
                  {pre[d.serial].error && <ErrorBox error={pre[d.serial].error!} />}
                  {pre[d.serial].needs_confirmation.length > 0 && (
                    <label className="row small" style={{ alignItems: "flex-start", cursor: "pointer", marginTop: 4 }}>
                      <input
                        type="checkbox"
                        checked={!!confirmed[d.serial]}
                        onChange={(e) => setConfirmed((c) => ({ ...c, [d.serial]: e.target.checked }))}
                        style={{ width: 16, height: 16, accentColor: "var(--err)", marginTop: 3 }}
                      />
                      <span>
                        {pre[d.serial].needs_confirmation.includes("signature") ? t("install.confirm.signature") : t("install.confirm.downgrade")}
                        {!confirmed[d.serial] && <div className="faint">{t("install.needsConfirm")}</div>}
                      </span>
                    </label>
                  )}
                </div>
              )}
            </div>
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
