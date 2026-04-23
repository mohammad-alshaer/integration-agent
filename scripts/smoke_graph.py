"""Graph-wiring smoke test — exercises the full M1 pipeline with a FakeLLM.

Why this exists: the real e2e via `worker run` is gated by Gemini free tier's
20-requests-per-day cap on gemini-2.5-flash; that quota is easy to burn in a
single run with retries. This script uses a scripted FakeLLM + the real
embeddings cache (ConstantEmbedder, no network) + the real LangGraph + the
real W4 DuckDB validator + a tiny Parquet sandbox, and exercises:

  - Happy-path specs for all 3 M1 patterns (rename x2, concat, derived)
  - The validator-triggered retry loop: the FIRST derived response emits
    broken SQL (references a nonexistent column). The validator catches
    it, populates ErrorHint(UNKNOWN_COLUMN). The graph routes back to
    transformation_generator. DerivedGenerator sees error_hints in its
    GenerationContext and the prompt grows a "PREVIOUS ATTEMPT FAILED"
    section. FakeLLM, seeing that marker, returns a corrected CASE. The
    final MappingSpec validates at pass_rate=1.0.

Run: ./.venv/Scripts/python.exe scripts/smoke_graph.py
"""

from __future__ import annotations

# Corporate TLS proxy (harmless if nothing hits HTTPS, which nothing here does).
import truststore

truststore.inject_into_ssl()

import shutil  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from agents.graph import build_graph  # noqa: E402
from agents.pattern_classifier import ClassifierOutput  # noqa: E402
from agents.semantic_matcher import MatcherOutput, RerankedCandidate  # noqa: E402
from agents.vector_store import SourceVectorStore  # noqa: E402
from generators.derived import DerivedSpec  # noqa: E402
from schemas import (  # noqa: E402
    ColumnProfile,
    Pattern,
    SchemaProfile,
    SemanticType,
    TableProfile,
)
from validator import Sandbox  # noqa: E402

load_dotenv()


# ------------------------------- Fake LLM ---------------------------------


class FakeLLM:
    """Dispatches by schema type. Mirrors the LLMClient Protocol.

    The retry-aware piece is in `_derived`: the first call for a given target
    returns broken SQL, and the second call (which the graph only makes if
    the validator said the first failed) returns correct SQL.
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
        raise RuntimeError(f"FakeLLM: unsupported schema {schema.__name__}")

    def _matcher(self, user: str) -> MatcherOutput:
        picks = []
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
            # Initial attempt: references a column that isn't in the source.
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


# ------------------------------ Fixtures ----------------------------------


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


def build_source_profile() -> SchemaProfile:
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


def build_target_profile() -> SchemaProfile:
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
            )
        ],
        profiled_at="2026-04-23T00:00:00+00:00",
    )


# ---------------------------- Fake embedder (no network) ------------------


class ConstantEmbedder:
    """Deterministic hash-based embeddings. Quality doesn't matter here —
    FakeLLM picks candidates by prompt substring match, not retrieval rank."""

    provider = "fake"
    model = "fake-emb-1"
    dims = 16

    def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            vec = [(b - 128) / 128.0 for b in h[: self.dims]]
            out.append(vec)
        return out


# ----------------- Sandbox sample fixtures (tiny Parquet) -----------------


def write_sample_parquets(out_dir: Path) -> None:
    """Create just enough rows so the validator's pass/fail math is deterministic."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Person.Person — 3 rows, one with NULL MiddleName (the concat must NULL-safe)
    pd.DataFrame(
        {
            "BusinessEntityID": [1, 2, 3],
            "FirstName": ["Ada", "Grace", "Alan"],
            "MiddleName": ["A.", None, "M."],
            "LastName": ["Lovelace", "Hopper", "Turing"],
            "EmailPromotion": [0, 1, 2],
        }
    ).to_parquet(out_dir / "Person.Person.parquet", index=False)

    # Sales.Customer — 2 rows
    pd.DataFrame(
        {
            "CustomerID": [101, 102],
            "PersonID": [1, 2],
        }
    ).to_parquet(out_dir / "Sales.Customer.parquet", index=False)


# --------------------------------- Main -----------------------------------


def main() -> int:
    source = build_source_profile()
    target = build_target_profile()

    # Stand up a tiny Parquet sample directory for the validator
    sample_dir = Path(tempfile.mkdtemp(prefix="smoke_graph_samples_"))
    try:
        write_sample_parquets(sample_dir)

        embedder = ConstantEmbedder()
        db_path = Path(".duckdb/smoke_graph.duckdb")
        if db_path.exists():
            db_path.unlink()
        store = SourceVectorStore(db_path, embedder)
        store.add_columns(source)

        sandbox = Sandbox(sample_dir)
        llm = FakeLLM()
        graph = build_graph(embedder, llm, store, sandbox=sandbox, max_retries=1)

        target_fqns = [c.fqn for t in target.tables for c in t.columns]
        initial: dict = {
            "source_profile": source,
            "target_profile": target,
            "target_fqns": target_fqns,
        }
        final = graph.invoke(initial)
    finally:
        shutil.rmtree(sample_dir, ignore_errors=True)

    specs = final.get("specs", [])
    reports = final.get("validation_reports", {})
    classifications = final.get("classifications", {})

    print(f"=== FakeLLM calls: {len(llm.calls)} ===")
    pattern_counts: dict[str, int] = {}
    for pc in classifications.values():
        pattern_counts[pc.pattern.value] = pattern_counts.get(pc.pattern.value, 0) + 1
    print(f"Classifications by pattern: {pattern_counts}")

    print(f"\n=== {len(specs)} MappingSpec(s) ===\n")
    for s in specs:
        rep = reports.get(s.target_fqn)
        pass_rate = f"{rep.pass_rate:.2f}" if rep else "?"
        print(f"-- {s.target_fqn}  ({s.pattern.value})  validation_pass_rate={pass_rate}")
        print(f"   sources: {s.source_fqns}")
        print(f"   sql: {s.sql}")
        print(f"   tests: {[t.name for t in s.tests]}")
        print(f"   llm_conf: {s.llm_confidence:.2f}")
        print()

    sandbox.close()
    store.close()

    # Assertions
    if not specs:
        print("FAIL: expected at least one MappingSpec")
        return 1
    patterns = {s.pattern for s in specs}
    missing_patterns = {Pattern.RENAME, Pattern.CONCAT, Pattern.DERIVED} - patterns
    if missing_patterns:
        print(f"FAIL: missing patterns {missing_patterns}")
        return 1
    # Retry expectation: the derived spec should have passed validation on the retry.
    derived = next(s for s in specs if s.pattern == Pattern.DERIVED)
    if derived.validation_pass_rate is None or derived.validation_pass_rate < 1.0:
        print(
            f"FAIL: DERIVED spec did not reach pass_rate=1.0 after retry "
            f"(got {derived.validation_pass_rate})"
        )
        return 1
    derived_calls = [c for c in llm.calls if c[0] == "DerivedSpec"]
    if len(derived_calls) < 2:
        print(f"FAIL: expected >=2 DerivedSpec calls (initial + retry), got {len(derived_calls)}")
        return 1

    print("smoke_graph: all 3 M1 patterns represented, retry-with-error-hints path verified -> OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
