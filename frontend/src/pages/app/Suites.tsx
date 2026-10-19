import { useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction, useAsync } from "../../lib/hooks";
import { Link, useRouter } from "../../lib/router";
import { ago, fmtBytes, fmtDate } from "../../lib/format";
import type { ConfigSummary, SuiteFull, SuiteRun, SuiteSummary } from "../../lib/types";
import { Confirm, DecisionBadge, Empty, ErrorBox, Field, Modal, PageHeader, Spinner } from "../../components/ui";

const DECISIONS = ["pass", "review", "quarantine", "block"] as const;
const DESTS = [["local_index", "Local index"], ["training", "Training"], ["external_api", "External API"], ["public", "Public"]];

function Locked() {
  return <Empty title="Test suites are available from the Starter plan" action={<Link className="btn primary" to="/app/billing">View plans</Link>}>
    A suite holds adjudicated examples and checks that a profile or policy still decides them as expected, before a change is published.</Empty>;
}

function Summary({ s }: { s: SuiteRun["summary"] }) {
  return (
    <span className="small">
      <b className={s.all_passed ? "ok-t" : "bad-t"}>{s.passed} of {s.total} as expected</b>
      {s.looser_than_expected > 0 && <span className="dir looser"> · {s.looser_than_expected} looser</span>}
      {s.stricter_than_expected > 0 && <span className="dir stricter"> · {s.stricter_than_expected} stricter</span>}
      {s.errors > 0 && <span className="warn-t"> · {s.errors} errors</span>}
    </span>
  );
}

export function SuitesList() {
  const { can, me } = useAccount();
  const { navigate } = useRouter();
  const enabled = !!me?.plan.features.includes("test_suites");
  const q = useAsync(() => (enabled ? api.get<SuiteSummary[]>("/suites") : Promise.resolve([] as SuiteSummary[])), [enabled]);
  const [creating, setCreating] = useState(false);
  const [f, setF] = useState({ name: "", description: "" });
  const [err, setErr] = useState("");
  const { busy, run: act } = useAction();
  const write = can("policies.write") && enabled;
  return (
    <>
      <PageHeader title="Test suites" sub="Adjudicated examples that a profile and policy must keep deciding the same way. Run them on demand or as a gate before publishing."
        actions={write && <button className="btn primary" onClick={() => { setF({ name: "", description: "" }); setErr(""); setCreating(true); }}>New suite</button>} />
      {!enabled ? <Locked /> : q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !q.data.length ? (
        <Empty title="No suites yet">Create a suite and add examples with the decision you expect for each.</Empty>
      ) : (
        <div className="tw"><table><thead><tr><th>Suite</th><th>Examples</th><th>Last run</th></tr></thead>
          <tbody>{q.data.map((s) => (
            <tr key={s.id} className="click" onClick={() => navigate(`/app/suites/${s.id}`)}>
              <td><Link to={`/app/suites/${s.id}`} onClick={(e) => e.stopPropagation()}><b>{s.name}</b></Link><div className="faint small">{s.description}</div></td>
              <td>{s.cases}</td>
              <td>{s.last_run ? <><Summary s={s.last_run.summary} /><div className="faint small">{ago(s.last_run.created_at)} · {s.last_run.profile_ref}</div></> : <span className="faint">Not run</span>}</td></tr>))}</tbody></table></div>)}
      {creating && (
        <Modal title="New test suite" onClose={() => setCreating(false)}>
          <div className="form">
            <Field label="Name"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Description" hint="Optional."><input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
            {err && <div className="alert error">{err}</div>}
            <button className="btn primary" disabled={busy || f.name.trim().length < 2} onClick={async () => {
              setErr(""); const r = await act(() => api.post<SuiteSummary>("/suites", f), { onError: (e) => setErr(Object.values(e.fields)[0] ?? e.message) });
              if (r) navigate(`/app/suites/${r.id}`); }}>Create suite</button>
          </div>
        </Modal>)}
    </>
  );
}

