"""E-Invoice / E-Way Bill applicability evaluation (PROMPT-018 §8/§18).

§8/§18 explicitly forbid inventing turnover thresholds or legal
applicability rules that have not been approved anywhere in this
codebase's source documents — and none exist. The HONEST resolution
(§53 Open Decision #4/#5, see PROMPT-018-NOTES.md) is a tenant-level
opt-in toggle (`integration_configuration.einvoice_enabled`/
`.eway_bill_enabled`) plus basic transaction-state checks (posted, not
cancelled) — NOT a fabricated legal rule engine. When a real, approved
rule set is defined, this is the ONE place it plugs in — every caller
already goes through `evaluate_einvoice_applicability`/
`evaluate_eway_bill_applicability` rather than checking `invoice.status`
inline.

`RULE_VERSION` exists so the applicability_result JSON snapshot records
which (currently trivial) rule set produced a given evaluation — §8's
own "applicability rules must be configurable/versioned" requirement.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models.integration_configuration import IntegrationConfiguration
from app.models.sales_invoice import CANCELLED as SI_CANCELLED
from app.models.sales_invoice import POSTED as SI_POSTED
from app.models.sales_invoice import SalesInvoice

RULE_VERSION = "v1-tenant-toggle-only"


@dataclass(frozen=True)
class ApplicabilityResult:
    applicable: bool
    reason: str
    rule_version: str = RULE_VERSION
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_json(self) -> dict:
        return {
            "applicable": self.applicable,
            "reason": self.reason,
            "rule_version": self.rule_version,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


def evaluate_einvoice_applicability(
    invoice: SalesInvoice, config: IntegrationConfiguration | None
) -> ApplicabilityResult:
    if invoice.status == SI_CANCELLED:
        return ApplicabilityResult(applicable=False, reason="The source invoice has been cancelled.")
    if invoice.status != SI_POSTED:
        return ApplicabilityResult(applicable=False, reason=f"Invoice is in {invoice.status} status, not POSTED.")
    if config is None or not config.is_active:
        return ApplicabilityResult(applicable=False, reason="E-Invoice integration is not configured for this tenant.")
    if not config.einvoice_enabled:
        return ApplicabilityResult(applicable=False, reason="E-Invoice generation is disabled for this tenant.")
    return ApplicabilityResult(applicable=True, reason="Invoice is posted and E-Invoice is enabled for this tenant.")


def evaluate_eway_bill_applicability(
    invoice: SalesInvoice, config: IntegrationConfiguration | None
) -> ApplicabilityResult:
    if invoice.status == SI_CANCELLED:
        return ApplicabilityResult(applicable=False, reason="The source invoice has been cancelled.")
    if invoice.status != SI_POSTED:
        return ApplicabilityResult(applicable=False, reason=f"Invoice is in {invoice.status} status, not POSTED.")
    if config is None or not config.is_active:
        return ApplicabilityResult(applicable=False, reason="E-Way Bill integration is not configured for this tenant.")
    if not config.eway_bill_enabled:
        return ApplicabilityResult(applicable=False, reason="E-Way Bill generation is disabled for this tenant.")
    return ApplicabilityResult(applicable=True, reason="Invoice is posted and E-Way Bill is enabled for this tenant.")
