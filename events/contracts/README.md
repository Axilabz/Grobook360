# Event contracts

`events/schemas/` holds JSON Schema (2020-12) for the envelope and five v1 events:
`InvoiceCreated`, `InvoiceCancelled`, `StockUpdated`, `PurchaseCompleted`, `JournalEntryCreated`.

**No event is emitted or consumed anywhere yet.** These are contracts for Phase 2+. No broker was introduced.

## Rules
- Money is a decimal **string**, never a float.
- `event_id` is the consumer's idempotency key; delivery will be at-least-once.
- `tenant_id` is mandatory; consumers must set tenant context before touching data.
- Schemas are immutable once published: add `v2` files, never edit `v1`. Only add optional fields within a version.
- `additionalProperties: false` on payloads so drift is caught in tests.

## Transactional Outbox (planned pattern)

```
BEGIN;
  UPDATE/INSERT business rows;            -- e.g. sales_invoice → POSTED
  INSERT INTO <schema>.outbox (event_id, tenant_id, event_type, event_version, payload, correlation_id, created_at, published_at NULL);
COMMIT;                                   -- both or neither

relay (poll or LISTEN/NOTIFY → Cloudflare Queue / other transport):
  SELECT … FROM outbox WHERE published_at IS NULL ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT n;
  publish; UPDATE outbox SET published_at = now() WHERE event_id = …;

consumer:
  INSERT INTO inbox(event_id) ON CONFLICT DO NOTHING; if no row inserted → already processed, ack and skip.
```

The relay may publish an event twice (crash after publish, before marking); that is why consumers de-duplicate on `event_id`. Each owning service gets its own `outbox` table in its schema. Tables are **not** created in Phase 1A.
