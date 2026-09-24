"""Password recovery delivery abstraction (PROMPT-004 S28; open decision — see
PROMPT-004-NOTES.md).

No email delivery provider is approved/available in this codebase (no SMTP,
SendGrid, SES, etc.). ConsolePasswordRecoveryProvider is a dev/test-only stub:
it never actually reaches a user, and it deliberately does NOT go through the
structured application logger (PROMPT-004 S26/S27: never log a reset token) —
it writes to stdout directly and to an in-memory, test-inspectable outbox that
mirrors the "test mail outbox" pattern common frameworks use, so tests can
assert on it without the token ever touching persistent logs.

Selecting and wiring a real provider is an OPEN DECISION for product/security
sign-off, not something to silently invent here.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryOutboxEntry:
    to_email: str
    reset_link: str


class PasswordRecoveryService(ABC):
    @abstractmethod
    async def send_reset_link(self, *, to_email: str, reset_link: str) -> None: ...


class ConsolePasswordRecoveryProvider(PasswordRecoveryService):
    """Dev/test-only stub. Never use in production — see get_recovery_provider()."""

    outbox: list[RecoveryOutboxEntry] = []

    async def send_reset_link(self, *, to_email: str, reset_link: str) -> None:
        print(f"[DEV ONLY — no real provider configured] Password reset link for {to_email}: {reset_link}")
        ConsolePasswordRecoveryProvider.outbox.append(RecoveryOutboxEntry(to_email=to_email, reset_link=reset_link))


def get_recovery_provider(*, is_production: bool) -> PasswordRecoveryService:
    if is_production:
        # Fail loudly rather than silently "deliver" nothing in production —
        # a real provider decision must be made before this ships live.
        raise RuntimeError(
            "No production password-recovery delivery provider is configured. "
            "This is a documented open decision (PROMPT-004-NOTES.md) — select "
            "and wire a real provider before enabling this endpoint in production."
        )
    return ConsolePasswordRecoveryProvider()
