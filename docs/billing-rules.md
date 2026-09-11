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

### Money and effective rates

- Use Decimal, never float, for monetary values and billing calculations. Do not introduce float conversions at persistence or API boundaries.
- Each invoice has exactly one currency. Do not silently combine currencies or convert between them.
- Rates are effective-dated and may differ by client, project, and date.
- An applicable project rate overrides an applicable client rate. Their coexistence is not itself a conflict.
- Missing rates or conflicting applicable rates block billing of the affected time. Do not substitute zero or arbitrarily select one.
- A date-only effective rate boundary needs a documented timezone interpretation.

### Invoice content and approval

- Draft invoices originate from eligible TimeEntries through billing calculations and allocations.
- Allocated TimeEntries must belong to the same workspace and client as the invoice, have compatible project/task relationships, and match the invoice currency/rate context.
- Preserve the time provenance, applied rates, quantities, amounts, and customer/issuer details needed to explain historical invoice content.
- Approved invoice content is versioned. Approval applies to an exact invoice revision and frozen artifact. This is a confirmed architectural rule: delivery must use the artifact corresponding to that approved revision.
- Editing approved content invalidates approval; a new manual approval is required before delivery.
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
- Ownership is confirmed; exact timezone, duration, and rate-boundary policies remain unresolved below.

## PROPOSED rules requiring confirmation

- Represent effective-rate intervals as half-open ranges: `[start, end)`, optionally without an end date.
- Measure elapsed work with integer duration units; convert to Decimal hours during billing.
- Use deterministic classification suggestions initially. Ambiguous/unclassified entries remain subject to the confirmed blocking or explicit-exclusion rule.

Document format and rendering details remain open; approval of an exact revision and frozen artifact is confirmed.

## UNRESOLVED decisions

Delivery implementation is blocked until all three of these policies are defined:

- Atomic claiming of an approved invoice for sending.
- What edits are allowed while delivery is in progress.
- How approval invalidation interacts with sending.

Do not infer a final concurrency policy from the outbox, worker, or pre-send eligibility check. Those mechanisms alone do not resolve the send/edit race.

| Decision | Questions to settle before implementation |
| --- | --- |
| Billing timezone | Is it fixed per workspace? How are timezone changes handled historically? Are rate dates interpreted in the same timezone? |
| Duration policy | Is billable duration actual elapsed time across daylight-saving transitions? What precision is retained? How are breaks recorded? |
| Rounding | Which increment, rounding mode, and stage apply: entry, day, line, or invoice? How are tax and subtotal rounding reconciled? |
| Rate boundaries | Confirm half-open date ranges, open-ended rates, and treatment of entries spanning rate changes. |
| Rate edits and validation | Reject overlapping rates at entry time or flag them? How do backdated changes affect existing drafts and approvals? Are zero/negative rates allowed? |
| Time review and eligibility | What optional TimeEntry review workflow is needed? Which edits affect eligibility? When do ambiguous, unclassified, or unbillable entries block generation versus get explicitly excluded, and how is exclusion shown? Individual entry approval is not required to generate a draft. |
| Overlap and all-day events | How are overlapping work intervals resolved? Are all-day events excluded or manually converted? |
| Source reconciliation | How do cancellation, deletion, recurrence changes, entry splits/merges, and edits to already billed source events behave? |
| Billing periods and grouping | Are periods date-inclusive or half-open? Are lines grouped by task, day, project, or rate? What descriptions are shown? |
| Allocations | Do drafts reserve time? When is a reservation released? Is partial billing supported, and how are overlaps prevented transactionally? |
| Currency | Which currencies are supported and with what precision? Are mismatches rejected or split into separate drafts? |
| Tax and legal scope | What is the launch jurisdiction? Which tax modes, required invoice fields, numbering rules, and retention periods apply? These require separate validation. |
| Numbering and dates | When is an invoice number assigned? How are numbering scope, issue dates, due dates, and voided numbers handled? |
| Approval and delivery edits | Define atomic claiming for sending, allowed edits during delivery, and approval invalidation during sending before implementing delivery. Do changes to recipients, schedule, or email text require new approval? |
| Meaning of sent | Does sent mean provider acceptance? How are delivery confirmation, bounce, unknown outcomes, cancellation, and deliberate resend represented? |
| Corrections | Which correction documents and links are required? How are credits or adjustments allocated without rewriting sent content? |
| Retention and deletion | What source data can be deleted while preserving required invoice provenance, audit records, and protected personal data? |

## Acceptance examples to define

Before billing implementation, agree on expected results for a client rate overridden by a project rate, missing/conflicting rates, a rate change during a billing period, midnight and daylight-saving crossings, fractional-hour rounding, duplicate allocation attempts, source changes after review, edits after approval, and an uncertain email send result. Examples must state timezone, currency, calculation policy, and expected audit/state outcomes where relevant.
