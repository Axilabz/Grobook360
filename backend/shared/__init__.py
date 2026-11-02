"""Cross-service building blocks (Phase 1A).

Everything here is framework-level and has NO business logic and NO database
access, so any service (or the gateway) can import it without coupling to
another service's domain. Business logic must never be placed in `shared`.
"""
