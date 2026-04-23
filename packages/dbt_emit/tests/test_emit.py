"""Golden-file tests for dbt_emit."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dbt_emit import emit_dbt_project, write_models, write_project_yml, write_schema_yml
from schemas import DbtTest, MappingSpec, Pattern


def _spec(
    target_fqn: str,
    source_fqns: list[str],
    sql: str,
    pattern: Pattern,
    tests: list[DbtTest] | None = None,
    pass_rate: float | None = None,
) -> MappingSpec:
    s = MappingSpec(
        target_fqn=target_fqn,
        source_fqns=source_fqns,
        pattern=pattern,
        sql=sql,
        rationale="test",
        tests=tests or [],
        llm_confidence=0.9,
    )
    s.validation_pass_rate = pass_rate
    return s


@pytest.fixture()
def canned_specs() -> list[MappingSpec]:
    return [
        _spec(
            "dbo.DimCustomer.CustomerKey",
            ["Sales.Customer.CustomerID"],
            "SELECT CustomerID AS CustomerKey",
            Pattern.RENAME,
            tests=[DbtTest(name="not_null"), DbtTest(name="unique")],
            pass_rate=1.0,
        ),
        _spec(
            "dbo.DimCustomer.FirstName",
            ["Person.Person.FirstName"],
            "SELECT FirstName AS FirstName",
            Pattern.RENAME,
            pass_rate=0.85,
        ),
        _spec(
            "dbo.DimCustomer.FullName",
            ["Person.Person.FirstName", "Person.Person.MiddleName", "Person.Person.LastName"],
            "SELECT concat_ws(' ', FirstName, MiddleName, LastName) AS FullName",
            Pattern.CONCAT,
            tests=[DbtTest(name="not_null")],
            pass_rate=1.0,
        ),
        _spec(
            "dbo.DimCustomer.EmailPromotionCategory",
            ["Person.Person.EmailPromotion"],
            "SELECT CASE WHEN EmailPromotion = 0 THEN 'None' ELSE 'Other' END AS EmailPromotionCategory",
            Pattern.DERIVED,
            tests=[
                DbtTest(name="accepted_values", config={"values": ["None", "Other"]}),
            ],
            pass_rate=1.0,
        ),
    ]


class TestProjectYml:
    def test_emits_expected_shape(self, tmp_path: Path) -> None:
        path = write_project_yml(tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "name: 'integration_agent_out'" in content
        assert "profile: 'integration_agent_local'" in content
        assert "staging:" in content
        assert "+materialized: view" in content


class TestWriteModels:
    def test_groups_specs_by_target_and_source_table(
        self, tmp_path: Path, canned_specs: list[MappingSpec]
    ) -> None:
        written = write_models(canned_specs, tmp_path, run_id="t1")
        names = {p.name for p in written}
        # DimCustomer from Person.Person (3 specs) + DimCustomer from Sales.Customer (1 spec)
        assert "stg_dim_customer_from_person_person.sql" in names
        assert "stg_dim_customer_from_sales_customer.sql" in names

    def test_emitted_sql_is_well_formed(
        self, tmp_path: Path, canned_specs: list[MappingSpec]
    ) -> None:
        write_models(canned_specs, tmp_path, run_id="t1")
        person_sql = (
            tmp_path / "models" / "staging" / "stg_dim_customer_from_person_person.sql"
        ).read_text(encoding="utf-8")
        # config block present
        assert "{{ config(" in person_sql
        # source macro references the sandbox-shaped table name
        assert "{{ source('aw_oltp', 'Person_Person') }}" in person_sql
        # All three aliases from Person.Person specs show up
        assert "AS FirstName" in person_sql
        assert "AS FullName" in person_sql
        assert "AS EmailPromotionCategory" in person_sql
        # Tail comment with pass_rate for the first spec
        assert "pass_rate=1.00" in person_sql or "pass_rate=0.85" in person_sql

    def test_single_source_table_model(
        self, tmp_path: Path, canned_specs: list[MappingSpec]
    ) -> None:
        write_models(canned_specs, tmp_path, run_id="t1")
        sales_sql = (
            tmp_path / "models" / "staging" / "stg_dim_customer_from_sales_customer.sql"
        ).read_text(encoding="utf-8")
        assert "CustomerID AS CustomerKey" in sales_sql
        assert "{{ source('aw_oltp', 'Sales_Customer') }}" in sales_sql

    def test_multi_source_specs_go_to_sidecar(self, tmp_path: Path) -> None:
        # A spec that references two different source tables should not be modeled
        multi = _spec(
            "dbo.DimX.Col",
            ["Person.Person.FirstName", "Sales.Customer.CustomerID"],
            "SELECT FirstName AS Col",
            Pattern.DERIVED,
        )
        written = write_models([multi], tmp_path)
        sidecar = tmp_path / "models" / "staging" / "_unmodeled_multi_source.txt"
        assert sidecar in written
        txt = sidecar.read_text(encoding="utf-8")
        assert "dbo.DimX.Col" in txt


class TestSchemaYml:
    def test_sources_and_models_present(
        self, tmp_path: Path, canned_specs: list[MappingSpec]
    ) -> None:
        path = write_schema_yml(canned_specs, tmp_path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert payload["version"] == 2
        assert payload["sources"][0]["name"] == "aw_oltp"
        src_tables = {t["name"] for t in payload["sources"][0]["tables"]}
        assert "Person_Person" in src_tables
        assert "Sales_Customer" in src_tables

        models_by_name = {m["name"]: m for m in payload["models"]}
        person_model = models_by_name["stg_dim_customer_from_person_person"]
        cols_by_name = {c["name"]: c for c in person_model["columns"]}
        assert set(cols_by_name.keys()) >= {"FirstName", "FullName", "EmailPromotionCategory"}

    def test_accepted_values_test_propagated(
        self, tmp_path: Path, canned_specs: list[MappingSpec]
    ) -> None:
        path = write_schema_yml(canned_specs, tmp_path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        models = {m["name"]: m for m in payload["models"]}
        person_model = models["stg_dim_customer_from_person_person"]
        cols = {c["name"]: c for c in person_model["columns"]}
        epc = cols["EmailPromotionCategory"]
        # Test declared with config => rendered as dict
        assert any(isinstance(t, dict) and "accepted_values" in t for t in epc.get("tests", []))

    def test_not_null_and_unique_on_business_key(
        self, tmp_path: Path, canned_specs: list[MappingSpec]
    ) -> None:
        path = write_schema_yml(canned_specs, tmp_path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        models = {m["name"]: m for m in payload["models"]}
        sales_model = models["stg_dim_customer_from_sales_customer"]
        cols = {c["name"]: c for c in sales_model["columns"]}
        ck = cols["CustomerKey"]
        names = {t if isinstance(t, str) else next(iter(t)) for t in ck["tests"]}
        assert {"not_null", "unique"} <= names


class TestEmitDbtProject:
    def test_full_emission(self, tmp_path: Path, canned_specs: list[MappingSpec]) -> None:
        duckdb_path = tmp_path / "sandbox.duckdb"
        emitted = emit_dbt_project(canned_specs, tmp_path / "project", duckdb_path)
        assert emitted.project_yml.exists()
        assert emitted.profiles_yml.exists()
        assert emitted.schema_yml.exists()
        assert len(emitted.model_files) >= 2
        # profiles.yml points at the given DuckDB path (forward slashes)
        prof_content = emitted.profiles_yml.read_text(encoding="utf-8")
        assert "duckdb" in prof_content
        assert "sandbox.duckdb" in prof_content
