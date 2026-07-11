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

## Ops Sim: Northstar Checkout Flag Prerequisite Leak

> Open only after attempting the learner-side drill.

### Executive diagnosis

A 10% coupon flag defaults true when tenant context is missing, mobile caches the variant for an hour, and server checkout trusts client-side discount math without enforcing the payment-v2 prerequisite.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `flag_true_rate{flag="coupon_v2"}: expected=10% observed=76%`
- `flag_eval_missing_context_total: +1.6M/hour`
- `discount_mismatch_rate: 0.03% -> 4.8%`
- `payment_decline_rate: 2.1% -> 9.4%`
- `mobile_flag_cache_age_minutes{p95}: 31`
- `orders_price_recalculated_total: +22000`
- Config clue: `coupon_v2.default: true`
- Config clue: `coupon_v2.requires: payment_v2 absent`
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

- `leave rollout because conversion looks flat`: improves a visible symptom while weakening the incident invariant or repair boundary.
- `delete every flag globally`: can destroy replay evidence or resurrect/de-synchronize state before repair is safe.
- `trust client price for reconciliation`: lets non-authoritative client state decide money movement.
- `cancel orders without audit`: turns a pricing mismatch into customer harm without an authoritative audit.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: order pricing ledger, payment authorization, server-side flag evaluations.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- fail-closed checkout flags
- server-side prerequisite graph
- short-lived emergency kill switches
- authoritative pricing verification before payment

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

---

