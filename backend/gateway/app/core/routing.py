"""Route table: which service owns which URL space.

Keys are paths RELATIVE to /api/v1 (existing API contract, unchanged).
Longest matching prefix wins; anything unlisted is served by "monolith".
Phase 1A points every service at the monolith (see config.service_urls); in
Phase 1B only the Identity/Tenant/Master-Data entries get their own URL.

Sales / Inventory / Accounting / GST deliberately remain one transactional
unit (served by the monolith) until Outbox + compensation are designed.
"""

MONOLITH = "monolith"

ROUTE_TABLE: dict[str, str] = {
    # identity
    "auth": "identity",
    "users": "identity",
    "roles": "identity",
    "permissions": "identity",
    # tenant
    "tenant": "tenant",
    "configuration": "tenant",
    # master data
    "products": "master-data",
    "units": "master-data",
    # inventory
    "inventory": "inventory",
    # sales
    "customers": "sales",
    "sales": "sales",
    "eway-bills": "sales",
    "integration": "sales",
    # purchase
    "suppliers": "purchase",
    "purchase": "purchase",
    # accounting (receipts/payments post journals in the same transaction)
    "accounting": "accounting",
    "customer-receipts": "accounting",
    "supplier-payments": "accounting",
    # gst
    "gst": "gst",
    # analytics (read-only)
    "reports": "analytics",
    "analysis": "analytics",
    "exports": "analytics",
    "parties": "analytics",
}


def resolve_service(relative_path: str) -> str:
    """Return the owning service name for a path relative to /api/v1."""
    segments = [s for s in relative_path.strip("/").split("/") if s]
    for length in range(len(segments), 0, -1):
        service = ROUTE_TABLE.get("/".join(segments[:length]))
        if service:
            return service
    return MONOLITH


def resolve_upstream(relative_path: str, service_urls: dict[str, str], monolith_url: str) -> tuple[str, str]:
    """Return (service_name, base_url) for a request path."""
    service = resolve_service(relative_path)
    return service, (service_urls.get(service) or monolith_url).rstrip("/")
