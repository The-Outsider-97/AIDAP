export const STAGES: { no: number; title: string; method: string; blurb: string }[] = [
  { no: 1, title: "Ingestion", method: "D", blurb: "Accept the file or payload, hash it, store the original untouched." },
  { no: 2, title: "Normalization", method: "D", blurb: "Parse in an isolated process, with size and time limits." },
  { no: 3, title: "Format / schema validation", method: "D", blurb: "Supported format, complete parse, declared schema." },
  { no: 4, title: "Structural quality", method: "D", blurb: "Required fields, types, ranges, missing metadata." },
  { no: 5, title: "Statistical quality", method: "D/S", blurb: "Duplicates, distributions, missingness." },
  { no: 6, title: "Anomaly detection", method: "S", blurb: "Drift and outliers against an approved baseline." },
  { no: 7, title: "Relationship analysis", method: "D", blurb: "Keys, references, versions and supersession." },
  { no: 8, title: "Semantic fitness", method: "D/M", blurb: "Conflicts and stale statements in the content." },
  { no: 9, title: "Privacy screening", method: "D/M", blurb: "Personal data and credentials, judged against the destination." },
  { no: 10, title: "Safety screening", method: "D/M", blurb: "Malware markers, prompt-injection patterns, hidden text." },
  { no: 11, title: "Provenance / evidence", method: "D", blurb: "Owner, source, revision, lineage." },
  { no: 12, title: "Intended-use fitness", method: "D/M", blurb: "Is this input fit for the stated purpose and destination?" },
  { no: 13, title: "Confidence", method: "S/M", blurb: "What is known, what is inferred, what could not be evaluated." },
  { no: 14, title: "Policy decision", method: "D", blurb: "Versioned policy turns evidence into Pass / Review / Quarantine / Block." },
  { no: 15, title: "Disposition", method: "D/H", blurb: "Release, hold for review, isolate, or reject." },
  { no: 16, title: "Evidence generation", method: "D", blurb: "A sealed, reproducible evidence bundle." },
  { no: 17, title: "Audit logging", method: "D", blurb: "Append-only, hash-chained audit record." },
  { no: 18, title: "Checkpointing", method: "D", blurb: "Restart-safe stages using SLAI's checkpoint manager." },
  { no: 19, title: "Alerting", method: "D", blurb: "Credential exposure, quarantines, repeated failures." },
  { no: 20, title: "Delivery", method: "D", blurb: "Pull gate, signed webhook or object-store release." },
];

export const FAQ: { q: string; a: string }[] = [
  { q: "What does AIDAP actually decide?", a: "Whether a specific input is fit for a specific use. You choose an intended-use profile (for example “documents before RAG indexing”) and a policy. AIDAP evaluates the input and returns Pass, Review, Quarantine or Block, with the findings and the rule that led to it." },
  { q: "Does a Pass mean the data is correct, lawful or safe?", a: "No. A Pass means that the checks required by your profile and policy were completed and found nothing that the policy treats as blocking. It is evidence for a decision, not a certification. See the limits page." },
  { q: "What happens when a check cannot run?", a: "AIDAP fails closed. A mandatory check that is unknown, errored or not evaluated can never produce a Pass; the run is held for Review or worse, and the report says which check was affected and why." },
  { q: "Are confidence scores calibrated probabilities?", a: "No, and AIDAP says so. Every finding is labelled deterministic, heuristic or unknown. Heuristic values are relative scores, not probabilities." },
  { q: "Can a model overrule the rules?", a: "No. Model-assisted findings are capped at Review and can never release an input, waive a credential or privacy rule, or lower a severity." },
  { q: "Who can approve an exception?", a: "A person with the role the policy names for that finding type. The submitter cannot approve their own exception when another eligible reviewer exists. Credentials, malware and tool-injection findings cannot be waived." },
  { q: "What do I get back from the API?", a: "A decision, findings with evidence pointers, per-stage records and a sealed evidence bundle (SHA-256 over canonical JSON) that you can download and re-verify. Webhooks carry metadata only, never document content." },
  { q: "How is usage billed?", a: "Plans include a number of validation runs and a scan-volume allowance per month. When an allowance is exhausted, new runs are held rather than silently billed, unless you switch on overage. Prices exclude VAT." },
  { q: "Is there a free tier?", a: "Yes. Developer is free: 100 runs a month, one project and seven days of evidence retention." },
  { q: "Where does my data go?", a: "Input bytes are sealed with AES-256-GCM before they reach storage, under a tenant-scoped key, using keys held by the deployment; they are deleted when your retention period ends. External model inference is off unless your policy turns it on and the destination class allows it." },
  { q: "How does AIDAP relate to SLAI?", a: "AIDAP runs on top of SLAI: SLAI’s privacy-identification, quality, safety and provenance agents supply findings, and SLAI’s checkpointing keeps stages restart-safe. AIDAP owns the decision, policy, evidence and billing layers." },
  { q: "How do I get Enterprise?", a: "Contact us at info.remy3design@gmail.com or use the form. Enterprise adds SSO, private deployment and custom retention and is quoted individually." },
];

export const FEATURE_LABEL: Record<string, string> = {
  api: "REST API & SDK", model_assist: "Model-assisted review (capped at Review)", custom_policy: "Custom profiles & policies",
  webhooks: "Signed webhooks", review_roles: "Review roles & segregation of duties", schedules: "Scheduled source checks",
  object_store: "Object-store delivery", audit_export: "Audit export", configurable_retention: "Configurable retention",
  priority_support: "Priority support", sso: "Single sign-on", private_deployment: "Private deployment",
};
