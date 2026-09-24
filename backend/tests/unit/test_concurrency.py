"""Item 12 (PROMPT-001 S18): row_version mechanism can detect a stale update."""

import pytest

from app.core.concurrency import apply_mutable_update, check_row_version
from app.core.exceptions import ConcurrencyConflictError
from app.models.tenant import Tenant


async def test_row_version_starts_at_one(db_session):
    tenant = Tenant(business_name="Concurrency Test Tenant")
    db_session.add(tenant)
    await db_session.flush()
    assert tenant.row_version == 1


async def test_stale_row_version_is_detected(db_session):
    tenant = Tenant(business_name="Concurrency Test Tenant 2")
    db_session.add(tenant)
    await db_session.flush()

    stale_expected_version = tenant.row_version  # caller read version 1
    tenant.business_name = "Renamed"
    apply_mutable_update(tenant)  # simulates a concurrent update bumping it to 2
    await db_session.flush()

    with pytest.raises(ConcurrencyConflictError):
        check_row_version(tenant, stale_expected_version)


async def test_matching_row_version_passes(db_session):
    tenant = Tenant(business_name="Concurrency Test Tenant 3")
    db_session.add(tenant)
    await db_session.flush()

    check_row_version(tenant, tenant.row_version)  # should not raise
