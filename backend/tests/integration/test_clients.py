from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.clients.adapters.models import ClientRow
from freelanceflow.modules.clients.adapters.repository import ClientRepository
from freelanceflow.modules.clients.adapters.transactions import SqlAlchemyClientTransaction
from freelanceflow.modules.clients.application.clients import ClientService
from freelanceflow.modules.clients.domain import Client, Project

from .conftest import disposable_database, migrate

WHITESPACE = [chr(i) for i in range(0x110000) if chr(i).isspace()]


@pytest.mark.parametrize("name", ["", *WHITESPACE, " \t\n\u2003"])
def test_database_rejects_blank(session: Session, name: str) -> None:
    session.add(ClientRow(id=uuid4(), workspace_id=uuid4(), name=name))
    with pytest.raises(IntegrityError, match="ck_clients_nonblank_name"):
        session.flush()


def test_transaction_failure_rolls_back(database: Engine) -> None:
    transaction = SqlAlchemyClientTransaction(database)
    workspace = uuid4()
    client = Client(uuid4(), workspace, "Rollback")
    with pytest.raises(IntegrityError):
        with transaction(workspace) as clients:
            clients.add_client(client)
            clients.add_client(client)
    with transaction(workspace) as clients:
        assert clients.get_client(client.id) is None
    with pytest.raises(RuntimeError, match="after flush"):
        with transaction(workspace) as clients:
            clients.add_client(client)
            raise RuntimeError("after flush")
    service = ClientService(transaction)
    assert service.list(workspace) == []
    committed = service.create(workspace, "  Preserved\t")
    assert service.get(workspace, committed.id) == committed


def test_api(database: Engine) -> None:
    workspace, other = uuid4(), uuid4()
    path = f"/workspaces/{workspace}/clients"
    with TestClient(create_app(database)) as http:
        assert http.get(path).json() == []
        response = http.post(path, json={"name": "  Acme\t"})
        assert response.status_code == 201
        body = response.json()
        assert set(body) == {"id", "workspace_id", "name"}
        assert body["workspace_id"] == str(workspace)
        assert body["name"] == "  Acme\t"
        identifier = UUID(body["id"])
        found = http.get(f"{path}/{identifier}")
        assert found.status_code == 200 and found.json() == body
        listed = http.get(path)
        assert listed.status_code == 200 and listed.json() == [body]
        assert http.get(f"/workspaces/{other}/clients").json() == []
        missing = http.get(f"{path}/{uuid4()}")
        foreign = http.get(f"/workspaces/{other}/clients/{identifier}")
        assert missing.status_code == foreign.status_code == 404
        assert missing.json() == foreign.json() == {"detail": "Client not found"}
        for payload in [
            {}, {"name": ""}, {"name": "\t\u00a0"}, {"name": None},
            {"name": 42}, {"name": "Acme", "client_id": str(uuid4())},
            {"name": "Acme", "workspace_id": str(other)},
        ]:
            assert http.post(path, json=payload).status_code == 422
        assert http.get(f"{path}/bad-uuid").status_code == 422
        assert http.post("/workspaces/bad/clients", json={"name": "Acme"}).status_code == 422
        assert http.get(path).json() == [body]
        long_name = "x" * 10000
        assert http.post(path, json={"name": long_name}).json()["name"] == long_name
    with Session(database) as session:
        assert ClientRepository(session, workspace_id=workspace).get_client(identifier) == Client(
            identifier, workspace, "  Acme\t"
        )


