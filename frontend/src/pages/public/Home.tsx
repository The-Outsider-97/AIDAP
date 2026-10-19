import { useAccount } from "../../lib/account";
import { Link } from "../../lib/router";
import { STAGES } from "../../lib/content";
import { DecisionBadge, Icon } from "../../components/ui";
import { openContact } from "../../components/shell/Shell";

export function Home() {
  const { me, openAuth } = useAccount();
  return (
    <>
      <div className="wrap">
        <section className="hero" id="top" data-title="Overview">
          <div>
            <span className="eyebrow">AI Data Assurance Platform</span>
            <h1>Know whether an input is fit for your AI — before it gets in.</h1>
            <p className="lead">AIDAP checks the documents, datasets and feeds your AI systems consume — before they are indexed, trained on, or sent to a model — and returns an evidence-backed decision for your intended use.</p>
            <div className="row">
              {me ? <Link className="btn primary lg" to="/app/new">Validate an input</Link> : <button className="btn primary lg" onClick={() => openAuth("signup")}>Start free</button>}
              <Link className="btn lg" to="/pricing">See plans</Link>
            </div>
            <p className="faint small" style={{ marginTop: 14 }}>Developer plan is free · 100 runs a month · no card needed</p>
          </div>
          <div className="sample" aria-label="Example decision">
            <div className="row between" style={{ marginBottom: 8 }}><b>onboarding-contacts.json</b><DecisionBadge decision="review" /></div>
            <div className="line"><span className="muted">Intended use</span><span>Documents before RAG indexing</span></div>
            <div className="line"><span className="muted">Policy</span><span>Standard @ 1</span></div>
            <div className="line"><span>Email address detected</span><span className="sev medium">medium</span></div>
            <div className="line"><span>Phone number detected</span><span className="sev medium">medium</span></div>
            <div className="line"><span className="muted">Mandatory checks concluded</span><span>10 / 10</span></div>
            <div className="line"><span className="muted">Evidence seal</span><code>sha256:4b0662…e847f</code></div>
            <p className="faint small" style={{ margin: "10px 0 0" }}>Illustrative example.</p>
          </div>
        </section>
      </div>

      <section className="section" id="decisions" data-title="Four decisions"><div className="wrap">
        <h2>Four decisions, each with a reason</h2>
        <p className="sub">Every run ends in one of four outcomes. The decision always comes with the findings behind it and the rule that applied — never a bare score.</p>
        <div className="grid g4">
          {([["pass", "Released to the destination you chose."], ["review", "Held for a person: approve an exception, reject, or repair."],
             ["quarantine", "Isolated. Access to the content needs a stated purpose and is logged."], ["block", "Not usable for this purpose. Credentials found are treated as exposed."]] as const).map(([d, t]) => (
            <div className="card" key={d}><DecisionBadge decision={d} /><p className="muted" style={{ margin: "12px 0 0" }}>{t}</p></div>
          ))}
        </div>
      </div></section>

      <section className="section" id="workflow" data-title="20-stage workflow"><div className="wrap">
        <h2>A fixed 20-stage workflow</h2>
        <p className="sub">Deterministic checks come first. Statistical and model-assisted steps add signals, never authority: a model can raise a concern to Review, but it cannot release an input. Stages are checkpointed with SLAI, so a worker that restarts resumes without repeating or double-billing a finished stage.</p>
        <ol className="stages">{STAGES.map((s) => <li key={s.no}><b>{s.title}</b><span>{s.blurb}</span></li>)}</ol>
      </div></section>

      <section className="section" id="evidence" data-title="Evidence"><div className="wrap">
        <h2>Evidence you can re-check</h2>
        <div className="grid g3">
          <div className="card feature"><h3><Icon name="eye" />Observed vs. inferred</h3><p className="muted">Each finding separates what was observed in the input from what is inferred, with a confidence label — deterministic, heuristic or unknown. Scores are never presented as calibrated probabilities.</p></div>
          <div className="card feature"><h3><Icon name="audit" />Sealed bundles</h3><p className="muted">Inputs, policy, profile, findings and stage records are sealed with SHA-256 over canonical JSON. Download the bundle and verify it yourself. Webhooks carry metadata only.</p></div>
          <div className="card feature"><h3><Icon name="lock" />Fail-closed rules</h3><p className="muted">If a mandatory check cannot run, the result is never a Pass. Credentials, malware and tool-injection findings cannot be waived by anyone.</p></div>
          <div className="card feature"><h3><Icon name="flow" />Intended-use profiles</h3><p className="muted">Data is not “good” in general. Choose a profile — RAG indexing, agent memory, external-LLM submission, training sets, dataset uploads or API feeds — and policies tuned to the destination.</p></div>
          <div className="card feature"><h3><Icon name="shield" />Human review, with duties separated</h3><p className="muted">Exceptions are time-limited and need the role your policy names. Submitters cannot approve their own exceptions when another reviewer is available.</p></div>
          <div className="card feature"><h3><Icon name="plug" />API, SDK, CI</h3><p className="muted">Gate pipelines with a single call. The CLI exits 0 / 10 / 20 / 30 for Pass / Review / Quarantine / Block.</p></div>
        </div>
      </div></section>

      <section className="section" id="slai" data-title="Built on SLAI"><div className="wrap">
        <h2>Built on SLAI</h2>
        <p className="sub">AIDAP runs inside the SLAI repository and uses its agents rather than re-implementing them: the privacy-identification agent for personal-data findings, the quality, safety and provenance agents where they are available, and SLAI’s checkpoint manager for restart-safe stages. When an agent is unavailable, the report says so — that check is shown as not evaluated, and the policy treats it conservatively.</p>
        <Link to="/methodology" className="btn">Read the methodology</Link>
      </div></section>

      <div className="wrap"><div className="cta">
        <h2>Put a gate in front of your AI inputs</h2>
        <p className="muted">Start on the free Developer plan, or talk to us about Enterprise.</p>
        <div className="row" style={{ justifyContent: "center" }}>
          {me ? <Link className="btn primary lg" to="/app/new">Validate an input</Link> : <button className="btn primary lg" onClick={() => openAuth("signup")}>Start free</button>}
          <button className="btn lg" onClick={openContact}>Contact sales</button>
        </div>
      </div></div>
    </>
  );
}
