"""Schema + column profiles. The output of Schema Explorer, input to every downstream stage."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SemanticType(StrEnum):
    UNKNOWN = "unknown"
    IDENTIFIER = "identifier"
    EMAIL = "email"
    PHONE = "phone"
    PERSON_NAME = "person_name"
    ADDRESS_LINE = "address_line"
    CITY = "city"
    COUNTRY_CODE = "country_code"
    POSTAL_CODE = "postal_code"
    CURRENCY_AMOUNT = "currency_amount"
    PERCENTAGE = "percentage"
    QUANTITY = "quantity"
    DATE = "date"
    TIMESTAMP = "timestamp"
    BOOLEAN_FLAG = "boolean_flag"
    ENUM_CATEGORY = "enum_category"
    FREE_TEXT = "free_text"


class QualityFlag(StrEnum):
    HIGH_NULL_RATE = "high_null_rate"
    LOW_CARDINALITY = "low_cardinality"
    SUSPECT_PII = "suspect_pii"
    NO_DESCRIPTION = "no_description"
    AMBIGUOUS_TYPE = "ambiguous_type"


class ColumnProfile(BaseModel):
    """One column, introspected + enriched with profile stats + semantic inference."""

    table_schema: str
    table_name: str
    column_name: str
    ordinal_position: int
    sql_type: str
    is_nullable: bool
    is_primary_key: bool
    is_foreign_key: bool
    fk_ref: str | None = None
    ms_description: str | None = None

    # Profile stats (filled in from sampled rows)
    null_rate: float = Field(ge=0.0, le=1.0)
    distinct_count: int
    total_count: int
    top_values: list[tuple[Any, int]] = []
    min_value: Any | None = None
    max_value: Any | None = None

    # Enriched by Schema Explorer LLM
    inferred_semantic_type: SemanticType = SemanticType.UNKNOWN
    semantic_type_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    quality_flags: list[QualityFlag] = []

    @property
    def fqn(self) -> str:
        """Fully-qualified name: schema.table.column."""
        return f"{self.table_schema}.{self.table_name}.{self.column_name}"


class TableProfile(BaseModel):
    table_schema: str
    table_name: str
    row_count_estimate: int
    columns: list[ColumnProfile]
    primary_key: list[str] = []
    foreign_keys: list[dict[str, str]] = []
    ms_description: str | None = None


class SchemaProfile(BaseModel):
    """Full database profile (source or target)."""

    database_name: str
    role: str  # "source" | "target"
    tables: list[TableProfile]
    profiled_at: str  # ISO8601
