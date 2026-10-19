import { useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction, useAsync } from "../../lib/hooks";
import { ago, fmtDate, titleCase } from "../../lib/format";
import type { Project } from "../../lib/types";
import { Confirm, CopyButton, Empty, ErrorBox, Field, Meter, Modal, PageHeader, Spinner } from "../../components/ui";

const ROLES = ["admin", "security", "reviewer", "analyst", "viewer"];
const ROLE_HELP: Record<string, string> = {
  admin: "Manage everything except billing ownership.", security: "Resolve privacy and safety reviews; access quarantine.", reviewer: "Resolve quality and freshness reviews.",
  analyst: "Submit runs and read results.", viewer: "Read-only.",
};

export function Team() {
  const { me, can } = useAccount();
  const q = useAsync(async () => {
    const [members, invites, projects] = await Promise.all([api.get<any[]>("/members"), api.get<any[]>("/invitations"), api.get<Project[]>("/projects")]);
    return { members, invites, projects };
  }, []);
  const [inv, setInv] = useState<{ email: string; role: string } | null>(null);
  const [link, setLink] = useState("");
  const [err, setErr] = useState("");
  const [remove, setRemove] = useState<any | null>(null);
  const { busy, run: act } = useAction();
  const seats = me?.plan.seats ?? 0;
  const manage = can("members.manage");
  return (
    <>
      <PageHeader title="Team" sub={`${q.data?.members.length ?? "…"} of ${seats} seats used on the ${me?.plan.name} plan.`} actions={manage && <button className="btn primary" onClick={() => setInv({ email: "", role: "analyst" })}>Invite someone</button>} />
      {q.data && <div style={{ maxWidth: 360, marginBottom: 18 }}><Meter value={q.data.members.length / Math.max(1, seats)} label="Seats used" /></div>}
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : (
        <div className="stack lg">
          <div className="tw"><table><thead><tr><th>Member</th><th>Role</th><th>2FA</th><th>Last sign-in</th><th /></tr></thead>
            <tbody>{q.data.members.map((m) => (
              <tr key={m.id}><td><b>{m.name}</b><div className="faint small">{m.email}</div></td>
                <td>{m.role === "owner" || !manage || m.user_id === me?.user.id ? <span className="tag">{m.role}</span> : (
                  <select aria-label={`Role for ${m.email}`} style={{ maxWidth: 150 }} value={m.role} onChange={async (e) => { if (await act(() => api.patch(`/members/${m.id}`, { role: e.target.value, project_ids: m.project_ids }), { ok: "Role updated" })) q.reload(); }}>
                    {ROLES.map((r) => <option key={r}>{r}</option>)}</select>)}</td>
                <td>{m.mfa_enabled ? "On" : <span className="faint">Off</span>}</td><td className="small">{ago(m.last_login_at)}</td>
                <td className="right">{manage && m.role !== "owner" && m.user_id !== me?.user.id && <button className="btn sm danger" onClick={() => setRemove(m)}>Remove</button>}</td></tr>))}</tbody></table></div>
          {q.data.invites.length > 0 && <div><h3>Pending invitations</h3><div className="tw"><table><tbody>{q.data.invites.map((i) => (
            <tr key={i.id}><td>{i.email}</td><td><span className="tag">{i.role}</span></td><td className="small">expires {fmtDate(i.expires_at)}</td>
              <td className="right">{manage && <button className="btn sm" onClick={async () => { if (await act(() => api.del(`/invitations/${i.id}`), { ok: "Invitation revoked" })) q.reload(); }}>Revoke</button>}</td></tr>))}</tbody></table></div></div>}
          <div className="card small"><h3>Roles</h3>{Object.entries(ROLE_HELP).map(([r, t]) => <div key={r}><b>{titleCase(r)}</b> — <span className="muted">{t}</span></div>)}
            <p className="muted" style={{ marginBottom: 0, marginTop: 8 }}>Baseline approval, policy publishing and exceptions follow segregation of duties: you cannot approve your own work when another eligible person exists.</p></div>
        </div>)}
      {inv && (
        <Modal title="Invite a teammate" onClose={() => setInv(null)}>
          <div className="form">
            <Field label="Email"><input type="email" value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} /></Field>
            <Field label="Role" hint={ROLE_HELP[inv.role]}><select value={inv.role} onChange={(e) => setInv({ ...inv, role: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></Field>
            {err && <div className="alert error">{err}</div>}
            <button className="btn primary" disabled={busy || !inv.email} onClick={async () => { setErr("");
              const r = await act(() => api.post("/invitations", { ...inv, project_ids: [] }), { onError: (e) => setErr(e.fields.email ?? e.message) });
              if (r) { setInv(null); setLink(r.token ? `${location.origin}/invite?token=${r.token}` : ""); q.reload(); } }}>Send invitation</button>
          </div>
        </Modal>)}
      {link && <Modal title="Invitation created" onClose={() => setLink("")}><div className="stack"><p>An email was sent. In development installations, the link is also shown here:</p><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{link}</pre><CopyButton text={link} /></div></Modal>}
      {remove && <Confirm title={`Remove ${remove.name}?`} danger confirm="Remove" busy={busy} onNo={() => setRemove(null)} onYes={async () => { if (await act(() => api.del(`/members/${remove.id}`), { ok: "Member removed" })) { setRemove(null); q.reload(); } }}><p>They lose access to this workspace immediately. Their past actions stay in the audit log.</p></Confirm>}
    </>
  );
}

const SCOPES: [string, string][] = [["runs:write", "Submit runs"], ["runs:read", "Read runs, findings, evidence"], ["deliveries:read", "Read deliveries"], ["policies:read", "Read profiles & policies"], ["usage:read", "Read usage"]];

export function ApiKeys() {
  const q = useAsync(() => api.get<any[]>("/api-keys"), []);
  const projects = useAsync(() => api.get<Project[]>("/projects"), []);
  const [edit, setEdit] = useState<any | null>(null);
  const [token, setToken] = useState("");
  const [err, setErr] = useState("");
  const [revoke, setRevoke] = useState<any | null>(null);
  const { busy, run: act } = useAction();
  return (
    <>
      <PageHeader title="API keys" sub="Use a key to submit inputs and read results from CI or your pipeline." actions={<button className="btn primary" onClick={() => setEdit({ name: "", scopes: ["runs:write", "runs:read"], project_ids: [], days: "" })}>Create key</button>} />
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !q.data.length ? <Empty title="No API keys" /> : (
        <div className="tw"><table><thead><tr><th>Name</th><th>Prefix</th><th>Scopes</th><th>Last used</th><th>Expires</th><th /></tr></thead>
          <tbody>{q.data.map((k) => (
            <tr key={k.id} style={k.revoked_at ? { opacity: 0.5 } : undefined}><td><b>{k.name}</b>{k.revoked_at && <span className="tag" style={{ marginLeft: 6 }}>revoked</span>}</td><td><code>{k.prefix}…</code></td>
              <td className="small">{k.scopes.join(", ")}{k.project_ids?.length ? <div className="faint">{k.project_ids.length} project(s)</div> : null}</td><td className="small">{k.last_used_at ? ago(k.last_used_at) : "never"}</td><td className="small">{k.expires_at ? fmtDate(k.expires_at) : "never"}</td>
              <td className="right">{!k.revoked_at && <button className="btn sm danger" onClick={() => setRevoke(k)}>Revoke</button>}</td></tr>))}</tbody></table></div>)}
      {edit && (
        <Modal title="Create an API key" onClose={() => setEdit(null)}>
          <div className="form">
            <Field label="Name"><input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} placeholder="e.g. CI pipeline" /></Field>
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}><legend className="small"><b>Scopes</b></legend>
              {SCOPES.map(([s, l]) => <label className="check" key={s}><input type="checkbox" checked={edit.scopes.includes(s)} onChange={(e) => setEdit({ ...edit, scopes: e.target.checked ? [...edit.scopes, s] : edit.scopes.filter((x: string) => x !== s) })} /><span><code>{s}</code> — {l}</span></label>)}</fieldset>
            <Field label="Limit to project" hint="Leave on “All projects” for full access."><select value={edit.project_ids[0] ?? ""} onChange={(e) => setEdit({ ...edit, project_ids: e.target.value ? [e.target.value] : [] })}><option value="">All projects</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
            <Field label="Expires in (days)" hint="Optional, up to 730."><input type="number" min={1} max={730} value={edit.days} onChange={(e) => setEdit({ ...edit, days: e.target.value })} /></Field>
            {err && <div className="alert error">{err}</div>}
            <button className="btn primary" disabled={busy || !edit.name.trim() || !edit.scopes.length} onClick={async () => { setErr("");
              const r = await act(() => api.post("/api-keys", { name: edit.name, scopes: edit.scopes, project_ids: edit.project_ids, expires_in_days: edit.days ? Number(edit.days) : null }), { onError: (e) => setErr(Object.values(e.fields)[0] ?? e.message) });
              if (r) { setEdit(null); setToken(r.token); q.reload(); } }}>Create key</button>
          </div>
        </Modal>)}
      {token && <Modal title="Copy your API key" onClose={() => setToken("")}><div className="stack"><div className="alert warn">This is the only time the key is shown. We store only a digest of it.</div><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{token}</pre><div className="row"><CopyButton text={token} /><button className="btn" onClick={() => setToken("")}>Done</button></div></div></Modal>}
      {revoke && <Confirm title={`Revoke “${revoke.name}”?`} danger confirm="Revoke" busy={busy} onNo={() => setRevoke(null)} onYes={async () => { if (await act(() => api.del(`/api-keys/${revoke.id}`), { ok: "Key revoked" })) { setRevoke(null); q.reload(); } }}><p>Anything using this key stops working immediately.</p></Confirm>}
    </>
  );
}
