from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest

from freelanceflow.modules.clients.application.clients import (
    ClientNotFound,
    ClientService,
    ClientStore,
)
from freelanceflow.modules.clients.domain import Client, InvalidClientName


@pytest.mark.parametrize("name", ["", " ", "\t\r\n", "\u00a0", "\u2003", "\u001c"])
def test_blank_names(name: str) -> None:
    with pytest.raises(InvalidClientName):
        Client(uuid4(), uuid4(), name)


def test_preserved_immutable_name() -> None:
    client = Client(uuid4(), uuid4(), "  Acme\t")
    assert client.name == "  Acme\t"
    with pytest.raises(FrozenInstanceError):
        client.name = "Changed"  # type: ignore[misc]


class MemoryClients:
    def __init__(self) -> None:
        self.values: dict[UUID, Client] = {}
        self.workspace_id = uuid4()

    def add_client(self, value: Client) -> None:
        self.values[value.id] = value

    def get_client(self, entity_id: UUID) -> Client | None:
        value = self.values.get(entity_id)
        return value if value and value.workspace_id == self.workspace_id else None

    def list_clients(self) -> list[Client]:
        return [v for v in self.values.values() if v.workspace_id == self.workspace_id]


def test_application_without_http() -> None:
    store = MemoryClients()
    exits: list[bool] = []

    @contextmanager
    def transaction(workspace_id: UUID) -> Iterator[ClientStore]:
        store.workspace_id = workspace_id
        try:
            yield store
        except ClientNotFound:
            exits.append(False)
            raise
        else:
            exits.append(True)

    service = ClientService(transaction)
    workspace = uuid4()
    assert service.list(workspace) == []
    first = service.create(workspace, " Acme ")
    second = service.create(workspace, "Acme")
    assert isinstance(first.id, UUID) and first.id != second.id
    assert first.name == " Acme "
    assert service.get(workspace, first.id) == first
    assert service.list(workspace) == [first, second]
    assert service.list(uuid4()) == []
    for scope, identifier in [(workspace, uuid4()), (uuid4(), first.id)]:
        with pytest.raises(ClientNotFound, match="Client not found"):
            service.get(scope, identifier)
        assert exits[-1] is False
    before = len(exits)
    with pytest.raises(InvalidClientName):
        service.create(workspace, " ")
    assert len(exits) == before
