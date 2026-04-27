"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Container } from "@/components/Container";
import { MappingSpecCard } from "@/components/MappingSpecCard";
import { NumberField, Toggle } from "@/components/NumberField";
import { PageHeader } from "@/components/PageHeader";
import { ProfileUploader } from "@/components/ProfileUploader";
import { Select } from "@/components/Select";
import { Spinner, PulseDot } from "@/components/Spinner";
import {
  ApiError,
  MapResponse,
  SchemaProfile,
  submitMap,
} from "@/lib/api";

export default function MapPage() {
  const [source, setSource] = useState<SchemaProfile | null>(null);
  const [target, setTarget] = useState<SchemaProfile | null>(null);
  const [targetTable, setTargetTable] = useState("");
  const [k, setK] = useState(15);
  const [maxRetries, setMaxRetries] = useState(1);
  const [rebuildIndex, setRebuildIndex] = useState(true);

  const [submitting, setSubmitting] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<MapResponse | null>(null);
  const [error, setError] = useState<{
    status: number | null;
    message: string;
  } | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const targetTableOptions = useMemo(() => {
    if (!target) return [];
    return target.tables.map((t) => ({
      value: `${t.table_schema}.${t.table_name}`,
      label: `${t.table_schema}.${t.table_name}`,
    }));
  }, [target]);

  function handleTargetLoad(profile: SchemaProfile | null) {
    setTarget(profile);
    setTargetTable("");
  }

  // Tick elapsed time while submitting. setElapsed(0) is called in onSubmit to
  // satisfy react-hooks/set-state-in-effect (no synchronous setState in effects).
  useEffect(() => {
    if (!submitting) return;
    const start = Date.now();
    const tick = window.setInterval(() => {
      setElapsed((Date.now() - start) / 1000);
    }, 250);
    return () => window.clearInterval(tick);
  }, [submitting]);

  const canSubmit = source && target && targetTable && !submitting;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!source || !target || !targetTable) return;
    setError(null);
    setResult(null);
    setElapsed(0);
    setSubmitting(true);
    abortRef.current = new AbortController();
    try {
      const data = await submitMap(
        {
          source_profile: source,
          target_profile: target,
          target_table: targetTable,
          k_candidates: k,
          max_retries: maxRetries,
          rebuild_index: rebuildIndex,
          sample_dir: null,
        },
        abortRef.current.signal,
      );
      setResult(data);
    } catch (e) {
      if (e instanceof ApiError) {
        setError({ status: e.status, message: e.message });
      } else if (e instanceof DOMException && e.name === "AbortError") {
        setError({ status: null, message: "request cancelled" });
      } else {
        setError({
          status: null,
          message:
            e instanceof Error
              ? `connect failed: ${e.message}`
              : "unknown error",
        });
      }
    } finally {
      setSubmitting(false);
      abortRef.current = null;
    }
  }

  function cancel() {
    abortRef.current?.abort();
  }

  return (
    <main className="flex-1 relative">
      <Container>
        <div className="stagger stagger-1">
          <PageHeader
            overline="map · run the graph"
            title={
              <>
                Map a target table
              </>
            }
            subtitle="Submit source + target SchemaProfile JSON, pick a target table, run the LangGraph pipeline. Returns one MappingSpec per target column with pattern, SQL, and validation pass-rate. Cached runs return in seconds; cold-cache full tables can take up to 5 minutes."
          />
        </div>

        <form onSubmit={onSubmit} className="space-y-8 py-12">
          <FormPanel className="stagger stagger-2" step="01" title="Inputs">
            <div className="grid gap-6 md:grid-cols-2">
              <ProfileUploader
                label="source profile"
                hint="e.g. tmp/profiles/aw2022_filtered.json"
                onLoad={setSource}
              />
              <ProfileUploader
                label="target profile"
                hint="e.g. tmp/profiles/awdw2022.json"
                onLoad={handleTargetLoad}
              />
            </div>
            <div className="mt-6">
              <Select
                label="target table"
                value={targetTable}
                onChange={setTargetTable}
                options={targetTableOptions}
                placeholder={
                  target
                    ? `pick one of ${targetTableOptions.length} tables`
                    : "load a target profile first"
                }
                disabled={!target}
              />
            </div>
          </FormPanel>

          <FormPanel className="stagger stagger-3" step="02" title="Options">
            <div className="grid gap-6 md:grid-cols-3">
              <NumberField
                label="k candidates"
                value={k}
                onChange={setK}
                min={5}
                max={50}
                hint="HNSW top-K (default 15)"
              />
              <NumberField
                label="max retries"
                value={maxRetries}
                onChange={setMaxRetries}
                min={0}
                max={3}
                hint="DERIVED retry on validator failure (default 1)"
              />
              <Toggle
                label="rebuild index"
                checked={rebuildIndex}
                onChange={setRebuildIndex}
                hint="reset + re-embed source on this request"
              />
            </div>
          </FormPanel>

          <section className="flex flex-wrap items-center gap-4 stagger stagger-4">
            <button
              type="submit"
              disabled={!canSubmit}
              className={`cta-primary inline-flex items-center gap-2 rounded-md px-6 py-3 font-mono text-[14px] uppercase tracking-[0.55px] transition-all ${
                canSubmit
                  ? "bg-white text-black"
                  : "bg-phantom text-whisper cursor-not-allowed"
              }`}
            >
              {submitting
                ? `mapping…  ${elapsed.toFixed(1)}s`
                : "run mapping"}
              {!submitting && <span aria-hidden>→</span>}
            </button>
            {submitting && (
              <button
                type="button"
                onClick={cancel}
                className="rounded-md border border-charcoal px-4 py-3 font-mono text-[14px] uppercase tracking-[0.55px] text-ghost hover:text-white hover:border-mist-12 transition-colors"
              >
                cancel
              </button>
            )}
            {submitting && (
              <span className="ml-2 inline-flex items-center gap-3 text-base text-ghost">
                <Spinner />
                <span className="font-mono text-[14px] tracking-[-0.28px]">
                  POST /map · single thread · cached ~10s, cold up to 5min
                </span>
              </span>
            )}
          </section>
        </form>

        {error && <ErrorPanel status={error.status} message={error.message} />}
        {result && <ResultPanel result={result} />}
      </Container>
    </main>
  );
}

