# Answer Key — CRDTs and Conflict Resolution

> Open only after attempting the learner file questions.

## Expert Analysis
### Q1: Every Conflict Resolution Failure

**Failure 1 — Redis vs DynamoDB Split Brain**

- Merge: Redis PN-Counter vs DynamoDB LWW on quantity
- Redis: qty=5 after merge. DynamoDB: qty=1 (LWW winner)
- Customer expected one cart everywhere
- Systems: Redis CRDB cache vs DynamoDB CartLineItems

**Failure 2 — DynamoDB LWW Lost Singapore Quantity**

- Singapore wrote qty=2 at 08:23; us-east wrote qty=1 at 08:24
- LWW: us-east wins. qty=2 silently discarded

**Failure 3 — OR-Set Remove vs Concurrent Add**

- Singapore add tag T_sg (offline). us-east add T_e1, remove {T_e1}
- Merge: active tags = {T_sg}. Item reappears after delete
- CRDT correct per OR-Set; UX wrong (no conflict notification)

**Failure 4 — Inventory LWW Oversell**

- 2,300 concurrent decrements; LWW lost many
- inventory_count too high → oversell

**Failure 5 — Stale Read During Sync Lag**

- us-east empty cart at 08:24 before Singapore sync arrived
- Customer re-added, amplifying merge conflicts

**Failure 6 — Offline Sync During CRDB Backlog**

- 12s queued sync; customer acted on locally-valid unglobal state

### Q2: Dual Store Flaw and Minimum Fix

Two mutable stores, different merge algebras → no guarantee of
agreement. Redis: PN-Counter ⊕ OR-Set. DynamoDB: LWW.

**Minimum fix:** Single source of truth for checkout. Checkout reads
same CRDT state as app (Redis merged state), with sync lag guard
(refuse checkout if lag > 2s). DynamoDB becomes append-only op log
or is eliminated for cart quantity.

### Q3: OR-Set Delete vs Add

Remove on us-east observed only {T_e1}. Singapore's T_sg was
unobserved → survives merge. OR-Set guarantee: add wins over
unobserved remove. Fix: conflict UI, multi-device sync indicator,
or session stickiness to reduce cross-device concurrency.

### Q4: PN-Counter and Inventory

PN-Counter preserves all decrements (convergent arithmetic).
Starting 10000, sold 2300 → all agree 7700 remaining.

Does NOT prevent oversell: 1000 stock, two regions sell 800 each
→ converges to -600. Still oversold.

Need: linearizable reserve, regional allocation, or accept backorder.

### Q5: Remediation

**Immediate:**
1. Block checkout ap-southeast (lag region) — C over A temporarily
2. Checkout guard: lag > 5s → 503 on POST /checkout
3. Checkout reads Redis CRDT not DynamoDB line items
4. Banner when lag > 2s or concurrent merge detected

**Strategic:**
5. Event-sourced cart ops; DynamoDB = op log only
6. Regional inventory allocation + linearizable reserve
7. OR-Set GC + delta sync for mobile
8. Multi-device conflict notifications
9. Monthly chaos: CRDB partition + concurrent cart edits

### Q6: Sync Lag Guardrail

Tier 0-2s: normal. 2-5s: checkout OK + banner. 5-30s: block
checkout. >30s: Route 53 shift traffic away from lagging region.

```python
def checkout_allowed(region: str) -> bool:
    lag = get_crdt_sync_lag_seconds(region)
    if lag > 5.0:
        metrics.checkout_blocked_crdt_lag.inc()
        return False
    return True
```

---

## Ops Sim: Northstar Cart Merge Conflict

### Q1 - Layer & root cause

The cart used wall-clock LWW where observed-remove semantics and checkout coordination were required.

A strong answer separates the trigger from retry, cache, routing, or observability amplifiers and states the invariant that cannot be violated.

### Q2/Q3 - Evidence

- `cart_conflict_rate: 0.4% -> 16%`
- `deleted_item_reappeared_total: +58k`
- `lww_clock_skew_conflicts: +31k`
- `inventory_reservation_reject_stale_cart: +9k`
- `cart_merge_latency_p99_ms: 120 -> 1900`
- `cart-sync: LWW chose mobile_ts=future +180s`
- `resolver: remove op ignored because add has later timestamp`
- `checkout: stale_version=true reject`
- Config clue: `strategy: last_write_wins_wall_clock`
- Config clue: `remove_tombstones: false`

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

- `trust wall-clock LWW`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `drop remove tombstones immediately`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `reserve from eventually consistent cart`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `disable offline sync without migration`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.

### Q8 - Capacity / blast radius

Quantify current usage, safe ceiling, growth rate, and time-to-exhaustion for queue/lag, connection or thread pools, disk/WAL/compaction, and affected business records. Scaling is only safe if the downstream dependency has headroom.

### Q9 - Correctness invariant

Accepted orders, money movement, inventory reservations, tenant isolation, and source-of-truth state must remain conservative. If the outcome is uncertain, mark it uncertain and reconcile instead of guessing.

### Q10 - Data repair

Use source-of-truth rows, stable idempotency keys, LSNs/offsets, and the incident window to define the repair set. Replay with duplicate suppression, throttle to downstream headroom, and record customer-visible corrections.

### Q11 - Durable fixes

- operation-based merge with causal versions.
- observed-remove set semantics.
- checkout revalidation against inventory.
- client clock skew detection.

Acceptance criteria: the old failure is reproduced in a drill, the new guardrail pages before customer impact, and the unsafe configuration cannot be enabled without review.

### Q12/Q13 - Alerting and runbook

Page on SLO burn, correctness failures, lag derivative, and scarce-resource exhaustion in the affected slice. By T+10 include incident commander, service owner, data/platform owner, product/business owner, support, and security/payments if trust or money is involved. Pre-authorized: stop unsafe rollouts, shed noncritical work, conservative fallback. Senior approval: durability downgrade, destructive repair, broad failover, or accepting derived data as truth.

---
