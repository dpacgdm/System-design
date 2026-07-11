# Migration and Cutover Answers

Open only after attempting the learner file Ops Sim.

## Northstar Checkout Order-Shape Cutover

### Q1 - Which layer owns the primary symptom: writer, backfill, CDC projection, 

Name the narrow failing layer first, then show why
adjacent healthy systems do not disprove it. The root
cause should be phrased as a mechanism with an invariant,
not as a team name or product name.

### Q2 - Which five signals confirm the unsafe migration state

Use the telemetry pack in slices. A strong answer cites at
least three metrics, one log/config fact, and one
misleading global signal that would hide the affected
customer group.

### Q3 - Write the first 15-minute sequence. Which flag or routing changes happen

The first fifteen minutes should freeze additional blast
radius, preserve evidence, scope or disable the dangerous
path, and avoid destructive cleanup. Do not optimize for
green dashboards before protecting correctness.

### Q4 - Why is global rollback to old code dangerous in this case

Reject fixes that weaken authentication, authorization,
idempotency, source-of-truth repair, or tenant boundaries.
Also reject broad global changes when the evidence points
to a cell, tier, client version, route, or operation
class.

### Q5 - Compute blast radius from the provided mismatch and request rates. What 

The capacity or blast-radius answer must do arithmetic
from the prompt: rates, percentages, queue depth, lag,
stale windows, or duplicate counts. Fleet averages are not
enough.

### Q6 - Define the CDC cutover repair: snapshot boundary, offset fence, duplicat

The durable fix should include an automated test or game-
day, a config or protocol change, telemetry, an owner, and
a clear acceptance threshold.

### Q7 - What must the support and product update say by T+30, and which customer

The org/runbook answer should name incident command,
service owner, security or fraud if relevant,
product/support, and the approval boundary for risky
mitigations.

### Q8 - List three durable acceptance tests before attempting cutover again.

The final answer should turn the incident into launch
criteria: what must be true before the next rollout and
which bad state is now impossible or quickly detected.

## Worked response outline

- Primary diagnosis: unsafe migration state. The writer,
  flag default, and CDC projection are inconsistent; the
  analytics symptom is a derived effect, not the authority
  to repair from.
- Immediate move: freeze contract and expansion of the
  cutover, force missing flag context to old path, stop or
  throttle the backfill on WAL/lag pressure, and keep old
  and new data for comparison.
- Do not globally rollback old code because old readers
  reject fulfillment_state=reserved_pending. A rollback
  that cannot read current data is another outage.
- CDC repair: define snapshot_end_lsn, restart projection
  from a fenced offset, make projection idempotent,
  compare source order IDs and line-item semantic hashes,
  then cut analytics by tenant/cell.
- Blast radius: 0.84% disagreement at enterprise EU with
  9k/min old partner traffic means thousands of orders per
  hour need reconciliation; doubling backfill while WAL
  grows 55GB/10min risks slot/disk failure.

## Scoring rubric

| Score | Description |
| --- | --- |
| Meets bar | Names mechanism, protects invariant, sequences mitigation safely, includes evidence and numeric blast-radius/capacity reasoning. |
| Borderline | Finds the symptom but misses one of rollback, capacity, customer slice, or rejected bad fix. |
| Miss | Optimizes a dashboard, repairs from derived state, weakens trust/idempotency, or ignores affected slice evidence. |
