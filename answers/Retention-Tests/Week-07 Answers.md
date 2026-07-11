# Answer Key — Week-07

> Open only after attempting the learner file questions.

# WEEK 7 RETENTION TEST — ANSWERS

---

# Part 1: Rapid-Fire

---

**Q1 (Load Balancing — Heterogeneous Backends):**
Round-robin sends equal **request count** to unequal capacity pods — c5.xlarge pods saturate at 4 vCPU while c5.4xlarge pods have headroom, so requests queue on small pods → **p99 skews high on small instances**, low on large. Fix: **weighted round-robin** or **least-outstanding-requests (LOR)** on ALB, or homogenize instance types. LOR routes to pods with fewest in-flight requests, naturally favoring faster/emptier pods.

---

**Q2 (Load Balancing — Warmup Health Check):**
`/health` returning 200 only proves the process is up — not that JIT compilation, connection pools, or caches are warm. Fix: **readiness probe** that hits a representative endpoint (`/health/ready` runs a lightweight search query or warms caches) with a **startupProbe** allowing 90s before marking ready. **Connection draining (deregistration delay):** when old pods deregister, ALB stops sending NEW connections but allows in-flight requests to complete — prevents cutting warm connections during deploy.

---

**Q3 (Load Balancing — L7 vs Client round_robin):**
NLB distributes **TCP connections** — all gRPC streams multiplex on one HTTP/2 connection to one pod (Week 1 black hole). Client-side `round_robin` opens connections to all backends from each client — works if you have many client instances, but **20 checkout pods as clients still pin connections**. Envoy sidecar with `LEAST_REQUEST` balances **per-request at L7** — sees each gRPC RPC individually, not the TCP connection. Sidecar intercepts all outbound traffic from the pod regardless of client count.

---

**Q4 (Load Balancing — Cross-Zone):**
With cross-zone disabled, ALB routes clients only to targets in **the same AZ as the ALB node handling the request** — 80% of clients hit us-east-1a, but only 33% of pods are in 1a → **1a pods overloaded**, 1b/1c underutilized. Fix (config): **Enable cross-zone load balancing** on ALB. Fix (architectural): **Topology-aware routing** — pod anti-affinity weighted toward 1a to match traffic, or move majority of clients to Global Accelerator with balanced anycast.

---

**Q5 (Rate Limiting — Edge vs Origin Mismatch):**
CloudFront edge and origin ALB maintain **separate counters** with different window boundaries. Edge sliding window may show client at 950/1000 tokens (under limit) while origin's fixed window **just reset and already counted 1000 requests in the first 200ms** from other edge POPs aggregating to the same origin pool. Token bucket allows burst; origin may use stricter leaky bucket. **Clock skew and non-shared state** between edge and origin cause edge to forward requests origin rejects with 429.

---

**Q6 (Rate Limiting — Bucket Granularity):**
40 gateway instances each increment a Redis counter with **1s TTL buckets**. At exactly 10k req/s, each instance sends ~250 req/s — but bucket boundaries are not synchronized across instances. In any given 1s window, **some buckets overshoot** due to race conditions (read-modify-write without atomic Lua script) and clock drift between instances. ~15% of requests hit an instance whose local view exceeds 250. Fix: **GCRA (Generic Cell Rate Algorithm)** or **Redis sliding window with atomic Lua** script — single source of truth, sub-second precision.

---

**Q7 (Rate Limiting — Composite Keys):**
Limit dimensions: **API key / user ID** (identity) and **endpoint** (resource). Composite key: `{api_key}:{endpoint}` or `{user_tier}:{user_id}` — rate limit per identity regardless of NAT IP. For corporate NAT: use **API key tier limits** at gateway (not IP), with **separate burst allowance for known corporate key prefixes**. Adversary rotating 500 free keys still hits per-key limit; legitimate corporate users each have distinct keys.

---

**Q8 (Search — Indexing Backlog):**
Lever 1: Increase `refresh_interval` from 1s to 5s or 30s — reduces segment merge pressure (merchants wait longer for visibility). Lever 2: Increase shard count or bulk indexing batch size — spread write load. Architectural split: **separate indexing cluster from search cluster** (Cassandra-style write path / Elasticsearch search path) — indexers write to a dedicated ingest tier, search cluster serves queries only.

---

