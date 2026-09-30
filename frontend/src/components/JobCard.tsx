import { CheckCircle2, CircleSlash, Clock, Download, FileArchive, FolderInput, Pause, Play, ShieldCheck, Smartphone, Upload, X, XCircle } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../i18n";
import type { TKey } from "../i18n/en";
import { ApiException, call } from "../lib/api";
import { useStore } from "../lib/store";
import type { Job } from "../lib/types";
import { useToast } from "./toast";
import { Alert, Badge, Button, Card, ErrorBox, Progress } from "./ui";

const kindIcon = {
  extract: Download,
  install: Upload,
  export: FileArchive,
  import: FolderInput,
  verify: ShieldCheck,
};

export function JobCard({ job, compact }: { job: Job; compact?: boolean }) {
  const { t, fmtBytes, fmtDuration, loc } = useI18n();
  const { upsertJob } = useStore();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const p = job.progress;
  const Icon = kindIcon[job.kind] ?? Download;
  const active = ["queued", "running", "waiting_device", "needs_decision"].includes(job.state);
  const frac = p.total > 0 ? p.done / p.total : 0;

  const act = async (action: string) => {
    setBusy(true);
    try {
      upsertJob(await call<Job>("job_action", job.id, action));
    } catch (e) {
      if (e instanceof ApiException) toast(loc(e.error.message), "err");
    } finally {
      setBusy(false);
    }
  };
  const decide = async (choice: string) => {
    try {
      await call("job_decide", job.id, choice);
    } catch (e) {
      if (e instanceof ApiException) toast(loc(e.error.message), "err");
    }
  };

  const tone =
    job.state === "completed" ? "ok" : job.state === "failed" ? "err" : job.state === "needs_decision" || job.state === "waiting_device" ? "warn" : job.state === "running" ? "info" : undefined;
  const StateIcon = job.state === "completed" ? CheckCircle2 : job.state === "failed" ? XCircle : job.state === "cancelled" ? CircleSlash : Clock;

  return (
    <Card className="col" style={{ gap: 12 }}>
      <div className="row">
        <div className="app-icon" style={{ width: 40, height: 40 }}>
          <Icon size={20} />
        </div>
        <div className="col" style={{ gap: 0, flex: 1, minWidth: 0 }}>
          <div className="row" style={{ gap: 8 }}>
            <strong className="truncate">{job.title || job.package}</strong>
            <Badge>{t(`tasks.kind.${job.kind}` as TKey)}</Badge>
          </div>
          <div className="small muted row" style={{ gap: 6 }}>
            {job.device_label && (
              <>
                <Smartphone size={13} />
                <span className="ltr">{job.device_label}</span>
                <span>·</span>
              </>
            )}
            <span className="mono ltr truncate">{job.package}</span>
          </div>
        </div>
        <Badge tone={tone} live={active}>
          {!active && <StateIcon size={13} />}
          {t(`tasks.state.${job.state}` as TKey)}
        </Badge>
      </div>

      {(active || job.state === "paused") && (
        <div className="col" style={{ gap: 6 }}>
          <Progress value={frac} indeterminate={job.state === "running" && p.total === 0} />
          <div className="row small muted wrap" style={{ gap: 12 }}>
            {p.phase && <span>{t(`tasks.phase.${p.phase}` as TKey)}</span>}
            <span className="ltr">
              {fmtBytes(p.done)} / {fmtBytes(p.total)}
            </span>
            {p.files_total > 0 && <span>{t("tasks.files", { done: p.files_done, total: p.files_total })}</span>}
            <span className="spacer" />
            {job.state === "running" && p.speed > 0 && <span className="ltr">{t("tasks.speed", { speed: fmtBytes(p.speed) })}</span>}
            {job.state === "running" && p.eta !== null && <span>{t("tasks.eta", { eta: fmtDuration(p.eta) })}</span>}
            <strong>{Math.floor(frac * 100)}%</strong>
          </div>
          {!compact && p.current && <div className="faint small mono ltr truncate" style={{ textAlign: "start" }}>{p.current}</div>}
        </div>
      )}

      {job.state === "waiting_device" && <Alert tone="warn">{t("tasks.waiting")}</Alert>}

      {job.decision && (
        <ErrorBox
          tone="warn"
          error={job.decision.error!}
          action={
            <div className="col" style={{ gap: 6 }}>
              {job.decision.options.map((o, i) => (
                <Button key={o} size="sm" variant={i === 0 ? "primary" : o === "cancel" ? "danger" : "default"} onClick={() => decide(o)}>
                  {t(`tasks.decision.${o}` as TKey)}
                </Button>
              ))}
            </div>
          }
        />
      )}

      {job.error && <ErrorBox error={job.error} />}

      {job.warnings.length > 0 && !compact && (
        <details className="tech">
          <summary>{t("tasks.warnings", { n: job.warnings.length })}</summary>
          <pre>{job.warnings.map((w) => `${loc(w.message)}\n${w.detail}`).join("\n\n")}</pre>
        </details>
      )}

      {job.state === "completed" && (
        <Alert
          tone="ok"
          action={
            job.kind === "export" && Array.isArray(job.result?.files) ? (
              <Button size="sm" onClick={() => call("open_path", (job.result!.files as string[])[0]).catch(() => {})}>
                {t("tasks.showFile")}
              </Button>
            ) : undefined
          }
        >
          {t(`tasks.done.${job.kind}` as TKey)}
          {job.kind === "export" && Array.isArray(job.result?.files) && (
            <div className="mono ltr small" style={{ textAlign: "start", wordBreak: "break-all" }}>
              {(job.result!.files as string[]).join("\n")}
            </div>
          )}
        </Alert>
      )}

      <div className="row" style={{ justifyContent: "flex-end" }}>
        {job.state === "running" && job.resumable && (
          <Button size="sm" icon={<Pause size={14} />} loading={busy} onClick={() => act("pause")}>
            {t("tasks.pause")}
          </Button>
        )}
        {(job.state === "paused" || (job.state === "failed" && job.resumable)) && (
          <Button size="sm" variant="primary" icon={<Play size={14} />} loading={busy} onClick={() => act("resume")}>
            {job.state === "failed" ? t("common.retry") : t("tasks.resume")}
          </Button>
        )}
        {(active || job.state === "paused") && (
          <Button size="sm" variant="danger" icon={<X size={14} />} loading={busy} onClick={() => act("cancel")}>
            {t("tasks.cancel")}
          </Button>
        )}
      </div>
    </Card>
  );
}
