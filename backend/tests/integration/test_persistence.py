from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.models import RateAgreementRow
from freelanceflow.modules.billing.adapters.repository import RateAgreementRepository
from freelanceflow.modules.billing.domain import RateAgreement
from freelanceflow.modules.clients.adapters.models import ProjectRow, TaskRow
from freelanceflow.modules.clients.adapters.repository import ClientRepository
from freelanceflow.modules.clients.domain import Client, Project, Task
from freelanceflow.modules.time_tracking.adapters.models import TimeEntryRow
from freelanceflow.modules.time_tracking.adapters.repository import TimeEntryRepository, to_row
from freelanceflow.modules.time_tracking.domain import TimeEntry

from .conftest import disposable_database, migrate


@pytest.fixture
def chain(session: Session) -> tuple[Client, Project, Task]:
    client = Client(uuid4(), uuid4(), "Client")
    project = Project(uuid4(), client, "Project")
    task = Task(uuid4(), project, "Task")
    repo = ClientRepository(session, workspace_id=client.workspace_id)
    repo.add_client(client)
    repo.add_project(project)
    repo.add_task(task)
    return client, project, task


def test_client_project_task_roundtrip(
    session: Session, chain: tuple[Client, Project, Task]
) -> None:
    client, project, task = chain
    session.expunge_all()
    repo = ClientRepository(session, workspace_id=client.workspace_id)
    assert repo.get_client(client.id) == client
    assert repo.get_project(project.id) == project
    assert repo.get_task(task.id) == task
    other = ClientRepository(session, workspace_id=uuid4())
    assert other.get_client(client.id) is None
    assert other.get_project(project.id) is None
    assert other.get_task(task.id) is None
    for value, add in [
        (client, other.add_client),
        (project, other.add_project),
        (task, other.add_task),
    ]:
        with pytest.raises(ValueError, match="Workspace"):
            add(value)  # type: ignore[operator]


@pytest.mark.parametrize("bounded", [True, False])
@pytest.mark.parametrize("project_rate", [True, False])
@pytest.mark.parametrize("amount", ["80.123456789012345678901234567890123456789", "0", "-1.2300"])
def test_rates(
    session: Session,
    chain: tuple[Client, Project, Task],
    bounded: bool,
    project_rate: bool,
    amount: str,
) -> None:
    client, project, _ = chain
    clients = ClientRepository(session, workspace_id=client.workspace_id)
    repo = RateAgreementRepository(session, workspace_id=client.workspace_id, clients=clients)
    value = RateAgreement(
        client,
        Decimal(amount),
        "EUR",
        date(2026, 1, 1),
        date(2026, 9, 1) if bounded else None,
        project if project_rate else None,
    )
    key = uuid4()
    repo.add(key, value)
    repo.add(uuid4(), value)  # Overlapping agreements are deliberately allowed.
    session.expunge_all()
    restored = repo.get(key)
    assert restored == value
    assert restored is not None
    assert str(restored.hourly_amount) == amount
    other = RateAgreementRepository(session, workspace_id=uuid4(), clients=clients)
    assert other.get(key) is None
    with pytest.raises(ValueError, match="Workspace"):
        other.add(uuid4(), value)


