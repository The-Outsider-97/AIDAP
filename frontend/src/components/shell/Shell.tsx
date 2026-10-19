import { useEffect, useState, type ReactNode } from "react";
import { Link, useRouter } from "../../lib/router";
import { useAccount } from "../../lib/account";
import { useAction, useTheme, useToast } from "../../lib/hooks";
import { api } from "../../lib/api";
import { Field, Modal, ThemeToggle } from "../ui";

export const BUSINESS_EMAIL = "info.remy3design@gmail.com";

export function Brand() {
  const [theme] = useTheme();
  return (
    <Link to="/" className="brand" aria-label="AIDAP home">
      <img src={theme === "dark" ? "/aidap-mark-dark.png" : "/aidap-mark-light.png"} alt="" width={40} height={40} />
      <span>AIDAP</span>
    </Link>
  );
}

const NAV: { title: string; items: { to: string; label: string }[] }[] = [
  { title: "Product", items: [
    { to: "/", label: "Overview" }, { to: "/methodology", label: "Methodology" }, { to: "/trust", label: "Trust & security" },
    { to: "/pricing", label: "Plans & pricing" } ] },
  { title: "Developers", items: [
    { to: "/docs", label: "API & SDK" }, { to: "/faq", label: "FAQ" }, { to: "/disclaimer", label: "Limits & disclaimer" } ] },
];

export function Header({ onMenu }: { onMenu: () => void }) {
  const { path, navigate } = useRouter();
  const { me, openAuth, logout } = useAccount();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest?.("[data-account-menu]")) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <header className="hdr">
      <div className="wrap">
        <button className="iconbtn" onClick={onMenu} aria-label="Open navigation"><span className="hamb"><i /></span></button>
        <Brand />
        <nav className="nav-inline" aria-label="Primary">
          <Link to="/pricing" className={path === "/pricing" ? "on" : ""}>Plans</Link>
          <Link to="/docs" className={path === "/docs" ? "on" : ""}>Docs</Link>
          <Link to="/trust" className={path === "/trust" ? "on" : ""}>Trust</Link>
        </nav>
        <span className="sp" />
        <ThemeToggle />
        {me ? (
          <div style={{ position: "relative" }} data-account-menu>
            <button className="btn sm" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="menu">{me.user.name} ▾</button>
            {open && (
              <div role="menu" className="card tight menu">
                <div className="muted small" style={{ marginBottom: 8 }}>{me.tenant.name} · {me.role} · {me.plan.name}</div>
                <div className="stack" style={{ gap: 4 }}>
                  <Link to="/app" className="btn sm ghost">Open workspace</Link>
                  <Link to="/app/settings" className="btn sm ghost">Settings</Link>
                  <button className="btn sm ghost" onClick={async () => { await logout(); navigate("/"); }}>Sign out</button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <>
            <button className="btn sm ghost" onClick={() => openAuth("login")}>Sign in</button>
            <button className="btn sm primary" onClick={() => openAuth("signup")}>Start free</button>
          </>
        )}
      </div>
    </header>
  );
}