**Q9 (Search — AND Intersection):**
Iterate **`iphone` first** (2M postings — smaller set), then seek each posting in `electronics` (40M). Query order is irrelevant — **always intersect starting from the smallest posting list** to minimize comparisons. This is the WAND/Leapfrog optimization: scan the rare term, probe the common term's postings list for each doc ID.

---

**Q10 (Search — Staleness Budget):**
```
Postgres commit:           T+0ms
Debezium capture:          T+200ms (replication lag)
Kafka → ES indexer:        T+300ms (consumer processing)
ES bulk index:             T+400ms (indexer batch)
ES refresh (near-real-time): T+1400ms (refresh_interval=1s)
Search query sees new doc: T+1400ms worst case

User searches at T+500ms → sees OLD price.
Budget: 200ms CDC + ~100ms pipeline + up to 1000ms refresh = ~1300ms minimum staleness.
```

---

**Q11 (Unique IDs — Clock Skew):**
NTP step backward -500ms causes the Snowflake generator to **produce IDs with timestamps in the past** relative to recent IDs — breaks **monotonic sort order** (new inserts sort before older rows in B-tree indexes). B-tree locality degrades because inserts no longer append to the right edge — **page splits and fragmentation** increase. Mitigation: **wait until caught up** — generator blocks until timestamp exceeds last issued timestamp (Snowflake "clock backward" exception handling); use **logical clock lease** from coordination service.

---

**Q12 (Feature Flags — Kill-Switch Evaluation):**
**Server-side evaluation** for kill-switches. Client-side cache (60s TTL) means toggling off a broken payment provider takes up to 60s+ to reach all clients — during an incident, 90s of broken payments is unacceptable. Server-side: flag change takes effect on **next API request** (milliseconds with Redis-backed flag store), and the server controls routing — client cannot override or cache stale kill-switch state.

---

**Q13 (Unique IDs — UUID v4 B-Tree Fragmentation):**
UUID v4 is **random** — inserts land at random B-tree positions, causing **page splits across the entire index** rather than append-only right-edge inserts. Over 48h at 50k/s, the index becomes fragmented, cache locality destroyed, insert p99 degrades. **UUID v7 or Snowflake IDs** preserve rough time order — inserts append to the right edge, maintaining B-tree locality and insert performance.

---

**Q14 (Feature Flags — Canary Promotion):**
You might promote manually if v2 error rate (3%) reflects **expected errors from new index edge cases** (e.g., missing fields on legacy SKUs) fixable without rollback — auto-rollback would kill a good deploy. Watch **p99 latency by cohort** and **search result click-through rate (CTR)** — a canary can have low errors but 40% worse CTR if results are irrelevant, which error rate alone misses.

---

# Part 2: Compound SRE Scenario

---

## Question 1: Six Problems — Layer, Classification, Evidence

### Problem 1: Search p99 > 2s (Search Layer — Symptom)

**Root cause downstream:** ES cluster YELLOW, unassigned shards, RF=1 risk, merge throttling.
**Evidence:**
```
→ /search?q=launch-deal times out >5s at 10:18
→ ALB TargetResponseTime p99 4.2s on search-api
→ search-api CPU 35% (I/O wait on ES, not compute)
→ PagerDuty P1: search p99 > 2s (SLO 300ms)
```

---

### Problem 2: ES Cluster YELLOW / Unassigned Shards (Search Layer — Root Cause)

**Root cause:** `products_v2` deployed with **RF=1** (single copy) — scaling nodes does not create replicas; shard allocation rules or disk watermarks block assignment.
**Evidence:**
```
→ Cluster status YELLOW at 10:28
→ Scaled 6→12 data nodes at 10:55 — still YELLOW
→ "unassigned shards persist"
→ products_v2: RF=1 (cost save during dev — never changed for prod)
→ Hot threads: merge throttling active
```

---

### Problem 3: Debezium → ES Lag 12 min (CDC Layer — Root Cause / Amplifier)

**Root cause:** Indexing rate 8k docs/s exceeds ES ingest capacity on overloaded cluster — indexer consumers back up, Debezium consumer lag grows.
**Evidence:**
```
→ Debezium lag 12 min at 10:28, climbing
→ Indexing rate 8k docs/s
→ New products invisible to merchants (staleness)
→ Background reindex from v1 still running (competing I/O)
```

