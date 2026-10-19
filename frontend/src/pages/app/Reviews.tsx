import { useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction, useAsync } from "../../lib/hooks";
import { Link, useRouter } from "../../lib/router";
import { ago, fmtDate, titleCase } from "../../lib/format";
import type { DecisionDoc, Finding, Review } from "../../lib/types";
import { DecisionBadge, Empty, ErrorBox, Field, Modal, PageHeader, SeverityBadge, Spinner } from "../../components/ui";

export function ReviewsList() {
  const { navigate } = useRouter();
  const [state, setState] = useState("open");
  const q = useAsync(() => api.get<Review[]>("/reviews", { state, limit: 100 }), [state]);
  return (
    <>
      <PageHeader title="Reviews" sub="Inputs held for a person. Approve a time-limited exception, reject, or ask for a repaired version." />
      <div className="row" style={{ marginBottom: 14 }}>
        <select style={{ maxWidth: 200 }} aria-label="State" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="open">Open</option><option value="resolved">Resolved</option><option value="">All</option></select>
      </div>
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !q.data.length ? <Empty title="Nothing waiting for review" /> : (
        <div className="tw"><table><thead><tr><th>Summary</th><th>State</th><th>Reasons</th><th>Due</th><th>Assignee</th></tr></thead>
          <tbody>{q.data.map((r) => (
            <tr key={r.id} className="click" onClick={() => navigate(`/app/reviews/${r.id}`)}>
              <td><Link to={`/app/reviews/${r.id}`} onClick={(e) => e.stopPropagation()}>{r.summary}</Link><div className="faint small">{ago(r.created_at)}</div></td>
              <td><span className="tag">{r.state}{r.resolution && ` · ${titleCase(r.resolution)}`}</span></td>
              <td className="small">{r.reason_codes.slice(0, 3).map((c) => <div key={c}><code>{c}</code></div>)}{r.reason_codes.length > 3 && <span className="faint">+{r.reason_codes.length - 3} more</span>}</td>
              <td className="small nowrap">{r.state === "open" ? fmtDate(r.due_at) : "—"}</td><td className="small">{r.assignee || <span className="faint">unassigned</span>}</td>
            </tr>))}</tbody></table></div>)}
    </>
  );
}

interface ReviewFull extends Review { run: Record<string, any>; decision_detail: DecisionDoc; findings: Finding[]; grants: any[]; waivable: Record<string, boolean> }