def test_project_task_api_and_transaction_behavior(database: Engine) -> None:
    workspace, other = uuid4(), uuid4()
    clients_path = f"/workspaces/{workspace}/clients"
    with TestClient(create_app(database)) as http:
        client_response = http.post(clients_path, json={"name": "Acme"})
        client = client_response.json()
        projects_path = f"{clients_path}/{client['id']}/projects"
        project_response = http.post(projects_path, json={"name": "Website"})
        assert project_response.status_code == 201
        project = project_response.json()
        assert set(project) == {"id", "workspace_id", "client_id", "name"}
        assert project["workspace_id"] == str(workspace)
        assert project["client_id"] == client["id"]
        UUID(project["id"])
        assert http.get(projects_path).json() == [project]
        assert http.get(f"/workspaces/{workspace}/projects/{project['id']}").json() == project

        tasks_path = f"/workspaces/{workspace}/projects/{project['id']}/tasks"
        task_response = http.post(tasks_path, json={"name": "Design"})
        assert task_response.status_code == 201
        task = task_response.json()
        assert set(task) == {"id", "workspace_id", "client_id", "project_id", "name"}
        assert task["workspace_id"] == str(workspace)
        assert task["client_id"] == client["id"] and task["project_id"] == project["id"]
        UUID(task["id"])
        assert http.get(tasks_path).json() == [task]
        assert http.get(f"/workspaces/{workspace}/tasks/{task['id']}").json() == task

        for path in [
            f"/workspaces/{workspace}/clients/{uuid4()}/projects",
            f"/workspaces/{other}/clients/{client['id']}/projects",
            f"/workspaces/{workspace}/projects/{uuid4()}/tasks",
            f"/workspaces/{other}/projects/{project['id']}/tasks",
        ]:
            assert http.post(path, json={"name": "Invalid"}).status_code == 404
        for path in [
            f"/workspaces/{workspace}/clients/{uuid4()}/projects",
            f"/workspaces/{other}/clients/{client['id']}/projects",
            f"/workspaces/{workspace}/projects/{uuid4()}",
            f"/workspaces/{other}/projects/{project['id']}",
            f"/workspaces/{workspace}/projects/{uuid4()}/tasks",
            f"/workspaces/{other}/projects/{project['id']}/tasks",
            f"/workspaces/{workspace}/tasks/{uuid4()}",
            f"/workspaces/{other}/tasks/{task['id']}",
        ]:
            response = http.get(path)
            assert response.status_code == 404
            assert response.json() == {"detail": "Resource not found"}
        for path in [projects_path, tasks_path]:
            assert http.post(path, json={}).status_code == 422
            assert http.post(path, json={"name": "Valid", "id": str(uuid4())}).status_code == 422

    with Session(database) as session:
        repository = ClientRepository(session, workspace_id=workspace)
        stored_project = repository.get_project(UUID(project["id"]))
        stored_task = repository.get_task(UUID(task["id"]))
        assert stored_project is not None and stored_project.name == "Website"
        assert stored_task is not None and stored_task.name == "Design"
        other_repository = ClientRepository(session, workspace_id=other)
        assert other_repository.get_project(UUID(project["id"])) is None
        assert other_repository.get_task(UUID(task["id"])) is None

    transaction = SqlAlchemyClientTransaction(database)
    service = ClientService(transaction)
    rollback_client = service.create(workspace, "Rollback parent")
    project_id = uuid4()
    with pytest.raises(RuntimeError, match="after flush"):
        with transaction(workspace) as transaction_repository:
            transaction_repository.add_project(Project(project_id, rollback_client, "Rolled back"))
            raise RuntimeError("after flush")
    with transaction(workspace) as transaction_repository:
        assert transaction_repository.get_project(project_id) is None


def test_migration_existing_clients() -> None:
    with disposable_database() as engine:
        migrate(engine, "upgrade", "0001")
        identifier, workspace = uuid4(), uuid4()
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO clients (id, workspace_id, name) VALUES (:id, :ws, :name)"),
                {"id": identifier, "ws": workspace, "name": " Acme\t"},
            )
        migrate(engine, "upgrade")
        migrate(engine, "check")
        assert "ck_clients_nonblank_name" in {
            check["name"] for check in inspect(engine).get_check_constraints("clients")
        }
        migrate(engine, "downgrade", "0001")
        assert inspect(engine).get_check_constraints("clients") == []
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT name FROM clients")) == " Acme\t"
            connection.execute(text("UPDATE clients SET name = :name"), {"name": "\t\u00a0 "})
        with pytest.raises(IntegrityError, match="ck_clients_nonblank_name"):
            migrate(engine, "upgrade")
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT name FROM clients")) == "\t\u00a0 "
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
            connection.execute(text("UPDATE clients SET name = 'Corrected manually'"))
        migrate(engine, "upgrade")
        migrate(engine, "check")
        with engine.connect() as connection:
            row = connection.execute(text("SELECT id, workspace_id, name FROM clients")).one()
            assert tuple(row) == (identifier, workspace, "Corrected manually")
