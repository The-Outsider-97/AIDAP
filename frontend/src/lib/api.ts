export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, any> = {}, public requestId = "") {
    super(message);
  }
  /** Field-level problems from a 422, keyed by field name. */
  get fields(): Record<string, string> { return (this.details.fields as Record<string, string>) ?? {}; }
}

const BASE = "/api/v1";

function cookie(name: string): string {
  return document.cookie.split("; ").find((c) => c.startsWith(name + "="))?.slice(name.length + 1) ?? "";
}

type Opts = { body?: unknown; query?: Record<string, string | number | boolean | undefined | null>; form?: FormData; signal?: AbortSignal };

async function request<T>(method: string, path: string, o: Opts = {}): Promise<T> {
  let url = BASE + path;
  if (o.query) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(o.query)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
    const s = q.toString();
    if (s) url += (url.includes("?") ? "&" : "?") + s;
  }
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (o.form) body = o.form;
  else if (o.body !== undefined) { body = JSON.stringify(o.body); headers["Content-Type"] = "application/json"; }
  if (method !== "GET") { const t = decodeURIComponent(cookie("aidap_csrf")); if (t) headers["X-CSRF-Token"] = t; }
  let res: Response;
  try { res = await fetch(url, { method, headers, body, credentials: "same-origin", signal: o.signal }); }
  catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network", "Could not reach the AIDAP server. Check your connection and try again.");
  }
  const ctype = res.headers.get("content-type") ?? "";
  const data = ctype.includes("json") ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    const err = data?.error ?? {};
    const e = new ApiError(res.status, err.code ?? "http_error", err.message ?? res.statusText, err.details ?? {}, data?.request_id ?? "");
    if (res.status === 401 && !path.startsWith("/auth/")) window.dispatchEvent(new CustomEvent("aidap:unauthenticated"));
    throw e;
  }
  return data as T;
}

export const api = {
  get: <T = any>(path: string, query?: Opts["query"], signal?: AbortSignal) => request<T>("GET", path, { query, signal }),
  post: <T = any>(path: string, body: unknown = {}) => request<T>("POST", path, { body }),
  put: <T = any>(path: string, body: unknown = {}) => request<T>("PUT", path, { body }),
  patch: <T = any>(path: string, body: unknown = {}) => request<T>("PATCH", path, { body }),
  del: <T = any>(path: string) => request<T>("DELETE", path),
  upload: <T = any>(path: string, form: FormData) => request<T>("POST", path, { form }),
  /** A same-origin GET URL the browser can download directly (the session cookie authenticates it). */
  url: (path: string, query?: Record<string, string>) => BASE + path + (query ? "?" + new URLSearchParams(query).toString() : ""),
};
