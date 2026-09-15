# Domain model

## Shared conventions

Start with one freelancer per workspace. All workspace-owned entities must be isolated from other workspaces. Entity identifiers are internal; provider identifiers are separate provenance fields.

Money uses `Decimal` with an explicit currency. Timestamps representing instants are timezone-aware; retain IANA timezone context for local-day calculations. Date-only fields are not timestamps. Proposed attributes below describe contracts, not a finalized database schema.

`billing-rules.md` is authoritative for whether a business rule is CONFIRMED, PROPOSED, or UNRESOLVED. This model must not silently promote unresolved rules.

## Entities

| Entity | Responsibility and proposed information | Relationships and invariants |
| --- | --- | --- |
| Workspace | Freelancer ownership boundary, billing identity, billing timezone, default currency | One freelancer initially; default currency does not permit mixed currencies within an invoice |
| WorkspaceBillingProfile | Current seller legal identity, entity kind, SIREN/SIRET, optional French VAT identity, structured legal and optional billing addresses, and company form/capital where applicable | Mutable one-per-workspace configuration; France-first seller address; never historical invoice truth |
| WorkspaceInvoiceSettings | Current France-first VAT regime, franchise legal basis or default VAT rate, VAT-on-debits choice, structured payment due rule, early-payment discount, late-payment penalty rate, recovery-indemnity policy, and operation category | Mutable one-per-workspace issuance defaults; VAT identity is independent; every value used must be snapshotted into future issued-invoice history |
| Client | Customer display name and ownership identity | Belongs to a workspace; display name is not legal identity and changes do not rewrite invoice snapshots |
| ClientBillingProfile | Current buyer legal name distinct from Client display name, optional trading name, structured legal and optional billing addresses, French SIREN where applicable, and optional French VAT identity | Mutable one-per-client configuration; inherits exact client/workspace ownership; never historical invoice truth |
| Project | Client work grouping, name, active status | Belongs to one client in the same workspace; may have project-specific rates |
| Task | Optional category of project work | Belongs to a project; distinct from an individual time interval |
| CalendarConnection | Connected account, selected calendars, credential reference, synchronization cursor/status | Belongs to a workspace; credential storage is protected and excluded from ordinary domain responses |
| CalendarEvent | Internal source record: provider/calendar/event identity, recurrence occurrence identity when relevant, source revision, interval or all-day dates, timezone, cancellation state | Belongs to a connection; repeat imports update the same source identity; never directly produces invoice lines |
| ClassificationRule | Matching criteria, priority, suggested client/project/task assignment | Workspace-scoped; suggestions must preserve valid client/project/task relationships; ambiguous matches require resolution |
| TimeEntry | Editable work interval, source reference if imported, client/project/task assignment, billable flag, reconciliation status, optional review metadata (workflow unresolved) | May be manual or derived from a CalendarEvent; eligible entries can generate drafts without individual approval; source changes cannot silently overwrite reviewed content; billed time is traceable through allocations |
| RateAgreement | Hourly Decimal amount, currency, client or project scope, effective start/end dates | Resolve at project level if any project rate applies, otherwise client level; conflicts only at the selected level block billing, as does a missing rate; effective-date interpretation must be explicit |
| Invoice | Billing period metadata, explicit currency precision snapshot, issuer/client snapshots, content version, exact pre-rounding subtotal, rounded totals, lifecycle information, artifact reference | One currency; tax-free MVP total is the sum of rounded lines; modifications create complete immutable revisions under one logical identity |
| InvoiceLine | Exact duration, applied hourly rate and RateAgreement identity, exact rational amount, rounded integer minor-unit amount, and source allocations | Caller-grouped compatible segments are summed exactly and rounded once using the confirmed policy; snapshots calculations rather than reading mutable current rates |
| InvoiceAllocation | Association between a billed TimeEntry segment and an invoice line, including allocated interval/quantity and provenance | Prevents duplicate billing of the same time; traces a line back to allocated work in the invoice workspace and client, with compatible project/task relationships and invoice currency/rate context; reservation/release policy remains unresolved |
| InvoiceArtifact | Application-generated identity, exact InvoiceDraft revision identity, media type, immutable bytes, exact byte size, lowercase hexadecimal SHA-256 digest, creation instant | Belongs to one workspace and one exact persisted revision; content-derived size and digest are server-authoritative; later revisions never rebind it |
| InvoiceApproval | Application-generated identity, workspace, exact invoice ID/revision, exact artifact ID/SHA-256 snapshot, approval timestamp | Immutable and unique per invoice revision; no actor is recorded before authentication exists; later revisions do not inherit it and a different artifact cannot replace it |
| InvoiceDelivery | Application-generated identity, exact immutable approval/revision/artifact/digest snapshot, requested time, provider-neutral message snapshot, state, ordered attempts | One logical delivery per approval; pending claims are atomic; the message and frozen artifact are stable across retries; provider-accepted `sent` and definitive `failed` are terminal; later revisions cannot retarget it |
| InvoiceDeliveryAttempt | Application-generated claim token, delivery identity, sequence, start/completion times, outcome, safe failure reason, optional accepted provider message ID | Append-only history; at most one open attempt per delivery; only the active token may finish the claim; provider-specific errors do not cross the adapter boundary |
| InvoiceDeliveryProviderEvent | Application-generated identity, signed provider event identity, optional provider message ID, raw and semantic event type, provider occurrence time, first receipt time, exact raw-payload SHA-256 | Immutable verified fact; signed event identity is unique; supported delivery events require a message ID; secrets, signatures, and raw payloads are not persisted |
| InvoiceDeliveryProviderEventMatch | Provider-event identity, exact delivery/workspace/provider-message identity, correlation time | Separate append-only correlation; absent for unmatched events; composite foreign keys ensure the event and accepted attempt carry the same provider message ID |
| AuditEvent | Actor, timestamp, entity/version, action, relevant change information, correlation identifier | Append-only; records important changes without secrets or unnecessary sensitive source payloads |

