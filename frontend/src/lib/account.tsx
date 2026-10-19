import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import type { Me } from "./types";

interface Account {
  me: Me | null; loading: boolean; refresh: () => Promise<Me | null>;
  login: (b: { email: string; password: string; code?: string }) => Promise<Me>;
  signup: (b: { email: string; name: string; password: string; organization: string; accept_terms: boolean }) => Promise<Me>;
  logout: () => Promise<void>; can: (perm: string) => boolean;
  authOpen: null | "login" | "signup"; openAuth: (mode: "login" | "signup") => void; closeAuth: () => void;
}
const Ctx = createContext<Account | null>(null);

export function AccountProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [authOpen, setAuthOpen] = useState<null | "login" | "signup">(null);

  const refresh = useCallback(async () => {
    try { const m = await api.get<Me>("/me"); setMe(m); return m; }
    catch (e) { if (e instanceof ApiError && e.status === 401) setMe(null); return null; }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const on = () => setMe(null);
    window.addEventListener("aidap:unauthenticated", on);
    return () => window.removeEventListener("aidap:unauthenticated", on);
  }, []);

  const value = useMemo<Account>(() => ({
    me, loading, refresh, authOpen,
    openAuth: setAuthOpen, closeAuth: () => setAuthOpen(null),
    login: async (b) => { const r = await api.post<{ me: Me }>("/auth/login", b); setMe(r.me); return r.me; },
    signup: async (b) => { const r = await api.post<{ me: Me }>("/auth/signup", b); setMe(r.me); return r.me; },
    logout: async () => { try { await api.post("/auth/logout"); } finally { setMe(null); } },
    can: (p) => !!me?.permissions.includes(p),
  }), [me, loading, refresh, authOpen]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAccount(): Account {
  const c = useContext(Ctx);
  if (!c) throw new Error("AccountProvider missing");
  return c;
}
