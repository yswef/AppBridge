import { ListChecks } from "lucide-react";
import { Card, EmptyState } from "../components/ui";
import { useI18n } from "../i18n";

export function TasksPage() {
  const { t } = useI18n();
  return (
    <div className="page">
      <Card>
        <EmptyState icon={<ListChecks size={40} />} title={t("nav.tasks")} />
      </Card>
    </div>
  );
}
