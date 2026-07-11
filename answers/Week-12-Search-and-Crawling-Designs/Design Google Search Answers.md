# Answer Key - Design Google Search

> Open only after attempting the learner file questions.

## Expert Analysis — Full Worked Response

---

### Question 1: Symptom Mapping and Causal Chain

#### Subsystem Assignment

```
SYMPTOM → SUBSYSTEM → ROLE IN CASCADE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  A. null_result_rate brand 3.8%     → QUERY/RANK (victim + partial cause)
  B. Ad CTR drop, wrong doc_ids      → QUERY/RANK + INDEX (victim)
  C. Crawler queue 890M, amazon stuck → CRAWL (amplifier — separate issue)
  D. Shard 7 UNASSIGNED / red        → INDEX (infrastructure failure)
  E. Top results are 404 / 6mo old   → INDEX + CACHE (victim)
  F. Partial update missing price    → INDEX (indexer overload symptom)
  G. Query cache 940s stale SERPs    → CACHE (amplifier — masks severity)
  H. index_lag 4200s, crawl normal → INDEX (core pathology)
```

#### The Causal Chain (Root Cause → Amplifiers → Victims)

```
TRIGGER (06:00): Ranking model v2.14 — freshness weight +40%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  v2.14 aggressively demotes documents with old crawl_timestamp.
  Merchant CDC pushed 200K price updates at 05:30, BUT index_lag was
  already rising (indexer fleet saturated from Black Friday prep).

  At 06:12, brand queries fail because:
    1. Fresh product pages exist in Kafka (docs.parsed backlog)
    2. Stale pages still in serving index have OLD crawl dates
    3. v2.14 demotes stale pages below relevance threshold
    4. Brand query expects exact SKU match → zero candidates pass cutoff
    → Symptom A (null results on brand queries)

  This is NOT purely a ranking bug — it's ranking change interacting
  with PRE-EXISTING index lag.

PARALLEL AMPLIFIER (06:24): Crawl queue explosion — SEPARATE TRACK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom C (890M queue, amazon.com stuck) is largely INDEPENDENT:
    → Black Friday recrawl push (+20% fleet) discovered massive URL fanout
    → amazon.com politeness bucket drained to 0, refill stuck (Redis hot key?)
    → Frontier keeps enqueueing discovered URLs faster than drain rate
    → Queue depth explodes WITHOUT increasing successful fetch rate

  This worsens Symptom H long-term (more URLs waiting) but did NOT
  cause the 06:12 null-result spike — crawl rate is still "normal"
  because "completed" counts fetches that return 429/503 as well.

INFRASTRUCTURE FAILURE (06:30): Shard 7 primary UNASSIGNED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom D is likely caused by indexer saturation (Symptom H):
    → 200K partial updates + 2.1M Kafka backlog → bulk indexing storm
    → Shard 7 node ran out of disk during segment merge
    → OR: JVM OOM killed shard 7 primary during merge
    → Primary unassigned → cluster red → queries hitting shard 7 fail

  Shard 7 failure → more queries retry → more load → worse lag
  Classic cascade amplifier.

CACHE AMPLIFIER (06:31+): stale-if-error engaged
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  When OpenSearch went red (06:30), CloudFront origin health check failed.
  stale-if-error policy: serve cached SERP even if expired.
  Symptom G: users see 940-second-old results including 404 doc_ids
  Symptom E: "6 month old dead links" — cache + old index generation
  Symptom B: ads matched to cached doc_ids no longer in index

  Query p99 118ms is MISLEADING — 67% cache hit rate masks 890ms misses.

VICTIM SUMMARY:
━━━━━━━━━━━━━━━

  Root trigger:     v2.14 ranking deploy on already-lagging index (A)
  Index pathology:  Kafka backlog + indexer saturation (H, F)
  Infra failure:    Shard 7 disk/OOM from merge storm (D)
  Cache amplifier:  stale-if-error hiding red cluster (G, E, B)
  Separate track:   Crawl politeness leak on amazon.com (C)
```

#### Why One Root Cause Is Insufficient