@pytest.mark.parametrize("classification", ["none", "project", "task"])
@pytest.mark.parametrize("billable", [True, False])
@pytest.mark.parametrize("zone", ["Europe/Paris", "fixed"])
def test_time_entries(
    session: Session,
    chain: tuple[Client, Project, Task],
    classification: str,
    billable: bool,
    zone: str,
) -> None:
    client, project, task = chain
    tz = ZoneInfo(zone) if zone != "fixed" else timezone(timedelta(hours=5, minutes=30))
    start = datetime(2026, 10, 25, 2, 45, tzinfo=tz, fold=0)
    end = (
        datetime(2026, 10, 25, 2, 45, 0, 123456, tzinfo=tz, fold=1)
        if zone != "fixed"
        else start + timedelta(days=1, microseconds=123456)
    )
    value = TimeEntry(
        uuid4(),
        client.workspace_id,
        start,
        end,
        billable,
        client if classification != "none" else None,
        project if classification != "none" else None,
        task if classification == "task" else None,
    )
    clients = ClientRepository(session, workspace_id=client.workspace_id)
    repo = TimeEntryRepository(session, workspace_id=client.workspace_id, clients=clients)
    repo.add(value)
    session.expunge_all()
    restored = repo.get(value.id)
    assert restored == value
    assert restored is not None
    assert restored.start.tzinfo == tz
    assert restored.end.tzinfo == tz
    assert restored.end.fold == value.end.fold
    assert restored.duration == value.duration
    other = TimeEntryRepository(session, workspace_id=uuid4(), clients=clients)
    assert other.get(value.id) is None
    with pytest.raises(ValueError, match="Workspace"):
        other.add(value)


@pytest.mark.parametrize(
    "client_present,project_present,task_present",
    [
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (True, False, True),
        (False, True, True),
    ],
)
@pytest.mark.parametrize("operation", ["insert", "update"])
def test_partial_classification_rejected(
    session: Session,
    chain: tuple[Client, Project, Task],
    client_present: bool,
    project_present: bool,
    task_present: bool,
    operation: str,
) -> None:
    client, project, task = chain
    start = datetime(2026, 1, 1, tzinfo=UTC)
    row = to_row(TimeEntry(uuid4(), client.workspace_id, start, start + timedelta(hours=1), True))
    if operation == "update":
        session.add(row)
        session.flush()
    row.client_id = client.id if client_present else None
    row.project_id = project.id if project_present else None
    row.task_id = task.id if task_present else None
    session.add(row)
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize(
    "case",
    [
        "project_client",
        "task_project",
        "rate_project",
        "entry_client",
        "entry_project",
        "entry_task",
        "missing_client",
    ],
)
def test_ownership_constraints(
    session: Session, chain: tuple[Client, Project, Task], case: str
) -> None:
    client, project, task = chain
    foreign = Client(uuid4(), uuid4(), "Other workspace")
    foreign_repo = ClientRepository(session, workspace_id=foreign.workspace_id)
    foreign_repo.add_client(foreign)
    other_project = Project(uuid4(), client, "Other project")
    ClientRepository(session, workspace_id=client.workspace_id).add_project(other_project)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    entry = to_row(
        TimeEntry(
            uuid4(),
            client.workspace_id,
            start,
            start + timedelta(hours=1),
            True,
            client,
            project,
            task,
        )
    )
    row: ProjectRow | TaskRow | RateAgreementRow | TimeEntryRow
    if case == "project_client":
        row = ProjectRow(
            id=uuid4(), workspace_id=client.workspace_id, client_id=foreign.id, name="Invalid"
        )
    elif case == "task_project":
        row = TaskRow(
            id=uuid4(),
            workspace_id=foreign.workspace_id,
            client_id=foreign.id,
            project_id=project.id,
            name="Invalid",
        )
    elif case == "rate_project":
        row = RateAgreementRow(
            id=uuid4(),
            workspace_id=foreign.workspace_id,
            client_id=foreign.id,
            project_id=project.id,
            hourly_amount=Decimal("80"),
            currency="EUR",
            valid_from=date(2026, 1, 1),
        )
    else:
        row = entry
        if case == "entry_client":
            entry.workspace_id = foreign.workspace_id
        elif case == "entry_project":
            entry.client_id = foreign.id
        elif case == "entry_task":
            entry.project_id = other_project.id
        else:
            entry.client_id = uuid4()
    session.add(row)
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize(
    "case", ["equal_time", "reversed_time", "equal_dates", "reversed_dates", "nan", "infinity"]
)
def test_interval_and_rate_constraints(
    session: Session, chain: tuple[Client, Project, Task], case: str
) -> None:
    client, _, _ = chain
    start = datetime(2026, 1, 1, tzinfo=UTC)
    if "time" in case:
        row = to_row(
            TimeEntry(uuid4(), client.workspace_id, start, start + timedelta(hours=1), True)
        )
        row.end = start if case == "equal_time" else start - timedelta(microseconds=1)
        session.add(row)
    else:
        rate = RateAgreementRow(
            id=uuid4(),
            workspace_id=client.workspace_id,
            client_id=client.id,
            hourly_amount=Decimal("80"),
            currency="EUR",
            valid_from=start.date(),
        )
        if "dates" in case:
            rate.valid_until = start.date() if case == "equal_dates" else date(2025, 1, 1)
        else:
            rate.hourly_amount = Decimal("NaN" if case == "nan" else "Infinity")
        session.add(rate)
    with pytest.raises(IntegrityError):
        session.flush()


