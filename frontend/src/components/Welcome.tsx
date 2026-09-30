import { Download, Scale, Smartphone, Upload } from "lucide-react";
import logo from "../logo.svg";
import { useI18n } from "../i18n";
import { useStore } from "../lib/store";
import { Alert, Button, Modal } from "./ui";

export function Welcome() {
  const { t } = useI18n();
  const { settings, updateSettings } = useStore();
  if (!settings || settings.welcome_done) return null;
  const close = () => updateSettings({ welcome_done: true }).catch(() => {});
  const steps = [
    { icon: <Smartphone size={20} />, text: t("welcome.step1") },
    { icon: <Download size={20} />, text: t("welcome.step2") },
    { icon: <Upload size={20} />, text: t("welcome.step3") },
  ];
  return (
    <Modal
      title={
        <span className="row">
          <img src={logo} width={32} height={32} alt="" />
          {t("welcome.title")}
        </span>
      }
      onClose={close}
      footer={<Button variant="primary" onClick={close}>{t("welcome.start")}</Button>}
    >
      <p style={{ marginTop: 0 }} className="muted">{t("welcome.body")}</p>
      <div className="col" style={{ gap: 12, margin: "14px 0" }}>
        {steps.map((s, i) => (
          <div key={i} className="row" style={{ alignItems: "flex-start" }}>
            <div className="app-icon" style={{ width: 36, height: 36, borderRadius: 10 }}>{s.icon}</div>
            <div style={{ paddingTop: 6 }}>{s.text}</div>
          </div>
        ))}
      </div>
      <Alert tone="warn" title={<span className="row"><Scale size={16} />{t("welcome.legal")}</span>} />
    </Modal>
  );
}
