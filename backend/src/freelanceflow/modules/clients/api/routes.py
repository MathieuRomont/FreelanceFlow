from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from freelanceflow.modules.clients.application.clients import ClientNotFound, ClientService
from freelanceflow.modules.clients.domain import Client, InvalidClientName

router = APIRouter(prefix="/workspaces/{workspace_id}/clients", tags=["clients"])


class CreateClientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class ClientResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str

    @classmethod
    def from_client(cls, client: Client) -> "ClientResponse":
        return cls(id=client.id, workspace_id=client.workspace_id, name=client.name)


def get_client_service() -> ClientService:
    raise RuntimeError("Client service must be supplied by bootstrap")


Service = Annotated[ClientService, Depends(get_client_service)]


@router.post("", status_code=201, response_model=ClientResponse)
def create_client(
    workspace_id: UUID, body: CreateClientRequest, service: Service
) -> ClientResponse:
    try:
        client = service.create(workspace_id, body.name)
    except InvalidClientName as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return ClientResponse.from_client(client)


@router.get("", response_model=list[ClientResponse])
def list_clients(workspace_id: UUID, service: Service) -> list[ClientResponse]:
    return [ClientResponse.from_client(client) for client in service.list(workspace_id)]


@router.get("/{client_id}", response_model=ClientResponse)
def get_client(workspace_id: UUID, client_id: UUID, service: Service) -> ClientResponse:
    try:
        client = service.get(workspace_id, client_id)
    except ClientNotFound as error:
        raise HTTPException(status_code=404, detail="Client not found") from error
    return ClientResponse.from_client(client)
