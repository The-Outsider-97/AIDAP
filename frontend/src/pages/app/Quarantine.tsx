import { useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction, useAsync } from "../../lib/hooks";
import { Link, useRouter } from "../../lib/router";
import { ago, fmtDate } from "../../lib/format";
import { Empty, ErrorBox, Field, Modal, PageHeader, Spinner } from "../../components/ui";

interface Q { id: string; run_id: string; project_id: string; reason_codes: string[]; created_at: string; retain_until: string; state: string; last_accessed_by: string; last_accessed_at: string | null; disposed_by: string; disposed_at: string | null }

export function QuarantineList() {
  const { navigate } = useRouter();
  const [state, setState] = useState("held");
  const q = useAsync(() => api.get<Q[]>("/quarantine", { state, limit: 100 }), [state]);
  return (
    <>
      <PageHeader title="Quarantine" sub="Isolated inputs. Reading the content needs a stated purpose, is time-limited and is logged." />
      <div className="row" style={{ marginBottom: 14 }}><select style={{ maxWidth: 200 }} aria-label="State" value={state} onChange={(e) => setState(e.target.value)}>
        <option value="held">Held</option><option value="disposed">Disposed</option><option value="">All</option></select></div>
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !q.data.length ? <Empty title="Nothing in quarantine" /> : (
        <div className="tw"><table><thead><tr><th>Item</th><th>State</th><th>Reasons</th><th>Retained until</th><th>Last access</th></tr></thead>
          <tbody>{q.data.map((x) => (
            <tr key={x.id} className="click" onClick={() => navigate(`/app/quarantine/${x.id}`)}>
              <td><Link to={`/app/quarantine/${x.id}`} onClick={(e) => e.stopPropagation()}>{x.id}</Link><div className="faint small">{ago(x.created_at)}</div></td>
              <td><span className="tag">{x.state}</span></td><td className="small">{x.reason_codes.map((c) => <div key={c}><code>{c}</code></div>)}</td>
              <td className="small">{fmtDate(x.retain_until)}</td><td className="small">{x.last_accessed_by ? `${x.last_accessed_by} · ${ago(x.last_accessed_at)}` : "—"}</td></tr>))}</tbody></table></div>)}
    </>
  );
}

export function QuarantineDetail({ id }: { id: string }) {
  const { can } = useAccount();
  const q = useAsync(() => api.get<Q>(`/quarantine/${id}`), [id]);
  const [modal, setModal] = useState<null | "access" | "dispose">(null);
  const [purpose, setPurpose] = useState("");
  const [grant, setGrant] = useState<{ access_id: string; expires_at: string; window_minutes: number } | null>(null);
  const [dispose, setDispose] = useState({ action: "delete", comment: "" });
  const [err, setErr] = useState("");
  const { busy, run: act } = useAction();
  const x = q.data;
  if (q.error && !x) return <ErrorBox error={q.error} retry={q.reload} />;
  if (!x) return <Spinner />;
  return (
    <>
      <p className="small" style={{ margin: "0 0 8px" }}><Link to="/app/quarantine">← Quarantine</Link></p>
      <PageHeader title="Quarantined input" sub={<><code>{x.id}</code> · <Link to={`/app/runs/${x.run_id}`}>open run</Link></>} actions={<span className="dec quarantine big"><span aria-hidden>■</span>{x.state}</span>} />
      <div className="grid g2" style={{ alignItems: "start" }}>
        <div className="card small">
          <h3>Why it is isolated</h3>{x.reason_codes.map((c) => <div key={c}><code>{c}</code></div>)}
          <hr className="hr" /><div>Quarantined {fmtDate(x.created_at)}</div><div>Retained until {fmtDate(x.retain_until)}</div>
          {x.last_accessed_by && <div>Last accessed by {x.last_accessed_by} · {fmtDate(x.last_accessed_at)}</div>}
          {x.disposed_by && <div>Disposed by {x.disposed_by} · {fmtDate(x.disposed_at)}</div>}
          {x.reason_codes.some((c) => c.startsWith("privacy.secret")) && <div className="alert warn" style={{ marginTop: 12 }}>A credential was found. Treat it as exposed and rotate it, whatever happens to this item.</div>}
        </div>
        <div className="card">
          <h3>Actions</h3>
          {x.state !== "held" ? <p className="muted">This item has been disposed.</p> : (
            <div className="stack">
              {can("quarantine.access") && (grant ? (
                <div className="alert ok small">Access granted until {fmtDate(grant.expires_at)} ({grant.window_minutes} minutes).{" "}
                  <a className="btn sm primary" href={api.url(`/quarantine/${id}/content`, { access_id: grant.access_id })} download>Download content</a></div>
              ) : <button className="btn" onClick={() => setModal("access")}>Request access to content…</button>)}
              {can("quarantine.dispose") && <button className="btn danger" onClick={() => setModal("dispose")}>Dispose…</button>}
            </div>)}
        </div>
      </div>
      {modal === "access" && (
        <Modal title="Why do you need the content?" onClose={() => setModal(null)}>
          <div className="form"><p className="muted small" style={{ margin: 0 }}>Your purpose is recorded in the audit log. Access lasts a short window; the content may include credentials or personal data.</p>
            <Field label="Purpose"><textarea value={purpose} onChange={(e) => setPurpose(e.target.value)} minLength={5} required placeholder="e.g. Confirm which key was exposed so it can be rotated" /></Field>
            {err && <div className="alert error">{err}</div>}
            <button className="btn primary" disabled={busy || purpose.trim().length < 5} onClick={async () => {
              setErr(""); const g = await act(() => api.post(`/quarantine/${id}/access`, { purpose }), { onError: (e) => setErr(e.fields.purpose ?? e.message) });
              if (g) { setGrant(g); setModal(null); q.reload(); } }}>Grant me access</button></div>
        </Modal>)}
      {modal === "dispose" && (
        <Modal title="Dispose of this item" onClose={() => setModal(null)}>
          <div className="form">
            <Field label="Action"><select value={dispose.action} onChange={(e) => setDispose({ ...dispose, action: e.target.value })}><option value="delete">Delete the content permanently</option><option value="release_for_investigation">Release for investigation</option></select></Field>
            <Field label="Comment" hint="Required for the audit trail."><textarea value={dispose.comment} onChange={(e) => setDispose({ ...dispose, comment: e.target.value })} minLength={3} required /></Field>
            {err && <div className="alert error">{err}</div>}
            <button className="btn danger" disabled={busy || dispose.comment.trim().length < 3} onClick={async () => {
              setErr(""); if (await act(() => api.post(`/quarantine/${id}/dispose`, dispose), { ok: "Item disposed", onError: (e) => setErr(e.message) })) { setModal(null); q.reload(); } }}>Confirm</button></div>
        </Modal>)}
    </>
  );
}
export type { Q };
