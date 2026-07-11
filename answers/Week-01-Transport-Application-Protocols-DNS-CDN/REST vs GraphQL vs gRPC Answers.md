# Answer Key - REST vs GraphQL vs gRPC

> Open only after attempting the learner file Ops Sim.

## Ops Sim: Northstar GraphQL Fan-Out and gRPC Black Hole

### Q1 - Layer & root cause

There are two failures:

1. GraphQL resolver N+1: `sellerReputation` calls `profile-grpc.GetUser` per bid row, serialized, with DataLoader/batching disabled.
2. gRPC over L4 NLB black hole: long-lived HTTP/2 connections are distributed by connection, not request, so two pods receive most traffic.

GraphQL HTTP 200 responses hide the application errors from HTTP-status-only monitoring.

### Q2 - Evidence

- GraphQL body errors: HTTP 200 with `errors.path=["auction","seller","reputation"]`.
- N+1: trace shows 1,400 repeated spans for one page and `dataloader_enabled=false`.
- L4 pinning: two `profile-grpc` pods at ~88% CPU while ten are idle; logs show long-lived streams through an NLB.
- Red herring: DB p95 9ms means profile storage is not the bottleneck.

### Q3 - First 15 minutes

1. Declare P1 because auction bidding UX is degraded.
2. Enable `batch_profile_lookup` / DataLoader if already shipped and safe.
3. If batching cannot be enabled immediately, degrade seller reputation/shipping widgets while preserving bid and payment eligibility paths.
4. Cap resolver calls per request to fail optional fields fast instead of consuming all gateway capacity.
5. Move gRPC clients to multiple channels with client-side round-robin or route through an L7/Envoy gRPC-aware balancer.
6. Alert on GraphQL error fields, not only HTTP status.

### Q4 - Bad fixes

Adding pods behind the same NLB does not guarantee more useful capacity because existing HTTP/2 channels remain pinned to the original hot pods. It may also create more connection churn during the incident.

Returning HTTP 500 for all GraphQL errors is wrong because partial data is a normal GraphQL behavior. Instead classify critical operations/paths and emit operation-level error metrics.

### Q5 - Capacity / blast radius

```text
100 heavy users x 1,400 calls = 140,000 profile calls
one retry doubles it to 280,000 calls
```

With L4 pinning, most of that can concentrate on two pods, effectively 140k calls/pod in a burst, while the rest are idle. Gateway CPU and retry queues will also rise.

### Q6 - Durable fix

GraphQL:
- Require DataLoader/batching for entity lookups.
- Set resolver budget limits per operation.
- Persisted queries with cost scoring for auction pages.

gRPC:
- Use gRPC-aware L7 load balancing or client-side round robin with enough channels.
- Track per-pod request distribution, not just service-level p99.

Acceptance criteria:
- AuctionPage profile calls are O(unique sellers), not O(bid rows).
- No pod gets >2x median `profile-grpc` RPS during load test.
- GraphQL operation error metrics page on-call even when HTTP status is 200.

### Q7 - Org / runbook

Notify incident commander, mobile/API lead, auction business owner, support, and profile service owner by T+10.

Pre-authorized degradation: hide optional seller reputation/shipping widgets or show stale cached values. Not pre-authorized: accepting bids without eligibility/payment checks.

---

# Incident Deep-Dive Analysis — Corrected

---

## Question 1: The TWO Root Causes & The Math

### Problem 1: Sequential Per-Post N+1 Fan-Out in the Feed Resolver

The critical code path:

```javascript
async function resolveFeed(userId) {
    const posts = await postService.GetFeed(userId);
    for (const post of posts) {                      // ← iterates POSTS
        post.author = await userService.GetUser(...)  // ← 1 gRPC call per POST
        post.images = await imageService.GetImages(.) // ← 1 gRPC call per POST
        post.author.followers = await userService
            .GetFollowerCount(...)                     // ← 1 gRPC call per POST
    }
}
```

