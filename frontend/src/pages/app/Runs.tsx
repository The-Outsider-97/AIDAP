import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction, useAsync, usePolling } from "../../lib/hooks";
import { Link, useRouter } from "../../lib/router";
import { ago, fmtBytes, fmtDate, pct, titleCase } from "../../lib/format";
import type { CheckSummary, DecisionDoc, Delivery, FeedbackRow, Finding, Page, Project, Run, Stage, Verdict } from "../../lib/types";
import { Confirm, DecisionBadge, Digest, Empty, ErrorBox, Modal, PageHeader, Pager, SeverityBadge, Spinner, StateDot, Tabs, CopyButton } from "../../components/ui";
import { STAGES } from "../../lib/content";

const LIMIT = 25;

export function RunsList() {
  const { navigate } = useRouter();
  const [f, setF] = useState({ q: "", decision: "", state: "", project_id: "" });
  const [offset, setOffset] = useState(0);
  const projects = useAsync(() => api.get<Project[]>("/projects"), []);
  const q = useAsync(() => api.get<Page<Run>>("/runs", { ...f, limit: LIMIT, offset }), [f.q, f.decision, f.state, f.project_id, offset]);
  const active = !!q.data?.items.some((r) => r.state === "queued" || r.state === "running");
  usePolling(q.reload, active, 2500);
  const set = (k: string) => (e: { target: { value: string } }) => { setOffset(0); setF({ ...f, [k]: e.target.value }); };
  return (
    <>
      <PageHeader title="Runs" sub="All validations and their decisions." actions={<Link className="btn primary" to="/app/new">New validation</Link>} />
      <div className="row" style={{ marginBottom: 14 }}>
        <input style={{ maxWidth: 260 }} placeholder="Search file name or label" aria-label="Search runs" value={f.q} onChange={set("q")} />
        <select style={{ maxWidth: 170 }} aria-label="Decision" value={f.decision} onChange={set("decision")}><option value="">All decisions</option>{["pass", "review", "quarantine", "block"].map((d) => <option key={d} value={d}>{titleCase(d)}</option>)}</select>
        <select style={{ maxWidth: 170 }} aria-label="State" value={f.state} onChange={set("state")}><option value="">All states</option>{["queued", "running", "completed", "failed", "cancelled"].map((d) => <option key={d} value={d}>{titleCase(d)}</option>)}</select>
        <select style={{ maxWidth: 220 }} aria-label="Project" value={f.project_id} onChange={set("project_id")}><option value="">All projects</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      </div>
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !q.data.items.length ? (
        <Empty title="No runs match" action={<Link className="btn primary" to="/app/new">Validate an input</Link>}>Validate a file to see it here.</Empty>
      ) : (
        <>
          <div className="tw"><table>
            <thead><tr><th>Input</th><th>Decision</th><th>Profile</th><th>Size</th><th>Submitted</th><th>By</th></tr></thead>
            <tbody>{q.data.items.map((r) => (
              <tr key={r.id} className="click" onClick={() => navigate(`/app/runs/${r.id}`)}>
                <td><Link to={`/app/runs/${r.id}`} onClick={(e) => e.stopPropagation()}>{r.label || r.filename}</Link>{r.label && <div className="faint small">{r.filename}</div>}
                  {r.parent_run_id && <span className="tag" style={{ marginLeft: 6 }}>derived</span>}</td>
                <td><DecisionBadge decision={r.decision} state={r.state} /> {r.shadow && <span className="tag">shadow</span>}</td>
                <td className="small">{r.profile_id} <span className="faint">· {r.policy_id}</span></td>
                <td className="small nowrap">{fmtBytes(r.size)}</td><td className="small nowrap" title={fmtDate(r.created_at)}>{ago(r.created_at)}</td><td className="small">{r.created_by}</td>
              </tr>))}</tbody>
          </table></div>
          <Pager total={q.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
        </>
      )}
    </>
  );
}