export function NavigationPanel({ open, onClose, onContact }: { open: boolean; onClose: () => void; onContact: () => void }) {
  const { path } = useRouter();
  const { me } = useAccount();
  useEffect(() => { if (open) onClose(); /* close on navigation */ // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);
  return (
    <>
      {open && <div className="scrim" style={{ zIndex: 100, background: "rgba(0,0,0,.45)" }} onClick={onClose} />}
      <aside className={`drawer left${open ? " open" : ""}`} aria-hidden={!open} aria-label="Site navigation">
        <Brand />
        {me && (<><h4>Workspace</h4><Link className="item" to="/app">Dashboard</Link><Link className="item" to="/app/new">Validate an input</Link></>)}
        {NAV.map((g) => (
          <div key={g.title}><h4>{g.title}</h4>
            {g.items.map((i) => <Link key={i.to} className={`item${path === i.to ? " on" : ""}`} to={i.to}>{i.label}</Link>)}
          </div>
        ))}
        <h4>Company</h4>
        <button className="item" onClick={() => { onClose(); onContact(); }}>Contact sales</button>
        <a className="item" href={`mailto:${BUSINESS_EMAIL}`}>{BUSINESS_EMAIL}</a>
      </aside>
    </>
  );
}

export function SidePanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [toc, setToc] = useState<{ id: string; text: string }[]>([]);
  const { path } = useRouter();
  useEffect(() => {
    if (!open) return;
    setToc([...document.querySelectorAll<HTMLElement>("main h2[id], main section[id]")].map((e) => ({ id: e.id, text: e.dataset.title ?? e.querySelector("h2")?.textContent ?? e.id })));
  }, [open, path]);
  return (
    <>
      {open && <div className="scrim" style={{ zIndex: 100, background: "rgba(0,0,0,.45)" }} onClick={onClose} />}
      <aside className={`drawer right${open ? " open" : ""}`} aria-hidden={!open} aria-label="Page options">
        <h4>On this page</h4>
        {toc.length ? toc.map((t) => <a key={t.id} className="item" href={`#${t.id}`} onClick={onClose}>{t.text}</a>) : <p className="muted small">No sections on this page.</p>}
        <h4>Appearance</h4>
        <div className="item static"><span>Theme</span><ThemeToggle /></div>
        <h4>More</h4>
        <Link className="item" to="/pricing" onClick={onClose}>Plans & pricing</Link>
        <p className="faint small" style={{ marginTop: 28 }}>Powered by SLAI</p>
      </aside>
    </>
  );
}

export function FloatingLogoButton({ onClick }: { onClick: () => void }) {
  const [theme] = useTheme();
  return (
    <button className="fab" onClick={onClick} aria-label="Open page options">
      <img src={theme === "dark" ? "/aidap-mark-dark.png" : "/aidap-mark-light.png"} alt="" />
    </button>
  );
}

export function Footer({ onContact }: { onContact: () => void }) {
  return (
    <footer className="ftr">
      <div className="wrap">
        <div className="cols">
          <div>
            <Brand />
            <p className="muted small" style={{ marginTop: 12, maxWidth: 320 }}>
              A validation gate for AI inputs. AIDAP reports evidence and a decision; it does not certify that data is true, lawful or safe.
            </p>
          </div>
          <div><h4>Product</h4><Link to="/">Overview</Link><Link to="/methodology">Methodology</Link><Link to="/pricing">Plans</Link><Link to="/trust">Trust</Link></div>
          <div><h4>Developers</h4><Link to="/docs">API & SDK</Link><Link to="/faq">FAQ</Link><Link to="/disclaimer">Limits</Link></div>
          <div><h4>Contact</h4><button className="linkbtn" style={{ color: "var(--text)", textDecoration: "none" }} onClick={onContact}>Talk to sales</button><a href={`mailto:${BUSINESS_EMAIL}`}>{BUSINESS_EMAIL}</a></div>
        </div>
        <p className="faint small" style={{ marginTop: 28 }}>© {new Date().getFullYear()} AIDAP · Powered by SLAI · Prices exclude VAT.</p>
      </div>
    </footer>
  );
}

export function ContactModal({ onClose, topic = "enterprise" }: { onClose: () => void; topic?: string }) {
  const { me } = useAccount();
  const [f, setF] = useState({ name: me?.user.name ?? "", email: me?.user.email ?? "", company: me?.tenant.name ?? "", topic, message: "", website: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [sent, setSent] = useState(false);
  const { busy, run } = useAction();
  const { push } = useToast();
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal title="Talk to us" onClose={onClose}>
      {sent ? (
        <div className="stack"><div className="alert ok">Thanks — your message was sent to our team. We reply from {BUSINESS_EMAIL}, usually within one business day.</div>
          <button className="btn" onClick={onClose}>Close</button></div>
      ) : (
        <form className="form" onSubmit={async (e) => {
          e.preventDefault(); setErrs({});
          const r = await run(() => api.post("/contact", f), { onError: (er) => { setErrs(er.fields); if (!Object.keys(er.fields).length) push("error", er.message); } });
          if (r) setSent(true);
        }}>
          <p className="muted small" style={{ margin: 0 }}>Enterprise plans, private deployment, SSO, security questions. Messages go to {BUSINESS_EMAIL}.</p>
          <Field label="Your name" error={errs.name}><input value={f.name} onChange={set("name")} required autoComplete="name" /></Field>
          <Field label="Work email" error={errs.email}><input type="email" value={f.email} onChange={set("email")} required autoComplete="email" /></Field>
          <Field label="Company" error={errs.company}><input value={f.company} onChange={set("company")} autoComplete="organization" /></Field>
          <Field label="Topic">
            <select value={f.topic} onChange={set("topic")}>
              <option value="enterprise">Enterprise plan</option><option value="sales">Pricing / sales</option><option value="support">Support</option>
              <option value="security">Security review</option><option value="other">Something else</option>
            </select>
          </Field>
          <Field label="How can we help?" error={errs.message}><textarea value={f.message} onChange={set("message")} required minLength={10} /></Field>
          {/* honeypot: hidden from people, filled by bots */}
          <input aria-hidden tabIndex={-1} autoComplete="off" value={f.website} onChange={set("website")} style={{ position: "absolute", left: -9999, width: 1, height: 1, opacity: 0 }} name="website" />
          <button className="btn primary" disabled={busy}>{busy ? "Sending…" : "Send message"}</button>
        </form>
      )}
    </Modal>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { path } = useRouter();
  const routeKey = path.startsWith("/app") ? "app" : path;         // the workspace animates its own pages; public pages animate here
  const [nav, setNav] = useState(false);
  const [side, setSide] = useState(false);
  const [contact, setContact] = useState(false);
  useEffect(() => {
    const h = () => setContact(true);
    window.addEventListener("aidap:contact", h);
    return () => window.removeEventListener("aidap:contact", h);
  }, []);
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <Header onMenu={() => setNav(true)} />
      <NavigationPanel open={nav} onClose={() => setNav(false)} onContact={() => setContact(true)} />
      <SidePanel open={side} onClose={() => setSide(false)} />
      <main id="main" key={routeKey} className="page-in">{children}</main>
      <Footer onContact={() => setContact(true)} />
      <FloatingLogoButton onClick={() => setSide(true)} />
      {contact && <ContactModal onClose={() => setContact(false)} />}
    </>
  );
}
export const openContact = () => window.dispatchEvent(new Event("aidap:contact"));
