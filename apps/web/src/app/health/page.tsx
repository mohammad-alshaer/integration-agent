"use client";

import { useEffect, useState } from "react";
import { Container } from "@/components/Container";
import { PageHeader } from "@/components/PageHeader";
import { Spinner } from "@/components/Spinner";
import { ApiError, HealthResponse, getHealth } from "@/lib/api";

export default function HealthPage() {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [probing, setProbing] = useState(false);
  const [deepResult, setDeepResult] = useState<Record<string, unknown> | null>(
    null,
  );
  const [deepError, setDeepError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const d = await getHealth();
        if (!cancelled) setData(d);
      } catch (e) {
        if (cancelled) return;
        setError(
          e instanceof ApiError
            ? `${e.status}: ${e.message}`
            : e instanceof Error
              ? `connect failed: ${e.message}`
              : "connect failed",
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function runDeepProbe() {
    setProbing(true);
    setDeepError(null);
    setDeepResult(null);
    try {
      const d = await getHealth(true);
      setDeepResult(d.deep_check ?? null);
    } catch (e) {
      setDeepError(
        e instanceof ApiError ? `${e.status}: ${e.message}` : "probe failed",
      );
    } finally {
      setProbing(false);
    }
  }

  return (
    <main className="flex-1 relative">
      <Container>
        <div className="stagger stagger-1">
          <PageHeader
            overline="api · liveness"
            title="Health"
            subtitle="Default GET /health is a cheap liveness probe — no LLM call. ?deep=true runs a single LLMClient.structured() round-trip via the API. Off by default to keep monitors from burning quota."
          />
        </div>

        <section className="py-12 stagger stagger-2">
          {error ? (
            <div className="glass glass-rim rounded-md p-8 border-red-500/30">
              <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-red-400">
                api unreachable
              </p>
              <p className="mt-3 text-white">{error}</p>
              <p className="mt-3 font-mono text-[14px] text-ghost">
                is uvicorn running?
              </p>
            </div>
          ) : !data ? (
            <div className="glass rounded-md p-8">
              <div className="flex items-center gap-3 text-ghost">
                <Spinner />
                <span className="font-mono text-[14px]">checking…</span>
              </div>
            </div>
          ) : (
            <div className="glass glass-rim rounded-md p-8 md:p-10 shadow-[var(--shadow-lift)]">
              <div className="grid gap-x-12 gap-y-8 md:grid-cols-2">
                <Field label="status" value={data.status} accent />
                <Field
                  label="vector db"
                  value={data.vector_db_exists ? "exists" : "missing"}
                  accent={data.vector_db_exists}
                />
                <Field
                  label="llm"
                  value={`${data.llm_provider} · ${data.llm_model}`}
                />
                <Field
                  label="embedder"
                  value={`${data.embedder_provider} · ${data.embedder_model} · ${data.embedder_dims} dims`}
                />
              </div>
            </div>
          )}
        </section>

        <section className="py-12 border-t border-mist-08 space-y-6 stagger stagger-3">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
              deep probe · 1 LLM call
            </h2>
            <span className="font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
              opt-in · cached re-runs are free
            </span>
          </div>
          <p className="text-base text-ghost max-w-2xl leading-relaxed">
            Round-trips a trivial Pydantic schema through{" "}
            <span className="font-mono text-white">LLMClient.structured()</span>
            . Burns one cache slot but proves end-to-end connectivity, auth,
            and schema validation. Cached re-runs are free.
          </p>
          <button
            type="button"
            onClick={runDeepProbe}
            disabled={probing || !data}
            className={`cta-primary inline-flex items-center gap-2 rounded-md px-6 py-3 font-mono text-[14px] uppercase tracking-[0.55px] transition-all ${
              probing || !data
                ? "bg-phantom text-whisper cursor-not-allowed"
                : "bg-white text-black"
            }`}
          >
            {probing ? "probing…" : "run deep probe"}
            {!probing && <span aria-hidden>→</span>}
          </button>

          {probing && (
            <div className="flex items-center gap-3 text-ghost">
              <Spinner />
              <span className="font-mono text-[14px]">
                awaiting LLM round-trip
              </span>
            </div>
          )}
          {deepError && (
            <div className="glass rounded-md p-6 border-red-500/30">
              <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-red-400">
                probe error
              </p>
              <p className="mt-3 text-white">{deepError}</p>
            </div>
          )}
          {deepResult && (
            <div className="glass glass-rim rounded-md p-6 md:p-7 shadow-[var(--shadow-lift)]">
              <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-cyan">
                deep_check
              </p>
              <pre className="mt-3 overflow-x-auto font-mono text-[14px] tracking-[-0.28px] text-white">
                {JSON.stringify(deepResult, null, 2)}
              </pre>
            </div>
          )}
        </section>
      </Container>
    </main>
  );
}

function Field({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div>
      <p className="font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
        {label}
      </p>
      <p
        className={`mt-2 font-mono text-[18px] tracking-[-0.32px] ${
          accent ? "text-cyan" : "text-white"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