type Tab = "overview" | "findings" | "stages" | "evidence" | "report" | "deliveries" | "history";

export function RunDetail({ id }: { id: string }) {
  const { can } = useAccount();
  const { navigate } = useRouter();
  const [tab, setTab] = useState<Tab>("overview");
  const q = useAsync(() => api.get<Run>(`/runs/${id}`), [id]);
  const run = q.data;
  usePolling(q.reload, !!run && (run.state === "queued" || run.state === "running"), 1500);
  const { busy, run: act } = useAction();
  const [confirm, setConfirm] = useState<null | "cancel" | "redact" | "delete">(null);
  const dec = run?.decision_detail ?? null;

  if (q.error && !run) return <ErrorBox error={q.error} retry={q.reload} />;
  if (!run) return <Spinner />;
  const doAction = (path: string, ok: string, goto?: (r: any) => string | null) => async () => {
    setConfirm(null);
    const r = await act(() => api.post(`/runs/${id}/${path}`, {}), { ok });
    if (r) { const to = goto?.(r); if (to) navigate(to); else q.reload(); }
  };
  const working = run.state === "queued" || run.state === "running";
  const finished = run.state === "completed" || run.state === "failed" || run.state === "cancelled";
  const doDelete = async () => {
    setConfirm(null);
    if (await act(() => api.del(`/runs/${id}/content`), { ok: "Stored content deleted" })) q.reload();
  };

  return (
    <>
      <p className="small" style={{ margin: "0 0 8px" }}><Link to="/app/runs">← Runs</Link></p>
      <PageHeader title={run.label || run.filename}
        sub={<>{run.filename} · {fmtBytes(run.size)} · submitted {ago(run.created_at)} by {run.created_by}{run.parent_run_id && <> · derived from <Link to={`/app/runs/${run.parent_run_id}`}>{run.parent_run_id.slice(0, 12)}…</Link></>}</>}
        actions={<>
          <DecisionBadge decision={run.decision} state={run.state} big />
          {can("runs.manage") && working && <button className="btn" onClick={() => setConfirm("cancel")}>Cancel</button>}
          {can("runs.manage") && run.state === "failed" && <button className="btn" disabled={busy} onClick={doAction("retry", "Run queued again")}>Retry</button>}
          {can("runs.submit") && run.state === "completed" && <button className="btn" disabled={busy} onClick={doAction("rerun", "Re-validation started", (r) => `/app/runs/${r.id}`)}>Re-validate</button>}
          {can("runs.submit") && run.state === "completed" && run.decision !== "pass" && <button className="btn" onClick={() => setConfirm("redact")}>Create redacted copy</button>}
          {can("retention.manage") && finished && !run.expired && <button className="btn" onClick={() => setConfirm("delete")}>Delete stored content</button>}
        </>} />
      {run.state === "failed" && <div className="alert error" style={{ marginBottom: 16 }}><b>The run failed.</b> {run.error}</div>}
      {working && <div className="alert info" style={{ marginBottom: 16 }} role="status"><span className="spin" style={{ width: 14, height: 14, borderWidth: 2, verticalAlign: "-2px", marginRight: 8 }} />Checking this input… this page updates automatically.</div>}
      {run.warnings?.length ? <div className="alert warn" style={{ marginBottom: 16 }}>{run.warnings.join(" ")}</div> : null}
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "overview", label: "Overview" }, { id: "findings", label: "Findings" }, { id: "stages", label: "Stages" },
        { id: "evidence", label: "Evidence" }, { id: "report", label: "Report" }, { id: "deliveries", label: "Deliveries" }, { id: "history", label: "History" }]} />
      {tab === "overview" && <Overview run={run} dec={dec} />}
      {tab === "findings" && <FindingsTab id={id} ready={run.state === "completed"} />}
      {tab === "stages" && <StagesTab id={id} running={working} />}
      {tab === "evidence" && <EvidenceTab id={id} ready={run.state === "completed"} />}
      {tab === "report" && <ReportTab id={id} ready={run.state === "completed"} />}
      {tab === "deliveries" && <DeliveriesTab id={id} />}
      {tab === "history" && <HistoryTab run={run} />}
      {confirm === "cancel" && <Confirm title="Cancel this run?" confirm="Cancel run" danger busy={busy} onNo={() => setConfirm(null)} onYes={doAction("cancel", "Run cancelled")}>
        <p>Checks stop at the next stage boundary. Nothing is released.</p></Confirm>}
      {confirm === "delete" && <Confirm title="Delete the stored content of this run?" confirm="Delete content" danger busy={busy} onNo={() => setConfirm(null)} onYes={doDelete}>
        <p>The uploaded input, the detailed results and the evidence bundle are removed now instead of at the end of your retention window. The decision, its reasons and the audit trail are kept. This cannot be undone, and the run can no longer be re-validated or its artifact pulled.</p></Confirm>}
      {confirm === "redact" && <Confirm title="Create a redacted copy?" confirm="Create copy" busy={busy} onNo={() => setConfirm(null)} onYes={doAction("redact", "Redacted copy submitted", (r) => `/app/runs/${r.id}`)}>
        <p>Detected personal data is replaced with <code>[REDACTED:type]</code> markers in a new input. The copy is validated again from scratch — redaction never changes the decision on the original.</p></Confirm>}
    </>
  );
}

