"""Transformation Generator — dispatcher that routes each MappingProposal to the right generator.

Takes the PatternClassifier outputs + source/target profiles, builds one
MappingSpec per target column, attaches provider/model metadata from the LLM
client, and returns the list.

Generators are indexed by Pattern. Classifications that land on non-M1
patterns (UNSUPPORTED_IN_M1, COMPOSITE, or any other non-{RENAME,CONCAT,DERIVED})
are NOT emitted — we surface them as gaps in the eval report instead.
"""

from __future__ import annotations

import logging

from agents.llm import LLMClient
from generators import ConcatGenerator, DerivedGenerator, GenerationContext, RenameGenerator
from schemas import ColumnProfile, MappingProposal, MappingSpec, Pattern, PatternClassification

log = logging.getLogger(__name__)

_M1_PATTERNS = {Pattern.RENAME, Pattern.CONCAT, Pattern.DERIVED}


def generate_mappings(
    classifications: dict[str, PatternClassification],
    target_columns: dict[str, ColumnProfile],
    source_columns: dict[str, ColumnProfile],
    llm: LLMClient,
) -> list[MappingSpec]:
    """Produce MappingSpec list for every M1-supported classification."""
    generators = {
        Pattern.RENAME: RenameGenerator(),
        Pattern.CONCAT: ConcatGenerator(),
        Pattern.DERIVED: DerivedGenerator(llm),
    }

    specs: list[MappingSpec] = []
    for target_fqn, classification in classifications.items():
        if classification.pattern not in _M1_PATTERNS:
            log.info(
                "skipping %s — pattern=%s not generated in M1",
                target_fqn,
                classification.pattern.value,
            )
            continue

        target = target_columns.get(target_fqn)
        if target is None:
            log.warning("skipping %s — target ColumnProfile missing from map", target_fqn)
            continue

        sources: list[ColumnProfile] = []
        missing: list[str] = []
        for s_fqn in classification.source_fqns:
            c = source_columns.get(s_fqn)
            if c is None:
                missing.append(s_fqn)
            else:
                sources.append(c)
        if missing:
            log.warning("skipping %s — source ColumnProfile(s) missing: %s", target_fqn, missing)
            continue

        proposal = MappingProposal(
            target_fqn=target_fqn,
            source_fqns=[s.fqn for s in sources],
            pattern=classification.pattern,
            rationale=classification.rationale,
        )
        ctx = GenerationContext(target=target, sources=sources)
        gen = generators[classification.pattern]

        try:
            spec = gen.generate(proposal, ctx)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "generator %s failed for %s: %s", classification.pattern.value, target_fqn, exc
            )
            continue

        # Carry through classifier's confidence + provider metadata
        spec.llm_confidence = classification.llm_confidence
        spec.provider = llm.provider
        spec.model = llm.model
        specs.append(spec)

    return specs
