"""Unit tests for ConcatGenerator."""

from __future__ import annotations

import pytest

from generators import ConcatGenerator, GenerationContext
from schemas import ColumnProfile, MappingProposal, Pattern


def _col(fqn: str, sql_type: str, *, is_nullable: bool = True) -> ColumnProfile:
    schema, table, column = fqn.split(".", 2)
    return ColumnProfile(
        table_schema=schema,
        table_name=table,
        column_name=column,
        ordinal_position=1,
        sql_type=sql_type,
        is_nullable=is_nullable,
        is_primary_key=False,
        is_foreign_key=False,
        null_rate=0.0,
        distinct_count=1,
        total_count=1,
    )


class TestConcatSQL:
    def test_concat_ws_with_string_sources(self) -> None:
        first = _col("Person.Person.FirstName", "nvarchar(50)")
        middle = _col("Person.Person.MiddleName", "nvarchar(50)")
        last = _col("Person.Person.LastName", "nvarchar(50)")
        tgt = _col("dbo.DimCustomer.FullName", "nvarchar(100)", is_nullable=False)

        spec = ConcatGenerator().generate(
            MappingProposal(
                target_fqn=tgt.fqn,
                source_fqns=[first.fqn, middle.fqn, last.fqn],
                pattern=Pattern.CONCAT,
                rationale="",
            ),
            GenerationContext(target=tgt, sources=[first, middle, last]),
        )

        assert spec.pattern == Pattern.CONCAT
        # concat_ws used for NULL-safety (per docstring)
        assert "concat_ws(' '," in spec.sql
        # Bare column names, in order, present
        assert "FirstName" in spec.sql
        assert "MiddleName" in spec.sql
        assert "LastName" in spec.sql
        assert "AS FullName" in spec.sql
        # No CAST for string types
        assert "CAST" not in spec.sql

    def test_numeric_sources_get_cast_to_varchar(self) -> None:
        a = _col("t.t.part_a", "int")
        b = _col("t.t.part_b", "varchar(20)")
        tgt = _col("u.u.combined", "varchar(50)")

        spec = ConcatGenerator().generate(
            MappingProposal(
                target_fqn=tgt.fqn,
                source_fqns=[a.fqn, b.fqn],
                pattern=Pattern.CONCAT,
                rationale="",
            ),
            GenerationContext(target=tgt, sources=[a, b]),
        )
        # Numeric source got CAST; string source didn't
        assert "CAST(part_a AS VARCHAR)" in spec.sql
        assert "part_b" in spec.sql
        assert "CAST(part_b" not in spec.sql


class TestConcatValidation:
    def test_raises_when_single_source(self) -> None:
        src = _col("a.b.c", "nvarchar(50)")
        tgt = _col("x.y.z", "nvarchar(50)")
        with pytest.raises(ValueError, match=">=2 sources"):
            ConcatGenerator().generate(
                MappingProposal(
                    target_fqn=tgt.fqn, source_fqns=[src.fqn], pattern=Pattern.CONCAT, rationale=""
                ),
                GenerationContext(target=tgt, sources=[src]),
            )
