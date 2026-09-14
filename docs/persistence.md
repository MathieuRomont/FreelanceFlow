# PostgreSQL persistence

Issue #9 adds synchronous SQLAlchemy 2.x and psycopg 3 adapters. Domain dataclasses remain unchanged and never import persistence. Module-owned `adapters/models.py` files define separate ORM rows. Bootstrap collects all five models in `bootstrap/metadata.py`; shared persistence contains only the declarative base and an explicit engine factory. Imports and application startup neither connect nor create tables.

## Schema and ownership

Core tables are `clients`, `projects`, `tasks`, `rate_agreements`, and `time_entries`.
Issue #22 adds `invoice_drafts`, `invoice_lines`, and `invoice_allocations` as immutable
historical snapshots. UUIDs identify drafts and lines; a draft uses `(id, revision)` as
its key so later revisions can be inserted without overwriting prior content. Every
workspace-owned root carries `workspace_id`; there is no speculative Workspace table.
Composite foreign keys enforce nested invoice ownership and ordering, while allocations
deliberately retain source TimeEntry and RateAgreement UUIDs without foreign keys to
mutable source rows. Deleting or changing a source row therefore cannot change or prevent
reconstruction of a historical draft.

TimeEntry checks require client/project both null or both present, task absent unless project is present, and end strictly after start. Rates require a null end date or an end strictly after the start date; finite amounts reflect existing domain validation. Required attributes are non-null. Currency validation otherwise remains in the existing domain constructor.

Rates use unbounded PostgreSQL `NUMERIC` mapped to `Decimal`, without a chosen currency scale or rounding policy. PostgreSQL's native numeric size limits still apply. Validity uses `DATE`. TimeEntry instants use `TIMESTAMP WITH TIME ZONE`; mappings write UTC and separately retain each endpoint's IANA zone key when present and exact offset in microseconds. Rehydration restores IANA zones (including DST fold) or a fixed offset. Arbitrary custom tzinfo implementations retain their instant and offset, not their custom class or future transition rules. Duration is derived, never stored.

Invoice rational numerators and positive denominators use unbounded `NUMERIC` columns
with integral checks, avoiding `BIGINT` limits and preserving Python integers exactly.
Rounded amounts are integral minor units plus a currency and precision snapshot. EUR/2
is the only accepted MVP invoice currency policy. Explicit line and allocation positions
define reconstruction order; PostgreSQL row order is never used. Lines snapshot ownership
names, the complete applied-rate inputs, and derived exact/rounded results. Allocations
snapshot original and allocated intervals with timezone context, business date, source
billable state, source identity, and exact source amount.

`POST /workspaces/{workspace_id}/invoice-drafts` accepts a client and ordered groups of
source TimeEntry IDs plus prepared intervals/business dates. It does not accept IDs,
revision, rates, exact/rounded amounts, subtotal, or total. One application transaction
loads workspace-scoped source objects and rates, invokes deterministic pricing and draft
construction, assigns UUIDs and revision 1, and flushes the complete snapshot. GET and
list reconstruct only from invoice snapshot tables, ordered by stored positions. Missing
and cross-workspace drafts share the same HTTP 404 response. Draft mutation, persistence
of later revisions, approval, tax, numbering, artifacts, and delivery remain out of scope.

## API and transactions

- `ClientRepository(session, workspace_id=...)`: `add_client`, `add_project`, `add_task`, and matching `get_*` methods.
- `RateAgreementRepository(session, workspace_id=..., clients=...)`: `add(agreement_id, agreement)` and `get(agreement_id)`. The caller supplies the UUID storage identity because RateAgreement has no domain ID.
- `TimeEntryRepository(session, workspace_id=..., clients=...)`: `add(entry)` and `get(entry_id)`; `to_row(entry)` explicitly maps interval and classification fields.

`clients` implements the `ClientCatalog` application protocol; other modules do not import Clients' ORM models. Supply the catalog for the same workspace and session. Reads return a domain object or `None`; missing referenced objects raise an error. Writes reject mismatched workspace ownership and flush, but never commit or roll back. Foreign-key failures surface as SQLAlchemy `IntegrityError`; the caller must roll back after failure. Insert parents first. Repositories never cascade persistence of nested dataclasses or silently upsert existing identifiers. Updates, deletion, authorization use cases, and audit workflows are outside this initial insert/read adapter API. Workspace scoping is an adapter boundary, not a replacement for application authorization; no API routes are added.

