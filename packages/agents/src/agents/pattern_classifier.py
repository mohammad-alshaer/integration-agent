"""Pattern Classifier — decide which transformation Pattern applies per target column.

Takes a target ColumnProfile + the CandidateSet from the Semantic Matcher, and
emits exactly one PatternClassification. For M1 only three patterns have
generators (RENAME / CONCAT / DERIVED); the other six (SPLIT, CONSTANT,
CONDITIONAL, LOOKUP, AGGREGATION, UNIT_CONVERSION) map to UNSUPPORTED_IN_M1
which is the explicit escape hatch in the Pattern enum.

This keeps scope discipline visible in the code AND in the eval metrics —
UNSUPPORTED_IN_M1 counts show how much of the benchmark is out of reach for
this milestone.
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field

from agents.llm import LLMClient, get_cached, prompt_cache_key
from schemas import CandidateSet, ColumnProfile, Pattern, PatternClassification

log = logging.getLogger(__name__)


class ClassifierOutput(BaseModel):
    """Structured output: one pattern choice per target."""

    pattern: Pattern
    source_fqns: list[str] = Field(
        default_factory=list,
        description="Source FQNs involved, in the order they appear in the transformation.",
    )
    rationale: str
    llm_confidence: float = Field(ge=0.0, le=1.0)


_PATTERN_GUIDE = """\
Pattern options (choose EXACTLY ONE):

M1-SUPPORTED (generator exists):
  - rename            1 source -> 1 target. Possibly a type cast. E.g., CustomerID -> CustomerKey
  - concat            N sources -> 1 target via string concatenation (concat_ws or similar).
                      E.g., FirstName + MiddleName + LastName -> FullName
  - derived           Computed from 1+ sources via a SQL expression (CASE, arithmetic, date parts).
                      E.g., EmailPromotion INT -> EmailPromotionCategory via CASE, OR
                      OrderDate -> CalendarYear via YEAR(), OR SubTotal + TaxAmt + Freight -> SalesAmount

NOT-YET-SUPPORTED (flag with unsupported_in_m1):
  - split             1 source -> N targets (this target is one of the N). E.g., FullName -> FirstName
  - constant          Target is a literal constant, no source.
  - conditional       Boolean-logic cascades that go beyond CASE. (Overlap with `derived`; prefer derived.)
  - lookup            Requires joining to a separate reference/dimension table not among sources.
  - aggregation       Requires GROUP BY (per customer / per month / etc.).
  - unit_conversion   Cross-unit transforms (USD<->EUR, kg<->lb). Not supported until M5.

Special values:
  - composite         Would require chaining two or more M1 patterns. Mark as unsupported_in_m1 for M1.
  - unsupported_in_m1 Explicit escape hatch; set when none of the M1-supported patterns fits cleanly.
"""


_SYSTEM_PROMPT = f"""\
You are a DataOps expert classifying the transformation pattern for a single TARGET column
given its top source candidates.

{_PATTERN_GUIDE}

Rules:
  - Exactly ONE pattern from the enum.
  - Prefer the M1-supported pattern that fits best. Only fall through to unsupported_in_m1 if
    a non-M1 pattern is clearly needed.
  - `source_fqns` MUST be drawn from the candidate FQNs provided. Do not invent sources.
  - If the CandidateSet is empty / no_match, return pattern=unsupported_in_m1, source_fqns=[].
  - Calibrate llm_confidence honestly: 1.0 = certain, 0.5 = plausible, 0.2 = weak signal.

Disambiguation guidance:
  - Pick `derived` (NOT `rename`) when the target value is computed by combining MULTIPLE source
    columns via arithmetic. Example: an `ExtendedAmount` target with both `UnitPrice` and `OrderQty`
    in the candidates is `derived` with sql `UnitPrice * OrderQty`, NOT `rename` from one of them.
  - Pick `rename` when EXACTLY ONE source candidate carries the target's full value, even if a
    type cast is involved. A persisted-computed source column (e.g. `LineTotal`) that already
    holds the answer is a `rename`, even though its underlying definition is arithmetic.
  - Pick `concat` when the target is a string built by joining 2+ string source columns.
    Single-source string mappings are `rename`, not `concat`.

