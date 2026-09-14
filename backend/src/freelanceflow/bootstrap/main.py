"""Compose HTTP and persistence without connecting during module import."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from freelanceflow.modules.clients.adapters.transactions import SqlAlchemyClientTransaction
from freelanceflow.modules.clients.api.project_tasks import get_project_task_service
from freelanceflow.modules.clients.api.project_tasks import router as project_task_router
from freelanceflow.modules.clients.api.routes import get_client_service, router
from freelanceflow.modules.clients.application.clients import ClientService
from freelanceflow.modules.clients.application.projects_tasks import ProjectTaskService
from freelanceflow.shared.persistence import build_engine


def create_app(engine: Engine | None = None) -> FastAPI:
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
            application.dependency_overrides[get_client_service] = lambda: service
            application.dependency_overrides[get_project_task_service] = (
                lambda: project_task_service
            )
        try:
            yield
        finally:
            application.dependency_overrides.pop(get_client_service, None)
            application.dependency_overrides.pop(get_project_task_service, None)
            if owned_engine is not None:
                owned_engine.dispose()

    application = FastAPI(title="FreelanceFlow", lifespan=lifespan)
    application.include_router(router)
    application.include_router(project_task_router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    return application


app = create_app()
