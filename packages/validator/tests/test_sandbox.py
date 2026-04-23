"""Unit tests for Sandbox — Parquet-to-view loading."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from validator.sandbox import Sandbox


@pytest.fixture()
def sample_dir(tmp_path: Path) -> Path:
    # Two Parquet files with the schema.table naming convention used by sqlserver/sample.py
    pd.DataFrame(
        {
            "BusinessEntityID": [1, 2, 3],
            "FirstName": ["Ada", None, "Grace"],
            "LastName": ["Lovelace", "Hopper", "Hopper"],
        }
    ).to_parquet(tmp_path / "Person.Person.parquet", index=False)

    pd.DataFrame(
        {
            "CustomerID": [10, 11],
            "AccountNumber": ["AW00000010", "AW00000011"],
        }
    ).to_parquet(tmp_path / "Sales.Customer.parquet", index=False)
    return tmp_path


class TestSandbox:
    def test_loads_each_parquet_as_view(self, sample_dir: Path) -> None:
        with Sandbox(sample_dir) as sb:
            assert sb.view_for("Person", "Person") == "source_raw.Person_Person"
            assert sb.view_for("Sales", "Customer") == "source_raw.Sales_Customer"

    def test_views_queryable(self, sample_dir: Path) -> None:
        with Sandbox(sample_dir) as sb:
            rows = sb.con.execute(
                f"SELECT COUNT(*) FROM {sb.view_for('Person', 'Person')}"
            ).fetchone()
            assert rows[0] == 3
            rows = sb.con.execute(
                f"SELECT COUNT(*) FROM {sb.view_for('Sales', 'Customer')}"
            ).fetchone()
            assert rows[0] == 2

    def test_missing_source_returns_none(self, sample_dir: Path) -> None:
        with Sandbox(sample_dir) as sb:
            assert sb.view_for("Nope", "Missing") is None

    def test_custom_schema(self, sample_dir: Path) -> None:
        with Sandbox(sample_dir, sandbox_schema="mysandbox") as sb:
            assert sb.view_for("Person", "Person") == "mysandbox.Person_Person"
            # View is actually queryable
            sb.con.execute(f"SELECT 1 FROM {sb.view_for('Person', 'Person')} LIMIT 1").fetchone()

    def test_nonexistent_sample_dir_is_tolerated(self, tmp_path: Path) -> None:
        with Sandbox(tmp_path / "does_not_exist") as sb:
            assert sb.view_for("x", "y") is None