Issue #5 implements Task as a category belonging to exactly one Project, carrying client and workspace ownership through that project. TimeEntry explicitly carries workspace ownership, aware start/end timestamps, a billable flag, and optional client/project/task references. Classification must form a consistent ownership chain: a project requires its selected client, and a task requires its selected project, all within the entry workspace.

TimeEntry requires end strictly after start as instants. Its exact elapsed duration is a `timedelta` computed after converting both timestamps to UTC, preserving microseconds across midnight and daylight-saving transitions. Supplied timestamps retain timezone context. For the current MVP this raw elapsed duration is also billable duration. No rounding, daily splitting, overlap policy, or review/approval states are implied.

Issue #7 adds explicit immutable operations: `classify_time_entry(entry, *, client, project, task=None)` assigns or replaces the complete classification; omitting Task clears any previous Task. `clear_time_entry_classification(entry)` removes all three references. Both return new entries, rerun existing validation, and preserve timestamps, elapsed duration, and billable state. These operations add no review, approval, eligibility, or automatic classification behavior.

## Relationships and lifecycle

```text
Workspace → Client → Project → Task
Workspace → WorkspaceBillingProfile
Workspace → WorkspaceInvoiceSettings
Workspace → Client → ClientBillingProfile
Workspace → CalendarConnection → CalendarEvent → TimeEntry
Workspace → ClassificationRule → suggested TimeEntry assignment
Client / Project → RateAgreement
TimeEntry → InvoiceAllocation → InvoiceLine → Invoice content version
Invoice content version → InvoiceApproval → InvoiceDelivery → InvoiceDeliveryAttempt
Verified provider event → optional InvoiceDeliveryProviderEventMatch → InvoiceDelivery
Important changes → AuditEvent
```

A CalendarEvent and a TimeEntry are separate records with separate purposes: the former represents source data; the latter represents editable work. Exact conversion cardinality and split/merge behavior are unresolved.

Time Tracking owns calendar/work interval duration and local-day splitting. Billing owns additional splitting specifically required by pricing/rate changes, reusing Time Tracking duration calculations rather than duplicating them. Raw elapsed duration is the confirmed MVP billable duration; billing timezone and automatic rate-boundary segmentation remain unresolved in `billing-rules.md`. Whether segments are persisted is an implementation choice. Invoice allocations must preserve sufficient segment identity to prevent duplicate billing regardless of that choice.

