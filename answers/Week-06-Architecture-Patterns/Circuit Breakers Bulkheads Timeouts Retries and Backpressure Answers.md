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

### Principal model response

The root mechanism is retry furnace plus missing bulkhead.
The payment provider has a regional brownout, but checkout
turns it into a self-inflicted outage because each request can
hold a worker for long timeouts, retry synchronously five
times, and share the same worker pool as the rest of checkout.
The breaker also treats HTTP 202 error payloads as success, so
it never protects the system.

First 15 minutes:

1. Declare P1 for checkout/payment unknown-state risk.
2. Assign incident command, checkout owner, payments owner,
   provider liaison, worker-pool/platform owner, support,
   finance/risk, and product.
3. Freeze checkout/payment deploys and config flips.
4. Reduce attempts and total budget immediately; no five
   synchronous attempts with 8s timeouts.
5. Move payment calls into a separate bulkhead or cap payment
   concurrency so checkout workers are not all occupied.
6. Treat HTTP 202 error payload/unknown as breaker failure or
   UNKNOWN, not success.
7. Return pending payment state to users when provider outcome
   is unknown.
8. Start reconciliation ledger keyed by internal idempotency
   key and provider transaction/request id.

Telemetry interpretation:

- Checkout p99 `0.42 -> 9.7` and worker pool `240/240` show
  user and scarce-resource impact.
- Payment inflight `900 -> 11800` and retry attempts p99
  `1.1 -> 4.7` show retry amplification.
- Provider p99 6.9s in us-east is the trigger, not the whole
  failure.
- `payment_unknown_state_total: +14200` proves correctness
  ambiguity, not just latency.
- Config `timeout_ms: 8000` with `max_attempts: 5` can hold
  a user request far longer than the acceptable checkout
  budget.

Capacity math:

- Worst-case synchronous wait is roughly `5 * 8s = 40s`
  before overhead, far beyond checkout SLO.
- At 240 workers, a 40s hold permits only about 6
  fully-blocking requests/sec if all workers are consumed.
- With 11,800 inflight payment calls, provider recovery may be
  delayed by client-side pressure even after the brownout ends.

Bad fixes:

- Adding checkout pods first can multiply provider pressure
  and increase unknown states.
- Disabling idempotency makes retries and reconciliation
  dangerous.
- Failing open on payment authorization violates money
  invariants.
- Shortening timeout without explicit UNKNOWN state creates
  faster ambiguity, not correctness.

Repair:

- For each unknown payment, query provider by idempotency key
  and transaction id before retrying or compensating.
- Mark customer order as pending until authoritative result is
  known.
- Replay only through the idempotent payment path with bounded
  concurrency.
- Preserve provider callbacks, request ids, and internal
  ledger transitions.

Durable architecture:

- Breaker has semantic states: success, failure, timeout, and
  unknown.
- Retry budget is per request and global per dependency, with
  exponential backoff and jitter.
- Payment provider calls have their own bulkhead and queue.
- Checkout has backpressure that returns pending/degraded
  states before workers saturate.
- Dashboards show inflight, retry attempts, breaker state,
  unknown payments, idempotency conflicts, worker utilization,
  and provider latency together.

Question-by-question grading notes:

- Q1 should name retry/bulkhead mechanics, not "provider slow"
  alone.
- Q2 should cite worker saturation, inflight growth, retry
  attempts, unknown states, and timeout config.
- Q3 should change retries/bulkheads before scaling callers.
- Q4 should reject fail-open payments and idempotency removal.
- Q5 should compute worst-case worker hold or inflight
  pressure.
- Q6 should define provider/idempotency reconciliation.
- Q7 should name finance/risk and provider liaison in the
  runbook.

Recovery is complete when:

- payment inflight and retry attempts return to budget;
- worker pool has reserved nonpayment capacity;
- unknown payment count is draining with reconciled outcomes;
- duplicate external effects remain zero;
- breaker trips on semantic provider failures;
- game-day proves brownout does not saturate checkout.

Minimum learner bar:

- If the response optimizes p99 while increasing UNKNOWN
  payments, it fails.
- If it lacks a separate payment bulkhead, it has not contained
  the blast radius.
- If it cannot explain retry budget versus timeout budget, it
  is not principal depth.
- If it skips provider reconciliation, it leaves money state
  ambiguous.

---


---
