import { useEffect, useMemo, useState } from "react";
import { api, type ApiError } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction, useAsync } from "../../lib/hooks";
import { Link, useRouter } from "../../lib/router";
import { fmtDate } from "../../lib/format";
import type { ConfigSummary, Doc, SuiteSummary, Suggestion } from "../../lib/types";
import { Confirm, DecisionBadge, Empty, ErrorBox, Field, Modal, PageHeader, SeverityBadge, Spinner, Tabs } from "../../components/ui";

type Kind = "profile" | "policy";
const base = (k: Kind) => (k === "profile" ? "/profiles" : "/policies");
const NOUN = { profile: "intended-use profile", policy: "policy" };

export function ConfigsList({ kind }: { kind: Kind }) {
  const { can } = useAccount();
  const { navigate } = useRouter();
  const q = useAsync(() => api.get<ConfigSummary[]>(base(kind)), [kind]);
  const [creating, setCreating] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [f, setF] = useState({ id: "", name: "", from: "" });
  const [err, setErr] = useState("");
  const { busy, run: act } = useAction();
  const write = can("policies.write");
  async function create() {
    setErr("");
    const src = await act(() => api.get(`${base(kind)}/${f.from}`), { onError: (e) => setErr(e.message) });
    if (!src) return;
    const v = [...src.versions].sort((a: any, b: any) => b.version - a.version)[0];
    const doc = { ...v.document, id: f.id, name: f.name };
    const r = await act(() => api.post(base(kind), { id: f.id, name: f.name, document: doc, note: `copied from ${f.from}` }), { onError: (e) => setErr(Object.values(e.fields)[0] ?? e.message) });
    if (r) navigate(`/app/${kind === "profile" ? "profiles" : "policies"}/${f.id}`);
  }
  return (
    <>
      <PageHeader title={kind === "profile" ? "Intended-use profiles" : "Policies"}
        sub={kind === "profile" ? "Intended use, destination and required checks. Data is judged against its purpose." : "How severities become Pass, Review, Quarantine or Block. Policies are versioned; publishing one needs a second approver."}
        actions={write && <>{kind === "profile" && <button className="btn" onClick={() => setSuggesting(true)}>From a sample</button>}<button className="btn primary" onClick={() => { setF({ id: "", name: "", from: q.data?.[0]?.id ?? "" }); setCreating(true); }}>New {kind}</button></>} />
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : (
        <div className="tw"><table><thead><tr><th>Name</th><th>Description</th><th>Published</th><th>Draft</th></tr></thead>
          <tbody>{q.data.map((c) => (
            <tr key={c.id} className="click" onClick={() => navigate(`/app/${kind === "profile" ? "profiles" : "policies"}/${c.id}`)}>
              <td><Link to={`/app/${kind === "profile" ? "profiles" : "policies"}/${c.id}`} onClick={(e) => e.stopPropagation()}><b>{c.name}</b></Link> {c.builtin && <span className="tag">built-in</span>}<div className="faint small"><code>{c.id}</code></div></td>
              <td className="small muted" style={{ maxWidth: 520 }}>{c.description}</td><td>{c.published_version ? `v${c.published_version}` : <span className="faint">—</span>}</td><td>{c.draft_version ? <span className="tag accent">v{c.draft_version}</span> : <span className="faint">—</span>}</td></tr>))}</tbody></table></div>)}
      {suggesting && <SuggestProfile onClose={() => setSuggesting(false)} onSaved={(pid) => navigate(`/app/profiles/${pid}`)} />}
      {creating && q.data && (
        <Modal title={`New ${NOUN[kind]}`} onClose={() => setCreating(false)}>
          <div className="form">
            <Field label="Start from"><select value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })}>{q.data.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
            <Field label="Name"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Identifier" hint="Letters, digits, dot, dash, underscore. Cannot be changed later."><input value={f.id} onChange={(e) => setF({ ...f, id: e.target.value })} pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{1,63}" /></Field>
            {err && <div className="alert error">{err}</div>}
            <button className="btn primary" disabled={busy || !f.id || !f.name || !f.from} onClick={create}>Create draft copy</button>
          </div>
        </Modal>)}
    </>
  );
}

