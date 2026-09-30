import { Component, type ReactNode } from "react";
import { useI18n } from "../i18n";
import { Button, Card, EmptyState } from "./ui";
import { TriangleAlert } from "lucide-react";

function Fallback({ error }: { error: Error }) {
  const { t } = useI18n();
  return (
    <div className="page" style={{ maxWidth: 640, paddingTop: 60 }}>
      <Card>
        <EmptyState
          icon={<TriangleAlert size={40} />}
          title={t("error.title")}
          body={t("error.body")}
          action={<Button variant="primary" onClick={() => location.reload()}>{t("error.reload")}</Button>}
        />
        <details className="tech">
          <summary>{t("common.details")}</summary>
          <pre>{String(error?.stack || error)}</pre>
        </details>
      </Card>
    </div>
  );
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error) {
    console.error("[AppBridge] UI error", error);
  }
  render() {
    return this.state.error ? <Fallback error={this.state.error} /> : this.props.children;
  }
}