Production compound incidents rarely have a single root cause. Here:

```
PRIMARY ROOT CAUSE (ranking):
  Freshness weight +40% on index with 70-minute lag = null results

PRECONDITION (indexing):
  Index lag was already climbing BEFORE deploy (120s → would have hit
  4200s regardless — deploy made it user-visible)

AMPLIFIER (infrastructure):
  Indexer saturation caused shard 7 failure

AMPLIFIER (cache):
  stale-if-error turned backend outage into user-visible staleness

INDEPENDENT (crawl):
  amazon.com politeness — must fix but not caused by ranking deploy
```

**Interview soundbite:** "I'd triage D (shard red) as immediate P1 infra, rollback v2.14 as immediate P1 product, and disable stale-if-error as immediate P1 cache — in parallel, three engineers, three workstreams."

---

### Question 2: Why Crawl Green ≠ Search Fresh

#### The Decoupling Explained

```
CRAWL SUBSYSTEM measures:
  "Did the fetcher successfully HTTP GET this URL?"

INDEX SUBSYSTEM measures:
  "Is this document tokenized, posted, merged, and visible in the
   serving index generation that query nodes read?"

These are connected by an ASYNC QUEUE (Kafka docs.parsed).
```

#### Step-by-Step: Where Documents Get Stuck

```
TIMELINE for a single Nike product page:

  05:32  Crawler fetches nike.com/air-max-90 → HTTP 200 ✓
         crawl_completed_total++  (DASHBOARD GREEN)

  05:32  Raw HTML written to Kafka crawl.raw

  05:33  Parser consumes, emits to docs.parsed

  05:33  Doc Builder SHOULD bulk-index to OpenSearch
         BUT: indexer CPU already 88%, bulk queue full
         Message sits in Kafka partition 7, offset 8912341

  06:15  Same URL still in Kafka backlog — NOT in serving index
         crawl_timestamp in DB: 05:32 (looks "fresh" to crawler)
         OpenSearch: doc missing OR old generation without this SKU

  06:15  User searches "nike air max 90"
         v2.14: freshness_score weighs crawl_date heavily
         Best match has crawl_date=2024-05-01 (6 months ago)
         Demoted below null threshold → ZERO RESULTS

  Crawl dashboard: GREEN (fetch succeeded 43 minutes ago)
  User experience: BROKEN (document not searchable)
```

#### The Metric That Proves Indexing Is Broken

```
SMOKING GUN METRIC:

  index_lag_seconds = now() - max(indexed_at) for docs in Kafka vs ES

  At 06:54: index_lag_seconds = 4200 (70 minutes)

  CORROBORATING METRICS:
    kafka_consumer_lag{group="doc-builder", topic="docs.parsed"} = 2.1M
    indexer_cpu = 94%
    index_rate_docs_per_sec: dropped from 8000 to 400 while
      crawl_ingress_docs_per_sec: still 7500

  THE PROOF:
    crawl_ingress_rate (7500/sec) >> index_egress_rate (400/sec)
    → backlog MUST grow
    → crawl dashboard irrelevant

  ANALOGY for junior engineer:
    "The warehouse receiving dock (crawl) is working fine.
     The shelving team (indexers) is 70 minutes behind.
     Customers asking for items added today get 'not found'
     even though the truck delivered this morning."
```

#### Why crawl_completed_total Lies

```
crawl_completed_total increments on:
  ✓ HTTP 200 with body
  ✓ HTTP 304 Not Modified
  ✓ Sometimes HTTP 429/503 (logged as "attempted")

It does NOT measure:
  ✗ Document parsed successfully
  ✗ Document indexed in OpenSearch
  ✗ Document visible in query results
  ✗ Document has correct price field after partial update

PRODUCTION FIX: single "freshness SLO" metric:
  search_freshness_lag_p95 = percentile(crawl_time - searchable_time)
  Alert when p95 > 300 seconds — regardless of crawl dashboard color
```

---

### Question 3: Immediate Mitigation (30-Minute Playbook)

#### Priority Order

