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

## Ops Sim: Northstar Cart Remove-Add Merge Conflict

> Open only after attempting the learner-side drill.

### Executive diagnosis

Offline carts use last-write-wins timestamps and 5-minute remove tombstones. Skewed devices resurrect removed items and checkout charges for stale cart contents.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `removed_items_reappeared_total: +88000`
- `checkout_cart_price_mismatch_rate: 6.1%`
- `mobile_sync_conflict_total: +310k`
- `device_clock_skew_seconds{p99}: 420`
- `cart_merge_lww_wins{source="offline"}: 72%`
- `refund_requests_wrong_item_total: +2100`
- Config clue: `cart.merge_strategy: lww_timestamp`
- Config clue: `cart.remove_tombstone_ttl_seconds: 300`
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

- `trust the newest device timestamp`: orders events by time observation rather than happens-before causality.
- `delete all offline carts`: can destroy replay evidence or resurrect/de-synchronize state before repair is safe.
- `repair from search/cart cache`: uses a derived view as truth, so it can miss or invent records during repair.
- `charge first and refund later`: turns an ambiguous cart merge into money movement and refund operations.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: server cart event log, checkout order rows, payment idempotency keys.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- observed-remove set semantics
- server-assigned logical clocks
- tombstone retention beyond offline horizon
- checkout conflict hold before payment

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

### Principal Ops Sim additions

The key distinction is that CRDT convergence does not equal
business safety. LWW cart merge can converge on a value that
resurrects removed items, and a PN-counter inventory model can
converge on negative stock after oversell. A strong incident
answer states both:

- convergence property: replicas eventually agree under the
  chosen merge algebra;
- business invariant: checkout cannot charge for stale or
  ambiguous cart contents.

Additional first-15-minute moves:

1. Block checkout for carts with unresolved remove/add
   conflicts or sync lag over the budget.
2. Preserve cart operation logs; do not delete offline carts
   to "clean up" the symptom.
3. Disable LWW timestamp merge for checkout decisions.
4. Show conflict UX before payment when server and device
   histories are concurrent.
5. Build affected set from cart op log, checkout order rows,
   payment idempotency keys, and device/app version.

Additional acceptance criteria:

- remove tombstones live longer than the maximum offline
  horizon plus repair window;
- checkout requires a causally merged server cart, not a
  device-local display value;
- replay tests include skewed clocks, offline remove/add,
  app restart, and delayed sync;
- dashboards show sync lag, conflict count, resurrection rate,
  checkout holds, and refund requests by app version;
- support language distinguishes "cart conflict held" from
  "order placed."

Reject any answer that says "CRDTs solve conflicts" without
naming which conflicts are acceptable for cart UX and which
must block money movement.

---


---
