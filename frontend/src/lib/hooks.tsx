import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "./api";

export interface Async<T> { data: T | null; error: ApiError | null; loading: boolean; reload: () => void; set: (v: T | null) => void }

// Short-lived response cache: a page that was visited a moment ago renders at once and refreshes in the background.
// Entries are keyed by the request function and its dependencies, expire after 30 s and are cleared on sign-out.
const CACHE = new Map<string, { at: number; data: unknown }>();
const MAX_AGE_MS = 30_000;
export const clearAsyncCache = () => CACHE.clear();
const cacheKey = (fn: unknown, deps: unknown[]) => { try { return `${String(fn)}|${JSON.stringify(deps)}`; } catch { return ""; } };
const fromCache = <T,>(key: string): T | null => {
  const hit = key ? CACHE.get(key) : undefined;
  return hit && Date.now() - hit.at < MAX_AGE_MS ? (hit.data as T) : null;
};
const toCache = (key: string, data: unknown) => {
  if (!key) return;
  CACHE.set(key, { at: Date.now(), data });
  if (CACHE.size > 80) CACHE.delete(CACHE.keys().next().value as string);
};

/** Fetch on mount and whenever ``deps`` change; ignores stale responses. */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[] = []): Async<T> {
  const key = cacheKey(fn, deps);
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean }>(() => ({ data: fromCache<T>(key), error: null, loading: true }));
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    const ac = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    fnRef.current(ac.signal).then(
      (data) => { if (!ac.signal.aborted) { toCache(key, data); setState({ data, error: null, loading: false }); } },
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

const THEME_KEY = "aidap-theme";
const readTheme = () => document.documentElement.dataset.theme === "light" ? "light" : "dark";

/** Apply a theme with a short colour transition (skipped when the visitor prefers reduced motion). */
function applyTheme(next: string, persist: boolean) {
  const root = document.documentElement;
  const calm = !matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (calm) { root.classList.add("theme-switching"); window.setTimeout(() => root.classList.remove("theme-switching"), 320); }
  root.dataset.theme = next;
  const meta = document.querySelector('meta[name="theme-color"]');
  meta?.setAttribute("content", next === "dark" ? "#050505" : "#f6f7f9");
  if (persist) { try { localStorage.setItem(THEME_KEY, next); } catch { /* storage may be unavailable */ } }
  window.dispatchEvent(new Event("aidap:theme"));
}

export function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState(readTheme);
  useEffect(() => {
    const sync = () => setTheme(readTheme());
    const media = matchMedia("(prefers-color-scheme: light)");
    const os = () => { let chosen: string | null = null; try { chosen = localStorage.getItem(THEME_KEY); } catch { /* ignore */ } if (!chosen) applyTheme(media.matches ? "light" : "dark", false); };
    const storage = (e: StorageEvent) => { if (e.key === THEME_KEY && e.newValue) applyTheme(e.newValue === "light" ? "light" : "dark", false); };
    window.addEventListener("aidap:theme", sync);
    window.addEventListener("storage", storage);
    media.addEventListener("change", os);
    return () => { window.removeEventListener("aidap:theme", sync); window.removeEventListener("storage", storage); media.removeEventListener("change", os); };
  }, []);
  const toggle = useCallback(() => applyTheme(readTheme() === "dark" ? "light" : "dark", true), []);
  return [theme, toggle];
}
