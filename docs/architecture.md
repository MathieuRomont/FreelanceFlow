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
| Billing | Current legal billing profiles, effective-dated rates, pricing/rate-boundary splitting, billing calculations, allocations, invoice versions, lines, approvals, frozen artifacts |
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

Workspace and client billing profiles are mutable Billing configuration. A workspace has at
most one current France-first seller profile and a client has at most one current buyer
profile. The latter is bound to the existing Client ownership chain but has a legal name
separate from `Client.name`. Future invoice issuance must copy all legal values it uses into
the immutable invoice revision or issuance snapshot; profile foreign keys must never be the
source of historical invoice truth.

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
required to record failure or success. Before the first provider call, the application
persists a provider-neutral snapshot of sender, recipient, subject, body, and attachment
filename. Every retry must use that same semantic message, the same frozen artifact bytes,
and the stable `invoice-delivery/<delivery UUID>` provider operation key. Provider acceptance
records the provider message identifier and makes the delivery terminal `sent`; this state
does not assert recipient delivery. A definitive rejection is terminal `failed`, a known
retryable failure returns to `pending`, and an unknown acceptance result remains
`in_progress` for reconciliation. A later invoice revision is a separate immutable snapshot
and cannot alter the historical delivery target.

Resend webhook ingestion is a separate authenticated ingress at `/webhooks/resend`.
The API reads the request body as exact bytes and passes it with `svix-id`,
`svix-timestamp`, and `svix-signature` to the official Svix verifier. Only after
verification does the Resend adapter parse and translate the payload into a minimal
provider-neutral event. Verified events and their optional delivery correlations are
stored in separate append-only tables. The first receipt time and exact raw-payload
SHA-256 are retained, while signatures, secrets, full message content, and the raw
webhook payload are not persisted.

The signed `svix-id` is the webhook deduplication identity. PostgreSQL conflict-safe
insertion makes retries and manual replays idempotent, and reuse of an identity with
different verified content is rejected. Correlation uses the exact provider message ID
stored on the accepted send attempt. Provider acceptance persistence and webhook
ingestion acquire the same transaction-scoped advisory lock for that provider message
ID, so an event arriving before or concurrently with acceptance cannot be lost between
two visibility checks. Unmatched verified events remain durable; the later acceptance
transaction or a replay can add the immutable match without modifying the event.

Provider events are downstream facts, not transitions of the local send state. In
particular, delivered, delayed, bounced, provider-failed, and complained events never
rewrite the historical fact that the provider accepted a delivery. Event arrival order
is not assumed; audit retrieval orders by provider occurrence time with stable identity
tie-breakers rather than inventing a mutable aggregate-status precedence.

## Worker and external operations

A background worker handles calendar synchronization, document work, and scheduled email delivery through application use cases. It uses persisted jobs, retry metadata, and stable operation identifiers.

For the MVP, prefer PostgreSQL-backed durable jobs and a simple transactional outbox if needed. Do not introduce Kafka, RabbitMQ, generic event buses, event sourcing, or microservices by default. Approval state and the corresponding durable delivery request are committed consistently. Workers record attempts and outcomes. Automatic recovery of an abandoned claim remains blocked until a lease/timeout policy is confirmed.

External operations must be idempotent. The Resend adapter supplies the stable logical
delivery operation key on every attempt, but Resend retains idempotency keys for a limited
period. This reduces duplicates only within the provider guarantee and does not replace
reconciliation. A provider timeout, other result that does not prove non-acceptance, or a
crash after provider acceptance but before the database success commit leaves the attempt
uncertain and in progress; it must not be retried automatically. Do not assume a local
transaction can make a remote send atomic or claim exactly-once delivery.

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

Provide replaceable adapters for Google Calendar/OAuth, PostgreSQL repositories and transactions, email delivery, and invoice rendering. Frozen artifact bytes use PostgreSQL `BYTEA` for the MVP. A narrow provider-neutral email port belongs to the Delivery application layer; the Resend HTTP adapter and environment-backed credentials belong to adapters. The adapter Base64-encodes the already-frozen bytes only for transport and never regenerates invoice content. Provider models and credentials stay outside the domain. Tests use controlled implementations of the same ports and transports.

Exact rendering libraries and the worker mechanism remain unresolved implementation choices. Resend is the first MVP transactional email adapter and its delivery-relevant webhooks are verified and retained; provider failover, polling, automatic ambiguous-send recovery, and webhook-driven marketing analytics remain out of scope. Docker Compose currently runs PostgreSQL only; GitHub Actions validates the backend and frontend in separate jobs.
