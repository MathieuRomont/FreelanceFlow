# FreelanceFlow contributor instructions

## Scope and architecture

- Build a modular monolith, not microservices. Keep backend and frontend separate in one repository.
- Planned stack: Python/FastAPI, PostgreSQL, Next.js/TypeScript, Docker for local development, GitHub Actions, and pytest. These are plans, not existing infrastructure.
- Start with one freelancer per workspace, hourly billing, and one currency per invoice.
- Follow `docs/architecture.md`, `docs/domain.md`, and `docs/billing-rules.md`. `docs/billing-rules.md` is authoritative for whether a business rule is CONFIRMED, PROPOSED, or UNRESOLVED. Architecture and domain documentation must not silently promote unresolved rules; do not implement them as defaults.
- For the MVP, prefer PostgreSQL-backed durable jobs and a simple transactional outbox if needed. Do not introduce Kafka, RabbitMQ, generic event buses, event sourcing, or microservices by default.
- Keep changes scoped to the requested task. Do not install dependencies, scaffold applications, or introduce infrastructure without task authorization.

## Layer boundaries

- **Domain:** entities, value objects, calculations, and invariants. No FastAPI, persistence models, Google APIs, network access, or other external I/O. Pass time and other nondeterministic inputs explicitly.
- **Application:** use cases, authorization coordination, transaction boundaries, and interfaces for persistence and external capabilities. Depend on domain code, not concrete adapters.
- **Adapters:** implement interfaces for PostgreSQL, Google Calendar, email, and document storage or rendering. Translate external data into internal models.
- **API:** authenticate requests, validate transport input, invoke application use cases, and serialize responses. No billing calculations or direct provider workflows in routes.
- **Bootstrap:** wire concrete implementations. Background workers invoke application use cases under the same rules as API requests.
- Modules own their data and expose explicit application interfaces; do not mutate another module's tables directly.
- Time Tracking owns calendar/work interval duration and local-day splitting. Billing owns splitting required by pricing/rate changes and reuses Time Tracking duration calculations rather than duplicating them.

## Coding rules and invariants

- Use typed Python and TypeScript with explicit contracts and descriptive names. Prefer small, deterministic functions and focused modules.
- Monetary values and billing arithmetic must use Python `Decimal`, never `float`. Use exact database numeric types and decimal strings at JSON boundaries; the frontend must not independently calculate authoritative totals with JavaScript numbers.
- Use timezone-aware timestamps for instants, store them in UTC, and preserve relevant IANA timezone context. Date-only business values remain dates with a documented interpretation.
- Google Calendar events must first become internal `CalendarEvent` records, then editable `TimeEntry` records. Calendar events must never directly generate invoice lines.
- Calendar source updates must not silently overwrite reviewed time entries.
- TimeEntries may be edited and classified; eligible entries may generate invoice drafts without individual approval. The freelancer reviews the resulting invoice before approval. Ambiguous, unclassified, or unbillable entries must block generation or be explicitly excluded; the detailed TimeEntry review workflow remains unresolved.
- Allocated TimeEntries must belong to the invoice workspace and client, have compatible project/task relationships, and match the invoice currency/rate context.
- Rates are effective-dated. Resolve at the highest applicable precedence level: project if any project rate applies, otherwise client. Missing rates or multiple applicable rates at the selected level block billing; lower-level conflicts cannot block a unique project rate. Global overlap rejection at creation/edit time remains unresolved.
- Approved invoice content is versioned. Approval applies to an exact invoice revision and frozen artifact; delivery must use the artifact corresponding to that approved revision. Editing approved content invalidates approval.
- Delivery implementation is blocked until atomic claiming of an approved invoice for sending, permitted edits during delivery, and approval invalidation during sending are defined in `docs/billing-rules.md`. A pre-send approval check alone is insufficient; do not invent the concurrency policy.
- Sent invoice content is immutable. Record corrections separately; never rewrite sent content or its stored artifact.
- External operations must be idempotent. Persist operation identity and outcomes; retries must not duplicate imports or deliveries. Reconcile uncertain provider outcomes before retrying.
- Record important state changes in append-only audit records, transactionally with the change where applicable.

## Git workflow

- Inspect repository instructions, branch, status, and relevant files before editing. Preserve unrelated user changes.
- Work on the task branch; do not commit directly to `main`. Use focused branches and reviewable pull requests.
- Keep commits cohesive with descriptive messages. Commit, push, or merge only when requested or authorized by the task.
- Do not force-push, rewrite shared history, or run destructive Git commands without explicit authorization.
- Review the final diff and status; report changes, validation, and unresolved limitations.

