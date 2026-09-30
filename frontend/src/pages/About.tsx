import { Lock, Scale, TriangleAlert } from "lucide-react";
import logo from "../logo.svg";
import { Alert, Card } from "../components/ui";
import { useI18n } from "../i18n";
import { useStore } from "../lib/store";

export function AboutPage() {
  const { t } = useI18n();
  const { appInfo } = useStore();
  return (
    <div className="page" style={{ maxWidth: 820 }}>
      <Card style={{ display: "flex", gap: 18, alignItems: "center", marginBottom: 16 }}>
        <img src={logo} width={72} height={72} alt="" />
        <div>
          <h1 style={{ margin: 0 }}>{t("about.title")}</h1>
          <div className="muted">
            {t("about.version")} <span className="ltr">{appInfo?.version}</span>
          </div>
        </div>
      </Card>
      <Card style={{ marginBottom: 16 }}>
        <p style={{ marginTop: 0 }}>{t("about.body")}</p>
        <Alert tone="ok" title={t("about.privacy")} />
      </Card>
      <Card style={{ marginBottom: 16 }}>
        <h3 className="row">
          <TriangleAlert size={18} /> {t("about.limits.title")}
        </h3>
        <ul className="muted" style={{ paddingInlineStart: 20, margin: "8px 0 0" }}>
          <li>{t("about.limits.internal")}</li>
          <li>{t("about.limits.server")}</li>
          <li>{t("about.limits.a14")}</li>
        </ul>
      </Card>
      <Card style={{ marginBottom: 16 }}>
        <Alert tone="warn" title={<span className="row"><Scale size={16} />{t("about.legal")}</span>} />
      </Card>
      {appInfo && (
        <Card className="flat">
          <dl className="kv">
            <dt>{t("about.adb")}</dt>
            <dd className="mono ltr">{appInfo.adb_version || appInfo.adb_path || "—"}</dd>
            <dt>{t("about.dataDir")}</dt>
            <dd className="mono ltr">{appInfo.data_dir}</dd>
            <dt><Lock size={14} /></dt>
            <dd className="small muted">offline · no telemetry</dd>
          </dl>
        </Card>
      )}
    </div>
  );
}