function Overview({ run, dec }: { run: Run; dec: DecisionDoc | null }) {
  if (!dec) return run.state === "completed" ? <Empty title="No decision recorded" /> : <Empty title="Waiting for a decision" />;
  return (
    <div className="grid split">
      <div className="stack">
        <div className="card">
          <h3>{dec.rationale.summary}</h3>
          {dec.rationale.next_action && <p><b>What to do next:</b> {dec.rationale.next_action}</p>}
          {run.release_authorized !== undefined && (
            <div className={`alert ${run.release_authorized ? "ok" : "warn"}`}>
              {run.release_authorized ? "Release is authorized for the exact bytes that were assessed." : "Release is not authorized. The pull gate returns the reason instead of the data."}
            </div>
          )}
          {run.review_id && <p className="small">An open review exists: <Link to={`/app/reviews/${run.review_id}`}>open review</Link>.</p>}
          {run.quarantine_id && <p className="small">The input is in quarantine: <Link to={`/app/quarantine/${run.quarantine_id}`}>open quarantine item</Link>.</p>}
        </div>
        <div className="card">
          <h3>Why this decision</h3>
          {dec.reasons.length ? (
            <div className="tw"><table><thead><tr><th>Reason</th><th>Effect</th><th>Severity</th><th>Waivable</th></tr></thead>
              <tbody>{dec.reasons.map((r, i) => (
                <tr key={i}><td><b>{r.message}</b><div className="faint small"><code>{r.code}</code></div>{r.guidance && <div className="small muted" style={{ marginTop: 4 }}>{r.guidance}</div>}{r.waived_by && <div className="small">Waived by {r.waived_by}</div>}</td>
                  <td><DecisionBadge decision={r.effect} /></td><td><SeverityBadge severity={r.severity} /></td><td className="small">{r.waivable ? "Yes" : "No"}</td></tr>))}</tbody></table></div>
          ) : <p className="muted">No findings affected the decision.</p>}
          <h4 style={{ marginTop: 18 }}>Rule steps</h4>
          <ol className="small" style={{ paddingLeft: 18, margin: 0 }}>{dec.rationale.steps.map((s: any, i: number) => (
            <li key={i} style={{ marginBottom: 4 }}><b>{s.rule_id}</b> {s.description} — <span className={s.outcome === "pass" ? "muted" : ""}>{s.outcome}</span></li>))}</ol>
        </div>
      </div>
      <div className="stack">
        <div className="card small">
          <h3>Details</h3>
          <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 14px" }}>
            <dt className="muted">Profile</dt><dd style={{ margin: 0 }}>{dec.profile_ref}</dd>
            <dt className="muted">Policy</dt><dd style={{ margin: 0 }}>{dec.policy_ref}{dec.shadow && <span className="tag" style={{ marginLeft: 6 }}>shadow</span>}</dd>
            <dt className="muted">Decided by</dt><dd style={{ margin: 0 }}>{dec.decided_by}</dd>
            <dt className="muted">Decided</dt><dd style={{ margin: 0 }}>{fmtDate(dec.created_at)}</dd>
            <dt className="muted">Valid until</dt><dd style={{ margin: 0 }}>{fmtDate(dec.expires_at)}</dd>
            <dt className="muted">Input digest</dt><dd style={{ margin: 0 }}><Digest value={dec.input_digest} /></dd>
            <dt className="muted">Evidence seal</dt><dd style={{ margin: 0 }}><Digest value={run.evidence_seal} /></dd>
            <dt className="muted">Coverage</dt><dd style={{ margin: 0 }}>{dec.coverage?.mandatory_conclusive ?? "—"} of {dec.coverage?.mandatory_total ?? "—"} mandatory checks concluded</dd>
          </dl>
        </div>
        {dec.exception_ids?.length > 0 && <div className="card small"><h3>Exceptions</h3>{dec.exception_ids.map((x) => <div key={x}><code>{x}</code></div>)}</div>}
      </div>
    </div>
  );
}

