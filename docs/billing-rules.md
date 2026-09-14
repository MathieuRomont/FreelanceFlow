# Billing rules

## Status

This document is the authoritative source for whether a business rule is CONFIRMED, PROPOSED, or UNRESOLVED. Architecture and domain documentation must not silently promote unresolved rules. An unresolved decision is not an implementation default. Settle affected decisions with concrete examples before implementing that behavior.

## CONFIRMED rules

### Scope and work capture

- Start with one freelancer per workspace and hourly billing.
- Import Google Calendar data into internal CalendarEvent records, then convert it into editable TimeEntries.
- Calendar events must never directly generate invoice lines. Billing uses eligible internal TimeEntries.
- TimeEntries may be edited and classified. Invoice drafts may be generated without individually approving every TimeEntry.
- Ambiguous, unclassified, or unbillable entries must block draft generation or be explicitly excluded. They must not be silently included or omitted. The detailed eligibility and exclusion workflow remains unresolved.
- Identify clients, projects, and tasks while allowing freelancer correction.
- Calculate worked time day by day with explicit timezone context.
- Calendar source updates must not silently overwrite reviewed TimeEntries. Surface discrepancies for reconciliation.
- The freelancer reviews the resulting invoice before approval. Manual review and explicit invoice approval are required before client delivery; the detailed TimeEntry review workflow remains unresolved.

### Task and TimeEntry intervals (issue #5)

- A Task belongs to exactly one Project, inheriting its client and workspace ownership.
- A TimeEntry belongs to one Workspace and may be unclassified or linked to a Client, Project, and optional Task. A selected Client must belong to that workspace; a selected Project requires that Client and must belong to it; a selected Task requires that Project and must belong to it.
- A TimeEntry can be marked billable or non-billable; this flag does not define billing eligibility or review state.
- Start and end must be timezone-aware instants, with end strictly after start.
- TimeEntry duration is exact elapsed time between instants, including across daylight-saving transitions, without float conversion. The domain implementation uses `timedelta` to preserve timestamp microseconds and retains the supplied timezone context.
- For the current MVP, raw exact `TimeEntry.duration` is the billable duration. There are no break, pause, or manual duration-adjustment rules. Future adjustments require a separately confirmed policy and must not be anticipated.
- These interval rules do not define future duration adjustments, rounding, daily segmentation, overlaps, all-day events, or review/approval workflows.

### Manual TimeEntry classification (issue #7)

- Entries are either completely unclassified (no Client, Project, or Task) or assigned a Client and Project together, with an optional Task, preserving the ownership chain above. Client-only and project-only classifications are invalid.
- Reclassification and clearing all classification are allowed.
- Classification preserves start, end, exact elapsed duration, and the billable flag.
- Billable state is independent of classification. Classification introduces no review, approval, billing eligibility, or automatic assignment behavior.

### Money and effective rates

- Use Decimal, never float, for monetary values and billing calculations. Do not introduce float conversions at persistence or API boundaries.
- Each invoice has exactly one currency. Do not silently combine currencies or convert between them.
- Rates are effective-dated and may differ by client, project, and date.
- Determine the highest applicable precedence level first. Project-level rates take precedence over client-level rates.
- If one or more applicable project rates exist, resolve only at project level. More than one applicable project rate is a conflict.
- If no project rate applies, resolve at client level. More than one applicable client rate is a conflict.
- A lower-precedence conflict must not block a unique higher-precedence applicable rate.
- Missing rates or conflicts at the highest applicable precedence level block billing of the affected time. Do not substitute zero or arbitrarily select one.
- Pre-invoice pricing preserves the exact unrounded monetary result derived from duration microseconds and the exact Decimal hourly rate. A billing-specific rational representation may be used when the result is not a terminating Decimal. The pricing engine does not perform invoice quantization; the confirmed tax-free MVP Invoice Draft policy is defined below.
- For tax-free MVP invoice drafts, aggregate exact `PricedSegment` durations and rational amounts into caller-defined logical lines before rounding. Round exactly once per line using explicit `ROUND_HALF_UP`; this is a FreelanceFlow product/accounting policy and not an implicit Decimal-context default. Do not round individual source segments.
- The current invoice-draft application policy supports EUR with two decimal places. Currency precision is selected from the application's supported-currency policy and snapshotted into the draft; callers cannot supply a replacement precision, unknown currencies are rejected, and two decimal places must not be inferred for currencies generally.
- The rounded invoice subtotal is the sum of rounded line amounts. While taxes are absent, total equals subtotal. Preserve the separately summed exact pre-rounding invoice aggregate; do not independently round it and reconcile a residual against displayed lines.
- RateAgreement validity uses half-open date intervals `[valid_from, valid_until)`: the start is inclusive, the end is exclusive, and a null end means open-ended.
- The rate resolver receives an already-interpreted business date. Timezone and timestamp-to-business-date conversion are outside issue #3 and remain unresolved.
- Conflicts at the selected precedence level raise an explicit domain error during resolution. This does not decide whether overlaps should be rejected globally when agreements are created or edited.
- Confirmed example: Rate A runs from 2026-01-01 to 2026-09-01; Rate B starts 2026-09-01 with no end. August 31 resolves A; September 1 resolves B. A client rate of 80 EUR/hour resolves to 80; an applicable project rate of 100 EUR/hour overrides it. Missing rates and conflicts at the selected precedence level raise explicit domain errors. A unique project rate of 100 EUR/hour still resolves when applicable client rates of 80 and 90 EUR/hour overlap.