interface Version { version: number; status: "draft" | "published" | "superseded" | string; document: Doc; note: string; created_at?: string; created_by?: string }
interface ConfigFull { id: string; name: string; builtin: boolean; kind: Kind; versions: Version[] }
interface Lint { issues: { level: string; path: string; message: string }[]; errors: number; warnings: number; publishable: boolean }

export function ConfigEditor({ kind, id }: { kind: Kind; id: string }) {
  const { can } = useAccount();
  const write = can("policies.write"), publish = can("policies.publish");
  const q = useAsync(() => api.get<ConfigFull>(`${base(kind)}/${id}`), [kind, id]);
  const [tab, setTab] = useState<"edit" | "simulate" | "versions">("edit");
  const cfg = q.data;
  const sorted = useMemo(() => [...(cfg?.versions ?? [])].sort((a, b) => b.version - a.version), [cfg]);
  const draft = sorted.find((v) => v.status === "draft");
  const published = sorted.find((v) => v.status === "published");
  const shown = draft ?? published ?? sorted[0];
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [lint, setLint] = useState<Lint | null>(null);
  const [err, setErr] = useState("");
  const { busy, run: act } = useAction();
  const [confirm, setConfirm] = useState<null | "publish" | "discard">(null);
  const [suites, setSuites] = useState<string[]>([]);
  const [gateProfile, setGateProfile] = useState("");
  const [gateErr, setGateErr] = useState<ApiError | null>(null);
  useEffect(() => { if (shown) { setText(JSON.stringify(shown.document, null, 2)); setLint(null); setErr(""); } }, [cfg?.id, shown?.version, shown?.status]); // eslint-disable-line

  if (q.error && !cfg) return <ErrorBox error={q.error} retry={q.reload} />;
  if (!cfg || !shown) return <Spinner />;
  const editable = write && !cfg.builtin;
  const parse = (): Doc | null => { try { return JSON.parse(text); } catch (e) { setErr("This is not valid JSON: " + (e as Error).message); return null; } };

  async function doLint() {
    setErr(""); const d = parse(); if (!d) return;
    const r = await act(() => api.post<Lint>("/lint", { [kind]: d }), { onError: (e) => setErr(e.message) });
    if (r) setLint(r);
  }
  async function save() {
    setErr(""); const d = parse(); if (!d) return;
    const r = await act(() => (draft ? api.put(`${base(kind)}/${id}/draft`, { document: d, note }) : api.post(`${base(kind)}/${id}/versions`, { document: d, note })), { ok: "Draft saved", onError: (e) => setErr(Object.values(e.fields)[0] ?? e.message) });
    if (r) q.reload();
  }
  return (
    <>
      <p className="small" style={{ margin: "0 0 8px" }}><Link to={`/app/${kind === "profile" ? "profiles" : "policies"}`}>← {kind === "profile" ? "Profiles" : "Policies"}</Link></p>
      <PageHeader title={cfg.name} sub={<><code>{cfg.id}</code> {cfg.builtin && <span className="tag">built-in · read-only</span>} {published && <span className="tag">published v{published.version}</span>} {draft && <span className="tag accent">draft v{draft.version}</span>}</>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "edit", label: "Document" }, { id: "simulate", label: "Simulate" }, { id: "versions", label: "Versions" }]} />
      {tab === "edit" && (
        <div className="stack">
          {cfg.builtin && <div className="alert info">Built-in templates cannot be edited. Create a copy from the list page to customise it.</div>}
          <textarea aria-label="Document JSON" value={text} onChange={(e) => setText(e.target.value)} readOnly={!editable} spellCheck={false}
            style={{ minHeight: 440, fontFamily: "ui-monospace, Consolas, monospace", fontSize: ".85rem" }} />
          {err && <div className="alert error" role="alert">{err}</div>}
          {lint && (
            <div className={`alert ${lint.errors ? "error" : lint.warnings ? "warn" : "ok"}`}>
              <b>{lint.errors} error(s), {lint.warnings} warning(s)</b> — {lint.publishable ? "publishable" : "not publishable"}
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{lint.issues.map((i, n) => <li key={n}><b>{i.level}</b> <code>{i.path}</code> {i.message}</li>)}</ul>
            </div>)}
          <div className="row">
            <button className="btn" onClick={doLint} disabled={busy}>Check document</button>
            {editable && <>
              <input style={{ maxWidth: 260 }} placeholder="Change note (optional)" aria-label="Change note" value={note} onChange={(e) => setNote(e.target.value)} />
              <button className="btn primary" onClick={save} disabled={busy}>{draft ? "Save draft" : "Save as new draft"}</button>
              {draft && publish && <button className="btn" onClick={() => setConfirm("publish")} disabled={busy}>Publish v{draft.version}…</button>}
              {draft && <button className="btn ghost" onClick={() => setConfirm("discard")} disabled={busy}>Discard draft</button>}
            </>}
          </div>
        </div>)}
      {tab === "simulate" && <Simulate kind={kind} getDoc={parse} id={id} />}
      {tab === "versions" && (
        <div className="tw"><table><thead><tr><th>Version</th><th>Status</th><th>Note</th><th>When</th></tr></thead>
          <tbody>{sorted.map((v) => <tr key={v.version}><td>v{v.version}</td><td><span className={`tag${v.status === "published" ? " accent" : ""}`}>{v.status}</span></td><td className="small muted">{v.note}</td><td className="small">{v.created_at ? fmtDate(v.created_at) : "—"}</td></tr>)}</tbody></table></div>)}
      {confirm === "publish" && draft && (
        <Confirm title={`Publish v${draft.version}?`} confirm="Publish" busy={busy} onNo={() => { setConfirm(null); setGateErr(null); }} onYes={async () => {
          setGateErr(null);
          const body = suites.length ? { suite_ids: suites, profile_id: kind === "policy" ? gateProfile : undefined } : {};
          const r = await act(() => api.post(`${base(kind)}/${id}/versions/${draft.version}/publish`, body), {
            ok: "Published", onError: (e) => { if (e.code === "suite_failed") setGateErr(e); else { setErr(e.message); setConfirm(null); } } });
          if (r) { setConfirm(null); setSuites([]); q.reload(); } }}>
          <p>New runs use this version immediately; earlier runs keep the version they were assessed with. Publishing needs a second person if another eligible approver exists — you cannot publish your own draft.</p>
          <PublishGate kind={kind} suites={suites} setSuites={setSuites} profile={gateProfile} setProfile={setGateProfile} />
          {gateErr && (
            <div className="alert error" role="alert">{gateErr.message}
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{((gateErr.details.failing ?? []) as any[]).map((c) => (
                <li key={c.case_id}>{c.name}: expected {c.expected}, got {c.actual ?? "no result"}{c.error ? ` (${c.error})` : ""}{c.missing_codes?.length ? `; missing ${c.missing_codes.join(", ")}` : ""}</li>))}</ul></div>)}
        </Confirm>)}
      {confirm === "discard" && <Confirm title="Discard the draft?" danger confirm="Discard" busy={busy} onNo={() => setConfirm(null)} onYes={async () => {
        const r = await act(() => api.del(`${base(kind)}/${id}/draft`), { ok: "Draft discarded" }); setConfirm(null); if (r) q.reload(); }}><p>The published version is not affected.</p></Confirm>}
    </>
  );
}

