"""Rename generator — 1:1 source -> target, with optional CAST.

Emits a column expression of the form:
    <src_col> AS <tgt_col>                                          (types match)
    CAST(<src_col> AS <target_type>) AS <tgt_col>                    (types differ)
"""

from __future__ import annotations

from typing import ClassVar

from generators.base import (
    GenerationContext,
    column_alias,
    default_tests_for_target,
    quote_col,
    to_duckdb_type,
    types_compatible,
)
from schemas import DbtTest, MappingProposal, MappingSpec, Pattern


class RenameGenerator:
    pattern: ClassVar[Pattern] = Pattern.RENAME

    def generate(self, proposal: MappingProposal, ctx: GenerationContext) -> MappingSpec:
        if len(ctx.sources) != 1:
            raise ValueError(f"RenameGenerator expects exactly 1 source, got {len(ctx.sources)}")
        src = ctx.sources[0]
        tgt = ctx.target

        src_col = quote_col(src.fqn)
        alias = column_alias(tgt.fqn)

        if types_compatible(src.sql_type, tgt.sql_type):
            sql = f"SELECT {src_col} AS {alias}"
        else:
            duckdb_type = to_duckdb_type(tgt.sql_type)
            sql = f"SELECT CAST({src_col} AS {duckdb_type}) AS {alias}"

        rationale = proposal.rationale or (
            f"1:1 rename from {src.fqn} to {tgt.fqn}"
            + (
                ""
                if types_compatible(src.sql_type, tgt.sql_type)
                else f" with CAST to {to_duckdb_type(tgt.sql_type)}"
            )
        )

        spec = MappingSpec(
            target_fqn=tgt.fqn,
            source_fqns=[src.fqn],
            pattern=Pattern.RENAME,
            sql=sql,
            rationale=rationale,
            tests=self.test_assertions_preview(tgt),
            llm_confidence=0.0,  # filled in by classifier/matcher upstream
        )
        spec.tests = self.test_assertions(spec)
        return spec

    def test_assertions_preview(self, tgt: ColumnProfile) -> list[DbtTest]:  # noqa: F821
        return default_tests_for_target(tgt)

    def test_assertions(self, spec: MappingSpec) -> list[DbtTest]:
        # Same as preview — no extra pattern-specific tests for rename beyond column-level defaults.
        # (Pattern-specific tests like `accepted_values` are added by derived/concat if applicable.)
        return list(spec.tests)