### Invoice content and approval

- Draft invoices originate from eligible TimeEntries through billing calculations and allocations.
- Allocated TimeEntries must belong to the same workspace and client as the invoice, have compatible project/task relationships, and match the invoice currency/rate context.
- For the initial pure Invoice Draft domain, callers explicitly select which `PricedSegment`s form each logical line. Every segment in one line must share workspace, client, project, task, currency, RateAgreement identity, and exact hourly rate. No grouping by description, source title, date, or other presentation field is implied.
- Each line retains an allocation to every source priced segment. Duplicate source-segment allocations and overlapping allocations from the same TimeEntry are invalid because they would bill the same source interval twice. Overlapping intervals from distinct TimeEntries remain permitted; the broader work-overlap policy is unresolved.
- Preserve the time provenance, applied rates, quantities, amounts, and customer/issuer details needed to explain historical invoice content.
- Persisted InvoiceDraft content is immutable. A modification creates a complete new revision under the same logical invoice ID, workspace, client, and currency. Revision numbers increase monotonically from 1; prior revisions remain unchanged and reconstructible.
- A frozen InvoiceArtifact belongs to one workspace and one exact persisted InvoiceDraft revision. Its application-generated UUID, nonblank media type, exact nonempty byte payload, creation instant, exact byte size, and lowercase hexadecimal SHA-256 digest are immutable. The server derives the digest and size from the bytes; later invoice revisions never alter the binding.
- Frozen artifact bytes are stored in PostgreSQL `BYTEA` for the MVP. Metadata and exact binary content are retrieved separately, and a stored media type does not assert that the bytes are a valid document of that type. There is no mutable latest/current artifact pointer.
- Approved invoice content is versioned. Approval applies to an exact invoice revision and frozen artifact. This is a confirmed architectural rule: delivery must use the artifact corresponding to that approved revision.
- One immutable approval may exist per exact invoice revision. It snapshots the artifact UUID and lowercase SHA-256 and is valid only when both match an artifact already bound to that revision and workspace. No approving actor is recorded before authentication exists.
- Repeating approval of the same exact `(invoice ID, revision, artifact ID, artifact SHA-256)` target returns the original approval unchanged. This target-specific behavior does not establish a general request-idempotency framework. Attempting to approve a different artifact for an already-approved revision is a conflict and cannot revoke or replace history.
- Creating or editing content produces a later revision that is unapproved; approval is never inherited. Historical approval of an earlier revision remains intact.
- Scheduled work must not bypass an invalidated approval. A pre-send eligibility check alone is insufficient; delivery implementation is blocked pending the concurrency decisions below.
- Sent invoice content and its delivered artifact remain immutable. Later changes to clients, rates, or source time must not rewrite them.
- Corrections to sent invoices must use separate linked records; the legal document/process is unresolved.

### Reliability and audit

- External operations must be idempotent, including repeat imports and delivery retries.
- Keep stable operation identifiers and durable attempt history. Uncertain email outcomes require reconciliation before a retry that could duplicate delivery.
- Prevent the same work from being billed more than once, including concurrent draft operations. Allocation reservation and release details remain unresolved.
- Audit important changes: time review/editing, rate changes, invoice changes, approval/invalidation, scheduling, and sending.
- Use timezone-aware timestamps for instants. Preserve local timezone context; business dates such as invoice dates remain date-only values.

### Confirmed architectural ownership

- Time Tracking owns calendar/work interval duration and local-day splitting.
- Billing owns splitting required specifically by pricing/rate-boundary changes and reuses Time Tracking duration calculations; do not duplicate duration calculations.
- Ownership is confirmed; billing timezone conversion and splitting work across rate boundaries remain unresolved below.

## PROPOSED rules requiring confirmation

- Use deterministic classification suggestions initially. Ambiguous/unclassified entries remain subject to the confirmed blocking or explicit-exclusion rule.

Document format and rendering details remain open; approval of an exact revision and frozen artifact is confirmed.