---

### Problem 4: Per-IP Rate Limit Blocks Corporate Users (Rate Limit Layer — Amplifier)

**Root cause:** Emergency 5k req/s per IP at CloudFront — corporate customers share one egress IP → **entire company throttled** as one "client."
**Evidence:**
```
→ Rate limit deployed 10:41
→ Support: "corporate customers blocked — shared egress IP"
→ Did NOT fix search latency or conversion
→ api-gateway 429 rate still 18%
```

---

### Problem 5: ID Mismatch — Search vs Checkout (IDs + Migration Layer — Root Cause)

**Root cause:** Strangler fig Phase 2 dual-write — search indexes **UUID v7**, checkout orders DB expects **bigint serial** — no ID mapping bridge.
**Evidence:**
```
→ 10:48: "Product IDs in search don't match checkout"
→ UUID v7 in search, bigint in orders DB
→ User finds SKU in search, add-to-cart: "product not found"
→ Strangler fig Phase 2 — reads split, writes dual
```

---

### Problem 6: Checkout Conversion Drop 22% (Symptom — Cross-Layer)

**Root cause:** NOT checkout failure — users find products in search, fail at cart, abandon. Conversion alert is a **downstream symptom** of Problems 1, 4, and 5.
**Evidence:**
```
→ checkout-svc metrics green (unchanged, healthy)
→ Conversion drop 22% correlates with search incident timeline
→ Symptom alert fired alongside search P1
→ Add-to-cart failures from ID mismatch + search timeout
```

---

## Question 2: YELLOW Cluster — Top Two Causes

### Cause 1: RF=1 with Node Loss or Disk Watermark

```bash
# Check unassigned shards
curl -s "$ES/_cat/shards?v&h=index,shard,prirep,state,unassigned.reason" \
  | grep UNASSIGNED

# Expected if RF=1 issue:
# products_v2  3  p  UNASSIGNED  NODE_LEFT
# (primary shard on dead node, no replica to promote)

curl -s "$ES/_cluster/allocation/explain" \
  -H 'Content-Type: application/json' \
  -d '{"index":"products_v2","shard":0,"primary":true}'

# Expected response:
# "decision": "NO"
# "explanation": "cannot allocate because no valid shard copies"
# OR "disk threshold exceeded"
```

**Fix:** Increase `number_of_replicas` to 1 minimum for production — `PUT /products_v2/_settings {"index.number_of_replicas": 1}`.

### Cause 2: Shard Count Exceeds Data Node Capacity (24 primaries, RF=1, disk)

```bash
curl -s "$ES/_cat/allocation?v&h=node,disk.percent,disk.used,disk.total"

# If any node > 85% disk:
# "decision": "NO", "explanation": "the node is above the 
# high watermark cluster setting [85%]"

curl -s "$ES/_cat/shards/products_v2?v" | wc -l
# 24 primary shards on 6 nodes = 4 shards/node
# After 6→12 scale, shards don't auto-rebalance if 
# cluster routing allocation is disabled or throttled
```

**Fix:** Enable allocation, add replicas, or reduce shard count on next reindex.

### ES Diagnostic Command Reference

```bash
# Full cluster health
curl -s "$ES/_cluster/health?pretty"
# YELLOW: "number_of_unassigned_shards": N

# Shard allocation explain for specific unassigned shard
curl -s "$ES/_cluster/allocation/explain?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "index": "products_v2",
    "shard": 0,
    "primary": true
  }'

# Common outcomes:
# NODE_LEFT: primary on dead node, RF=1 → data loss risk
# DISK_WATERMARK: "high watermark [85%] exceeded"
# ALLOCATION_DISABLED: "cluster routing allocation is disabled"

# Check if reindex is saturating thread pools
curl -s "$ES/_cat/thread_pool/write,search?v&h=node,name,active,queue,rejected"
# write.active=8, write.rejected>0 → indexing overloaded

# Recovery throttle settings
curl -s "$ES/_cluster/settings?include_defaults=true&filter_path=**.recovery*"
```

---

## Question 3: Rate Limiting Failures

**Per-IP at CloudFront harmed corporate users:**