The loop variable is `post`, not `follower`. For every single post in the feed, three **sequential** gRPC calls are made — `GetUser`, `GetImages`, `GetFollowerCount`. The number of posts in a user's feed is directly proportional to **how many accounts they follow**. More follows → more authors producing content → more posts in the feed.

### Problem 2: gRPC Connection Pinning Through L4 Load Balancers

The architecture specifies **L4 load balancers** in front of gRPC services. gRPC runs on HTTP/2 with long-lived, multiplexed connections. An L4 LB distributes **TCP connections**, not individual requests. This means all 47,000 gRPC requests/sec are funneled through 2-3 TCP connections pinned to only 2 of the 6 User Service replicas.

### The Math: Why 500+ Follower Users Are Destroyed

```
Each post in the feed requires 3 sequential gRPC calls.
Assume each gRPC call costs ~5ms under normal conditions.

User follows 50 accounts:
  Feed contains ~50 recent posts
  gRPC calls = 50 posts × 3 calls/post = 150 gRPC calls
  Latency = 150 × 5ms = 750ms
  → Slow but survivable. Under a 1s timeout.

User follows 200 accounts:
  Feed contains ~200 recent posts
  gRPC calls = 200 × 3 = 600 gRPC calls
  Latency = 600 × 5ms = 3,000ms (3 seconds)
  → Painful. Likely hitting timeout thresholds.

User follows 500 accounts:
  Feed contains ~500 recent posts
  gRPC calls = 500 × 3 = 1,500 gRPC calls
  Latency = 1,500 × 5ms = 7,500ms (7.5 seconds)
  → MATCHES THE OBSERVED 12s p99 (with overhead,
    retries, and CPU contention on hot replicas)

VALIDATING AGAINST OBSERVED gRPC VOLUME:
  Baseline gRPC calls/sec: 3,000 (pre-deployment)
  Post-deployment: 47,000/sec

  If ~30 concurrent heavy users (500+ follows) each
  generate 1,500 gRPC calls per feed load:
    30 × 1,500 = 45,000 calls
    + baseline light users: ~2,000 calls
    = ~47,000 gRPC calls/sec ✓ EXACT MATCH

THE DESTRUCTION THRESHOLD:
  At ~170 follows: 170 × 3 × 5ms ≈ 2,550ms → timeout zone begins
  At 500 follows: 7,500ms → guaranteed timeout
  Timeouts trigger client retries (typically 3x automatic)
  Each retry regenerates 1,500 gRPC calls on the SAME
  pinned replicas (Problem 2), compounding the death spiral
```

**The two problems are multiplicative:**
- Problem 1 (N+1 fan-out) **creates** 1,500 gRPC calls per feed load
- Problem 2 (L4 pinning) **concentrates** all 47,000 calls/sec onto 2 replicas
- Together: 2 replicas drown → timeouts → retries → more calls → cascading failure

---

## Question 2: The 85%/8% CPU Distribution — The gRPC L4 Black Hole

```
Cluster State:
╭──────────────────────────────────────────────────────╮
│  Replica 1:  ██████████████████████████████████ 85%  │ ← ALL TRAFFIC
│  Replica 2:  ██████████████████████████████████ 85%  │ ← ALL TRAFFIC
│  Replica 3:  ████ 8%                                 │ ← GHOST
│  Replica 4:  ████ 8%                                 │ ← GHOST
│  Replica 5:  ████ 8%                                 │ ← GHOST
│  Replica 6:  ████ 8%                                 │ ← GHOST
╰──────────────────────────────────────────────────────╯
```

This is the **gRPC + L4 Load Balancer Black Hole** — a known, documented failure pattern.

### The Exact Mechanism:

**Step 1: gRPC uses HTTP/2 with long-lived, multiplexed connections.**
Unlike HTTP/1.1 (one request per connection), HTTP/2 sends **thousands of requests** over a single TCP connection via stream multiplexing.

