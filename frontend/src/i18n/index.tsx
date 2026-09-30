import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ar } from "./ar";
import { en, type TKey } from "./en";
import type { Lang, Localized } from "../lib/types";

const dicts = { ar, en };

export function systemLang(): Lang {
  return (navigator.language || "en").toLowerCase().startsWith("ar") ? "ar" : "en";
}

interface I18n {
  lang: Lang;
  dir: "rtl" | "ltr";
  setLang: (l: Lang) => void;
  t: (key: TKey, params?: Record<string, string | number>) => string;
  loc: (v: Localized | undefined | null) => string;
  fmtBytes: (n: number | null | undefined) => string;
  fmtNumber: (n: number) => string;
  fmtDate: (iso: string | number) => string;
  fmtDuration: (seconds: number | null | undefined) => string;
}

const Ctx = createContext<I18n | null>(null);

export function I18nProvider({ initial, children }: { initial: Lang; children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(initial);
  const dir = lang === "ar" ? "rtl" : "ltr";

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = dir;
  }, [lang, dir]);

  const t = useCallback(
    (key: TKey, params?: Record<string, string | number>) => {
      let s: string = dicts[lang][key] ?? en[key] ?? key;
      if (params) for (const [k, v] of Object.entries(params)) s = s.split(`{${k}}`).join(String(v));
      return s;
    },
    [lang],
  );

  const value = useMemo<I18n>(() => {
    const locale = lang === "ar" ? "ar-EG" : "en-US";
    const nf = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
    const units = lang === "ar" ? ["بايت", "ك.ب", "م.ب", "غ.ب", "ت.ب"] : ["B", "KB", "MB", "GB", "TB"];
    return {
      lang,
      dir,
      setLang,
      t,
      loc: (v) => (v ? v[lang] || v.en : ""),
      fmtNumber: (n) => nf.format(n),
      fmtBytes: (n) => {
        if (n === null || n === undefined || Number.isNaN(n)) return "—";
        let i = 0;
        let v = n;
        while (v >= 1024 && i < units.length - 1) {
          v /= 1024;
          i++;
        }
        return `${nf.format(v)} ${units[i]}`;
      },
      fmtDate: (iso) =>
        new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
          typeof iso === "number" ? new Date(iso * 1000) : new Date(iso),
        ),
      fmtDuration: (s) => {
        if (s === null || s === undefined || !Number.isFinite(s)) return "—";
        const sec = Math.max(0, Math.round(s));
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        const r = sec % 60;
        const pad = (x: number) => String(x).padStart(2, "0");
        const txt = h ? `${h}:${pad(m)}:${pad(r)}` : `${m}:${pad(r)}`;
        return lang === "ar" ? `⁦${txt}⁩` : txt;
      },
    };
  }, [lang, dir, t]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n outside provider");
  return v;
}