Examples:
  TARGET: dbo.DimCustomer.FullName (VARCHAR)
  CANDIDATES: 1. Person.Person.FirstName  2. Person.Person.MiddleName  3. Person.Person.LastName
  -> pattern=concat, source_fqns=[Person.Person.FirstName, Person.Person.MiddleName, Person.Person.LastName]

  TARGET: dbo.FactInternetSales.ExtendedAmount (DECIMAL)
  CANDIDATES: 1. Sales.SalesOrderDetail.UnitPrice  2. Sales.SalesOrderDetail.OrderQty
  -> pattern=derived, source_fqns=[Sales.SalesOrderDetail.UnitPrice, Sales.SalesOrderDetail.OrderQty]
     (multiplication: UnitPrice * OrderQty)

  TARGET: dbo.FactInternetSales.SalesAmount (DECIMAL)
  CANDIDATES: 1. Sales.SalesOrderDetail.LineTotal  (a persisted computed column)
  -> pattern=rename, source_fqns=[Sales.SalesOrderDetail.LineTotal]
     (LineTotal already holds the value; no recomputation needed downstream)

  TARGET: dbo.FactInternetSales.DiscountAmount (DECIMAL)
  CANDIDATES: 1. Sales.SalesOrderDetail.UnitPrice  2. Sales.SalesOrderDetail.UnitPriceDiscount (a percentage 0..1)  3. Sales.SalesOrderDetail.OrderQty
  -> pattern=derived, source_fqns=[Sales.SalesOrderDetail.UnitPrice, Sales.SalesOrderDetail.UnitPriceDiscount, Sales.SalesOrderDetail.OrderQty]
     (multiplication: UnitPrice * UnitPriceDiscount * OrderQty — discount-percentage applied to extended amount)
"""


def _format_input(target: ColumnProfile, cs: CandidateSet) -> str:
    lines = [
        f"TARGET: {target.fqn}",
        f"Type: {target.sql_type}",
    ]
    if target.ms_description:
        lines.append(f"Description: {target.ms_description}")
    if target.inferred_semantic_type.value != "unknown":
        lines.append(f"Semantic type: {target.inferred_semantic_type.value}")

    if cs.no_match or not cs.candidates:
        lines.append("\nCANDIDATES: (none — no plausible source found)")
    else:
        lines.append("\nCANDIDATES (best-first, from Semantic Matcher):")
        for i, c in enumerate(cs.candidates, 1):
            lines.append(f"  {i}. {c.source_fqn}  sim={c.embedding_similarity:.2f}  {c.rationale}")

    lines.append("\nReturn JSON matching the ClassifierOutput schema.")
    return "\n".join(lines)


def classify_target_columns(
    target_cols: list[ColumnProfile],
    candidate_sets: dict[str, CandidateSet],
    llm: LLMClient,
    *,
    rate_limit_delay_sec: float = 0.0,
) -> dict[str, PatternClassification]:
    """Return {target_fqn: PatternClassification} for every input target column."""
    out: dict[str, PatternClassification] = {}
    total = len(target_cols)
    for idx, col in enumerate(target_cols, start=1):
        log.info("pattern_classifier %d/%d: %s", idx, total, col.fqn)
        cs = candidate_sets.get(
            col.fqn, CandidateSet(target_fqn=col.fqn, candidates=[], no_match=True)
        )

        if cs.no_match or not cs.candidates:
            out[col.fqn] = PatternClassification(
                target_fqn=col.fqn,
                pattern=Pattern.UNSUPPORTED_IN_M1,
                source_fqns=[],
                rationale="No candidate source columns found by the Semantic Matcher.",
                llm_confidence=1.0,
            )
            continue

        user_prompt = _format_input(col, cs)
        key = prompt_cache_key(
            llm.provider, llm.model, _SYSTEM_PROMPT, user_prompt, ClassifierOutput.__name__
        )
        cache_hit = get_cached(key) is not None

        try:
            result = llm.structured(_SYSTEM_PROMPT, user_prompt, ClassifierOutput)
        except Exception as exc:  # noqa: BLE001
            log.warning("pattern_classifier LLM failed for %s: %s", col.fqn, exc)
            out[col.fqn] = PatternClassification(
                target_fqn=col.fqn,
                pattern=Pattern.UNSUPPORTED_IN_M1,
                source_fqns=[],
                rationale=f"Classifier LLM call failed: {exc}",
                llm_confidence=0.0,
            )
            continue

        # Validate source_fqns against candidate set
        valid = {c.source_fqn for c in cs.candidates}
        kept = [s for s in result.source_fqns if s in valid]
        if len(kept) < len(result.source_fqns):
            log.warning(
                "pattern_classifier: dropped %d invented source_fqns for %s",
                len(result.source_fqns) - len(kept),
                col.fqn,
            )

        out[col.fqn] = PatternClassification(
            target_fqn=col.fqn,
            pattern=result.pattern,
            source_fqns=kept,
            rationale=result.rationale,
            llm_confidence=result.llm_confidence,
        )

        if not cache_hit and rate_limit_delay_sec > 0 and idx < total:
            time.sleep(rate_limit_delay_sec)

    return out