TimeEntries may be edited and classified. Eligible entries may generate drafts without individual approval; ambiguous, unclassified, or unbillable entries must block generation or be explicitly excluded. The freelancer reviews the resulting invoice before approval. Detailed TimeEntry review semantics remain unresolved.

The local delivery lifecycle starts `pending → in_progress`. A failure known not to have
been accepted records a retryable `failed` attempt and returns the logical delivery to
`pending`; a provider rejection records `rejected` and makes the delivery terminal `failed`;
provider acceptance records `sent` with its provider message ID and makes the delivery
terminal `sent`. A timeout, network loss, generic provider server failure, or malformed
success response records an `ambiguous` attempt and deliberately remains `in_progress`.
Claiming locks one pending row with PostgreSQL `FOR UPDATE SKIP LOCKED`, persists the attempt
token in the same transaction, and permits only that token to record an outcome. All attempt
outcomes remain historical.

There is no mutable approved content to edit or invalidate: delivery references an immutable
approval, revision, artifact, and digest. A later revision and its approval are a distinct
target and never retarget an existing delivery. Sender, recipient, subject, body, and
attachment filename are provider-neutral values frozen before the first external call and
cannot change on retry. The exact stored artifact bytes and media type are supplied through
the application port to the Resend adapter. `sent` means provider acceptance, not recipient
delivery. Scheduling, deliberate resend, derived downstream status, and abandoned-claim
recovery remain unresolved.

Delivery-relevant Resend webhooks are verified over their exact raw request bytes before
parsing. The append-only provider-event history distinguishes provider accepted, recipient
mail-server delivered, delayed, bounced, provider failed, and complained facts. Unsupported
verified event types are retained without changing delivery state. Events can arrive more
than once or out of order; signed provider event identity deduplicates retries, and no
mutable downstream status is derived in this slice. A valid event without a locally known
provider message ID remains unmatched until deterministic correlation becomes possible.

Approval applies to an exact invoice revision and frozen artifact, and delivery must use that corresponding artifact. Invoice versions must retain the calculation inputs and results needed to explain the bill. Historical approvals and delivery attempts remain auditable after edits, failures, or corrections.

Legal billing profiles describe only current party configuration. `Client.name` remains a
display name and is not promoted to a legal name. Local SIREN/SIRET/French-VAT checks prove
only shape, checksum where defined, and consistency between identifiers; they do not verify
registration. A future issued invoice must snapshot the seller and buyer legal identity and
addresses it used, so later profile updates cannot change historical reconstruction.

`WorkspaceInvoiceSettings` likewise contains current defaults rather than invoice facts.
The VAT regime is explicitly either `franchise_en_base` with a structured statutory basis,
or `taxable` with an exact Decimal default VAT percentage; it is never inferred from a VAT
identification number. Payment terms preserve the selected invoice-date-based rule without
inventing an issue date or due date. The current hourly-services MVP records the electronic-
invoice operation category as services. A future issuance operation must resolve these
defaults into an immutable snapshot, including the exact rate, dates, amounts, and wording
actually placed on that invoice.

InvoiceDraft revisions are complete immutable snapshots. Revision 1 creates the logical
invoice identity; later modifications preserve its workspace, client, and currency and
insert monotonically increasing revisions without overwriting history. A current-revision
pointer is concurrency metadata, not mutable invoice content. Frozen artifacts provide a
stable identity for exact revision bytes. No approval record is valid without both that
exact revision and its artifact identity. Repeating approval of that same exact target
returns the original immutable record; approving another artifact for the revision is a
conflict. Revocation and replacement are not defined.

Issue #11 confirms that Client requires a nonblank name. Empty and Unicode
whitespace-only names are rejected; supplied nonblank names are preserved without
trimming or an arbitrary maximum length. Client remains an immutable dataclass.
Application creation generates its UUID; HTTP callers cannot supply that identifier.
