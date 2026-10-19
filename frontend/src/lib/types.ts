// Shapes returned by the AIDAP API (aidap.* contracts). Only the fields the UI reads are listed.
export type Decision = "pass" | "review" | "quarantine" | "block";
export type Severity = "info" | "low" | "medium" | "high" | "critical";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Doc = Record<string, any>;

export interface Confidence { basis: "deterministic" | "heuristic" | "unknown"; interpretation: string; value: number | null; note: string }
export interface Pointer { path: string; start: number | null; end: number | null; excerpt: string; digest: string }
export interface Finding {
  id: string; check_id: string; category: string; code: string; title: string; severity: Severity; observed: string;
  inference: string; confidence: Confidence; recommended_action: string; origin: "native" | "slai" | "model"; pointers: Pointer[];
  count: number; mandatory: boolean; tags: string[]; data: Doc;
}
export interface CheckSummary {
  check_id: string; status: "passed" | "failed" | "unknown" | "not_evaluated" | "error"; evaluator: string; origin: string;
  mandatory: boolean; coverage: number | null; unknown_reason: string | null; message: string; duration_ms: number; findings: number;
}
export interface Reason { code: string; message: string; effect: Decision; severity: Severity; check_id: string; waivable: boolean; guidance: string; waived_by: string | null }
export interface DecisionDoc {
  id: string; decision: Decision; status: string; disposition: string; reasons: Reason[]; created_at: string; expires_at: string | null;
  shadow: boolean; decided_by: string; policy_ref: string; profile_ref: string; input_digest: string; released_digest: string;
  exception_ids: string[]; supersedes: string | null; coverage: Doc; rationale: { summary: string; next_action: string; steps: { title: string; detail: string }[] };
}
export interface Stage { stage: number; name: string; state: string; message: string; started_at: string; finished_at: string; attempt: number; metrics: Doc }
export interface Delivery { id: string; kind: string; state: string; attempts: number; created_at: string; sent_at: string | null; last_error: string; note: string; decision: Decision }
export interface Run {
  id: string; project_id: string; state: string; decision: Decision | null; filename: string; label: string; created_at: string; created_by: string;
  finished_at: string | null; profile_id: string; profile_version: number; policy_id: string; policy_version: number; size: number; error: string;
  source: string; input_digest: string; parent_run_id: string | null; review_id?: string | null; quarantine_id?: string | null; version_no: number;
  destination_id: string | null; warnings?: string[]; release_authorized?: boolean; decision_detail?: DecisionDoc | null;
  stages?: Stage[]; deliveries?: Delivery[]; history?: DecisionDoc[]; shadow?: boolean; expired?: boolean; evidence_seal?: string; plan_id?: string;
}
export interface Page<T> { items: T[]; total: number; limit: number; offset: number }
export interface Plan {
  id: string; name: string; tagline: string; price_month_cents: number | null; currency: string; included_runs: number; included_scan_gb: number;
  inference_allowance_cents: number; max_projects: number; evidence_retention_days: number; max_run_mb: number; seats: number; features: string[];
  support: string; contact_sales: boolean; annual_hint: string; onboarding_hint: string; highlights: string[];
}
export interface Me {
  user: Doc; role: string; permissions: string[]; tenant: Doc; memberships: { tenant_id: string; tenant_name: string; role: string; current: boolean }[];
  plan: Plan; subscription_status: string; billing_provider: string; mfa_enabled: boolean;
}
export interface Project { id: string; name: string; description: string; default_profile_id: string; default_policy_id: string; default_destination_id: string; archived: boolean; run_count?: number; created_at: string }
export interface ConfigSummary { id: string; name: string; builtin: boolean; description: string; task?: string; mode?: string; published_version: number | null; draft_version: number | null; version: number; updated_at?: string }
export interface Review {
  id: string; run_id: string; project_id: string; state: string; reason_codes: string[]; summary: string; created_at: string; assignee: string; due_at: string;
  resolved_by: string; resolved_at: string | null; resolution: string; comment: string; exception_id: string;
}
export interface Alert { id: string; kind: string; title: string; detail: string; severity: string; run_id: string; project_id: string; first_seen_at: string; last_seen_at: string; count: number; acknowledged_at: string | null }
export interface Usage {
  period: string; plan: Plan; subscription: Doc; used: { runs: number; scan_bytes: number; scan_gb: number; inference_cents: number; cpu_ms: number; projects: number; seats: number };
  limits: { runs: number; scan_bytes: number; inference_cents: number; projects: number; seats: number }; ratios: Record<string, number | null>;
}

