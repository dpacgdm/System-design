# Answer Key - Database Scaling Patterns

> Open only after attempting the learner file questions.

## Ops Sim: Northstar Checkout Pool Backpressure Inversion

> Open only after attempting the learner-side drill.

### Executive diagnosis

PgBouncer session pooling pins server connections after a prepared-statement rollout; global primary-read fallback then sends noncritical reads into the write pool. The primary has CPU headroom, but admission to the database is saturated.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `checkout_confirm_latency_seconds{quantile="0.99"}: 0.38 -> 11.8`
- `checkout_confirm_success_rate: 99.96% -> 96.9%`
- `pgbouncer_pools_cl_waiting{db="orders"}: 0 -> 690`
- `pgbouncer_pools_sv_idle{db="orders"}: 0`
- `postgres_process_cpu_percent: 43`
- `read_to_primary_ratio{service="orders-api"}: 0.21 -> 0.93`
- Config clue: `pgbouncer.pool_mode: session`
- Config clue: `pgbouncer.default_pool_size: 180`
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

- `raise max_connections to 900 without memory math`: can exhaust primary memory and checkpoint capacity while leaving the pool topology bug intact.
- `route every read to the primary`: moves stale-read pain into the write path and turns replica lag into checkout admission failure.
- `turn off idempotency checks`: converts impatient retries or repair replays into duplicate external side effects.
- `promote lagged replica r2 because it is quiet`: risks losing recent committed state or reading stale data as authoritative.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: orders and payments tables keyed by idempotency key plus PgBouncer pool metrics.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- separate checkout write/read/projector pools
- required-LSN replica routing with per-replica quarantine
- transaction pooling review gate for prepared statements
- pool-wait and read-to-primary alerts by route

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

