// TS mirror of the Python contracts in:
//   packages/schemas/src/schemas/api.py        (EvalSummary, MapRequest, MapResponse, HealthResponse)
//   packages/schemas/src/schemas/mapping.py    (MappingSpec, DbtTest)
//   packages/schemas/src/schemas/profile.py    (SchemaProfile, TableProfile)
//   packages/evals/src/evals/models.py:60-112  (ScoreEntry, EvalReport, MatchLevel)
//   packages/schemas/src/schemas/patterns.py   (Pattern enum)
// Hand-maintained; auto-gen from /openapi.json is M4.x.

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

// SchemaProfile: structurally validated by the API; we read .tables[i].table_schema/table_name
// in the UI for the target-table picker. Other fields pass through unchanged.
export interface SchemaProfile {
  database_name: string;
  role: string;
  tables: Array<{ table_schema: string; table_name: string; [key: string]: unknown }>;
  profiled_at: string;
  [key: string]: unknown;
}

export interface DbtTest {
  name: string;
  config: Record<string, unknown>;
}

export interface MappingSpec {
  target_fqn: string;
  source_fqns: string[];
  pattern: Pattern;
  sql: string;
  rationale: string;
  tests: DbtTest[];
  llm_confidence: number;
  validation_pass_rate: number | null;
  provider: string;
  model: string;
  prompt_cache_hit: boolean;
  tokens_in: number;
  tokens_out: number;
}

export interface MapRequest {
  source_profile: SchemaProfile;
  target_profile: SchemaProfile;
  target_table: string;
  k_candidates: number;
  max_retries: number;
  rebuild_index: boolean;
  sample_dir: string | null;
}

export interface MapResponse {
  target_table: string;
  specs: MappingSpec[];
  classifications_summary: Record<string, number>;
  validation_summary: { passed: number; failed: number } | null;
  retry_count: number;
  elapsed_sec: number;
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

async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
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

export const submitMap = (body: MapRequest, signal?: AbortSignal) =>
  apiFetch<MapResponse>("/map", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
