# Answer Key - Mock Interview 02 Payment System

> Open only after attempting the learner file questions.

## Expert Model Answer

### Minute 0–5: Requirements

```
CLARIFYING QUESTIONS I'D ASK:

  1. "Payment lifecycle — auth-only, auth+capture, or direct charge?"
     → Assume auth + capture for marketplace (hold then release on ship)

  2. "Exactly-once — does that mean no duplicate charges, or also
     no lost payments?"
     → Both: no duplicate charges AND every accepted request is durable

  3. "Refund types — full, partial, idempotent retries?"
     → Full and partial; refunds must be idempotent too

  4. "Who holds PCI scope — us or PSP?"
     → PSP tokenization (Stripe Elements); we never see PAN

  5. "Read patterns — merchants polling status?"
     → Yes; estimate 5× read:write on payment status

  6. "Multi-region — active-active or primary/failover?"
     → Active-active API; payment_id assigned in one region (affinity)
       to avoid split brain on same payment

  7. "Settlement — do we track PSP settlement files?"
     → Yes; daily reconciliation is P0

FUNCTIONAL (ranked):
  P0: Create payment, capture, refund, status query, ledger
  P1: Webhooks to merchants, chargeback handling
  P2: Multi-currency (defer if time constrained)

NON-FUNCTIONAL:
  → 50K TPS peak write
  → Exactly-once money movement
  → 99.99% API availability
  → p99 < 500ms for authorization response
  → 7-year audit retention
  → PCI DSS SAQ A (tokenized)

DESIGN DRIVER: Exactly-once + auditability → idempotency + double-entry
```

### Minute 5–10: Estimation

```
GIVEN: 50K TPS peak (payments write)

READ QPS:
  Status polling: 5× writes = 250K reads/sec peak
  Support/admin: negligible vs polling

STORAGE (ledger):
  Per payment: 2–4 ledger entries × 200 bytes = ~800 bytes
  Daily (assume 50K TPS × 3600 × 4 peak hours realistic):
    50K × 14400 sec = 720M payments/day (upper bound)
    More conservative: 10K avg × 86400 = 864M/day
  Use 500M/day for estimation:
    500M × 800 bytes = 400 GB/day raw ledger
    × 7 years × 365 = ~1 PB (with indexes, replicas: 3–5 PB)

  → Must shard ledger by merchant_id; never single node

BANDWIDTH:
  Request ~1KB × 50K = 50 MB/sec ingress (trivial)
  PSP API ~2KB × 50K = 100 MB/sec egress (manageable)

BOTTLENECK:
  Ledger write throughput. At 50K txn/sec with 4 entries each =
  200K row inserts/sec. Requires 20–40 shards at 5K–10K writes/shard.

IDEMPOTENCY STORE:
  24h retention × 500M keys/day × 500 bytes = 250 GB/day (TTL eviction)
  Redis cluster with persistence OR DB with partition by date
```

### Minute 10–15: API & Data Model

```
POST /v1/payments
  Headers:
    Authorization: Bearer ...
    Idempotency-Key: {uuid}  (required)
  Body:
    {
      "merchant_id": "m_123",
      "amount": 4999,
      "currency": "usd",
      "payment_method": "pm_token_abc",
      "capture_method": "manual",
      "description": "Order #456",
      "metadata": { "order_id": "456" }
    }
  Response 201:
    {
      "payment_id": "pay_789",
      "status": "authorized",
      "amount": 4999,
      "psp_reference": "ch_xxx"
    }

POST /v1/payments/{id}/capture
  Idempotency-Key required

POST /v1/payments/{id}/refunds
  Idempotency-Key required
  Body: { "amount": 2500, "reason": "partial_return" }

GET /v1/payments/{id}
  → current status + status_history[]

WEBHOOK (to merchant):
  payment.authorized | payment.captured | payment.failed | refund.completed
```

### Minute 15–25: Architecture Narration