Corporate offices route all employees through a **single NAT gateway IP** (or small IP pool). 5k req/s per IP means **500 employees collectively share 5k req/s** — one employee's search binge blocks colleagues. Legitimate high-volume corporate integrations (ERP, pricing bots) hit the limit instantly. CloudFront counts **per edge POP independently** — a user may pass edge check at POP-A but origin still overloads from aggregate global traffic.

**Global 10k/s Redis buckets allow 429s at steady 10k/s:**

40 gateway instances × ~250 req/s each = 10k req/s total — but Redis counter uses **1s fixed buckets with non-atomic increment**:

```
Instance A reads count=240, Instance B reads count=240 (same ms)
Both write 241 — lost update. Actual count 480, stored as 241.
OR: bucket rolls over at T=1.000 — 200 requests in last 100ms 
of old bucket + 200 in first 100ms of new bucket = 400 in 200ms 
window but each bucket shows 200 (under 250 limit per instance).
```

At exactly the limit, **probabilistic overshoot** causes ~15% false 429s. Steady 10k/s is the worst case — always at the boundary. **GCRA with centralized Redis Lua script** eliminates race conditions.

### Why 10:41 Emergency Rate Limit Made Things Worse

```
Before 10:41:
  - Search latency high (ES YELLOW) but corporate users could search
  - Conversion drop from ID mismatch + search timeout

After 10:41 (5k req/s per IP at CloudFront):
  - Corporate users: 500 employees × ~10 searches/min = blocked
  - Legitimate high-volume integrators throttled
  - Search latency UNCHANGED (origin ES still YELLOW)
  - Conversion drop WORSENED (corporate segment blocked entirely)

The rate limit treated SYMPTOM (high QPS) as CAUSE (abuse).
  Actual cause: ES cluster unhealthy + ID mismatch.
  Rate limit added a third failure mode without fixing either.
```

---

## Question 4: ID Mismatch Trace

```
User journey:
  1. Merchant creates SKU "launch-deal-2024" in products DB
     → Postgres assigns UUID v7: 018f3a2b-7c4d-7a8e-9f0b-1d2e3f4a5b6c
  2. Debezium → ES indexer → products_v2
     → Document indexed with id=018f3a2b-... (keyword field)
  3. User searches "launch deal" → ES returns UUID
  4. User clicks "Add to Cart"
     → checkout-svc queries orders DB: 
        SELECT * FROM products WHERE id = $1
     → Expects bigint: 8472918374 (legacy serial)
     → UUID lookup returns ZERO ROWS
  5. Error: "product not found"
```

**Strangler fig Phase 2 failure:** Reads split (search uses new catalog) but **writes to orders still use legacy bigint FK**. The **parity gate skipped: ID mapping table** — a `product_id_map (uuid, legacy_bigint)` table should have been populated during dual-write phase. Every new catalog write must **dual-write both IDs** until checkout migrates.

**Browse works because:** browse path reads Postgres products DB directly (UUID). Search works because ES has UUID. Checkout fails because **orders DB join path was not migrated**.

### Dual-Write Parity Gate (What Should Have Existed)

```
Required before Phase 2 read cutover:

  CREATE TABLE product_id_map (
    uuid_v7        UUID PRIMARY KEY,
    legacy_bigint  BIGINT NOT NULL UNIQUE,
    created_at     TIMESTAMPTZ DEFAULT now()
  );

  On every catalog write (dual-write phase):
    1. INSERT products (uuid_v7, ...)
    2. INSERT product_id_map (uuid_v7, legacy_bigint from sequence)
    3. Debezium indexes uuid_v7 to ES

  On add-to-cart:
    checkout-svc receives uuid_v7 from search result
    → SELECT legacy_bigint FROM product_id_map WHERE uuid_v7 = $1
    → INSERT order_line (product_id = legacy_bigint)

  SKIPPED GATE: Step 2 never implemented.
  Result: mapping table empty → all new SKUs fail checkout.
```

---

## Question 5: Three Reasons Canary Performs Worse

**1. Cold index / empty caches:**
products_v2 is newly created — **no OS page cache, no ES query cache, no filter cache**. 10% of traffic hits cold shards while 90% hits warm products_v1 with months of cached segments. Canary p99 reflects **disk I/O on cold data**, not code quality.

