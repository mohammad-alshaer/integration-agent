"use client";

import { useEffect, useState } from "react";
import { Brand } from "@/components/Brand";
import { Card } from "@/components/Card";
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
    <>
      <Brand />
      <main className="flex-1">
        <Container>
          <PageHeader
            overline="api · liveness"
            title="Health"
            subtitle="Default GET /health is a cheap liveness probe — no LLM call. ?deep=true runs a single LLMClient.structured() round-trip via the API. Off by default to keep monitors from burning quota."
          />

          <section className="py-12 space-y-8">
            {error ? (
              <Card className="border-red-500/30">
                <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-red-400">
                  api unreachable
                </p>
                <p className="mt-3 text-white">{error}</p>
                <p className="mt-3 font-mono text-[14px] text-ghost">
                  is uvicorn running?
                </p>
              </Card>
            ) : !data ? (
              <Card>
                <div className="flex items-center gap-3 text-ghost">
                  <Spinner /> <span className="font-mono text-[14px]">checking…</span>
                </div>
              </Card>
            ) : (
              <Card brutalist>
                <div className="grid gap-x-12 gap-y-6 md:grid-cols-2">
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
              </Card>
            )}
          </section>

          <section className="py-12 space-y-6 border-t border-mist-08">
            <h2 className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
              deep probe · 1 LLM call
            </h2>
            <p className="text-base text-ghost max-w-2xl">
              Round-trips a trivial Pydantic schema through{" "}
              <span className="font-mono text-white">LLMClient.structured()</span>.
              Burns one cache slot but proves end-to-end connectivity, auth, and
              schema validation. Cached re-runs are free.
            </p>
            <button
              type="button"
              onClick={runDeepProbe}
              disabled={probing || !data}
              className={`rounded-md px-6 py-3 font-mono text-[14px] uppercase tracking-[0.55px] transition-all ${
                probing || !data
                  ? "bg-phantom text-whisper cursor-not-allowed"
                  : "bg-white text-black hover:shadow-[var(--shadow-brutalist)]"
              }`}
            >
              {probing ? "probing…" : "run deep probe"}
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
              <Card className="border-red-500/30">
                <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-red-400">
                  probe error
                </p>
                <p className="mt-3 text-white">{deepError}</p>
              </Card>
            )}
            {deepResult && (
              <Card brutalist>
                <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
                  deep_check
                </p>
                <pre className="mt-3 overflow-x-auto font-mono text-[14px] tracking-[-0.28px] text-white">
                  {JSON.stringify(deepResult, null, 2)}
                </pre>
              </Card>
            )}
          </section>
        </Container>
      </main>
    </>
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
        className={`mt-2 font-mono text-[16px] tracking-[-0.32px] ${
          accent ? "text-cyan" : "text-white"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
