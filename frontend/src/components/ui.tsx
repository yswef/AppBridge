import { AlertTriangle, CheckCircle2, Info, Search, X, XCircle } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { useI18n } from "../i18n";
import type { ApiError } from "../lib/types";

export function Card({ children, className = "", ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`card ${className}`} {...rest}>
      {children}
    </div>
  );
}

type Variant = "default" | "primary" | "danger" | "ghost";
export function Button({
  variant = "default",
  size,
  icon,
  loading,
  children,
  className = "",
  solid,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm";
  icon?: ReactNode;
  loading?: boolean;
  solid?: boolean;
}) {
  const cls = ["btn", variant !== "default" ? variant : "", size ?? "", !children ? "icon" : "", solid ? "solid" : "", className]
    .filter(Boolean)
    .join(" ");
  return (
    <button className={cls} disabled={loading || rest.disabled} {...rest}>
      {loading ? <span className="spinner" /> : icon}
      {children}
    </button>
  );
}

export function Badge({ tone, children, live }: { tone?: "ok" | "warn" | "err" | "info" | "accent"; children: ReactNode; live?: boolean }) {
  return (
    <span className={`badge ${tone ?? ""}`}>
      {live !== undefined && <span className={`dot ${live ? "live" : ""}`} />}
      {children}
    </span>
  );
}

export function Progress({ value, tone, indeterminate }: { value: number; tone?: "ok" | "err"; indeterminate?: boolean }) {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <div className={`progress ${tone ?? ""} ${indeterminate ? "indeterminate" : ""}`} role="progressbar" aria-valuenow={pct}>
      <div style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label?: string }) {
  return <button className={`switch ${on ? "on" : ""}`} role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)} />;
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="segmented" role="tablist">
      {options.map((o) => (
        <button key={o.value} className={o.value === value ? "on" : ""} role="tab" aria-selected={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function SearchInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const { t } = useI18n();
  return (
    <label className="search">
      <Search size={16} />
      <input className="input" value={value} placeholder={placeholder ?? t("common.search")} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

export function Alert({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: "info" | "warn" | "err" | "ok";
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const Icon = tone === "err" ? XCircle : tone === "warn" ? AlertTriangle : tone === "ok" ? CheckCircle2 : Info;
  return (
    <div className={`alert ${tone}`}>
      <Icon size={18} />
      <div style={{ flex: 1, minWidth: 0 }}>
        {title && <div className="title">{title}</div>}
        {children && <div className="muted">{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function ErrorBox({ error, tone = "err", action }: { error: ApiError; tone?: "err" | "warn"; action?: ReactNode }) {
  const { loc, t } = useI18n();
  return (
    <Alert tone={tone} title={loc(error.message)} action={action}>
      {loc(error.hint) && <p>{loc(error.hint)}</p>}
      {error.detail && (
        <details className="tech">
          <summary>{t("common.details")}</summary>
          <pre>{error.detail}</pre>
        </details>
      )}
    </Alert>
  );
}

export function EmptyState({ icon, title, body, action }: { icon: ReactNode; title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="art">{icon}</div>
      <h2>{title}</h2>
      {body && <p>{body}</p>}
      {action && <div className="row" style={{ marginTop: 8 }}>{action}</div>}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true">
        <div className="modal-head">
          <h2>{title}</h2>
          <Button variant="ghost" size="sm" icon={<X size={18} />} onClick={onClose} aria-label="close" />
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function AppIcon({ src, name, size }: { src?: string | null; name: string; size?: "lg" }) {
  const letter = (name || "?").replace(/^com\.|^net\.|^org\./, "").charAt(0).toUpperCase();
  let hash = 0;
  for (const c of name) hash = (hash * 31 + c.charCodeAt(0)) | 0;
  const hue = Math.abs(hash) % 360;
  return (
    <div className={`app-icon ${size ?? ""}`} style={src ? { background: "var(--surface-2)" } : { background: `linear-gradient(135deg, hsl(${hue} 70% 55%), hsl(${(hue + 40) % 360} 70% 45%))` }}>
      {src ? <img src={src} alt="" draggable={false} /> : letter}
    </div>
  );
}