The pure Invoice Draft scope does not implement VAT or tax calculation, legal invoice
numbering, negative-invoice or credit-note semantics, delivery, corrections,
PDF rendering, billing-period membership, or automatic line descriptions.
Their rules remain unresolved or belong to later explicitly scoped work.

## UNRESOLVED decisions

Delivery implementation is blocked until all three of these policies are defined:

- Atomic claiming of an approved invoice for sending.
- What edits are allowed while delivery is in progress.
- How approval invalidation interacts with sending.

Do not infer a final concurrency policy from the outbox, worker, or pre-send eligibility check. Those mechanisms alone do not resolve the send/edit race.

Invoice approval now binds the immutable revision and exact artifact atomically. Revocation,
replacement, and any actor identity remain undefined and must not be inferred.

| Decision | Questions to settle before implementation |
| --- | --- |
| Billing timezone | Is it fixed per workspace? How are timezone changes handled historically? Are rate dates interpreted in the same timezone? |
| Future duration adjustments | Raw TimeEntry elapsed duration is the confirmed MVP billable duration. Any future break, pause, or manual adjustment behavior requires a new confirmed rule. |
| Tax and later monetary rounding | Tax-free MVP invoice lines use the confirmed EUR precision, line-level `ROUND_HALF_UP`, and sum-of-rounded-lines policy above. Tax calculation and its line/subtotal/total reconciliation policy remain UNRESOLVED. Other currencies require an explicitly confirmed supported precision before use. |
| Rate boundaries | Automatic pricing-boundary segmentation is blocked by the unresolved billing-timezone/business-date policy. Date-range inclusivity and open-ended agreements are confirmed above; callers may provide already-prepared segments with an explicit business date. |
| Rate edits and validation | Resolution rejects conflicts only at the highest applicable precedence level. Whether overlapping agreements should be rejected globally at creation/edit time remains UNRESOLVED. How do backdated changes affect existing drafts and approvals? Are zero/negative rates allowed? |
| Time review and eligibility | What optional TimeEntry review workflow is needed? Which edits affect eligibility? When do ambiguous, unclassified, or unbillable entries block generation versus get explicitly excluded, and how is exclusion shown? Individual entry approval is not required to generate a draft. |
| Overlap and all-day events | How are overlapping work intervals resolved? Are all-day events excluded or manually converted? |
| Source reconciliation | How do cancellation, deletion, recurrence changes, entry splits/merges, and edits to already billed source events behave? |
| Billing periods and presentation grouping | Are periods date-inclusive or half-open? Billing-period metadata must not determine allocation membership yet. Caller-defined compatible segment groups are confirmed for the pure draft domain, but automatic grouping and line descriptions by task, day, project, title, or other presentation fields remain UNRESOLVED. |
| Allocations | Do drafts reserve time? When is a reservation released? Is partial billing supported, and how are overlaps prevented transactionally? |
| Additional currencies | EUR with two decimal places is confirmed for MVP invoice drafts. Which additional currencies are supported and what authoritative precision does each use? Currency mismatches are rejected rather than converted or silently split. |
| Tax and legal scope | What is the launch jurisdiction? Which tax modes, required invoice fields, numbering rules, and retention periods apply? These require separate validation. |
| Numbering and dates | When is an invoice number assigned? How are numbering scope, issue dates, due dates, and voided numbers handled? |
| Approval and delivery edits | Define atomic claiming for sending, allowed edits during delivery, and approval invalidation during sending before implementing delivery. Do changes to recipients, schedule, or email text require new approval? |
| Meaning of sent | Does sent mean provider acceptance? How are delivery confirmation, bounce, unknown outcomes, cancellation, and deliberate resend represented? |
| Corrections | Which correction documents and links are required? How are credits or adjustments allocated without rewriting sent content? |
| Negative invoice amounts | Rate resolution and exact pricing do not reject negative rates, but their meaning on an InvoiceDraft and all credit-note behavior remain UNRESOLVED. Do not treat `ROUND_HALF_UP` for ordinary positive invoice lines as a legal negative-invoice or credit-note policy. |
| Retention and deletion | What source data can be deleted while preserving required invoice provenance, audit records, and protected personal data? |
| Artifact request idempotency | Repeating a freeze request currently creates another immutable artifact, even for identical bytes; identical bytes have the same SHA-256 but distinct UUIDs. Define an explicit operation identity before changing this behavior. Global content deduplication is not implied. |

## Acceptance examples to define

Before billing implementation, agree on expected results for a client rate overridden by a project rate, missing/conflicting rates, a rate change during a billing period, midnight and daylight-saving crossings, fractional-hour rounding, duplicate allocation attempts, source changes after review, edits after approval, and an uncertain email send result. Examples must state timezone, currency, calculation policy, and expected audit/state outcomes where relevant.
