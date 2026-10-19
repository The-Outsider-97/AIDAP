import { useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction, useTheme } from "../../lib/hooks";
import { CopyButton, Field, Modal, PageHeader } from "../../components/ui";

export function Settings() {
  const { me, refresh, can } = useAccount();
  const [theme, toggle] = useTheme();
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [pwErr, setPwErr] = useState("");
  const [org, setOrg] = useState({ name: me?.tenant.name ?? "", retention_days: me?.tenant.retention_days ?? "", review_sla_hours: me?.tenant.settings?.review_sla_hours ?? 72 });
  const [orgErr, setOrgErr] = useState("");
  const [mfa, setMfa] = useState<null | { secret: string; uri: string }>(null);
  const [code, setCode] = useState("");
  const [mfaErr, setMfaErr] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [disable, setDisable] = useState<null | { code: string; password: string }>(null);
  const { busy, run: act } = useAction();
  if (!me) return null;
  const canRetention = me.plan.features.includes("configurable_retention");
  return (
    <>
      <PageHeader title="Settings" sub={`${me.user.email} · ${me.role} in ${me.tenant.name}`} />
      <div className="grid g2" style={{ alignItems: "start" }}>
        <div className="card form">
          <h3>Password</h3>
          <Field label="Current password"><input type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
          <Field label="New password" hint="At least 12 characters. Other sessions are signed out."><input type="password" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
          {pwErr && <div className="alert error" role="alert">{pwErr}</div>}
          <button className="btn" disabled={busy || !pw.current_password || pw.new_password.length < 12} onClick={async () => { setPwErr("");
            if (await act(() => api.post("/auth/password/change", pw), { ok: "Password changed", onError: (e) => setPwErr(e.fields.new_password ?? e.message) })) { setPw({ current_password: "", new_password: "" }); await refresh(); } }}>Change password</button>
        </div>
        <div className="card">
          <h3>Two-factor authentication</h3>
          <p className="muted small">Protect your account with a time-based code from an authenticator app.</p>
          {me.mfa_enabled ? (
            <div className="stack"><div className="alert ok">Two-factor authentication is on.</div><button className="btn danger" onClick={() => setDisable({ code: "", password: "" })}>Turn off…</button></div>
          ) : (
            <button className="btn primary" disabled={busy} onClick={async () => { setMfaErr(""); setCode(""); const r = await act(() => api.post("/auth/mfa/setup")); if (r) setMfa(r); }}>Set up two-factor</button>)}
        </div>
        {can("tenant.delete") || me.role === "owner" || me.role === "admin" ? (
          <div className="card form">
            <h3>Organization</h3>
            <Field label="Name"><input value={org.name} onChange={(e) => setOrg({ ...org, name: e.target.value })} /></Field>
            <Field label="Evidence retention (days)" hint={canRetention ? "Leave empty to use your plan’s default." : `Your ${me.plan.name} plan keeps evidence for ${me.plan.evidence_retention_days} days. Configurable retention is a Business feature.`}>
              <input type="number" min={1} max={3650} disabled={!canRetention} value={org.retention_days ?? ""} onChange={(e) => setOrg({ ...org, retention_days: e.target.value as any })} /></Field>
            <Field label="Review target (hours)" hint="Open reviews older than this are flagged in Insights and raise one alert."><input type="number" min={1} max={720} value={org.review_sla_hours} onChange={(e) => setOrg({ ...org, review_sla_hours: e.target.value as any })} /></Field>
            {orgErr && <div className="alert error" role="alert">{orgErr}</div>}
            <button className="btn" disabled={busy} onClick={async () => { setOrgErr("");
              const body: Record<string, unknown> = { name: org.name, review_sla_hours: Number(org.review_sla_hours) || 72 }; if (canRetention) body.retention_days = org.retention_days === "" ? null : Number(org.retention_days);
              if (await act(() => api.patch("/tenant", body), { ok: "Saved", onError: (e) => setOrgErr(Object.values(e.fields)[0] ?? e.message) })) await refresh(); }}>Save</button>
            {me.role === "owner" && (<>
              <h3 style={{ marginTop: 22 }}>Your data</h3>
              <p className="small">A JSON copy of your organization’s records: runs, decisions, reviews, projects, settings and the audit trail. Uploaded content, evidence bundles and credentials are not included.</p>
              <a className="btn" href={api.url("/account/export")}>Export organization data</a>
            </>)}
          </div>) : null}
        <div className="card">
          <h3>Appearance</h3>
          <button className="btn" onClick={toggle}>{theme === "dark" ? "Use the light theme" : "Use the dark theme"}</button>
          {me.memberships.length > 1 && (<><h3 style={{ marginTop: 22 }}>Switch workspace</h3>
            <div className="stack">{me.memberships.map((m) => <button key={m.tenant_id} className="btn" disabled={m.current || busy} onClick={async () => { if (await act(() => api.post("/me/switch-tenant", { tenant_id: m.tenant_id }))) { await refresh(); window.location.assign("/app"); } }}>{m.tenant_name} · {m.role}{m.current ? " (current)" : ""}</button>)}</div></>)}
        </div>
      </div>
      {mfa && (
        <Modal title="Set up two-factor" onClose={() => setMfa(null)}>
          <div className="form">
            <p className="small">Add this key to your authenticator app (choose “enter a setup key”), then enter the 6-digit code it shows.</p>
            <pre style={{ overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}>{mfa.secret}</pre>
            <div className="row"><CopyButton text={mfa.secret} /><a className="small" href={mfa.uri}>Open in an authenticator app</a></div>
            <Field label="6-digit code" error={mfaErr}><input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
            <button className="btn primary" disabled={busy || code.length < 6} onClick={async () => { setMfaErr("");
              const r = await act(() => api.post("/auth/mfa/enable", { code }), { onError: (e) => setMfaErr(e.message) });
              if (r) { setMfa(null); setRecovery(r.recovery_codes); await refresh(); } }}>Turn on</button>
          </div>
        </Modal>)}
      {recovery && (
        <Modal title="Save your recovery codes" onClose={() => setRecovery(null)}>
          <div className="stack"><div className="alert warn">Each code works once if you lose your authenticator. They are shown only now.</div>
            <pre>{recovery.join("\n")}</pre><div className="row"><CopyButton text={recovery.join("\n")} /><button className="btn" onClick={() => setRecovery(null)}>I saved them</button></div></div>
        </Modal>)}
      {disable && (
        <Modal title="Turn off two-factor" onClose={() => setDisable(null)}>
          <div className="form"><Field label="Current code"><input value={disable.code} onChange={(e) => setDisable({ ...disable, code: e.target.value })} inputMode="numeric" /></Field>
            <Field label="Password"><input type="password" value={disable.password} onChange={(e) => setDisable({ ...disable, password: e.target.value })} autoComplete="current-password" /></Field>
            <button className="btn danger" disabled={busy || disable.code.length < 6 || !disable.password} onClick={async () => { if (await act(() => api.post("/auth/mfa/disable", disable), { ok: "Two-factor turned off" })) { setDisable(null); await refresh(); } }}>Turn off</button></div>
        </Modal>)}
    </>
  );
}
