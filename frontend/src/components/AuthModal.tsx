import { useState } from "react";
import { useAccount } from "../lib/account";
import { useAction } from "../lib/hooks";
import { useRouter } from "../lib/router";
import { ApiError } from "../lib/api";
import { Field, Modal } from "./ui";

export function AuthModal() {
  const { authOpen, closeAuth, openAuth } = useAccount();
  if (!authOpen) return null;
  return authOpen === "login" ? <Login onClose={closeAuth} swap={() => openAuth("signup")} /> : <Signup onClose={closeAuth} swap={() => openAuth("login")} />;
}

function Login({ onClose, swap }: { onClose: () => void; swap: () => void }) {
  const { login } = useAccount();
  const { navigate, path } = useRouter();
  const [f, setF] = useState({ email: "", password: "", code: "" });
  const [needCode, setNeedCode] = useState(false);
  const [error, setError] = useState("");
  const { busy, run } = useAction();
  return (
    <Modal title="Sign in" onClose={onClose}>
      <form className="form" onSubmit={async (e) => {
        e.preventDefault(); setError("");
        const me = await run(() => login(f), { onError: (er: ApiError) => { if (er.code === "mfa_required") setNeedCode(true); else setError(er.message); } });
        if (me) { onClose(); if (!path.startsWith("/app")) navigate("/app"); }
      }}>
        {error && <div className="alert error" role="alert">{error}</div>}
        <Field label="Email"><input type="email" required autoComplete="username" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Password"><input type="password" required autoComplete="current-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        {needCode && <Field label="Verification code" hint="From your authenticator app, or a recovery code."><input autoFocus inputMode="numeric" autoComplete="one-time-code" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>}
        <button className="btn primary" disabled={busy}>{busy ? "Signing in…" : needCode ? "Verify and sign in" : "Sign in"}</button>
        <div className="row between small">
          <button type="button" className="linkbtn" onClick={() => { onClose(); navigate("/forgot-password"); }}>Forgot password?</button>
          <button type="button" className="linkbtn" onClick={swap}>Create an account</button>
        </div>
      </form>
    </Modal>
  );
}

function Signup({ onClose, swap }: { onClose: () => void; swap: () => void }) {
  const { signup } = useAccount();
  const { navigate } = useRouter();
  const [f, setF] = useState({ name: "", email: "", organization: "", password: "", accept_terms: false });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const { busy, run } = useAction();
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal title="Start on the free plan" onClose={onClose}>
      <form className="form" onSubmit={async (e) => {
        e.preventDefault(); setErrs({}); setError("");
        const me = await run(() => signup(f), { onError: (er) => { setErrs(er.fields); setError(Object.keys(er.fields).length ? "" : er.message); } });
        if (me) { onClose(); navigate("/app"); }
      }}>
        <p className="muted small" style={{ margin: 0 }}>Developer plan: 100 validation runs a month, no card needed.</p>
        {error && <div className="alert error" role="alert">{error}</div>}
        <Field label="Your name" error={errs.name}><input required autoComplete="name" value={f.name} onChange={set("name")} /></Field>
        <Field label="Work email" error={errs.email}><input type="email" required autoComplete="email" value={f.email} onChange={set("email")} /></Field>
        <Field label="Organization" error={errs.organization}><input required autoComplete="organization" value={f.organization} onChange={set("organization")} /></Field>
        <Field label="Password" hint="At least 12 characters. Avoid common passwords." error={errs.password}>
          <input type="password" required minLength={12} autoComplete="new-password" value={f.password} onChange={set("password")} />
        </Field>
        <label className="check"><input type="checkbox" checked={f.accept_terms} onChange={(e) => setF({ ...f, accept_terms: e.target.checked })} required />
          <span>I accept the service terms and understand that AIDAP reports evidence for a decision and does not certify data.</span></label>
        {errs.accept_terms && <span className="err">{errs.accept_terms}</span>}
        <button className="btn primary" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
        <div className="small"><button type="button" className="linkbtn" onClick={swap}>I already have an account</button></div>
      </form>
    </Modal>
  );
}
