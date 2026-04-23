"""Concat generator — N sources -> 1 target via concat_ws(' ', ...) for NULL-safety.

Uses DuckDB / dbt `concat_ws`, which skips NULL arguments rather than propagating.
Example:
    concat_ws(' ', FirstName, MiddleName, LastName) AS FullName

For numeric types we cast to VARCHAR first so concat_ws is well-defined.
"""

from __future__ import annotations

from typing import ClassVar

from generators.base import (
    GenerationContext,
    base_type,
    column_alias,
    default_tests_for_target,
    quote_col,
)
from schemas import ColumnProfile, DbtTest, MappingProposal, MappingSpec, Pattern

_STRING_TYPES = {"char", "varchar", "nchar", "nvarchar", "text", "ntext"}


def _cast_to_varchar_if_needed(col: ColumnProfile) -> str:
    """Return `col` or `CAST(col AS VARCHAR)` depending on source type."""
    q = quote_col(col.fqn)
    if base_type(col.sql_type) in _STRING_TYPES:
        return q
    return f"CAST({q} AS VARCHAR)"


class ConcatGenerator:
    pattern: ClassVar[Pattern] = Pattern.CONCAT

    def generate(self, proposal: MappingProposal, ctx: GenerationContext) -> MappingSpec:
        if len(ctx.sources) < 2:
            raise ValueError(
                f"ConcatGenerator expects >=2 sources, got {len(ctx.sources)} "
                f"for target {ctx.target.fqn}"
            )

        pieces = [_cast_to_varchar_if_needed(s) for s in ctx.sources]
        alias = column_alias(ctx.target.fqn)
        sql = f"SELECT concat_ws(' ', {', '.join(pieces)}) AS {alias}"

        rationale = proposal.rationale or (
            f"N:1 concat of {[s.fqn for s in ctx.sources]} into {ctx.target.fqn} "
            "using concat_ws for NULL-safe joining"
        )

        spec = MappingSpec(
            target_fqn=ctx.target.fqn,
            source_fqns=[s.fqn for s in ctx.sources],
            pattern=Pattern.CONCAT,
            sql=sql,
            rationale=rationale,
            tests=default_tests_for_target(ctx.target),
            llm_confidence=0.0,
        )
        spec.tests = self.test_assertions(spec)
        return spec

    def test_assertions(self, spec: MappingSpec) -> list[DbtTest]:
        return list(spec.tests)
