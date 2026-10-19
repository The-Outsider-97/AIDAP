import { useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAsync } from "../../lib/hooks";
import { Link } from "../../lib/router";
import { fmtNum, titleCase } from "../../lib/format";
import type { Insights as Data, Project } from "../../lib/types";
import { Empty, ErrorBox, PageHeader, Spinner } from "../../components/ui";
import { Chart } from "./Dashboard";

const pc = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);
const hrs = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v < 1 ? `${Math.round(v * 60)} min` : `${v.toFixed(1)} h`);

function Stat({ value, label, hint, tone }: { value: string; label: string; hint?: string; tone?: "ok" | "bad" | "warn" }) {
  return <div className="card tight"><div className="stat"><b className={tone ? `${tone}-t` : undefined}>{value}</b><span>{label}</span>{hint && <small>{hint}</small>}</div></div>;
}

export function Insights() {
  const { me } = useAccount();
  const [days, setDays] = useState(30);
  const [project, setProject] = useState("");
  const projects = useAsync(() => api.get<Project[]>("/projects"), []);
  const q = useAsync(() => api.get<Data>("/insights", { days, project_id: project }), [days, project]);
  const d = q.data;
  const defs = d?.definitions ?? {};
  const hasMetrics = me?.plan.features.includes("metrics_export");
  const total = d ? Object.values(d.runs.by_decision).reduce((a, b) => a + b, 0) : 0;
  return (
    <>
      <PageHeader title="Insights" sub="Operating measures for the validation gate: coverage, reliability, review load and finding quality."
        actions={<>
          <select aria-label="Project" value={project} onChange={(e) => setProject(e.target.value)} style={{ maxWidth: 200 }}>
            <option value="">All projects</option>{(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
          <div className="seg" role="group" aria-label="Period">{[7, 30, 90].map((n) => <button key={n} aria-pressed={days === n} onClick={() => setDays(n)}>{n} days</button>)}</div>
        </>} />
      {q.error && !d ? <ErrorBox error={q.error} retry={q.reload} /> : !d ? <Spinner /> : d.runs.total === 0 ? (
        <Empty title="No runs in this period" action={<Link className="btn primary" to="/app/new">New validation</Link>}>Measures appear once runs have completed.</Empty>
      ) : (
        <div className="stack lg">
          <section aria-label="Key measures" className="grid g4">
            <Stat value={fmtNum(d.runs.finished)} label="Completed runs" hint={`${fmtNum(d.runs.total)} submitted`} />
            <Stat value={pc(d.runs.pass_rate)} label="Passed" hint={`${pc(d.runs.hold_rate)} held or blocked`} />
            <Stat value={pc(d.reliability.mandatory_check_completion)} label="Mandatory-check completion" hint={defs.mandatory_check_completion}
              tone={d.reliability.mandatory_check_completion !== null && d.reliability.mandatory_check_completion < 1 ? "warn" : undefined} />
            <Stat value={pc(d.reliability.unsupported_input_rate)} label="Unsupported inputs" hint={`${d.reliability.sampled_runs} runs sampled`} />
          </section>

          <div className="grid split" style={{ alignItems: "start" }}>
            <div className="card">
              <h3>Decisions</h3>
              <div className="bar" role="img" aria-label="Share of decisions">
                {(["pass", "review", "quarantine", "block"] as const).map((k, i) => total && d.runs.by_decision[k] ? <i key={k} className={"prqb"[i]} style={{ width: `${(d.runs.by_decision[k] / total) * 100}%` }} title={`${k}: ${d.runs.by_decision[k]}`} /> : null)}
              </div>
              <div className="row small" style={{ marginTop: 10, flexWrap: "wrap", gap: 16 }}>
                {(["pass", "review", "quarantine", "block"] as const).map((k) => <span key={k}><b>{fmtNum(d.runs.by_decision[k] ?? 0)}</b> <span className="muted">{titleCase(k)}</span></span>)}
              </div>
              <div style={{ marginTop: 16 }}><Chart series={d.series as any} span={Math.min(d.window_days, 30)} /></div>
            </div>
            <div className="card">
              <h3>Review</h3>
              <dl className="kv">
                <dt>Open</dt><dd>{d.review.open}{d.review.overdue > 0 && <span className="bad-t"> · {d.review.overdue} past {d.review.sla_hours} h</span>}</dd>
                <dt>Oldest open</dt><dd>{hrs(d.review.oldest_open_hours)}</dd>
                <dt title={defs.time_to_resolve_hours}>Time to resolve</dt><dd>median {hrs(d.review.time_to_resolve_hours.median)} · p90 {hrs(d.review.time_to_resolve_hours.p90)}</dd>
                <dt title={defs.review_overturn_rate}>Exceptions approved</dt><dd>{pc(d.review.overturn_rate)} of {d.review.resolved} resolved</dd>
                <dt>Repair requested / rejected</dt><dd>{d.review.repair_requested} / {d.review.rejected}</dd>
                <dt>Held in quarantine</dt><dd>{d.review.held_quarantine}</dd>
              </dl>
              <p className="faint small" style={{ marginBottom: 0 }}>Review target: {d.review.sla_hours} h. Change it in <Link to="/app/settings">Settings</Link>.</p>
            </div>
          </div>

          <div className="grid g2" style={{ alignItems: "start" }}>
            <div className="card">
              <h3>Release integrity</h3>
              <dl className="kv">
                <dt>Delivered</dt><dd>{d.reliability.delivery.sent}</dd>
                <dt>Failed</dt><dd className={d.reliability.delivery.failed ? "warn-t" : undefined}>{d.reliability.delivery.failed}</dd>
                <dt>Retried</dt><dd>{d.reliability.delivery.retried}</dd>
                <dt title={defs.integrity_stops}>Integrity stops</dt><dd>{d.reliability.delivery.integrity_stops}</dd>
                <dt title={defs.unhandled_errors}>Unhandled errors</dt><dd className={d.reliability.unhandled_errors ? "bad-t" : undefined}>{d.reliability.unhandled_errors} ({pc(d.reliability.error_rate)})</dd>
              </dl>
            </div>
            <div className="card">
              <h3>Finding quality</h3>
              <dl className="kv">
                <dt>Ratings</dt><dd>{d.feedback.total}</dd>
                <dt title={defs.finding_usefulness}>Rated useful</dt><dd>{pc(d.feedback.usefulness)}</dd>
                <dt>Useful / false positive / unclear</dt><dd>{d.feedback.verdicts.useful} / {d.feedback.verdicts.false_positive} / {d.feedback.verdicts.unclear}</dd>
              </dl>
              <p className="faint small" style={{ marginBottom: 0 }}>Ratings are reviewer opinion. They never change a decision or a policy.</p>
            </div>
          </div>

          <div className="card">
            <h3>Checks</h3>
            {d.checks.length ? (
              <div className="tw"><table><thead><tr><th>Check</th><th>Runs</th><th>Failed</th><th>Inconclusive</th><th>Findings</th><th>Rated useful</th></tr></thead>
                <tbody>{d.checks.map((c) => (
                  <tr key={c.check_id}><td><code>{c.check_id}</code></td><td>{c.runs}</td><td>{c.failed}</td>
                    <td className={c.unknown ? "warn-t" : undefined}>{c.unknown}{c.unknown_rate !== null && c.unknown ? ` (${pc(c.unknown_rate)})` : ""}</td>
                    <td>{c.findings}</td><td>{c.rated ? `${pc(c.usefulness)} of ${c.rated}` : <span className="faint">—</span>}</td></tr>))}</tbody></table></div>
            ) : <p className="muted">No stored results in this period.</p>}
          </div>

          <div className="card">
            <h3>Most frequent findings</h3>
            {d.top_findings.length ? (
              <div className="tw"><table><thead><tr><th>Finding</th><th>Check</th><th>Occurrences</th><th>Runs</th><th>False positives</th></tr></thead>
                <tbody>{d.top_findings.map((f) => (
                  <tr key={f.code}><td><code>{f.code}</code></td><td className="small muted">{f.check_id}</td><td>{fmtNum(f.count)}</td><td>{f.runs}</td>
                    <td>{f.rated ? `${f.false_positive} of ${f.rated}` : <span className="faint">—</span>}</td></tr>))}</tbody></table></div>
            ) : <p className="muted">No findings in this period.</p>}
          </div>

          <p className="faint small">
            {hasMetrics ? <>Prometheus format: <code>GET /api/v1/insights/metrics</code> (API key with read access).</> : "Prometheus export is available on the Team plan and above."}
            {" "}Check statistics come from the {d.reliability.sampled_runs} most recent stored results; runs past retention are excluded.
          </p>
        </div>)}
    </>
  );
}
