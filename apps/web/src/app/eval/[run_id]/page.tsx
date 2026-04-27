import Link from "next/link";
import { notFound } from "next/navigation";
import { Brand } from "@/components/Brand";
import { Container } from "@/components/Container";
import { Card } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import {
  DisputedTag,
  MatchLevelBadge,
  PatternBadge,
} from "@/components/Badge";
import {
  ApiError,
  EvalReport,
  ScoreEntry,
  getEvalReport,
} from "@/lib/api";
import { formatDollars, formatPercent, formatRanAt } from "@/lib/format";

const LEVELS = ["exact", "pattern", "sql_exec_equivalent", "sql_semantic"] as const;
const LEVEL_LABEL: Record<(typeof LEVELS)[number], string> = {
  exact: "exact",
  pattern: "pattern",
  sql_exec_equivalent: "sql · exec",
  sql_semantic: "sql · semantic",
};

export default async function EvalDetailPage({
  params,
}: {
  params: Promise<{ run_id: string }>;
}) {
  const { run_id } = await params;
  let report: EvalReport;
  try {
    report = await getEvalReport(run_id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }

  return (
    <>
      <Brand />
      <main className="flex-1">
        <Container>
          <PageHeader
            overline={`run · ${report.run_id}`}
            title={
              <>
                {report.pair}
                <span className="text-ghost"> · </span>
                <span className="text-cyan">{report.provider}</span>
              </>
            }
            subtitle={
              <span className="font-mono text-[14px] tracking-[-0.28px] text-ghost">
                {report.model} · {formatRanAt(report.ran_at)} ·{" "}
                {report.expected_count} expected · {report.actual_count} actual ·{" "}
                {formatDollars(report.pipeline_dollars_total)}
              </span>
            }
          />

          <section className="py-12">
            <h2 className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper mb-4">
              rates
            </h2>
            <RatesMatrix rates={report.rates} />
          </section>

          <section className="py-12">
            <h2 className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper mb-4">
              entries · {report.entries.length}
            </h2>
            <EntriesTable entries={report.entries} />
          </section>

          <div className="border-t border-mist-06 py-8">
            <Link
              href="/eval"
              className="font-mono text-[14px] text-ghost hover:text-cyan transition-colors"
            >
              ← all evaluations
            </Link>
          </div>
        </Container>
      </main>
    </>
  );
}

function RatesMatrix({
  rates,
}: {
  rates: Record<string, Record<string, number>>;
}) {
  const scopes = ["inclusive", "exclusive"];
  return (
    <Card brutalist className="p-0 overflow-hidden">
      <div className="grid grid-cols-[120px_repeat(4,1fr)] divide-x divide-mist-08">
        <div className="bg-black px-4 py-4" />
        {LEVELS.map((l) => (
          <div
            key={l}
            className="bg-black px-4 py-4 font-mono text-[12px] uppercase tracking-[0.7px] text-whisper"
          >
            {LEVEL_LABEL[l]}
          </div>
        ))}
        {scopes.map((scope) => (
          <Row key={scope} scope={scope} rates={rates[scope] ?? {}} />
        ))}
      </div>
    </Card>
  );
}

function Row({
  scope,
  rates,
}: {
  scope: string;
  rates: Record<string, number>;
}) {
  return (
    <>
      <div className="border-t border-mist-08 px-4 py-6 font-mono text-[12px] uppercase tracking-[0.7px] text-ghost">
        {scope}
      </div>
      {LEVELS.map((l) => {
        const value = rates[l] ?? 0;
        const isExact = l === "exact";
        return (
          <div
            key={l}
            className={`border-t border-mist-08 px-4 py-6 ${
              isExact && value > 0.9 ? "bg-[var(--color-cyan-glow)]" : ""
            }`}
          >
            <div className="font-mono text-2xl tracking-[-0.48px] text-white">
              {formatPercent(value)}
            </div>
          </div>
        );
      })}
    </>
  );
}

function EntriesTable({ entries }: { entries: ScoreEntry[] }) {
  return (
    <DataTable
      headers={[
        "target",
        "expected",
        "actual",
        "level",
        "sources",
        "llm_conf",
        "validation",
      ]}
      rows={entries.map((e) => entryRow(e))}
      emptyState={<p className="text-whisper">no entries scored.</p>}
    />
  );
}

function entryRow(e: ScoreEntry) {
  const dim = e.disputed ? "text-whisper" : "text-white";
  return [
    <div key="t" className="space-y-2">
      {e.disputed && <DisputedTag />}
      <div className={`font-mono text-[14px] tracking-[-0.28px] ${dim}`}>
        {e.target_fqn}
      </div>
    </div>,
    <PatternBadge key="ep" pattern={e.expected_pattern} />,
    <PatternBadge key="ap" pattern={e.actual_pattern} />,
    <MatchLevelBadge key="l" level={e.level} />,
    <div key="s" className="font-mono text-[12px] text-ghost space-y-1">
      {e.actual_source_fqns.length === 0 ? (
        <span className="text-phantom">—</span>
      ) : (
        e.actual_source_fqns.map((s) => <div key={s}>{s}</div>)
      )}
    </div>,
    <span key="c" className="font-mono text-[14px] text-ghost">
      {e.actual_llm_confidence == null
        ? "—"
        : e.actual_llm_confidence.toFixed(2)}
    </span>,
    <span key="v" className="font-mono text-[14px] text-ghost">
      {e.actual_validation_pass_rate == null
        ? "—"
        : formatPercent(e.actual_validation_pass_rate, 0)}
    </span>,
  ];
}
