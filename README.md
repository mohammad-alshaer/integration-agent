# Integration-Agent

Multi-agent AI system that automates schema mapping and dbt-model generation for data integration work (OLTP to analytical warehouse). Given a source schema and a target schema, the agent profiles both, semantically matches fields, classifies transformation patterns, generates dbt models, validates them in a DuckDB sandbox, and surfaces low-confidence mappings for human review.

**Status:** M0 — repo scaffold.
**Primary benchmark:** AdventureWorks OLTP to AdventureWorksDW.
**Implementation plan:** see `~/.claude/plans/i-want-to-do-jiggly-yeti.md`.
