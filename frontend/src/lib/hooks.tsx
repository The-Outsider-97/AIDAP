import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "./api";

export interface Async<T> { data: T | null; error: ApiError | null; loading: boolean; reload: () => void; set: (v: T | null) => void }

/** Fetch on mount and whenever ``deps`` change; ignores stale responses. */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[] = []): Async<T> {
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean }>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    const ac = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    fnRef.current(ac.signal).then(
      (data) => !ac.signal.aborted && setState({ data, error: null, loading: false }),
      (e) => { if (!ac.signal.aborted) setState((s) => ({ data: s.data, error: e instanceof ApiError ? e : new ApiError(0, "error", String(e?.message ?? e)), loading: false })); },
    );
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const set = useCallback((v: T | null) => setState((s) => ({ ...s, data: v })), []);
  return { ...state, reload, set };
}

/** Poll while ``active(data)`` is true (e.g. a run that has not finished). */
export function usePolling(reload: () => void, active: boolean, ms = 1500) {
  useEffect(() => {
    if (!active) return;
    const t = setInterval(reload, ms);
    return () => clearInterval(t);
  }, [active, ms, reload]);
}

// ------------------------------------------------------------------ toasts
interface Toast { id: number; kind: "ok" | "error" | "info"; text: string }
const ToastCtx = createContext<{ push: (kind: Toast["kind"], text: string) => void }>({ push: () => {} });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((l) => [...l.slice(-3), { id, kind, text }]);
    setTimeout(() => setItems((l) => l.filter((t) => t.id !== id)), kind === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast toast--${t.kind}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/** Run an async action with a busy flag; errors become toasts unless ``onError`` handles them. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const { push } = useToast();
  const run = useCallback(async <T,>(fn: () => Promise<T>, o: { ok?: string; onError?: (e: ApiError) => void } = {}): Promise<T | undefined> => {
    setBusy(true);
    try {
      const r = await fn();
      if (o.ok) push("ok", o.ok);
      return r;
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, "error", String((e as Error)?.message ?? e));
      if (o.onError) o.onError(err); else push("error", err.message);
      return undefined;
    } finally { setBusy(false); }
  }, [push]);
  return { busy, run };
}

export function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? "dark");
  const toggle = useCallback(() => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("aidap-theme", next); } catch { /* storage may be unavailable */ }
    setTheme(next);
  }, [theme]);
  return [theme, toggle];
}