function Simulate({ kind, getDoc, id }: { kind: Kind; getDoc: () => Doc | null; id: string }) {
  const [content, setContent] = useState('[{"title": "Leave policy", "body": "Contact maria@example.org for questions about carrying over leave into the next year."}]');
  const [meta, setMeta] = useState('{"owner": "HR"}');
  const [dest, setDest] = useState("local_index");
  const [source, setSource] = useState("internal_doc");
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState("");
  const { busy, run: act } = useAction();
  async function go() {
    setErr(""); setRes(null);
    const d = getDoc(); if (!d) { setErr("Fix the JSON on the Document tab first."); return; }
    let metadata = {}; try { metadata = meta.trim() ? JSON.parse(meta) : {}; } catch { setErr("Metadata must be valid JSON."); return; }
    const body: any = { content, filename: "sample.json", destination: dest, source_class: source, metadata };
    if (kind === "profile") { body.profile = d; body.policy_id = "standard"; } else { body.policy = d; body.profile_id = "rag_indexing"; }
    const r = await act(() => api.post("/simulate", body), { onError: (e) => setErr(Object.values(e.fields)[0] ?? e.message) });
    if (r) setRes(r);
  }
  return (
    <div className="grid g2" style={{ alignItems: "start" }}>
      <div className="stack">
        <div className="alert info small">Simulation uses AIDAP’s deterministic checks on a sample, with your unsaved edits. Nothing is stored, no quota is used, and SLAI agents are not called. A simulation can never authorize release.</div>
        <Field label="Sample content"><textarea style={{ minHeight: 180, fontFamily: "ui-monospace, Consolas, monospace" }} value={content} onChange={(e) => setContent(e.target.value)} spellCheck={false} /></Field>
        <Field label="Metadata (JSON)"><textarea style={{ minHeight: 70 }} value={meta} onChange={(e) => setMeta(e.target.value)} spellCheck={false} /></Field>
        <div className="grid g2">
          <Field label="Destination"><select value={dest} onChange={(e) => setDest(e.target.value)}>{["local_index", "internal_model", "training_set", "external_model", "public_endpoint"].map((x) => <option key={x}>{x}</option>)}</select></Field>
          <Field label="Source"><select value={source} onChange={(e) => setSource(e.target.value)}>{["internal_doc", "published", "customer_upload", "third_party", "generated", "unknown"].map((x) => <option key={x}>{x}</option>)}</select></Field>
        </div>
        {err && <div className="alert error" role="alert">{err}</div>}
        <button className="btn primary" onClick={go} disabled={busy}>{busy ? "Simulating…" : `Simulate ${kind === "profile" ? "this profile" : "this policy"}`}</button>
      </div>
      <div className="card">
        <h3>Result</h3>
        {!res ? <p className="muted">Run a simulation to see the decision.</p> : (
          <div className="stack">
            <div className="row"><DecisionBadge decision={res.decision} big /><span className="tag">simulation</span></div>
            <p>{res.summary}</p>
            {res.findings?.slice(0, 20).map((f: any) => <div key={f.id} className="small"><SeverityBadge severity={f.severity} /> <b>{f.title}</b> <code className="faint">{f.code}</code></div>)}
            {res.lint?.issues?.length > 0 && <div className="small muted">{res.lint.issues.length} lint note(s).</div>}
            <p className="faint small">{res.note}</p>
          </div>)}
      </div>
    </div>
  );
}
export { Empty };

