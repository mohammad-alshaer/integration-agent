"""Deterministic fakes for offline/fast testing.

Mirrors scripts/smoke_graph.py's FakeLLM + ConstantEmbedder, kept in the evals
package so tests can import them without hacking sys.path to reach scripts/.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agents.pattern_classifier import ClassifierOutput
from agents.semantic_matcher import MatcherOutput, RerankedCandidate
from generators.derived import DerivedSpec
from schemas import ColumnProfile, Pattern, SchemaProfile, SemanticType, TableProfile


class ConstantEmbedder:
    """Deterministic hash-based embeddings — no network. 16-dim vectors."""

    provider = "fake"
    model = "fake-emb-1"
    dims = 16

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            vec = [(b - 128) / 128.0 for b in h[: self.dims]]
            out.append(vec)
        return out


class SmokeFakeLLM:
    """Scripted responses matching the 4 DimCustomer target columns in the smoke fixture.

    Dispatches by schema type (MatcherOutput | ClassifierOutput | DerivedSpec).
    For DERIVED, the first call returns broken SQL; if the prompt includes
    'PREVIOUS ATTEMPT FAILED' (emitted by DerivedGenerator on retry), returns
    corrected SQL — this exercises the validator-triggered retry path.
    """

    provider = "fake"
    model = "fake-1"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def structured(self, system: str, user: str, schema: type) -> Any:
        self.calls.append((schema.__name__, user[:60]))
        if schema is MatcherOutput:
            return self._matcher(user)
        if schema is ClassifierOutput:
            return self._classifier(user)
        if schema is DerivedSpec:
            return self._derived(user)
        raise RuntimeError(f"SmokeFakeLLM: unsupported schema {schema.__name__}")

    def _matcher(self, user: str) -> MatcherOutput:
        picks: list[RerankedCandidate] = []
        if "FirstName" in user:
            picks.append(_rc("Person.Person.FirstName", "direct name match", 0.95))
        if "LastName" in user:
            picks.append(_rc("Person.Person.LastName", "direct name match", 0.95))
        if "MiddleName" in user:
            picks.append(_rc("Person.Person.MiddleName", "direct name match", 0.95))
        if "CustomerKey" in user:
            picks.append(_rc("Sales.Customer.CustomerID", "business key", 0.9))
        if "FullName" in user:
            picks.extend(
                [
                    _rc("Person.Person.FirstName", "part 1", 0.85),
                    _rc("Person.Person.MiddleName", "part 2", 0.85),
                    _rc("Person.Person.LastName", "part 3", 0.85),
                ]
            )
        if "EmailPromotionCategory" in user:
            picks.append(_rc("Person.Person.EmailPromotion", "integer encoding", 0.9))
        return MatcherOutput(candidates=picks, no_match=not picks)

    def _classifier(self, user: str) -> ClassifierOutput:
        if "DimCustomer.CustomerKey" in user:
            return ClassifierOutput(
                pattern=Pattern.RENAME,
                source_fqns=["Sales.Customer.CustomerID"],
                rationale="Business-key rename",
                llm_confidence=0.95,
            )
        if "DimCustomer.FirstName" in user:
            return ClassifierOutput(
                pattern=Pattern.RENAME,
                source_fqns=["Person.Person.FirstName"],
                rationale="Direct rename",
                llm_confidence=0.98,
            )
        if "DimCustomer.FullName" in user:
            return ClassifierOutput(
                pattern=Pattern.CONCAT,
                source_fqns=[
                    "Person.Person.FirstName",
                    "Person.Person.MiddleName",
                    "Person.Person.LastName",
                ],
                rationale="N:1 concat of name parts with NULL-safe join",
                llm_confidence=0.92,
            )
        if "DimCustomer.EmailPromotionCategory" in user:
            return ClassifierOutput(
                pattern=Pattern.DERIVED,
                source_fqns=["Person.Person.EmailPromotion"],
                rationale="CASE WHEN encoding of integer enum",
                llm_confidence=0.88,
            )
        return ClassifierOutput(
            pattern=Pattern.UNSUPPORTED_IN_M1,
            source_fqns=[],
            rationale="no mapping in fake scenario",
            llm_confidence=0.1,
        )

    def _derived(self, user: str) -> DerivedSpec:
        is_retry = "PREVIOUS ATTEMPT FAILED" in user
        if "EmailPromotionCategory" in user:
            if is_retry:
                return DerivedSpec(
                    sql_expression=(
                        "CASE WHEN EmailPromotion = 0 THEN 'None' "
                        "WHEN EmailPromotion = 1 THEN 'AdventureWorks Only' "
                        "WHEN EmailPromotion = 2 THEN 'AdventureWorks and Partners' END"
                    ),
                    rationale="Corrected after validator caught UNKNOWN_COLUMN on first try",
                    accepted_values=[
                        "None",
                        "AdventureWorks Only",
                        "AdventureWorks and Partners",
                    ],
                    confidence=0.95,
                )
            return DerivedSpec(
                sql_expression="CASE WHEN nonexistent_col = 0 THEN 'None' ELSE 'Other' END",
                rationale="first guess; will fail validation",
                accepted_values=None,
                confidence=0.35,
            )
        return DerivedSpec(
            sql_expression="CAST(src AS VARCHAR)",
            rationale="passthrough",
            accepted_values=None,
            confidence=0.4,
        )


def _rc(fqn: str, rationale: str, sim: float) -> RerankedCandidate:
    return RerankedCandidate(source_fqn=fqn, rationale=rationale, similarity=sim)


def _col(
    schema: str,
    table: str,
    name: str,
    pos: int,
    sql_type: str,
    *,
    desc: str | None = None,
    is_nullable: bool = True,
    is_pk: bool = False,
    sem: SemanticType = SemanticType.UNKNOWN,
) -> ColumnProfile:
    return ColumnProfile(
        table_schema=schema,
        table_name=table,
        column_name=name,
        ordinal_position=pos,
        sql_type=sql_type,
        is_nullable=is_nullable,
        is_primary_key=is_pk,
        is_foreign_key=False,
        ms_description=desc,
        null_rate=0.0,
        distinct_count=100,
        total_count=1000,
        inferred_semantic_type=sem,
    )


def build_smoke_source_profile() -> SchemaProfile:
    return SchemaProfile(
        database_name="AdventureWorks2022",
        role="source",
        tables=[
            TableProfile(
                table_schema="Person",
                table_name="Person",
                row_count_estimate=19972,
                columns=[
                    _col(
                        "Person",
                        "Person",
                        "BusinessEntityID",
                        1,
                        "int",
                        is_nullable=False,
                        is_pk=True,
                        sem=SemanticType.IDENTIFIER,
                    ),
                    _col(
                        "Person",
                        "Person",
                        "FirstName",
                        5,
                        "nvarchar(50)",
                        desc="First name",
                        sem=SemanticType.PERSON_NAME,
                    ),
                    _col(
                        "Person",
                        "Person",
                        "MiddleName",
                        6,
                        "nvarchar(50)",
                        desc="Middle name",
                        sem=SemanticType.PERSON_NAME,
                    ),
                    _col(
                        "Person",
                        "Person",
                        "LastName",
                        7,
                        "nvarchar(50)",
                        desc="Last name",
                        sem=SemanticType.PERSON_NAME,
                    ),
                    _col(
                        "Person",
                        "Person",
                        "EmailPromotion",
                        10,
                        "int",
                        desc="0=None, 1=AW only, 2=AW + Partners",
                        sem=SemanticType.ENUM_CATEGORY,
                    ),
                ],
            ),
            TableProfile(
                table_schema="Sales",
                table_name="Customer",
                row_count_estimate=19820,
                columns=[
                    _col(
                        "Sales",
                        "Customer",
                        "CustomerID",
                        1,
                        "int",
                        is_nullable=False,
                        is_pk=True,
                        sem=SemanticType.IDENTIFIER,
                    ),
                    _col("Sales", "Customer", "PersonID", 2, "int"),
                ],
            ),
        ],
        profiled_at="2026-04-23T00:00:00+00:00",
    )


def build_smoke_target_profile() -> SchemaProfile:
    return SchemaProfile(
        database_name="AdventureWorksDW2022",
        role="target",
        tables=[
            TableProfile(
                table_schema="dbo",
                table_name="DimCustomer",
                row_count_estimate=18484,
                columns=[
                    _col(
                        "dbo",
                        "DimCustomer",
                        "CustomerKey",
                        1,
                        "int",
                        is_nullable=False,
                        is_pk=True,
                        sem=SemanticType.IDENTIFIER,
                    ),
                    _col(
                        "dbo",
                        "DimCustomer",
                        "FirstName",
                        4,
                        "nvarchar(50)",
                        desc="First name of customer",
                        sem=SemanticType.PERSON_NAME,
                    ),
                    _col(
                        "dbo",
                        "DimCustomer",
                        "FullName",
                        7,
                        "nvarchar(100)",
                        desc="Concatenated full name",
                        sem=SemanticType.PERSON_NAME,
                    ),
                    _col(
                        "dbo",
                        "DimCustomer",
                        "EmailPromotionCategory",
                        15,
                        "nvarchar(40)",
                        desc="Human-readable enum of EmailPromotion code",
                        sem=SemanticType.ENUM_CATEGORY,
                    ),
                ],
            ),
        ],
        profiled_at="2026-04-23T00:00:00+00:00",
    )


def write_smoke_sample_parquets(out_dir: Path) -> None:
    """Tiny Parquet samples for the validator sandbox."""
    import pandas as pd

    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "BusinessEntityID": [1, 2, 3],
            "FirstName": ["Ada", "Grace", "Alan"],
            "MiddleName": ["A.", None, "M."],
            "LastName": ["Lovelace", "Hopper", "Turing"],
            "EmailPromotion": [0, 1, 2],
        }
    ).to_parquet(out_dir / "Person.Person.parquet", index=False)
    pd.DataFrame(
        {
            "CustomerID": [101, 102],
            "PersonID": [1, 2],
        }
    ).to_parquet(out_dir / "Sales.Customer.parquet", index=False)


def build_smoke_fake_llm() -> SmokeFakeLLM:
    return SmokeFakeLLM()


__all__ = [
    "ConstantEmbedder",
    "SmokeFakeLLM",
    "build_smoke_fake_llm",
    "build_smoke_source_profile",
    "build_smoke_target_profile",
    "write_smoke_sample_parquets",
]
