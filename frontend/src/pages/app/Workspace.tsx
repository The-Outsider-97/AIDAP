import { useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction, useAsync } from "../../lib/hooks";
import { Link } from "../../lib/router";
import { ago, fmtDate } from "../../lib/format";
import type { ConfigSummary, Page, Project, Run } from "../../lib/types";
import { Confirm, CopyButton, Empty, ErrorBox, Field, Modal, PageHeader, Spinner } from "../../components/ui";

/* ------------------------------------------------------------------ baselines */
export function Baselines() {
  const { can } = useAccount();
  const q = useAsync(async () => {
    const [baselines, runs, projects] = await Promise.all([api.get<any[]>("/baselines"), api.get<Page<Run>>("/runs", { state: "completed", limit: 50 }), api.get<Project[]>("/projects")]);
    return { baselines, runs: runs.items, projects };
  }, []);
  const [propose, setPropose] = useState<{ run_id: string; name: string } | null>(null);
  const [err, setErr] = useState("");
  const { busy, run: act } = useAction();
  const pname = (id: string) => q.data?.projects.find((p) => p.id === id)?.name ?? id;
  return (
    <>
      <PageHeader title="Baselines" sub="Approved references for drift, schema and volume comparison. A second person approves each baseline." actions={can("baselines.propose") && <button className="btn primary" onClick={() => setPropose({ run_id: q.data?.runs[0]?.id ?? "", name: "" })}>Propose from a run</button>} />
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !q.data.baselines.length ? <Empty title="No baselines yet">Propose one from a completed run that you consider representative.</Empty> : (
        <div className="tw"><table><thead><tr><th>Baseline</th><th>Project</th><th>Status</th><th>Sample</th><th>Proposed</th><th /></tr></thead>
          <tbody>{q.data.baselines.map((b) => (
            <tr key={b.id}><td><b>{b.name}</b><div className="faint small">v{b.version} · {b.profile_id}</div></td><td className="small">{pname(b.project_id)}</td>
              <td><span className={`tag${b.status === "approved" ? " accent" : ""}`}>{b.status}</span></td><td className="small">{b.sample_size} records</td>
              <td className="small">{b.proposed_by_name} · {ago(b.created_at)}{b.approved_by && <div className="faint">approved {fmtDate(b.approved_at)}</div>}</td>
              <td className="right nowrap">
                {b.status === "proposed" && can("baselines.approve") && <button className="btn sm primary" disabled={busy} onClick={async () => { if (await act(() => api.post(`/baselines/${b.id}/approve`), { ok: "Baseline approved" })) q.reload(); }}>Approve</button>}{" "}
                {b.status !== "retired" && can("baselines.approve") && <button className="btn sm" disabled={busy} onClick={async () => { if (await act(() => api.post(`/baselines/${b.id}/retire`), { ok: "Baseline retired" })) q.reload(); }}>Retire</button>}</td></tr>))}</tbody></table></div>)}
      {propose && q.data && (
        <Modal title="Propose a baseline" onClose={() => setPropose(null)}>
          <div className="form">
            <Field label="From run"><select value={propose.run_id} onChange={(e) => setPropose({ ...propose, run_id: e.target.value })}>{q.data.runs.map((r) => <option key={r.id} value={r.id}>{r.label || r.filename} · {r.decision} · {ago(r.created_at)}</option>)}</select></Field>
            <Field label="Name" hint="Optional."><input value={propose.name} onChange={(e) => setPropose({ ...propose, name: e.target.value })} /></Field>
            {err && <div className="alert error">{err}</div>}
            <button className="btn primary" disabled={busy || !propose.run_id} onClick={async () => { setErr(""); if (await act(() => api.post("/baselines", propose), { ok: "Baseline proposed", onError: (e) => setErr(e.message) })) { setPropose(null); q.reload(); } }}>Propose</button>
          </div>
        </Modal>)}
    </>
  );
}

/* ------------------------------------------------------------------ destinations */
const CLASSES: [string, string][] = [["local_index", "Local index (e.g. vector store you operate)"], ["internal_model", "Internal model"], ["training_set", "Training set"], ["external_model", "External model / API"], ["public_endpoint", "Public endpoint"]];

