import { ListChecks, Trash2 } from "lucide-react";
import { JobCard } from "../components/JobCard";
import { Button, Card, EmptyState } from "../components/ui";
import { useI18n } from "../i18n";
import { call } from "../lib/api";
import { useStore } from "../lib/store";

export function TasksPage() {
  const { t } = useI18n();
  const { jobs, activeJobs, reloadJobs } = useStore();
  const finished = jobs.length - activeJobs.length;
  return (
    <div className="page" style={{ maxWidth: 920 }}>
      <div className="page-header">
        <div>
          <h1>{t("tasks.title")}</h1>
          <p>{t("tasks.subtitle")}</p>
        </div>
        <span className="spacer" />
        {finished > 0 && (
          <Button icon={<Trash2 size={16} />} onClick={async () => { await call("clear_finished_jobs"); reloadJobs(); }}>
            {t("tasks.clear")}
          </Button>
        )}
      </div>
      {jobs.length === 0 ? (
        <Card>
          <EmptyState icon={<ListChecks size={40} />} title={t("tasks.empty.title")} body={t("tasks.empty.body")} />
        </Card>
      ) : (
        <div className="col" style={{ gap: 12 }}>
          {jobs.map((j) => (
            <JobCard key={j.id} job={j} />
          ))}
        </div>
      )}
    </div>
  );
}
