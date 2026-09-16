"""Complete migration metadata; importing this module performs no database I/O."""

from freelanceflow.modules.billing.adapters.billing_profile_models import (
    ClientBillingProfileRow,
    WorkspaceBillingProfileRow,
)
from freelanceflow.modules.billing.adapters.invoice_settings_models import (
    WorkspaceInvoiceSettingsRow,
)
from freelanceflow.modules.billing.adapters.issued_invoice_approval_models import (
    IssuedInvoiceApprovalRow,
)
from freelanceflow.modules.billing.adapters.issued_invoice_artifact_models import (
    IssuedInvoiceArtifactRow,
)
from freelanceflow.modules.billing.adapters.issued_invoice_models import (
    InvoiceNumberCounterRow,
    IssuedInvoiceAllocationRow,
    IssuedInvoiceClientRow,
    IssuedInvoiceLineRow,
    IssuedInvoiceRow,
    IssuedInvoiceSellerRow,
    IssuedInvoiceVatBreakdownRow,
)
from freelanceflow.modules.billing.adapters.models import (
    InvoiceAllocationRow,
    InvoiceApprovalRow,
    InvoiceArtifactRow,
    InvoiceDraftHeadRow,
    InvoiceDraftRow,
    InvoiceLineRow,
    RateAgreementRow,
)
from freelanceflow.modules.clients.adapters.models import ClientRow, ProjectRow, TaskRow
from freelanceflow.modules.delivery.adapters.models import (
    InvoiceDeliveryAttemptRow,
    InvoiceDeliveryProviderEventMatchRow,
    InvoiceDeliveryProviderEventRow,
    InvoiceDeliveryRow,
)
from freelanceflow.modules.time_tracking.adapters.models import TimeEntryRow
from freelanceflow.shared.persistence import Base

__all__ = [
    "Base",
    "ClientRow",
    "ProjectRow",
    "TaskRow",
    "RateAgreementRow",
    "WorkspaceBillingProfileRow",
    "ClientBillingProfileRow",
    "WorkspaceInvoiceSettingsRow",
    "InvoiceDraftRow",
    "InvoiceDraftHeadRow",
    "InvoiceDeliveryRow",
    "InvoiceDeliveryAttemptRow",
    "InvoiceDeliveryProviderEventRow",
    "InvoiceDeliveryProviderEventMatchRow",
    "InvoiceLineRow",
    "InvoiceAllocationRow",
    "InvoiceApprovalRow",
    "InvoiceArtifactRow",
    "InvoiceNumberCounterRow",
    "IssuedInvoiceRow",
    "IssuedInvoiceSellerRow",
    "IssuedInvoiceClientRow",
    "IssuedInvoiceVatBreakdownRow",
    "IssuedInvoiceLineRow",
    "IssuedInvoiceAllocationRow",
    "IssuedInvoiceArtifactRow",
    "IssuedInvoiceApprovalRow",
    "TimeEntryRow",
]
