import type { ReactNode } from "react";
import { FAQ, STAGES } from "../../lib/content";
import { Link } from "../../lib/router";
import { openContact, BUSINESS_EMAIL } from "../../components/shell/Shell";
import { DECISION_MEANING, DecisionBadge } from "../../components/ui";

function Doc({ title, lead, sections, children }: { title: string; lead?: string; sections: [string, string][]; children: ReactNode }) {
  return (
    <div className="wrap doc-layout">
      <nav className="toc" aria-label="On this page">{sections.map(([id, t]) => <a key={id} href={`#${id}`}>{t}</a>)}</nav>
      <article className="prose">
        <h1>{title}</h1>{lead && <p className="muted" style={{ fontSize: "1.1rem" }}>{lead}</p>}
        {children}
      </article>
    </div>
  );
}

export function Methodology() {
  return (
    <Doc title="Methodology" lead="How AIDAP turns an input and an intended use into a decision, and what it will and won’t claim."
      sections={[["model", "Decision model"], ["workflow", "The 20 stages"], ["rules", "Hard rules"], ["confidence", "Confidence"], ["slai", "SLAI agents"], ["human", "Human review"]]}>
      <h2 id="model">Decision model</h2>
      <p>AIDAP evaluates one input against an <b>intended-use profile</b> (what the data is for, where it is going, which checks are required) and a <b>versioned policy</b> (how severities map to outcomes). The outcome is one of:</p>
      <ul>{(["pass", "review", "quarantine", "block"] as const).map((d) => <li key={d}><DecisionBadge decision={d} /> {DECISION_MEANING[d]}</li>)}</ul>
      <p>Findings keep four things apart: the <b>observed evidence</b>, the <b>inference</b> drawn from it, the <b>confidence</b> label, and the <b>recommended action</b>. A decision is always paired with the reasons, the rule steps that were applied and the policy and profile versions.</p>
      <h2 id="workflow">The 20 stages</h2>
      <ol>{STAGES.map((s) => <li key={s.no}><b>{s.title}</b> <span className="tag">{s.method}</span> — {s.blurb}</li>)}</ol>
      <p className="muted small">D = deterministic, S = statistical, M = model-assisted, H = human. Stages 3–14 are checkpointed through SLAI’s checkpoint manager.</p>
      <h2 id="rules">Hard rules and fail-closed behaviour</h2>
      <p>Five rules apply to every policy and cannot be removed by configuration:</p>
      <ul>
        <li><b>H1</b> A prohibited destination blocks the requested operation (Block).</li>
        <li><b>H2</b> Credentials are never released; the artifact is kept in restricted storage (Block).</li>
        <li><b>H3</b> Malicious artifacts are isolated and cannot be waived (Quarantine).</li>
        <li><b>H4</b> An integrity mismatch between what was assessed and what is stored isolates the artifact (Quarantine).</li>
        <li><b>H5</b> Embedded tool or exfiltration directives isolate the artifact (Quarantine).</li>
      </ul>
      <p>Beyond these, the engine is fail-closed: a mandatory check that is unknown, errored or not evaluated can never produce a Pass; model-assisted findings are capped at Review; and shadow policies never authorize release. Release is authorized only when the decision is active, not shadow, a Pass, not expired, and the bytes being released have the digest that was assessed.</p>
      <h2 id="confidence">Confidence</h2>
      <p>Findings are labelled <code>deterministic</code> (validated pattern or structure), <code>heuristic</code> (an uncalibrated score) or <code>unknown</code>. AIDAP does not present any value as a calibrated probability, and evidence bundles carry <code>calibrated: false</code> to say so.</p>
      <h2 id="slai">SLAI agents</h2>
      <p>AIDAP lives inside SLAI and calls its agents through a narrow adapter layer: personal-data identification (DataID), quality, safety, provenance and language agents. Their output is mapped to AIDAP findings with severity capped at High and treated as model-origin where applicable. If an agent cannot be loaded, its check is recorded as <i>not evaluated</i> with the reason. Open <Link to="/app/system">System status</Link> in your workspace to see which agents are active.</p>
      <h2 id="human">Human review</h2>
      <p>Reviewers can approve a time-limited exception for waivable findings, reject (which tightens the decision to Block), or ask for repair. Exceptions need the role the policy names, are bounded in time, can be revoked, and every action is written to a hash-chained audit log.</p>
    </Doc>
  );
}

