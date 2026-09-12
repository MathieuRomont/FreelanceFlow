# FreelanceFlow

Freelance time tracking and invoicing. This foundation contains a FastAPI health endpoint, a Next.js home page, and local PostgreSQL. Core client, rate, and time-entry domain objects now have PostgreSQL persistence; business API routes are not implemented.

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.12.13 (matching CI); uv can install Python 3.13
- Node.js 24 and npm (see `frontend/.nvmrc`)
- Docker with Docker Compose v2

Run the following commands from the repository root unless a directory change is shown.

## Environment and PostgreSQL

```sh
cp .env.example .env
```

Set `POSTGRES_PASSWORD` in `.env` to a locally generated password. Never commit `.env`. The example intentionally has no usable password; Compose rejects missing or empty required values.

```sh
docker compose config --quiet
docker compose up -d --wait postgres
```

PostgreSQL is available on `127.0.0.1:5432`; adjust `POSTGRES_PORT` if needed. Data persists in the `postgres_data` named volume. `docker compose down` stops the service without deleting that volume. Initialization credentials apply when the data directory is first created; editing `.env` does not change an existing database password.

The root `.env` configures Compose. Persistence tools use an explicit `DATABASE_URL` with the `postgresql+psycopg` driver; the health endpoint does not connect to the database. See [persistence setup and migrations](docs/persistence.md). The frontend needs no environment variables.

## Backend

```sh
cd backend
uv python install 3.13
uv sync --frozen --extra dev
uv run --frozen --extra dev uvicorn freelanceflow.bootstrap.main:app --reload --host 127.0.0.1 --port 8000
```

`uv sync` creates `backend/.venv`; activation is not needed with `uv run`. `pyproject.toml` remains the dependency source, while `uv.lock` pins resolved runtime and development dependencies. Local setup and CI use `--frozen` to install from that lockfile without rewriting it. The `dev` extra includes pytest, Ruff, mypy, and the HTTP test client.

When intentionally changing dependencies, edit `backend/pyproject.toml`, then run `uv lock` and `uv sync --frozen --extra dev` from `backend/`. Review both files together. Use `uv lock --check` to verify that the lockfile matches the project; frozen mode alone does not check freshness. Use `uv lock --upgrade` only for an intentional dependency upgrade.

`GET http://127.0.0.1:8000/health` returns `{"status":"healthy"}`. This is process liveness, not database readiness. API documentation is at `/docs`.

## Frontend

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. To run a production build locally, use `npm run build` followed by `npm start`.

## Checks

Backend, from `backend/`:

```sh
uv run --frozen --extra dev pytest
uv run --frozen --extra dev ruff check .
uv run --frozen --extra dev mypy
```

Frontend, from `frontend/`:

```sh
npm run lint
npm run typecheck
npm run build
```

Type checking generates Next.js route types before running TypeScript, so it works before the first build. GitHub Actions runs these checks in separate backend and frontend jobs on pull requests and pushes to `main`. Unit tests need no database or provider credentials. PostgreSQL integration tests run when `TEST_DATABASE_URL` is set (required in CI), using disposable databases created and dropped by the test role. See [persistence validation](docs/persistence.md).

## Architecture

See [architecture](docs/architecture.md), [domain model](docs/domain.md), and [billing rules](docs/billing-rules.md). FastAPI wiring lives in `backend/src/freelanceflow/bootstrap/`; future business modules will remain independent of framework and provider APIs. Only PostgreSQL runs in Docker for this foundation; backend and frontend run on the host.