**2. Suboptimal shard topology:**
products_v2 has **24 shards, RF=1** vs v1's tuned 12 shards, RF=2. More shards = more segment files = **more merge pressure**. Canary queries scatter-gather across 24 primaries; v1 queries hit 12 warm shards with replicas for load sharing.

**3. Background reindex competing for I/O:**
Reindex from v1→v2 still running — ** steals disk I/O and indexing threads**. Canary queries scatter-gather across 24 primaries; v1 queries hit 12 warm shards with replicas for load sharing.

### Additional Canary Trap: Query Plan Regression

```
products_v2 mapping change:
  - title: analyzed with new ICU tokenizer
  - category: changed from keyword to text with subfields

Query: /search?q=launch-deal
  v1: keyword match on title.raw → 1 shard fanout, 12ms
  v2: ICU analyzer + 24 shard scatter-gather → 420ms

The CODE is "better" (multilingual support) but the INDEX DESIGN
makes the launch-day query path slower. Canary correctly identified
this — team misread "canary worse" as infra noise, not signal.
```

---

## Question 6: Rollback Sequence at 11:05

```
╔══════════════════════════════════════════════════════════════════════════╗
║  STEP │ ACTION                         │ RATIONALE                       ║
╠══════════════════════════════════════════════════════════════════════════╣
║   1   │ Disable search_v2_rollout        │ Stop sending traffic to       ║
║       │ canary → 0%                      │ broken v2 index immediately.  ║
║       │                                  │ 30s effect. Zero code deploy. ║
╠══════════════════════════════════════════════════════════════════════════╣
║   2   │ Set search_v2_index flag → v1    │ All queries route to warm,    ║
║       │                                  │ stable products_v1 index.     ║
║       │                                  │ Latency drops in ~60s.        ║
╠══════════════════════════════════════════════════════════════════════════╣
║   3   │ Remove CloudFront per-IP rate    │ Restore corporate access.     ║
║       │ limit (10:41 emergency rule)     │ Conversion recovery begins.   ║
║       │                                  │ Search load increases — v1    ║
║       │                                  │ must handle it (step 2 first) ║
╠══════════════════════════════════════════════════════════════════════════╣
║   4   │ Pause Debezium → ES indexer for  │ Stop flooding broken v2.      ║
║       │ products_v2 (keep v1 indexer)    │ Reduce ES cluster pressure.   ║
╠══════════════════════════════════════════════════════════════════════════╣
║   5   │ Roll back search-api deploy      │ Revert any query-logic        ║
║       │ (10:15 deploy)                   │ changes in application code.  ║
║       │                                  │ Only after traffic on v1.     ║
╠══════════════════════════════════════════════════════════════════════════╣
║   6   │ Fix ID mapping before re-enable    │ Add product_id_map table.   ║
║       │ (NOT same day — parity gate)       │ Dual-write UUID+bigint.     ║
╠══════════════════════════════════════════════════════════════════════════╣
║   7   │ ES: increase RF, cancel reindex,  │ Infrastructure fix before    ║
║       │ fix YELLOW (post-incident)       │ next v2 attempt.              ║
╚══════════════════════════════════════════════════════════════════════════╝
```

**Why NOT rollback ES scale first:** Adding nodes to a YELLOW cluster with RF=1 does not help — wastes time. **Why flags before deploy rollback:** Flags take effect in seconds via Istio control plane; deploy rollback takes 5-10 min with pod churn. **Why remove rate limit after routing to v1:** v1 can handle restored corporate traffic; rate limit was harming conversion more than helping latency.

### Immediate Commands (Steps 1-3)

```bash
# Step 1: Zero canary
curl -X PATCH https://flags.internal/api/v1/flags/search_v2_rollout \
  -d '{"rollout_percentage": 0}'

# Step 2: Route to v1 index
curl -X PATCH https://flags.internal/api/v1/flags/search_v2_index \
  -d '{"value": "products_v1"}'

# Verify search-api logs show products_v1 within 30s
kubectl logs -l app=search-api --tail=20 | grep index

# Step 3: Remove CloudFront rate limit
aws wafv2 update-web-acl --scope CLOUDFRONT \
  --id $WAF_ACL_ID \
  --lock-token $TOKEN \
  --rules file://waf-rules-without-rate-limit.json

# Monitor conversion recovery
aws cloudwatch get-metric-statistics \
  --namespace Ecommerce \
  --metric-name CheckoutConversionRate \
  --start-time $(date -u -d '15 min ago' +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 --statistics Average
```

