"""Verify AdventureWorks 2022 OLTP + DW are restored correctly on SQLDEV2025.

Exits 0 on success, 1 on any mismatch. Row-count expectations come from the
Microsoft-published baseline; they are stable across machines.
"""

from __future__ import annotations

import sys

import pyodbc


def _conn_str(database: str) -> str:
    return (
        "Driver={ODBC Driver 18 for SQL Server};"
        "Server=localhost\\SQLDEV2025;"
        f"Database={database};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )


EXPECTED: list[tuple[str, str, int]] = [
    ("AdventureWorks2022", "Sales.SalesOrderHeader", 31465),
    ("AdventureWorks2022", "Sales.SalesOrderDetail", 121317),
    ("AdventureWorks2022", "Person.Person", 19972),
    ("AdventureWorksDW2022", "dbo.FactInternetSales", 60398),
    ("AdventureWorksDW2022", "dbo.DimCustomer", 18484),
    ("AdventureWorksDW2022", "dbo.DimProduct", 606),
]


def main() -> int:
    failures: list[str] = []
    for db, table, expected in EXPECTED:
        try:
            with pyodbc.connect(_conn_str(db)) as conn:
                cur = conn.cursor()
                cur.execute(f"SELECT COUNT(*) FROM {table};")
                actual = cur.fetchone()[0]
        except pyodbc.Error as exc:
            failures.append(f"  [{db}].{table}  ERROR: {exc}")
            continue

        status = "OK " if actual == expected else "FAIL"
        line = f"  {status}  [{db}].{table:<35}  expected={expected:>7}  actual={actual:>7}"
        print(line)
        if actual != expected:
            failures.append(line)

    if failures:
        print("\nAdventureWorks verification FAILED:", file=sys.stderr)
        for f in failures:
            print(f, file=sys.stderr)
        return 1
    print("\nAdventureWorks verification: all expected row counts match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
