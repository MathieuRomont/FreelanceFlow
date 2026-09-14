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
- Pre-invoice pricing preserves the exact unrounded monetary result derived from duration microseconds and the exact Decimal hourly rate. A billing-specific rational representation may be used when the result is not a terminating Decimal. Final currency quantization and rounding remain unresolved.
- RateAgreement validity uses half-open date intervals `[valid_from, valid_until)`: the start is inclusive, the end is exclusive, and a null end means open-ended.
- The rate resolver receives an already-interpreted business date. Timezone and timestamp-to-business-date conversion are outside issue #3 and remain unresolved.
- Conflicts at the selected precedence level raise an explicit domain error during resolution. This does not decide whether overlaps should be rejected globally when agreements are created or edited.
- Confirmed example: Rate A runs from 2026-01-01 to 2026-09-01; Rate B starts 2026-09-01 with no end. August 31 resolves A; September 1 resolves B. A client rate of 80 EUR/hour resolves to 80; an applicable project rate of 100 EUR/hour overrides it. Missing rates and conflicts at the selected precedence level raise explicit domain errors. A unique project rate of 100 EUR/hour still resolves when applicable client rates of 80 and 90 EUR/hour overlap.

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
- Ownership is confirmed; billing timezone conversion and splitting work across rate boundaries remain unresolved below.

## PROPOSED rules requiring confirmation

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
| Future duration adjustments | Raw TimeEntry elapsed duration is the confirmed MVP billable duration. Any future break, pause, or manual adjustment behavior requires a new confirmed rule. |
| Rounding | Final monetary/currency quantization remains unresolved. Which increment, rounding mode, and stage apply: segment, entry, day, line, or invoice? How are tax and subtotal rounding reconciled? |
| Rate boundaries | Automatic pricing-boundary segmentation is blocked by the unresolved billing-timezone/business-date policy. Date-range inclusivity and open-ended agreements are confirmed above; callers may provide already-prepared segments with an explicit business date. |
| Rate edits and validation | Resolution rejects conflicts only at the highest applicable precedence level. Whether overlapping agreements should be rejected globally at creation/edit time remains UNRESOLVED. How do backdated changes affect existing drafts and approvals? Are zero/negative rates allowed? |
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