```
"I'll optimize for correctness on the write path. Money is the source
 of truth in the ledger; the PSP is an external effect we reconcile."

KEY DECISIONS:
  1. Tokenization at PSP — SAQ A, tokens only in our system
  2. Idempotency store — first gate before any side effect
  3. Ledger + outbox in single DB transaction — no dual-write
  4. PSP adapter — abstract Stripe/Adyen; forward idempotency keys
  5. Shard ledger by merchant_id — locality for merchant balance queries
  6. Async merchant webhooks via outbox → Kafka

CRITICAL PATH (sync, <500ms p99):
  Gateway → Payment Svc → Idempotency check → Ledger txn → PSP call
  → Ledger update → Return response

ASYNC PATH:
  Outbox → Settlement worker, merchant webhooks, reconciliation feed
```

### Minute 25–40: Deep Dive — Idempotency + Ledger Combined

```
DUPLICATE REQUEST SCENARIO:

  T0: Client POST /payments, Idempotency-Key: K1
  T1: Service writes idempotency(K1, IN_PROGRESS), ledger entries, commits
  T2: PSP call in flight...
  T3: Client timeout, retries POST /payments, Idempotency-Key: K1
  T4: Service finds K1 IN_PROGRESS → return 409 or wait (prefer 409 +
      Retry-After for fast clients; long-poll optional for SDK)
  T5: PSP returns success
  T6: Service completes K1 → COMPLETED with 201 body
  T7: Client retry gets cached 201 (not a second charge)

TIMEOUT SCENARIO (hardest):

  T2: PSP receives request, charges card
  T3: Network timeout before response reaches us
  T4: Our idempotency still IN_PROGRESS
  T5: Reconciliation job queries PSP: GET /charges?idempotency_key=K1
  T6: If found → complete ledger + idempotency; if not → safe to retry PSP

LEDGER EXAMPLE — $49.99 capture:

  transaction_id: txn_001
  entry 1: DR merchant_escrow(m_123)     +4999
  entry 2: CR platform_clearing          -4999
  entry 3: DR platform_clearing          +4999
  entry 4: CR psp_settlement             -4999

  Sum(txn_001) = 0 ✓

SHARDING:
  shard = hash(merchant_id) mod 64
  All entries for merchant's payments on same shard
  Cross-merchant transfers (marketplace fees) → async settlement batch
```

### Minute 40–45: Failure Modes

```
FAILURE 1: DUPLICATE CHARGE
  Cause: Idempotency key not forwarded to PSP; client generates new key per retry
  Symptom: Customer charged twice; support tickets
  Detection: Reconciliation job finds 2 PSP charges for 1 order_id
  Mitigation: Require Idempotency-Key; SDK generates one key per user action
  Prevention: DB unique constraint on (merchant_id, order_id) in metadata

FAILURE 2: SPLIT BRAIN (multi-region)
  Cause: Same payment_id written in US and EU region simultaneously
  Symptom: Conflicting ledger states; double PSP call
  Detection: Cross-region audit log mismatch; duplicate payment_id
  Mitigation: Route by payment_id → single home region (geo-DNS + affinity)
  Prevention: payment_id allocation includes region prefix; reject foreign writes

FAILURE 3: RECONCILIATION DRIFT
  Cause: PSP settlement file doesn't match ledger (timezone, partial captures)
  Symptom: Finance reports $50K discrepancy at month end
  Detection: Daily job: SUM(ledger) vs PSP settlement file per day
  Mitigation: Auto-ticket for drift > $1; manual review queue
  Prevention: Immutable ledger; never DELETE entries; adjustment entries only

FAILURE 4: OUTBOX PUBLISHER STALL
  Cause: Outbox relay crash; merchants don't receive webhooks
  Symptom: Merchants show unpaid orders that are captured
  Detection: outbox_lag_seconds metric > 60
  Mitigation: Alert + auto-restart; merchants poll GET /payments as backup
```

---