export function ReviewDetail({ id }: { id: string }) {
  const { can, me } = useAccount();
  const q = useAsync(() => api.get<ReviewFull>(`/reviews/${id}`), [id]);
  const [mode, setMode] = useState<null | "approve_exception" | "reject" | "request_repair">(null);
  const { busy, run: act } = useAction();
  const [form, setForm] = useState({ comment: "", days: 7, codes: [] as string[] });
  const [err, setErr] = useState("");
  const r = q.data;
  if (q.error && !r) return <ErrorBox error={q.error} retry={q.reload} />;
  if (!r) return <Spinner />;
  const open = r.state === "open";
  const waivable = r.reason_codes.filter((c) => r.waivable[c]);
  const fixed = r.reason_codes.filter((c) => !r.waivable[c]);
  const own = r.run.created_by === me?.user.email;

  async function resolve() {
    setErr("");
    const body: Record<string, unknown> = { resolution: mode, comment: form.comment };
    if (mode === "approve_exception") { body.reason_codes = form.codes.length ? form.codes : waivable; body.days = form.days; }
    const ok = await act(() => api.post(`/reviews/${id}/resolve`, body), { ok: "Review resolved", onError: (e) => setErr(e.message) });
    if (ok) { setMode(null); q.reload(); }
  }

  return (
    <>
      <p className="small" style={{ margin: "0 0 8px" }}><Link to="/app/reviews">← Reviews</Link></p>
      <PageHeader title="Review" sub={r.summary} actions={<DecisionBadge decision={r.run.decision} big />} />
      <div className="grid split">
        <div className="stack">
          <div className="card">
            <h3>Findings behind this review</h3>
            {r.findings.length ? r.findings.map((f) => (
              <div key={f.id} className="ptr" style={{ marginBottom: 8 }}>
                <div className="row"><SeverityBadge severity={f.severity} /><b>{f.title}</b>{!r.waivable[f.code] && <span className="tag">cannot be waived</span>}</div>
                <div className="small muted" style={{ marginTop: 4 }}>{f.observed}</div>
                <div className="small" style={{ marginTop: 4 }}><b>Suggested:</b> {f.recommended_action}</div>
                {f.pointers[0] && <div className="small faint" style={{ marginTop: 4 }}><code>{f.pointers[0].path}</code> — {f.pointers[0].excerpt}</div>}
              </div>)) : <p className="muted">No findings recorded.</p>}
            <p className="small"><Link to={`/app/runs/${r.run_id}`}>Open the full run →</Link></p>
          </div>
        </div>
        <div className="stack">
          <div className="card small">
            <h3>Input</h3>
            <div><b>{r.run.label || r.run.filename}</b></div>
            <div className="muted">Submitted {fmtDate(r.run.created_at)} by {r.run.created_by}</div>
            <div className="muted">Profile {r.run.profile_id} · policy {r.run.policy_id}</div>
            <hr className="hr" />
            <div>State: <span className="tag">{r.state}</span>{r.resolution && <> <span className="tag">{titleCase(r.resolution)}</span></>}</div>
            {r.assignee && <div>Assigned to {r.assignee}</div>}
            {r.resolved_by && <div>Resolved by {r.resolved_by} · {fmtDate(r.resolved_at)}</div>}
            {r.comment && <div className="muted">“{r.comment}”</div>}
            {r.exception_id && <div>Exception <code>{r.exception_id}</code></div>}
          </div>
          {open && can("reviews.resolve") && (
            <div className="card">
              <h3>Your decision</h3>
              {own && <div className="alert warn small" style={{ marginBottom: 10 }}>You submitted this input. Segregation of duties prevents you approving your own exception when another eligible reviewer exists.</div>}
              {fixed.length > 0 && <div className="alert info small" style={{ marginBottom: 10 }}>These cannot be waived: {fixed.map((c) => <code key={c}> {c}</code>)}</div>}
              <div className="stack">
                {waivable.length > 0 && <button className="btn primary" onClick={() => { setForm({ ...form, codes: waivable }); setMode("approve_exception"); }}>Approve an exception…</button>}
                <button className="btn" onClick={() => setMode("request_repair")}>Request repair</button>
                <button className="btn danger" onClick={() => setMode("reject")}>Reject (block)</button>
              </div>
            </div>)}
        </div>
      </div>
      {mode && (
        <Modal title={mode === "approve_exception" ? "Approve an exception" : mode === "reject" ? "Reject this input" : "Request repair"} onClose={() => setMode(null)}>
          <div className="form">
            {mode === "approve_exception" && <>
              <p className="muted small" style={{ margin: 0 }}>The exception is time-limited, recorded in the audit log, and can be revoked. The policy sets the maximum duration and the role allowed to grant it.</p>
              <fieldset style={{ border: 0, padding: 0, margin: 0 }}><legend className="small"><b>Waive these findings</b></legend>
                {waivable.map((c) => <label className="check" key={c}><input type="checkbox" checked={form.codes.includes(c)} onChange={(e) => setForm({ ...form, codes: e.target.checked ? [...form.codes, c] : form.codes.filter((x) => x !== c) })} /><code>{c}</code></label>)}</fieldset>
              <Field label="Valid for (days)"><input type="number" min={1} max={365} value={form.days} onChange={(e) => setForm({ ...form, days: Number(e.target.value) })} /></Field></>}
            {mode === "reject" && <p className="muted small" style={{ margin: 0 }}>Rejecting replaces the Review decision with Block. A person can only tighten a decision this way.</p>}
            <Field label="Comment" hint="Required for the audit trail."><textarea value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} required /></Field>
            {err && <div className="alert error" role="alert">{err}</div>}
            <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn" onClick={() => setMode(null)}>Cancel</button>
              <button className={`btn ${mode === "reject" ? "danger" : "primary"}`} disabled={busy || !form.comment.trim() || (mode === "approve_exception" && !form.codes.length)} onClick={resolve}>{busy ? "Saving…" : "Confirm"}</button></div>
          </div>
        </Modal>)}
    </>
  );
}
