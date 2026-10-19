import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";
import { useAsync, useAction } from "../../lib/hooks";
import { Link, useQuery, useRouter } from "../../lib/router";
import { fmtBytes } from "../../lib/format";
import type { ConfigSummary, Project, Run, Stage } from "../../lib/types";
import { DecisionBadge, ErrorBox, Field, PageHeader, Spinner } from "../../components/ui";
import { STAGES } from "../../lib/content";

const SOURCES = [["unknown", "Unknown"], ["internal_doc", "Internal document"], ["published", "Published content"], ["customer_upload", "Customer upload"], ["third_party", "Third party"], ["generated", "Generated"]];
const CLASSES = [["public", "Public"], ["internal", "Internal"], ["confidential", "Confidential"], ["restricted", "Restricted"]];

type Phase = "idle" | "uploading" | "running" | "done" | "failed";

export function NewRun() {
  const { navigate } = useRouter();
  const preProject = useQuery().get("project") ?? "";
  const setup = useAsync(async () => {
    const [projects, profiles, policies, dests] = await Promise.all([
      api.get<Project[]>("/projects"), api.get<ConfigSummary[]>("/profiles"), api.get<ConfigSummary[]>("/policies"), api.get<any[]>("/destinations").catch(() => []),
    ]);
    return { projects: projects.filter((p) => !p.archived), profiles, policies, dests };
  }, []);
  const [f, setF] = useState({ project_id: preProject, profile_id: "", policy_id: "", destination_id: "", source_class: "unknown", classification: "internal", label: "", metadata: "" });
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [run, setRun] = useState<Run | null>(null);
  const [stages, setStages] = useState<Stage[]>([]);
  const [err, setErr] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const { run: act } = useAction();

  useEffect(() => {
    const d = setup.data; if (!d) return;
    const p = d.projects.find((x) => x.id === f.project_id) ?? d.projects[0];
    if (p && (!f.project_id || !d.projects.some((x) => x.id === f.project_id)))
      setF((x) => ({ ...x, project_id: p.id, profile_id: x.profile_id || p.default_profile_id || "rag_indexing", policy_id: x.policy_id || p.default_policy_id || "standard", destination_id: x.destination_id || p.default_destination_id || "" }));
  }, [setup.data]); // eslint-disable-line

  // poll the run while it is working
  useEffect(() => {
    if (phase !== "running" || !run) return;
    let stop = false;
    const tick = async () => {
      try {
        const [r, s] = await Promise.all([api.get<Run>(`/runs/${run.id}`), api.get<Stage[]>(`/runs/${run.id}/stages`)]);
        if (stop) return;
        setRun(r); setStages(s);
        if (r.state === "completed") setPhase("done");
        else if (r.state === "failed" || r.state === "cancelled") { setPhase("failed"); setErr(r.error || `The run ${r.state}.`); }
      } catch { /* transient; next tick retries */ }
    };
    const t = setInterval(tick, 1200); void tick();
    return () => { stop = true; clearInterval(t); };
  }, [phase, run?.id]); // eslint-disable-line

  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const choose = (x: File | undefined | null) => { if (x) { setFile(x); setPhase("idle"); setErr(""); setRun(null); } };

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setErr("");
    if (!file) { setErr("Choose a file to validate."); return; }
    let meta = "";
    if (f.metadata.trim()) { try { JSON.parse(f.metadata); meta = f.metadata; } catch { setErr("Metadata must be valid JSON, e.g. {\"owner\": \"HR\"}."); return; } }
    const fd = new FormData();
    fd.set("file", file);
    for (const [k, v] of Object.entries(f)) if (v && k !== "metadata") fd.set(k, v);
    if (meta) fd.set("metadata", meta);
    fd.set("idempotency_key", `ui-${crypto.randomUUID()}`);
    setPhase("uploading");
    const r = await act(() => api.upload<Run>("/runs", fd), { onError: (er) => { setPhase("idle"); setErr(Object.values(er.fields).join(" ") || er.message); } });
    if (r) { setRun(r); setPhase(r.state === "completed" ? "done" : "running"); }
  }

  if (setup.loading && !setup.data) return <Spinner />;
  if (setup.error) return <ErrorBox error={setup.error} retry={setup.reload} />;
  const d = setup.data!;
  const prof = d.profiles.find((p) => p.id === f.profile_id);
  const busy = phase === "uploading" || phase === "running";
  const cur = stages.filter((s) => s.state === "committed" || s.state === "skipped").length;

  return (
    <>
      <PageHeader title="New validation" sub="Choose what the input is for. AIDAP checks it against that purpose and returns a decision with evidence." />
      {!d.projects.length ? <div className="alert warn">You need a project first. <Link to="/app/projects">Create one</Link>.</div> : (
        <div className="grid split">
          <form className="stack" onSubmit={submit}>
            <div className={`drop${over ? " over" : ""}`} role="button" tabIndex={0} aria-label="Choose a file"
              onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); choose(e.dataTransfer.files[0]); }}>
              <b>{file ? file.name : "Drop a file here, or click to choose"}</b>
              <span className="muted small">{file ? fmtBytes(file.size) : "CSV, JSON, JSONL, TXT, Markdown, HTML, PDF, DOCX …"}</span>
              <input ref={input} type="file" hidden onChange={(e) => choose(e.target.files?.[0])} data-testid="file" />
            </div>
            <div className="card form">
              <div className="grid g2">
                <Field label="Project"><select value={f.project_id} onChange={set("project_id")}>{d.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
                <Field label="Intended use (profile)">
                  <select value={f.profile_id} onChange={set("profile_id")}>{d.profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
                </Field>
                <Field label="Policy"><select value={f.policy_id} onChange={set("policy_id")}>{d.policies.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
                <Field label="Destination" hint="Optional — controls delivery after a Pass.">
                  <select value={f.destination_id} onChange={set("destination_id")}><option value="">None (pull gate only)</option>{d.dests.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
                </Field>
                <Field label="Where did it come from?"><select value={f.source_class} onChange={set("source_class")}>{SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
                <Field label="Data classification"><select value={f.classification} onChange={set("classification")}>{CLASSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
              </div>
              {prof && <p className="muted small" style={{ margin: 0 }}>{prof.description}</p>}
              <Field label="Label" hint="Optional name to find this run later."><input value={f.label} onChange={set("label")} maxLength={120} /></Field>
              <Field label="Metadata (JSON)" hint="Owner, source revision, effective date — whatever your profile requires.">
                <textarea value={f.metadata} onChange={set("metadata")} placeholder='{"owner": "HR Team", "source_revision": "3", "effective_date": "2026-09-01"}' spellCheck={false} />
              </Field>
              {err && <div className="alert error" role="alert">{err}</div>}
              <div className="row"><button className="btn primary lg" disabled={busy || !file}>{busy ? "Validating…" : "Validate"}</button>
                {file && !busy && <button type="button" className="btn ghost" onClick={() => { setFile(null); setRun(null); setPhase("idle"); }}>Clear</button>}</div>
            </div>
          </form>

          <aside className="stack" aria-live="polite">
            <div className="card">
              <h3>Progress</h3>
              <ul className="phases">
                <li className={file ? "done" : ""}><span className="dot" />Input selected</li>
                <li className={phase === "uploading" ? "active" : phase !== "idle" ? "done" : ""}><span className="dot" />Uploaded and hashed</li>
                <li className={phase === "running" ? "active" : phase === "done" ? "done" : phase === "failed" ? "bad" : ""}><span className="dot" />
                  {phase === "running" ? `Running checks — ${cur} of ${STAGES.length} stages` : "Checks run (20-stage workflow)"}</li>
                <li className={phase === "done" ? "done" : phase === "failed" ? "bad" : ""}><span className="dot" />Decision and evidence</li>
              </ul>
            </div>
            {phase === "done" && run && (
              <div className="card">
                <div className="row between"><h3 style={{ margin: 0 }}>Result</h3><DecisionBadge decision={run.decision} big /></div>
                <p className="muted">{run.decision_detail?.rationale.summary ?? "The run finished."}</p>
                {run.decision_detail?.rationale.next_action && <p className="small"><b>Next:</b> {run.decision_detail.rationale.next_action}</p>}
                <div className="row">
                  <button className="btn primary" onClick={() => navigate(`/app/runs/${run.id}`)}>Open full result</button>
                  <button className="btn" onClick={() => { setFile(null); setRun(null); setPhase("idle"); }}>Validate another</button>
                </div>
              </div>
            )}
            {phase === "failed" && <div className="alert error" role="alert">{err}</div>}
            <div className="card flat small muted">
              <b style={{ color: "var(--text)" }}>Before you submit</b>
              <p style={{ margin: "6px 0 0" }}>Files up to your plan’s per-run limit are accepted. Native checks run in an isolated process; nothing leaves AIDAP unless your policy and destination allow it.</p>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
