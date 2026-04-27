import Link from "next/link";
import { Container } from "@/components/Container";
import { API_BASE_URL } from "@/lib/api";

const STATS = [
  { value: "78.9%", label: "exact match", sub: "inclusive · m2-complete" },
  { value: "96.7%", label: "exclusive exact", sub: "non-disputed specs" },
  { value: "137", label: "tests passing", sub: "python + api" },
  { value: "9/10", label: "dbt models", sub: "building clean" },
];

const STACK = [
  "Gemini 2.5 Flash",
  "DuckDB + vss",
  "LangGraph",
  "dbt-duckdb",
  "FastAPI",
  "Next.js 16",
];

export default function HomePage() {
  return (
    <main className="flex-1 relative">
      <Container>
          {/* ───────── Hero ───────── */}
          <section className="pt-20 pb-16 md:pt-24 md:pb-20 grid gap-12 lg:grid-cols-[1.25fr_0.95fr] lg:gap-14 items-start">
            <div>
              <div className="inline-flex items-center gap-2 rounded-pill border border-mist-12 bg-black/40 px-4 py-1.5 backdrop-blur">
                <span className="relative inline-flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan opacity-60" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan" />
                </span>
                <span className="font-mono text-[11px] uppercase tracking-[0.55px] text-ghost">
                  m4 complete · live demo
                </span>
              </div>

              <h1 className="mt-8 text-5xl md:text-6xl lg:text-[68px] font-normal leading-[0.95] tracking-[-0.035em]">
                <span className="text-white">Schema mapping</span>
                <br />
                <span className="text-gradient-cyan">for the warehouse pipeline.</span>
              </h1>

              <p className="mt-8 text-lg text-ghost leading-relaxed max-w-xl">
                Multi-agent LangGraph that maps OLTP source schemas to
                dimensional warehouses. Semantic matching, pattern
                classification, DuckDB-sandbox validation, dbt-duckdb model
                emission — end-to-end.
              </p>

              <div className="mt-10 flex flex-wrap items-center gap-4">
                <Link
                  href="/map"
                  className="cta-primary inline-flex items-center gap-2 rounded-md bg-white px-6 py-3 text-black font-medium"
                >
                  Run a mapping
                  <span aria-hidden>→</span>
                </Link>
                <Link
                  href="/eval"
                  className="inline-flex items-center gap-2 rounded-md border border-mist-12 bg-black/40 px-6 py-3 text-white backdrop-blur transition-all hover:border-cyan/40 hover:text-cyan"
                >
                  Browse evaluations
                </Link>
              </div>
            </div>

            <HeroPreviewCard />
          </section>

          {/* ───────── Stats ───────── */}
          <section className="border-t border-mist-08 py-14 md:py-16">
            <div className="flex items-baseline justify-between mb-10">
              <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
                benchmark · adventureworks · gemini 2.5 flash
              </p>
              <Link
                href="/eval"
                className="hidden md:inline font-mono text-[11px] uppercase tracking-[0.55px] text-whisper hover:text-cyan transition-colors"
              >
                view all runs →
              </Link>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-x-8 gap-y-12">
              {STATS.map((s, i) => (
                <div key={s.label} className="relative">
                  <div className="font-mono text-[10px] uppercase tracking-[0.55px] text-whisper">
                    {String(i + 1).padStart(2, "0")}
                  </div>
                  <div className="mt-3 font-mono text-4xl md:text-5xl tracking-[-0.04em] text-white">
                    {s.value}
                  </div>
                  <div className="mt-3 font-mono text-[12px] uppercase tracking-[0.6px] text-cyan">
                    {s.label}
                  </div>
                  <div className="mt-1.5 text-[13px] text-whisper">{s.sub}</div>
                </div>
              ))}
            </div>
          </section>

          {/* ───────── Stack ───────── */}
          <section className="py-14">
            <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper mb-6">
              stack
            </p>
            <div className="flex flex-wrap gap-2.5">
              {STACK.map((tech) => (
                <span
                  key={tech}
                  className="inline-flex items-center rounded-pill border border-mist-10 bg-black/40 px-4 py-2 font-mono text-[13px] tracking-[-0.26px] text-ghost backdrop-blur"
                >
                  {tech}
                </span>
              ))}
            </div>
          </section>

          {/* ───────── Feature cards ───────── */}
          <section className="grid gap-6 md:grid-cols-2 py-14 md:py-16">
            <FeatureCard
              number="01"
              tag="read-only"
              title="Evaluations"
              description="Per-run rates matrix (inclusive / exclusive × exact / pattern / sql_exec / sql_semantic) and per-spec score breakdown across all benchmarks."
              href="/eval"
            />
            <FeatureCard
              number="02"
              tag="live · runs the graph"
              title="Map a target table"
              description="Submit source + target SchemaProfile JSON, pick a target table, run the LangGraph pipeline. Returns MappingSpecs with SQL, pattern classification, and validation pass-rates."
              href="/map"
              highlighted
            />
          </section>

          {/* ───────── Footer ───────── */}
          <footer className="border-t border-mist-06 py-8 mt-12 flex flex-wrap items-center justify-between gap-4 font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
            <div>integration-agent · m4-complete · 998b52f</div>
            <div className="flex items-center gap-6">
              <span>api · {API_BASE_URL}</span>
              <Link
                href="https://github.com/mohammad-alshaer/integration-agent"
                className="hover:text-cyan transition-colors"
              >
                github →
              </Link>
            </div>
          </footer>
      </Container>
    </main>
  );
}

