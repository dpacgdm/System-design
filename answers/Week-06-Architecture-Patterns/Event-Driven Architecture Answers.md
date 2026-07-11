# Answer Key - Event-Driven Architecture

> Open only after attempting the learner file questions.

## Ops Sim: Northstar Order Event Contract Break

> Open only after attempting the learner-side drill.

### Executive diagnosis

A producer reuses a field for a new enum meaning under the same schema id. Type compatibility passes, but old consumers default unknown values into destructive business states.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `consumer_unknown_enum_total{field="status_reason"}: 0 -> 64200`
- `warehouse_pick_ticket_missing_gift_wrap_total: +8700`
- `fraud_event_lag_seconds{p99}: 12 -> 980`
- `search_order_state_mismatch_total: +19200`
- `email_duplicate_status_total: +4100`
- `kafka_consumer_lag{group="warehouse"}: 0 -> 240k`
- Config clue: `schema.compatibility: BACKWARD`
- Config clue: `event.version.bump_required_for_enum_semantics: false`
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

- `replay immediately after consumer deploy`: repeats the same bad side effects before idempotency and consumer semantics are fixed.
- `trust schema type compatibility as semantic safety`: reintroduces the semantic incompatibility and guarantees another consumer split-brain.
- `drop unknown events`: can destroy replay evidence or resurrect/de-synchronize state before repair is safe.
- `patch only one consumer`: may return a faster answer that violates the correctness model the system promised.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: order database, event id/schema id, projection mismatch rows, side-effect ledgers.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- semantic contract tests for enum additions
- unknown values quarantine by default
- versioned event state transitions
- replay tooling with operation ids

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

