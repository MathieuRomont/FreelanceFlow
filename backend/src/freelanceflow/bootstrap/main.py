"""Compose HTTP and persistence without connecting during module import."""

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from freelanceflow.modules.billing.adapters.billing_profile_transactions import (
    SqlAlchemyBillingProfileTransaction,
)
from freelanceflow.modules.billing.adapters.invoice_approval_transactions import (
    SqlAlchemyInvoiceApprovalTransaction,
)
from freelanceflow.modules.billing.adapters.invoice_artifact_transactions import (
    SqlAlchemyInvoiceArtifactTransaction,
)
from freelanceflow.modules.billing.adapters.invoice_draft_transactions import (
    SqlAlchemyInvoiceDraftTransaction,
)
from freelanceflow.modules.billing.adapters.invoice_settings_transactions import (
    SqlAlchemyInvoiceSettingsTransaction,
)
from freelanceflow.modules.billing.adapters.issued_invoice_transactions import (
    SqlAlchemyInvoiceIssuanceTransaction,
)
from freelanceflow.modules.billing.adapters.transactions import (
    SqlAlchemyRateAgreementTransaction,
)
from freelanceflow.modules.billing.api.billing_profiles import (
    get_billing_profile_service,
)
from freelanceflow.modules.billing.api.billing_profiles import router as billing_profile_router
from freelanceflow.modules.billing.api.invoice_approvals import (
    get_invoice_approval_service,
)
from freelanceflow.modules.billing.api.invoice_approvals import router as invoice_approval_router
from freelanceflow.modules.billing.api.invoice_artifacts import (
    get_invoice_artifact_service,
)
from freelanceflow.modules.billing.api.invoice_artifacts import router as invoice_artifact_router
from freelanceflow.modules.billing.api.invoice_drafts import get_invoice_draft_service
from freelanceflow.modules.billing.api.invoice_drafts import router as invoice_draft_router
from freelanceflow.modules.billing.api.invoice_settings import get_invoice_settings_service
from freelanceflow.modules.billing.api.invoice_settings import router as invoice_settings_router
from freelanceflow.modules.billing.api.issued_invoices import (
    get_invoice_issuance_service,
)
from freelanceflow.modules.billing.api.issued_invoices import router as issued_invoice_router
from freelanceflow.modules.billing.api.rate_agreements import get_rate_agreement_service
from freelanceflow.modules.billing.api.rate_agreements import router as rate_agreement_router
from freelanceflow.modules.billing.application.billing_profiles import BillingProfileService
from freelanceflow.modules.billing.application.invoice_approvals import (
    InvoiceApprovalService,
)
from freelanceflow.modules.billing.application.invoice_artifacts import (
    InvoiceArtifactService,
)
from freelanceflow.modules.billing.application.invoice_drafts import InvoiceDraftService
from freelanceflow.modules.billing.application.invoice_settings import InvoiceSettingsService
from freelanceflow.modules.billing.application.issued_invoices import InvoiceIssuanceService
from freelanceflow.modules.billing.application.rate_agreements import RateAgreementService
from freelanceflow.modules.clients.adapters.repository import ClientRepository
from freelanceflow.modules.clients.adapters.transactions import SqlAlchemyClientTransaction
from freelanceflow.modules.clients.api.project_tasks import get_project_task_service
from freelanceflow.modules.clients.api.project_tasks import router as project_task_router
from freelanceflow.modules.clients.api.routes import get_client_service, router
from freelanceflow.modules.clients.application.clients import ClientService
from freelanceflow.modules.clients.application.projects_tasks import ProjectTaskService
from freelanceflow.modules.delivery.adapters.invoice_delivery_transactions import (
    SqlAlchemyInvoiceDeliveryTransaction,
)
from freelanceflow.modules.delivery.adapters.provider_event_transactions import (
    SqlAlchemyInvoiceDeliveryProviderEventTransaction,
)
from freelanceflow.modules.delivery.adapters.resend_webhooks import (
    ResendWebhookVerifier,
    load_resend_webhook_secret,
)
from freelanceflow.modules.delivery.api.invoice_deliveries import (
    get_invoice_delivery_service,
)
from freelanceflow.modules.delivery.api.invoice_deliveries import (
    router as invoice_delivery_router,
)
from freelanceflow.modules.delivery.api.provider_events import (
    get_email_provider_webhook_verifier,
    get_invoice_delivery_provider_event_service,
)
from freelanceflow.modules.delivery.api.provider_events import (
    router as invoice_delivery_provider_event_router,
)
from freelanceflow.modules.delivery.application.invoice_deliveries import (
    InvoiceDeliveryService,
)
from freelanceflow.modules.delivery.application.provider_events import (
    InvoiceDeliveryProviderEventService,
)
from freelanceflow.modules.time_tracking.adapters.repository import TimeEntryRepository
from freelanceflow.modules.time_tracking.adapters.transactions import (
    SqlAlchemyTimeEntryTransaction,
)
from freelanceflow.modules.time_tracking.api.time_entries import get_time_entry_service
from freelanceflow.modules.time_tracking.api.time_entries import router as time_entry_router
from freelanceflow.modules.time_tracking.application.time_entries import TimeEntryService
from freelanceflow.shared.persistence import build_engine


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_app(
    engine: Engine | None = None,
    *,
    invoice_clock: Callable[[], datetime] = _utc_now,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        owned_engine = None
        configured_engine = engine
        if configured_engine is None and (url := os.environ.get("DATABASE_URL")):
            owned_engine = configured_engine = build_engine(url)
        if configured_engine is not None:
            service = ClientService(SqlAlchemyClientTransaction(configured_engine))
            project_task_service = ProjectTaskService(
                SqlAlchemyClientTransaction(configured_engine)
            )
            rate_agreement_service = RateAgreementService(
                SqlAlchemyRateAgreementTransaction(configured_engine, ClientRepository)
            )
            billing_profile_service = BillingProfileService(
                SqlAlchemyBillingProfileTransaction(configured_engine, ClientRepository)
            )
            invoice_settings_service = InvoiceSettingsService(
                SqlAlchemyInvoiceSettingsTransaction(configured_engine)
            )
            time_entry_service = TimeEntryService(
                SqlAlchemyTimeEntryTransaction(configured_engine, ClientRepository)
            )
            invoice_draft_service = InvoiceDraftService(
                SqlAlchemyInvoiceDraftTransaction(
                    configured_engine, ClientRepository, TimeEntryRepository
                )
            )
            invoice_issuance_service = InvoiceIssuanceService(
                SqlAlchemyInvoiceIssuanceTransaction(
                    configured_engine, ClientRepository, TimeEntryRepository
                ),
                clock=invoice_clock,
            )
            invoice_artifact_service = InvoiceArtifactService(
                SqlAlchemyInvoiceArtifactTransaction(configured_engine)
            )
            invoice_approval_service = InvoiceApprovalService(
                SqlAlchemyInvoiceApprovalTransaction(configured_engine)
            )
            invoice_delivery_service = InvoiceDeliveryService(
                SqlAlchemyInvoiceDeliveryTransaction(configured_engine)
            )
            invoice_delivery_provider_event_service = (
                InvoiceDeliveryProviderEventService(
                    SqlAlchemyInvoiceDeliveryProviderEventTransaction(
                        configured_engine
                    )
                )
            )
            application.dependency_overrides[get_client_service] = lambda: service
            application.dependency_overrides[get_project_task_service] = (
                lambda: project_task_service
            )
            application.dependency_overrides[get_rate_agreement_service] = (
                lambda: rate_agreement_service
            )
            application.dependency_overrides[get_billing_profile_service] = (
                lambda: billing_profile_service
            )
            application.dependency_overrides[get_invoice_settings_service] = (
                lambda: invoice_settings_service
            )
            application.dependency_overrides[get_time_entry_service] = (
                lambda: time_entry_service
            )
            application.dependency_overrides[get_invoice_draft_service] = (
                lambda: invoice_draft_service
            )
            application.dependency_overrides[get_invoice_issuance_service] = (
                lambda: invoice_issuance_service
            )
            application.dependency_overrides[get_invoice_artifact_service] = (
                lambda: invoice_artifact_service
            )
            application.dependency_overrides[get_invoice_approval_service] = (
                lambda: invoice_approval_service
            )
            application.dependency_overrides[get_invoice_delivery_service] = (
                lambda: invoice_delivery_service
            )
            application.dependency_overrides[
                get_invoice_delivery_provider_event_service
            ] = lambda: invoice_delivery_provider_event_service
            if os.environ.get("RESEND_WEBHOOK_SECRET", "").strip():
                resend_webhook_verifier = ResendWebhookVerifier(
                    load_resend_webhook_secret()
                )
                application.dependency_overrides[
                    get_email_provider_webhook_verifier
                ] = lambda: resend_webhook_verifier
        try:
            yield
        finally:
            application.dependency_overrides.pop(get_client_service, None)
            application.dependency_overrides.pop(get_project_task_service, None)
            application.dependency_overrides.pop(get_rate_agreement_service, None)
            application.dependency_overrides.pop(get_billing_profile_service, None)
            application.dependency_overrides.pop(get_invoice_settings_service, None)
            application.dependency_overrides.pop(get_time_entry_service, None)
            application.dependency_overrides.pop(get_invoice_draft_service, None)
            application.dependency_overrides.pop(get_invoice_issuance_service, None)
            application.dependency_overrides.pop(get_invoice_artifact_service, None)
            application.dependency_overrides.pop(get_invoice_approval_service, None)
            application.dependency_overrides.pop(get_invoice_delivery_service, None)
            application.dependency_overrides.pop(
                get_invoice_delivery_provider_event_service, None
            )
            application.dependency_overrides.pop(
                get_email_provider_webhook_verifier, None
            )
            if owned_engine is not None:
                owned_engine.dispose()

    application = FastAPI(title="FreelanceFlow", lifespan=lifespan)
    application.include_router(router)
    application.include_router(project_task_router)
    application.include_router(rate_agreement_router)
    application.include_router(billing_profile_router)
    application.include_router(invoice_settings_router)
    application.include_router(time_entry_router)
    application.include_router(invoice_draft_router)
    application.include_router(issued_invoice_router)
    application.include_router(invoice_artifact_router)
    application.include_router(invoice_approval_router)
    application.include_router(invoice_delivery_router)
    application.include_router(invoice_delivery_provider_event_router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    return application


app = create_app()