function FormPanel({
  step,
  title,
  children,
  className = "",
}: {
  step: string;
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`glass rounded-md p-6 md:p-8 shadow-[0_20px_60px_-30px_rgba(0,0,0,0.6)] ${className}`}
    >
      <div className="flex items-baseline gap-3 mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.55px] text-cyan">
          {step}
        </span>
        <span className="block w-px h-3 bg-mist-12" aria-hidden />
        <h2 className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

function ErrorPanel({
  status,
  message,
}: {
  status: number | null;
  message: string;
}) {
  return (
    <div className="glass glass-rim my-12 rounded-md p-8 border-red-500/30">
      <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-red-400">
        {status ? `error ${status}` : "error"}
      </p>
      <p className="mt-3 text-white">{message}</p>
      {status === 504 && (
        <p className="mt-2 font-mono text-[14px] text-whisper">
          the graph exceeded the 600s timeout. try a smaller table, or run
          cold-cache via the CLI.
        </p>
      )}
      {status === 422 && (
        <p className="mt-2 font-mono text-[14px] text-whisper">
          request body failed pydantic validation — check that both profiles
          are full SchemaProfile shapes.
        </p>
      )}
    </div>
  );
}

function ResultPanel({ result }: { result: MapResponse }) {
  const summary = result.classifications_summary;
  const summaryEntries = Object.entries(summary).sort(
    (a, b) => (b[1] as number) - (a[1] as number),
  );
  return (
    <section className="space-y-8 pb-16">
      <div className="glass glass-rim rounded-md p-6 md:p-8 shadow-[var(--shadow-lift)]">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
              result · target table
            </p>
            <h2 className="mt-2 font-mono text-3xl md:text-4xl tracking-[-0.04em] text-white">
              {result.target_table}
            </h2>
          </div>
          <div className="flex items-center gap-3">
            <PulseDot />
            <span className="font-mono text-[14px] text-cyan">
              {result.elapsed_sec.toFixed(2)}s
            </span>
          </div>
        </div>
        <div className="mt-7 grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-4">
          <Metric label="specs" value={result.specs.length} />
          <Metric label="retries" value={result.retry_count} />
          <Metric
            label="validated"
            value={
              result.validation_summary
                ? `${result.validation_summary.passed} / ${
                    result.validation_summary.passed +
                    result.validation_summary.failed
                  }`
                : "—"
            }
          />
          <Metric
            label="patterns"
            value={
              summaryEntries.map(([k, v]) => `${k}:${v}`).join(" · ") || "—"
            }
          />
        </div>
      </div>

      <h2 className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
        specs · {result.specs.length}
      </h2>
      <div className="grid gap-6">
        {result.specs.map((spec) => (
          <MappingSpecCard key={spec.target_fqn} spec={spec} />
        ))}
      </div>
    </section>
  );
}

function Metric({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div>
      <p className="font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
        {label}
      </p>
      <p className="mt-2 font-mono text-[18px] tracking-[-0.32px] text-white">
        {value}
      </p>
    </div>
  );
}
