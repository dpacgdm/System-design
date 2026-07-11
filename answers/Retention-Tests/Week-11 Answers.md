# Answer Key - Week-11

> Open only after attempting `Retention-Tests/Week-11.md`.

---

## Part 1: Rapid-Fire Model Answers

**Q1:** `orders.paid=true` is a business view. The ledger is append-only accounting truth: every debit and credit is auditable, reversible via new entries, and reconcilable to PSP/bank settlement.

**Q2:** Return `409 idempotency_key_mismatch`. The same key means "same operation"; allowing a different amount under the key would make retries unsafe and could mask fraud or client bugs.

**Q3:** A timeout is unknown outcome, not failure. The PSP may have authorized successfully, so cancellation/refund must wait for PSP lookup/webhook/reconciliation to determine actual state.

**Q4:** Typical forward path: reserve inventory, authorize payment, create order, capture payment, publish events/fulfill. Compensations: release inventory, void authorization/refund capture if needed, cancel order, and send corrective events idempotently.

**Q5:** Reserving inventory before auth avoids charging for unavailable goods. Capturing after order commit avoids taking money when the business order does not exist or cannot be fulfilled.

**Q6:** Transactional outbox/CDC. The order row and outbox event commit atomically, then a reliable publisher emits to Kafka.

**Q7:** Acknowledged ledger writes not replayed to the promoted replica are at risk. Synchronous replication/quorum commit for ledger writes reduces data loss at the cost of availability/latency.

**Q8:** Kafka lets multiple independent consumer groups read the same immutable payment event stream and replay if needed. A work queue would hand each message to one consumer and lose the multi-subscriber/replay semantics.

**Q9:** Confirmation is part of the read-after-write user contract. A lagging replica/cache can show "order not found" after success; route to primary or require an LSN/session token before reading replicas.

**Q10:** Ledger should prefer correctness/CP. It is better to reject or queue money movement than accept writes that may conflict or disappear.

**Q11:** Rate limit at API edge and payment service by account/user/card/device/idempotency key, while allowing safe same-key retries. Also rate limit PSP adapter calls so duplicate unknown-outcome retries do not multiply external charges.

**Q12:** Tokenization keeps raw card data out of your systems. You store PSP/network tokens, reducing PCI scope and breach impact.

**Q13:** Product images, static assets, public catalog pages, and maybe read-only seller content can use stale-if-error. Checkout, payment intents, carts, inventory reservations, and auth-specific order state should not serve stale content.

**Q14:** Per-tenant refund quotas, PSP call budgets, ledger write quotas, queue isolation, and manual review thresholds. Large seller operations should run through batch lanes that cannot starve live checkout.

**Q15:** Ledger posting lag, PSP timeout/unknown outcome rate, idempotency mismatch rate, duplicate authorization rate, reconciliation break count, webhook processing lag, and debit/credit imbalance count.

---

## Part 2: Compound Scenario - Expert Analysis

### Root-Cause Chain

1. PSP p99 rose to 6s.
2. Checkout deploy lowered PSP timeout to 2s, converting slow successes into app-level timeouts.
3. Clients retried with fixed 500ms policy, creating 3.7x amplification.
4. PSP idempotency key was not forwarded, so retries could create duplicate PSP authorization attempts.
5. Idempotency DynamoDB throttled and left `IN_PROGRESS` records, making safe retry resolution harder.
6. Ledger primary failed over with async replica lag and `synchronous_commit=off`, losing acknowledged ledger entries from the promoted state.
7. Kafka projections lagged, but Kafka lag is not the same as ledger truth; missing ledger sequence ids after failover indicate actual ledger data loss or rollback that must be reconciled from external truth.

### Actual Data Loss vs Delayed Projection

Delayed projection: `payment-events` consumer lag and order/search/payment views behind the event stream.

Potential actual loss: `journal_entries` sequence gaps after async failover and PSP captures absent from ledger. Because the PSP is an external system of record for captures, the ledger must be repaired to match verified PSP facts, not merely replay internal projections.

### T+0 Decision

Freeze:

- Payment deploys and schema changes.
- Automated refunds/captures for affected flows unless explicitly reconciled.
- Risky backfills into ledger.

Stop:

- Fixed retry storms for unknown PSP outcomes.
- Any code path that sends a new PSP request without a stable idempotency key.

