import Link from "next/link";
import { Brand } from "@/components/Brand";
import { Container } from "@/components/Container";
import { PageHeader } from "@/components/PageHeader";
import { API_BASE_URL } from "@/lib/api";

export default function HomePage() {
  return (
    <>
      <Brand />
      <main className="flex-1 relative">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-[420px] opacity-50"
          style={{
            background:
              "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(0,7,205,0.18), rgba(15,15,15,0) 60%)",
          }}
        />
        <Container>
          <PageHeader
            overline="multi-agent dataops"
            title={
              <>
                Schema mapping
                <br />
                for the warehouse pipeline.
              </>
            }
            subtitle={
              <>
                AdventureWorks 2022 OLTP → AdventureWorksDW 2022.{" "}
                <span className="text-whisper">
                  Gemini 2.5 Flash · DuckDB+vss · LangGraph · dbt-duckdb.
                </span>
              </>
            }
          />

          <div className="grid gap-6 md:grid-cols-2 py-12">
            <Link
              href="/eval"
              className="group block rounded-md border border-mist-10 bg-black p-8 hover:border-cyan/40 hover:shadow-[var(--shadow-brutalist)] transition-all"
            >
              <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
                01 / read-only
              </p>
              <h2 className="mt-4 text-2xl font-medium leading-tight text-white group-hover:text-cyan transition-colors">
                Evaluations
              </h2>
              <p className="mt-3 text-base text-ghost leading-relaxed">
                Browse benchmark results across runs. Per-run rates matrix
                (inclusive / exclusive × exact / pattern / sql_exec / sql_semantic)
                and per-spec score breakdown.
              </p>
            </Link>

            <Link
              href="/map"
              className="group block rounded-md border border-mist-10 bg-black p-8 hover:border-cyan/40 hover:shadow-[var(--shadow-brutalist)] transition-all"
            >
              <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
                02 / live · runs the graph
              </p>
              <h2 className="mt-4 text-2xl font-medium leading-tight text-white group-hover:text-cyan transition-colors">
                Map a target table
              </h2>
              <p className="mt-3 text-base text-ghost leading-relaxed">
                Submit source + target SchemaProfile JSON, pick a target table,
                run the LangGraph pipeline. Returns MappingSpecs with SQL,
                pattern classifications, and validation pass-rates.
              </p>
            </Link>
          </div>

          <div className="border-t border-mist-06 py-8 font-mono text-[11px] tracking-[0.55px] text-whisper">
            api · {API_BASE_URL}
          </div>
        </Container>
      </main>
    </>
  );
}
