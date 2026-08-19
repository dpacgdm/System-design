# Answer Key — Final Capstone Scenario

> Open only after attempting the learner file questions.

## 13. Full Expert Analysis

### Q1: Problems A–K — Layer, Root Cause, Evidence

#### Problem A: Stale Feed GraphQL CDN Cache
- **Week/Domain:** Week 1 (CDN) + Week 9 (Feed)
- **Layer:** CDN / HTTP caching
- **Root cause:** `Cache-Control: public, s-maxage=45` on `/graphql/feed` caused CloudFront to cache personalized timeline responses including keynote banner state.
- **Evidence:** 14:03 stale banner; `Age: 38` header; deploy 13:45; live WebSocket stream correct (bypasses CDN).

#### Problem B: Kafka Hot Partition 42
- **Week/Domain:** Week 6 (Kafka) + Week 9 (Feed)
- **Layer:** Kafka / async pipeline
- **Root cause:** @omni_ceo post fan-out-on-write keyed to partition 42; single consumer cannot process 680M fan-out targets.
- **Evidence:** partition 42 lag 3.8M; fanout-42 CPU 99%; fanout-07 at 8%; spike at 14:02.

#### Problem C: Payment Idempotency Failure
- **Week/Domain:** Week 11 (Payments) + Week 7 (Redis)
- **Layer:** PostgreSQL + Redis idempotency
- **Root cause:** Non-atomic check-then-set; 15m TTL expired under 30s client retries + gateway timeout.
- **Evidence:** success 94.1%; ledger 857K vs Stripe 842K; duplicate tickets 14:04; TTL change 2026-07-05.

#### Problem D: Geo Shard Split-Brain
- **Week/Domain:** Week 10 (Uber/geospatial) + Week 13 (Config store)
- **Layer:** Config store + geospatial index
- **Root cause:** v3 policy not converged in sa-east-1; matching cached v2, settlement used v3 surge.
- **Evidence:** surge 1.2× display vs 2.8× receipt; config lag 45s; push 13:55; 1,200 disputes/10min.

#### Problem E: gRPC L4 Black Hole (Matching Engine)
- **Week/Domain:** Week 1 (gRPC) + Week 7 (LB) + Week 10 (Ride)
- **Layer:** gRPC / L4 load balancing
- **Root cause:** NLB pinned long-lived HTTP/2 connections to replicas 1–2; 46 replicas idle.
- **Evidence:** replica-1/2 CPU 97%/94%; replicas 3–48 at 4–8%; architecture notes L4 LB.

#### Problem F: CoreDNS ndots Explosion
- **Week/Domain:** Week 1 (DNS)
- **Layer:** DNS / Kubernetes
- **Root cause:** ndots:5 → 5 queries per external lookup; retry storms multiplied volume.
- **Evidence:** CoreDNS 97%; 1.1M qps; NXDOMAIN 78%; baseline 220K.

#### Problem G: CRDT Doc Fork
- **Week/Domain:** Week 8 (CRDTs) + Week 14 (Docs)
- **Layer:** CRDT / Kafka consumer rebalance
- **Root cause:** range assignor rebalance during 847-editor session split operation stream.
- **Evidence:** divergent paragraph 14; assignor change 2026-07-05; 14:08 report.

#### Problem H: LLM Queue Starvation
- **Week/Domain:** Week 14 (LLM serving) + Week 7 (Rate limiting)
- **Layer:** LLM gateway + shared Redis
- **Root cause:** 100% GA Copilot flooded llm.requests (890K depth) + shared rate limiter/contended Redis with payments.
- **Evidence:** first-token p99 47s; queue 890K; GA 340K req/min; flag omni_copilot_ga 100%.

#### Problem I: Search Stale + ES Disk
- **Week/Domain:** Week 12 (Search)
- **Layer:** Elasticsearch
- **Root cause:** Takedown not indexed; disk 91% blocked replica recovery → stale segments served.
- **Evidence:** phishing in autocomplete; YELLOW cluster; 34 unassigned shards; disk 91%.

#### Problem J: Cassandra cass-us-07 Partition
- **Week/Domain:** Week 4–5 (Replication, Cassandra)
- **Layer:** Cassandra quorum
- **Root cause:** Node UNREACHABLE → LOCAL_QUORUM failures for token ranges on cass-us-07.
- **Evidence:** nodetool UN; HH queue 1.2M; UnavailableException on timelines/messages.

#### Problem K: WebSocket Idle Timeout
- **Week/Domain:** Week 1 (WebSockets/TCP)
- **Layer:** NLB / TCP keepalive
- **Root cause:** NLB idle timeout 60s without app ping/pong; connections drop at regular 60s cadence.
- **Evidence:** 2.4M reconnects/min; 60s cadence; chat delay 38s; NLB timeout 60s.

---

