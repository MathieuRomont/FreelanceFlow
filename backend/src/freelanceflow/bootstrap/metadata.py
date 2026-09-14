"""Complete migration metadata; importing this module performs no database I/O."""

from freelanceflow.modules.billing.adapters.models import (
    InvoiceAllocationRow,
    InvoiceDraftHeadRow,
    InvoiceDraftRow,
    InvoiceLineRow,
    RateAgreementRow,
)
from freelanceflow.modules.clients.adapters.models import ClientRow, ProjectRow, TaskRow
from freelanceflow.modules.time_tracking.adapters.models import TimeEntryRow
from freelanceflow.shared.persistence import Base

__all__ = [
    "Base",
    "ClientRow",
    "ProjectRow",
    "TaskRow",
    "RateAgreementRow",
    "InvoiceDraftRow",
    "InvoiceDraftHeadRow",
    "InvoiceLineRow",
    "InvoiceAllocationRow",
    "TimeEntryRow",
]