```python
from sqlalchemy.orm import Session
from freelanceflow.shared.persistence import build_engine
from freelanceflow.modules.clients.adapters.repository import ClientRepository

engine = build_engine(database_url)
try:
    with Session(engine) as session, session.begin():
        clients = ClientRepository(session, workspace_id=authorized_workspace_id)
        clients.add_client(client)
        clients.add_project(project)
finally:
    engine.dispose()
```

## Local migrations and validation

Configure `.env` as described in the README, then from the repository root:

```sh
docker compose up -d postgres
docker compose ps
# Load your trusted local Compose configuration without printing its password.
set -a
. ./.env
set +a
export DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT:-5432}/${POSTGRES_DB}"
export TEST_DATABASE_URL="$DATABASE_URL"
cd backend
uv sync --frozen --extra dev
uv run --frozen --extra dev alembic upgrade head
uv run --frozen --extra dev ruff check .
uv run --frozen --extra dev mypy
uv run --frozen --extra dev pytest
```

URL-encode credentials containing URL-special characters when constructing the URL. The test role needs `CREATEDB`; the Compose initialization role has this capability. Tests create randomly named databases, migrate them, and drop only their own databases. They never downgrade or drop the database named in `TEST_DATABASE_URL`. An unset test URL skips integration tests; an invalid/unreachable configured URL fails. `uv run --frozen --extra dev pytest tests/unit tests/test_health.py` runs without PostgreSQL.

Alembic uses `backend/alembic.ini`, complete bootstrap metadata, and `migrations/env.py`. Revision `0001` contains explicit DDL independent of current ORM definitions, creating parent tables first and dropping dependents first. There is no `create_all()` path. `test_migration_cycle` verifies an empty PostgreSQL database, upgrade, metadata drift check, downgrade to base, re-upgrade, and another drift check. Run it alone with:

```sh
uv run --frozen --extra dev pytest tests/integration/test_persistence.py::test_migration_cycle
```

CI starts PostgreSQL 17, supplies both URLs, installs the frozen lockfile, upgrades the main CI database, and runs the same checks and disposable-database integration suite. Production migration orchestration is outside scope.

No sign policy, overlap exclusions, billing precision/rounding, timestamp-to-rate-date policy, billing eligibility, review, invoice, delivery, allocation, or retention rules are introduced.

## Client HTTP slice (issue #11)

Client names were already persisted by revision `0001`. Revision `0002` adds only
`ck_clients_nonblank_name`, using an explicit Unicode whitespace set matching Python's
`str.strip()` validation. It neither trims nor repairs rows. Existing blank names cause
upgrade to fail transactionally; correct them explicitly before retrying. Downgrade to
`0001` removes only that constraint. There is no name length limit.

`ClientService` exposes create/get/list use cases through a client-specific transaction
port, independently of HTTP. Create generates a UUID in the application. The SQLAlchemy
transaction adapter opens a session and transaction per use case, commits on successful
exit, and rolls back on failure. Repositories flush only and return immutable domain
objects. `ClientRepository.list_clients()` filters by workspace and orders by UUID.

Bootstrap supplies the service to explicit Pydantic/FastAPI boundaries:

- `POST /workspaces/{workspace_id}/clients` accepts only `name`, returning 201.
- `GET /workspaces/{workspace_id}/clients` returns a workspace-scoped array with 200.
- `GET /workspaces/{workspace_id}/clients/{client_id}` returns 200 or the same 404
  for missing and cross-workspace clients.

Responses contain `id`, `workspace_id`, and `name`. Invalid transport data and blank
names return 422. Nonblank names retain their original whitespace. `DATABASE_URL`
configures persistence at application lifespan startup; health remains available without
it. Client endpoints require database configuration. No authentication or authorization
system is introduced; explicit workspace routes provide scoping, not access control.

The PostgreSQL tests cover existing rows across upgrade/downgrade, failed upgrade with
unchanged data and revision, manual correction and retry, all Python whitespace code
points, persistence through HTTP, workspace isolation, and rollback after flushed writes.
