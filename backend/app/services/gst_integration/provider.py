"""GST/NIC integration provider abstraction (PROMPT-018 §5).

The application NEVER talks to an external GST/NIC/GSP provider
directly — every call goes through `EInvoiceProvider`/`EWayBillProvider`,
so the actual provider (§43 Open Decision #1, unresolved — no provider
is approved/selected) can be swapped without touching
`einvoice_service.py`/`eway_bill_service.py` or any API route.

`SandboxSimulatorProvider` is the ONLY implementation in this codebase —
a deterministic, fully-local dev/test stub, the same "make the interface
real and testable, but never call anything external" discipline as
`ConsolePasswordRecoveryProvider` (PROMPT-004) and `NullGSTProvider`
(PROMPT-002). It never reaches a real government system. Selecting a
real provider is an explicit Open Decision requiring product/security/
legal sign-off — not something to invent here.

`force_outcome` is a test-only hook (mirrors `ConsolePasswordRecoveryProvider.
outbox`'s "inspectable/controllable in tests" pattern) letting integration
tests deterministically exercise TIMEOUT/UNAVAILABLE/AUTH_FAILED/UNKNOWN
paths without a real flaky network dependency.
"""

import base64
import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar

# --- Outcome classification (drives retry/error-code decisions in the
# service layer — §23/§30) ---

SUCCESS = "SUCCESS"
VALIDATION_FAILED = "VALIDATION_FAILED"  # permanent — never auto-retry (§23)
AUTH_FAILED = "AUTH_FAILED"  # permanent from the caller's POV — needs config fix
ALREADY_EXISTS = "ALREADY_EXISTS"  # provider says this document already has an IRN/EWB
NOT_FOUND = "NOT_FOUND"
TIMEOUT = "TIMEOUT"  # transient, but result UNKNOWN — must reconcile, not blindly retry (§24)
UNAVAILABLE = "UNAVAILABLE"  # transient — safe to retry with backoff
RATE_LIMITED = "RATE_LIMITED"  # transient — retry after configured delay

RETRYABLE_OUTCOMES = frozenset({UNAVAILABLE, RATE_LIMITED})
UNKNOWN_OUTCOMES = frozenset({TIMEOUT})


@dataclass(frozen=True)
class ProviderResult:
    outcome: str
    response_code: str | None = None
    response_message: str | None = None
    provider_reference: str | None = None
    irn: str | None = None
    ack_number: str | None = None
    ack_date: datetime | None = None
    signed_invoice_data: str | None = None
    signed_qr_data: str | None = None
    eway_bill_number: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    cancelled: bool = False

    @property
    def is_success(self) -> bool:
        return self.outcome == SUCCESS

    @property
    def is_retryable(self) -> bool:
        return self.outcome in RETRYABLE_OUTCOMES

    @property
    def is_unknown(self) -> bool:
        return self.outcome in UNKNOWN_OUTCOMES


class EInvoiceProvider(ABC):
    @abstractmethod
    async def authenticate(self) -> None: ...

    @abstractmethod
    async def generate_irn(self, *, idempotency_key: str, payload: dict) -> ProviderResult: ...

    @abstractmethod
    async def get_irn_status(self, *, irn: str | None, provider_reference: str | None) -> ProviderResult: ...

    @abstractmethod
    async def cancel_irn(self, *, irn: str, reason: str) -> ProviderResult: ...


class EWayBillProvider(ABC):
    @abstractmethod
    async def authenticate(self) -> None: ...

    @abstractmethod
    async def generate_eway_bill(self, *, idempotency_key: str, payload: dict) -> ProviderResult: ...

    @abstractmethod
    async def get_eway_bill_status(
        self, *, eway_bill_number: str | None, provider_reference: str | None
    ) -> ProviderResult: ...

    @abstractmethod
    async def cancel_eway_bill(self, *, eway_bill_number: str, reason: str) -> ProviderResult: ...


class NullEInvoiceProvider(EInvoiceProvider):
    """No provider configured. Always reports unavailable — mirrors
    `NullGSTProvider`'s discipline of never fabricating a result."""

    async def authenticate(self) -> None:
        raise RuntimeError("No E-Invoice integration provider is configured.")

    async def generate_irn(self, *, idempotency_key: str, payload: dict) -> ProviderResult:
        return ProviderResult(outcome=UNAVAILABLE, response_message="No E-Invoice provider is configured.")

    async def get_irn_status(self, *, irn: str | None, provider_reference: str | None) -> ProviderResult:
        return ProviderResult(outcome=UNAVAILABLE, response_message="No E-Invoice provider is configured.")

    async def cancel_irn(self, *, irn: str, reason: str) -> ProviderResult:
        return ProviderResult(outcome=UNAVAILABLE, response_message="No E-Invoice provider is configured.")


class NullEWayBillProvider(EWayBillProvider):
    async def authenticate(self) -> None:
        raise RuntimeError("No E-Way Bill integration provider is configured.")

    async def generate_eway_bill(self, *, idempotency_key: str, payload: dict) -> ProviderResult:
        return ProviderResult(outcome=UNAVAILABLE, response_message="No E-Way Bill provider is configured.")

    async def get_eway_bill_status(
        self, *, eway_bill_number: str | None, provider_reference: str | None
    ) -> ProviderResult:
        return ProviderResult(outcome=UNAVAILABLE, response_message="No E-Way Bill provider is configured.")

    async def cancel_eway_bill(self, *, eway_bill_number: str, reason: str) -> ProviderResult:
        return ProviderResult(outcome=UNAVAILABLE, response_message="No E-Way Bill provider is configured.")


