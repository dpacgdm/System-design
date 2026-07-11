# Answer Key - Lamport Clocks Vector Clocks and Causality

> Open only after attempting the learner file questions.

## Ops Sim: Northstar Causal Notification Inversion

> Open only after attempting the learner-side drill.

### Executive diagnosis

Notification fanout orders by broker arrival time after dropping `causal_parent_id` and omitting the payment actor from vector clocks. Customers receive shipped before paid.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `notification_inversion_total: +64000`
- `payment_to_ship_event_lag_seconds{p99}: 12`
- `notification_send_order_violation_rate: 7.4%`
- `fanout_reorder_buffer_drops_total: +220k`
- `vector_clock_missing_actor_total: +118k`
- `customer_cancel_after_ship_email_total: +1700`
- Config clue: `fanout.order_by: broker_arrival_time`
- Config clue: `event.causal_parent_id.required: false`
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

- `sort by wall-clock timestamp`: orders events by time observation rather than happens-before causality.
- `increase buffer without causal metadata`: delays symptoms but still drops or misorders events without causal metadata.
- `delete duplicate notification records`: can destroy replay evidence or resurrect/de-synchronize state before repair is safe.
- `resend all emails immediately`: improves a visible symptom while weakening the incident invariant or repair boundary.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: order state machine transitions and event causal metadata.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- required causal predecessor ids
- vector clocks covering payment/order/shipment actors
- holdback queues with explicit expiry behavior
- notification idempotency by transition id

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

