"""Alembic owns schema changes; URL supplied explicitly via the environment."""

import os

from alembic import context

from freelanceflow.bootstrap.metadata import Base
from freelanceflow.shared.persistence import build_engine


def run_migrations() -> None:
    url = os.environ["DATABASE_URL"]
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = build_engine(url)
        try:
            with engine.connect() as connection:
                context.configure(connection=connection, target_metadata=Base.metadata)
                with context.begin_transaction():
                    context.run_migrations()
        finally:
            engine.dispose()


run_migrations()
