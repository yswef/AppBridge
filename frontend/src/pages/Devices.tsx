import { HelpCircle, LayoutGrid, RefreshCw, Smartphone, Usb } from "lucide-react";
import { useState } from "react";
import { HowToModal } from "../components/HowTo";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Progress } from "../components/ui";
import { useI18n } from "../i18n";
import type { TKey } from "../i18n/en";
import { useStore } from "../lib/store";
import type { Device } from "../lib/types";

export function stateLabel(state: string): TKey {
  const known = ["device", "unauthorized", "offline", "no permissions", "recovery"];
  return `devices.state.${known.includes(state) ? state : "other"}` as TKey;
}

function DeviceCard({ d, onBrowse }: { d: Device; onBrowse: (serial: string) => void }) {
  const { t, fmtBytes } = useI18n();
  const ready = d.state === "device";
  const used = d.total_bytes && d.free_bytes !== null ? 1 - d.free_bytes / d.total_bytes : 0;
  return (
    <Card className={`device ${ready ? "" : "unready"}`}>
      <div className="top">
        <div className="phone">
          <Smartphone size={24} />
        </div>
        <div className="col" style={{ gap: 2, minWidth: 0, flex: 1 }}>
          <div className="title truncate ltr" style={{ textAlign: "start" }}>{d.label || d.model || d.serial}</div>
          <div className="muted small">
            {d.manufacturer && <span style={{ textTransform: "capitalize" }}>{d.manufacturer} · </span>}
            {d.android_version ? t("devices.android", { v: d.android_version }) : t("common.unknown")}
          </div>
        </div>
        <Badge tone={ready ? "ok" : d.state === "unauthorized" ? "warn" : "err"} live={!ready}>
          {t(stateLabel(d.state))}
        </Badge>
      </div>

      {ready ? (
        <>
          <div className="meter">
            <div className="row small">
              <span className="muted">{t("devices.storage")}</span>
              <span className="spacer" />
              <span>{t("common.free", { free: fmtBytes(d.free_bytes), total: fmtBytes(d.total_bytes) })}</span>
            </div>
            <Progress value={used} />
          </div>
          <dl className="kv">
            <dt>{t("devices.serial")}</dt>
            <dd className="mono ltr">{d.serial}</dd>
            <dt>{t("devices.abi")}</dt>
            <dd className="mono ltr">{d.abi || "—"}</dd>
          </dl>
          <Button variant="primary" icon={<LayoutGrid size={16} />} onClick={() => onBrowse(d.serial)}>
            {t("devices.browseApps")}
          </Button>
        </>
      ) : d.state === "unauthorized" ? (
        <Alert tone="warn" title={t("devices.unauthorized.title")}>
          {t("devices.unauthorized.body")}
        </Alert>
      ) : (
        <Alert tone="err">{t("devices.offline.body")}</Alert>
      )}
    </Card>
  );
}

export function DevicesPage({ onBrowse }: { onBrowse: (serial: string) => void }) {
  const { t } = useI18n();
  const { devices, devicesError, refreshDevices, appInfo } = useStore();
  const [howto, setHowto] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await refreshDevices();
    } finally {
      setTimeout(() => setRefreshing(false), 700);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>{t("devices.title")}</h1>
          <p>{t("devices.subtitle")}</p>
        </div>
        <span className="spacer" />
        <Button variant="ghost" icon={<HelpCircle size={16} />} onClick={() => setHowto(true)}>
          {t("devices.howto")}
        </Button>
        <Button icon={<RefreshCw size={16} />} loading={refreshing} onClick={refresh}>
          {t("common.refresh")}
        </Button>
      </div>

      {appInfo && !appInfo.adb_available && (
        <div style={{ marginBottom: 16 }}>
          <Alert tone="err">{t("devices.adbMissing")}</Alert>
        </div>
      )}
      {devicesError && (
        <div style={{ marginBottom: 16 }}>
          <ErrorBox error={devicesError} />
        </div>
      )}

      {devices.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Usb size={40} />}
            title={t("devices.empty.title")}
            body={t("devices.empty.body")}
            action={
              <Button variant="primary" icon={<HelpCircle size={16} />} onClick={() => setHowto(true)}>
                {t("devices.howto")}
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid">
          {devices.map((d) => (
            <DeviceCard key={d.serial} d={d} onBrowse={onBrowse} />
          ))}
        </div>
      )}
      {howto && <HowToModal onClose={() => setHowto(false)} />}
    </div>
  );
}