**Step 2: L4 load balancers operate at the TCP layer.**
An L4 LB sees a TCP SYN, picks a backend via round-robin, and pins that **entire connection** to that backend. It never inspects HTTP/2 frames. It has zero visibility into how many gRPC requests are flowing inside that connection.

**Step 3: The Feed Gateway opens very few TCP connections.**
gRPC clients maintain a small connection pool — typically 1-3 connections per target. The L4 LB distributes these connections at creation time:

```
╔══════════════════════════════════════════════════════════════╗
║   Feed Gateway (gRPC Client)                                 ║
║     │                                                        ║
║     ├── TCP conn 1 ─► L4 LB ─► Replica 1                     ║
║     │   (multiplexes ~25,000 gRPC req/sec)                   ║
║     │                                                        ║
║     ├── TCP conn 2 ─► L4 LB ─► Replica 2                     ║
║     │   (multiplexes ~22,000 gRPC req/sec)                   ║
║     │                                                        ║
║     ╰── (no more connections opened)                         ║
║                                                              ║
║   Replicas 3, 4, 5, 6: ZERO TCP connections                  ║
║   They are healthy, running, and completely idle.            ║
║   The L4 LB has no reason to route to them —                 ║
║   no new TCP connections are being created.                  ║
╚══════════════════════════════════════════════════════════════╝
```

**Step 4: Scaling is useless.**
If you `kubectl scale --replicas=10`, you now have **8 idle replicas** instead of 4. The L4 LB will never route traffic to them because the existing TCP connections are long-lived and already pinned. This is why the 4 replicas at 8% CPU exist — they were likely added by autoscaling that detected high average CPU, but the new replicas received zero connections.

### Why This Is NOT Hash-Based Routing or Mega-User Concentration:

```
The evidence eliminates complex theories:

  ✗ Hash collision theory: Would produce SOME traffic
     on all replicas, just unevenly. We see near-ZERO
     on 4 replicas (8% is baseline/healthcheck overhead).

  ✗ Mega-user theory: Would affect specific user requests,
     not ALL requests on specific replicas.

  ✓ L4 + gRPC black hole: Explains EXACTLY why traffic
     is binary — either a replica has a connection (85%)
     or it doesn't (8%). There is no middle ground.

Occam's Razor for SRE:
  The scenario says "L4 load balancers" + "gRPC services."
  That combination has ONE known failure mode.
  It matches ALL observed symptoms perfectly.
  Don't reach for complex explanations when a simple,
  documented pattern fits every data point.
```

---

## Question 3: Immediate Mitigation — Right Now, In Order

### Step 0: ROLL BACK THE DEPLOYMENT (Minute 0-3)

```bash
# A junior developer's "enriched feed" feature was deployed.
# That deployment is the DIRECT CAUSE of the N+1 fan-out.
# Rolling it back eliminates the problem at the source.

# Identify the last known good revision:
kubectl rollout history deployment/feed-gateway

# Roll back to the previous revision:
kubectl rollout undo deployment/feed-gateway

# Or if using a CI/CD pipeline (ArgoCD, Spinnaker):
# Trigger a redeploy of the previous artifact version.

# Watch the rollout:
kubectl rollout status deployment/feed-gateway

# EXPECTED RESULT (within 2-3 minutes):
#   gRPC calls/sec: 47,000 → 3,000 (back to baseline)
#   Feed p99 latency: 12s → 400ms
#   User Service CPU: normalizes as call volume drops
```

**This is the #1 rule of incident response: if a deployment caused it, undo the deployment.** Everything below is for if rollback is impossible (corrupted state, database migration, etc.).

### Step 1: IF Rollback Fails — Feature Flag the Enrichment (Minute 3-5)

