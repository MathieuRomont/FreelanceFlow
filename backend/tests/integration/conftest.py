"""Real PostgreSQL only. Each run owns a disposable database, never the URL database."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from freelanceflow.shared.persistence import build_engine


@contextmanager
def disposable_database() -> Iterator[Engine]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    admin = build_engine(url).execution_options(isolation_level="AUTOCOMMIT")
    name = "freelanceflow_test_" + uuid4().hex
    engine = build_engine(make_url(url).set(database=name).render_as_string(hide_password=False))
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            yield engine
        finally:
            engine.dispose()
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}"'))
    finally:
        admin.dispose()


def migrate(engine: Engine, action: str, revision: str = "head") -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        if action == "upgrade":
            command.upgrade(config, revision)
        elif action == "downgrade":
            command.downgrade(config, revision)
        elif action == "check":
            command.check(config)
        else:
            raise ValueError(action)


@pytest.fixture(scope="session")
def database() -> Iterator[Engine]:
    with disposable_database() as engine:
        migrate(engine, "upgrade")
        yield engine


@pytest.fixture
def session(database: Engine) -> Iterator[Session]:
    with database.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection) as session:
            yield session
        if transaction.is_active:
            transaction.rollback()
