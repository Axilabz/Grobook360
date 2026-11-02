# API endpoint → service mapping

Public paths are unchanged (`/api/v1/<existing path>`). Column "Owner" is the service that will own the route; in Phase 1A **every route is still served by the monolith**. The gateway table is `backend/gateway/app/core/routing.py` (a unit test pins its behaviour).

| Prefix (under `/api/v1`) | Owner | Phase |
|---|---|---|
| `auth/*`, `users`, `roles`, `permissions` | identity | **1B** |
| `tenant`, `configuration` | tenant | **1B** |
| `products`, `units` | master-data | **1B** |
| `inventory` | inventory | after Outbox |
| `customers`, `sales/*` (estimates, orders, delivery-challans, invoices, returns, credit-debit-notes, e-invoice), `eway-bills`, `integration/*` | sales | after Outbox |
| `suppliers`, `purchase/*` | purchase | after Outbox |
| `accounting`, `customer-receipts`, `supplier-payments` | accounting | after Outbox |
| `gst` | gst | after Outbox |
| `payroll` (prefix not pinned in the table; defaults to monolith) | payroll | later |
| `reports`, `analysis`, `exports`, `parties` | analytics (read-only) | later |
| `health`, `version` | each process | — |

Gateway-owned: `GET /gateway/health`, `/gateway/health/ready`, `/gateway/routes`.

The prompt's example paths (`/api/v1/identity/*`, `/api/v1/tenants/*`, …) were **not** introduced: they would break the existing frontend contract. If wanted, they can be added as aliases in Phase 1B.
