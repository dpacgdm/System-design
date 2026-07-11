# Transfer Drill: Patterns Northstar - The Refund Furnace

**Time box:** 70 minutes
**Concept range:** Weeks 5-8 and 08b
**Novel failure:** A refund pipeline brownout combining queue semantics, saga compensation, outbox/CDC lag, observability cardinality, auth key rotation, tenant isolation, and cost controls.

## Rules

1. Do not use Week 6 or Week 8 answer files.
2. Preserve money and tenant isolation before throughput.
3. Explain why each tempting fix changes load, correctness, or blast radius.
4. Include one capacity or cost calculation in every major decision.

---

## 1. Scenario stem

```text
Northstar launches instant refunds for enterprise sellers.
Refunds are orchestrated as sagas:
  Refund API -> Saga Orchestrator -> Payment Gateway -> Ledger -> Notification
Events are written to an outbox table and published by Debezium to Kafka.
Tenant-specific read models are updated by consumers.
Auth uses OIDC JWTs and JWKS rotation.
Observability uses Prometheus, Loki, traces, and wide events.

At 11:00 UTC, a payment provider latency spike overlaps with a JWKS rotation,
a Kafka consumer rebalance, and a new per-tenant metrics label.
```

---

## 2. Telemetry pack

```text
SAGA / REFUNDS:
  refund requests: 1,200/min -> 8,600/min
  orchestrator running sagas: 4,800 -> 74,000
  payment authorize p99: 180ms -> 7.4s
  compensation queue depth: 0 -> 1.8M
  duplicate refund attempts blocked by idempotency: 12/min -> 19,000/min
  refunds stuck in PAYMENT_UNKNOWN: 0 -> 38,000

OUTBOX / CDC / KAFKA:
  outbox rows pending: 14,000 -> 3.7M
  oldest outbox age: 22s -> 47m
  Debezium connector CPU: 78%
  Kafka topic partitions: refunds.events = 12
  consumer group rebalance count: 2/hr -> 180/hr
  max.poll.interval.ms: 300000
  consumer processing p99: 420s
  poison message tenant: seller-redwood

AUTH / JWKS:
  token validation failures: 0.1% -> 17%
  JWKS endpoint p99: 40ms -> 2.9s
  JWKS cache TTL: 5s
  negative cache TTL for unknown kid: 0s
  signing keys active: old + new for 30m
  services accepting alg=none in local-dev profile: true

OBSERVABILITY:
  metrics ingest samples/sec: 1.8M -> 14M
  Prometheus head memory: 62GB -> 118GB
  new labels:
    tenant_id
    refund_id
    exception_message
  trace sampling: 100% for refunds during incident
  Loki ingest: 900GB/day -> 5.8TB/day

TENANCY / COST:
  enterprise tenant seller-redwood owns 41% of stuck refunds
  shared refund worker pool: 600 workers
  seller-redwood consumes 510 workers
  other tenants p95 refund latency: 3s -> 14m
  NAT gateway data processing: 2TB/day -> 11TB/day
  payment provider retry egress: 380GB/day -> 2.7TB/day
```

---

## 3. Wrong config pack

```yaml
refund_saga:
  payment_timeout: 30s
  user_slo: 3s
  compensation_retry:
    max_attempts: unlimited
    backoff: fixed_1s
  idempotency_key_scope: refund_id_only

outbox:
  publisher_mode: debezium
  outbox_table_partitioning: none
  consumer_idempotency: best_effort_memory_cache

kafka:
  refunds_events_partitions: 12
  consumer_max_poll_interval_ms: 300000
  poison_message_strategy: retry_forever_same_partition
  cooperative_rebalance: false

auth:
  jwks_cache_ttl: 5s
  unknown_kid_negative_cache_ttl: 0s
  allowed_algs: [RS256, none]
  issuer_pin: "https://issuer.northstar.example"

observability:
  metric_labels: [tenant_id, refund_id, exception_message]
  trace_sample_rate_refunds: 1.0
  log_full_jwt_claims: true

tenancy:
  worker_pool: shared_global
  per_tenant_concurrency_cap: none
  dlq_scope: shared
```

---

## 4. T+ timeline

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | Refund latency spikes; stuck sagas begin accumulating. | |
| T+5 | Auth failures and JWKS traffic spike; dashboards slow down. | |
| T+15 | seller-redwood poison messages monopolize workers; other tenants impacted. | |
| T+60 | Money movement is paused for some tenants; backlog is huge; CFO asks cost impact. | |

---

## 5. Bad fixes

1. Turn off idempotency checks to drain refunds faster.
2. Increase compensation retries to every 100ms.
3. Delete old JWKS key immediately because new key is active.
4. Add `user_id` and `jwt` as metric labels for debugging.
5. Replay the shared DLQ without tenant filtering.
6. Scale refund workers 10x with no provider rate limit.
7. Disable auth for internal refund workers during the incident.
8. Set Kafka partitions from 12 to 200 immediately without a keying review.

---

## 6. Capacity and cost worksheet

```text
Refund worker pool:
  total workers = 600
  seller-redwood workers = 510
  remaining workers = ______
  percent captured by one tenant = ______

Kafka partitions:
  partitions = 12
  consumer processing p99 = 420s
  max.poll.interval.ms = 300s
  what happens? ______

Observability:
  samples/sec before = 1.8M
  samples/sec after = 14M
  multiplier = ______

Cost:
  NAT data/day before = 2TB
  NAT data/day after = 11TB
  extra data/day = ______
  which retries likely drive it? ______
```

---

## 7. Questions

**Q1 - Problem inventory:** Identify at least eight mechanisms across saga, Kafka, outbox, auth, observability, tenancy, and cost.

**Q2 - Correctness first:** Which actions protect money movement and idempotency before throughput? What should be paused?

**Q3 - Saga repair:** How do you handle `PAYMENT_UNKNOWN`, compensation retries, and stuck saga logs safely?

**Q4 - Kafka/outbox repair:** Explain the rebalance loop and poison-message pattern. What should happen to seller-redwood messages?

**Q5 - Auth repair:** Fix JWKS caching and algorithm validation without breaking valid old tokens.

**Q6 - Observability repair:** Which labels/sampling/logging must be rolled back immediately and why?

**Q7 - Tenant isolation:** How do you restore fairness without losing seller-redwood's audit trail?

**Q8 - Cost response:** Estimate the multiplier and name the cost drivers. What can be degraded without hiding safety signals?

**Q9 - Bad fix rejection:** Reject each bad fix with mechanism and safer alternative.

**Q10 - Verification:** List metrics that prove each subsystem is recovering.

**Q11 - Principal stretch:** Propose a durable operating model for refund sagas: ownership, runbooks, limits, audits, and cost guardrails.

---

## 8. Self-score

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Money correctness sacrificed | | |
| Idempotency weakened | | |
| Auth bypass accepted | | |
| Cardinality explosion missed | | |
| Tenant isolation missed | | |
| Cost ignored | | |

**Answer key:** [`../answers/Ops-Sims/Transfer-Patterns-Northstar Answers.md`](../answers/Ops-Sims/Transfer-Patterns-Northstar%20Answers.md)
