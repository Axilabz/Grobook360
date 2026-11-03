"""Idempotent-request handling (PROMPT-002 S16; API Contract S10.1).

Same key + same request fingerprint -> return the original stored result.
Same key + different fingerprint -> REG-009 / 409 IDEMPOTENCY_KEY_REUSED.
No prior record -> caller executes the operation and stores the result.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import REG_IDEMPOTENCY_CONFLICT
from app.core.exceptions import ConflictError
from app.models.idempotency_key import IdempotencyKey


def compute_fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IdempotencyCheckResult:
    existing_response: tuple[int, dict] | None  # (status_code, body) if a replay


class IdempotencyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check(self, *, idempotency_key: str, endpoint: str, payload: dict) -> IdempotencyCheckResult:
        fingerprint = compute_fingerprint(payload)
        stmt = select(IdempotencyKey).where(
            IdempotencyKey.idempotency_key == idempotency_key,
            IdempotencyKey.endpoint == endpoint,
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is None:
            return IdempotencyCheckResult(existing_response=None)

        if existing.request_fingerprint != fingerprint:
            raise ConflictError(
                "Idempotency-Key already used with a different request payload",
                code=REG_IDEMPOTENCY_CONFLICT,
            )

        return IdempotencyCheckResult(existing_response=(existing.response_status, existing.response_body))

    async def check_signup(self, *, idempotency_key: str, payload: dict) -> IdempotencyCheckResult:
        """Sign-up variant of check(): no tenant exists yet, so row-level
        security hides every idempotency row. Uses the narrow SECURITY DEFINER
        lookup (migration 0038), which is hard-wired to the sign-up endpoint."""
        row = (
            await self._session.execute(
                text("SELECT request_fingerprint, response_status, response_body FROM public.signup_idempotency_lookup(:k)"),
                {"k": idempotency_key},
            )
        ).first()
        if row is None:
            return IdempotencyCheckResult(existing_response=None)
        if row.request_fingerprint != compute_fingerprint(payload):
            raise ConflictError(
                "Idempotency-Key already used with a different request payload",
                code=REG_IDEMPOTENCY_CONFLICT,
            )
        body = row.response_body
        return IdempotencyCheckResult(existing_response=(row.response_status, json.loads(body) if isinstance(body, str) else body))

    async def store(
        self,
        *,
        idempotency_key: str,
        endpoint: str,
        payload: dict,
        tenant_id: uuid.UUID | None,
        response_status: int,
        response_body: dict,
    ) -> None:
        entry = IdempotencyKey(
            idempotency_key=idempotency_key,
            endpoint=endpoint,
            request_fingerprint=compute_fingerprint(payload),
            tenant_id=tenant_id,
            response_status=response_status,
            response_body=response_body,
        )
        self._session.add(entry)
        await self._session.flush()