### Q2: Causal Graph (Eight+ Edges)

```
EDGE 1: A (stale CDN) → C (payment retries)
  Users refresh feed repeatedly → GraphQL load ↑ → checkout timeouts → retries → duplicates

EDGE 2: C (payment retries) → F (CoreDNS)
  Each retry calls fraud-check.external.com → 5× DNS queries per ndots

EDGE 3: F (CoreDNS slow) → C (slower checkout)
  DNS +500ms → longer checkout → more timeouts → MORE retries (loop)

EDGE 4: B (Kafka lag) → A (worse stale perception)
  Feed API falls back to Redis/Cassandra stale data while CDN also stale → double staleness

EDGE 5: H (LLM load) → Redis shard-11 hot
  Shared Redis: llm queue + timeline:omni_ceo + ratelimit:asn same shard

EDGE 6: H → GraphQL gateway slow
  Shared mesh + thread pool contention → 22s p99 → client retries across ALL verticals

EDGE 7: E (gRPC black hole) → D (match latency)
  Slow matching → more concurrent location updates → geo index write pressure

EDGE 8: D (split-brain) → C (payment disputes)
  Wrong surge → users retry payment disputes → support tools hit checkout APIs

EDGE 9: K (WS drops) → B (chat events backlog)
  Reconnect storms republish presence/chat → Kafka chat.events volume spike

EDGE 10: J (Cassandra UN) → B (fan-out read fallback fails)
  Timeline LOCAL_QUORUM failures → API serves last Redis cache (6h old)

EDGE 11: I (search stale) ← independent of B but worsened by ES disk from crawl spike
  Launch traffic → more crawl/index → disk 91%

EDGE 12: G (doc fork) ← triggered by Kafka rebalance also affecting chat consumers (Problem K overlap)
  Shared Kafka ops during incident increased rebalance frequency
```

---

### Q3: Expert Prioritization Ranking (14:25)

| Rank | ID | Justification |
|------|-----|---------------|
| **1** | **C** | Financial integrity P0; regulatory threshold; direct money loss; fixable in minutes via idempotency mode |
| **2** | **D** | Active mischarging on rides; 1,200 disputes/10min; LATAM launch centerpiece; rollback fast |
| **3** | **A** | 180M notif users; misleading launch state; reputational; CDN purge < 5 min |
| **4** | **K** | 340K active trips need driver location WS; safety-adjacent; chat 38s delay |
| **5** | **B** | Massive blast radius but partial mitigations (fan-out-on-read) exist; lag alert was late |
| **6** | **I** | High severity per phishing result but 0.3% volume; ES fix takes hours |
| **7** | **G** | Internal runbook fork; 12 enterprise SLAs; not consumer-facing for most |
| **8** | **H** | Degrade Copilot acceptable; feature flag rollback; cosmetic vs money |

---

### Q4: Top 3 Immediate Mitigations

*(See Section 9.1 Actions 1–3 for full commands.)*

**#1 Problem C:**
```bash
kubectl set env deployment/checkout-api -n payments \
  IDEMPOTENCY_TTL_SECONDS=86400 IDEMPOTENCY_MODE=db_claim_first
```
Expected: duplicate rate 6% → <0.1%; ledger divergence stops growing.

**#2 Problem D:**
```bash
omnilink-ctl config set ride.geo.shard_policy consistent_hash_v2 --force-version-check
kubectl rollout restart deployment/matching-engine -n omniride
```
Expected: surge dispute −80% within 15 min.

**#3 Problem A:**
```bash
aws cloudfront create-invalidation --distribution-id E3ABCDEF123456 \
  --paths "/graphql/feed" "/graphql/feed/*"
# plus hotfix Cache-Control: private on feed resolver
```
Expected: banner staleness clears within 2 min.

---

### Q5: Payment Idempotency Race — Detailed

**Race timeline:**
```
T0: Request A arrives Idempotency-Key: abc-123
T1: Request B arrives Idempotency-Key: abc-123 (client retry)
T2: A checks Redis GET idempotency:abc-123 → MISS (expired after 15m)
T3: B checks Redis GET idempotency:abc-123 → MISS (before A sets)
T4: A SET NX idempotency:abc-123 → OK
T5: B SET NX idempotency:abc-123 → OK (should fail but both proceed if check was GET not SET)
T6: A inserts ledger row $49.99
T7: B inserts ledger row $49.99  ← DUPLICATE
```

**Why 15m TTL mattered:** Launch retries spanned 30s × 3 + queue delay > 15m for users who retried from app background.

**Missing atomicity:** Check (GET) and claim (SET) were separate. DB had no UNIQUE on idempotency_key enforced before insert.

