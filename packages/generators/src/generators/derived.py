"""Derived generator — LLM authors a SQL expression over 1+ source columns.

`derived` covers: CASE/WHEN maps (integer-coded enum -> label), arithmetic
(`SubTotal + TaxAmt + Freight`), date parts (`YEAR(OrderDate)`), and other
single-target computed expressions.

Because the space of derived expressions is large, we use the LLM to author
the SQL rather than templating. The LLM is given:
  - Target column (name, type, description, semantic type)
  - Source columns involved (name, type, description, top values)
  - Explicit constraints on what it may emit (pure expression, no joins, no
    aggregates — those belong to `lookup` and `aggregation` patterns)

Output is structured (Pydantic) so we get validation for free, and the
LLMClient prompt-hash cache means re-generations on identical inputs are free.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import BaseModel, Field

from generators.base import GenerationContext, column_alias, default_tests_for_target, quote_col
from schemas import DbtTest, MappingProposal, MappingSpec, Pattern

log = logging.getLogger(__name__)


class DerivedSpec(BaseModel):
    """Structured output from the LLM for a derived mapping."""

    sql_expression: str = Field(
        description=(
            "A single SQL expression (no SELECT / FROM) that computes the target column "
            "from the source columns. Use BARE column names (not qualified) — the dbt "
            "model wraps them in a SELECT at a higher layer. No joins, no aggregates."
        )
    )
    rationale: str
    accepted_values: list[str] | None = Field(
        default=None,
        description=(
            "If the expression is a finite-domain CASE statement, list the distinct "
            "output values so we can emit an `accepted_values` dbt test. Otherwise null."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0)


_SYSTEM_PROMPT = """\
You author a single SQL expression that computes a TARGET column from one or more SOURCE columns.

Output rules:
  - `sql_expression` is ONLY the expression (no SELECT, no FROM, no aliases, no semicolons).
  - Use BARE column names, not schema.table.column — the expression will be placed inside
    a SELECT over a CTE that already references the sources by bare name.
  - No joins. No window functions. No aggregates (GROUP BY / SUM / AVG / ...). Those belong
    to other pattern generators.
  - Prefer ANSI SQL over dialect-specific syntax.
  - Do NOT include explicit CAST unless the source and target types genuinely differ.
    A passthrough rename of a DECIMAL to a DECIMAL needs no cast.
  - If the logic is a finite-domain CASE, populate `accepted_values` with the distinct output
    strings so the eval harness can emit an `accepted_values` dbt test.

DuckDB dialect constraints (the validator runs your SQL against DuckDB; SQL Server types fail):
  - Use DECIMAL(19,4) instead of MONEY or SMALLMONEY.
  - Use VARCHAR or TEXT instead of NVARCHAR / NCHAR / NTEXT.
  - Use TIMESTAMP instead of DATETIME2 / SMALLDATETIME / DATETIMEOFFSET.
  - Use DOUBLE / REAL instead of FLOAT(53) / FLOAT(24).
  - For currency arithmetic, multiply/add at the column level. Do not wrap in CAST(... AS MONEY).
  - For string concatenation use `||` or `concat_ws`, not `+`.

Calibrate `confidence` honestly: 1.0 means "I'm sure this is semantically correct", 0.4 means
"plausible guess given the context".
"""


class DerivedGenerator:
    pattern: ClassVar[Pattern] = Pattern.DERIVED

    def __init__(self, llm) -> None:
        self._llm = llm

    def generate(self, proposal: MappingProposal, ctx: GenerationContext) -> MappingSpec:
        if not ctx.sources:
            raise ValueError(f"DerivedGenerator requires at least 1 source for {ctx.target.fqn}")

        user_prompt = self._build_prompt(ctx)
        llm_failed = False
        try:
            result = self._llm.structured(_SYSTEM_PROMPT, user_prompt, DerivedSpec)
        except Exception as exc:  # noqa: BLE001
            log.warning("DerivedGenerator LLM failed for %s: %s", ctx.target.fqn, exc)
            # Fallback: passthrough from the first source with a cast if needed
            src_col = quote_col(ctx.sources[0].fqn)
            expr = f"CAST({src_col} AS {ctx.target.sql_type})"
            result = DerivedSpec(
                sql_expression=expr,
                rationale=f"Derived LLM failed ({exc}); emitting passthrough cast as fallback.",
                accepted_values=None,
                confidence=0.0,
            )
            llm_failed = True

        alias = column_alias(ctx.target.fqn)
        sql = f"SELECT {result.sql_expression} AS {alias}"

        tests = default_tests_for_target(ctx.target)
        if result.accepted_values:
            tests.append(DbtTest(name="accepted_values", config={"values": result.accepted_values}))

        final_rationale = (
            proposal.rationale
            or result.rationale
            or (f"Derived expression over {[s.fqn for s in ctx.sources]}")
        )

        return MappingSpec(
            target_fqn=ctx.target.fqn,
            source_fqns=[s.fqn for s in ctx.sources],
            pattern=Pattern.DERIVED,
            sql=sql,
            rationale=final_rationale,
            tests=tests,
            llm_confidence=result.confidence,
            provider=getattr(self._llm, "provider", "unknown"),
            model=getattr(self._llm, "model", "unknown"),
            tokens_in=0 if llm_failed else int(getattr(self._llm, "last_tokens_in", 0) or 0),
            tokens_out=0 if llm_failed else int(getattr(self._llm, "last_tokens_out", 0) or 0),
            prompt_cache_hit=False
            if llm_failed
            else bool(getattr(self._llm, "last_cache_hit", False)),
        )

    def test_assertions(self, spec: MappingSpec) -> list[DbtTest]:
        return list(spec.tests)

    # ------- prompt helpers -------

    def _build_prompt(self, ctx: GenerationContext) -> str:
        lines = [
            "TARGET:",
            f"  FQN: {ctx.target.fqn}",
            f"  Type: {ctx.target.sql_type}",
        ]
        if ctx.target.ms_description:
            lines.append(f"  Description: {ctx.target.ms_description}")
        if ctx.target.inferred_semantic_type.value != "unknown":
            lines.append(f"  Semantic type: {ctx.target.inferred_semantic_type.value}")

        lines.append("")
        lines.append("SOURCES (use BARE column names in the expression):")
        for s in ctx.sources:
            piece = f"  - {s.fqn}  type={s.sql_type}"
            if s.ms_description:
                piece += f'  desc="{s.ms_description[:80]}"'
            if s.top_values:
                samples = ", ".join(repr(v) for v, _ in s.top_values[:5])
                piece += f"  top_values=[{samples}]"
            lines.append(piece)

        # On retry, include the validator's structured feedback so the LLM can correct.
        if ctx.error_hints:
            lines.append("")
            lines.append("PREVIOUS ATTEMPT FAILED VALIDATION. Correct the specific issues below:")
            for h in ctx.error_hints:
                lines.append(f"  - kind={h.kind.value}: {h.duckdb_error_message}")
                if h.suggestion:
                    lines.append(f"    suggestion: {h.suggestion}")
                if h.offending_sql_snippet:
                    lines.append(f"    offending sql was: {h.offending_sql_snippet}")
            lines.append("")
            lines.append(
                "Emit a NEW sql_expression that addresses every failure above. "
                "Do not repeat the failed expression."
            )

        lines.append("")
        lines.append("Return JSON matching the DerivedSpec schema.")
        return "\n".join(lines)
