import { api } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import type { Plan } from "../../lib/types";
import { PlanCards } from "../../components/PlanCards";
import { ErrorBox, Spinner } from "../../components/ui";
import { openContact } from "../../components/shell/Shell";
import { fmtNum } from "../../lib/format";

interface PlansRes { plans: Plan[]; vat: string; note: string; sandbox: boolean; provider: string; contact: string }

export function Pricing() {
  const q = useAsync(() => api.get<PlansRes>("/plans"), []);
  return (
    <div className="wrap" style={{ paddingTop: 56 }}>
      <section id="plans" data-title="Plans">
        <span className="eyebrow">Plans & pricing</span>
        <h1>Pay for validation runs, not seats-and-surprises.</h1>
        <p className="muted" style={{ maxWidth: "64ch" }}>Every plan includes the full decision model, evidence bundles and the API. Plans differ in monthly volume, retention and workflow features. Prices are per month and exclude VAT.</p>
        {q.loading && !q.data ? <Spinner /> : q.error ? <ErrorBox error={q.error} retry={q.reload} /> : q.data && (
          <>
            {q.data.sandbox && <div className="alert warn" style={{ margin: "12px 0" }}>This installation uses the billing sandbox: checkout is simulated and no payment is taken.</div>}
            <PlanCards plans={q.data.plans} />
            <p className="faint small" style={{ marginTop: 14 }}>{q.data.vat} {q.data.note}</p>
          </>
        )}
      </section>

      <section id="compare" data-title="Compare" style={{ paddingTop: 56 }}>
        <h2>Compare plans</h2>
        {q.data && (
          <div className="tw"><table>
            <thead><tr><th>Plan</th><th>Runs / month</th><th>Scanning</th><th>Projects</th><th>Seats</th><th>Retention</th><th>Max run size</th><th>Support</th></tr></thead>
            <tbody>{q.data.plans.filter((p) => !p.contact_sales).map((p) => (
              <tr key={p.id}><td><b>{p.name}</b></td><td>{fmtNum(p.included_runs)}</td><td>{p.included_scan_gb} GB</td><td>{p.max_projects}</td><td>{p.seats}</td><td>{p.evidence_retention_days} days</td><td>{p.max_run_mb} MB</td><td>{p.support}</td></tr>
            ))}<tr><td><b>Enterprise</b></td><td colSpan={7} className="muted">Custom — contact sales</td></tr></tbody>
          </table></div>
        )}
      </section>

      <section id="how-billing-works" data-title="How billing works" style={{ paddingTop: 56 }}>
        <h2>How billing works</h2>
        <div className="grid g3">
          <div className="card"><h3>Runs are metered once</h3><p className="muted">One billable run is recorded when the policy decision is committed. Retries and restarts never bill twice.</p></div>
          <div className="card"><h3>Held, not surprised</h3><p className="muted">When an allowance is used up, new runs are held. Turn on overage or buy a top-up if you prefer to keep going.</p></div>
          <div className="card"><h3>Small inputs round up</h3><p className="muted">Scan volume counts at least 1 KiB per run; 1 GB is 10⁹ bytes. Native deterministic checks cost you no inference.</p></div>
        </div>
        <p className="faint small" style={{ marginTop: 16 }}>Plan names, prices and allowances are launch hypotheses and may change with usage data.</p>
        <div className="cta"><h2>Need SSO, private deployment or custom retention?</h2><p className="muted">Enterprise is quoted individually.</p><button className="btn primary lg" onClick={openContact}>Contact sales</button></div>
      </section>
    </div>
  );
}
