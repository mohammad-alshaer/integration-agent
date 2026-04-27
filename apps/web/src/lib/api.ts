// TS mirror of the Python contracts in:
//   packages/schemas/src/schemas/api.py        (EvalSummary, MapRequest, etc.)
//   packages/evals/src/evals/models.py:60-112  (ScoreEntry, EvalReport, MatchLevel)
//   packages/schemas/src/schemas/patterns.py   (Pattern enum)
// Hand-maintained for M4.1; auto-gen from /openapi.json is a future M4.x improvement.

export type Pattern =
  | "rename"
  | "concat"
  | "split"
  | "derived"
  | "constant"
  | "lookup"
  | "unsupported_in_m1";

export type MatchLevel =
  | "exact"
  | "pattern"
  | "sql_exec_equivalent"
  | "sql_semantic"
  | "mismatch"
  | "missing"
  | "extra";

export interface EvalSummary {
  run_id: string;
  pair: string;
  provider: string;
  model: string;
  ran_at: string;
  expected_count: number;
  exact_match_rate_inclusive: number;
  exact_match_rate_exclusive: number;
  pipeline_dollars_total: number;
  report_path: string;
}

export interface ScoreEntry {
  target_fqn: string;
  expected_pattern: Pattern | null;
  actual_pattern: Pattern | null;
  level: MatchLevel;
  disputed: boolean;
  expected_source_fqns: string[];
  actual_source_fqns: string[];
  actual_sql: string | null;
  actual_llm_confidence: number | null;
  actual_validation_pass_rate: number | null;
}

export interface EvalReport {
  pair: string;
  provider: string;
  model: string;
  run_id: string;
  ran_at: string;
  expected_count: number;
  actual_count: number;
  exact_match_count: number;
  pattern_match_count: number;
  sql_exec_equivalent_match_count: number;
  sql_semantic_match_count: number;
  missing_count: number;
  extra_count: number;
  mismatch_count: number;
  rates: Record<string, Record<string, number>>;
  per_pattern: Record<string, Record<string, number>>;
  mean_llm_confidence: number | null;
  mean_validation_pass_rate: number | null;
  prompt_cache_hit_rate: number | null;
  tokens_in_total: number;
  tokens_out_total: number;
  pipeline_total_llm_calls: number;
  pipeline_total_tokens_in: number;
  pipeline_total_tokens_out: number;
  pipeline_cache_hit_rate: number | null;
  pipeline_dollars_in: number;
  pipeline_dollars_out: number;
  pipeline_dollars_total: number;
  entries: ScoreEntry[];
}

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const listEvalReports = () => apiFetch<EvalSummary[]>("/eval");
export const getEvalReport = (runId: string) =>
  apiFetch<EvalReport>(`/eval/${encodeURIComponent(runId)}`);