export function Trust() {
  return (
    <Doc title="Trust & security" lead="What the platform does to protect your data and your decisions — and what it leaves to your deployment."
      sections={[["controls", "Controls"], ["evidence", "Evidence & audit"], ["data", "Your data"], ["not", "What we don’t claim"]]}>
      <h2 id="controls">Controls</h2>
      <ul>
        <li><b>Authentication</b> — salted, slow password hashing; optional TOTP two-factor with single-use recovery codes; account lock-out on repeated failures.</li>
        <li><b>Sessions</b> — HTTP-only cookies, CSRF token on every state-changing request, origin checks, strict content-security headers.</li>
        <li><b>API keys</b> — scoped, optionally project-limited and expiring; stored as digests; shown once.</li>
        <li><b>Roles</b> — owner, admin, security, reviewer, analyst, viewer; segregation of duties for baseline approval, policy publishing and exceptions.</li>
        <li><b>Webhooks</b> — HTTPS only, SSRF-validated targets, HMAC-signed with a timestamp, metadata only (no document content).</li>
        <li><b>Rate limits</b> — per IP and per API key, with <code>Retry-After</code>.</li>
        <li><b>Input handling</b> — parsing happens in an isolated process with size and time limits; spreadsheet formulas are neutralised in CSV exports.</li>
      </ul>
      <h2 id="evidence">Evidence & audit</h2>
      <p>Each run produces an <code>aidap.evidence/1</code> bundle sealed with SHA-256 over canonical JSON, with a PROV-style lineage graph. The audit log is append-only (enforced in the database) and hash-chained; verification is available in the workspace and via the API.</p>
      <h2 id="data">Your data</h2>
      <p>Inputs are sealed with AES-256-GCM (the object key is bound as associated data) before they reach storage, and removed when your retention period ends. Quarantined content is only readable after you state a purpose; each access is logged and time-limited. External model inference is off unless your policy enables it and the destination class permits it.</p>
      <h2 id="not">What we don’t claim</h2>
      <p>AIDAP is a validation aid. It is not a certification, a legal compliance determination, or a guarantee that data is true, unbiased or free of malware. See <Link to="/disclaimer">limits & disclaimer</Link>. Questions: <a href={`mailto:${BUSINESS_EMAIL}`}>{BUSINESS_EMAIL}</a>.</p>
    </Doc>
  );
}

export function Faq() {
  return (
    <Doc title="Frequently asked questions" sections={FAQ.map((f, i) => [`q${i}`, f.q] as [string, string])}>
      {FAQ.map((f, i) => <section key={i} id={`q${i}`}><h3>{f.q}</h3><p>{f.a}</p></section>)}
      <p>Something else? <button className="linkbtn" onClick={openContact}>Ask us</button>.</p>
    </Doc>
  );
}

export function Disclaimer() {
  return (
    <Doc title="Limits & disclaimer" lead="Please read this before relying on a decision."
      sections={[["what", "What AIDAP is"], ["limits", "Known limits"], ["resp", "Your responsibility"]]}>
      <h2 id="what">What AIDAP is</h2>
      <p>AIDAP produces evidence and a recommended decision about whether an input is fit for a stated use. It does not certify truthfulness, lawfulness, fairness, licensing, consent or safety.</p>
      <h2 id="limits">Known limits</h2>
      <ul>
        <li>Pattern-based privacy and safety detectors have false positives and false negatives; a Pass is not proof that none is present.</li>
        <li>The built-in malware check recognises the standard EICAR test marker only and never reports “clean”. Connect an antivirus engine (ClamAV) for real scanning; until then the file-safety check is reported as not scanned.</li>
        <li>Some SLAI agents (quality, safety, provenance, language) need their own dependencies or data stores. When one is unavailable it is recorded as not evaluated, and the policy treats the gap conservatively.</li>
        <li>Heuristic confidence values are relative scores, not probabilities.</li>
        <li>Freshness, supersession and conflict checks rely on metadata you supply.</li>
        <li>Plan prices and allowances are launch hypotheses.</li>
      </ul>
      <h2 id="resp">Your responsibility</h2>
      <p>You remain responsible for deciding what data may be used for which purpose and for reviewing Review and Quarantine items. Do not use AIDAP as the sole safeguard for regulated or high-risk processing.</p>
    </Doc>
  );
}

