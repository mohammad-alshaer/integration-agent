"""Pydantic v2 contracts shared by every Integration-Agent specialist.

These types are the contract between Schema Explorer, Semantic Matcher,
Pattern Classifier, Transformation Generator, and Validator. Change them
reluctantly; every change ripples through prompts.
"""

from schemas.api import EvalSummary, HealthResponse, MapRequest, MapResponse
from schemas.candidates import CandidateSet, MatchCandidate
from schemas.mapping import DbtTest, MappingProposal, MappingSpec
from schemas.patterns import Pattern, PatternClassification
from schemas.profile import (
    ColumnProfile,
    QualityFlag,
    SchemaProfile,
    SemanticType,
    TableProfile,
)
from schemas.trace import DecisionStep, DecisionTrace
from schemas.validation import ErrorHint, ErrorKind, ValidationReport

__all__ = [
    "CandidateSet",
    "ColumnProfile",
    "DbtTest",
    "DecisionStep",
    "DecisionTrace",
    "ErrorHint",
    "ErrorKind",
    "EvalSummary",
    "HealthResponse",
    "MapRequest",
    "MapResponse",
    "MappingProposal",
    "MappingSpec",
    "MatchCandidate",
    "Pattern",
    "PatternClassification",
    "QualityFlag",
    "SchemaProfile",
    "SemanticType",
    "TableProfile",
    "ValidationReport",
]