```
MINUTE 0–5: STOP THE BLEEDING (parallel workstreams)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ACTION 1 [P0]: Rollback ranking model v2.14 → v2.13
  ─────────────────────────────────────────────────
  Owner: ML platform on-call
  Effect: Restores null_result_rate on brand queries within 2 min
  Risk: LOW — v2.13 was stable for 3 weeks

  Exact steps:
    aws sagemaker update-endpoint --endpoint-name search-ltr-prod \
      --endpoint-config-name search-ltr-v2-13-config

    # OR feature flag (faster if wired):
    curl -X PATCH https://config.internal/flags/search_ltr_model \
      -d '{"value": "v2.13", "rollout": 100}'

    # Verify:
    curl -s https://config.internal/flags/search_ltr_model | jq .value
    # Watch: null_result_rate{query_type="brand"} drop within 5 min

  ACTION 2 [P0]: Disable stale-if-error on query cache
  ────────────────────────────────────────────────────
  Owner: Edge/CDN on-call
  Effect: Users see errors instead of 404 results — honest failure
  Risk: MEDIUM — error rate spike short-term, but stops lying to users

  aws cloudfront update-distribution --id E1234567890 \
    --if-match $ETAG \
    --distribution-config file://config-no-stale-if-error.json

  # Emergency Redis flush if CloudFront change slow:
  redis-cli -h query-cache-prod.cache.amazonaws.com \
    --scan --pattern 'qcache:*' | head -10000 | xargs redis-cli DEL

  ACTION 3 [P0]: Restore shard 7 primary
  ─────────────────────────────────────
  Owner: Search infra on-call
  Effect: Cluster red → yellow/green; queries stop failing on shard 7
  Risk: MEDIUM — may need disk cleanup or node replacement

  (See Question 4 for full diagnosis — start immediately)


MINUTE 5–15: SHED LOAD ON INDEXING PATH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ACTION 4 [P1]: Pause non-essential crawl sources
  ─────────────────────────────────────────────────
  Effect: Reduces Kafka ingress from 7500 → ~3000 docs/sec
  Risk: LOW for product search — blog/rec crawl not needed today

  kafka-configs.sh --bootstrap-server $BROKERS \
    --entity-type topics --entity-name crawl.raw.blog \
    --alter --add-config retention.ms=1000
  # Effectively drop messages (emergency only — document in incident)

  # Better: disable crawl scheduler jobs
  aws ecs update-service --cluster crawl-prod \
    --service crawl-fetcher-low-priority --desired-count 0

  DO NOT: Scale UP crawlers — worsens Kafka backlog

  ACTION 5 [P1]: Scale indexer consumers horizontally
  ─────────────────────────────────────────────────────
  Effect: Increase index egress rate
  Risk: LOW if cluster has headroom; watch OpenSearch master CPU

  aws ecs update-service --cluster index-prod \
    --service doc-builder --desired-count 48
  # Was 24 — double consumers in same Kafka group

  kafka-consumer-groups.sh --bootstrap-server $BROKERS \
    --group doc-builder-v3 --describe
  # Verify: LAG decreasing after 5 min

  ACTION 6 [P1]: Boost merchant.updates topic priority
  ──────────────────────────────────────────────────────
  Effect: 200K price updates indexed before blog backlog
  Risk: LOW — business-critical path

  # Reassign indexer pods to dedicated consumer group for merchant topic
  kubectl scale deployment doc-builder-merchant --replicas=16


MINUTE 15–30: STABILIZE AND COMMUNICATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ACTION 7 [P2]: Emergency CMS fallback for zero-result brand queries
  ───────────────────────────────────────────────────────────────────
  Effect: Exact SKU lookup via Postgres when ES returns 0 hits
  Risk: LOW — already built for admin, wire to query coordinator

  ACTION 8 [P2]: Status page + revenue team comms with ETA
  ─────────────────────────────────────────────────────────
  ETA math:
    LAG = 2.1M messages, egress = 400/sec (current) → 5250 sec (87 min)
    After scale to 48 consumers, egress ≈ 1200/sec → 1750 sec (29 min)
    Communicate: "Search freshness degraded, ETA 30 min to normalize"

  ACTION 9 [P2]: Fix amazon.com politeness (parallel track)
  ───────────────────────────────────────────────────────────
  redis-cli -h politeness.cache.amazonaws.com DEL politeness:amazon.com
  redis-cli HSET politeness:amazon.com tokens 2 refill_rate 0.5
  # Halve amazon.com rate until queue drains
```