function FindingsTab({ id, ready }: { id: string; ready: boolean }) {
  const q = useAsync(() => api.get<{ findings: Finding[]; checks: CheckSummary[]; confidence: any }>(`/runs/${id}/findings`), [id, ready]);
  const fb = useAsync(() => api.get<FeedbackRow[]>(`/runs/${id}/feedback`).catch(() => [] as FeedbackRow[]), [id, ready]);
  const { run: act } = useAction();
  const { can } = useAccount();
  const [open, setOpen] = useState<string | null>(null);
  const [sev, setSev] = useState("");
  const mine = (fid: string) => fb.data?.find((x) => x.finding_id === fid && x.mine)?.verdict;
  const tally = (fid: string) => (fb.data ?? []).filter((x) => x.finding_id === fid).length;
  const rate = (fid: string, verdict: Verdict) => act(() => api.post(`/runs/${id}/findings/${fid}/feedback`, { verdict }), { ok: "Feedback recorded" }).then(() => fb.reload());
  if (q.error) return <ErrorBox error={q.error} retry={q.reload} />;
  if (!q.data) return <Spinner />;
  const list = q.data.findings.filter((f) => !sev || f.severity === sev);
  const unresolved = q.data.checks.filter((c) => ["unknown", "not_evaluated", "error"].includes(c.status) && c.unknown_reason !== "not_applicable");
  return (
    <div className="stack lg">
      {unresolved.length > 0 && (
        <div className="alert warn"><b>{unresolved.length} check{unresolved.length > 1 ? "s" : ""} could not conclude.</b> Unknown is not the same as clean.
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{unresolved.map((c) => <li key={c.check_id}><code>{c.check_id}</code> — {c.unknown_reason || c.message || c.status}{c.mandatory && <b> (mandatory)</b>}</li>)}</ul></div>
      )}
      <div>
        <div className="row between" style={{ marginBottom: 10 }}><h3 style={{ margin: 0 }}>Findings ({list.length})</h3>
          <select style={{ maxWidth: 170 }} aria-label="Severity filter" value={sev} onChange={(e) => setSev(e.target.value)}><option value="">All severities</option>{["critical", "high", "medium", "low", "info"].map((s) => <option key={s}>{s}</option>)}</select></div>
        {!list.length ? <Empty title="No findings">Nothing was flagged by the checks that ran.</Empty> : list.map((f) => (
          <div className="finding" key={f.id}>
            <button aria-expanded={open === f.id} onClick={() => setOpen(open === f.id ? null : f.id)}>
              <SeverityBadge severity={f.severity} /><span style={{ flex: 1 }}><b>{f.title}</b> <span className="faint small">× {f.count}</span><div className="faint small"><code>{f.code}</code></div></span>
              <span className="tag">{f.origin}</span><span className="tag">{f.confidence.basis}</span><span aria-hidden>{open === f.id ? "▴" : "▾"}</span>
            </button>
            {open === f.id && (
              <div className="body">
                <dl>
                  <dt>Observed</dt><dd>{f.observed}</dd>
                  <dt>Inference</dt><dd>{f.inference}</dd>
                  <dt>Confidence</dt><dd>{f.confidence.basis}{f.confidence.value !== null && ` · ${f.confidence.value}`} — {f.confidence.note}</dd>
                  <dt>Recommended</dt><dd>{f.recommended_action}</dd>
                  <dt>Check</dt><dd><code>{f.check_id}</code>{f.mandatory && " · mandatory"}</dd>
                </dl>
                {(can("reviews.resolve") || can("runs.submit")) && (
                  <div className="rate" role="group" aria-label="Rate this finding" style={{ margin: "8px 0" }}>
                    <span className="muted small">Was this useful?</span>
                    {([["useful", "Useful"], ["false_positive", "False positive"], ["unclear", "Unclear"]] as [Verdict, string][]).map(([v, l]) => (
                      <button key={v} type="button" aria-pressed={mine(f.id) === v} onClick={() => rate(f.id, v)}>{l}</button>))}
                    {tally(f.id) > 0 && <span className="faint small">{tally(f.id)} rating{tally(f.id) > 1 ? "s" : ""}</span>}
                  </div>)}
                {f.pointers.length > 0 && <div><div className="muted small" style={{ marginBottom: 4 }}>Evidence pointers</div>
                  {f.pointers.slice(0, 8).map((p, i) => <div className="ptr small" key={i}><code>{p.path}</code>{p.start !== null && <span className="faint"> [{p.start}–{p.end}]</span>}<div>{p.excerpt}</div></div>)}</div>}
              </div>)}
          </div>))}
      </div>
      <div>
        <h3>Checks ({q.data.checks.length})</h3>
        <div className="tw"><table><thead><tr><th>Check</th><th>Status</th><th>Evaluator</th><th>Coverage</th><th>Findings</th></tr></thead>
          <tbody>{q.data.checks.map((c) => (
            <tr key={c.check_id}><td><code>{c.check_id}</code>{c.mandatory && <span className="tag" style={{ marginLeft: 6 }}>mandatory</span>}{(c.unknown_reason || c.message) && <div className="faint small">{c.unknown_reason || c.message}</div>}</td>
              <td><StateDot state={c.status} /></td><td className="small">{c.evaluator} <span className="faint">({c.origin})</span></td><td className="small">{pct(c.coverage)}</td><td>{c.findings}</td></tr>))}</tbody></table></div>
        <p className="faint small" style={{ marginTop: 8 }}>{q.data.confidence?.note}</p>
      </div>
    </div>
  );
}

