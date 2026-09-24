"""Document Numbering Service (PROMPT-011).

§34/§35: final GST/financial document numbering must be server-
authoritative — never a client-generated final number, never last-write-
wins. This is the shared mechanism every future Sales document-type
prompt calls to allocate its number; none of them should implement their
own counter.

Format decision (§74 Q5-10, resolved here since nothing approved defines
one): "{PREFIX}-{FY}-{seq:04d}", e.g. "INV-2026-27-0001". Scope is
tenant + document_type + financial_year — each document type gets its own
independent sequence that resets every financial year (the FY boundary
comes from the tenant's own `financial_year_start_month`, already
established in PROMPT-002). Cancelling a document does NOT free or reuse
its number — gaps are normal and expected in GST-compliant sequential
numbering; this service never re-derives "the next free gap," only ever
increments forward. Concurrency is handled with a row-level lock (or, for
a not-yet-existing sequence row, an insert-and-retry-on-conflict) so two
simultaneous requests can never receive the same number.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.document_number_sequence import DocumentNumberSequence
from app.models.tenant import Tenant

_MAX_ATTEMPTS = 5


def get_financial_year_label(tenant: Tenant, as_of: date | None = None) -> str:
    as_of = as_of or date.today()
    start_month = tenant.financial_year_start_month
    fy_start_year = as_of.year if as_of.month >= start_month else as_of.year - 1
    fy_end_year = fy_start_year + 1
    return f"{fy_start_year}-{str(fy_end_year)[-2:]}"


class DocumentNumberingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_number(
        self, *, tenant: Tenant, document_type: str, prefix: str, as_of: date | None = None
    ) -> str:
        label = get_financial_year_label(tenant, as_of)

        for _ in range(_MAX_ATTEMPTS):
            result = await self._session.execute(
                select(DocumentNumberSequence)
                .where(
                    DocumentNumberSequence.tenant_id == tenant.id,
                    DocumentNumberSequence.document_type == document_type,
                    DocumentNumberSequence.financial_year_label == label,
                )
                .with_for_update()
            )
            sequence = result.scalar_one_or_none()

            if sequence is None:
                sequence = DocumentNumberSequence(
                    tenant_id=tenant.id, document_type=document_type, financial_year_label=label, last_number=0
                )
                try:
                    async with self._session.begin_nested():
                        self._session.add(sequence)
                        await self._session.flush()
                except IntegrityError:
                    # Another concurrent request created it first — retry
                    # the loop to SELECT ... FOR UPDATE the row it made.
                    # add() happening *inside* the failed SAVEPOINT means
                    # its rollback also detaches the pending object, so the
                    # next loop iteration starts clean (see
                    # PROMPT-011-NOTES.md for the bug this fixes).
                    continue

            sequence.last_number += 1
            await self._session.flush()
            return f"{prefix}-{label}-{sequence.last_number:04d}"

        raise ConflictError("Could not allocate a document number. Please retry.")

    async def next_number_no_fy(self, *, tenant: Tenant, document_type: str, prefix: str) -> str:
        """PROMPT-029 §6: Employee Code (and any other identifier that
        must NEVER reset annually, unlike every GST/financial document
        number `next_number` allocates) needs the identical server-
        authoritative, concurrency-safe counter — just without the
        financial-year segment/reset. Reuses `DocumentNumberSequence`
        with a constant sentinel `financial_year_label` ("ALL") instead
        of a real FY label, keeping this a genuinely separate, permanent
        sequence per tenant+document_type rather than reusing (and
        colliding with) any real FY-scoped sequence."""
        label = "ALL"

        for _ in range(_MAX_ATTEMPTS):
            result = await self._session.execute(
                select(DocumentNumberSequence)
                .where(
                    DocumentNumberSequence.tenant_id == tenant.id,
                    DocumentNumberSequence.document_type == document_type,
                    DocumentNumberSequence.financial_year_label == label,
                )
                .with_for_update()
            )
            sequence = result.scalar_one_or_none()

            if sequence is None:
                sequence = DocumentNumberSequence(
                    tenant_id=tenant.id, document_type=document_type, financial_year_label=label, last_number=0
                )
                try:
                    async with self._session.begin_nested():
                        self._session.add(sequence)
                        await self._session.flush()
                except IntegrityError:
                    continue

            sequence.last_number += 1
            await self._session.flush()
            return f"{prefix}-{sequence.last_number:06d}"

        raise ConflictError("Could not allocate a document number. Please retry.")