export function Destinations() {
  const { can, me } = useAccount();
  const q = useAsync(() => api.get<any[]>("/destinations"), []);
  const manage = can("destinations.manage");
  const [edit, setEdit] = useState<any | null>(null);
  const [secret, setSecret] = useState("");
  const [err, setErr] = useState<Record<string, string>>({});
  const [del, setDel] = useState<any | null>(null);
  const { busy, run: act } = useAction();
  const features = me?.plan.features ?? [];
  async function save() {
    setErr({});
    const b = { name: edit.name, klass: edit.klass, delivery: edit.delivery, target_url: edit.target_url ?? "", description: edit.description ?? "", ...(edit.secret ? { secret: edit.secret } : {}) };
    const r = await act(() => (edit.id ? api.patch(`/destinations/${edit.id}`, b) : api.post("/destinations", b)), { ok: "Destination saved", onError: (e) => setErr(Object.keys(e.fields).length ? e.fields : { _: e.message }) });
    if (r) { if (r.signing_secret) setSecret(r.signing_secret); setEdit(null); q.reload(); }
  }
  return (
    <>
      <PageHeader title="Destinations & webhooks" sub="Where released data and decisions go. Webhooks are signed and carry metadata only. The destination class feeds the privacy rules." actions={manage && <button className="btn primary" onClick={() => setEdit({ klass: "local_index", delivery: "pull", name: "" })}>New destination</button>} />
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !q.data.length ? <Empty title="No destinations">Without a destination, read released data through the pull gate: <code>GET /runs/&#123;id&#125;/artifact</code>.</Empty> : (
        <div className="tw"><table><thead><tr><th>Name</th><th>Class</th><th>Delivery</th><th>Target</th><th>Enabled</th><th /></tr></thead>
          <tbody>{q.data.map((d) => (
            <tr key={d.id}><td><b>{d.name}</b><div className="faint small">{d.description}</div></td><td className="small">{d.klass}</td><td><span className="tag">{d.delivery}</span></td>
              <td className="small" style={{ maxWidth: 320, overflowWrap: "anywhere" }}>{d.target_url || "—"}</td><td>{d.enabled ? "Yes" : "No"}</td>
              <td className="right nowrap">{manage && <><button className="btn sm" onClick={() => setEdit({ ...d, secret: "" })}>Edit</button>{" "}<button className="btn sm danger" onClick={() => setDel(d)}>Delete</button></>}</td></tr>))}</tbody></table></div>)}
      {edit && (
        <Modal title={edit.id ? "Edit destination" : "New destination"} onClose={() => setEdit(null)}>
          <div className="form">
            {err._ && <div className="alert error" role="alert">{err._}</div>}
            <Field label="Name" error={err.name}><input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Destination class" hint="Privacy rules depend on where data ends up."><select value={edit.klass} onChange={(e) => setEdit({ ...edit, klass: e.target.value })}>{CLASSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
            <Field label="Delivery">
              <select value={edit.delivery} onChange={(e) => setEdit({ ...edit, delivery: e.target.value })}>
                <option value="pull">Pull gate only</option><option value="webhook" disabled={!features.includes("webhooks")}>Signed webhook{!features.includes("webhooks") ? " (Team plan)" : ""}</option>
                <option value="object_store" disabled={!features.includes("object_store")}>Object store{!features.includes("object_store") ? " (Team plan)" : ""}</option></select></Field>
            {edit.delivery !== "pull" && <Field label={edit.delivery === "webhook" ? "Webhook URL (https)" : "Key prefix"} error={err.target_url}><input value={edit.target_url ?? ""} onChange={(e) => setEdit({ ...edit, target_url: e.target.value })} placeholder={edit.delivery === "webhook" ? "https://example.com/hooks/aidap" : "validated/"} /></Field>}
            {edit.delivery === "webhook" && <Field label="Signing secret" hint={edit.id ? "Leave empty to keep the current secret." : "Leave empty to generate one — it is shown once."}><input type="password" autoComplete="new-password" value={edit.secret ?? ""} onChange={(e) => setEdit({ ...edit, secret: e.target.value })} /></Field>}
            <Field label="Description"><input value={edit.description ?? ""} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
            {edit.id && <label className="check"><input type="checkbox" checked={edit.enabled} onChange={async (e) => setEdit({ ...edit, enabled: e.target.checked })} />Enabled</label>}
            <button className="btn primary" disabled={busy || !edit.name?.trim()} onClick={save}>{busy ? "Saving…" : "Save"}</button>
          </div>
        </Modal>)}
      {secret && (
        <Modal title="Copy your signing secret" onClose={() => setSecret("")}>
          <div className="stack"><div className="alert warn">This is the only time the secret is shown. Store it where your webhook receiver can read it.</div>
            <pre style={{ overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}>{secret}</pre><div className="row"><CopyButton text={secret} /><button className="btn" onClick={() => setSecret("")}>Done</button></div></div>
        </Modal>)}
      {del && <Confirm title={`Delete “${del.name}”?`} danger confirm="Delete" busy={busy} onNo={() => setDel(null)} onYes={async () => { if (await act(() => api.del(`/destinations/${del.id}`), { ok: "Destination deleted" })) { setDel(null); q.reload(); } }}>
        <p>Runs that used it keep their history. Pending deliveries to it will fail.</p></Confirm>}
    </>
  );
}

