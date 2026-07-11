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

## Ops Sim: Northstar Payment Brownout Retry Furnace

> Open only after attempting the learner-side drill.

### Executive diagnosis

A regional payment provider brownout becomes a checkout outage because the client retries five times synchronously, the breaker counts HTTP 202 error payloads as success, and payment calls share the checkout worker pool.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `checkout_request_duration_seconds{p99}: 0.42 -> 9.7`
- `checkout_worker_pool_in_use: 68 -> 240/240`
- `payment_client_inflight_requests: 900 -> 11800`
- `payment_client_retry_attempts_per_request: 1.1 -> 4.7`
- `payment_provider_latency_seconds{region="us-east",p99}: 0.8 -> 6.9`
- `payment_unknown_state_total: +14200`
- Config clue: `payment.timeout_ms: 8000`
- Config clue: `payment.max_attempts: 5`
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

- `add checkout pods first`: feeds the bottleneck or idle side of the system without fixing assignment, retries, or the scarce resource.
- `disable idempotency`: converts impatient retries or repair replays into duplicate external side effects.
- `fail open on payment authorization`: optimizes conversion by violating money or write-safety invariants.
- `shorten timeout without UNKNOWN state`: improves a visible symptom while weakening the incident invariant or repair boundary.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: provider transaction API/callbacks plus internal idempotency ledger.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- semantic breaker states SUCCESS/FAILURE/UNKNOWN
- retry budgets with jitter
- separate payment bulkhead
- pending-payment UX and reconciliation runbook

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

