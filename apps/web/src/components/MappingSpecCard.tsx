import { PatternBadge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { MappingSpec } from "@/lib/api";
import { formatPercent } from "@/lib/format";

export function MappingSpecCard({ spec }: { spec: MappingSpec }) {
  return (
    <Card brutalist className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex items-center gap-3">
          <PatternBadge pattern={spec.pattern} />
          <code className="font-mono text-[15px] tracking-[-0.3px] text-white">
            {spec.target_fqn}
          </code>
        </div>
        <div className="font-mono text-[12px] text-whisper">
          llm_conf{" "}
          <span className="text-ghost">
            {spec.llm_confidence.toFixed(2)}
          </span>
          {spec.validation_pass_rate != null && (
            <>
              {"  ·  "}
              pass_rate{" "}
              <span className="text-ghost">
                {formatPercent(spec.validation_pass_rate, 0)}
              </span>
            </>
          )}
        </div>
      </div>

      {spec.source_fqns.length > 0 && (
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
            sources
          </p>
          <ul className="mt-1 space-y-1">
            {spec.source_fqns.map((src) => (
              <li
                key={src}
                className="font-mono text-[14px] tracking-[-0.28px] text-ghost"
              >
                {src}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <p className="font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
          sql
        </p>
        <pre className="mt-2 overflow-x-auto rounded-sharp border border-mist-08 bg-black p-4 font-mono text-[14px] leading-relaxed tracking-[-0.28px] text-white">
          {spec.sql}
        </pre>
      </div>

      {spec.rationale && (
        <p className="text-base text-ghost leading-relaxed">{spec.rationale}</p>
      )}

      {spec.tests.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {spec.tests.map((t, i) => (
            <span
              key={`${t.name}-${i}`}
              className="inline-flex items-center rounded-sharp border border-mist-10 px-2 py-[2px] font-mono text-[11px] uppercase tracking-[0.55px] text-ghost"
            >
              test · {t.name}
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}
