# Answer Key - Week 08 - Northstar Slow-Burn Checkout

> Open only after attempting the Ops Sim.

## Executive diagnosis

A strong response identifies the source-of-truth invariant first, then stops amplifiers before replaying or scaling. The incident is proven by the combination of user slice, scarce-resource metrics, logs, and unsafe config.

## Evidence map

- `global_checkout_availability: 99.94%`
- `enterprise_eu_checkout_availability: 98.62%`
- `payment_auth_success_rate{tier=enterprise,region=eu}: 92.8%`
- `checkout_latency_p99_ms{enterprise,eu}: 420 -> 4100 over 6h`
- `slo_burn_rate_5m: missing`
- `active_metric_series: 22M -> 980M`
- `metrics_query_timeout_rate: 41%`
- `trace_sampling_rate: 1.0 no expiry`
- `slo: dropped labels region,tenant_tier during dashboard refactor`
- `metrics: high-cardinality label order_id on checkout_request_duration`
- `coupon: token issued in future by 88s; rejecting`
- `cart-sync: LWW chose device_ts future +120s for removed item`
- `dispatch: matched courier location_age=181s`

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
