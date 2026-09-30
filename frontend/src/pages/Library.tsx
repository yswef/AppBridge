import { Library } from "lucide-react";
import type { Page } from "../App";
import { Card, EmptyState } from "../components/ui";
import { useI18n } from "../i18n";

export function LibraryPage(_: { onNavigate: (p: Page) => void }) {
  const { t } = useI18n();
  return (
    <div className="page">
      <Card>
        <EmptyState icon={<Library size={40} />} title={t("nav.library")} />
      </Card>
    </div>
  );
}
