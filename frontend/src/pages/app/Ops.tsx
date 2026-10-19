import { useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction, useAsync } from "../../lib/hooks";
import { Link } from "../../lib/router";
import { ago, fmtDate } from "../../lib/format";
import { Empty, ErrorBox, PageHeader, Pager, SeverityBadge, Spinner, StateDot } from "../../components/ui";

export function Alerts() {
  const { can } = useAccount();
  const q = useAsync(() => api.get<any[]>("/alerts", { limit: 100 }), []);
  const { busy, run: act } = useAction();
  return (
    <>
      <PageHeader title="Alerts" sub="Credential exposure, quarantines, overdue reviews and repeated failures. Repeats are grouped." />
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !q.data.length ? <Empty title="No alerts" /> : (
        <div className="stack">{q.data.map((a) => (
          <div className="card tight" key={a.id} style={a.acknowledged_at ? { opacity: 0.6 } : undefined}>
            <div className="row between"><div className="row"><SeverityBadge severity={a.severity} /><b>{a.title}</b>{a.count > 1 && <span className="tag">× {a.count}</span>}</div>
              {!a.acknowledged_at && can("alerts.ack") && <button className="btn sm" disabled={busy} onClick={async () => { if (await act(() => api.post(`/alerts/${a.id}/ack`, {}), { ok: "Acknowledged" })) q.reload(); }}>Acknowledge</button>}</div>
            <p className="muted small" style={{ margin: "6px 0 0" }}>{a.detail}</p>
            <div className="faint small" style={{ marginTop: 4 }}>{ago(a.last_seen_at)}{a.run_id && <> · <Link to={`/app/runs/${a.run_id}`}>run</Link></>}{a.acknowledged_at && <> · acknowledged by {a.acknowledged_by}</>}</div>
          </div>))}</div>)}
    </>
  );
}

const LIMIT = 50;
export function Audit() {
  const { can } = useAccount();
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const q = useAsync(() => api.get<any[]>("/audit", { limit: LIMIT + 1, offset, action }), [offset, action]);
  const ver = useAsync(() => api.get<{ ok: boolean; events: number; broken_at: string | null; head: string }>("/audit/verify"), []);
  const [open, setOpen] = useState<string | null>(null);
  const rows = q.data?.slice(0, LIMIT) ?? [];
  return (
    <>
      <PageHeader title="Audit log" sub="Append-only and hash-chained: each entry commits to the one before it."
        actions={can("audit.export") ? <a className="btn" href={api.url("/audit/export")} download>Export CSV</a> : <span className="tag">Export: Business plan</span>} />
      {ver.data && (
        <div className={`alert ${ver.data.ok ? "ok" : "error"}`} style={{ marginBottom: 16 }}>
          {ver.data.ok ? <>Chain verified: {ver.data.events} events, head <code>{ver.data.head.replace("sha256:", "").slice(0, 16)}…</code></> : <>Chain verification FAILED at {ver.data.broken_at}. Treat this log as untrustworthy and contact your administrator.</>}
          {" "}<button className="linkbtn" onClick={ver.reload}>Re-verify</button>
        </div>)}
      <div className="row" style={{ marginBottom: 12 }}><input style={{ maxWidth: 280 }} placeholder="Filter by action prefix, e.g. review." aria-label="Action prefix" value={action} onChange={(e) => { setOffset(0); setAction(e.target.value); }} /></div>
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !rows.length ? <Empty title="No events" /> : (
        <>
          <div className="tw"><table><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Target</th><th /></tr></thead>
            <tbody>{rows.map((e) => (
              <>
                <tr key={e.id} className="click" onClick={() => setOpen(open === e.id ? null : e.id)}>
                  <td className="small nowrap">{fmtDate(e.at)}</td><td className="small">{e.actor} {e.actor_kind !== "user" && <span className="tag">{e.actor_kind}</span>}</td><td><code>{e.action}</code></td><td className="small" style={{ overflowWrap: "anywhere" }}>{e.target}</td><td aria-hidden>{open === e.id ? "▴" : "▾"}</td></tr>
                {open === e.id && <tr key={e.id + "d"}><td colSpan={5}><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify({ data: e.data, hash: e.hash, prev_hash: e.prev_hash, correlation_id: e.correlation_id }, null, 2)}</pre></td></tr>}
              </>))}</tbody></table></div>
          <div className="row between" style={{ marginTop: 12 }}><span className="muted small">Showing {offset + 1}–{offset + rows.length}</span>
            <div className="row"><button className="btn sm" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>Newer</button><button className="btn sm" disabled={(q.data?.length ?? 0) <= LIMIT} onClick={() => setOffset(offset + LIMIT)}>Older</button></div></div>
        </>)}
    </>
  );
}
export { Pager };

const AGENT_LABEL: Record<string, string> = { privacy_id: "Privacy identification (DataID)", quality: "Quality agent", safety: "Safety agent", provenance: "Provenance agent", language: "Language agent" };

export function SystemStatus() {
  const q = useAsync(() => api.get<any>("/system/status"), []);
  if (q.error) return <ErrorBox error={q.error} retry={q.reload} />;
  if (!q.data) return <Spinner />;
  const s = q.data;
  const agents = Object.entries(s.slai?.agents ?? {}) as [string, any][];
  return (
    <>
      <PageHeader title="System & SLAI status" sub="Available components. Checks that depend on an unavailable component are reported as not evaluated."
        actions={<button className="btn" onClick={q.reload}>Refresh</button>} />
      <div className="stack lg">
        <div className="card">
          <div className="row between"><h3 style={{ margin: 0 }}>SLAI</h3><StateDot state={s.slai?.present ? "ok" : "error"} /></div>
          <p className="muted small">{s.slai?.present ? "Running inside the SLAI repository." : "SLAI was not found; AIDAP is limited to its native checks."}</p>
          <div className="tw"><table><thead><tr><th>Component</th><th>State</th><th>Detail</th></tr></thead><tbody>
            <tr><td><b>Checkpoint manager</b></td><td><StateDot state={s.checkpointing?.ok ? "ok" : "error"} /></td><td className="small muted">{s.checkpointing?.detail}</td></tr>
            {agents.map(([k, a]) => (
              <tr key={k}><td><b>{AGENT_LABEL[k] ?? k}</b><div className="faint small">{a.agent}</div></td><td><StateDot state={a.state === "ready" ? "ok" : a.state === "unavailable" ? "error" : "unknown"} /></td>
                <td className="small muted" style={{ maxWidth: 560, overflowWrap: "anywhere" }}>{a.reason || a.note || ""}</td></tr>))}
          </tbody></table></div>
        </div>
        <div className="grid g3">
          <div className="card"><h3>Malware scanning</h3><StateDot state={s.malware_scanner?.ok ? "ok" : "unknown"} /><p className="small muted">{s.malware_scanner?.ok ? `Engine: ${s.malware_scanner.engine}` : "No antivirus engine is connected. The built-in check recognises the EICAR test marker only and never reports a file as clean."}</p></div>
          <div className="card"><h3>Billing</h3><StateDot state={s.billing?.ok ? "ok" : "error"} /><p className="small muted">Provider: {s.billing?.provider}. {s.billing?.detail}</p></div>
          <div className="card"><h3>Job queue</h3><div className="small muted">{Object.entries(s.queue ?? {}).map(([k, v]) => <div key={k}>{k}: {String(v)}</div>)}</div></div>
        </div>
      </div>
    </>
  );
}