function HeroPreviewCard() {
  return (
    <div className="relative">
      {/* Soft glow behind the card */}
      <div
        aria-hidden
        className="absolute -inset-8 -z-10 rounded-[40px] bg-cyan/10 blur-3xl opacity-60"
      />
      <div className="glass glass-rim rounded-md p-6 md:p-7 transform-gpu lg:rotate-[-1.5deg] lg:hover:rotate-0 lg:hover:translate-y-[-2px] transition-all duration-500 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.6)]">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
            example · MappingSpec
          </span>
          <span className="inline-flex items-center rounded-sharp border border-cyan/40 bg-[var(--color-cyan-glow)] px-2 py-[2px] font-mono text-[11px] uppercase tracking-[0.55px] text-cyan">
            concat
          </span>
        </div>
        <div className="mt-5">
          <p className="font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
            target
          </p>
          <p className="mt-1 font-mono text-[15px] tracking-[-0.3px] text-white">
            dbo.DimCustomer.FullName
          </p>
        </div>
        <div className="mt-4">
          <p className="font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
            sources
          </p>
          <ul className="mt-1 space-y-0.5 font-mono text-[13px] text-ghost">
            <li>Person.Person.FirstName</li>
            <li>Person.Person.MiddleName</li>
            <li>Person.Person.LastName</li>
          </ul>
        </div>
        <div className="mt-4">
          <p className="font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
            sql
          </p>
          <pre className="mt-1 overflow-x-auto rounded-sharp border border-mist-08 bg-black/60 p-3 font-mono text-[13px] leading-relaxed text-white">
{`CONCAT_WS(
  ' ',
  FirstName,
  MiddleName,
  LastName
) AS FullName`}
          </pre>
        </div>
        <div className="mt-5 flex items-center justify-between font-mono text-[12px] text-whisper">
          <span>
            llm_conf <span className="text-ghost">0.92</span>
          </span>
          <span>
            pass_rate <span className="text-cyan">100%</span>
          </span>
        </div>
      </div>
    </div>
  );
}

function FeatureCard({
  number,
  tag,
  title,
  description,
  href,
  highlighted = false,
}: {
  number: string;
  tag: string;
  title: string;
  description: string;
  href: string;
  highlighted?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`group glass glass-hover relative block overflow-hidden rounded-md p-8 md:p-10 ${
        highlighted ? "glass-rim" : ""
      }`}
    >
      <div
        aria-hidden
        className={`absolute -top-24 -right-24 h-56 w-56 rounded-full blur-3xl transition-opacity duration-500 ${
          highlighted ? "bg-cyan/15 opacity-50" : "bg-cobalt/20 opacity-0 group-hover:opacity-60"
        }`}
      />
      <div className="relative">
        <div className="flex items-baseline justify-between">
          <span className="font-mono text-5xl md:text-6xl tracking-[-0.04em] text-mist-12 group-hover:text-cyan/40 transition-colors">
            {number}
          </span>
          <span className="font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
            {tag}
          </span>
        </div>
        <h2 className="mt-6 text-3xl font-medium leading-tight text-white group-hover:text-cyan transition-colors">
          {title}
        </h2>
        <p className="mt-3 text-[15px] text-ghost leading-relaxed">
          {description}
        </p>
        <div className="mt-7 inline-flex items-center gap-2 font-mono text-[13px] tracking-[-0.26px] text-cyan/80 group-hover:text-cyan">
          open
          <span
            aria-hidden
            className="transition-transform duration-300 group-hover:translate-x-1"
          >
            →
          </span>
        </div>
      </div>
    </Link>
  );
}
