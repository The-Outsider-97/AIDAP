import { createContext, useCallback, useContext, useEffect, useMemo, useState, type AnchorHTMLAttributes, type ReactNode } from "react";

interface Loc { path: string; search: string; hash: string }
interface Ctx extends Loc { navigate: (to: string, opts?: { replace?: boolean }) => void }

const RouterCtx = createContext<Ctx>({ path: "/", search: "", hash: "", navigate: () => {} });
const read = (): Loc => ({ path: window.location.pathname, search: window.location.search, hash: window.location.hash });

export function Router({ children }: { children: ReactNode }) {
  const [loc, setLoc] = useState<Loc>(read);
  useEffect(() => {
    const on = () => setLoc(read());
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
  const navigate = useCallback((to: string, opts?: { replace?: boolean }) => {
    const u = new URL(to, window.location.origin);
    if (u.origin !== window.location.origin) { window.location.assign(to); return; }
    const samePage = u.pathname === window.location.pathname && u.search === window.location.search;
    if (opts?.replace) window.history.replaceState(null, "", u.pathname + u.search + u.hash);
    else window.history.pushState(null, "", u.pathname + u.search + u.hash);
    setLoc(read());
    if (!samePage || !u.hash) window.scrollTo({ top: 0 });
    if (u.hash) requestAnimationFrame(() => document.getElementById(u.hash.slice(1))?.scrollIntoView({ behavior: "smooth" }));
  }, []);
  const value = useMemo(() => ({ ...loc, navigate }), [loc, navigate]);
  return <RouterCtx.Provider value={value}>{children}</RouterCtx.Provider>;
}

export const useRouter = () => useContext(RouterCtx);
export const useQuery = () => { const { search } = useRouter(); return useMemo(() => new URLSearchParams(search), [search]); };

export function Link({ to, onClick, ...rest }: { to: string } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  const { navigate } = useRouter();
  return (
    <a href={to} {...rest} onClick={(e) => {
      onClick?.(e);
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || rest.target === "_blank") return;
      e.preventDefault();
      navigate(to);
    }} />
  );
}

export interface RouteDef { path: string; render: (params: Record<string, string>) => ReactNode }

export function matchPath(pattern: string, path: string): Record<string, string> | null {
  const a = pattern.split("/").filter(Boolean), b = path.split("/").filter(Boolean);
  if (a.length !== b.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < a.length; i++) {
    if (a[i].startsWith(":")) params[a[i].slice(1)] = decodeURIComponent(b[i]);
    else if (a[i] !== b[i]) return null;
  }
  return params;
}

export function Routes({ routes, fallback }: { routes: RouteDef[]; fallback: ReactNode }) {
  const { path } = useRouter();
  for (const r of routes) {
    const m = matchPath(r.path, path);
    if (m) return <>{r.render(m)}</>;
  }
  return <>{fallback}</>;
}

export function Redirect({ to }: { to: string }) {
  const { navigate } = useRouter();
  useEffect(() => navigate(to, { replace: true }), [to, navigate]);
  return null;
}
