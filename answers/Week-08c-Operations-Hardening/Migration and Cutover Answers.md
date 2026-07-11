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

## Principal-depth model answer

### Q1 - Failing layer and mechanism

The primary symptom belongs to the migration protocol across
the writer and CDC projection, not to seller analytics alone.
Analytics is where the enterprise sellers notice the missing
line items, but the evidence shows the authoritative order
shape is split before analytics reads it:

- the writer commits old JSON but times out on secondary v2
  rows;
- the flag defaults missing tenant context to the new path;
- the CDC projection starts from `latest` without a
  `snapshot_end_lsn`;
- shadow reads disagree only on `line_items`, especially with
  `seller_promo_code`;
- old partners still send legacy payloads at 9k/min.

Name the invariant as: every accepted checkout has one
authoritative semantic order shape, and every derived
projection must be built from a fenced source boundary. The
invariant is not "analytics green" and not "global checkout
success above 99.9%."

### Q2 - Telemetry interpretation

A strong answer uses at least five of these signals together:

1. `checkout_success_rate_enterprise_eu: 98.1%` shows the
   impacted contractual slice even though global success is
   99.92%.
2. `shadow_read_disagreement_ratio{field=line_items}: 0.84%`
   points at semantic parity, not request availability.
3. `dual_write_mismatch_total: 1840/min` proves the writer is
   creating divergent old/new representations.
4. `analytics-loader: projection offset 881244 <
   snapshot_end_lsn 881991` proves the CDC read model can miss
   part of the snapshot/stream boundary.
5. `wal_retained_gb: 640, +55GB/10min` shows a scarce
   resource that can turn a correctness incident into a
   database availability incident.
6. `flag_eval_missing_context_total: 3.8k/min` plus
   `safe_default: true` explains why the rollout is wider than
   intended.
7. The trace `JSON item_count=4` and `v2 line_item rows=3`
   proves a real semantic mismatch on an order, not only a
   monitoring artifact.

The green global checkout number is a red herring. It can stay
healthy while enterprise EU seller reporting and promo order
shape correctness burn.

### Q3 - First 15 minutes

T+0 to T+3:

1. Declare P1 for enterprise EU order-shape correctness.
2. Assign incident command, checkout writer owner, data/CDC
   owner, analytics owner, partner gateway owner, support, and
   product.
3. State the invariant on the bridge: no accepted order can
   lose or invent line items; repairs must come from
   authoritative orders/outbox rows, not analytics.
4. Freeze new tenant enablement, schema contract changes,
   analytics authority moves, and partner routing changes.

T+3 to T+8:

5. Override `checkout.new_order_shape` so missing tenant
   context fails closed to the old path, not the new path.
6. Stop the analytics projection from becoming authority for
   more tenants; keep dual representations for comparison.
7. Put partner legacy traffic on the known-compatible old
   endpoint while recording partner, tenant, and order ids.
8. Pause or throttle the backfill when WAL growth and replica
   lag cross the incident threshold.

T+8 to T+15:

9. Build the affected set from source order ids in EU
   enterprise tenants where promo code is present and shadow
   read disagrees.
10. Compare semantic hashes: order id, tenant id, promo code,
    sku, quantity, money fields, fulfillment state, and
    line-item count.
11. Preserve old JSON and v2 rows; do not delete either side.
12. Publish a T+15 update: blast radius is scoped to
    enterprise EU/new-shape tenants and legacy partners, not
    all checkout.

### Q4 - Why global rollback is dangerous

A global rollback to the old binary is unsafe because old
readers reject `fulfillment_state='reserved_pending'`. That
rollback can convert a partial migration mismatch into a
checkout read/write outage. It may also strand tenants that
already wrote v2-only enum values and confuse partner clients
that have cached routing.

Safer rollback is scoped and contractual:

- freeze expansion and contract, but leave compatible readers
  deployed;
