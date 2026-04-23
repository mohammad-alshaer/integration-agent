"""Base protocol + helpers shared across pattern generators."""

from __future__ import annotations

from typing import ClassVar, Protocol

from pydantic import BaseModel

from schemas import ColumnProfile, DbtTest, ErrorHint, MappingProposal, MappingSpec, Pattern


class GenerationContext(BaseModel):
    """Resolved context for a generator — target and source ColumnProfiles by FQN."""

    model_config = {"arbitrary_types_allowed": True}

    target: ColumnProfile
    sources: list[ColumnProfile]  # ordered to match proposal.source_fqns
    # When non-empty, a previous attempt's validator feedback. Generators that emit
    # LLM-authored SQL (derived, future split/conditional/lookup) include these hints
    # in their retry prompt so the model can correct the specific failure. Deterministic
    # generators (rename, concat) ignore error_hints.
    error_hints: list[ErrorHint] = []


class PatternGenerator(Protocol):
    """Every generator implements this: classify-by-pattern + emit SQL + emit tests."""

    pattern: ClassVar[Pattern]

    def generate(self, proposal: MappingProposal, ctx: GenerationContext) -> MappingSpec: ...
    def test_assertions(self, spec: MappingSpec) -> list[DbtTest]: ...


# ---------- small SQL helpers reused by the concrete generators ----------


def column_alias(target_fqn: str) -> str:
    """Last segment of schema.table.column → column alias for the SELECT list."""
    return target_fqn.split(".")[-1]


def quote_col(source_fqn: str) -> str:
    """Quote just the column name from a FQN. Source tables are referenced via CTEs /
    the dbt `{{ source() }}` macro at the model layer, so we emit bare-column
    references here."""
    return source_fqn.split(".")[-1]


def base_type(sql_type: str) -> str:
    """Strip size suffix: `nvarchar(50)` -> `nvarchar`, `decimal(18,4)` -> `decimal`."""
    return sql_type.split("(")[0].strip().lower()


def types_compatible(a: str, b: str) -> bool:
    """Loose equivalence — same base type family. Enough to decide whether to CAST."""
    return base_type(a) == base_type(b)


def default_tests_for_target(target: ColumnProfile) -> list[DbtTest]:
    """Default dbt assertions derivable from the target column metadata alone."""
    tests: list[DbtTest] = []
    if not target.is_nullable:
        tests.append(DbtTest(name="not_null"))
    if target.is_primary_key:
        tests.append(DbtTest(name="unique"))
    return tests
