# Architecture

## Status and scope

This document describes the target architecture. The technical foundation now includes a FastAPI health endpoint, a Next.js home page, PostgreSQL Compose configuration, and CI. Business modules and the background worker are not implemented yet. FreelanceFlow starts with one freelancer per workspace and hourly billing.

`billing-rules.md` is authoritative for whether a business rule is CONFIRMED, PROPOSED, or UNRESOLVED. This document must not silently promote unresolved business rules.

## Modular monolith and repository layout

Use one Python backend codebase with explicit module boundaries and one PostgreSQL database. The HTTP API and background worker are execution entry points into the same application, not separate business services.

The Next.js/TypeScript frontend is a separate application in the same repository. It consumes backend contracts and supports review/editing workflows; the backend owns authoritative billing calculations and state transitions.

Target layout (only the technical foundation is scaffolded so far):

```text
backend/
  src/freelanceflow/
    modules/
      identity/
      clients/
      calendar/
      time_tracking/
      billing/
      delivery/
      audit/
    shared/
    bootstrap/
  tests/
    unit/
    integration/
    acceptance/
  migrations/
frontend/
  src/
    app/
    features/
    lib/
infrastructure/
  docker/
docs/
.github/workflows/
```

Each backend module separates `domain/`, `application/`, `adapters/`, and `api/` where needed. Keep shared code limited to genuinely common primitives; do not move business workflows into a shared utility layer.

## Modules and ownership

| Module | Responsibilities |
| --- | --- |
| Identity | Workspace, freelancer identity, authentication integration, authorization context |
| Clients | Clients, projects, tasks, and their relationships |
| Calendar | Connections, internal source-event records, synchronization, classification rules and suggestions |
| Time tracking | Editable/classifiable time entries, source reconciliation, calendar/work interval duration, local-day splitting; detailed review workflow unresolved |
| Billing | Effective-dated rates, pricing/rate-boundary splitting, billing calculations, allocations, invoice versions, lines, approvals, frozen artifacts |
| Delivery | Scheduling, provider interaction, delivery attempts and outcomes |
| Audit | Append-only records of important state changes |

## Dependency direction

Domain code has no framework or external infrastructure dependencies. Application code depends on domain code and defines the ports it needs. Adapters implement those ports. FastAPI routes call application use cases, while bootstrap code supplies concrete dependencies.

```text
API / worker entry point → application → domain
adapters → application ports and domain contracts
bootstrap → concrete composition
```

Cross-module workflows use explicit application interfaces; a generic event bus is not a default requirement. They do not import another module's private persistence implementation. Billing consumes eligible internal TimeEntry data and never Google payloads.

Time Tracking owns calendar/work interval duration and local-day splitting. Billing owns additional splitting required specifically by pricing/rate changes and reuses Time Tracking duration calculations. Do not implement duplicate duration calculations. Raw TimeEntry elapsed duration is the current MVP billable duration. Billing timezone and automatic rate-boundary segmentation remain subject to the decisions in `billing-rules.md`.

## Processing flow

```text
Google Calendar adapter
  → CalendarEvent
  → editable TimeEntry
  → Billing calculation
  → Invoice draft
  → Freelancer review and approval of exact revision and frozen artifact
  → Delivery of frozen approved artifact
```

Calendar import and classification produce internal data and suggestions. The freelancer can correct assignments and time. Source updates flag reviewed entries for reconciliation instead of silently replacing edits.

Drafts may be generated from eligible TimeEntries without individually approving every entry. Ambiguous, unclassified, or unbillable entries must block generation or be explicitly excluded. The freelancer reviews the resulting invoice before approval; the detailed TimeEntry review workflow remains unresolved.

Billing resolves effective rates, applies pricing-specific segmentation, calculates exact amounts, and records allocations and invoice snapshots. Calendar events never directly generate invoice lines.

InvoiceDraft modifications insert complete immutable revisions. A logical invoice head is
locked transactionally when allocating its next monotonically increasing revision number;
existing revision rows, lines, and allocations are never updated. The head pointer is
coordination metadata only and does not replace historical content.

Frozen invoice artifacts are immutable PostgreSQL `BYTEA` records bound by foreign key
to one exact `(invoice ID, revision, workspace)` snapshot. The application generates the
artifact UUID and creation time and derives a lowercase hexadecimal SHA-256 digest and
exact byte size from the payload. Metadata retrieval is separate from binary retrieval;
there is no mutable current-artifact pointer.

Approval is an immutable record bound to one exact invoice revision, artifact UUID, and
artifact SHA-256 snapshot. PostgreSQL serializes approval attempts on the revision and
enforces at most one approval per revision. Repeating the same exact target returns its
existing approval; a different artifact conflicts and cannot replace it. Later revisions
remain unapproved. Delivery must use the artifact corresponding to the approved revision.
Sent content and its artifact remain immutable; delivery history can accumulate separately.

A durable logical delivery in the Delivery module is bound by foreign key to one immutable approval and its exact
revision, artifact UUID, and artifact SHA-256 snapshot. Repeating a request for the same
approval returns that delivery. Workers atomically claim pending deliveries with PostgreSQL
row locking and `SKIP LOCKED`; each claim creates a new immutable attempt identity that is
required to record failure or success. A successful delivery is terminal. A later invoice
revision is a separate immutable snapshot and cannot alter the historical delivery target.

## Worker and external operations

A background worker handles calendar synchronization, document work, and scheduled email delivery through application use cases. It uses persisted jobs, retry metadata, and stable operation identifiers.

For the MVP, prefer PostgreSQL-backed durable jobs and a simple transactional outbox if needed. Do not introduce Kafka, RabbitMQ, generic event buses, event sourcing, or microservices by default. Approval state and the corresponding durable delivery request are committed consistently. Workers record attempts and outcomes. Automatic recovery of an abandoned claim remains blocked until a lease/timeout policy is confirmed.

External operations must be idempotent. The stable logical delivery UUID is available as a
future provider operation key, but this only prevents duplicates when the selected provider
honors idempotency or supports reconciliation. A provider timeout or a crash after provider
acceptance but before the database success commit leaves the attempt uncertain and in
progress; it must not be retried automatically. Do not assume a local transaction can make
a remote send atomic or claim exactly-once delivery.

## Database boundaries

- One PostgreSQL database, with module-owned tables and a coordinated migration history.
- Domain objects are independent of persistence models; adapters map between them.
- Application use cases define transactions. Use database constraints and concurrency control for uniqueness, allocation conflicts, and lifecycle transitions.
- Workspace-owned records carry an ownership boundary enforced on reads and writes.
- Every allocated TimeEntry must belong to the invoice workspace and client, have compatible project/task relationships, and match the invoice currency/rate context.
- Store money in exact numeric columns and instants as timezone-aware timestamps; retain timezone identifiers where local interpretation matters.
- Persist invoice snapshots and append-only audit records. Write audit records with associated state changes in the same transaction where applicable.
- Historical invoice content must not change when client, rate, or time-entry records change.

## External adapters

Provide replaceable adapters for Google Calendar/OAuth, PostgreSQL repositories and transactions, email delivery, and invoice rendering. Frozen artifact bytes use PostgreSQL `BYTEA` for the MVP. Provider models and credentials stay outside the domain. Tests use controlled implementations of the same ports.

Exact rendering libraries, email provider, and worker mechanism remain unresolved implementation choices. Docker Compose currently runs PostgreSQL only; GitHub Actions validates the backend and frontend in separate jobs.