#### What You Must NOT Do

```
DO NOT:
  ✗ Scale crawl fleet UP — adds Kafka pressure, worsens index lag
  ✗ Deploy hotfix to v2.14 ("tweak freshness weight") — untested under load
  ✗ Force-merge OpenSearch indices during incident — IO storm kills nodes
  ✗ Alias swap to incomplete index generation — ad doc_id chaos
  ✗ Ignore shard 7 red while fixing ranking — 8.3% of docs unreachable
  ✗ Full query cache flush WITHOUT disabling stale-if-error first
      → thundering herd on red cluster kills remaining nodes
```

---

### Question 4: Shard 7 UNASSIGNED — Diagnosis Walkthrough

#### Step 1: Confirm Shard State

```bash
# Which shard is broken?
curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cat/shards/catalog-v3?v&h=index,shard,prirep,state,unassigned.reason,node" \
  | grep -E "UNASSIGNED|shard"

# Expected output:
# catalog-v3  7  p  UNASSIGNED  ALLOCATION_FAILED  -
# catalog-v3  7  r  STARTED     -                  ip-10-0-1-42
```

#### Step 2: Read Allocation Explanation

```bash
curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cluster/allocation/explain?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "index": "catalog-v3",
    "shard": 7,
    "primary": true
  }'

# Common decision strings:
#   "disk threshold exceeded"     → disk full (MOST LIKELY during bulk index)
#   "no valid shard copy"         → all replicas corrupted
#   "awareness attributes"        → AZ imbalance
#   "too many open files"         → ulimit issue
```

#### Step 3: Check Node Disk and JVM

```bash
# Disk usage per node
curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cat/nodes?v&h=name,disk.used,disk.total,disk.used_percent,heap.max,heap.current,cpu"

# AWS OpenSearch — check EBS volume
aws opensearch describe-domain --domain-name prod-search \
  --query 'DomainStatus.EBSOptions'

# CloudWatch disk alarm
aws cloudwatch get-metric-statistics \
  --namespace AWS/ES \
  --metric-name ClusterUsedSpace \
  --dimensions Name=DomainName,Value=prod-search \
  --start-time 2024-11-29T05:00:00Z \
  --end-time 2024-11-29T07:00:00Z \
  --period 300 --statistics Maximum
```

#### Step 4: Distinguish Root Causes

```
IF disk.used_percent > 85% on former shard 7 node:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CAUSE: Bulk index + segment merge filled disk
  EVIDENCE: index_rate spike at 05:30 correlates with disk climb
  FIX:
    1. Delete old index generations: curl -X DELETE .../catalog-v2
    2. Increase EBS volume (AWS console or API)
    3. reroute shard after disk freed:
       curl -X POST .../_cluster/reroute -d '{
         "commands": [{
           "allocate_empty_primary": {
             "index": "catalog-v3", "shard": 7,
             "node": "ip-10-0-1-99", "accept_data_loss": false
           }
         }]
       }'
    4. If replica intact: prefer allocate_stale_primary from replica

IF heap.percent = 100 + GC logs show OOM:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CAUSE: Mapping explosion OR fielddata on text field
  CHECK:
    curl -s .../catalog-v3/_mapping | jq '.[] | .mappings.properties | keys | length'
    # > 10000 fields = mapping explosion
  FIX: Roll back bad mapping deploy; restore from snapshot

IF node absent from _cat/nodes:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CAUSE: EC2 instance terminated / AZ outage
  FIX: AWS OpenSearch auto-replaces; wait or trigger manual restore
    aws opensearch describe-domain --domain-name prod-search \
      --query 'DomainStatus.Processing'
```

