# Answer Key - Cassandra Architecture

> Open only after attempting the learner file questions.

## Ops Sim: Northstar Inventory Tombstone Read Storm

> Open only after attempting the learner-side drill.

### Executive diagnosis

A flash-sale SKU stores millions of short-lived cart holds under one `sku` partition. Reads at LOCAL_QUORUM scan expired tombstones before finding a few live holds; STCS and high gc_grace keep the graveyard around.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `cassandra_client_request_latency_seconds{scope="Read",quantile="0.99"}: 0.028 -> 7.9`
- `cassandra_table_tombstone_scanned_histogram{table="inventory_holds",p99}: 120 -> 870000`
- `cassandra_table_live_scanned_histogram{table="inventory_holds",p99}: 22`
- `cassandra_compaction_pending_tasks{table="inventory_holds"}: 12 -> 1840`
- `inventory_reservation_reject_rate{sku="dragon-hoodie"}: 0.3% -> 31%`
- `checkout_inventory_dependency_timeout_rate: 0.02% -> 8.4%`
- Config clue: `table.inventory_holds.compaction: SizeTieredCompactionStrategy`
- Config clue: `table.inventory_holds.default_time_to_live_seconds: 900`
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

- `drop consistency to ONE`: may return a faster answer that violates the correctness model the system promised.
- `add nodes and expect the old hot partition to split`: adds aggregate capacity but does not split the already-hot partition or poisoned key.
- `force major compaction during peak`: competes for the same disk/IO budget during peak and can lengthen the outage.
- `delete tombstones without repair discipline`: may return a faster answer that violates the correctness model the system promised.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: Cassandra reservation rows plus checkout attempts for the affected SKU/time window.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- bucket holds by sku and hour
- TWCS for TTL-heavy data
- alerts on tombstones scanned and top partitions
- separate OLTP reservations from seller analytics

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

