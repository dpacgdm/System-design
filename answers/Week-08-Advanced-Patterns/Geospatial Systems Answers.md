# Answer Key - Geospatial Systems

> Open only after attempting the learner file questions.

## Ops Sim: Northstar Courier Geofence Drift

### Q1 - Layer & root cause

Stale locations remained eligible and radius expansion amplified hot-cell Redis GEO load.

A strong answer separates the trigger from retry, cache, routing, or observability amplifiers and states the invariant that cannot be violated.

### Q2/Q3 - Evidence

- `courier_location_age_seconds_p95: 18 -> 137`
- `match_radius_expansion_rate: 2% -> 48%`
- `hot_h3_cell_queries_per_sec: 62k`
- `redis_geo_cpu: 92%`
- `stale_courier_offer_rate: 0.4% -> 12%`
- `dispatch: matched courier location_age=173s`
- `geo: expanding radius to 50km`
- `courier-app: update dropped battery_saver=true`
- Config clue: `max_location_age_seconds: 300`
- Config clue: `radius_expand_until_candidate: true`

### Q4 - Red herrings

Do not trust fleet averages, shallow health checks, or resource alerts that are not tied to the affected user slice. Downstream lag and retries may be symptoms to control, but they do not automatically identify the first cause.

### Q5/Q6 - Safe first 15 minutes

1. Declare severity, name the invariant, and assign subsystem owners.
2. Freeze new deploys, rollouts, rebalances, schema changes, or bulk replays touching the path.
3. Stop the active amplifier called out in the config/timeline.
4. Shed or degrade noncritical work before weakening checkout, payment, inventory, or tenant isolation.
5. Verify with the primary SLI, the scarce-resource metric, and the lag/error derivative.
6. Start an affected-record ledger for repair before any manual replay.

### Q7 - Bad fixes

- `widen radius globally`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `ignore location freshness`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `trust client ETA after stale match`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `use one fixed cell resolution`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.

### Q8 - Capacity / blast radius

Quantify current usage, safe ceiling, growth rate, and time-to-exhaustion for queue/lag, connection or thread pools, disk/WAL/compaction, and affected business records. Scaling is only safe if the downstream dependency has headroom.

### Q9 - Correctness invariant

Accepted orders, money movement, inventory reservations, tenant isolation, and source-of-truth state must remain conservative. If the outcome is uncertain, mark it uncertain and reconcile instead of guessing.

### Q10 - Data repair

Use source-of-truth rows, stable idempotency keys, LSNs/offsets, and the incident window to define the repair set. Replay with duplicate suppression, throttle to downstream headroom, and record customer-visible corrections.

### Q11 - Durable fixes

- freshness TTL and heartbeat gating.
- adaptive H3 resolution.
- supply-aware cache shards.
- ETA SLO by freshness bucket.

Acceptance criteria: the old failure is reproduced in a drill, the new guardrail pages before customer impact, and the unsafe configuration cannot be enabled without review.

### Q12/Q13 - Alerting and runbook

Page on SLO burn, correctness failures, lag derivative, and scarce-resource exhaustion in the affected slice. By T+10 include incident commander, service owner, data/platform owner, product/business owner, support, and security/payments if trust or money is involved. Pre-authorized: stop unsafe rollouts, shed noncritical work, conservative fallback. Senior approval: durability downgrade, destructive repair, broad failover, or accepting derived data as truth.

---
