"""Global Table/Grid Export Framework request schema.

`columns` is deliberately NOT a client-controllable field in M1 — every
resource always exports its own full, hand-authored allowlist (see
app/services/export/resources.py). Accepting a client-supplied column
list would reopen exactly the "request unauthorized/internal columns"
attack the source prompt's own §29 TEST 7 warns against; a per-request
column-selection feature (§9 of the source prompt, itself marked
optional) can be added later as a SUBSET filter over the existing
allowlist, never an expansion of it.
"""

from datetime import date

from pydantic import BaseModel, Field


class ExportRequest(BaseModel):
    resource: str
    format: str = Field(pattern="^(xlsx|pdf)$")
    scope: str = Field(pattern="^(CURRENT_PAGE|ALL_FILTERED)$")
    search: str | None = None
    status: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    party_id: str | None = None
    page: int = 1
    page_size: int = 25
