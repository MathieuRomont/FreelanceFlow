from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from freelanceflow.shared.persistence import Base


class RateAgreementRow(Base):
    __tablename__ = "rate_agreements"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "client_id"], ["clients.workspace_id", "clients.id"]),
        ForeignKeyConstraint(
            ["workspace_id", "client_id", "project_id"],
            ["projects.workspace_id", "projects.client_id", "projects.id"],
        ),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="validity"),
        CheckConstraint(
            "hourly_amount NOT IN ('NaN', 'Infinity', '-Infinity')", name="finite_rate"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    client_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    hourly_amount: Mapped[Decimal] = mapped_column(Numeric())
    currency: Mapped[str]
    valid_from: Mapped[date]
    valid_until: Mapped[date | None]
