# Answer Key - Week 06 - Northstar CDC Slot Meltdown: WAL Cliff and Idempotent Backfill

> Open only after attempting the learner-side drill.

### Executive diagnosis

A Debezium connector stalls after DDL while a manual repair job publishes non-idempotent fulfillment events. The logical slot is the recovery point and the disk threat.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `pg_replication_slot_retained_bytes: 14GB -> 430GB`
- `postgres_wal_disk_free_percent: 32 -> 5`
- `debezium_source_lag_seconds: 6 -> 2860`
- `fulfillment_missing_paid_orders: 23100`
- `manual_republish_events_total: +310k`
- `fulfillment_duplicate_external_call_total: +6200`
- Config clue: `debezium.snapshot.mode: always`
- Config clue: `slot.max_retained_wal_bytes: unlimited`
- Red herring: a fleet average or generic health check that does not include the damaged slice.

### First 15 minutes: sequencing

1. Declare severity, name the invariant, and assign an incident commander.
2. Freeze deploys, config flips, schema changes, broad failovers, and bulk replay touching this path.
3. Stop the active amplifier before adding capacity: retry storms, unsafe repair, global fallback, bad routing, or telemetry blow-up.
4. Roll back or override the specific dangerous config while preserving source-of-truth writes.
5. Shed noncritical surfaces: dashboards, notifications, search, decorative metadata, analytics, or advisory enrichment as appropriate.
6. Verify with the sliced SLI and scarce-resource metric; do not declare recovery from a global average.
7. Start an affected-record ledger before any replay or customer-visible repair.

### Bad fixes

- `drop the slot`: can destroy replay evidence or resurrect/de-synchronize state before repair is safe.
- `let manual republish continue`: improves a visible symptom while weakening the incident invariant or repair boundary.
- `replay at maximum Kafka throughput`: moves backlog into downstream overload and can duplicate side effects faster than teams can audit.
- `use search as the missing-order source`: uses a derived view as truth, so it can miss or invent records during repair.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: orders/outbox tables, replication slot LSN, fulfillment operation ids.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- slot-preserving WAL headroom runbook
- schema history recovery drill
- idempotent fulfillment operation keys
- backfill dry-run and throttle tooling

Acceptance criteria:
- The exact bad config from the drill is blocked or requires senior review.
- A staging drill reproduces the old failure and verifies safe rollback/replay.
- The dashboard contains the sliced SLI and the scarce-resource metric together.
- The alert fires before customer impact or before the scarce resource reaches exhaustion.

### Org and runbook

By T+10 include incident command, the owning service team, the relevant platform/data owner, product/business owner, and support. Add payments, security, finance, warehouse, seller-ops, or customer-success when money, trust, physical fulfillment, or enterprise promises are involved.

Pre-authorized: rollback bad config, pause unsafe repair, shed noncritical work, throttle retry/replay, quarantine unhealthy replicas/consumers/pods, and communicate degraded mode. Escalate: destructive state changes, durability downgrades, broad failover, consistency weakening, manual ledger/customer remediation outside policy, or accepting derived data as truth.

### Principal-depth checklist

- Root mechanism, trigger, and amplifier are distinct.
- Evidence uses real metric/config names from the drill.
- First action protects the invariant, not the prettiest graph.
- Bad fixes are rejected with concrete failure modes.
- Capacity math precedes scale/failover/replay.
- Repair has source of truth, idempotency, throttle, and audit.
- Durable fixes include alerts, tests, config guardrails, and ownership.

## Principal model response

### Root cause and invariant

The incident is a CDC recovery failure plus an unsafe manual
repair. `debezium.snapshot.mode: always` and missing schema
history recovery force repeated snapshots/restarts, while the
logical slot retains WAL. At the same time, manual republish
emits fulfillment events with no operation id, so repair
creates duplicate external calls.

The invariant is:

> Every paid order eventually receives exactly one fulfillment
> intent, and no repair replay creates duplicate external
> fulfillment effects.

Email/search/analytics may lag. Paid order truth and external
fulfillment idempotency may not.

### Telemetry interpretation

- `pg_replication_slot_retained_bytes: 14GB -> 430GB` shows
  the slot is retaining WAL faster than consumers advance.
