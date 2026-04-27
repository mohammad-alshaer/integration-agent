import Link from "next/link";
import { notFound } from "next/navigation";
import { Container } from "@/components/Container";
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

const LEVELS = [
  "exact",
  "pattern",
  "sql_exec_equivalent",
  "sql_semantic",
] as const;
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
    <main className="flex-1 relative">
      <Container>
        <div className="stagger stagger-1">
          <PageHeader
            overline={`run · ${report.run_id}`}
            title={
              <>
                {report.pair}
                <span className="text-ghost"> · </span>
                <span className="text-gradient-cyan">{report.provider}</span>
              </>
            }
            subtitle={
              <div className="mt-2 flex flex-wrap gap-2">
                <MetaPill label="model" value={report.model} mono />
                <MetaPill label="ran" value={formatRanAt(report.ran_at)} mono />
                <MetaPill label="expected" value={String(report.expected_count)} />
                <MetaPill label="actual" value={String(report.actual_count)} />
                <MetaPill
                  label="cost"
                  value={formatDollars(report.pipeline_dollars_total)}
                />
              </div>
            }
          />
        </div>

        <section className="py-12 stagger stagger-2">
          <h2 className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper mb-4">
            rates
          </h2>
          <RatesMatrix rates={report.rates} />
        </section>

        <section className="py-12 stagger stagger-3">
          <div className="flex items-baseline justify-between mb-4">
            <h2 className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
              entries · {report.entries.length}
            </h2>
          </div>
          <EntriesTable entries={report.entries} />
        </section>

        <div className="border-t border-mist-06 py-8 stagger stagger-4">
          <Link
            href="/eval"
            className="inline-flex items-center gap-2 font-mono text-[14px] text-ghost hover:text-cyan transition-colors"
          >
            <span aria-hidden className="transition-transform group-hover:-translate-x-1">←</span>
            all evaluations
          </Link>
        </div>
      </Container>
    </main>
  );
}

function MetaPill({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2 rounded-pill border border-mist-10 bg-black/40 backdrop-blur px-3 py-1">
      <span className="font-mono text-[10px] uppercase tracking-[0.55px] text-whisper">
        {label}
      </span>
      <span
        className={`text-[13px] text-ghost ${mono ? "font-mono tracking-[-0.26px]" : ""}`}
      >
        {value}
      </span>
    </span>
  );
}

function RatesMatrix({
  rates,
}: {
  rates: Record<string, Record<string, number>>;
}) {
  const scopes = ["inclusive", "exclusive"];
  return (
    <div className="glass glass-rim rounded-md overflow-hidden shadow-[var(--shadow-lift)]">
      <div className="grid grid-cols-[120px_repeat(4,1fr)] divide-x divide-mist-08">
        <div className="px-4 py-4" />
        {LEVELS.map((l) => (
          <div
            key={l}
            className="px-4 py-4 font-mono text-[12px] uppercase tracking-[0.7px] text-whisper"
          >
            {LEVEL_LABEL[l]}
          </div>
        ))}
        {scopes.map((scope) => (
          <Row key={scope} scope={scope} rates={rates[scope] ?? {}} />
        ))}
      </div>
    </div>
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
      <div className="border-t border-mist-08 px-4 py-7 font-mono text-[12px] uppercase tracking-[0.7px] text-ghost">
        {scope}
      </div>
      {LEVELS.map((l) => {
        const value = rates[l] ?? 0;
        const high = value >= 0.9;
        return (
          <div
            key={l}
            className={`relative border-t border-mist-08 px-4 py-7 ${
              high ? "bg-[var(--color-cyan-glow)]" : ""
            }`}
          >
            <div
              className={`font-mono text-2xl md:text-3xl tracking-[-0.04em] ${
                high ? "text-cyan" : "text-white"
              }`}
            >
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
