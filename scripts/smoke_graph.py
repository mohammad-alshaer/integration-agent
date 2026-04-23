"""Graph-wiring smoke test — exercises the full Week 3 pipeline with a FakeLLM.

Why this exists: the real e2e via `worker run` is gated by Gemini free tier's
20-requests-per-day cap on gemini-2.5-flash; that quota is easy to burn in a
single run with retries. This script uses a scripted FakeLLM + the real
embeddings cache + the real LangGraph to prove the pipeline's internal
plumbing works end-to-end. It emits at least one `MappingSpec` per pattern.

Run: ./.venv/Scripts/python.exe scripts/smoke_graph.py
"""

from __future__ import annotations

# Corporate TLS proxy (needed by VoyageEmbedder / GeminiEmbedder if they were used).
import truststore

truststore.inject_into_ssl()

from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

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

load_dotenv()


# ------------------------------- Fake LLM ---------------------------------


class FakeLLM:
    """Dispatches by schema type. Mirrors the LLMClient Protocol."""

    provider = "fake"
    model = "fake-1"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []  # (schema_name, target_fqn-ish)

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
        # Pick 1-3 relevant candidates per target based on keyword hints in the prompt
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
        if "EmailPromotionCategory" in user:
            return DerivedSpec(
                sql_expression=(
                    "CASE WHEN EmailPromotion = 0 THEN 'None' "
                    "WHEN EmailPromotion = 1 THEN 'AdventureWorks Only' "
                    "WHEN EmailPromotion = 2 THEN 'AdventureWorks and Partners' END"
                ),
                rationale="CASE-based enum decode",
                accepted_values=["None", "AdventureWorks Only", "AdventureWorks and Partners"],
                confidence=0.9,
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
    """Produces deterministic, orthogonal-ish embeddings from column text hash.

    We don't care about quality here — the FakeLLM picks candidates by prompt
    substring matching, not by retrieval rank. We just need something the
    vector store can index and query.
    """

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


# --------------------------------- Main -----------------------------------


def main() -> int:
    source = build_source_profile()
    target = build_target_profile()

    embedder = ConstantEmbedder()
    db_path = Path(".duckdb/smoke_graph.duckdb")
    if db_path.exists():
        db_path.unlink()
    store = SourceVectorStore(db_path, embedder)
    store.add_columns(source)

    llm = FakeLLM()
    graph = build_graph(embedder, llm, store)

    target_fqns = [c.fqn for t in target.tables for c in t.columns]
    initial: dict = {
        "source_profile": source,
        "target_profile": target,
        "target_fqns": target_fqns,
    }
    final = graph.invoke(initial)

    specs = final.get("specs", [])
    classifications = final.get("classifications", {})

    print(f"=== FakeLLM calls: {len(llm.calls)} ===")
    pattern_counts: dict[str, int] = {}
    for pc in classifications.values():
        pattern_counts[pc.pattern.value] = pattern_counts.get(pc.pattern.value, 0) + 1
    print(f"Classifications by pattern: {pattern_counts}")
    print(f"\n=== {len(specs)} MappingSpec(s) ===\n")
    for s in specs:
        print(f"-- {s.target_fqn}  ({s.pattern.value})")
        print(f"   sources: {s.source_fqns}")
        print(f"   sql: {s.sql}")
        print(f"   tests: {[t.name for t in s.tests]}")
        print(f"   llm_conf: {s.llm_confidence:.2f}")
        print()

    store.close()

    if not specs:
        print("FAIL: expected at least one MappingSpec")
        return 1
    patterns = {s.pattern for s in specs}
    expected = {Pattern.RENAME, Pattern.CONCAT, Pattern.DERIVED}
    missing = expected - patterns
    if missing:
        print(f"FAIL: missing patterns {missing}")
        return 1
    print("smoke_graph: all 3 M1 patterns represented -> OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
