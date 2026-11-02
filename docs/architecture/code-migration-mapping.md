# Old → new code mapping

Phase 1A moved **nothing**. This is the plan for Phase 1B/later; `backend/app/` remains authoritative until a service passes its own tests.

| Existing (`backend/app/…`) | Future home |
|---|---|
| `api/v1/{auth,password_reset,users,roles}.py`, `services/{auth,user_management,rbac,signup,password_recovery}/`, models `user, role, permission, role_permission, user_role, auth_session, password_reset_token` | `services/identity-service` (Phase 1B) |
| `api/v1/{tenant,configuration}.py`, `services/{tenant,configuration}/`, models `tenant, integration_configuration, invoice_template_configuration` | `services/tenant-service` (Phase 1B) |
| `api/v1/{products,units}.py`, `services/products/`, models `product, unit_of_measure, product_unit_conversion, location` | `services/master-data-service` (Phase 1B) |
| `core/{correlation,error_handlers,security,exceptions}.py`, `logging/`, `middleware/` | already mirrored in `backend/shared/` (monolith not yet switched over) |
| `services/inventory`, `sales`, `purchase`, `accounting`, `gst`, `payments`, `payroll`, `reports` | stay in monolith until Outbox/compensation exist |

## Known cross-domain couplings that Phase 1B must handle
- `core/deps.py::get_current_user` reads `auth_session`, user and role/permission tables → every other module authenticates through identity data. Extraction needs either a token-introspection endpoint or a shared read model.
- Product lookups (`sales_validation_service`, `InventoryService`) are in-process calls to master-data; they stay in-process while those modules share a transaction.
- `audit_log`, `idempotency_key`, `document_number_sequence` are used by every domain (`platform_shared` owner).
