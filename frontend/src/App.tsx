import { Info, Languages, Library, ListChecks, Moon, Settings as SettingsIcon, Smartphone, Sun, LayoutGrid } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import logo from "./logo.svg";
import { Button } from "./components/ui";
import { systemLang, useI18n } from "./i18n";
import type { TKey } from "./i18n/en";
import type { LibraryItem } from "./lib/types";
import { useStore } from "./lib/store";
import { InstallModal } from "./components/InstallModal";
import { AboutPage } from "./pages/About";
import { AppsPage } from "./pages/Apps";
import { DevicesPage } from "./pages/Devices";
import { LibraryPage } from "./pages/Library";
import { SettingsPage } from "./pages/Settings";
import { TasksPage } from "./pages/Tasks";

export type Page = "devices" | "apps" | "library" | "tasks" | "settings" | "about";

function useTheme() {
  const { settings } = useStore();
  const [systemDark, setSystemDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const fn = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);
  const pref = settings?.theme ?? "system";
  const dark = pref === "dark" || (pref === "system" && systemDark);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);
  return dark;
}

export function App() {
  const { t, lang, setLang } = useI18n();
  const { settings, updateSettings } = useStore();
  const [page, setPage] = useState<Page>("devices");
  const [serial, setSerial] = useState<string | null>(null);
  const [installing, setInstalling] = useState<LibraryItem | null>(null);
  const dark = useTheme();

  useEffect(() => {
    if (!settings) return;
    setLang(settings.language === "system" ? systemLang() : settings.language);
  }, [settings?.language, setLang, settings]);

  const nav: { id: Page; icon: ReactNode; label: TKey }[] = [
    { id: "devices", icon: <Smartphone size={18} />, label: "nav.devices" },
    { id: "apps", icon: <LayoutGrid size={18} />, label: "nav.apps" },
    { id: "library", icon: <Library size={18} />, label: "nav.library" },
    { id: "tasks", icon: <ListChecks size={18} />, label: "nav.tasks" },
    { id: "settings", icon: <SettingsIcon size={18} />, label: "nav.settings" },
    { id: "about", icon: <Info size={18} />, label: "nav.about" },
  ];

  const go = (p: Page) => setPage(p);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <img src={logo} alt="" />
          <div>
            <div className="name">{t("app.name")}</div>
            <div className="tag">{t("app.tagline")}</div>
          </div>
        </div>
        {nav.map((n) => (
          <button key={n.id} className={`nav-item ${page === n.id ? "active" : ""}`} onClick={() => go(n.id)}>
            {n.icon}
            <span>{t(n.label)}</span>
            <NavCount page={n.id} />
          </button>
        ))}
        <div className="sidebar-footer">
          <div className="row">
            <Button
              size="sm"
              icon={<Languages size={15} />}
              onClick={() => updateSettings({ language: lang === "ar" ? "en" : "ar" })}
              style={{ flex: 1 }}
            >
              {lang === "ar" ? "English" : "العربية"}
            </Button>
            <Button
              size="sm"
              icon={dark ? <Sun size={15} /> : <Moon size={15} />}
              aria-label={t("settings.theme")}
              onClick={() => updateSettings({ theme: dark ? "light" : "dark" })}
            />
          </div>
        </div>
      </aside>
      <main className="main">
        {page === "devices" && (
          <DevicesPage
            onBrowse={(s) => {
              setSerial(s);
              go("apps");
            }}
          />
        )}
        {page === "apps" && <AppsPage serial={serial} onSerial={setSerial} onNavigate={go} />}
        {page === "library" && <LibraryPage onNavigate={go} onInstall={setInstalling} />}
        {page === "tasks" && <TasksPage />}
        {page === "settings" && <SettingsPage />}
        {page === "about" && <AboutPage />}
      </main>
      {installing && (
        <InstallModal
          item={installing}
          onClose={() => setInstalling(null)}
          onStarted={() => {
            setInstalling(null);
            go("tasks");
          }}
        />
      )}
    </div>
  );
}

function NavCount({ page }: { page: Page }) {
  const { devices, activeJobs } = useStore();
  if (page === "tasks") return activeJobs.length ? <span className="count">{activeJobs.length}</span> : null;
  if (page === "devices") {
    const n = devices.filter((d) => d.state === "device").length;
    return n ? <span className="count">{n}</span> : null;
  }
  return null;
}