**Fix pattern:**
```sql
-- DB-first claim (correct)
INSERT INTO idempotency_claims (key, response_ref, created_at)
VALUES ('abc-123', NULL, NOW())
ON CONFLICT (key) DO NOTHING
RETURNING key;
-- If 0 rows returned → fetch existing response_ref → return cached outcome
-- Else proceed to Stripe auth
```
```redis
SET idempotency:abc-123 "pending" NX EX 86400
-- Only after DB commit:
SET idempotency:abc-123 '{"status":"completed","charge_id":"ch_xxx"}' EX 86400
```

---

### Q6: Geo Shard Split-Brain

**Mechanism:** consistent_hash_v3 moved 12% of geohash cells to different Redis shards. sa-east-1 matching engine still on v2 ring → driver lookup used v2 cell→surge table (1.2×). Payment settlement read global surge from config leader v3 (2.8× for high-demand cells).

**Match path:** Location → geohash → v2 shard → driver pool → estimate 1.2×
**Settlement path:** Trip complete → OmniPay reads config store v3 surge multiplier → 2.8× charge

**Fix:** Monotonic version gate:
```go
if localPolicy.Version < configStore.MinVersion("ride.geo.shard_policy") {
    return ErrPolicyStale // refuse match until refreshed
}
```

---

### Q7: CoreDNS NXDOMAIN Calculation

**Assumptions from timeline:**
- Baseline 220K qps total
- Peak 1.1M qps
- NXDOMAIN ratio 78% → ~858K NXDOMAIN/sec at peak

**Per external lookup with ndots:5 (3-dot hostname):** 5 queries (4 NXDOMAIN + 1 success)

**If 180K successful external lookups/sec needed at peak:**
180K × 5 = 900K queries — matches observed order of magnitude.

**Generators:** checkout-api (fraud-check.vendor.com), stripe adapter (api.stripe.com), llm-gateway (models.huggingface.co), matching-engine (maps.googleapis.com).

**Fix yaml:**
```yaml
spec:
  dnsConfig:
    options:
      - name: ndots
        value: "1"
      - name: single-request-reopen
```

---

### Q8: Kafka Partition 42

**Why partition 42:** `partition = murmur2(user_id) mod 48`. @omni_ceo fan-out events keyed by celebrity user_id hash → single partition.

**Why adding workers fails:** Max 1 consumer per partition in group; 200 workers, 47 idle on this topic's hot partition.

**Commands:**
```bash
# Emergency: fan-out-on-read
omnilink-ctl flags set feed.celebrity_fanout_on_read omni_ceo=true

# Dedicated consumer group for partition 42
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --bootstrap-server kafka-events:9092 \
  --create --group fanout-hot-ceo --topic posts.created \
  --partitions 42

# Long-term: route celebrity posts to dedicated topic
kafka-topics.sh --create --topic posts.created.celebrity --partitions 12 \
  --replication-factor 3 --config retention.ms=604800000
```

---

### Q9: CRDT Doc Fork

**Assignor role:** cooperative-sticky → range caused full partition revoke on rolling restart. Doc operations routed by doc_id; during rebalance, editors on revoked partitions buffered ops locally; reconnected to different shard without full history merge.

**847 editors:** Exceeded CRDT gossip efficiency; op log buffer overflow → snapshot divergence.

**Merge without loss:** Server-side RGA merge:
```
merged = RGA_merge(fork_a, fork_b)  // both retain unique inserts by op_id
LWW_register for metadata fields
Persist merged state to S3; broadcast reset op to all clients
```
Reference Week 8 CRDT commutative merge + Week 14 server authoritative snapshot.

---

### Q10: LLM Gateway Starvation

**Trace:** omni_copilot_ga 100% → 340K req/min → Redis Streams llm.requests depth 890K → inference batch saturation → vLLM queue 47s → GraphQL gateway shares thread pool + Redis cluster shard-11 with ratelimit + timeline cache → payment/checkout Redis timeouts.

**Bulkhead fixes:**
1. Separate Redis cluster for LLM queue (`redis-llm.internal`)
2. Dedicated ALB + gateway deployment for `/v1/copilot/*` with circuit breaker to core APIs
3. Admission control: `max_inflight_llm=5000` per region; 429 early with Retry-After

**Config values from scenario:**
- llm.requests queue depth alert threshold: 50K (was unalerted at 890K)
- omni_copilot_ga canary should cap at 25% when payment burn > 2×

---

### Q11: Search — Freshness vs Cluster Health

**Freshness problem:** Takedown 6h ago not in delete pipeline → stale autocomplete index.

**Cluster health problem:** disk 91% → `flood_stage` → unassigned replicas → YELLOW → query routing serves stale primary segments.

**Diagnostic APIs:**
```bash
# Freshness — compare crawl vs index
curl "es:9200/merchant_catalog/_search?q=phishing_merchant_id&pretty"
curl "es:9200/_cat/indices/merchant_catalog?v&h=index,docs.count,store.size"

# Cluster health
curl "es:9200/_cluster/health?pretty"
curl "es:9200/_cat/allocation?v&h=node,disk.percent,disk.used"
curl "es:9200/_cluster/settings?include_defaults=true&filter_path=**.disk*"
```