def test_caller_commit_and_rollback(database: Engine) -> None:
    client = Client(uuid4(), uuid4(), "Committed")
    with Session(database) as session:
        ClientRepository(session, workspace_id=client.workspace_id).add_client(client)
        session.rollback()
    with Session(database) as session:
        repo = ClientRepository(session, workspace_id=client.workspace_id)
        assert repo.get_client(client.id) is None
        with session.begin_nested():
            repo.add_client(client)
        session.commit()
    with Session(database) as session:
        assert (
            ClientRepository(session, workspace_id=client.workspace_id).get_client(client.id)
            == client
        )
        session.execute(text("DELETE FROM clients WHERE id = :id"), {"id": client.id})
        session.commit()


def test_migration_cycle() -> None:
    with disposable_database() as engine:
        assert inspect(engine).get_table_names() == []
        migrate(engine, "upgrade")
        assert set(inspect(engine).get_table_names()) == {
            "clients",
            "projects",
            "tasks",
            "rate_agreements",
            "time_entries",
            "invoice_drafts",
            "invoice_draft_heads",
            "invoice_lines",
            "invoice_allocations",
            "invoice_artifacts",
            "invoice_approvals",
            "alembic_version",
        }
        migrate(engine, "check")
        migrate(engine, "downgrade", "base")
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
        migrate(engine, "upgrade")
        migrate(engine, "check")


def test_invoice_head_migration_backfills_existing_revision_history() -> None:
    invoice_id = uuid4()
    workspace_id = uuid4()
    client_id = uuid4()
    with disposable_database() as engine:
        migrate(engine, "upgrade", "0003")
        with engine.begin() as connection:
            for revision in (1, 2):
                connection.execute(
                    text(
                        """
                        INSERT INTO invoice_drafts (
                            id, revision, workspace_id, client_id,
                            currency, currency_decimal_places,
                            exact_subtotal_numerator, exact_subtotal_denominator,
                            subtotal_minor_units, total_minor_units
                        ) VALUES (
                            :id, :revision, :workspace_id, :client_id,
                            'EUR', 2, 0, 1, 0, 0
                        )
                        """
                    ),
                    {
                        "id": invoice_id,
                        "revision": revision,
                        "workspace_id": workspace_id,
                        "client_id": client_id,
                    },
                )
        migrate(engine, "upgrade")
        with engine.connect() as connection:
            head = connection.execute(
                text(
                    """
                    SELECT workspace_id, client_id, currency,
                           currency_decimal_places, current_revision
                    FROM invoice_draft_heads
                    WHERE id = :id
                    """
                ),
                {"id": invoice_id},
            ).one()
        assert head == (workspace_id, client_id, "EUR", 2, 2)
        migrate(engine, "check")
        migrate(engine, "downgrade", "0003")
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT count(*) FROM invoice_drafts WHERE id = :id"),
                {"id": invoice_id},
            ) == 2
