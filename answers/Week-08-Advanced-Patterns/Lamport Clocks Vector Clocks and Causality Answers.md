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

### Principal model response

The root mechanism is causality metadata loss. Notification
fanout orders by broker arrival time after the event contract
drops `causal_parent_id` and vector clocks omit the payment
actor. Broker arrival is an observation order, not a
happens-before relation, so customers can receive "shipped"
before "paid."

First 15 minutes:

1. Declare P1 for customer notification correctness and order
   state trust.
2. Assign incident command, order state owner, payment owner,
   shipment owner, notification owner, event platform,
   support/comms, and product.
3. Freeze notification replay, event contract changes, and
   broad resend jobs.
4. Stop sending transition notifications that lack required
   causal predecessor metadata.
5. Hold or quarantine events with missing payment actor/vector
   component.
6. Reconstruct affected set from order state machine, event
   ids, transition ids, causal parent, and notification send
   ledger.
7. Send customer correction only after source order state is
   verified.

Telemetry interpretation:

- `notification_inversion_total: +64000` is user-facing
  causality breakage.
- `payment_to_ship_event_lag_seconds p99: 12` is small enough
  that buffering could help only if metadata exists.
- `fanout_reorder_buffer_drops_total: +220k` shows the buffer
  is dropping instead of resolving causality.
- `vector_clock_missing_actor_total: +118k` names missing
  causality state.
- `fanout.order_by: broker_arrival_time` is the wrong order
  relation.

Capacity/blast radius:

- 64k inversions define the notification repair lower bound.
- 220k buffer drops may include events that never had enough
  metadata to order safely.
- Replaying all emails immediately can multiply support and
  confusion; replay must be by transition id and current order
  state.

Bad fixes:

- Sorting by wall-clock timestamp replaces one observation
  order with another and fails under skew.
- Increasing buffer without required metadata delays the
  symptom but cannot infer causality.
- Deleting duplicate records destroys audit and idempotency
  anchors.
- Resending all emails immediately can send more wrong
  messages before state is reconciled.

Repair:

- Source of truth is the order state machine and transition
  log, not notification delivery order.
- For each order, compute valid transition sequence:
  payment authorized/paid before shipped before delivered.
- Use transition id as notification idempotency key.
- Send correction/suppression messages only for customers
  whose delivered notifications contradict current source
  state.
- Keep a ledger of skipped, corrected, and resent
  notifications.

Durable architecture:

- Events that represent state transitions require predecessor
  transition id or causal parent.
- Vector clocks include order, payment, shipment, and support
  actors where those actors affect customer-visible order.
- Holdback queues have explicit expiry behavior: quarantine or
  pending, not unsafe send.
- Notification service dedupes by transition id and state
  version.
- Dashboards show inversion count, missing actor, buffer drop,
  causal metadata absence, resend volume, and support tickets.

Question-by-question grading notes:

- Q1 should name happens-before metadata loss.
- Q2 should cite inversion count, missing actor, buffer drops,
  and broker-arrival config.
- Q3 should stop unsafe sends before replaying.
- Q4 should reject wall-clock or broker-time sorting.
- Q5 should compute affected transitions and notification
  repair scope.
- Q6 should use order state machine as repair authority.
- Q7 should include support/comms because customer messages
  have already gone out.

Recovery is complete when:

- no new notifications are sent without required causal
  metadata;
- inversion count returns to zero in canary;
- affected customers are classified and corrected;
- replay uses transition idempotency;
- contract tests fail if `causal_parent_id` or required vector
  actors are missing;
- game-day covers broker delay/reorder and actor omission.

Minimum learner bar:

- If the answer sorts by wall-clock or broker-arrival time, it
  confuses observation order with causality.
- If it sends notifications without predecessor metadata, it
  continues customer harm.
- If it deletes notification records before repair, it loses
  audit and idempotency.
- If it lacks a transition-id replay ledger, correction cannot
  be safely bounded.

Interview-caliber close:

- Name the happens-before edge that must hold before sending a
  customer-visible notification.
- Explain which events are concurrent and which must be
  ordered by the order state machine.
- Verify replay from transition ids, not email timestamps or
  broker offsets alone.

---

