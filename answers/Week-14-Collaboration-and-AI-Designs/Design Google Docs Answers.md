# Answer Key — Design Google Docs

> Open only after attempting the learner file questions.

## Expert Analysis

### Q1: Most Likely Bug Class

```
Transform optimization likely skipped edge case in concurrent
insert+delete at same offset (classic OT pitfall).

Evidence:
  - Single doc_id dominating errors → deterministic repro
  - revision_gap_fetch spike → clients detecting revision mismatch
  - Text "reverting" → server acked transformed op client couldn't apply

The optimization probably memoized transform results by op TYPE pair
(insert, delete) without including context (offset overlap class).
```

### Q2: Worked Answer

```
ANSWER Q2:

  Priority 2: Rollback deploy first
  Enable read-only mode flag for hot doc_ids




  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
```

### Q3: Worked Answer

```
ANSWER Q3:

  Priority 3: Isolate affected doc_ids via log query

  Run checksum bot against top 1000 active docs



  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
```

### Q4: Worked Answer

```
ANSWER Q4:

  Priority 4: Isolate affected doc_ids via log query


  Replay ops from immutable log with v2.13.0 transform library


  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
```

### Q5: Worked Answer

```
ANSWER Q5:

  Priority 5: Isolate affected doc_ids via log query



  Mandatory 1M-op property test in CI + 24h canary at 1% traffic

  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
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

- Identify the highest-amplification actor in `Design Google Docs`: the one that can turn
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
