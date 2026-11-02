"""Structural checks on events/schemas (no jsonschema dependency in this project)."""

import json
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[3] / "events" / "schemas"
_EVENTS = ["InvoiceCreated", "InvoiceCancelled", "StockUpdated", "PurchaseCompleted", "JournalEntryCreated"]


def _load(name: str) -> dict:
    return json.loads((_DIR / name).read_text(encoding="utf-8"))


def test_envelope_requires_tenant_correlation_and_idempotency_key():
    env = _load("envelope.schema.json")
    assert {"event_id", "tenant_id", "correlation_id", "occurred_at", "event_version"} <= set(env["required"])
    assert env["additionalProperties"] is False


@pytest.mark.parametrize("name", _EVENTS)
def test_event_schema_is_versioned_and_references_envelope(name):
    schema = _load(f"{name}.v1.schema.json")
    assert schema["$id"].endswith(f"{name}.v1.schema.json")
    assert schema["allOf"] == [{"$ref": "envelope.schema.json"}]
    props = schema["properties"]
    assert props["event_type"]["const"] == name and props["event_version"]["const"] == 1
    payload = props["payload"]
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) <= set(payload["properties"])


@pytest.mark.parametrize("name", _EVENTS)
def test_money_is_never_a_float(name):
    payload = _load(f"{name}.v1.schema.json")["properties"]["payload"]["properties"]
    for field, spec in payload.items():
        assert spec.get("type") != "number", f"{name}.{field} must be a decimal string, not a float"
