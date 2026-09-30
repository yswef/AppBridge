import { FolderOpen, Library as LibraryIcon, Pencil, Trash2, Upload } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import type { Page } from "../App";
import { useToast } from "../components/toast";
import { Alert, AppIcon, Badge, Button, Card, EmptyState, Modal, SearchInput, Segmented } from "../components/ui";
import { useI18n } from "../i18n";
import { ApiException, call } from "../lib/api";
import { useStore } from "../lib/store";
import type { LibraryItem } from "../lib/types";

type Sort = "date" | "name" | "size";

export function LibraryPage({
  onNavigate,
  onInstall,
  extraToolbar,
  extraActions,
}: {
  onNavigate: (p: Page) => void;
  onInstall?: (item: LibraryItem) => void;
  extraToolbar?: ReactNode;
  extraActions?: (item: LibraryItem) => ReactNode;
}) {
  const { t, fmtBytes, fmtDate, loc } = useI18n();
  const { library, libraryRoot, libraryLoaded, reloadLibrary } = useStore();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("date");
  const [renaming, setRenaming] = useState<LibraryItem | null>(null);
  const [deleting, setDeleting] = useState<LibraryItem | null>(null);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const xs = library.filter((i) => !q || i.display_name.toLowerCase().includes(q) || i.package.toLowerCase().includes(q));
    return [...xs].sort((a, b) =>
      sort === "name" ? a.display_name.localeCompare(b.display_name) : sort === "size" ? b.size - a.size : b.created_at.localeCompare(a.created_at),
    );
  }, [library, query, sort]);

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      await reloadLibrary();
    } catch (e) {
      if (e instanceof ApiException) toast(loc(e.error.message), "err");
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>{t("library.title")}</h1>
          <p>{t("library.subtitle")}</p>
        </div>
        <span className="spacer" />
        {extraToolbar}
        <Button icon={<FolderOpen size={16} />} onClick={() => run(() => call("library_open_folder"))}>
          {t("common.openFolder")}
        </Button>
      </div>

      {library.length > 0 && (
        <div className="toolbar">
          <SearchInput value={query} onChange={setQuery} />
          <span className="spacer" />
          <Segmented<Sort>
            value={sort}
            onChange={setSort}
            options={[
              { value: "date", label: t("library.sort.date") },
              { value: "name", label: t("library.sort.name") },
              { value: "size", label: t("library.sort.size") },
            ]}
          />
        </div>
      )}

      {libraryLoaded && library.length === 0 ? (
        <Card>
          <EmptyState
            icon={<LibraryIcon size={40} />}
            title={t("library.empty.title")}
            body={t("library.empty.body")}
            action={<Button variant="primary" onClick={() => onNavigate("apps")}>{t("library.goApps")}</Button>}
          />
        </Card>
      ) : (
        <div className="grid">
          {shown.map((item) => (
            <Card key={item.id} className="col lib-card" style={{ gap: 12 }}>
              <div className="row">
                <AppIcon src={item.icon} name={item.display_name || item.package} size="lg" />
                <div className="col" style={{ gap: 0, minWidth: 0, flex: 1 }}>
                  <strong className="truncate" style={{ fontSize: 16 }}>{item.display_name}</strong>
                  <span className="mono ltr small faint truncate" style={{ textAlign: "start" }}>{item.package}</span>
                  <span className="small muted">
                    {t("library.version", { v: item.version_name || String(item.version_code) })} · {fmtBytes(item.size)}
                  </span>
                </div>
              </div>
              <div className="row wrap" style={{ gap: 6 }}>
                <Badge tone={item.status === "complete" ? "ok" : "warn"}>
                  {item.status === "complete" ? t("library.complete") : t("library.incomplete")}
                </Badge>
                {item.apk_count > 1 && <Badge>{t("library.splits", { n: item.apk_count })}</Badge>}
                {item.has_obb && <Badge tone="info">{t("library.hasObb")}</Badge>}
                {item.has_data ? <Badge tone="accent">{t("library.hasData")}</Badge> : <Badge>{t("library.noData")}</Badge>}
              </div>
              <div className="small faint">
                {t("library.extracted", { date: fmtDate(item.created_at) })}
                {item.source_device && <> · {t("library.from", { device: item.source_device })}</>}
              </div>
              {item.status !== "complete" && <Alert tone="warn">{t("library.incompleteHint")}</Alert>}
              <div className="row" style={{ marginTop: "auto" }}>
                {onInstall && (
                  <Button variant="primary" size="sm" icon={<Upload size={14} />} disabled={item.status !== "complete"} onClick={() => onInstall(item)}>
                    {t("library.install")}
                  </Button>
                )}
                {extraActions?.(item)}
                <span className="spacer" />
                <Button size="sm" variant="ghost" icon={<FolderOpen size={15} />} aria-label={t("library.openFolder")} title={t("library.openFolder")}
                  onClick={() => run(() => call("library_open_folder", item.id))} />
                <Button size="sm" variant="ghost" icon={<Pencil size={15} />} aria-label={t("common.rename")} title={t("common.rename")} onClick={() => setRenaming(item)} />
                <Button size="sm" variant="ghost" icon={<Trash2 size={15} />} aria-label={t("common.delete")} title={t("common.delete")} className="danger" onClick={() => setDeleting(item)} />
              </div>
            </Card>
          ))}
        </div>
      )}

      {libraryRoot && <div className="faint small" style={{ marginTop: 16 }}>{t("library.folder")}<span className="mono ltr">{libraryRoot}</span></div>}

      {renaming && <RenameModal item={renaming} onClose={() => setRenaming(null)} onSave={(name) => run(() => call("library_rename", renaming.id, name)).then(() => setRenaming(null))} />}
      {deleting && (
        <Modal
          title={t("library.deleteTitle")}
          onClose={() => setDeleting(null)}
          footer={
            <>
              <Button onClick={() => setDeleting(null)}>{t("common.cancel")}</Button>
              <Button
                variant="danger"
                solid
                icon={<Trash2 size={15} />}
                onClick={() =>
                  run(() => call("library_delete", deleting.id)).then(() => {
                    toast(t("library.deleted"));
                    setDeleting(null);
                  })
                }
              >
                {t("common.delete")}
              </Button>
            </>
          }
        >
          <p style={{ margin: 0 }}>{t("library.deleteBody", { name: deleting.display_name, size: fmtBytes(deleting.size) })}</p>
        </Modal>
      )}
    </div>
  );
}

function RenameModal({ item, onClose, onSave }: { item: LibraryItem; onClose: () => void; onSave: (name: string) => void }) {
  const { t } = useI18n();
  const [name, setName] = useState(item.display_name);
  return (
    <Modal
      title={t("library.renameTitle")}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" onClick={() => onSave(name)}>{t("common.save")}</Button>
        </>
      }
    >
      <input className="input" style={{ width: "100%" }} autoFocus value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && onSave(name)} />
    </Modal>
  );
}
