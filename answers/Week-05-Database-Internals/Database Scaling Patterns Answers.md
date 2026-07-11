# Answer Key - Database Scaling Patterns

> Open only after attempting the learner file questions.

## Ops Sim: Northstar Checkout Pool Saturation

### Q1 - Layer & root cause

Connection-pool exhaustion and unsafe primary read routing, amplified by replica lag and read-model lag rather than raw CPU saturation.

A strong answer separates the trigger from retry, cache, routing, or observability amplifiers and states the invariant that cannot be violated.

### Q2/Q3 - Evidence

- `orders_api_request_p99_ms: 180 -> 4100`
- `checkout_write_tps: 2900 -> 4800`
- `postgres_primary_cpu: 42%; iowait: 9%; locks_waiting: 31`
- `pgbouncer checkout: cl_active=720 cl_waiting=510 sv_active=180 sv_idle=0`
- `replica_lag_seconds: r1=1.5 r2=42.0 r3=3.2`
- `orders-api: timeout acquiring pg connection route=/checkout/confirm`
- `postgres: canceling statement due to conflict with recovery on replica r2`
- `worker-search: checkpoint stalled at lsn=8/AB7730`
- Config clue: `route_all_reads_to_primary: true`
- Config clue: `pgbouncer_max_server_conn: 180`

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

- `route all reads to primary`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `add replicas as first write-latency fix`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `turn off idempotency checks`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `promote a lagged replica blindly`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.

### Q8 - Capacity / blast radius

Quantify current usage, safe ceiling, growth rate, and time-to-exhaustion for queue/lag, connection or thread pools, disk/WAL/compaction, and affected business records. Scaling is only safe if the downstream dependency has headroom.

### Q9 - Correctness invariant

Accepted orders, money movement, inventory reservations, tenant isolation, and source-of-truth state must remain conservative. If the outcome is uncertain, mark it uncertain and reconcile instead of guessing.

### Q10 - Data repair

Use source-of-truth rows, stable idempotency keys, LSNs/offsets, and the incident window to define the repair set. Replay with duplicate suppression, throttle to downstream headroom, and record customer-visible corrections.

### Q11 - Durable fixes

- separate write/read pools.
- required-LSN replica routing.
- idempotent checkout confirmation.
- CQRS lag SLOs and sharding thresholds.

Acceptance criteria: the old failure is reproduced in a drill, the new guardrail pages before customer impact, and the unsafe configuration cannot be enabled without review.

### Q12/Q13 - Alerting and runbook

Page on SLO burn, correctness failures, lag derivative, and scarce-resource exhaustion in the affected slice. By T+10 include incident commander, service owner, data/platform owner, product/business owner, support, and security/payments if trust or money is involved. Pre-authorized: stop unsafe rollouts, shed noncritical work, conservative fallback. Senior approval: durability downgrade, destructive repair, broad failover, or accepting derived data as truth.

---