```bash
# Disable the enriched feed path via feature flag
# Falls back to the old feed resolver (no per-post enrichment)
curl -X POST https://feature-flags.internal/api/flags \
  -d '{"flag": "enriched_feed_v2", "enabled": false}'
```

### Step 2: IF No Feature Flag — Hard Circuit Break on User Service (Minute 5-8)

```bash
# Apply circuit breaker to prevent the retry storm
# from killing User Service entirely
kubectl apply -f - <<EOF
apiVersion: networking.istio.io/v1alpha3
kind: DestinationRule
metadata:
  name: user-service-emergency-cb
spec:
  host: user-service
  trafficPolicy:
    outlierDetection:
      consecutive5xxErrors: 3
      interval: 10s
      baseEjectionTime: 30s
    connectionPool:
      http:
        maxRequestsPerConnection: 1    # ← FORCE new TCP connections
        h2UpgradePolicy: DO_NOT_UPGRADE # ← Break HTTP/2 multiplexing
EOF
```

Note: `maxRequestsPerConnection: 1` is the **emergency fix for the L4 black hole** — it forces a new TCP connection per request, allowing the L4 LB to actually distribute traffic. This is a band-aid, not a solution.

### Step 3: Verify Recovery (Minute 8-12)

```bash
# Confirm gRPC call volume has dropped
watch -n 5 "kubectl exec -it prometheus-0 -- promtool query instant \
  'rate(grpc_client_handled_total[1m])'"

# Confirm CPU is equalizing across replicas
kubectl top pods -l app=user-service

# Confirm p99 latency is recovering
# Confirm 5xx error rate is dropping to zero
# Confirm no user-facing errors in the feed
```

### The Priority Ladder:

```
╔══════════════════════════════════════════════════════════════╗
║   INCIDENT RESPONSE PRIORITY ORDER:                          ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. ROLL BACK the deployment        ← DO THIS               ║
║      (fixes 80% of production incidents)                     ║
║                                                              ║
║   2. Feature flag to disable broken code path                ║
║      (if rollback isn't possible)                            ║
║                                                              ║
║   3. Infrastructure mitigation                               ║
║      (circuit breakers, drain nodes, scale)                  ║
║      (if you can't change application behavior)              ║
║                                                              ║
║   4. Scale up and absorb the damage                          ║
║      (last resort — buys time to debug)                      ║
║                                                              ║
║   Always try 1 before 2, 2 before 3, 3 before 4              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 4: Long-Term Redesign — Code Fix & Infrastructure Fix

### A. The Code Fix: DataLoader Pattern (The Canonical GraphQL N+1 Solution)

**DataLoader is to GraphQL what connection pooling is to databases — it is not optional, it is mandatory.**

```javascript
// ✗ BEFORE: The killer — 1,500 sequential gRPC calls for a 500-post feed
async function resolveFeed(userId) {
    const posts = await postService.GetFeed(userId);
    for (const post of posts) {
        post.author = await userService.GetUser(post.authorId);          // N calls
        post.images = await imageService.GetImages(post.id);             // N calls
        post.author.followers = await userService.GetFollowerCount(post.authorId); // N calls
    }  // Total: 3N sequential gRPC calls
}

// ✓ AFTER: DataLoader — 3 batched gRPC calls regardless of feed size
const userLoader = new DataLoader(async (userIds) => {
    // Step 1: Deduplicate — 500 posts might only have 80 unique authors
    // Step 2: Single batched gRPC call
    const users = await userService.BatchGetUsers(userIds);
    // Step 3: Return results in the same order as input keys
    return userIds.map(id => users.find(u => u.id === id));
});

const imageLoader = new DataLoader(async (postIds) => {
    const images = await imageService.BatchGetImages(postIds);
    return postIds.map(id => images.filter(img => img.postId === id));
});

const followerCountLoader = new DataLoader(async (userIds) => {
    const counts = await userService.BatchGetFollowerCounts(userIds);
    return userIds.map(id => counts.find(c => c.userId === id)?.count ?? 0);
});

