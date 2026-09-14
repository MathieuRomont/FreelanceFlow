# Domain model

## Shared conventions

Start with one freelancer per workspace. All workspace-owned entities must be isolated from other workspaces. Entity identifiers are internal; provider identifiers are separate provenance fields.

Money uses `Decimal` with an explicit currency. Timestamps representing instants are timezone-aware; retain IANA timezone context for local-day calculations. Date-only fields are not timestamps. Proposed attributes below describe contracts, not a finalized database schema.

`billing-rules.md` is authoritative for whether a business rule is CONFIRMED, PROPOSED, or UNRESOLVED. This model must not silently promote unresolved rules.

## Entities

| Entity | Responsibility and proposed information | Relationships and invariants |
| --- | --- | --- |
| Workspace | Freelancer ownership boundary, billing identity, billing timezone, default currency | One freelancer initially; default currency does not permit mixed currencies within an invoice |
| Client | Customer name, billing details, recipients, payment terms | Belongs to a workspace; changes do not rewrite invoice snapshots |
| Project | Client work grouping, name, active status | Belongs to one client in the same workspace; may have project-specific rates |
| Task | Optional category of project work | Belongs to a project; distinct from an individual time interval |
| CalendarConnection | Connected account, selected calendars, credential reference, synchronization cursor/status | Belongs to a workspace; credential storage is protected and excluded from ordinary domain responses |
| CalendarEvent | Internal source record: provider/calendar/event identity, recurrence occurrence identity when relevant, source revision, interval or all-day dates, timezone, cancellation state | Belongs to a connection; repeat imports update the same source identity; never directly produces invoice lines |
| ClassificationRule | Matching criteria, priority, suggested client/project/task assignment | Workspace-scoped; suggestions must preserve valid client/project/task relationships; ambiguous matches require resolution |
| TimeEntry | Editable work interval, source reference if imported, client/project/task assignment, billable flag, reconciliation status, optional review metadata (workflow unresolved) | May be manual or derived from a CalendarEvent; eligible entries can generate drafts without individual approval; source changes cannot silently overwrite reviewed content; billed time is traceable through allocations |
| RateAgreement | Hourly Decimal amount, currency, client or project scope, effective start/end dates | Resolve at project level if any project rate applies, otherwise client level; conflicts only at the selected level block billing, as does a missing rate; effective-date interpretation must be explicit |
| Invoice | Billing period metadata, explicit currency precision snapshot, issuer/client snapshots, content version, exact pre-rounding subtotal, rounded totals, lifecycle information, artifact reference | One currency; tax-free MVP total is the sum of rounded lines; immutable revision-1 drafts are persisted, while edits, approval, and artifacts are later work |
| InvoiceLine | Exact duration, applied hourly rate and RateAgreement identity, exact rational amount, rounded integer minor-unit amount, and source allocations | Caller-grouped compatible segments are summed exactly and rounded once using the confirmed policy; snapshots calculations rather than reading mutable current rates |
| InvoiceAllocation | Association between a billed TimeEntry segment and an invoice line, including allocated interval/quantity and provenance | Prevents duplicate billing of the same time; traces a line back to allocated work in the invoice workspace and client, with compatible project/task relationships and invoice currency/rate context; reservation/release policy remains unresolved |
| InvoiceApproval | Approving freelancer, timestamp, invoice content version, artifact identity | Authorizes an exact invoice revision and frozen artifact; delivery must use the artifact corresponding to that revision; retained as history when later content changes invalidate it |
| DeliveryJob | Invoice version/artifact, recipients, scheduled instant, operation identity, job status | Requires valid approval before sending; must not send stale content; rescheduling and recipient-change rules need definition |
| DeliveryAttempt | Job reference, attempt time, provider request/message identifiers, outcome, sanitized error metadata | Distinguishes accepted, failed, and uncertain outcomes; attempts do not mutate sent invoice content |
| AuditEvent | Actor, timestamp, entity/version, action, relevant change information, correlation identifier | Append-only; records important changes without secrets or unnecessary sensitive source payloads |

Issue #5 implements Task as a category belonging to exactly one Project, carrying client and workspace ownership through that project. TimeEntry explicitly carries workspace ownership, aware start/end timestamps, a billable flag, and optional client/project/task references. Classification must form a consistent ownership chain: a project requires its selected client, and a task requires its selected project, all within the entry workspace.

TimeEntry requires end strictly after start as instants. Its exact elapsed duration is a `timedelta` computed after converting both timestamps to UTC, preserving microseconds across midnight and daylight-saving transitions. Supplied timestamps retain timezone context. For the current MVP this raw elapsed duration is also billable duration. No rounding, daily splitting, overlap policy, or review/approval states are implied.

Issue #7 adds explicit immutable operations: `classify_time_entry(entry, *, client, project, task=None)` assigns or replaces the complete classification; omitting Task clears any previous Task. `clear_time_entry_classification(entry)` removes all three references. Both return new entries, rerun existing validation, and preserve timestamps, elapsed duration, and billable state. These operations add no review, approval, eligibility, or automatic classification behavior.

## Relationships and lifecycle

```text
Workspace → Client → Project → Task
Workspace → CalendarConnection → CalendarEvent → TimeEntry
Workspace → ClassificationRule → suggested TimeEntry assignment
Client / Project → RateAgreement
TimeEntry → InvoiceAllocation → InvoiceLine → Invoice content version
Invoice content version → InvoiceApproval → DeliveryJob → DeliveryAttempt
Important changes → AuditEvent
```

A CalendarEvent and a TimeEntry are separate records with separate purposes: the former represents source data; the latter represents editable work. Exact conversion cardinality and split/merge behavior are unresolved.

Time Tracking owns calendar/work interval duration and local-day splitting. Billing owns additional splitting specifically required by pricing/rate changes, reusing Time Tracking duration calculations rather than duplicating them. Raw elapsed duration is the confirmed MVP billable duration; billing timezone and automatic rate-boundary segmentation remain unresolved in `billing-rules.md`. Whether segments are persisted is an implementation choice. Invoice allocations must preserve sufficient segment identity to prevent duplicate billing regardless of that choice.

TimeEntries may be edited and classified. Eligible entries may generate drafts without individual approval; ambiguous, unclassified, or unbillable entries must block generation or be explicitly excluded. The freelancer reviews the resulting invoice before approval. Detailed TimeEntry review semantics remain unresolved.

The invoice lifecycle includes draft, approval, and sent content. Scheduling and provider outcomes belong to delivery records. Exact status enums and failure/recovery transitions are unresolved; no transition may bypass freelancer approval or rewrite sent content.

Delivery implementation is blocked until atomic claiming of an approved invoice for sending, permitted edits during delivery, and approval invalidation during sending are defined. A pre-send approval check alone is insufficient; the concurrency policy remains unresolved.

Approval applies to an exact invoice revision and frozen artifact, and delivery must use that corresponding artifact. Invoice versions must retain the calculation inputs and results needed to explain the bill. Historical approvals and delivery attempts remain auditable after edits, failures, or corrections.

Issue #11 confirms that Client requires a nonblank name. Empty and Unicode
whitespace-only names are rejected; supplied nonblank names are preserved without
trimming or an arbitrary maximum length. Client remains an immutable dataclass.
Application creation generates its UUID; HTTP callers cannot supply that identifier.
