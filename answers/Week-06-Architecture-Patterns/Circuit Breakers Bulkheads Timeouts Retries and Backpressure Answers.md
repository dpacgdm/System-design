# Answer Key — Circuit Breakers Bulkheads Timeouts Retries and Backpressure

> Open only after attempting the learner file questions.

## Expert Analysis

```
This section intentionally contains scenario questions only.
Worked responses belong in Retention-Tests/Week-06.md when
that file is authored.

Use the seven questions above for self-assessment and mock
incident drills. A principal-grade response to Question 2
should be executable by another engineer without clarification.
```

---

## Ops Sim: Northstar Payment Dependency Brownout

### Q1 - Layer & root cause

A PSP brownout is amplified by unsafe retries, missing idempotency, disabled breakers, and absent bulkheads.

A strong answer separates the trigger from retry, cache, routing, or observability amplifiers and states the invariant that cannot be violated.

### Q2/Q3 - Evidence

- `psp_authorize_p99_ms: 320 -> 8100`
- `checkout_threads_busy: 98%`
- `retry_attempts_per_order_p95: 1 -> 17`
- `duplicate_authorization_rate: 0.01% -> 1.2%`
- `payment_bulkhead_queue: 0 -> 4800`
- `payment-client: timeout after 1000ms; retrying immediately`
- `psp: duplicate merchant_request_id missing`
- `checkout: shared executor rejected catalog request`
- Config clue: `timeout_ms: 1000`
- Config clue: `retry_backoff_ms: 200`

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

- `increase retries`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `disable idempotency`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `share all endpoints in one pool`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `keep enterprise breaker bypass`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.

### Q8 - Capacity / blast radius

Quantify current usage, safe ceiling, growth rate, and time-to-exhaustion for queue/lag, connection or thread pools, disk/WAL/compaction, and affected business records. Scaling is only safe if the downstream dependency has headroom.

### Q9 - Correctness invariant

Accepted orders, money movement, inventory reservations, tenant isolation, and source-of-truth state must remain conservative. If the outcome is uncertain, mark it uncertain and reconcile instead of guessing.

### Q10 - Data repair

Use source-of-truth rows, stable idempotency keys, LSNs/offsets, and the incident window to define the repair set. Replay with duplicate suppression, throttle to downstream headroom, and record customer-visible corrections.

### Q11 - Durable fixes

- PSP idempotency keys.
- bounded retries with jitter.
- payment bulkhead.
- audited circuit-breaker overrides.

Acceptance criteria: the old failure is reproduced in a drill, the new guardrail pages before customer impact, and the unsafe configuration cannot be enabled without review.

### Q12/Q13 - Alerting and runbook

Page on SLO burn, correctness failures, lag derivative, and scarce-resource exhaustion in the affected slice. By T+10 include incident commander, service owner, data/platform owner, product/business owner, support, and security/payments if trust or money is involved. Pre-authorized: stop unsafe rollouts, shed noncritical work, conservative fallback. Senior approval: durability downgrade, destructive repair, broad failover, or accepting derived data as truth.

---