- force missing-context flag evaluations to the old path;
- route legacy partners to the legacy payload endpoint;
- prevent analytics authority from moving to v2 until the
  snapshot and stream are fenced;
- keep dual-write comparison until old code, caches, jobs, and
  partner endpoints are proven gone.

### Q5 - Capacity and blast-radius math

Do the arithmetic before repair:

- Mismatch rate: `1840/min` dual-write mismatches means
  110,400 suspect writes/hour if the rate persists.
- Shadow disagreement: 0.84% sounds small, but at high sale
  volume it is material. At 220k enterprise EU checkouts/hour,
  `220000 * 0.0084 = 1848` orders/hour need reconciliation.
- Legacy partner traffic: 9k/min is 540k requests/hour still
  exercising old contracts.
- WAL retained: `+55GB/10min` is 5.5GB/min. With only 50GB of
  intended safety buffer, doubling backfill while growth is
  positive can exhaust the buffer in under ten minutes.
- Replica lag: analytics lag at 72s is below the 120s pause
  threshold but already invalid for parity checks that assume
  current data.

Doubling backfill is the wrong direction. It adds WAL, IO,
buffer churn, and replica lag while the projection boundary is
not even correct.

### Q6 - CDC cutover repair

The repair needs an explicit state machine:

1. Stop the authority move; analytics reads old authoritative
   state or a labeled degraded view.
2. Define `snapshot_start_lsn` and `snapshot_end_lsn` for the
   normalized table, and persist them in the migration record.
3. Restart streaming from `snapshot_end_lsn`, not `latest`.
4. Make projection writes idempotent by
   `(tenant_id, order_id, line_item_id, projection_version)`.
5. Include duplicate detection for both old JSON items and v2
   row ids.
6. Backfill by bounded chunks tied to WAL retained bytes,
   replica lag, and checkout pool waiters.
7. Compare source semantic hashes and projection semantic
   hashes per tenant, promo-code status, and partner route.
8. Only then move analytics authority by cell/tenant with an
   abort gate.

### Q7 - T+30 customer and product update

The update should be precise and conservative:

- "Checkout remains available for most buyers, but a subset of
  enterprise EU seller analytics for promo orders may be
  missing or stale after successful checkout."
- "Payment correctness is higher priority than promotion
  analytics. We have frozen new cutover expansion and are
  reconciling order line items from the order source of truth."
- Included customers: enterprise EU tenants enabled for the
  new order shape, promo-code orders, and legacy partner
  fulfillment traffic through the old endpoint.
- Not included unless evidence appears: all global checkout,
  all buyers, non-EU sellers, and non-promo orders.

Do not say "analytics is fixed" because parity and CDC fences
are not yet verified. Do not promise zero impact until the
affected-record ledger is complete.

### Q8 - Durable acceptance criteria

Before another cutover attempt:

- Flag evaluation test proves missing tenant context fails
  closed and pages on any nonzero missing-context rate.
- Expand/contract test writes `reserved_pending` and verifies
  every still-deployed reader, job, partner path, and rollback
  binary can parse it or is gated off.
- CDC fixture records `snapshot_end_lsn`, restarts from the
  fence, kills the connector mid-cutover, and proves no gap or
  duplicate semantic line item.
- Shadow-read gate compares semantic hashes, not row counts,
  with thresholds by tenant/cell/promo route.
- Backfill load test enforces WAL retained bytes, replica lag,
  pool waiters, and pause/resume thresholds.
- Runbook has named owners for checkout, data platform,
  analytics, partner gateway, support, and product approval.

## Scoring rubric

| Score | Description |
| --- | --- |
| Meets bar | Names mechanism, protects invariant, sequences mitigation safely, includes evidence and numeric blast-radius/capacity reasoning. |
| Borderline | Finds the symptom but misses one of rollback, capacity, customer slice, or rejected bad fix. |
| Miss | Optimizes a dashboard, repairs from derived state, weakens trust/idempotency, or ignores affected slice evidence. |