function StagesTab({ id, running }: { id: string; running: boolean }) {
  const q = useAsync(() => api.get<Stage[]>(`/runs/${id}/stages`), [id]);
  usePolling(q.reload, running, 1500);
  if (q.error) return <ErrorBox error={q.error} retry={q.reload} />;
  if (!q.data) return <Spinner />;
  const by = new Map(q.data.map((s) => [s.stage, s]));
  return (
    <div className="tw"><table><thead><tr><th>#</th><th>Stage</th><th>Method</th><th>State</th><th>Duration</th><th>Notes</th></tr></thead>
      <tbody>{STAGES.map((sp) => {
        const s = by.get(sp.no);
        const ms = s?.started_at && s?.finished_at ? new Date(s.finished_at).getTime() - new Date(s.started_at).getTime() : null;
        return <tr key={sp.no}><td>{sp.no}</td><td><b>{sp.title}</b></td><td><span className="tag">{sp.method}</span></td>
          <td>{s ? <StateDot state={s.state} /> : <span className="faint small">pending</span>}</td><td className="small">{ms !== null ? `${ms} ms` : "—"}</td><td className="small muted">{s?.message}{s && s.attempt > 1 && ` · attempt ${s.attempt}`}</td></tr>;
      })}</tbody></table></div>
  );
}

