import { useAccount } from "../lib/account";
import { FEATURE_LABEL } from "../lib/content";
import { fmtNum, planPrice } from "../lib/format";
import type { Plan } from "../lib/types";
import { openContact } from "./shell/Shell";

const ORDER = ["developer", "starter", "team", "business", "enterprise"];

export function PlanCards({ plans, current, onSelect, busy, cta }: {
  plans: Plan[]; current?: string; busy?: string; cta?: (p: Plan) => string;
  onSelect?: (p: Plan) => void;
}) {
  const { openAuth, me } = useAccount();
  const list = [...plans].sort((a, b) => ORDER.indexOf(a.id) - ORDER.indexOf(b.id));
  return (
    <div className="plans">
      {list.map((p) => {
        const isCur = current === p.id;
        return (
          <article key={p.id} className={`plan${p.id === "team" ? " pop" : ""}${isCur ? " current" : ""}`} aria-label={`${p.name} plan`}>
            <div className="row between"><h3 style={{ margin: 0 }}>{p.name}</h3>{p.id === "team" && <span className="tag accent">Most teams</span>}{isCur && <span className="tag">Current</span>}</div>
            <div className="price">{planPrice(p)}{!p.contact_sales && <small> / month</small>}</div>
            <p className="muted small" style={{ margin: 0 }}>{p.tagline}</p>
            <ul>
              {p.contact_sales ? (
                <>
                  <li>Custom volumes and retention</li><li>Single sign-on</li><li>Private deployment option</li>
                  {p.annual_hint && <li>{p.annual_hint}</li>}{p.onboarding_hint && <li>{p.onboarding_hint}</li>}
                </>
              ) : (
                <>
                  <li>{fmtNum(p.included_runs)} validation runs / month</li>
                  <li>{p.included_scan_gb < 1 ? `${p.included_scan_gb} GB` : `${fmtNum(p.included_scan_gb)} GB`} deterministic scanning</li>
                  <li>{p.inference_allowance_cents ? `€${p.inference_allowance_cents / 100} managed-inference allowance` : "Native checks only"}</li>
                  <li>{p.max_projects} project{p.max_projects > 1 ? "s" : ""} · {p.seats} seat{p.seats > 1 ? "s" : ""}</li>
                  <li>{p.evidence_retention_days}-day evidence retention</li>
                  <li>Up to {p.max_run_mb} MB per run</li>
                  {p.features.filter((f) => f !== "api" && FEATURE_LABEL[f]).slice(0, 5).map((f) => <li key={f}>{FEATURE_LABEL[f]}</li>)}
                </>
              )}
            </ul>
            {p.contact_sales ? (
              <button className="btn" onClick={openContact}>Contact sales</button>
            ) : onSelect ? (
              <button className={`btn${p.id === "team" ? " primary" : ""}`} disabled={isCur || busy === p.id} onClick={() => onSelect(p)}>
                {isCur ? "Your plan" : busy === p.id ? "Opening…" : cta?.(p) ?? "Choose plan"}
              </button>
            ) : (
              <button className={`btn${p.id === "team" ? " primary" : ""}`} onClick={() => (me ? window.location.assign("/app/billing") : openAuth("signup"))}>
                {p.price_month_cents === 0 ? "Start free" : "Get started"}
              </button>
            )}
          </article>
        );
      })}
    </div>
  );
}