export function SuiteDetail({ id }: { id: string }) {
  const { can, me } = useAccount();
  const { navigate } = useRouter();
  const enabled = !!me?.plan.features.includes("test_suites");
  const q = useAsync(() => api.get<SuiteFull>(`/suites/${id}`), [id]);
  const cfg = useAsync(async () => ({ profiles: await api.get<ConfigSummary[]>("/profiles"), policies: await api.get<ConfigSummary[]>("/policies") }), []);
  const [profile, setProfile] = useState("");
  const [policy, setPolicy] = useState("");
  const [result, setResult] = useState<SuiteRun | null>(null);
  const [adding, setAdding] = useState(false);
  const [confirm, setConfirm] = useState<null | "delete" | { case_id: string }>(null);
  const { busy, run: act } = useAction();
  const write = can("policies.write") && enabled;
  if (!enabled) return <Locked />;
  if (q.error && !q.data) return <ErrorBox error={q.error} retry={q.reload} />;
  const s = q.data;
  if (!s) return <Spinner />;
  const shown = result ?? s.runs[0] ?? null;
  const chosenProfile = profile || cfg.data?.profiles[0]?.id || "";
  const rows = shown ? Object.fromEntries(shown.cases.map((c) => [c.case_id, c])) : {};
  return (
    <>
      <PageHeader title={s.name} sub={s.description || "Test suite"} actions={<>
        <Link className="btn" to="/app/suites">All suites</Link>
        {write && <button className="btn" onClick={() => setAdding(true)}>Add example</button>}
        {write && <button className="btn danger" onClick={() => setConfirm("delete")}>Delete</button>}
      </>} />
      <div className="stack lg">
        <div className="card form">
          <h3>Run</h3>
          <div className="grid g2" style={{ alignItems: "start" }}>
            <Field label="Profile"><select value={chosenProfile} onChange={(e) => setProfile(e.target.value)}>{(cfg.data?.profiles ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
            <Field label="Policy" hint="Default policy when left unchanged."><select value={policy} onChange={(e) => setPolicy(e.target.value)}><option value="">Default</option>{(cfg.data?.policies ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          </div>
          <div className="row" style={{ gap: 12 }}>
            <button className="btn primary" disabled={busy || !s.cases.length || !chosenProfile || !can("runs.submit")} onClick={async () => {
              const r = await act(() => api.post<SuiteRun>(`/suites/${id}/run`, { profile_id: chosenProfile, policy_id: policy }), { ok: "Suite run complete" });
              if (r) { setResult(r); q.reload(); } }}>{busy ? "Running…" : "Run suite"}</button>
            {shown && <Summary s={shown.summary} />}
          </div>
          {shown && <p className="faint small" style={{ margin: 0 }}>{fmtDate(shown.created_at)} · {shown.profile_ref} · {shown.policy_ref}. {shown.note}</p>}
        </div>

        <div className="card">
          <h3>Examples ({s.cases.length})</h3>
          {!s.cases.length ? <p className="muted">No examples yet.</p> : (
            <div className="tw"><table><thead><tr><th>Example</th><th>Expected</th><th>Result</th><th /></tr></thead>
              <tbody>{s.cases.map((c) => {
                const r = rows[c.id];
                return (
                  <tr key={c.id}>
                    <td><b>{c.name}</b><div className="faint small">{c.filename} · {fmtBytes(c.size)}{c.expected_codes.length > 0 && <> · expects <code>{c.expected_codes.join(", ")}</code></>}</div></td>
                    <td><DecisionBadge decision={c.expected} /></td>
                    <td>{r ? (r.error ? <span className="warn-t small">{r.error}</span> : <>
                      <DecisionBadge decision={r.actual} />{r.direction && <span className={`dir ${r.direction}`}> {r.direction}</span>}
                      {r.missing_codes.length > 0 && <div className="small warn-t">Missing: <code>{r.missing_codes.join(", ")}</code></div>}
                      {r.changed && <div className="faint small">was {r.was ?? "—"}</div>}</>) : <span className="faint">—</span>}</td>
                    <td className="right">{write && <button className="btn sm" onClick={() => setConfirm({ case_id: c.id })}>Remove</button>}</td>
                  </tr>);
              })}</tbody></table></div>)}
        </div>

        {s.runs.length > 0 && (
          <div className="card">
            <h3>Run history</h3>
            <div className="tw"><table><thead><tr><th>When</th><th>Profile · policy</th><th>Outcome</th></tr></thead>
              <tbody>{s.runs.map((r) => <tr key={r.id} className="click" onClick={() => setResult(r)}><td>{fmtDate(r.created_at)}</td><td className="small">{r.profile_ref} · {r.policy_ref}</td><td><Summary s={r.summary} /></td></tr>)}</tbody></table></div>
          </div>)}
        <p className="faint small">Suites use deterministic checks only, so a result is repeatable. Example content is stored sealed and is deleted with the suite. To block a publish on failure, select the suite when publishing a profile or policy version.</p>
      </div>
      {adding && <AddCase suiteId={id} onClose={() => setAdding(false)} onDone={() => { setAdding(false); q.reload(); }} />}
      {confirm === "delete" && <Confirm title="Delete this suite?" confirm="Delete suite" danger busy={busy} onNo={() => setConfirm(null)}
        onYes={async () => { if (await act(() => api.del(`/suites/${id}`), { ok: "Suite deleted" })) navigate("/app/suites"); }}><p>The suite, its examples and its run history are removed.</p></Confirm>}
      {confirm && typeof confirm === "object" && <Confirm title="Remove this example?" confirm="Remove" danger busy={busy} onNo={() => setConfirm(null)}
        onYes={async () => { if (await act(() => api.del(`/suites/${id}/cases/${confirm.case_id}`), { ok: "Example removed" })) { setConfirm(null); setResult(null); q.reload(); } }}><p>The stored content is deleted.</p></Confirm>}
    </>
  );
}

function AddCase({ suiteId, onClose, onDone }: { suiteId: string; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ name: "", expected: "pass", codes: "", destination: "local_index", text: "" });
  const [file, setFile] = useState<File | null>(null);
  const [err, setErr] = useState("");
  const { busy, run: act } = useAction();
  const ready = (file || f.text.trim()) && f.name.trim();
  return (
    <Modal title="Add an example" onClose={onClose} wide>
      <div className="form">
        <div className="grid g2">
          <Field label="Name"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Expected decision"><select value={f.expected} onChange={(e) => setF({ ...f, expected: e.target.value })}>{DECISIONS.map((d) => <option key={d} value={d}>{d[0].toUpperCase() + d.slice(1)}</option>)}</select></Field>
        </div>
        <Field label="Expected finding codes" hint="Optional, comma separated. The run fails if any is missing."><input value={f.codes} onChange={(e) => setF({ ...f, codes: e.target.value })} placeholder="privacy.pii.email" /></Field>
        <Field label="Destination"><select value={f.destination} onChange={(e) => setF({ ...f, destination: e.target.value })}>{DESTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
        <Field label="File" hint="Up to 200 KB."><input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
        {!file && <Field label="Or paste content"><textarea rows={6} value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} spellCheck={false} /></Field>}
        {err && <div className="alert error">{err}</div>}
        <button className="btn primary" disabled={busy || !ready} onClick={async () => {
          setErr("");
          const fd = new FormData();
          fd.set("name", f.name); fd.set("expected", f.expected); fd.set("destination", f.destination);
          const codes = f.codes.split(",").map((c) => c.trim()).filter(Boolean); if (codes.length) fd.set("expected_codes", JSON.stringify(codes));
          if (file) fd.set("file", file); else { fd.set("content", f.text); fd.set("filename", "pasted.txt"); }
          if (await act(() => api.upload(`/suites/${suiteId}/cases`, fd), { ok: "Example added", onError: (e) => setErr(Object.values(e.fields)[0] ?? e.message) })) onDone();
        }}>Add example</button>
      </div>
    </Modal>
  );
}
