import { Cable, Hammer, Settings2, ShieldCheck, Smartphone, ToggleRight } from "lucide-react";
import { useI18n } from "../i18n";
import { Alert, Button, Modal } from "./ui";

const icons = [Smartphone, Hammer, Settings2, ToggleRight, Cable, ShieldCheck];

function PhoneIllustration({ step }: { step: number }) {
  // Simple, language-neutral phone sketch highlighting the step's action.
  const Icon = icons[step];
  return (
    <svg className="illus" width="120" height="70" viewBox="0 0 120 70" aria-hidden>
      <rect x="1" y="1" width="118" height="68" rx="12" fill="var(--surface-2)" stroke="var(--border)" />
      <rect x="44" y="8" width="32" height="54" rx="6" fill="var(--surface)" stroke="var(--text-3)" />
      <rect x="49" y="16" width="22" height="4" rx="2" fill="var(--surface-3)" />
      <rect x="49" y="24" width="22" height="4" rx="2" fill={step === 1 ? "var(--accent)" : "var(--surface-3)"} />
      <rect x="49" y="32" width="22" height="4" rx="2" fill={step === 3 ? "var(--accent)" : "var(--surface-3)"} />
      <foreignObject x="84" y="20" width="30" height="30">
        <div style={{ color: "var(--accent)" }}>
          <Icon size={26} />
        </div>
      </foreignObject>
    </svg>
  );
}

export function HowToModal({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const steps = ["howto.step1", "howto.step2", "howto.step3", "howto.step4", "howto.step5", "howto.step6"] as const;
  return (
    <Modal title={t("howto.title")} onClose={onClose} wide footer={<Button variant="primary" onClick={onClose}>{t("common.close")}</Button>}>
      <ol className="steps">
        {steps.map((k, i) => (
          <li key={k}>
            <div>
              <div>{t(k)}</div>
              <PhoneIllustration step={i} />
            </div>
          </li>
        ))}
      </ol>
      <div style={{ marginTop: 14 }}>
        <Alert tone="info">{t("howto.driverNote")}</Alert>
      </div>
    </Modal>
  );
}
