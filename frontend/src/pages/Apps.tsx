import { LayoutGrid } from "lucide-react";
import type { Page } from "../App";
import { Card, EmptyState } from "../components/ui";
import { useI18n } from "../i18n";

export function AppsPage(_: { serial: string | null; onSerial: (s: string) => void; onNavigate: (p: Page) => void }) {
  const { t } = useI18n();
  return (
    <div className="page">
      <Card>
        <EmptyState icon={<LayoutGrid size={40} />} title={t("nav.apps")} />
      </Card>
    </div>
  );
}