def _deterministic_reference(prefix: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}{digest}"


class SandboxSimulatorProvider(EInvoiceProvider, EWayBillProvider):
    """Deterministic, fully-local dev/test stub for BOTH interfaces (§43
    Open Decision #1 — no real provider is approved). Never reaches any
    external system. Same IRN/reference is always produced for the same
    `idempotency_key`, so a test (or a real retry) calling this twice
    with the same key observes the same result rather than a fresh
    fabricated one — this is what makes the higher-level idempotency
    tests meaningful without a real provider's own dedup behavior to
    rely on.

    `force_outcome` (test-only): when set, the next call returns that
    outcome instead of SUCCESS, letting tests exercise TIMEOUT/
    UNAVAILABLE/AUTH_FAILED/RATE_LIMITED/UNKNOWN paths deterministically.
    Reset it between tests (see conftest-style fixtures in the test
    files that use it).
    """

    force_outcome: ClassVar[str | None] = None

    async def authenticate(self) -> None:
        # Fault injection for AUTH_FAILED is handled uniformly by
        # generate_irn/cancel_irn's own force_outcome check (so the
        # resulting ProviderResult.outcome is correctly classified,
        # rather than surfacing here as a raised exception the caller
        # would have to re-classify).
        return None

    async def generate_irn(self, *, idempotency_key: str, payload: dict) -> ProviderResult:
        if self.force_outcome:
            outcome = self.force_outcome
            return ProviderResult(outcome=outcome, response_message=f"Simulated {outcome.lower()}.")

        reference = _deterministic_reference("SIMREF", idempotency_key)
        irn = hashlib.sha256(f"IRN:{idempotency_key}".encode()).hexdigest()
        ack_number = str(int(hashlib.sha256(idempotency_key.encode()).hexdigest()[:10], 16))[:12]
        qr_payload = base64.b64encode(f"{irn}|{payload.get('invoice_number', '')}".encode()).decode()
        return ProviderResult(
            outcome=SUCCESS,
            response_code="200",
            response_message="IRN generated (sandbox simulator).",
            provider_reference=reference,
            irn=irn,
            ack_number=ack_number,
            ack_date=datetime.now(timezone.utc),
            signed_invoice_data=base64.b64encode(str(payload).encode()).decode(),
            signed_qr_data=qr_payload,
        )

    async def get_irn_status(self, *, irn: str | None, provider_reference: str | None) -> ProviderResult:
        if self.force_outcome:
            return ProviderResult(outcome=self.force_outcome)
        if irn:
            return ProviderResult(outcome=SUCCESS, irn=irn, response_message="IRN is active (sandbox simulator).")
        return ProviderResult(outcome=NOT_FOUND, response_message="No IRN found for this reference.")

    async def cancel_irn(self, *, irn: str, reason: str) -> ProviderResult:
        if self.force_outcome:
            return ProviderResult(outcome=self.force_outcome)
        return ProviderResult(outcome=SUCCESS, irn=irn, cancelled=True, response_message="IRN cancelled (sandbox simulator).")

    async def generate_eway_bill(self, *, idempotency_key: str, payload: dict) -> ProviderResult:
        if self.force_outcome:
            outcome = self.force_outcome
            return ProviderResult(outcome=outcome, response_message=f"Simulated {outcome.lower()}.")

        reference = _deterministic_reference("EWBREF", idempotency_key)
        number = str(int(hashlib.sha256(f"EWB:{idempotency_key}".encode()).hexdigest()[:12], 16))[:12]
        now = datetime.now(timezone.utc)
        return ProviderResult(
            outcome=SUCCESS,
            response_code="200",
            response_message="E-Way Bill generated (sandbox simulator).",
            provider_reference=reference,
            eway_bill_number=number,
            valid_from=now,
        )

    async def get_eway_bill_status(
        self, *, eway_bill_number: str | None, provider_reference: str | None
    ) -> ProviderResult:
        if self.force_outcome:
            return ProviderResult(outcome=self.force_outcome)
        if eway_bill_number:
            return ProviderResult(outcome=SUCCESS, eway_bill_number=eway_bill_number)
        return ProviderResult(outcome=NOT_FOUND)

    async def cancel_eway_bill(self, *, eway_bill_number: str, reason: str) -> ProviderResult:
        if self.force_outcome:
            return ProviderResult(outcome=self.force_outcome)
        return ProviderResult(outcome=SUCCESS, eway_bill_number=eway_bill_number, cancelled=True)


def get_einvoice_provider(*, is_production: bool) -> EInvoiceProvider:
    if is_production:
        # Fail loudly, same discipline as get_recovery_provider() — no
        # real provider decision has been made (§43 Open Decision #1).
        raise RuntimeError(
            "No production E-Invoice integration provider is configured. This is a "
            "documented open decision (PROMPT-018-NOTES.md) — select and wire a real "
            "GST/NIC provider before enabling this in production."
        )
    return SandboxSimulatorProvider()


def get_eway_bill_provider(*, is_production: bool) -> EWayBillProvider:
    if is_production:
        raise RuntimeError(
            "No production E-Way Bill integration provider is configured. This is a "
            "documented open decision (PROMPT-018-NOTES.md) — select and wire a real "
            "GST/NIC provider before enabling this in production."
        )
    return SandboxSimulatorProvider()


def new_idempotency_key() -> str:
    return str(uuid.uuid4())
