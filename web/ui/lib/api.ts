// Types mirror comprev.schemas (the engine's source-of-truth contract) and the
// backend's thin response envelopes (web/api/comprev_web/models.py).

export type CheckStatus = "pass" | "fail" | "uncertain";
export type OverallStatus = "pass" | "fail" | "needs_review";
export type Severity = "serious" | "normal";

export interface Evidence {
  surface: "visual" | "audio";
  timestamp: string | null;
  frame_index: number | null;
  quote: string;
  ocr_confidence: number | null;
  asr_confidence: number | null;
}

export interface CheckResult {
  check_id: string;
  status: CheckStatus;
  severity: Severity;
  confidence: number;
  surfaces_evaluated: ("visual" | "audio")[];
  summary?: string;
  findings?: string[];
  reasoning: string;
  evidence: Evidence[];
  policy_ref: string;
  low_confidence_inputs: boolean;
  not_applicable: boolean;
}

export interface VideoReport {
  video_id: string;
  product: string;
  duration_seconds: number;
  overall_status: OverallStatus;
  checks: CheckResult[];
  needs_human_review: boolean;
  review_reasons: string[];
  // The policy this verdict was judged under (stamped at review time).
  policy_version?: string | null;
  policy_source?: string | null;
  checks_hash?: string | null;
  // Present when the original upload was preserved (out/<id>/source.*); null for
  // older reports run before previews existed.
  media_kind?: MediaKind | null;
}

// Mirrors comprev.schemas.Check — one entry in the compliance check library.
export interface Check {
  id: string;
  description: string;
  surface: "visual" | "audio" | "both";
  severity: Severity;
  applies_when: string;
  method: "text" | "vision";
  required_text: string | null;
  min_on_screen_seconds: number | null;
  policy_ref: string;
  pass_criteria: string;
  notes: string | null;
}

// One policy source file on disk (config/*.yaml) driving every review.
export interface PolicyFile {
  name: string;
  title: string;
  description: string;
  size_bytes: number;
  modified_at: number;
  n_checks: number | null;
}

export interface ReportSummary {
  video_id: string;
  overall_status: OverallStatus;
  needs_human_review: boolean;
  duration_seconds: number;
  n_checks: number;
  modified_at: number;
  media_kind?: MediaKind | null;
}

export interface Health {
  ok: boolean;
  anthropic_key_present: boolean;
  ml_extras_present: boolean;
}

export type MediaKind = "video" | "image" | "audio";

export type JobStage =
  | "queued"
  | "sampling"
  | "transcribing"
  | "evaluating"
  | "routing"
  | "done"
  | "error";

export interface JobStatus {
  job_id: string;
  video_id: string;
  kind: MediaKind;
  stage: JobStage;
  report_ready: boolean;
  error: string | null;
}

// Server Components can't use the browser /api rewrite, so they call the
// backend directly. Override with BACKEND_URL in the environment.
const SERVER_BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function fetchReports(): Promise<ReportSummary[]> {
  const res = await fetch(`${SERVER_BASE}/api/reports`, { cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function fetchReport(videoId: string): Promise<VideoReport | null> {
  const res = await fetch(
    `${SERVER_BASE}/api/reports/${encodeURIComponent(videoId)}`,
    { cache: "no-store" },
  );
  if (!res.ok) return null;
  return res.json();
}

export interface RenameResult {
  ok: boolean;
  video_id?: string;
  error?: string;
}

// Called only from a client component, so it hits the same-origin /api proxy.
export async function renameReport(
  oldId: string,
  newId: string,
): Promise<RenameResult> {
  const res = await fetch(`/api/reports/${encodeURIComponent(oldId)}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_id: newId }),
  });
  if (res.ok) {
    const data = await res.json();
    return { ok: true, video_id: data.video_id };
  }
  const detail = await res.json().catch(() => null);
  return { ok: false, error: detail?.detail ?? "Rename failed." };
}

export async function fetchActiveJobs(): Promise<JobStatus[]> {
  try {
    const res = await fetch(`${SERVER_BASE}/api/jobs`, { cache: "no-store" });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export async function fetchChecks(): Promise<Check[]> {
  const res = await fetch(`${SERVER_BASE}/api/checks`, { cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function fetchPolicyFiles(): Promise<PolicyFile[]> {
  const res = await fetch(`${SERVER_BASE}/api/policies`, { cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function fetchHealth(): Promise<Health | null> {
  try {
    const res = await fetch(`${SERVER_BASE}/api/health`, { cache: "no-store" });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}
