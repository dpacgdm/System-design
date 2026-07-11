# Answer Key - Cassandra Architecture

> Open only after attempting the learner file questions.

## Ops Sim: Northstar Inventory Tombstone Storm

### Q1 - Layer & root cause

Wide partitions plus mass deletes created tombstone and compaction debt; reservation reads became uncertain and must fail closed.

A strong answer separates the trigger from retry, cache, routing, or observability amplifiers and states the invariant that cannot be violated.

### Q2/Q3 - Evidence

- `read_p99_ms inventory_by_sku: 38 -> 2350`
- `tombstones_scanned_p95: 900 -> 185000`
- `pending_compactions: 12 -> 240`
- `sstables_per_read_p95: 7 -> 88`
- `coordinator_timeouts: 0.1% -> 9.4%`
- `cassandra: Scanned over 100000 tombstones for sku=ns-8841`
- `inventory-api: reservation uncertain; fail_closed=true`
- `cleanup-job: DELETE ... ALLOW FILTERING`
- Config clue: `primary_key: ((sku_id), hold_id)`
- Config clue: `compaction: SizeTieredCompactionStrategy`

### Q4 - Red herrings

Do not trust fleet averages, shallow health checks, or resource alerts that are not tied to the affected user slice. Downstream lag and retries may be symptoms to control, but they do not automatically identify the first cause.

### Q5/Q6 - Safe first 15 minutes

1. Declare severity, name the invariant, and assign subsystem owners.
2. Freeze new deploys, rollouts, rebalances, schema changes, or bulk replays touching the path.
3. Stop the active amplifier called out in the config/timeline.
4. Shed or degrade noncritical work before weakening checkout, payment, inventory, or tenant isolation.
5. Verify with the primary SLI, the scarce-resource metric, and the lag/error derivative.
6. Start an affected-record ledger for repair before any manual replay.

### Q7 - Bad fixes

- `lower checkout reads to ONE globally`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `continue delete job during peak`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `run major compaction on every node immediately`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `trust Redis counts for reservation`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.

### Q8 - Capacity / blast radius

Quantify current usage, safe ceiling, growth rate, and time-to-exhaustion for queue/lag, connection or thread pools, disk/WAL/compaction, and affected business records. Scaling is only safe if the downstream dependency has headroom.

### Q9 - Correctness invariant

Accepted orders, money movement, inventory reservations, tenant isolation, and source-of-truth state must remain conservative. If the outcome is uncertain, mark it uncertain and reconcile instead of guessing.

### Q10 - Data repair

Use source-of-truth rows, stable idempotency keys, LSNs/offsets, and the incident window to define the repair set. Replay with duplicate suppression, throttle to downstream headroom, and record customer-visible corrections.

### Q11 - Durable fixes

- bucket holds by expiry/time.
- TTL plus TWCS for time-bound data.
- safe cleanup windows.
- tombstone alerts and per-SKU dashboards.

Acceptance criteria: the old failure is reproduced in a drill, the new guardrail pages before customer impact, and the unsafe configuration cannot be enabled without review.

### Q12/Q13 - Alerting and runbook

Page on SLO burn, correctness failures, lag derivative, and scarce-resource exhaustion in the affected slice. By T+10 include incident commander, service owner, data/platform owner, product/business owner, support, and security/payments if trust or money is involved. Pre-authorized: stop unsafe rollouts, shed noncritical work, conservative fallback. Senior approval: durability downgrade, destructive repair, broad failover, or accepting derived data as truth.

---