async function resolveFeed(userId) {
    const posts = await postService.GetFeed(userId);
    // DataLoader collects all .load() calls within a single tick,
    // deduplicates keys, and fires ONE batched request per resource type
    await Promise.all(posts.map(async (post) => {
        post.author = await userLoader.load(post.authorId);
        post.images = await imageLoader.load(post.id);
        post.author.followers = await followerCountLoader.load(post.authorId);
    }));
}
```

**The DataLoader math:**
```
BEFORE DataLoader (500-post feed, 80 unique authors):
  GetUser:           500 individual calls (sequential)
  GetImages:         500 individual calls (sequential)
  GetFollowerCount:  500 individual calls (sequential)
  TOTAL:             1,500 gRPC calls, ~7,500ms

AFTER DataLoader (same feed):
  BatchGetUsers:          1 call, 80 unique IDs (deduplicated)
  BatchGetImages:         1 call, 500 post IDs (batched)
  BatchGetFollowerCounts: 1 call, 80 unique IDs (deduplicated)
  TOTAL:                  3 gRPC calls, running in parallel via Promise.all
  Latency:                ~15-30ms

  That's a 500x reduction in call count.
  That's a 250x-500x reduction in latency.
```

### B. Complementary Code Fixes

**Cursor-based pagination on the feed itself:**
```javascript
async function resolveFeed(userId, cursor = null, limit = 50) {
    // Never return an unbounded feed — even with DataLoader,
    // a 5,000-post feed is unnecessary
    const posts = await postService.GetFeed(userId, { after: cursor, limit });
    // ... DataLoader resolution as above ...
    return { posts, nextCursor: posts[posts.length - 1]?.id };
}
```

**Materialized follower counts via counter cache:**
```
Instead of computing follower counts on every feed load,
maintain a pre-computed counter in Redis:

  On follow event:   INCR user:{authorId}:follower_count
  On unfollow event:  DECR user:{authorId}:follower_count
  On feed resolve:    GET user:{authorId}:follower_count → O(1)

Populate via CDC (Debezium) from the followers table,
or via application-level events. This eliminates the
GetFollowerCount gRPC call entirely.
```

### C. The Infrastructure Fix: Kill the L4 + gRPC Black Hole

**Fix 1: Replace L4 LB with L7 (request-level) load balancing for gRPC**

The direct fix — use a load balancer that understands HTTP/2 frames and distributes individual gRPC **requests**, not TCP connections.

```yaml
# Option A: Istio sidecar proxy (Envoy-based, L7-aware)
# Envoy terminates the HTTP/2 connection and load-balances
# each gRPC request independently across all replicas

apiVersion: networking.istio.io/v1alpha3
kind: DestinationRule
metadata:
  name: user-service-lb
spec:
  host: user-service
  trafficPolicy:
    loadBalancer:
      simple: LEAST_REQUEST    # ← Distributes by in-flight request count
                                #   NOT by TCP connection
```

```yaml
# Option B: If not using a service mesh, use gRPC-native
# client-side load balancing (e.g., grpc-js with xDS or
# round-robin pick_first replacement)

# In the gRPC client configuration:
const client = new UserServiceClient(
    'dns:///user-service.default.svc.cluster.local',
    grpc.credentials.createInsecure(),
    { 'grpc.service_config': JSON.stringify({
        loadBalancingConfig: [{ round_robin: {} }]  // ← client resolves ALL endpoints
    })}                                              //   and round-robins REQUESTS
);
```

**Why LEAST_REQUEST is the correct algorithm:**
```
Round-robin: equal distribution by count, ignores request cost
  → A 1,500-call feed load and a 10-call feed load get equal weight
  → Can still create imbalance under skewed workloads

Least-request: routes to the replica with fewest in-flight requests
  → A replica processing an expensive request naturally gets FEWER
     new requests routed to it
  → Self-balancing under ANY workload distribution
  → Inherently cost-aware without needing to know request cost