function EvidenceTab({ id, ready }: { id: string; ready: boolean }) {
  const q = useAsync(() => (ready ? api.get<any>(`/runs/${id}/evidence`) : Promise.resolve(null)), [id, ready]);
  const [show, setShow] = useState(false);
  if (!ready) return <Empty title="Evidence is created when the run finishes" />;
  if (q.error) return <ErrorBox error={q.error} retry={q.reload} />;
  if (!q.data) return <Spinner />;
  const b = q.data.bundle;
  return (
    <div className="stack">
      <div className={`alert ${q.data.verified ? "ok" : "error"}`}>{q.data.verified ? "Seal verified: the stored bundle matches its SHA-256 seal." : "Seal verification FAILED: the stored bundle no longer matches its seal."}</div>
      <div className="card small">
        <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 14px" }}>
          <dt className="muted">Schema</dt><dd style={{ margin: 0 }}><code>{b.schema}</code></dd>
          <dt className="muted">Seal</dt><dd style={{ margin: 0, overflowWrap: "anywhere" }}><code>{q.data.seal}</code> <CopyButton text={q.data.seal} /></dd>
          <dt className="muted">Input digest</dt><dd style={{ margin: 0, overflowWrap: "anywhere" }}><code>{b.input.digest}</code></dd>
          <dt className="muted">Producer</dt><dd style={{ margin: 0 }}>{b.producer.name} {b.producer.version} · SLAI baseline <code>{String(b.producer.slai_baseline_commit).slice(0, 10)}</code></dd>
          <dt className="muted">Evaluators</dt><dd style={{ margin: 0 }}>{b.evaluators.length}</dd>
          <dt className="muted">Calibrated confidence</dt><dd style={{ margin: 0 }}>{b.confidence.calibrated ? "yes" : "no"} — {b.confidence.note}</dd>
        </dl>
        <p className="muted" style={{ marginTop: 12 }}>{b.statement}</p>
      </div>
      <div className="row">
        <a className="btn primary" href={api.url(`/runs/${id}/evidence`, { download: "1" })}>Download evidence bundle (JSON)</a>
        <button className="btn" onClick={() => setShow(!show)}>{show ? "Hide" : "Show"} lineage (PROV)</button>
      </div>
      {show && <pre>{JSON.stringify(b.provenance, null, 2)}</pre>}
    </div>
  );
}

function ReportTab({ id, ready }: { id: string; ready: boolean }) {
  if (!ready) return <Empty title="The report is available when the run finishes" />;
  return (
    <div className="card stack">
      <p className="muted" style={{ margin: 0 }}>The report restates the decision, the reasons, the findings, check coverage and what was not evaluated. Spreadsheet exports neutralise formulas.</p>
      <div className="row">
        {[["pdf", "PDF"], ["html", "HTML"], ["csv", "CSV (findings)"], ["json", "JSON"]].map(([f, l]) => <a key={f} className="btn" href={api.url(`/runs/${id}/report`, { format: f })} download>{l}</a>)}
      </div>
    </div>
  );
}

