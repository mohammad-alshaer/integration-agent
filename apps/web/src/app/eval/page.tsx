import Link from "next/link";
import { Brand } from "@/components/Brand";
import { Container } from "@/components/Container";
import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ApiError, EvalSummary, listEvalReports } from "@/lib/api";
import { formatDollars, formatPercent, formatRanAt } from "@/lib/format";

async function loadSummaries(): Promise<{
  data: EvalSummary[] | null;
  error: string | null;
}> {
  try {
    const data = await listEvalReports();
    return { data, error: null };
  } catch (e) {
    if (e instanceof ApiError)
      return { data: null, error: `${e.status}: ${e.message}` };
    return {
      data: null,
      error:
        e instanceof Error
          ? `connect failed: ${e.message}`
          : "connect failed: unknown error",
    };
  }
}

export default async function EvalListPage() {
  const { data, error } = await loadSummaries();

  return (
    <>
      <Brand />
      <main className="flex-1">
        <Container>
          <PageHeader
            overline="benchmark · all runs"
            title="Evaluations"
            subtitle="Each row is a `benchmarks/<pair>/out/eval_report*.json` discovered by the M3 API. Click a run to drill into its rates + per-spec breakdown."
          />
          <section className="py-12">
            {error ? (
              <ApiErrorPanel error={error} />
            ) : (
              <DataTable
                headers={[
                  "run_id",
                  "pair",
                  "provider · model",
                  "expected",
                  "incl. exact",
                  "excl. exact",
                  "$",
                  "ran_at",
                ]}
                rows={(data ?? []).map((s) => [
                  <Link
                    key="r"
                    href={`/eval/${encodeURIComponent(s.run_id)}`}
                    className="font-mono text-[14px] tracking-[-0.28px] text-cyan hover:underline"
                  >
                    {s.run_id}
                  </Link>,
                  <span key="p" className="text-white">
                    {s.pair}
                  </span>,
                  <span key="m" className="font-mono text-[14px] text-ghost">
                    {s.provider} · {s.model}
                  </span>,
                  <span key="e" className="font-mono text-ghost">
                    {s.expected_count}
                  </span>,
                  <span key="i" className="font-mono text-white">
                    {formatPercent(s.exact_match_rate_inclusive)}
                  </span>,
                  <span key="x" className="font-mono text-white">
                    {formatPercent(s.exact_match_rate_exclusive)}
                  </span>,
                  <span key="d" className="font-mono text-ghost">
                    {formatDollars(s.pipeline_dollars_total)}
                  </span>,
                  <span key="t" className="font-mono text-[12px] text-whisper">
                    {formatRanAt(s.ran_at)}
                  </span>,
                ])}
                emptyState={
                  <div>
                    <p className="text-ghost">
                      No eval reports found under{" "}
                      <span className="font-mono text-white">benchmarks/</span>.
                    </p>
                    <p className="mt-2 font-mono text-[14px] text-whisper">
                      run: python -m evals --pair adventureworks
                    </p>
                  </div>
                }
              />
            )}
          </section>
        </Container>
      </main>
    </>
  );
}

function ApiErrorPanel({ error }: { error: string }) {
  return (
    <div className="rounded-md border border-mist-10 bg-black p-8">
      <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
        api unreachable
      </p>
      <p className="mt-3 text-white">{error}</p>
      <p className="mt-4 font-mono text-[14px] text-ghost">
        is uvicorn running? try:{" "}
        <span className="text-white">
          ./.venv/Scripts/python.exe -m uvicorn api.main:app --reload
        </span>
      </p>
    </div>
  );
}
