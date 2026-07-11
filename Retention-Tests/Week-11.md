# WEEK 11 RETENTION TEST

Covers **Weeks 1-11** with emphasis on payment systems, e-commerce checkout, and payment data loss.

---

## Rules

```text
RULES OF ENGAGEMENT

1. Answer from memory. Do not open keys, modules, or worked examples.
2. Rapid-fire answers should be concise: 2-4 sentences.
3. Ops Sim answers should include evidence, sequencing, and trade-offs.
4. It is acceptable to say "I do not remember."
5. Open the answer key only after finishing your attempt.
```

---

## Part 1: Rapid-Fire Concept Recall (15 Questions)

**Q1 (Current - payments):** Why is an append-only double-entry ledger the source of truth rather than the `orders.paid=true` column?

**Q2 (Current - idempotency):** A client retries `POST /payment_intents` with the same idempotency key but a different amount. What should the API return and why?

**Q3 (Current - PSP timeout):** The PSP call times out after authorization may have succeeded. Why is immediate cancellation dangerous, and what reconciliation step is required?

**Q4 (Current - checkout saga):** Name the major forward steps and compensations in a physical-goods checkout saga.

**Q5 (Current - e-commerce inventory):** Why should payment authorization usually happen after inventory reservation but capture after order creation/commit?

**Q6 (Mid - outbox):** Order creation commits to Postgres but `order.placed` is not published to Kafka. What pattern prevents downstream systems from missing the event?

**Q7 (Mid - replication):** Async primary failover happens seconds after acknowledging ledger writes. What class of data is at risk, and what replication setting reduces that risk?

**Q8 (Mid - Kafka):** Payment events are consumed by email, analytics, risk, and fulfillment. Why is Kafka a better fit than a single work queue for this fan-out?

**Q9 (Mid - caching):** Why should checkout confirmation read from the write source or a read-your-writes route instead of a lagging replica/cache?

**Q10 (Old - CAP):** In a partition between ledger quorum nodes, should the payment ledger prefer availability or correctness? Explain the trade-off.

**Q11 (Old - rate limits):** Where do you rate limit payment creation to reduce fraud and PSP cost without blocking legitimate retries?

**Q12 (Old - auth/PCI):** What does tokenization buy you in PCI scope reduction?

**Q13 (Old - CDN):** Which e-commerce pages or assets can safely use CDN `stale-if-error`, and which checkout/payment paths should not?

**Q14 (Old - tenancy/cost):** A marketplace seller import creates millions of refunds. What tenant-level controls protect the shared ledger and PSP adapter?

**Q15 (Old - observability):** Name three payment-specific metrics that are more important than generic HTTP 5xx.

---

## Part 2: Compound Ops Sim - Northstar Payment Data Loss

```text
INCIDENT REPORT

Severity: P0
Company: Northstar Commerce
Systems:
  - checkout-api
  - pay-ledger Postgres cluster
  - psp-adapter
  - idempotency DynamoDB table
  - payment-events Kafka topic
  - reconciliation job for settlement files

Business event:
  Flash sale reaches 45k checkout peak TPS (events). Payment creation
  peaks at 1,800/sec. Support reports customers charged but orders show
  "payment pending" or "order not found".

Timeline:
  01:10 - PSP latency p99 rises from 600ms to 6s.
  01:14 - checkout-api deploy changes HTTP timeout from 12s to 2s.
  01:18 - retry rate triples.
  01:22 - pay-ledger primary fails over.
  01:25 - Kafka payment-events lag rises.
  01:31 - Finance sees PSP dashboard captures not present in ledger.
```

### Telemetry Pack

```text
checkout-api:
  payment_intent_create_qps: 1,800/sec
  client_retry_rate: 3.7x baseline
  http_409_idempotency_mismatch: +0.4%
  payment_timeout_rate: 0.2% -> 18%

psp-adapter:
  PSP authorize p99: 600ms -> 6s
  PSP success webhooks/min: 12k -> 46k
  duplicate PSP authorization attempts: +8.2%

pay-ledger:
  primary failover at 01:22
  async replica replay lag before promotion: 4.8s
  journal_entries gap by sequence: 18,442 ids missing after promotion
  ledger_posting_lag_seconds p99: 4s -> 740s
  journal_entries(idempotency_key) unique constraint present

idempotency store:
  DynamoDB conditional write throttles: 0 -> 2,900/sec
  TTL: 24h
  some records status=IN_PROGRESS for >20 min

Kafka:
  topic payment-events partitions=120 RF=3
  producer acks=1
  consumer lag risk-ledger-projector: 11M
  outbox table exists for orders, NOT for ledger postings

Settlement/reconciliation:
  PSP settlement file T+1 contains captures not in ledger
  webhook signature verification failures: 0
```

### Config Pack

```text
checkout-api:
  psp_timeout_ms=2000
  client_retry_policy=fixed_500ms_3_attempts
  idempotency_body_hash=enforced

pay-ledger:
  synchronous_commit=off
  replication=async
  isolation=READ COMMITTED

psp-adapter:
  forwards idempotency_key to PSP: false
  reconciliation poller interval: 6h

alerts:
  payment_api_5xx_rate pages at >1%
  ledger_posting_lag_seconds pages at >300s
  no page on PSP-timeout-with-later-webhook
```

### Decision Points

**T+0:** You join at 01:31. What do you freeze, what do you stop retrying, and what data do you preserve?

**T+5:** PSP shows captures missing from the ledger. What is the safest customer-facing state and internal source of truth while reconciling?

**T+15:** Engineers propose replaying Kafka `payment-events` into the ledger. What must be checked first?

**T+60:** You have settlement files, PSP APIs, idempotency rows, and partial ledger data. What is the reconciliation plan?

### Scenario Questions

1. Identify the root-cause chain and distinguish actual data loss from delayed projection.
2. Explain the role of the 2s timeout and missing PSP idempotency forwarding.
3. Explain how async failover can create ledger gaps even when the app got an acknowledgement.
4. **Bad-fix gallery:** Analyze (a) mark all pending orders paid, (b) refund everyone with a timeout, (c) replay Kafka blindly, (d) disable idempotency mismatch checks, (e) lower ledger durability for throughput.
5. **Capacity question:** At 1,800 payment creates/sec and 3.7x retry amplification, what is the attempted payment-create rate? What does this do to PSP and idempotency capacity?
6. **Org/runbook question:** What changes are required in payment timeout policy, ledger durability, reconciliation, and incident ownership?

---

## Self-Score Error-Type Table

| Error type | Count | Notes to review |
|------------|-------|-----------------|
| Ledger/accounting model error | | |
| Idempotency/retry error | | |
| PSP reconciliation error | | |
| Saga/order-state error | | |
| Replication/failover error | | |
| Kafka/outbox error | | |
| Capacity math error | | |
| Org/runbook gap | | |

---

> **Answer key (do not open until you attempt the test):**  
> [`../answers/Retention-Tests/Week-11 Answers.md`](../answers/Retention-Tests/Week-11%20Answers.md)
