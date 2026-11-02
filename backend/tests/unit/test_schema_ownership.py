"""Guards database/documentation/schema-ownership.json against drift.

Phase 1A only DOCUMENTS which service will own each table. This test makes
sure every table the ORM defines has exactly one owner, so a new model cannot
be added without deciding who owns it.
"""

import json
from pathlib import Path

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.db.base import Base

_MAP = Path(__file__).resolve().parents[3] / "database" / "documentation" / "schema-ownership.json"


def _owners() -> dict[str, list[str]]:
    return json.loads(_MAP.read_text(encoding="utf-8"))["owners"]


def test_every_orm_table_has_exactly_one_owner():
    owned = [t for tables in _owners().values() for t in tables]
    assert len(owned) == len(set(owned)), "a table is listed under two owners"
    assert set(owned) == set(Base.metadata.tables), (
        f"unmapped: {sorted(set(Base.metadata.tables) - set(owned))}; "
        f"stale: {sorted(set(owned) - set(Base.metadata.tables))}"
    )


def test_owner_names_are_valid_postgres_schema_names():
    for name in _owners():
        assert name.isidentifier() and name == name.lower()