function DeliveriesTab({ id }: { id: string }) {
  const { can } = useAccount();
  const q = useAsync(() => api.get<Delivery[]>(`/runs/${id}/deliveries`), [id]);
  const { run: act } = useAction();
  if (q.error) return <ErrorBox error={q.error} retry={q.reload} />;
  if (!q.data) return <Spinner />;
  if (!q.data.length) return <Empty title="No deliveries">A destination (webhook or object store) is notified after the decision. Pull-gate reads are logged here.</Empty>;
  return (
    <div className="tw"><table><thead><tr><th>Kind</th><th>State</th><th>Attempts</th><th>Created</th><th>Sent</th><th>Notes</th><th /></tr></thead>
      <tbody>{q.data.map((d) => (
        <tr key={d.id}><td>{d.kind}</td><td><StateDot state={d.state} /></td><td>{d.attempts}</td><td className="small">{ago(d.created_at)}</td><td className="small">{ago(d.sent_at)}</td><td className="small muted">{d.last_error || d.note}</td>
          <td>{can("webhooks.manage") && ["failed", "dead"].includes(d.state) && <button className="btn sm" onClick={async () => { if (await act(() => api.post(`/deliveries/${d.id}/retry`), { ok: "Delivery re-queued" })) q.reload(); }}>Retry</button>}</td></tr>))}</tbody></table></div>
  );
}

function HistoryTab({ run }: { run: Run }) {
  const decs = useAsync(() => api.get<DecisionDoc[]>(`/runs/${run.id}/decisions`), [run.id]);
  const siblings = useAsync(() => api.get<Page<Run>>("/runs", { project_id: run.project_id, limit: 50 }), [run.id]);
  const [other, setOther] = useState(run.parent_run_id ?? "");
  const diff = useAsync(() => (other ? api.get<any>(`/runs/${run.id}/diff`, { against: other }) : Promise.resolve(null)), [run.id, other]);
  useEffect(() => { if (!other && run.parent_run_id) setOther(run.parent_run_id); }, [run.parent_run_id]); // eslint-disable-line
  const choices = useMemo(() => (siblings.data?.items ?? []).filter((r) => r.id !== run.id && r.state === "completed"), [siblings.data, run.id]);
  return (
    <div className="stack lg">
      <div className="card">
        <h3>Decision history</h3>
        {!decs.data ? <Spinner /> : !decs.data.length ? <p className="muted">No decisions yet.</p> : (
          <ul className="timeline">{decs.data.map((d) => (
            <li key={d.id}><div className="row"><DecisionBadge decision={d.decision} /><span className="tag">{d.status}</span>{d.shadow && <span className="tag">shadow</span>}</div>
              <div className="small muted">{fmtDate(d.created_at)} · {d.decided_by} · {d.policy_ref}</div><div className="small">{d.rationale.summary}</div></li>))}</ul>)}
      </div>
      <div className="card">
        <h3>Compare with another run</h3>
        <select aria-label="Compare with" value={other} onChange={(e) => setOther(e.target.value)} style={{ maxWidth: 420 }}>
          <option value="">Choose a run…</option>{choices.map((r) => <option key={r.id} value={r.id}>{r.label || r.filename} · {r.decision} · {ago(r.created_at)}</option>)}
        </select>
        {diff.error && <div style={{ marginTop: 12 }}><ErrorBox error={diff.error} /></div>}
        {diff.data && (
          <div className="stack" style={{ marginTop: 14 }}>
            <p className="small">Decision {diff.data.decision_changed ? <>changed from <DecisionBadge decision={diff.data.base.decision} /> to <DecisionBadge decision={diff.data.compare.decision} /></> : "did not change"}.</p>
            {([["findings_added", "New in the compared run"], ["findings_resolved", "No longer present in the compared run"]] as const).map(([k, l]) => (
              <div key={k}><h4>{l} ({diff.data[k].length})</h4>{diff.data[k].map((f: any) => <div key={f.code} className="small"><SeverityBadge severity={f.severity} /> <code>{f.code}</code> × {f.count}</div>)}</div>))}
            <div><h4>Changed ({diff.data.findings_changed.length})</h4>{diff.data.findings_changed.map((c: any) => <div key={c.code} className="small"><code>{c.code}</code>: {c.from.count} → {c.to.count}</div>)}</div>
          </div>)}
      </div>
    </div>
  );
}
export { Modal };
