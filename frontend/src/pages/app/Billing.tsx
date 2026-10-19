import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction, useAsync, useToast } from "../../lib/hooks";
import { Link, useQuery, useRouter } from "../../lib/router";
import { fmtDate, fmtEur, fmtNum, titleCase } from "../../lib/format";
import type { Plan, Usage } from "../../lib/types";
import { PlanCards } from "../../components/PlanCards";
import { Confirm, ErrorBox, Meter, PageHeader, Spinner } from "../../components/ui";
import { openContact, BUSINESS_EMAIL } from "../../components/shell/Shell";

interface BillingState { subscription: Record<string, any>; plan: Plan; effective_plan: Plan; provider: string; sandbox: boolean; can_manage: boolean; manual: boolean }

export function Billing() {
  const { me, refresh } = useAccount();
  const { navigate } = useRouter();
  const { push } = useToast();
  const params = useQuery();
  const st = useAsync(() => api.get<BillingState>("/billing"), []);
  const usage = useAsync(() => api.get<Usage>("/usage"), []);
  const hist = useAsync(() => api.get<any[]>("/usage/history"), []);
  const plans = useAsync(() => api.get<{ plans: Plan[] }>("/plans"), []);
  const { busy, run: act } = useAction();
  const [pending, setPending] = useState<string>("");
  const [cancel, setCancel] = useState(false);
  const [topup, setTopup] = useState(1000);
  const sandboxSession = params.get("sandbox_session");
  const checkout = params.get("checkout");

  useEffect(() => { if (checkout === "success") { push("ok", "Thanks — your subscription is being activated."); void refresh(); st.reload(); usage.reload(); navigate("/app/billing", { replace: true }); } }, [checkout]); // eslint-disable-line

  async function go(fn: () => Promise<{ url: string; sandbox?: boolean }>) {
    const r = await act(fn);
    if (!r?.url) return;
    // The sandbox "checkout" is a page of this app: follow it in place whatever base URL the server was configured with.
    if (r.sandbox) { const u = new URL(r.url, window.location.origin); navigate(u.pathname + u.search); }
    else window.location.assign(r.url);
  }
  async function completeSandbox() {
    const r = await act(() => api.post("/billing/sandbox/complete", { session_id: sandboxSession }), { ok: "Simulated payment completed" });
    if (r) { await refresh(); navigate("/app/billing", { replace: true }); st.reload(); usage.reload(); }
  }

  if (st.error && !st.data) return <ErrorBox error={st.error} retry={st.reload} />;
  if (!st.data || !usage.data) return <Spinner />;
  const s = st.data, u = usage.data, sub = s.subscription;
  const canManage = s.can_manage;
  const rows: [string, string, number | null | undefined][] = [
    ["Validation runs", `${fmtNum(u.used.runs)} of ${fmtNum(u.limits.runs)}`, u.ratios.runs],
    ["Deterministic scanning", `${u.used.scan_gb.toFixed(2)} of ${(u.limits.scan_bytes / 1e9).toFixed(1)} GB`, u.ratios.scan],
    ["Managed inference", `${fmtEur(u.used.inference_cents, 2)} of ${fmtEur(u.limits.inference_cents, 2)}`, u.ratios.inference],
    ["Projects", `${u.used.projects} of ${u.limits.projects}`, u.ratios.projects],
    ["Seats", `${u.used.seats} of ${u.limits.seats}`, u.ratios.seats],
  ];
  return (
    <>
      <PageHeader title="Usage & billing" sub={`Period ${u.period} · prices exclude VAT`} />
      {sandboxSession && (
        <div className="card" style={{ borderColor: "var(--review)", marginBottom: 20 }}>
          <h3>Simulated checkout</h3>
          <p className="muted">This installation uses the billing <b>sandbox</b>. No payment is taken and no card is needed. Completing this step switches your plan as a real payment would.</p>
          <div className="row"><button className="btn primary" disabled={busy} onClick={completeSandbox}>Complete simulated payment{params.get("plan") ? ` for ${titleCase(params.get("plan")!)}` : params.get("topup") ? ` (${fmtEur(Number(params.get("topup")))} top-up)` : ""}</button>
            <button className="btn ghost" onClick={() => navigate("/app/billing", { replace: true })}>Cancel</button></div>
        </div>)}
      {s.sandbox && !sandboxSession && <div className="alert warn" style={{ marginBottom: 16 }}>Billing sandbox: checkout is simulated and no money moves. A production deployment uses Stripe.</div>}
      {sub.status === "past_due" && <div className="alert error" style={{ marginBottom: 16 }}><b>Payment is past due.</b> Your plan falls back to Developer after a 7-day grace period unless payment succeeds. {canManage && s.provider !== "none" && <button className="linkbtn" onClick={() => go(() => api.post("/billing/portal"))}>Update payment method</button>}</div>}
      {sub.cancel_at_period_end && <div className="alert warn" style={{ marginBottom: 16 }}>Your subscription ends on {fmtDate(sub.current_period_end)}, then the account moves to Developer.</div>}

      <div className="grid split rev" style={{ marginBottom: 28 }}>
        <div className="card">
          <div className="row between"><h3 style={{ margin: 0 }}>{s.effective_plan.name} plan</h3><span className="tag accent">{sub.status.replace("_", " ")}</span></div>
          <p className="muted small">{s.effective_plan.tagline}</p>
          <dl className="small" style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 14px" }}>
            <dt className="muted">Price</dt><dd style={{ margin: 0 }}>{s.effective_plan.contact_sales ? "Custom" : s.effective_plan.price_month_cents ? `${fmtEur(s.effective_plan.price_month_cents)} / month` : "Free"}</dd>
            <dt className="muted">Billing</dt><dd style={{ margin: 0 }}>{s.manual ? "Arranged with sales" : s.provider === "none" ? "Not configured" : s.provider}</dd>
            <dt className="muted">{sub.cancel_at_period_end ? "Ends" : "Renews"}</dt><dd style={{ margin: 0 }}>{fmtDate(sub.current_period_end)}</dd>
            <dt className="muted">Evidence retention</dt><dd style={{ margin: 0 }}>{s.effective_plan.evidence_retention_days} days</dd>
            <dt className="muted">Support</dt><dd style={{ margin: 0 }}>{s.effective_plan.support}</dd>
          </dl>
          {canManage && !s.manual && s.provider !== "none" && me?.plan.id !== "developer" && (
            <div className="row" style={{ marginTop: 14 }}><button className="btn sm" onClick={() => go(() => api.post("/billing/portal"))} disabled={busy}>Manage payment & invoices</button>
              {!sub.cancel_at_period_end && <button className="btn sm danger" onClick={() => setCancel(true)}>Cancel subscription</button>}</div>)}
          {s.manual && <p className="small muted" style={{ marginBottom: 0 }}>This plan is managed by our team. Questions: <a href={`mailto:${BUSINESS_EMAIL}`}>{BUSINESS_EMAIL}</a></p>}
        </div>
        <div className="card">
          <h3>This period</h3>
          <div className="stack">{rows.map(([l, t, r]) => <div key={l}><div className="row between small"><span>{l}</span><span className="muted">{t}</span></div><Meter value={r} label={l} /></div>)}</div>
          {u.ratios.runs !== null && u.ratios.runs >= 1 && <div className="alert warn small" style={{ marginTop: 14 }}>The run allowance is used up. New runs are {sub.auto_overage ? "billed as overage" : "held"} until the next period or a plan change.</div>}
        </div>
      </div>

      {canManage && (
        <div className="grid g2" style={{ marginBottom: 28 }}>
          <div className="card">
            <h3>When an allowance runs out</h3>
            <div className="stack">
              <label className="check"><input type="checkbox" checked={!!sub.hold_on_exhaustion} disabled={busy} onChange={async (e) => { if (await act(() => api.post("/billing/settings", { hold_on_exhaustion: e.target.checked }), { ok: "Saved" })) st.reload(); }} /><span><b>Hold new runs</b><br /><span className="muted small">Nothing is processed or billed beyond the plan until you decide.</span></span></label>
              <label className="check"><input type="checkbox" checked={!!sub.auto_overage} disabled={busy || s.provider === "none"} onChange={async (e) => { if (await act(() => api.post("/billing/settings", { auto_overage: e.target.checked }), { ok: "Saved" })) { st.reload(); usage.reload(); } }} /><span><b>Allow overage</b><br /><span className="muted small">Off by default. Keeps runs flowing past the allowance at metered rates.</span></span></label>
            </div>
          </div>
          <div className="card">
            <h3>Inference top-up</h3>
            <p className="muted small">Add managed-inference credit for model-assisted checks. Native deterministic checks never use it.</p>
            <div className="row"><select aria-label="Amount" style={{ maxWidth: 160 }} value={topup} onChange={(e) => setTopup(Number(e.target.value))}>{[500, 1000, 2500, 5000, 10000].map((c) => <option key={c} value={c}>{fmtEur(c)}</option>)}</select>
              <button className="btn" disabled={busy || s.provider === "none" || s.manual} onClick={() => go(() => api.post("/billing/topup", { amount_cents: topup }))}>Add credit</button></div>
            {sub.topup_inference_cents > 0 && <p className="small muted" style={{ marginBottom: 0 }}>Top-up balance: {fmtEur(sub.topup_inference_cents, 2)}</p>}
          </div>
        </div>)}

      <h2 id="plans" style={{ fontSize: "1.3rem" }}>Plans</h2>
      {plans.data && (
        canManage && s.provider !== "none" && !s.manual ? (
          <PlanCards plans={plans.data.plans} current={s.effective_plan.id} busy={pending} onSelect={async (p) => {
            if (p.id === "developer") { setCancel(true); return; }
            setPending(p.id); await go(() => api.post("/billing/checkout", { plan_id: p.id })); setPending("");
          }} cta={(p) => (p.price_month_cents ?? 0) > (s.effective_plan.price_month_cents ?? 0) ? `Upgrade to ${p.name}` : `Switch to ${p.name}`} />
        ) : (
          <>
            <PlanCards plans={plans.data.plans} current={s.effective_plan.id} onSelect={() => openContact()} cta={() => "Ask about this plan"} />
            <p className="muted small" style={{ marginTop: 10 }}>{!canManage ? "Only the account owner or an admin with billing rights can change the plan." : s.manual ? "Your plan is managed by our team — contact us to change it." : "Self-serve billing is not configured on this installation."}</p>
          </>)
      )}
      {hist.data && hist.data.length > 0 && (
        <><h2 style={{ fontSize: "1.3rem", marginTop: 32 }}>History</h2>
          <div className="tw"><table><thead><tr><th>Period</th><th>Runs</th><th>Scanned</th><th>Inference</th></tr></thead>
            <tbody>{hist.data.map((h) => <tr key={h.period}><td>{h.period}</td><td>{fmtNum(h.runs)}</td><td>{(h.scan_bytes / 1e9).toFixed(3)} GB</td><td>{fmtEur(h.inference_cents, 2)}</td></tr>)}</tbody></table></div></>)}
      <p className="faint small" style={{ marginTop: 18 }}>Need Enterprise, SSO or private deployment? <button className="linkbtn" onClick={openContact}>Contact sales</button> · <Link to="/pricing">Public pricing page</Link></p>
      {cancel && <Confirm title="Cancel your subscription?" danger confirm="Cancel at period end" busy={busy} onNo={() => setCancel(false)} onYes={async () => { if (await act(() => api.post("/billing/cancel"), { ok: "Subscription will end at the period end" })) { setCancel(false); st.reload(); } }}>
        <p>You keep your current plan until {fmtDate(sub.current_period_end)}. After that the account moves to the free Developer plan; evidence older than 7 days is then removed by retention.</p></Confirm>}
    </>
  );
}
