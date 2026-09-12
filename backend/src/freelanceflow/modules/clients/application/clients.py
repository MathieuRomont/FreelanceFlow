"""Client use cases with explicit transaction ownership and no HTTP dependencies."""

from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.clients.domain import Client


class ClientNotFound(LookupError):
    """No client exists in the requested workspace."""


class ClientStore(Protocol):
    def add_client(self, value: Client) -> None: ...
    def get_client(self, entity_id: UUID) -> Client | None: ...
    def list_clients(self) -> list[Client]: ...


class ClientTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[ClientStore]: ...


class ClientService:
    def __init__(self, transaction: ClientTransaction) -> None:
        self.transaction = transaction

    def create(self, workspace_id: UUID, name: str) -> Client:
        client = Client(uuid4(), workspace_id, name)
        with self.transaction(workspace_id) as clients:
            clients.add_client(client)
        return client

    def get(self, workspace_id: UUID, client_id: UUID) -> Client:
        with self.transaction(workspace_id) as clients:
            client = clients.get_client(client_id)
            if client is None:
                raise ClientNotFound("Client not found")
        return client

    def list(self, workspace_id: UUID) -> list[Client]:
        with self.transaction(workspace_id) as clients:
            return clients.list_clients()