/* ------------------------------------------------------------------ schedules */
export function Schedules() {
  const { can, me } = useAccount();
  const q = useAsync(async () => {
    const [schedules, projects, profiles] = await Promise.all([api.get<any[]>("/schedules").catch((e) => { if (e.status === 402 || e.status === 403) return null; throw e; }), api.get<Project[]>("/projects"), api.get<ConfigSummary[]>("/profiles")]);
    return { schedules, projects, profiles };
  }, []);
  const [edit, setEdit] = useState<any | null>(null);
  const [err, setErr] = useState<Record<string, string>>({});
  const { busy, run: act } = useAction();
  const allowed = me?.plan.features.includes("schedules");
  async function save() {
    setErr({});
    const r = await act(() => api.post("/schedules", { ...edit, interval_minutes: Number(edit.interval_minutes) }), { ok: "Schedule created", onError: (e) => setErr(Object.keys(e.fields).length ? e.fields : { _: e.message }) });
    if (r) { setEdit(null); q.reload(); }
  }
  return (
    <>
      <PageHeader title="Schedules" sub="Fetch an HTTPS source on an interval and validate it." actions={allowed && can("schedules.manage") && q.data && <button className="btn primary" onClick={() => setEdit({ name: "", interval_minutes: 1440, source_url: "https://", project_id: q.data!.projects[0]?.id, profile_id: "api_feed", policy_id: "standard" })}>New schedule</button>} />
      {!allowed && <div className="alert info" style={{ marginBottom: 16 }}>Scheduled source checks are included from the Team plan. <Link to="/app/billing">See plans</Link></div>}
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !q.data.schedules?.length ? <Empty title="No schedules" /> : (
        <div className="tw"><table><thead><tr><th>Schedule</th><th>Every</th><th>Last run</th><th>Next run</th><th>Enabled</th><th /></tr></thead>
          <tbody>{q.data.schedules.map((s) => (
            <tr key={s.id}><td><b>{s.name}</b><div className="faint small" style={{ overflowWrap: "anywhere" }}>{s.source_url}</div>{s.last_error && <div className="err small">{s.last_error}</div>}</td>
              <td className="small">{s.interval_minutes >= 1440 && s.interval_minutes % 1440 === 0 ? `${s.interval_minutes / 1440} d` : s.interval_minutes % 60 === 0 ? `${s.interval_minutes / 60} h` : `${s.interval_minutes} min`}</td>
              <td className="small">{s.last_run_id ? <Link to={`/app/runs/${s.last_run_id}`}>{ago(s.last_run_at)}</Link> : "—"}</td><td className="small">{fmtDate(s.next_run_at)}</td><td>{s.enabled ? "Yes" : "Paused"}</td>
              <td className="right nowrap">{can("schedules.manage") && <><button className="btn sm" onClick={async () => { if (await act(() => api.patch(`/schedules/${s.id}`, { enabled: !s.enabled }))) q.reload(); }}>{s.enabled ? "Pause" : "Resume"}</button>{" "}
                <button className="btn sm danger" onClick={async () => { if (await act(() => api.del(`/schedules/${s.id}`), { ok: "Schedule deleted" })) q.reload(); }}>Delete</button></>}</td></tr>))}</tbody></table></div>)}
      {edit && q.data && (
        <Modal title="New schedule" onClose={() => setEdit(null)}>
          <div className="form">
            {err._ && <div className="alert error">{err._}</div>}
            <Field label="Name" error={err.name}><input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Source URL (https)" error={err.source_url}><input value={edit.source_url} onChange={(e) => setEdit({ ...edit, source_url: e.target.value })} /></Field>
            <Field label="Every (minutes)" hint="15 to 10080." error={err.interval_minutes}><input type="number" min={15} max={10080} value={edit.interval_minutes} onChange={(e) => setEdit({ ...edit, interval_minutes: e.target.value })} /></Field>
            <Field label="Project"><select value={edit.project_id} onChange={(e) => setEdit({ ...edit, project_id: e.target.value })}>{q.data.projects.filter((p) => !p.archived).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
            <Field label="Intended use"><select value={edit.profile_id} onChange={(e) => setEdit({ ...edit, profile_id: e.target.value })}>{q.data.profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
            <button className="btn primary" disabled={busy || !edit.name.trim()} onClick={save}>Create schedule</button>
          </div>
        </Modal>)}
    </>
  );
}
