"""Live integration test — runs against the local SQLDEV2025 instance + restored AdventureWorks2022.

Skipped automatically if the server isn't reachable, so CI / fresh-clone environments
don't fail. Real value is catching regressions when the introspection queries drift
from the actual schema.
"""

from __future__ import annotations

import pyodbc
import pytest

from sqlserver import connect, introspect_schema


def _server_reachable() -> bool:
    try:
        conn = connect("master")
        conn.close()
        return True
    except pyodbc.Error:
        return False


pytestmark = pytest.mark.skipif(
    not _server_reachable(), reason="local SQLDEV2025 instance not reachable"
)


@pytest.fixture(scope="module")
def aw_profile():
    conn = connect("AdventureWorks2022")
    try:
        yield introspect_schema(conn, "AdventureWorks2022", role="source")
    finally:
        conn.close()


def test_person_person_business_entity_id_is_ordinal_1_and_pk(aw_profile):
    person = next(
        t for t in aw_profile.tables if t.table_schema == "Person" and t.table_name == "Person"
    )
    be_id = next(c for c in person.columns if c.column_name == "BusinessEntityID")
    assert be_id.ordinal_position == 1
    assert be_id.is_primary_key is True
    assert be_id.sql_type == "int"
    assert be_id.is_nullable is False


def test_sales_customer_personid_fk_resolves_to_person(aw_profile):
    customer = next(
        t for t in aw_profile.tables if t.table_schema == "Sales" and t.table_name == "Customer"
    )
    person_id = next(c for c in customer.columns if c.column_name == "PersonID")
    assert person_id.is_foreign_key is True
    assert person_id.fk_ref == "Person.Person.BusinessEntityID"


def test_system_tables_filtered_out(aw_profile):
    schemas = {t.table_schema for t in aw_profile.tables}
    assert "sys" not in schemas
    assert "INFORMATION_SCHEMA" not in schemas
    names = {(t.table_schema, t.table_name) for t in aw_profile.tables}
    assert ("dbo", "sysdiagrams") not in names