export type Verdict = "useful" | "false_positive" | "unclear";
export interface FeedbackRow { finding_id: string; verdict: Verdict; note: string; actor: string; mine: boolean; created_at: string }
export interface Insights {
  window_days: number; project_id: string | null; generated_at: string;
  runs: { total: number; finished: number; by_decision: Record<string, number>; pass_rate: number | null; hold_rate: number | null };
  reliability: { unhandled_errors: number; error_rate: number | null; mandatory_check_completion: number | null; unsupported_input_rate: number | null; sampled_runs: number;
    delivery: { sent: number; failed: number; retried: number; integrity_stops: number } };
  review: { opened: number; resolved: number; open: number; overturned: number; overturn_rate: number | null; repair_requested: number; rejected: number;
    time_to_resolve_hours: { median: number | null; p90: number | null }; sla_hours: number; overdue: number; oldest_open_hours: number | null; held_quarantine: number };
  feedback: { total: number; verdicts: Record<Verdict, number>; usefulness: number | null };
  checks: { check_id: string; runs: number; failed: number; unknown: number; findings: number; rated: number; usefulness: number | null; unknown_rate: number | null }[];
  top_findings: { code: string; check_id: string; count: number; runs: number; rated: number; false_positive: number; usefulness: number | null }[];
  series: ({ day: string } & Record<string, number | string>)[];
  definitions: Record<string, string>;
}
export interface SuiteSummary { id: string; name: string; description: string; project_id: string; cases: number; created_at: string; created_by: string;
  last_run: null | { id: string; created_at: string; summary: SuiteRunSummary; profile_ref: string; policy_ref: string } }
export interface SuiteRunSummary { total: number; passed: number; failed: number; errors: number; looser_than_expected: number; stricter_than_expected: number; changed_since_last_run: number; all_passed: boolean }
export interface SuiteCase { id: string; name: string; expected: Decision; expected_codes: string[]; filename: string; destination: string; source_class: string; classification: string; note: string; size: number; created_at: string }
export interface SuiteCaseResult { case_id: string; name: string; expected: Decision; actual: Decision | null; ok: boolean; direction: "looser" | "stricter" | null; missing_codes: string[]; codes: string[]; error: string; changed: boolean; was: Decision | null }
export interface SuiteRun { id: string; suite_id: string; suite_name: string; created_at: string; created_by: string; profile_ref: string; policy_ref: string; summary: SuiteRunSummary; cases: SuiteCaseResult[]; note: string }
export interface SuiteFull extends Omit<SuiteSummary, "cases" | "last_run"> { cases: SuiteCase[]; runs: SuiteRun[] }
export interface AssetRow { id: string; name: string; project_id: string; runs: number; versions: number; latest_run: string; latest_decision: Decision | null; latest_state: string; last_seen_at: string; first_seen_at: string; passed: number; held: number; released_to: string[] }
export interface AssetHistory {
  asset: { id: string; name: string; project_id: string; created_at: string; source_class: string; classification: string };
  versions: { version_id: string; version_no: number; digest: string; size: number; runs: number; first_seen_at: string }[];
  timeline: { run_id: string; created_at: string; version_no: number; decision: Decision | null; state: string; reason_codes: string[]; new_reasons: string[]; cleared_reasons: string[]; profile: string; policy: string; destination_id: string | null; label: string; same_content_as_previous: boolean }[];
}
export interface Suggestion { profile: Doc; columns: Record<string, any>[] | Doc; sensitive_types: string[]; records: number; format: string; notes: string[]; lint: { issues: { level: string; path: string; message: string }[]; errors: number; warnings: number; publishable: boolean }; stored: boolean; next: string }
