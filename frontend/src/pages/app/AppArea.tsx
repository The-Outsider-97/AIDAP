import { useEffect } from "react";
import { useAccount } from "../../lib/account";
import { useAsync } from "../../lib/hooks";
import { api } from "../../lib/api";
import { Link, Routes, useRouter, type RouteDef } from "../../lib/router";
import { Empty } from "../../components/ui";
import { Dashboard } from "./Dashboard";
import { NewRun } from "./NewRun";
import { RunsList, RunDetail } from "./Runs";
import { ReviewsList, ReviewDetail } from "./Reviews";
import { QuarantineList, QuarantineDetail } from "./Quarantine";
import { Projects } from "./Projects";
import { ConfigsList, ConfigEditor } from "./Configs";
import { Baselines, Destinations, Schedules } from "./Workspace";
import { ApiKeys, Team } from "./Team";
import { Billing } from "./Billing";
import { Alerts, Audit, SystemStatus } from "./Ops";
import { Settings } from "./Settings";

const ROUTES: RouteDef[] = [
  { path: "/app", render: () => <Dashboard /> },
  { path: "/app/new", render: () => <NewRun /> },
  { path: "/app/runs", render: () => <RunsList /> },
  { path: "/app/runs/:id", render: (p) => <RunDetail id={p.id} /> },
  { path: "/app/reviews", render: () => <ReviewsList /> },
  { path: "/app/reviews/:id", render: (p) => <ReviewDetail id={p.id} /> },
  { path: "/app/quarantine", render: () => <QuarantineList /> },
  { path: "/app/quarantine/:id", render: (p) => <QuarantineDetail id={p.id} /> },
  { path: "/app/projects", render: () => <Projects /> },
  { path: "/app/profiles", render: () => <ConfigsList kind="profile" /> },
  { path: "/app/profiles/:id", render: (p) => <ConfigEditor kind="profile" id={p.id} /> },
  { path: "/app/policies", render: () => <ConfigsList kind="policy" /> },
  { path: "/app/policies/:id", render: (p) => <ConfigEditor kind="policy" id={p.id} /> },
  { path: "/app/baselines", render: () => <Baselines /> },
  { path: "/app/destinations", render: () => <Destinations /> },
  { path: "/app/schedules", render: () => <Schedules /> },
  { path: "/app/api-keys", render: () => <ApiKeys /> },
  { path: "/app/team", render: () => <Team /> },
  { path: "/app/billing", render: () => <Billing /> },
  { path: "/app/alerts", render: () => <Alerts /> },
  { path: "/app/audit", render: () => <Audit /> },
  { path: "/app/system", render: () => <SystemStatus /> },
  { path: "/app/settings", render: () => <Settings /> },
];

interface Item { to: string; label: string; perm?: string; badge?: "open_reviews" | "held_quarantine" | "open_alerts" }
const GROUPS: { title: string; items: Item[] }[] = [
  { title: "Validate", items: [
    { to: "/app", label: "Dashboard" }, { to: "/app/new", label: "New validation", perm: "runs.submit" }, { to: "/app/runs", label: "Runs", perm: "runs.read" },
    { to: "/app/reviews", label: "Reviews", perm: "reviews.read", badge: "open_reviews" }, { to: "/app/quarantine", label: "Quarantine", perm: "reviews.read", badge: "held_quarantine" } ] },
  { title: "Configure", items: [
    { to: "/app/projects", label: "Projects", perm: "runs.read" }, { to: "/app/profiles", label: "Intended-use profiles", perm: "policies.read" },
    { to: "/app/policies", label: "Policies", perm: "policies.read" }, { to: "/app/baselines", label: "Baselines", perm: "runs.read" },
    { to: "/app/destinations", label: "Destinations & webhooks", perm: "deliveries.read" }, { to: "/app/schedules", label: "Schedules", perm: "runs.read" } ] },
  { title: "Operate", items: [
    { to: "/app/alerts", label: "Alerts", perm: "alerts.read", badge: "open_alerts" }, { to: "/app/audit", label: "Audit log", perm: "audit.read" },
    { to: "/app/system", label: "System & SLAI status" } ] },
  { title: "Account", items: [
    { to: "/app/billing", label: "Usage & billing", perm: "usage.read" }, { to: "/app/api-keys", label: "API keys", perm: "apikeys.manage" },
    { to: "/app/team", label: "Team", perm: "members.manage" }, { to: "/app/settings", label: "Settings" } ] },
];

export function AppArea() {
  const { me, openAuth, can } = useAccount();
  const { path } = useRouter();
  useEffect(() => { if (!me) openAuth("login"); }, [me, openAuth]);
  const counts = useAsync(() => (me ? api.get("/dashboard") : Promise.resolve(null)), [me?.tenant.id, path]);
  if (!me) return <div className="wrap"><Empty title="Sign in to open your workspace" action={<button className="btn primary" onClick={() => openAuth("login")}>Sign in</button>} /></div>;
  const c = counts.data as Record<string, number> | null;
  return (
    <div className="app">
      <nav className="side" aria-label="Workspace">
        {GROUPS.map((g) => (
          <div key={g.title}>
            <h5>{g.title}</h5>
            {g.items.filter((i) => !i.perm || can(i.perm)).map((i) => {
              const on = i.to === "/app" ? path === "/app" : path === i.to || path.startsWith(i.to + "/");
              const n = i.badge && c ? c[i.badge] : 0;
              return <Link key={i.to} to={i.to} className={on ? "on" : ""} aria-current={on ? "page" : undefined}>{i.label}{n > 0 && <span className="badge">{n}</span>}</Link>;
            })}
          </div>
        ))}
      </nav>
      <div className="main">
        <Routes routes={ROUTES} fallback={<Empty title="Page not found" action={<Link className="btn" to="/app">Back to dashboard</Link>}>That page doesn’t exist in the workspace.</Empty>} />
      </div>
    </div>
  );
}
