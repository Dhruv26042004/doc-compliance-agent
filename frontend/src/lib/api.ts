export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Rect = { page: number; bbox: [number, number, number, number] };

export type DocumentSummary = {
  id: string;
  filename: string;
  file_type: string;
  size_bytes: number;
  n_pages: number;
  n_clauses: number;
  has_layout: boolean;
  warnings: string[];
  created_at: string;
};

export type Clause = {
  id: string;
  idx: number;
  char_start: number;
  char_end: number;
  text: string;
  page_start: number | null;
  page_end: number | null;
  rects: Rect[];
};

export type DocumentDetail = DocumentSummary & {
  text: string;
  pages: { number: number; width: number; height: number }[];
  clauses: Clause[];
};

export type DecisionKind = "finding" | "rejected_finding" | "possible_miss" | "missing_required";
export type DecisionStatus = "auto" | "pending" | "approved" | "overridden";

export type Decision = {
  id: string;
  position: number;
  clause_id: string | null;
  clause_idx: number | null;
  rule_id: string;
  rule_title: string;
  severity: string;
  kind: DecisionKind;
  proposed_applies: boolean;
  verdict: "violation" | "flag" | "satisfies" | "violated" | "none";
  route: "auto" | "review";
  route_reason: string;
  quote: string | null;
  quote_start: number | null;
  quote_end: number | null;
  explanation: string;
  confidence: number | null;
  rects: Rect[];
  status: DecisionStatus;
  final_applies: boolean | null;
  reviewer: string | null;
  review_reason: string | null;
  reviewed_at: string | null;
};

export type RuleStatus = "violated" | "flagged" | "satisfied" | "clear" | "pending";

export type Analysis = {
  id: string;
  document_id: string;
  created_at: string;
  policy_id: string;
  policy_version: number;
  pipeline: string;
  prompt_hash: string;
  model_version: string;
  auto_threshold: number;
  llm_calls: number;
  clauses_screened_out: number;
  status: "needs_review" | "complete";
  rule_status: Record<string, RuleStatus>;
  n_auto: number;
  n_pending: number;
  decisions: Decision[];
};

export type QueueItem = Decision & {
  analysis_id: string;
  document_id: string;
  filename: string;
  clause_text: string | null;
};

export type Rule = {
  id: string;
  title: string;
  kind: "required" | "prohibited" | "review";
  severity: "low" | "medium" | "high";
  definition: string;
};

export type Policy = { policy_id: string; version: number; rules: Rule[] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(
      0,
      "Can't reach the API. On free hosting it sleeps when idle and takes about a minute to wake up; reload the page shortly.",
    );
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {}
    throw new ApiError(resp.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return resp.status === 204 ? (undefined as T) : resp.json();
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const api = {
  documents: () => request<DocumentSummary[]>("/documents"),
  document: (id: string) => request<DocumentDetail>(`/documents/${id}`),
  fileUrl: (id: string) => `${API_URL}/documents/${id}/file`,
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentDetail>("/documents", { method: "POST", body: form });
  },
  analyze: (id: string) => request<Analysis>(`/documents/${id}/analyze`, { method: "POST" }),
  latestAnalysis: (id: string) =>
    request<Analysis>(`/documents/${id}/analysis`).catch((e) => {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }),
  queue: (ruleId?: string) => request<QueueItem[]>(`/reviews/queue${ruleId ? `?rule_id=${ruleId}` : ""}`),
  review: (decisionId: string, action: "approve" | "override", reviewer: string, reason?: string) =>
    request<Decision>(`/decisions/${decisionId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, reviewer, reason: reason || null }),
    }),
  policy: () => request<Policy>("/policy"),
};

export type RuleMetrics = {
  rule_id: string;
  title: string;
  decisions: number;
  auto: number;
  pending: number;
  reviewed: number;
  overridden: number;
  override_rate: number | null;
  reviewer_precision: number | null;
};

export type Metrics = {
  documents: number;
  analyses: number;
  decisions: number;
  auto_decisions: number;
  automation_rate: number | null;
  clauses_analyzed: number;
  clauses_without_human: number | null;
  pending_reviews: number;
  reviewed: number;
  override_rate: number | null;
  labels: number;
  rules: RuleMetrics[];
  volume: { day: string; uploaded: number; analyzed: number; reviewed: number }[];
};

export type EvalRun = {
  file: string;
  split: string;
  run_at: string;
  model_version: string;
  pipeline: string;
  policy_version: number;
  n_clauses: number;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  llm_calls: number;
  per_rule: Record<string, { precision: number | null; recall: number | null }>;
};

export const metricsApi = {
  metrics: () => request<Metrics>("/metrics"),
  evals: () => request<EvalRun[]>("/metrics/evals"),
};