## Testing expectations

- Use pytest for Python. Domain tests must run without FastAPI, PostgreSQL, Google, or email services.
- Test billing examples and meaningful boundaries: effective-rate changes, missing/conflicting rates, decimal rounding, midnight and daylight-saving transitions, and duplicate allocations.
- Add integration tests for persistence constraints, transactions, adapter behavior, and workspace isolation when those components exist.
- Cover approval invalidation, sent-content immutability, import reconciliation, delivery retries, and concurrent state transitions.
- Use fakes or controlled provider fixtures; routine tests must not send real client email or require production credentials.
- Run checks appropriate to the change and report what was actually run. Documentation-only tasks need read-only validation, not dependency installation or application scaffolding.

## Security

- Secrets must never be committed, including OAuth tokens, credentials, private keys, and populated environment files. Examples contain placeholders only.
- Use minimum required provider scopes and protect stored OAuth credentials with encryption and controlled access.
- Enforce workspace authorization server-side on every access path, including worker jobs. Never trust client-supplied ownership identifiers alone.
- Avoid logging tokens, sensitive calendar payloads, or unnecessary personal and billing data. Minimize imported and retained data.
- Audit approval, delivery, billing changes, and relevant access changes without putting secrets in audit records.
- Treat external input as untrusted. Validate it at boundaries and preserve invariants in application/domain operations.

## Codex efficiency

Code quality, correctness, and data safety take priority over token or compute savings.

FreelanceFlow should nevertheless avoid unnecessary model usage, repository exploration, abstraction, and computation.

### Default working approach

For normal tasks:

1. Identify the relevant files and documented rules.
2. Inspect only the code necessary to understand the change.
3. Make the smallest coherent change.
4. Update every test, migration, or document required for correctness.
5. Run focused tests while implementing.
6. Run the complete validation required by the task before declaring it safe to commit.
7. Stop when the requested task is complete.

Do not optimize token usage by skipping necessary analysis, tests, migrations, or documentation.

### Repository exploration

- Start with targeted searches and relevant files.
- Read the relevant architecture and domain documentation before changing behavior governed by it.
- Do not scan the entire repository unless the task genuinely requires it.
- Do not repeatedly inspect files that have already been understood unless new evidence requires it.
- Existing patterns may be reused only when they are consistent with AGENTS.md and documented architecture.

### Implementation

- Prefer simple, explicit implementations.
- Avoid speculative abstractions and architecture for hypothetical future requirements.
- Do not refactor unrelated code.
- Do not introduce dependencies unless they provide clear value.
- Make the smallest coherent change, not merely the smallest number of changed files.
- Preserve module boundaries and confirmed domain invariants.

### Tests and validation

During implementation:
- Prefer focused tests and checks for fast feedback.

Before declaring a change safe to commit:
- Run all validation required by the task.
- Run the relevant complete test suite when the change can affect multiple layers.
- Never skip integration or migration tests merely to save computation.
- Do not rerun expensive checks when no relevant code has changed.

### Database and migrations

- Every schema change must use the established migration mechanism.
- Do not modify an established historical migration merely to avoid creating a new migration.
- Never silently rewrite existing production data to make a migration succeed unless that behavior has been explicitly approved.
- Preserve explicit transaction boundaries and database invariants.

### High-risk areas

Treat the following as sensitive work:

- billing and monetary calculations
- rate resolution
- invoice generation, approval, correction, or delivery
- timezone and date-boundary logic
- database migrations involving existing data
- concurrency and transaction behavior
- authentication and authorization
- irreversible external actions
- idempotency and retry behavior

For sensitive work:

- correctness takes priority over token efficiency
- inspect the relevant domain and architecture rules first
- identify important invariants and failure modes explicitly
- use stronger reasoning when warranted
- include adversarial and boundary-case tests
- run complete relevant validation before safe-to-commit

If the current model or reasoning level appears insufficient for a sensitive task, explicitly recommend escalation rather than compensating with a weak implementation.

### Agent usage

- Do not spawn additional agents for routine work.
- Additional independent review is appropriate when it materially improves confidence in sensitive or complex changes.
- Do not use additional agents merely because they are available.

### Final response

Keep completion reports concise.

Report:
- what changed
- important files modified
- tests/checks performed
- unresolved issues or assumptions
- whether the change is safe to commit