- `postgres_wal_disk_free_percent: 32 -> 5` is the scarce
  resource and near-term database availability risk.
- `debezium_source_lag_seconds: 6 -> 2860` proves the CDC
  stream is not current.
- `connector_restart_total: +27/30m` suggests repeated
  recovery attempts, not steady backpressure.
- `fulfillment_missing_paid_orders: 23100` is the customer
  slice needing reconciliation.
- `manual_republish_events_total: +310k` and
  `fulfillment_duplicate_external_call_total: +6200` prove
  the repair job is an amplifier.
- `operation_id=null` names why replay is unsafe.

A fleet average dashboard is a red herring if it omits slot
retention, WAL free, and fulfillment slice correctness.

### First 15 minutes

T+0 to T+5:

1. Declare P1 for paid-order fulfillment correctness and WAL
   exhaustion risk.
2. Assign incident command, orders DB owner, data platform/CDC,
   fulfillment owner, support, finance/ops, and product.
3. Freeze schema changes, connector restarts by automation,
   manual republish, broad failover, and slot-destructive
   actions.
4. Stop manual republish immediately; it is creating duplicate
   external effects.

T+5 to T+15:

5. Add WAL headroom if safe: provision disk, archive pressure
   relief, or reduce noncritical writers before slot loss.
6. Preserve the logical slot unless a senior-approved recovery
   plan records exact LSN and rebuild path.
7. Fix connector config: disable repeated snapshot mode,
   restore schema history, and resume from known LSN.
8. Build affected set from orders/outbox table where paid
   order lacks fulfillment event in the incident window.
9. Define fulfillment operation id:
   `(tenant_id, order_id, fulfillment_action, attempt_version)`.
10. Publish status: paid orders are durable; fulfillment is
    delayed/reconciling; duplicate external calls are being
    stopped.

### Capacity math

WAL growth:

- retained WAL grew by 416GB from 14GB to 430GB.
- With disk free at 5%, the system is close to hard stop.
- If current growth is, for example, 20GB/10m and available
  headroom is 50GB, time to exhaustion is about 25 minutes.
  The exact answer should compute from the prompt's observed
  derivative or immediately measure it.

Replay:

- 23,100 missing paid orders is the lower-bound affected set.
- 310k manual republish events for 23.1k missing orders is
  over 13 emitted events per missing order on average.
- 6,200 duplicate external calls prove replay throughput must
  be throttled by idempotency and provider capacity, not Kafka
  max throughput.

### Repair plan

1. Query source orders/outbox for paid orders in the incident
   window with no successful fulfillment operation.
2. Join against fulfillment provider/audit logs by order id
   and stable operation id where present.
3. For records with null operation id, create a reconciliation
   ledger row before external calls.
4. Replay through a single worker path that writes the
   idempotency key before side effects.
5. Throttle by provider quota, fulfillment downstream capacity,
   and DB pool headroom.
6. Mark each order as reconciled, pending, skipped duplicate,
   or needs manual review.
7. Rebuild search/email projections only after fulfillment
   invariant is safe.

### Bad-fix rejection

- Dropping the slot may remove the only exact recovery point
  and force a blind snapshot during outage.
- Continuing manual republish improves "missing event" counts
  while creating duplicate external work.
- Max Kafka replay moves the bottleneck to fulfillment and
  hides audit gaps.
- Using search as source of missing orders undercounts or
  invents records because search is a derived view.
- Failing over Postgres without LSN/slot plan can preserve the
  application outage and lose replay context.

### Durable acceptance gates

- Debezium schema-history recovery drill is run quarterly.
- `slot.max_retained_wal_bytes` or equivalent guardrail pages
  before disk exhaustion.
- Snapshot mode changes require senior review and staging
  replay.
- Fulfillment events require non-null operation ids.
- Backfill/replay tooling has dry-run, max concurrency,
  provider quota, and duplicate-detection gates.
- Dashboards show slot retained bytes, WAL free, connector lag,
  outbox age, missing paid orders, duplicate external calls,
  and replay throttle together.
- Runbook defines who can approve slot drop, snapshot rebuild,
  provider replay, and customer remediation.

---
