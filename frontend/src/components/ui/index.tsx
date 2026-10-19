import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../../lib/api";
import type { Decision, Severity } from "../../lib/types";
import { Link } from "../../lib/router";
import { useToast } from "../../lib/hooks";

const GLYPH: Record<string, string> = { pass: "✓", review: "!", quarantine: "■", block: "✕" };
export const DECISION_TEXT: Record<string, string> = {
  pass: "Pass", review: "Review", quarantine: "Quarantine", block: "Block",
};
export const DECISION_MEANING: Record<string, string> = {
  pass: "Safe to release to the intended destination.",
  review: "Held until a person approves an exception, rejects it, or the input is repaired.",
  quarantine: "Isolated. Content access is restricted, purpose-gated and logged.",
  block: "Must not be used for this purpose.",
};

export function DecisionBadge({ decision, big, state }: { decision?: Decision | null; big?: boolean; state?: string }) {
  if (!decision) {
    return <span className={`dec none${big ? " big" : ""}`}>{state ? state.replace("_", " ") : "pending"}</span>;
  }
  return (
    <span className={`dec ${decision}${big ? " big" : ""}`} title={DECISION_MEANING[decision]}>
      <span aria-hidden>{GLYPH[decision]}</span>{DECISION_TEXT[decision]}
    </span>
  );
}
export const SeverityBadge = ({ severity }: { severity: Severity | string }) => <span className={`sev ${severity}`}>{severity}</span>;
export const StateDot = ({ state }: { state: string }) => <span className={`state ${state}`}>{state.replaceAll("_", " ")}</span>;

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <div className="center" role="status"><span className="spin" /><span className="sr">{label}</span></div>;
}

export function ErrorBox({ error, retry }: { error: ApiError | Error | string; retry?: () => void }) {
  const msg = typeof error === "string" ? error : error.message;
  const id = error instanceof ApiError && error.requestId ? ` (request ${error.requestId})` : "";
  return (
    <div className="alert error" role="alert">
      {msg}<span className="faint small">{id}</span>
      {retry && <> <button className="linkbtn" onClick={retry}>Try again</button></>}
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="empty"><b>{title}</b>{children}{action && <div style={{ marginTop: 14 }}>{action}</div>}</div>;
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-h">
      <div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("input,select,textarea,button:not(.x)");
    first?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && ref.current) {
        const f = [...ref.current.querySelectorAll<HTMLElement>("a[href],button:not(:disabled),input,select,textarea")].filter((x) => x.offsetParent !== null);
        if (!f.length) return;
        const a = f[0], z = f[f.length - 1];
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
        else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
      }
    };
    document.addEventListener("keydown", key);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", key); document.body.style.overflow = ""; prev?.focus(); };
  }, [onClose]);
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={id} ref={ref}>
        <button className="iconbtn x" onClick={onClose} aria-label="Close">✕</button>
        <h2 id={id}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Confirm({ title, children, confirm, danger, busy, onYes, onNo }: {
  title: string; children: ReactNode; confirm: string; danger?: boolean; busy?: boolean; onYes: () => void; onNo: () => void;
}) {
  return (
    <Modal title={title} onClose={onNo}>
      <div className="stack">{children}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onNo}>Cancel</button>
          <button className={`btn ${danger ? "danger" : "primary"}`} onClick={onYes} disabled={busy}>{busy ? "Working…" : confirm}</button>
        </div>
      </div>
    </Modal>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={t.id === value} onClick={() => onChange(t.id)}>{t.label}</button>
      ))}
    </div>
  );
}

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <label className="f">
      {label}
      {children}
      {hint && <span className="hint">{hint}</span>}
      {error && <span className="err" role="alert">{error}</span>}
    </label>
  );
}

export function Meter({ value, label }: { value: number | null | undefined; label?: string }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  return (
    <div className={`meter${v >= 1 ? " full" : v >= 0.8 ? " warn" : ""}`} role="progressbar" aria-valuenow={Math.round(v * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <i style={{ width: `${v * 100}%` }} />
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const { push } = useToast();
  const [done, setDone] = useState(false);
  return (
    <button className="btn sm" type="button" onClick={async () => {
      try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }
      catch { push("error", "Copy is not available in this browser."); }
    }}>{done ? "Copied" : label}</button>
  );
}

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (o: number) => void }) {
  if (total <= limit) return null;
  return (
    <div className="row between" style={{ marginTop: 12 }}>
      <span className="muted small">{offset + 1}–{Math.min(offset + limit, total)} of {total}</span>
      <div className="row">
        <button className="btn sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Previous</button>
        <button className="btn sm" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next</button>
      </div>
    </div>
  );
}

export const Digest = ({ value }: { value?: string | null }) =>
  value ? <code title={value}>{value.replace("sha256:", "").slice(0, 16)}…</code> : <span className="faint">—</span>;

export function Kpi({ value, label, to }: { value: ReactNode; label: string; to?: string }) {
  const inner = <div className="kpi"><b>{value}</b><span>{label}</span></div>;
  return <div className="card tight">{to ? <Link to={to} style={{ color: "inherit", textDecoration: "none" }}>{inner}</Link> : inner}</div>;
}

export function Icon({ name }: { name: "shield" | "scan" | "audit" | "flow" | "lock" | "plug" | "eye" | "bolt" | "doc" }) {
  const p: Record<string, string> = {
    shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z M9 12l2 2 4-4",
    scan: "M4 8V5a1 1 0 011-1h3M20 8V5a1 1 0 00-1-1h-3M4 16v3a1 1 0 001 1h3M20 16v3a1 1 0 01-1 1h-3M7 12h10",
    audit: "M6 3h9l4 4v14H6z M14 3v5h5 M9 13h6 M9 17h6",
    flow: "M5 6h4v4H5z M15 14h4v4h-4z M9 8h3a3 3 0 013 3v3",
    lock: "M7 11V8a5 5 0 0110 0v3 M5 11h14v10H5z",
    plug: "M9 3v5 M15 3v5 M6 8h12v4a6 6 0 01-12 0z M12 18v3",
    eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z M12 9a3 3 0 100 6 3 3 0 000-6z",
    bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
    doc: "M6 3h9l4 4v14H6z M9 12h6 M9 16h4",
  };
  return <span className="ico" aria-hidden><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={p[name]} /></svg></span>;
}
