import { useState } from "react";
import { api } from "../../lib/api";
import { useAccount } from "../../lib/account";
import { useAction, useAsync } from "../../lib/hooks";
import { Link } from "../../lib/router";
import { fmtDay } from "../../lib/format";
import type { ConfigSummary, Project } from "../../lib/types";
import { Empty, ErrorBox, Field, Modal, PageHeader, Spinner } from "../../components/ui";

export function Projects() {
  const { can, me } = useAccount();
  const q = useAsync(async () => {
    const [projects, profiles, policies] = await Promise.all([api.get<Project[]>("/projects"), api.get<ConfigSummary[]>("/profiles"), api.get<ConfigSummary[]>("/policies")]);
    return { projects, profiles, policies };
  }, []);
  const [edit, setEdit] = useState<Partial<Project> | null>(null);
  const [err, setErr] = useState<Record<string, string>>({});
  const { busy, run: act } = useAction();
  const manage = can("projects.manage");
  const active = q.data?.projects.filter((p) => !p.archived).length ?? 0;

  async function save() {
    if (!edit) return; setErr({});
    const body = { name: edit.name, description: edit.description ?? "", default_profile_id: edit.default_profile_id ?? "", default_policy_id: edit.default_policy_id ?? "standard", default_destination_id: edit.default_destination_id ?? "" };
    const r = await act(() => (edit.id ? api.patch(`/projects/${edit.id}`, body) : api.post("/projects", body)), { ok: "Project saved", onError: (e) => setErr(Object.keys(e.fields).length ? e.fields : { _: e.message }) });
    if (r) { setEdit(null); q.reload(); }
  }
  return (
    <>
      <PageHeader title="Projects" sub={`Group inputs by pipeline or system. ${active} of ${me?.plan.max_projects} projects used on the ${me?.plan.name} plan.`}
        actions={manage && <button className="btn primary" onClick={() => setEdit({ default_policy_id: "standard" })}>New project</button>} />
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !q.data.projects.length ? <Empty title="No projects" /> : (
        <div className="grid g3">{q.data.projects.map((p) => (
          <div className="card" key={p.id} style={p.archived ? { opacity: 0.6 } : undefined}>
            <div className="row between"><h3 style={{ margin: 0 }}>{p.name}</h3>{p.archived && <span className="tag">archived</span>}</div>
            <p className="muted small">{p.description || "No description."}</p>
            <div className="small muted">Profile: {p.default_profile_id || "—"} · Policy: {p.default_policy_id || "—"}</div>
            <div className="small muted">{p.run_count ?? 0} runs · created {fmtDay(p.created_at)}</div>
            <div className="row" style={{ marginTop: 12 }}>
              {!p.archived && <Link className="btn sm primary" to={`/app/new?project=${p.id}`}>Validate</Link>}
              {manage && <button className="btn sm" onClick={() => setEdit(p)}>Edit</button>}
              {manage && <button className="btn sm ghost" onClick={async () => { if (await act(() => api.patch(`/projects/${p.id}`, { archived: !p.archived }), { ok: p.archived ? "Project restored" : "Project archived" })) q.reload(); }}>{p.archived ? "Restore" : "Archive"}</button>}
            </div>
          </div>))}</div>)}
      {edit && q.data && (
        <Modal title={edit.id ? "Edit project" : "New project"} onClose={() => setEdit(null)}>
          <div className="form">
            {err._ && <div className="alert error" role="alert">{err._}</div>}
            <Field label="Name" error={err.name}><input value={edit.name ?? ""} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required /></Field>
            <Field label="Description" error={err.description}><textarea value={edit.description ?? ""} onChange={(e) => setEdit({ ...edit, description: e.target.value })} style={{ minHeight: 70 }} /></Field>
            <Field label="Default intended use"><select value={edit.default_profile_id ?? ""} onChange={(e) => setEdit({ ...edit, default_profile_id: e.target.value })}><option value="">None</option>{q.data.profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
            <Field label="Default policy"><select value={edit.default_policy_id ?? "standard"} onChange={(e) => setEdit({ ...edit, default_policy_id: e.target.value })}>{q.data.policies.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
            <button className="btn primary" disabled={busy || !(edit.name ?? "").trim()} onClick={save}>{busy ? "Saving…" : "Save project"}</button>
          </div>
        </Modal>)}
    </>
  );
}
