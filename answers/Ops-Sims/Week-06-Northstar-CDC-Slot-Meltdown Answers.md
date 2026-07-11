# Answer Key - Week 06 - Northstar CDC Slot Meltdown

> Open only after attempting the Ops Sim.

## Executive diagnosis

A strong response identifies the source-of-truth invariant first, then stops amplifiers before replaying or scaling. The incident is proven by the combination of user slice, scarce-resource metrics, logs, and unsafe config.

## Evidence map

- `orders_paid_total: +510k/hour`
- `outbox_rows_pending: 0 -> 226k`
- `outbox_oldest_age_seconds: 12 -> 2840`
- `pg_replication_slot_retained_bytes: 14GB -> 410GB`
- `postgres_wal_disk_free_percent: 31 -> 6`
- `debezium_source_lag_seconds: 5 -> 2600`
- `connector_restarts: +19/30m`
- `kafka_order_events_duplicate_key_rate: 0.03% -> 6.8%`
- `debezium: ERROR column order_total_cents not optional; schema history incompatible`
- `orders-api: inserted paid order without outbox row path=legacy-mobile-v3`
- `postgres: replication slot northstar_outbox retained WAL; disk usage above 90%`
- `manual-publisher: producing event order_id=ns-8844 idempotency_key=null`
- `fulfillment: duplicate external shipment request suppressed=false`

## First 15 minutes

1. Declare P1 and assign incident command, service lead, data/platform lead, and communications owner.
2. Freeze deploys, rollouts, rebalances, schema changes, and bulk replay touching the path.
3. Stop the active bad mitigation from the scenario before adding capacity.
4. Protect correctness: fail closed or mark uncertain where the source of truth cannot be proven.
5. Degrade noncritical surfaces allowed by the business constraint.
6. Verify with the sliced SLI, scarce-resource metric, and lag/error derivative.

## Bad fixes

- Deleting replay state or dropping slots/logs can turn a recoverable incident into permanent data loss.
- Weakening consistency globally hides symptoms and can create duplicate money, inventory, or tenant effects.
- Unlimited replay converts backlog into downstream overload.
- Derived caches/search/telemetry are not source of truth for checkout, inventory, or money movement.

## Capacity and repair

Compute time-to-exhaustion, replay drain rate, and affected record count before changing concurrency. Repair from source-of-truth rows plus stable idempotency/operation keys; throttle replay to downstream headroom and measure duplicates explicitly.

## Durable fixes

- Enforce the write/event/telemetry contract in CI and production admission checks.
- Add user-slice SLOs, lag/retention alerts, and runbooks with safe replay controls.
- Require stable operation IDs for all external side effects.
- Add drills that reproduce the old failure and prove rollback/replay safety.

## Org/runbook

By T+10: incident commander, owning service team, data/platform owner, product/business owner, support, and security/payments when trust or money is involved. Pre-authorized actions: stop unsafe rollouts, shed noncritical work, throttle replay, conservative fallback. Senior approval: destructive state changes, durability downgrade, broad failover, or accepting derived data as truth.
