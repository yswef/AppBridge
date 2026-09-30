import { FileArchive, FolderOpen } from "lucide-react";
import { useState } from "react";
import { useToast } from "../components/toast";
import { Button, Card, Segmented, Switch } from "../components/ui";
import { useI18n } from "../i18n";
import { ApiException, call } from "../lib/api";
import { useStore } from "../lib/store";
import type { Settings } from "../lib/types";

export function SettingsPage() {
  const { t, loc } = useI18n();
  const { settings, updateSettings } = useStore();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!settings) return null;

  const save = async (c: Partial<Settings>) => {
    try {
      await updateSettings(c);
    } catch (e) {
      if (e instanceof ApiException) toast(loc(e.error.message), "err");
    }
  };

  const chooseLibrary = async () => {
    setBusy(true);
    try {
      const r = await call<Settings | null>("choose_library_dir");
      if (r) {
        await updateSettings({});
        toast(t("settings.saved"));
      }
    } catch (e) {
      if (e instanceof ApiException) toast(loc(e.error.message), "err");
    } finally {
      setBusy(false);
    }
  };

  const exportLogs = async () => {
    try {
      const p = await call<string | null>("export_logs");
      if (p) toast(t("settings.logsSaved", { path: p }));
    } catch (e) {
      if (e instanceof ApiException) toast(loc(e.error.message), "err");
    }
  };

  return (
    <div className="page" style={{ maxWidth: 820 }}>
      <div className="page-header">
        <h1>{t("settings.title")}</h1>
      </div>

      <section className="settings-section">
        <h2>{t("settings.appearance")}</h2>
        <Card>
          <div className="setting">
            <div className="label">{t("settings.language")}</div>
            <Segmented
              value={settings.language}
              onChange={(v) => save({ language: v })}
              options={[
                { value: "system", label: t("settings.lang.system") },
                { value: "ar", label: "العربية" },
                { value: "en", label: "English" },
              ]}
            />
          </div>
          <div className="setting">
            <div className="label">{t("settings.theme")}</div>
            <Segmented
              value={settings.theme}
              onChange={(v) => save({ theme: v })}
              options={[
                { value: "system", label: t("theme.system") },
                { value: "light", label: t("theme.light") },
                { value: "dark", label: t("theme.dark") },
              ]}
            />
          </div>
        </Card>
      </section>

      <section className="settings-section">
        <h2>{t("settings.library")}</h2>
        <Card>
          <div className="setting">
            <div className="label">
              <div>{t("settings.libraryDir")}</div>
              <div className="mono ltr truncate" style={{ textAlign: "start" }}>{settings.library_dir}</div>
              <div className="hint">{t("settings.libraryHint")}</div>
            </div>
            <Button size="sm" icon={<FolderOpen size={15} />} onClick={() => call("open_path", settings.library_dir).catch(() => {})}>
              {t("common.openFolder")}
            </Button>
            <Button size="sm" loading={busy} onClick={chooseLibrary}>
              {t("settings.change")}
            </Button>
          </div>
        </Card>
      </section>

      <section className="settings-section">
        <h2>{t("settings.install")} · {t("settings.export")}</h2>
        <Card>
          <div className="setting">
            <div className="label">{t("settings.verifyBeforeInstall")}</div>
            <Switch on={settings.verify_before_install} onChange={(v) => save({ verify_before_install: v })} />
          </div>
          <div className="setting">
            <div className="label">{t("settings.showSystem")}</div>
            <Switch on={settings.show_system_apps} onChange={(v) => save({ show_system_apps: v })} />
          </div>
          <div className="setting">
            <div className="label">{t("settings.includeBat")}</div>
            <Switch on={settings.include_install_bat} onChange={(v) => save({ include_install_bat: v })} />
          </div>
          <div className="setting">
            <div className="label">{t("settings.splitSize")}</div>
            <input
              className="input ltr"
              type="number"
              min={0}
              step={512}
              style={{ width: 120 }}
              value={settings.split_size_mb}
              onChange={(e) => save({ split_size_mb: Math.max(0, Number(e.target.value) || 0) })}
            />
          </div>
        </Card>
      </section>

      <section className="settings-section">
        <h2>{t("settings.support")}</h2>
        <Card>
          <div className="setting">
            <div className="label">
              <div>{t("settings.exportLogs")}</div>
              <div className="hint">{t("settings.logsHint")}</div>
            </div>
            <Button size="sm" icon={<FileArchive size={15} />} onClick={exportLogs}>
              {t("settings.exportLogs")}
            </Button>
          </div>
        </Card>
      </section>
    </div>
  );
}
