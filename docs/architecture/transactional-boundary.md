# Why Sales, Inventory, Accounting and GST are not split yet

Posting a Sales Invoice today runs, inside **one database transaction**:

1. lock + validate the invoice, stock-out per line (`InventoryService.post_movement`, row locks, negative-stock guard)
2. balanced journal (`AccountingPostingService` → `JournalService`)
3. GST ledger rows (`GstReportingService`)
4. bookkeeping counters (`paid_amount`, `returned_quantity`, …), idempotency record, audit log

If these become separate processes there is no shared transaction: a crash between (1) and (2) leaves stock removed with no journal, and retries can double-post. The same applies to Purchase, Payments, Returns and Credit/Debit Notes.

## Preconditions before extraction (per approval condition 9)

| Mechanism | Needed because | Designed | Tested |
|---|---|---|---|
| Transactional Outbox (event written in the same tx as the state change) | no lost/phantom events | contract + pattern in `events/contracts/README.md` | no |
| Consumer idempotency (`event_id` de-dup table) | at-least-once delivery | schema has `event_id` | no |
| Compensation (reverse stock / reverse journal) | partial failure | reversal primitives exist (`*_REVERSAL` ledger sources, `reverse_journal`) | per-document only |
| Reconciliation job (ledger vs journal vs GST vs stock cache) | detect drift | reconciliation *reports* exist (GST vs journal) | no job |

Only when all four are implemented **and tested under failure injection** should Sales/Inventory/Accounting/GST be separated.
