import { useState } from "react";
import { api } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { Link, useRouter } from "../../lib/router";
import { ago, fmtBytes, fmtDate } from "../../lib/format";
import type { AssetHistory, AssetRow, Project } from "../../lib/types";
import { DecisionBadge, Digest, Empty, ErrorBox, PageHeader, Spinner } from "../../components/ui";

export function AssetsList() {
  const { navigate } = useRouter();
  const [project, setProject] = useState("");
  const [text, setText] = useState("");
  const projects = useAsync(() => api.get<Project[]>("/projects"), []);
  const q = useAsync(() => api.get<AssetRow[]>("/assets", { project_id: project, q: text, limit: 100 }), [project, text]);
  const pname = (id: string) => projects.data?.find((p) => p.id === id)?.name ?? id;
  return (
    <>
      <PageHeader title="Assets" sub="Each named input with its versions and how its decision changed over time."
        actions={<>
          <input type="search" aria-label="Search assets" placeholder="Search by name" value={text} onChange={(e) => setText(e.target.value)} style={{ maxWidth: 220 }} />
          <select aria-label="Project" value={project} onChange={(e) => setProject(e.target.value)} style={{ maxWidth: 200 }}>
            <option value="">All projects</option>{(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        </>} />
      {q.error && !q.data ? <ErrorBox error={q.error} retry={q.reload} /> : !q.data ? <Spinner /> : !q.data.length ? (
        <Empty title="No assets found" action={<Link className="btn primary" to="/app/new">New validation</Link>}>Assets are created when an input is validated. Submitting the same file name again adds a version.</Empty>
      ) : (
        <div className="tw"><table><thead><tr><th>Asset</th><th>Project</th><th>Latest</th><th>Versions</th><th>Passed / held</th><th>Last seen</th></tr></thead>
          <tbody>{q.data.map((a) => (
            <tr key={a.id} className="click" onClick={() => navigate(`/app/assets/${a.id}`)}>
              <td><Link to={`/app/assets/${a.id}`} onClick={(e) => e.stopPropagation()}><b>{a.name}</b></Link></td>
              <td className="small">{pname(a.project_id)}</td>
              <td><DecisionBadge decision={a.latest_decision} state={a.latest_state} /></td>
              <td>{a.versions}</td><td>{a.passed} / {a.held}</td><td className="small">{ago(a.last_seen_at)}</td></tr>))}</tbody></table></div>)}
    </>
  );
}

export function AssetDetail({ id }: { id: string }) {
  const q = useAsync(() => api.get<AssetHistory>(`/assets/${id}`), [id]);
  if (q.error && !q.data) return <ErrorBox error={q.error} retry={q.reload} />;
  const h = q.data;
  if (!h) return <Spinner />;
  const timeline = [...h.timeline].reverse();
  return (
    <>
      <PageHeader title={h.asset.name} sub={`${h.asset.source_class.replaceAll("_", " ")} · ${h.asset.classification} · first seen ${fmtDate(h.asset.created_at)}`}
        actions={<Link className="btn" to="/app/assets">All assets</Link>} />
      <div className="grid split">
        <div className="card">
          <h3>History</h3>
          <ol className="tl">
            {timeline.map((t) => (
              <li key={t.run_id} className={t.decision ?? ""}>
                <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
                  <DecisionBadge decision={t.decision} state={t.state} />
                  <Link to={`/app/runs/${t.run_id}`}>Version {t.version_no}{t.label ? ` · ${t.label}` : ""}</Link>
                  <span className="faint small">{fmtDate(t.created_at)}</span>
                  {t.same_content_as_previous && <span className="tag">unchanged content</span>}
                </div>
                <div className="faint small">{t.profile} · {t.policy}</div>
                {t.new_reasons.length > 0 && <div className="small"><span className="bad-t">New:</span> <code>{t.new_reasons.join(", ")}</code></div>}
                {t.cleared_reasons.length > 0 && <div className="small"><span className="ok-t">Cleared:</span> <code>{t.cleared_reasons.join(", ")}</code></div>}
              </li>))}
          </ol>
        </div>
        <div className="card">
          <h3>Versions</h3>
          <div className="tw"><table><thead><tr><th>#</th><th>Digest</th><th>Size</th><th>Runs</th></tr></thead>
            <tbody>{h.versions.map((v) => <tr key={v.version_id}><td>{v.version_no}</td><td><Digest value={v.digest} /></td><td className="small">{fmtBytes(v.size)}</td><td>{v.runs}</td></tr>)}</tbody></table></div>
        </div>
      </div>
    </>
  );
}