/** Optional pre-publish check: run chosen test suites against the draft and stop if any example changes outcome. */
function PublishGate({ kind, suites, setSuites, profile, setProfile }: { kind: Kind; suites: string[]; setSuites: (s: string[]) => void; profile: string; setProfile: (p: string) => void }) {
  const { me } = useAccount();
  const enabled = !!me?.plan.features.includes("test_suites");
  const list = useAsync(() => (enabled ? api.get<SuiteSummary[]>("/suites") : Promise.resolve([] as SuiteSummary[])), [enabled]);
  const profiles = useAsync(() => (kind === "policy" && enabled ? api.get<ConfigSummary[]>("/profiles") : Promise.resolve([] as ConfigSummary[])), [kind, enabled]);
  const usable = (list.data ?? []).filter((x) => x.cases > 0);
  if (!enabled || !usable.length) return null;
  const pick = profile || profiles.data?.[0]?.id || "";
  return (
    <fieldset className="card tight" style={{ margin: 0 }}>
      <legend className="small muted">Test before publishing</legend>
      {usable.map((x) => (
        <label key={x.id} className="row small" style={{ gap: 8 }}>
          <input type="checkbox" checked={suites.includes(x.id)} onChange={(e) => setSuites(e.target.checked ? [...suites, x.id] : suites.filter((i) => i !== x.id))} />
          {x.name} <span className="faint">({x.cases} examples)</span></label>))}
      {kind === "policy" && suites.length > 0 && (
        <Field label="Profile to test with"><select value={pick} onChange={(e) => { setProfile(e.target.value); }} onFocus={() => !profile && setProfile(pick)}>{(profiles.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>)}
    </fieldset>
  );
}

/** Draft a profile from a representative sample. Nothing is stored until the draft is saved as a new profile. */
export function SuggestProfile({ onClose, onSaved }: { onClose: () => void; onSaved: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [task, setTask] = useState("");
  const [res, setRes] = useState<Suggestion | null>(null);
  const [f, setF] = useState({ id: "", name: "" });
  const [err, setErr] = useState("");
  const { busy, run: act } = useAction();
  return (
    <Modal title="Draft a profile from a sample" onClose={onClose} wide>
      {!res ? (
        <div className="form">
          <p className="muted small" style={{ margin: 0 }}>Upload a representative sample. AIDAP infers field types, ranges, allowed values and sensitive data deterministically. The sample is not stored.</p>
          <Field label="Sample file" hint="CSV, JSON, JSONL or text."><input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
          <Field label="Task" hint="Optional, for example rag_indexing or training_batch."><input value={task} onChange={(e) => setTask(e.target.value)} /></Field>
          {err && <div className="alert error">{err}</div>}
          <button className="btn primary" disabled={busy || !file} onClick={async () => {
            setErr(""); const fd = new FormData(); fd.set("file", file!); if (task) fd.set("task", task);
            const r = await act(() => api.upload<Suggestion>("/profiles/suggest", fd), { onError: (e) => setErr(Object.values(e.fields)[0] ?? e.message) });
            if (r) { setRes(r); setF({ id: `draft_${file!.name.replace(/\.[^.]*$/, "").replace(/[^A-Za-z0-9_.-]+/g, "_").slice(0, 40)}`, name: String((r.profile as any).name ?? "") }); } }}>{busy ? "Analyzing…" : "Analyze sample"}</button>
        </div>
      ) : (
        <div className="form">
          <p className="small" style={{ margin: 0 }}>{res.records.toLocaleString()} records · {res.format}. {res.lint.errors} error(s), {res.lint.warnings} warning(s).</p>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{res.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
          <pre className="code" style={{ maxHeight: 260, overflow: "auto" }}>{JSON.stringify(res.profile, null, 2)}</pre>
          <div className="grid g2">
            <Field label="Name"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Identifier" hint="Letters, digits, dot, dash, underscore."><input value={f.id} onChange={(e) => setF({ ...f, id: e.target.value })} /></Field>
          </div>
          {err && <div className="alert error">{err}</div>}
          <div className="row"><button className="btn" onClick={() => setRes(null)}>Back</button>
            <button className="btn primary" disabled={busy || !f.id || !f.name} onClick={async () => {
              setErr(""); const doc = { ...res.profile, id: f.id, name: f.name };
              const r = await act(() => api.post("/profiles", { id: f.id, name: f.name, document: doc, note: "drafted from a sample" }), { ok: "Draft saved", onError: (e) => setErr(Object.values(e.fields)[0] ?? e.message) });
              if (r) onSaved(f.id); }}>Save as draft profile</button></div>
        </div>)}
    </Modal>
  );
}
