# Answer Key - Lamport Clocks Vector Clocks and Causality

> Open only after attempting the learner file questions.

## Ops Sim: Northstar Causal Notification Inversion

### Q1 - Layer & root cause

Notifications lacked causal metadata and sorted by unreliable timestamps across independent streams.

A strong answer separates the trigger from retry, cache, routing, or observability amplifiers and states the invariant that cannot be violated.

### Q2/Q3 - Evidence

- `notification_inversion_rate: 0.03% -> 5.7%`
- `cross_topic_delivery_skew_seconds_p99: 480`
- `wall_clock_skew_seconds_p99: 37`
- `duplicate_notification_suppression_miss: +22k`
- `order_version_missing_rate: 64%`
- `notify: render shipped before paid order=ns-77`
- `fulfillment: event has no parent_order_version`
- `mobile: sorted by producer created_at`
- Config clue: `sort_key: producer_created_at`
- Config clue: `require_order_version: false`

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

- `single topic for every domain event`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `sort by receive time only`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `use wall clock as causal proof`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `dedup without operation id`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.

### Q8 - Capacity / blast radius

Quantify current usage, safe ceiling, growth rate, and time-to-exhaustion for queue/lag, connection or thread pools, disk/WAL/compaction, and affected business records. Scaling is only safe if the downstream dependency has headroom.

### Q9 - Correctness invariant

Accepted orders, money movement, inventory reservations, tenant isolation, and source-of-truth state must remain conservative. If the outcome is uncertain, mark it uncertain and reconcile instead of guessing.

### Q10 - Data repair

Use source-of-truth rows, stable idempotency keys, LSNs/offsets, and the incident window to define the repair set. Replay with duplicate suppression, throttle to downstream headroom, and record customer-visible corrections.

### Q11 - Durable fixes

- order version or sequence in notifications.
- Lamport/domain sequence for happens-before.
- vector clocks where concurrency must be detected.
- client guards for missing parents.

Acceptance criteria: the old failure is reproduced in a drill, the new guardrail pages before customer impact, and the unsafe configuration cannot be enabled without review.

### Q12/Q13 - Alerting and runbook

Page on SLO burn, correctness failures, lag derivative, and scarce-resource exhaustion in the affected slice. By T+10 include incident commander, service owner, data/platform owner, product/business owner, support, and security/payments if trust or money is involved. Pre-authorized: stop unsafe rollouts, shed noncritical work, conservative fallback. Senior approval: durability downgrade, destructive repair, broad failover, or accepting derived data as truth.

---