#### Step 5: Recovery Without Data Loss

```bash
# Preferred: restore primary from replica (if replica STARTED)
curl -s -X POST -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cluster/reroute" \
  -H "Content-Type: application/json" \
  -d '{
    "commands": [{
      "allocate_stale_primary": {
        "index": "catalog-v3",
        "shard": 7,
        "node": "ip-10-0-1-42",
        "accept_data_loss": false
      }
    }]
  }'

# Verify recovery
watch -n5 'curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cluster/health?pretty" \
  | grep -E "status|unassigned"'
```

---

### Question 5: 30-Day Roadmap — Prevent Recurrence

#### Week 1: Incident-Driven Hotfixes

```
DAY 1–3: Ranking deploy governance
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  □ Mandatory canary: 1% → 5% → 25% → 100% over 48h (remove VP override path)
  □ Shadow mode: log v2.14 scores alongside v2.13 for 24h before any promotion
  □ Golden query set (1000 navigational + 1000 brand) — automated NDCG check
  □ Rollback button: one-click feature flag, < 60 second SLA

DAY 3–5: Freshness SLO
━━━━━━━━━━━━━━━━━━━━━━
  □ Deploy search_freshness_lag_p95 metric (crawl_time → searchable_time)
  □ Page exec when p95 > 300s (not crawl dashboard)
  □ Separate hot pipeline for merchant.updates (already started in incident)
  □ Autoscale doc-builder on kafka_consumer_lag derivative

DAY 5–7: Cache policy
━━━━━━━━━━━━━━━━━━━━━
  □ Remove stale-if-error for search SERPs (keep for static assets only)
  □ Cache key includes index_generation_id — auto-invalidate on alias swap
  □ Max stale Age: 60s hard cap even during origin errors
  □ Alert: query_cache_hit_rate > 60% AND cluster_health != green
```

#### Week 2–3: Infrastructure Hardening

```
INDEX CAPACITY
━━━━━━━━━━━━━━
  □ Load test: 2× Black Friday ingest on staging BEFORE event
  □ Indexer fleet autoscale policy tied to kafka_lag, not CPU
  □ Disk watermark alerts at 70% (not 85%)
  □ Quarterly restore drill from automated snapshot

SHARD RESILIENCE
━━━━━━━━━━━━━━━━
  □ Reduce replicas from 15 → 2 for non-query-critical shards
    (15 replicas = 15× merge work — contributed to disk exhaustion)
  □ Dedicated query replicas loaded from immutable snapshots
  □ Shard size target: < 50GB per primary (split catalog-v4)

CRAWL POLITENESS
━━━━━━━━━━━━━━━━
  □ Alert: politeness tokens=0 for > 5 min on any top-100 host
  □ Max frontier depth per host: 100K (hard cap)
  □ Redis hot-key mitigation: hash tags → politeness:{amazon.com} on dedicated shard
  □ Trap detection: auto-reduce host priority when URL/content ratio > 1000
```

#### Week 4: Process and Testing

```
COMPOUND INCIDENT SIMULATION (game day)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Scenario: ranking deploy + index lag + shard failure simultaneously
  Success criteria:
    □ Rollback < 5 min
    □ Freshness SLO alert fires BEFORE user reports
    □ No stale-if-error SERPs served
    □ Shard recovery < 15 min from runbook

DOCUMENTATION
━━━━━━━━━━━━━
  □ Update on-call runbook with "crawl green ≠ fresh" section
  □ Decision tree poster: symptom → subsystem mapping
  □ Post-mortem published with action item owners and dates
```

#### Architecture Evolution (60–90 Day)

```
  Blue/green index generations with checksum gate before alias swap
  Separate OpenSearch domains: catalog-hot (merchant) vs catalog-cold (web)
  Head query overlay index for top 10K brand queries
  Ranking feature store: freshness_score computed from indexed_at, not crawl_time
    → eliminates class of bug where crawl fresh but index stale
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

- Identify the highest-amplification actor in `Design Google Search`: the one that can turn
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
