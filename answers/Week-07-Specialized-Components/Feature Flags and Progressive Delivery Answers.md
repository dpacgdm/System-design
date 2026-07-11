# Answer Key — Feature Flags and Progressive Delivery

> Open only after attempting the learner file questions.

## Expert Analysis

```
This section intentionally contains scenario questions only.
Worked responses belong in Retention-Tests/Week-07.md when
that file is authored.

Use the seven questions above for self-assessment and mock
incident drills. A principal-grade response to Question 2
should be executable by another engineer without clarification.

PARTIAL HINTS (not full answers — retention test has worked solutions):

  Q1(a): Broken hybrid paths ≈ P(A⊕B) for independent 25% flags.
         P(both on) = 0.25×0.25 = 6.25% happy path.
         P(A only) = P(B only) = 0.25×0.75 ≈ 18.75% each → broken.
         Total broken ≈ 37.5% of users who hit new-checkout cohort
         (plus legacy users hitting new-payments-only path).

  Q2(a): Flip new-checkout first (removes largest broken surface),
         then new-payments-v2 (stops legacy users hitting v2 payments).

  Q3(a): Circuit breakers trip on failure RATE to dependency calls.
         Validation errors may be caught in-app before 5xx propagates,
         or returned as 200 with error payload — CB sees success.

  Q4(a): Prerequisite: release.new-checkout requires release.new-payments-v2.
```

---

## Ops Sim: Northstar Checkout Flag Blast Radius

### Q1 - Layer & root cause

Missing flag context defaulted true and rollback was slowed by stale client caches.

A strong answer separates the trigger from retry, cache, routing, or observability amplifiers and states the invariant that cannot be violated.

### Q2/Q3 - Evidence

- `flag_true_rate coupon_v2: expected=10% observed=78%`
- `checkout_discount_mismatch_rate: 0.02% -> 4.9%`
- `payment_authorization_declines: +11%`
- `flag_eval_missing_context: 0 -> 1.8M/hour`
- `mobile_flag_cache_age_p95_min: 27`
- `flag-eval: missing tenant_id; default=true`
- `mobile: cached flag variant=v2 age=1740s`
- `pricing: coupon applied twice`
- Config clue: `flag_default: true`
- Config clue: `rollout_percent: 10`

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

- `leave rollout because conversion is flat`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `delete all flags globally`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `trust client-side pricing`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `cancel orders without audit`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.

### Q8 - Capacity / blast radius

Quantify current usage, safe ceiling, growth rate, and time-to-exhaustion for queue/lag, connection or thread pools, disk/WAL/compaction, and affected business records. Scaling is only safe if the downstream dependency has headroom.

### Q9 - Correctness invariant

Accepted orders, money movement, inventory reservations, tenant isolation, and source-of-truth state must remain conservative. If the outcome is uncertain, mark it uncertain and reconcile instead of guessing.

### Q10 - Data repair

Use source-of-truth rows, stable idempotency keys, LSNs/offsets, and the incident window to define the repair set. Replay with duplicate suppression, throttle to downstream headroom, and record customer-visible corrections.

### Q11 - Durable fixes

- fail-closed checkout flags.
- required targeting context.
- server-side authoritative pricing.
- payment-error and mismatch guardrails.

Acceptance criteria: the old failure is reproduced in a drill, the new guardrail pages before customer impact, and the unsafe configuration cannot be enabled without review.

### Q12/Q13 - Alerting and runbook

Page on SLO burn, correctness failures, lag derivative, and scarce-resource exhaustion in the affected slice. By T+10 include incident commander, service owner, data/platform owner, product/business owner, support, and security/payments if trust or money is involved. Pre-authorized: stop unsafe rollouts, shed noncritical work, conservative fallback. Senior approval: durability downgrade, destructive repair, broad failover, or accepting derived data as truth.

---