**Disk watermark:** At 91%, ES blocks new shard allocation to node; replica unassigned → lose redundancy; merge throttled → stale segments persist.

---

### Q12: SLO Error Budget

**Multi-window burn (Week 8):**
- 1h burn 14.2× → page immediately (fast burn)
- 6h burn ~4× → sustained damage
- 3d burn ~1.5× → monthly budget context

**Policy:** Block GA when ANY critical SLO 1h burn > 2×. At 14:11 payment burn 14.2× — **LLM GA should have auto-rolled back at 14:05** when success dropped 94%.

**Error budget:** 0.05%/month payment failures ≈ 216 min downtime equivalent. Burned in 11 min → entire July budget consumed.

---

### Q13: WebSocket vs DNS

**Problem K (WS):** Regular 60s disconnect cadence = NLB idle timeout signature. NOT random, NOT geographic.

**Problem F (DNS):** Elevated latency on ALL outbound connections; no 60s cadence; CoreDNS metrics.

**Fixes:**
```bash
# NLB
aws elbv2 modify-target-group-attributes \
  --target-group-arn arn:aws:elasticloadbalancing:...:ws-chat-tg \
  --attributes Key=idle_timeout.timeout_seconds,Value=3600

# App ConfigMap
PING_INTERVAL_SEC: "30"   # must be < idle_timeout/2
PONG_TIMEOUT_SEC: "10"
```

---

### Q14: Cassandra cass-us-07

**Quorum impact:**
- Feed timelines: LOCAL_QUORUM 2/3 — reads/writes fail for ~1/24 token range
- Chat messages: same CF on cass-us-07 ranges — delivery delay
- Ride trips: trip history writes fail → dispatch state inconsistent

**Hinted handoff at 1.2M:** cass-us-02 storing writes for unreachable cass-us-07 → replay on recovery causes write amplification + temporary read latency.

**Commands:**
```bash
nodetool status
nodetool describecluster
nodetool gethintedhandoffmetrics cass-us-02
nodetool disablehintfordc DC1  # emergency only if HH overload threatens cluster
nodetool removenode <cass-us-07-uuid>
nodetool repair -pr keyspace user_timelines
```

---

### Q15: Six Durable Cross-Cutting Changes

1. **DB-first idempotency** (Week 11) — Payments, ride wallet, LLM token billing
2. **L7 gRPC LB everywhere** (Week 1/7) — Matching, media, any HTTP/2 service
3. **SLO-gated feature flags** (Week 8) — All GA launches including LLM
4. **Config version guards** (Week 13) — Geo, rate limits, CDN policies
5. **Vertical Redis bulkheads** (Week 2/6) — cache | ratelimit | llm | geo
6. **Hot-key detection pipeline** (Week 3/9) — Kafka lag anomaly + celebrity routing

---

## 14. Scoring Rubric for Capstone Performance

```
TOTAL: 100 points

SECTION A — Problem Identification (20 pts)
  11 problems × ~1.8 pts each
  Full credit: correct layer + root cause + evidence citation
  Partial: wrong layer but correct domain
  Zero: misidentified layer AND domain

SECTION B — Cascade Analysis (15 pts)
  8+ edges × 1.5 pts
  Must explain mechanism, not just draw arrows
  +3 bonus for identifying feedback loops (max 15)

SECTION C — Prioritization (15 pts)
  Rank correlation with expert ranking (Section 13 Q3)
  Spearman-like: exact match top 3 = 8 pts; reasonable justification = 7 pts
  Penalize: payment ranked below LLM (−5)

SECTION D — Mitigations (20 pts)
  Top 3 mitigations with working commands: 7 pts each
  Must include expected metric delta
  Partial credit for correct direction, wrong command syntax

SECTION E — Deep Dives Q5–Q14 (20 pts)
  2 pts per question (pick any 10) OR 1.33 × 15
  Full credit: atomic patterns, calculations, API names

SECTION F — Architecture Redesign (10 pts)
  6 recommendations × 1.5 pts (round up)
  Must tie to curriculum week/pattern

GRADING SCALE:
  90–100: Staff-ready — integrate across domains under pressure
  75–89:  Senior-ready — minor blind spots (usually DNS or CRDT)
  60–74:  Mid-level — knows modules in isolation, weak on cascades
  45–59:  Needs review — re-do Weeks 6, 8, 11, 13 scenarios
  <45:    Foundation gaps — restart from Week 1 compound scenario

SELF-SCORING WORKSHEET:
  A: ___/20   B: ___/15   C: ___/15   D: ___/20   E: ___/20   F: ___/10
  TOTAL: ___/100
```

---


---