Preserve:

- PSP request/response logs, idempotency table, ledger WAL/backups, Kafka offsets, settlement files, webhook payloads, and application traces. Take snapshots before repair.

### T+5 Decision

Customer-facing state should be conservative: "payment processing/verification pending" for unknown outcomes, not paid and not failed. Internally, use PSP API/settlement plus surviving ledger entries and idempotency records as reconciliation inputs. Do not ship goods or issue refunds until each payment intent is classified.

### T+15 Decision

Before replaying Kafka:

- Determine whether events represent pre-failover ledger facts, post-failover duplicates, or projections.
- Check event idempotency keys and ledger unique constraints.
- Confirm ordering and exactly-once assumptions.
- Compare with PSP captures and idempotency rows.
- Run replay into a shadow ledger table first and produce a diff.

Blind replay can double-post journal entries, mark failed PSP attempts paid, or recreate entries that were rolled back inconsistently.

### T+60 Reconciliation Plan

1. Define affected window: 01:10 through stable recovery plus replay lag.
2. Build a payment-intent inventory from idempotency rows, checkout orders, PSP API/settlement files, webhooks, and existing ledger entries.
3. Classify each item:
   - PSP captured, ledger missing.
   - PSP authorized only, ledger pending.
   - PSP failed/canceled, ledger pending.
   - Duplicate PSP authorizations.
   - Ledger posted, order missing.
4. For PSP captured but ledger missing, post compensating/backfill journal entries with idempotency key `reconcile:<psp_id>` and audit metadata.
5. For duplicate auth/captures, void/refund according to PSP state and ledger both the refund and fees.
6. Rebuild order/payment read models from repaired ledger/outbox.
7. Finance signs off against settlement totals; Support receives customer-safe messaging.

### Timeout and PSP Idempotency

The 2s timeout is below PSP p99 during incident, so it manufactures unknown outcomes. Missing PSP idempotency forwarding means same logical payment may reach PSP as multiple independent attempts. Correct behavior is a longer timeout budget or async state machine plus PSP idempotency keys and reconciliation polling for unknown outcomes.

### Async Failover Ledger Gaps

With async replication and `synchronous_commit=off`, the primary can acknowledge a commit before WAL is flushed/replicated to the standby. If the primary dies and a lagging standby is promoted, acknowledged ledger entries in the lost lag window are absent. For money, this is usually unacceptable; use synchronous commit/replication or a consensus-backed ledger path.

### Bad-Fix Gallery

| Bad fix | Failure mode |
|---------|--------------|
| Mark all pending orders paid | Ships goods for failed/uncaptured payments; creates fraud/loss |
| Refund everyone with a timeout | Refunds successful legitimate payments, may double-refund, creates customer confusion |
| Replay Kafka blindly | Double-posts or posts events that are not authoritative ledger facts |
| Disable idempotency mismatch checks | Allows same key with different amount/body; unsafe money movement |
| Lower ledger durability | Increases chance of the exact data-loss class during peak |

### Capacity Answer

Attempted rate: `1,800/sec * 3.7 = 6,660 payment-create attempts/sec`.

That multiplies PSP calls, idempotency conditional writes, ledger transaction attempts, and webhook volume. The idempotency table throttling at 2,900/sec is plausible under this amplification. PSP duplicate attempts rise because retries are not collapsed by a forwarded PSP idempotency key.

### Org/Runbook Changes

- Payment timeout changes require payment SRE and finance approval.
- Unknown PSP outcomes enter a reconciliation state machine, not immediate fail/refund.
- Forward idempotency keys to PSP where supported.
- Ledger uses synchronous durability or a documented CP write path.
- Reconciliation poller interval moves from 6h to near-real-time for unknown outcomes.
- P0 runbook names incident commander, finance lead, payment engineering lead, support lead, and data preservation owner.

---

## Scoring Guide - 85% Gate

| Area | Points |
|------|--------|
| Rapid-fire correctness | 30 |
| Root-cause chain | 18 |
| Data-loss vs projection distinction | 12 |
| Reconciliation plan | 15 |
| Bad-fix analysis | 10 |
| Capacity math | 5 |
| Org/runbook controls | 10 |

Pass gate: **85%+**. Critical misses: treating PSP timeout as failure, ignoring async ledger data loss, or proposing blind Kafka replay as the primary repair.
