import { useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction } from "../../lib/hooks";
import { Link, useQuery, useRouter } from "../../lib/router";
import { Field } from "../../components/ui";

function Box({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="wrap" style={{ maxWidth: 480, paddingTop: 64 }}><div className="card"><h1 style={{ fontSize: "1.6rem" }}>{title}</h1>{children}</div></div>;
}

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const { busy, run } = useAction();
  return (
    <Box title="Reset your password">
      {done ? <div className="alert ok">If that address has an account, a reset link is on its way. The link is valid for a short time.</div> : (
        <form className="form" onSubmit={async (e) => { e.preventDefault(); if (await run(() => api.post("/auth/password/reset-request", { email }))) setDone(true); }}>
          <Field label="Email"><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" /></Field>
          <button className="btn primary" disabled={busy}>Send reset link</button>
        </form>)}
      <p className="small" style={{ marginTop: 16 }}><Link to="/">Back to AIDAP</Link></p>
    </Box>
  );
}

export function ResetPassword() {
  const token = useQuery().get("token") ?? "";
  const [pw, setPw] = useState("");
  const [done, setDone] = useState(false);
  const [err, setErr] = useState("");
  const { openAuth } = useAccount();
  const { busy, run } = useAction();
  return (
    <Box title="Choose a new password">
      {!token ? <div className="alert error">This reset link is missing its token. Request a new one.</div> : done ? (
        <div className="stack"><div className="alert ok">Password updated. All other sessions were signed out.</div><button className="btn primary" onClick={() => openAuth("login")}>Sign in</button></div>
      ) : (
        <form className="form" onSubmit={async (e) => { e.preventDefault(); setErr(""); if (await run(() => api.post("/auth/password/reset-confirm", { token, new_password: pw }), { onError: (x) => setErr(x.fields.new_password ?? x.message) })) setDone(true); }}>
          {err && <div className="alert error" role="alert">{err}</div>}
          <Field label="New password" hint="At least 12 characters."><input type="password" required minLength={12} value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" /></Field>
          <button className="btn primary" disabled={busy}>Update password</button>
        </form>)}
    </Box>
  );
}

export function AcceptInvite() {
  const token = useQuery().get("token") ?? "";
  const [f, setF] = useState({ name: "", password: "" });
  const [err, setErr] = useState("");
  const { refresh } = useAccount();
  const { navigate } = useRouter();
  const { busy, run } = useAction();
  return (
    <Box title="Join your team on AIDAP">
      {!token ? <div className="alert error">This invitation link is missing its token.</div> : (
        <form className="form" onSubmit={async (e) => { e.preventDefault(); setErr("");
          const r = await run(() => api.post("/auth/invitations/accept", { token, ...f }), { onError: (x) => setErr(x.message) });
          if (r) { await refresh(); navigate("/app"); } }}>
          {err && <div className="alert error" role="alert">{err}</div>}
          <p className="muted small">If you already have an AIDAP account, leave the fields empty and sign in first; otherwise choose your name and password.</p>
          <Field label="Your name"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoComplete="name" /></Field>
          <Field label="Password" hint="At least 12 characters."><input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" /></Field>
          <button className="btn primary" disabled={busy}>Accept invitation</button>
        </form>)}
    </Box>
  );
}