---

## Question 7: Post-Incident Action Items (With Acceptance Criteria)

### Search / Elasticsearch (2)

**1. Production index guardrails (oncall-search)**
- `number_of_replicas >= 1` enforced via index template for all `products_*` indices
- CI check rejects index creation with RF=0 in prod namespaces
- Acceptance: `/_cat/indices/products_*?v&h=index,rep` shows rep≥1 for all prod indices

**2. Dedicated ingest tier (oncall-search + platform)**
- Separate ES cluster for indexing (16 indexer pods) vs search (12 data nodes)
- Cross-cluster replication or alias swap for query isolation
- Acceptance: search p99 unaffected when indexing at 2× peak write rate

### Rate Limiting (2)

**3. GCRA at api-gateway (oncall-platform)**
- Replace 1s Redis fixed buckets with atomic Lua GCRA script
- Acceptance: at steady 10k req/s for 10 min, false 429 rate < 0.1%

**4. Per-API-key tier limits (oncall-platform)**
- Composite key `{api_key}:{endpoint}` with tier from key metadata
- Corporate keys get dedicated burst pool, not shared NAT IP bucket
- Acceptance: 500 rotating free keys cannot exceed 10 req/min/key aggregate

### ID / Migration (1)

**5. product_id_map parity gate (oncall-app)**
- Dual-write UUID v7 + legacy bigint on every catalog create
- Checkout add-to-cart resolves via mapping table before order write
- Acceptance: 0 "product not found" errors in canary with 1000 new SKUs

### Feature Flags / Canary (1)

**6. Canary readiness checklist (oncall-sre)**
- Before any search index canary: RF≥1, index warm (≥1M docs or explicit warm job), ID parity verified
- Auto-rollback on p99 regression >2× baseline OR CTR drop >5%
- Acceptance: checklist enforced in deploy pipeline; incident replay would block 10:35 canary

---

```
╔══════════════════════════════════════════════════════════════════════╗
║  # │ CHANGE                              │ OWNER         │ TYPE      ║
╠══════════════════════════════════════════════════════════════════════╣
║  1 │ products_v2: RF=2 minimum in prod   │ oncall-search │ ES        ║
║  2 │ Separate ingest cluster from search │ oncall-search │ ES        ║
╠══════════════════════════════════════════════════════════════════════╣
║  3 │ Replace 1s Redis buckets with GCRA  │ oncall-platform│ Rate Lim ║
║  4 │ Per-API-key tier limits (not IP)    │ oncall-platform│ Rate Lim ║
╠══════════════════════════════════════════════════════════════════════╣
║  5 │ product_id_map dual-write parity    │ oncall-app    │ IDs       ║
║    │ gate before Phase 2 reads           │               │           ║
╠══════════════════════════════════════════════════════════════════════╣
║  6 │ Canary process: require warm index, │ oncall-sre    │ Flags     ║
║    │ RF check, ID parity before rollout  │               │           ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Rollback Timeline (11:05 Execution)

```
╔════════════════════════════════════════════════════════════════╗
║  T+0 (11:05)  │ search_v2_rollout → 0%                         ║
║  T+30s        │ search_v2_index → products_v1                  ║
║  T+60s        │ Search p99 dropping (verify Grafana)           ║
║  T+90s        │ Remove CloudFront per-IP WAF rule              ║
║  T+120s       │ Corporate customers unblocked                  ║
║  T+180s       │ Pause Debezium → products_v2 indexer           ║
║  T+300s       │ search-api deploy rollback initiated           ║
║  T+600s       │ Conversion recovering toward baseline          ║
║               │                                                ║
║  NOT TODAY    │ ID mapping table + dual-write parity gate      ║
║  (Day 2+)     │ ES RF=2 + dedicated ingest cluster             ║
║               │ GCRA rate limiting at gateway                  ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Scoring Guide (Self-Check)

```text
Part 1 (Q1–Q14):   11/14+ → Week 7 specialized components retained
Part 2 (scenario):  Principal depth on multi-layer diagnosis

Overall:
  Ready for Week 8  → 85%+ across parts
  Review Week 7     → below 70% on Part 1
  Review Week 6     → struggle on search/CDC bridge questions
```
