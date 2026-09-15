"""PostgreSQL transaction lock shared by send acceptance and webhooks."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_provider_message_id(session: Session, provider_message_id: str) -> None:
    """Serialize visibility and correlation for one provider message identity."""
    session.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(CAST(:provider_message_id AS text), 0)"
            ")"
        ),
        {"provider_message_id": provider_message_id},
    )