const CURL = `curl -X POST https://YOUR-HOST/api/v1/runs \\
  -H "Authorization: Bearer aidk_xxx" \\
  -H "Idempotency-Key: build-1842" \\
  -H "X-Filename: handbook.json" \\
  --data-binary @handbook.json \\
  "https://YOUR-HOST/api/v1/runs?project_id=prj_xxx&profile_id=rag_indexing&wait=true"`;
const PY = `from aidap_sdk import Client

c = Client("https://YOUR-HOST", api_key="aidk_xxx")
result = c.assure("handbook.json", project="prj_xxx", profile="rag_indexing")
print(result.decision, result.reason_codes)
# CLI for CI: exit code 0 pass · 10 review · 20 quarantine · 30 block
#   python -m aidap_sdk check handbook.json --project prj_xxx --profile rag_indexing`;
const HOOK = `Headers:   X-SLAI-Webhook-Id, X-SLAI-Webhook-Timestamp, X-SLAI-Webhook-Event, X-SLAI-Webhook-Signature
Event:     decision.issued   (schema aidap.webhook/1, metadata only)
Signature: "v1=" + hex(HMAC_SHA256(secret, f"{timestamp}.{event_id}.{body}"))`;

export function Docs() {
  return (
    <Doc title="API & SDK" lead="Everything the workspace does is available over a versioned REST API."
      sections={[["auth", "Authentication"], ["submit", "Submit an input"], ["result", "Read the result"], ["gate", "Pull gate"], ["webhooks", "Webhooks"], ["sdk", "SDK & CI"], ["errors", "Errors"]]}>
      <h2 id="auth">Authentication</h2>
      <p>Create an API key under <b>Workspace → API keys</b> and send it as <code>Authorization: Bearer aidk_…</code>. Keys carry scopes (<code>runs:write</code>, <code>runs:read</code>, <code>deliveries:read</code>, <code>policies:read</code>, <code>usage:read</code>) and may be limited to projects.</p>
      <h2 id="submit">Submit an input</h2>
      <pre>{CURL}</pre>
      <p>Send a multipart <code>file</code>, a raw body, or JSON with <code>content</code>. <code>Idempotency-Key</code> makes retries safe. With <code>wait=true</code> the call waits up to 25 seconds for the decision; otherwise poll <code>GET /api/v1/runs/{"{id}"}</code>.</p>
      <h2 id="result">Read the result</h2>
      <ul>
        <li><code>GET /runs/{"{id}"}</code> — state, decision, references</li>
        <li><code>GET /runs/{"{id}"}/findings</code> · <code>/stages</code> · <code>/decisions</code></li>
        <li><code>GET /runs/{"{id}"}/evidence?download=1</code> — sealed bundle</li>
        <li><code>GET /runs/{"{id}"}/report?format=json|csv|html|pdf</code></li>
      </ul>
      <h2 id="gate">Pull gate</h2>
      <p><code>GET /runs/{"{id}"}/artifact</code> returns the validated bytes only if the decision authorizes release; otherwise it answers <code>403</code> (<code>release_not_authorized</code>) with the reason. Use it as the single place your pipeline fetches released data.</p>
      <h2 id="webhooks">Webhooks</h2>
      <p>Destinations of type <i>webhook</i> receive metadata-only events, signed and timestamped. Verify with <code>aidap_sdk.webhooks.verify_signature</code>.</p>
      <pre>{HOOK}</pre>
      <h2 id="sdk">SDK & CI</h2>
      <pre>{PY}</pre>
      <h2 id="errors">Errors</h2>
      <p>Errors use the <code>aidap.error/1</code> envelope: <code>{`{"error": {"code", "message", "details"}, "request_id"}`}</code>. <code>422</code> includes <code>details.fields</code>; <code>429</code> includes <code>Retry-After</code>; <code>402</code> means the plan’s allowance or a plan limit has been reached.</p>
      <p className="muted small">Live API reference for your own installation: <code>/api/v1/meta</code> and the contracts exported by <code>python -m AIDAP export-contracts</code>.</p>
    </Doc>
  );
}