```

**Fix 2: Bulkhead Pattern — Isolate Heavy Feed Loads**

```
                    ╔══════════════════════════════════════════════════════════════╗
                    ║    API Gateway /                                             ║
                    ║    Request Classifier                                        ║
                    ║    (check user.following                                     ║
                    ║     count from cache)                                        ║
                    ╚══════════════════════════════════════════════════════════════╝
                           │          │
                following > 200    following ≤ 200
                           │          │
                    ╔══════════════════════════════════════════════════════════════╗
                    ║  HEAVY      │  │ STANDARD                                    ║
                    ║  POOL       │  │ POOL                                        ║
                    ║  (dedicated │  │ (main fleet)                                ║
                    ║   replicas, │  │                                             ║
                    ║   higher    │  │                                             ║
                    ║   timeouts) │  │                                             ║
                    ╚══════════════════════════════════════════════════════════════╝
```

A heavy user's feed load melting the heavy pool **cannot cascade** to standard users. This is the Bulkhead Pattern from Nygard's *Release It!*.

**Fix 3: Circuit Breaker + Adaptive Concurrency Limiting**

```java
// Resilience4j at the application layer
// Prevents any single downstream from being overwhelmed

CircuitBreakerConfig cbConfig = CircuitBreakerConfig.custom()
    .failureRateThreshold(50)
    .slowCallRateThreshold(80)
    .slowCallDurationThreshold(Duration.ofMillis(500))
    .slidingWindowSize(20)
    .waitDurationInOpenState(Duration.ofSeconds(10))
    .build();

BulkheadConfig bhConfig = BulkheadConfig.custom()
    .maxConcurrentCalls(25)
    .maxWaitDuration(Duration.ofMillis(200))
    .build();
```

### D. Complete Fix Matrix

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  LAYER                │ FIX                              │ TOOL               ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Query pattern        │ DataLoader: batch + deduplicate  │ graphql/dataloader ║
║                       │ per-post gRPC calls              │                    ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Feed size            │ Cursor-based pagination          │ Application code   ║
║                       │ Hard cap at 50 posts/page        │                    ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Follower counts      │ Materialized counter cache       │ Redis + Debezium   ║
║                       │ Updated async via CDC            │ (CDC)              ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Load balancing       │ Replace L4 LB with L7 (Envoy)   │ Istio / Envoy /     ║
║                       │ LEAST_REQUEST algorithm          │ Linkerd            ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Alternative LB       │ gRPC client-side LB with         │ grpc-js xDS or     ║
║                       │ direct endpoint resolution       │ round_robin config ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Traffic isolation    │ Bulkhead: separate heavy/standard│ Istio              ║
║                       │ user pools                       │ VirtualService     ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Resilience           │ Circuit breaker on downstream    │ Resilience4j /     ║
║                       │ calls + concurrency limiter      │ Envoy              ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Observability        │ Per-user-tier latency metrics    │ Prometheus +       ║
║                       │ Alert on CPU skew > 2x across    │ Grafana            ║
║                       │ replicas of same service         │                    ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Code review gates    │ Mandatory DataLoader usage in    │ ESLint custom rule ║
║                       │ all GraphQL resolvers            │ / CI check         ║
║                       │ Flag any await-in-loop pattern   │                    ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

### The Layered Defense:

```
DataLoader eliminates the CREATION of expensive fan-out.
Pagination caps the MAXIMUM possible fan-out.
Counter caches eliminate an entire class of gRPC calls.
L7 load balancing eliminates the CONCENTRATION of traffic.
Bulkheads eliminate the BLAST RADIUS of any remaining hot paths.
Circuit breakers eliminate the AMPLIFICATION from retries.
Observability ensures you SEE the next incident before users do.
```

No single fix is sufficient. Each layer defends against a different failure mode. Together, they make this class of incident structurally impossible.
