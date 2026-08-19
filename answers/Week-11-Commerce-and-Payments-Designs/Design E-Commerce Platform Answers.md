# Answer Key — Design E-Commerce Platform

> Open only after attempting the learner file questions.

## Expert Analysis


### Q1: Immediate

```
1. Enable checkout queue (feature flag) — return 202, scale workers 20→200
2. Emergency inventory: cap 1 pair per user_id (DynamoDB condition on cart)
3. CloudFront: enable stale-if-error on /api/public/plp (origin failing)
4. Search: manual indexer flip in_stock=false for LIMITED-SNEAKER-2026
   (emergency override endpoint — documented break-glass)
```

### Q2: User Journey

```
User sees in_stock=true (90s stale index) → PDP CDN cached OK →
Add to cart OK (reservation competes) → Checkout fails reserve or OOS →
Anger. Fix: checkout always hits inventory truth; search lag display only.
```

### Q3: Bot fairness

```
WAF rate limit: 10 add-to-cart/min/IP
Require login 5 min before sale for high-heat SKU
Device fingerprint + CAPTCHA on checkout
Reservation tied to verified user_id max qty 1
```

### Q4: CDN miss spike

```
Deploy added ?v=2.14 to PLP API URLs → new cache key → 100% miss
Week 1 lesson: version in path not arbitrary query params for CDN keys
Rollback query param; warm cache via synthetic crawler pre-sale
```

### Q5: 48-hour fixes

```
- Mandatory checkout queue for heat-check SKUs
- Inventory shard auto-scaling + pre-warm
- Search: priority lane for in_stock updates on flash SKUs
- CDN: documented cache key policy review in deploy checklist
- Game day: flash sale rehearsal quarterly
```

### Q6: Extended analysis — inventory shard math

```
Question: Drill-down 6 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q6_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q06

Quantified example for Q6:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q7: Extended analysis — CDN cache key audit

```
Question: Drill-down 7 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q7_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q07

Quantified example for Q7:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q8: Extended analysis — search freshness SLO

```
Question: Drill-down 8 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q8_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q08

Quantified example for Q8:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q9: Extended analysis — inventory shard math

```
Question: Drill-down 9 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q9_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q09

Quantified example for Q9:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q10: Extended analysis — CDN cache key audit

```
Question: Drill-down 10 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q10_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q10

Quantified example for Q10:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q11: Extended analysis — search freshness SLO

```
Question: Drill-down 11 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q11_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q11

Quantified example for Q11:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q12: Extended analysis — inventory shard math

```
Question: Drill-down 12 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q12_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q12

Quantified example for Q12:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q13: Extended analysis — CDN cache key audit

```
Question: Drill-down 13 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q13_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q13

Quantified example for Q13:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q14: Extended analysis — search freshness SLO

```
Question: Drill-down 14 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q14_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q14

Quantified example for Q14:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q15: Extended analysis — inventory shard math

```
Question: Drill-down 15 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q15_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q15

Quantified example for Q15:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q16: Extended analysis — CDN cache key audit

```
Question: Drill-down 16 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q16_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q16

Quantified example for Q16:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q17: Extended analysis — search freshness SLO

```
Question: Drill-down 17 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q17_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q17

Quantified example for Q17:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q18: Extended analysis — inventory shard math

```
Question: Drill-down 18 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q18_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q18

Quantified example for Q18:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q19: Extended analysis — CDN cache key audit

```
Question: Drill-down 19 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q19_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q19

Quantified example for Q19:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q20: Extended analysis — search freshness SLO

```
Question: Drill-down 20 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q20_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q20

Quantified example for Q20:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```

---

---

## Design Gates (mandatory) - Model Responses

These responses are intentionally gate-shaped rather than a second full design.
Use them to verify the design explicitly covers trust, abuse, tenancy, cost,
and blast radius.

### Gate 1 - Authn/z trust boundary

- State every principal: external user, internal service, admin/support actor,
  background worker, tenant, and third-party partner where applicable.
- Put the first trust boundary at the public edge or private service ingress,
  then name the enforcement point that owns object/action authorization.
- Accept only scoped identity artifacts with issuer, audience, expiry, and
  key/certificate validation. Service-to-service calls should use workload
  identity or mTLS, not ambient network trust.
- Fail closed for money, privacy, admin, and write paths. Degrade or serve
  cached public content only where policy explicitly allows it.

### Gate 2 - Abuse and misuse

- Identify the highest-amplification actor in `Design E-Commerce Platform`: the one that can turn
  one request into many writes, fetches, fan-outs, model calls, or downstream
  retries.
- Use layered quotas: user/API key, tenant/tier, entity key, endpoint/job
  class, region/cell, and global safety cap.
- Distinguish organic flash traffic from abuse with per-key skew, user-agent
  or principal entropy, retry rate, error mix, and historical baselines.
- Bound retries with budgets, jitter, circuit breakers, and idempotency keys.

### Gate 3 - Multi-tenant isolation

- Name the tenancy model for every stateful plane: relational data, cache,
  queue/topic, object storage, search index, model/vector store, metrics, logs,
  and support exports.
- Tenant context must be explicit in APIs, async messages, cache keys, search
  filters, audit logs, and support tooling. Missing tenant context fails closed.
- Reserve or quota shared scarce resources: DB connections, Kafka partitions
  and bytes, cache memory/ops, worker concurrency, indexing bandwidth, and
  third-party API calls.
- Prove isolation with cross-tenant cache/search/export tests, route-map tests,
  and incident kill switches for one tenant or cell.

### Gate 4 - Unit cost at target scale

- Define one business unit and compute order-of-magnitude cost at target scale
  and at peak multiplier. Include idle headroom and replication, not only
  request CPU.
- Dominant line items usually include storage retention, egress/cross-AZ or
  cross-region transfer, observability ingest, model/API calls, NAT, cache
  memory, and replay/rebuild capacity.
- Page on cost per successful business unit and slope by feature/deploy/tenant,
  not only monthly spend after the fact.
- Preferred degradation cuts optional analytics, freshness, ranking depth,
  export concurrency, or non-critical replicas before correctness-critical
  writes and reads.

### Gate 5 - Failure blast radius

- Declare the intended blast-radius boundary: partition, shard, tenant, topic,
  cell, region, queue, worker pool, cache namespace, or model version.
- Separate critical and non-critical paths so analytics, exports, replay,
  recommendation/ranking, or support tooling cannot starve checkout, payment,
  auth, or core serving.
- Document runbook hazards: global cache flush, raising max connections,
  disabling auth, removing rate limits, replaying without throttle, or widening
  a feature flag globally.
- Game day the highest-risk boundary and verify alerts fire before customer or
  tenant-wide impact.


---
