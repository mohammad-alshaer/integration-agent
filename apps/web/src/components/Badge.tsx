import { MatchLevel, Pattern } from "@/lib/api";

const PATTERN_TONE: Record<Pattern, string> = {
  rename: "border-mist-10 text-ghost",
  concat: "border-signal/30 text-signal",
  split: "border-mist-10 text-ghost",
  derived: "border-cobalt/40 text-white bg-cobalt/10",
  constant: "border-mist-10 text-ghost",
  lookup: "border-mist-10 text-ghost",
  unsupported_in_m1: "border-mist-08 text-phantom",
};

const LEVEL_TONE: Record<MatchLevel, string> = {
  exact: "border-cyan/40 text-cyan bg-[var(--color-cyan-glow)]",
  pattern: "border-cobalt/40 text-white bg-cobalt/10",
  sql_exec_equivalent: "border-signal/40 text-signal",
  sql_semantic: "border-mist-12 text-ghost",
  mismatch: "border-mist-10 text-whisper",
  missing: "border-mist-08 text-phantom",
  extra: "border-mist-08 text-phantom",
};

const baseClass =
  "inline-flex items-center rounded-sharp border px-2 py-[2px] font-mono text-[11px] uppercase tracking-[0.55px]";

export function PatternBadge({ pattern }: { pattern: Pattern | null }) {
  if (!pattern) return <span className="text-phantom font-mono text-[11px]">—</span>;
  return <span className={`${baseClass} ${PATTERN_TONE[pattern]}`}>{pattern}</span>;
}

export function MatchLevelBadge({ level }: { level: MatchLevel }) {
  return (
    <span className={`${baseClass} ${LEVEL_TONE[level]}`}>
      {level.replace(/_/g, " ")}
    </span>
  );
}

export function DisputedTag() {
  return (
    <span className="inline-flex items-center rounded-sharp border border-mist-08 px-2 py-[2px] font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
      disputed
    </span>
  );
}
