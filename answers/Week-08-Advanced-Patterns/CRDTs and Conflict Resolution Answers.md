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
