import { Download, Gamepad2, LayoutGrid, RefreshCw, Smartphone } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { Page } from "../App";
import { useToast } from "../components/toast";
import { Alert, AppIcon, Badge, Button, Card, EmptyState, ErrorBox, SearchInput, Segmented, Switch } from "../components/ui";
import { useI18n } from "../i18n";
import { ApiException, call } from "../lib/api";
import { useStore } from "../lib/store";
import type { ApiError, AppDetails, Job, PhoneApp } from "../lib/types";

type Filter = "user" | "games" | "all";

export function prettyPackage(pkg: string) {
  const parts = pkg.split(".").filter((p) => !["com", "org", "net", "android", "app", "apps", "mobile"].includes(p));
  const last = parts[parts.length - 1] || pkg;
  return last.charAt(0).toUpperCase() + last.slice(1);
}

export function AppsPage({
  serial,
  onSerial,
  onNavigate,
}: {
  serial: string | null;
  onSerial: (s: string) => void;
  onNavigate: (p: Page) => void;
}) {
  const { t, fmtBytes } = useI18n();
  const { devices, upsertJob } = useStore();
  const toast = useToast();
  const ready = devices.filter((d) => d.state === "device");
  const current = ready.find((d) => d.serial === serial) ?? ready[0];

  const [apps, setApps] = useState<PhoneApp[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<Filter>("user");
  const [sort, setSort] = useState<"size" | "name">("size");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async (s: string, all: boolean) => {
    setLoading(true);
    setError(null);
    try {
      setApps(await call<PhoneApp[]>("list_apps", s, all));
    } catch (e) {
      setApps(null);
      if (e instanceof ApiException) setError(e.error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (current && current.serial !== serial) onSerial(current.serial);
  }, [current, serial, onSerial]);

  const includeSystem = filter === "all";
  useEffect(() => {
    setSelected(null);
    if (current) load(current.serial, includeSystem);
    else setApps(null);
  }, [current?.serial, includeSystem, load]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = useMemo(() => {
    let xs = apps ?? [];
    if (filter === "user") xs = xs.filter((a) => !a.system);
    if (filter === "games") xs = xs.filter((a) => a.game);
    const q = query.trim().toLowerCase();
    if (q) xs = xs.filter((a) => a.package.toLowerCase().includes(q) || prettyPackage(a.package).toLowerCase().includes(q));
    return [...xs].sort((a, b) =>
      sort === "size" ? b.apk_bytes + b.obb_bytes - (a.apk_bytes + a.obb_bytes) : prettyPackage(a.package).localeCompare(prettyPackage(b.package)),
    );
  }, [apps, filter, query, sort]);

  if (!current) {
    return (
      <div className="page">
        <Card>
          <EmptyState
            icon={<Smartphone size={40} />}
            title={t("apps.noDevice.title")}
            body={t("apps.noDevice.body")}
            action={<Button onClick={() => onNavigate("devices")}>{t("nav.devices")}</Button>}
          />
        </Card>
      </div>
    );
  }

  const sel = shown.find((a) => a.package === selected) ?? apps?.find((a) => a.package === selected) ?? null;

  return (
    <div className="page" style={{ maxWidth: 1280 }}>
      <div className="page-header">
        <div>
          <h1>{t("apps.title")}</h1>
          <p>{t("apps.subtitle")}</p>
        </div>
        <span className="spacer" />
        {ready.length > 1 && (
          <Segmented value={current.serial} onChange={onSerial} options={ready.map((d) => ({ value: d.serial, label: d.label || d.model }))} />
        )}
      </div>

      <div className="toolbar">
        <Segmented<Filter>
          value={filter}
          onChange={setFilter}
          options={[
            { value: "user", label: t("apps.filter.user") },
            { value: "games", label: t("apps.filter.games") },
            { value: "all", label: t("apps.filter.all") },
          ]}
        />
        <SearchInput value={query} onChange={setQuery} />
        <span className="spacer" />
        <Segmented
          value={sort}
          onChange={setSort}
          options={[
            { value: "size", label: t("apps.sort.size") },
            { value: "name", label: t("apps.sort.name") },
          ]}
        />
        <Button icon={<RefreshCw size={16} />} loading={loading} onClick={() => load(current.serial, includeSystem)} aria-label={t("common.refresh")} />
      </div>

      {error && (
        <div style={{ marginBottom: 16 }}>
          <ErrorBox error={error} action={<Button size="sm" onClick={() => load(current.serial, includeSystem)}>{t("common.retry")}</Button>} />
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 360px", gap: 16, alignItems: "start" }}>
        <Card style={{ padding: 0, overflow: "hidden" }}>
          {loading && !apps ? (
            <div className="empty">
              <span className="spinner" style={{ width: 28, height: 28 }} />
              <p>{t("apps.loading")}</p>
            </div>
          ) : shown.length === 0 ? (
            <EmptyState icon={<LayoutGrid size={36} />} title={t("apps.empty")} />
          ) : (
            <div style={{ maxHeight: "calc(100vh - 260px)", overflow: "auto" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("apps.col.app")}</th>
                    <th>{t("apps.col.version")}</th>
                    <th className="num">{t("apps.col.size")}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((a) => (
                    <tr key={a.package} className={`clickable ${selected === a.package ? "selected" : ""}`} onClick={() => setSelected(a.package)}>
                      <td>
                        <div className="row" style={{ minWidth: 0 }}>
                          <AppIcon name={a.package} />
                          <div className="col" style={{ gap: 0, minWidth: 0 }}>
                            <div className="row" style={{ gap: 6 }}>
                              <strong className="truncate">{prettyPackage(a.package)}</strong>
                              {a.game && <Badge tone="accent"><Gamepad2 size={12} />{t("apps.game")}</Badge>}
                              {a.system && <Badge>{t("apps.system")}</Badge>}
                              {a.in_library && <Badge tone="ok">{t("apps.inLibrary")}</Badge>}
                            </div>
                            <span className="faint small mono ltr truncate" style={{ textAlign: "start" }}>{a.package}</span>
                          </div>
                        </div>
                      </td>
                      <td className="mono ltr small">{a.version_name || "—"}</td>
                      <td className="num">
                        {fmtBytes(a.apk_bytes + a.obb_bytes)}
                        {a.obb_bytes > 0 && <div className="faint small">{t("apps.obb")} {fmtBytes(a.obb_bytes)}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="faint small" style={{ padding: "8px 14px", borderTop: "1px solid var(--border)" }}>{t("apps.estimated")}</div>
        </Card>

        <div style={{ position: "sticky", top: 0 }}>
          {sel ? (
            <DetailsPanel
              key={sel.package + current.serial}
              serial={current.serial}
              app={sel}
              onStarted={(job) => {
                upsertJob(job);
                toast(t("apps.extracting"));
                onNavigate("tasks");
              }}
            />
          ) : (
            <Card>
              <EmptyState icon={<Download size={32} />} title={t("apps.pick")} />
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function DetailsPanel({ serial, app, onStarted }: { serial: string; app: PhoneApp; onStarted: (j: Job) => void }) {
  const { t, fmtBytes, loc } = useI18n();
  const toast = useToast();
  const [details, setDetails] = useState<AppDetails | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [obb, setObb] = useState(true);
  const [data, setData] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    call<AppDetails>("app_details", serial, app.package)
      .then((d) => {
        if (!alive) return;
        setDetails(d);
        if (d.data_error) setData(false);
      })
      .catch((e) => alive && e instanceof ApiException && setError(e.error));
    return () => {
      alive = false;
    };
  }, [serial, app.package]);

  const apkBytes = details ? details.apks.reduce((s, a) => s + a.size, 0) : app.apk_bytes;
  const total = apkBytes + (obb ? details?.obb_bytes ?? app.obb_bytes : 0) + (data ? details?.data_bytes ?? 0 : 0);

  const start = async () => {
    setBusy(true);
    try {
      const job = await call<Job>("start_extract", serial, app.package, { include_obb: obb, include_data: data });
      onStarted(job);
    } catch (e) {
      if (e instanceof ApiException) toast(loc(e.error.message), "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="col" style={{ gap: 14 }}>
      <div className="row">
        <AppIcon name={app.package} size="lg" />
        <div className="col" style={{ gap: 0, minWidth: 0 }}>
          <strong style={{ fontSize: 17 }} className="truncate">{prettyPackage(app.package)}</strong>
          <span className="mono ltr small faint truncate" style={{ textAlign: "start" }}>{app.package}</span>
          <span className="small muted ltr" style={{ textAlign: "start" }}>
            {app.version_name} {app.version_code ? `(${app.version_code})` : ""}
          </span>
        </div>
      </div>

      {error && <ErrorBox error={error} />}
      {!details && !error && <div className="row muted small"><span className="spinner" />{t("common.loading")}</div>}

      {details && (
        <dl className="kv">
          <dt>{t("apps.details.apk")}</dt>
          <dd>
            {fmtBytes(apkBytes)}
            {details.apks.length > 1 && <div className="faint small">{t("apps.details.split", { n: details.apks.length })}</div>}
          </dd>
          <dt>{t("apps.details.obb")}</dt>
          <dd>
            {fmtBytes(details.obb_bytes)}
            <div className="faint small">{t("apps.details.files", { n: details.obb_files })}</div>
          </dd>
          <dt>{t("apps.details.data")}</dt>
          <dd>
            {details.data_bytes === null ? "—" : fmtBytes(details.data_bytes)}
            {details.data_files !== null && <div className="faint small">{t("apps.details.files", { n: details.data_files })}</div>}
          </dd>
        </dl>
      )}

      <div className="col" style={{ gap: 10 }}>
        <label className="row small" style={{ justifyContent: "space-between" }}>
          <span>{t("apps.opt.obb")}</span>
          <Switch on={obb} onChange={setObb} />
        </label>
        <label className="row small" style={{ justifyContent: "space-between" }}>
          <span>{t("apps.opt.data")}</span>
          <Switch on={data} onChange={setData} />
        </label>
      </div>

      {details?.data_error && <Alert tone="warn">{t("apps.dataDenied")}</Alert>}
      <Alert tone="info">{t("apps.internalNote")}</Alert>

      <div className="row">
        <span className="muted small">{t("apps.details.total")}</span>
        <span className="spacer" />
        <strong>{fmtBytes(total)}</strong>
      </div>
      <Button variant="primary" icon={<Download size={16} />} loading={busy} onClick={start}>
        {t("apps.extract")}
      </Button>
    </Card>
  );
}
