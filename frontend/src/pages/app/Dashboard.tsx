import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAsync } from "../../lib/hooks";
import { Link } from "../../lib/router";
import { ago, fmtNum, titleCase } from "../../lib/format";
import type { Usage, Run } from "../../lib/types";
import { DecisionBadge, Empty, ErrorBox, Kpi, Meter, PageHeader, Spinner } from "../../components/ui";

interface Dash {
  runs_total: number; by_decision: Record<string, number>; series: ({ day: string } & Record<string, number | string>)[];
  top_findings: { code: string; count: number }[]; open_reviews: number; held_quarantine: number; open_alerts: number;
  recent: Run[]; usage: Usage;
}

function Chart({ series }: { series: Dash["series"] }) {
  const days: string[] = [];
  for (let i = 13; i >= 0; i--) days.push(new Date(Date.now() - i * 864e5).toISOString().slice(0, 10));
  const by = Object.fromEntries(series.map((s) => [s.day, s]));
  const tot = (d: string) => ["pass", "review", "quarantine", "block"].reduce((a, k) => a + Number(by[d]?.[k] ?? 0), 0);
  const max = Math.max(1, ...days.map(tot));
  const W = 560, H = 150, bw = W / 14;
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H + 20}`} role="img" aria-label="Runs per day for the last 14 days, by decision">
      <line x1="0" x2={W} y1={H} y2={H} />
      {days.map((d, i) => {
        let y = H;
        const bars = (["pass", "review", "quarantine", "block"] as const).map((k, j) => {
          const n = Number(by[d]?.[k] ?? 0); const h = (n / max) * (H - 10); y -= h;
          return n ? <rect key={k} className={"prqb"[j]} x={i * bw + 6} y={y} width={bw - 12} height={h} rx={2}><title>{`${d}: ${n} ${k}`}</title></rect> : null;
        });
        return <g key={d}>{bars}{i % 2 === 0 && <text x={i * bw + bw / 2} y={H + 14} textAnchor="middle">{d.slice(5)}</text>}</g>;
      })}
    </svg>
  );
}

export function Dashboard() {
  const { me } = useAccount();
  const q = useAsync(() => api.get<Dash>("/dashboard"), []);
  const d = q.data;
  return (
    <>
      <PageHeader title="Dashboard" sub={`${me?.tenant.name} · ${me?.plan.name} plan`}
        actions={<Link className="btn primary" to="/app/new">New validation</Link>} />
      {q.loading && !d ? <Spinner /> : q.error ? <ErrorBox error={q.error} retry={q.reload} /> : d && (
        <div className="stack lg">
          <div className="grid g4">
            <Kpi value={fmtNum(d.runs_total)} label="Runs this period" to="/app/runs" />
            <Kpi value={d.open_reviews} label="Open reviews" to="/app/reviews" />
            <Kpi value={d.held_quarantine} label="Held in quarantine" to="/app/quarantine" />
            <Kpi value={d.open_alerts} label="Open alerts" to="/app/alerts" />
          </div>
          <div className="grid split">
            <div className="card">
              <div className="row between"><h3>Decisions, last 14 days</h3>
                <div className="row small">{(["pass", "review", "quarantine", "block"] as const).map((k) => <DecisionBadge key={k} decision={k} />)}</div></div>
              {d.runs_total ? <Chart series={d.series} /> : <Empty title="No runs yet">Validate your first input to see decisions here.</Empty>}
            </div>
            <div className="card">
              <h3>Usage this period</h3>
              <div className="stack">
                {([["runs", "Validation runs", (u: Usage) => `${fmtNum(u.used.runs)} / ${fmtNum(u.limits.runs)}`],
                   ["scan_bytes", "Scanned data", (u: Usage) => `${u.used.scan_gb.toFixed(2)} / ${(u.limits.scan_bytes / 1e9).toFixed(1)} GB`],
                   ["projects", "Projects", (u: Usage) => `${u.used.projects} / ${u.limits.projects}`],
                   ["seats", "Seats", (u: Usage) => `${u.used.seats} / ${u.limits.seats}`]] as const).map(([k, label, f]) => (
                  <div key={k}><div className="row between small"><span>{label}</span><span className="muted">{f(d.usage)}</span></div><Meter value={d.usage.ratios[k]} label={label} /></div>
                ))}
                <Link to="/app/billing" className="small">Usage & billing →</Link>
              </div>
            </div>
          </div>
          <div className="grid g2">
            <div className="card">
              <h3>Recent runs</h3>
              {d.recent.length ? (
                <div className="tw"><table><tbody>{d.recent.map((r) => (
                  <tr key={r.id}><td><Link to={`/app/runs/${r.id}`}>{r.label || r.filename}</Link><div className="faint small">{ago(r.created_at)}</div></td><td className="right"><DecisionBadge decision={r.decision} state={r.state} /></td></tr>
                ))}</tbody></table></div>
              ) : <Empty title="Nothing here yet" />}
            </div>
            <div className="card">
              <h3>Most common findings</h3>
              {d.top_findings.length ? (
                <div className="tw"><table><tbody>{d.top_findings.map((f) => (
                  <tr key={f.code}><td><code>{f.code}</code></td><td className="right">{f.count}</td></tr>
                ))}</tbody></table></div>
              ) : <Empty title="No findings yet" />}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
export { titleCase };
