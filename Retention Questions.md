# WEEK 2 RETENTION TEST — ANSWERS

---

# Part 1: Rapid-Fire

---

**Q1 [TCP — TIME_WAIT]:**

a) TIME_WAIT ensures delayed packets from a closed connection aren't misinterpreted by a new connection reusing the same source/destination port tuple.

b) 2×MSL (Maximum Segment Lifetime), typically 60 seconds. 1×MSL guarantees any in-flight packet has expired; 2×MSL guarantees both the final ACK and any retransmission of the FIN it acknowledges have expired.

c) `sysctl -w net.ipv4.tcp_tw_reuse=1` — allows reusing TIME_WAIT sockets for new outbound connections when the timestamp indicates safety.

---

**Q2 [HTTP — HoL Blocking]:**

HTTP/1.1 used 6 parallel TCP connections per domain, so a single packet loss only stalled ~1/6 of in-flight resources. HTTP/2 multiplexes ALL streams onto ONE TCP connection, meaning one lost TCP segment stalls EVERY stream simultaneously — the blast radius of a single packet loss is 6x worse. HTTP/3 solves this by replacing TCP with QUIC, which runs over UDP and implements per-stream independent flow control — a lost packet in stream A only stalls stream A, while streams B, C, D continue unblocked because QUIC handles retransmission at the stream level, not the connection level.

---

**Q3 [gRPC — L4 Black Hole]:**

a) L4 load balancer distributes TCP connections (not requests), and gRPC's long-lived HTTP/2 connections multiplex all requests onto 1-2 pinned connections to replica 1, while replicas 2-6 receive zero application traffic.

b) Fix 1: Replace L4 LB with L7 LB (Envoy/Istio) using LEAST_REQUEST algorithm — distributes individual gRPC requests, not TCP connections. Fix 2: gRPC client-side load balancing with direct endpoint resolution (`round_robin` channel policy), bypassing the L4 LB entirely.

---

**Q4 [WebSockets — 60s Drops]:**

a) An intermediate network component (NAT gateway, security group, proxy, or ALB if in the path) has a 60-second idle connection timeout, killing WebSocket TCP connections that have no data flowing.

b) Implement WebSocket ping/pong heartbeat frames every 30 seconds (well within the 60-second idle window) to keep the connection alive through all idle timeout detectors.

c) AWS NLB has a **fixed 350-second** idle timeout (not configurable). 350 ≠ 60, so the NLB is not the component dropping connections at 60-second intervals.

---

**Q5 [DNS — ndots:5]:**

a) **5 DNS queries** per HTTP call.

b)
```
1. fraud-api.payments.example.com.default.svc.cluster.local  → NXDOMAIN
2. fraud-api.payments.example.com.svc.cluster.local          → NXDOMAIN
3. fraud-api.payments.example.com.cluster.local               → NXDOMAIN
4. fraud-api.payments.example.com.us-east-1.compute.internal  → NXDOMAIN
5. fraud-api.payments.example.com.                            → SUCCESS
```

c) A trailing dot: `fraud-api.payments.example.com.` — tells the resolver this is an absolute FQDN, skip all search domain expansion.

---

**Q6 [CDN — Cache-Control]:**

```
T=0:   Cache MISS. CDN fetches from origin, caches response. 
       Content is FRESH (within max-age=300). Served directly.

T=200: Content still FRESH (200 < 300). Served from cache, 
       no origin contact.

T=350: Content is STALE (350 > 300). But within stale-while-
       revalidate window (300+60=360). CDN serves stale content 
       IMMEDIATELY and revalidates with origin ASYNCHRONOUSLY 
       in the background.

T=400: Beyond stale-while-revalidate (400 > 360). CDN must 
       revalidate SYNCHRONOUSLY — user waits for origin 
       response. Normal cache miss behavior.

T=350 + origin down: Content is stale (350 > 300). CDN 
       attempts revalidation but origin is DOWN. 
       stale-if-error=86400 activates — CDN serves stale 
       content (up to 24 hours old) instead of returning 
       a 502/504 to the user. Site stays up on stale data.
```

---

**Q7 [SQL/ACID — Isolation Levels]:**

a) READ COMMITTED: Txn A sees **$500**. READ COMMITTED always reads the latest COMMITTED data, so after Txn B commits, Txn A's second read sees the updated value.

b) REPEATABLE READ: Txn A sees **$1000**. REPEATABLE READ guarantees a consistent snapshot from the transaction's start — subsequent reads within the same transaction always return the same data regardless of other commits.

c) **Non-repeatable read** (also called "read skew") — the same row returns different values on two reads within the same transaction.

---

**Q8 [SQL/Indexing — Composite Index]:**

Composite index: `(user_id, status, created_at)` — leftmost prefix rule applies.

a) `WHERE user_id = 123` — **YES.** Matches the leftmost prefix of the index.

b) `WHERE user_id = 123 AND created_at > '2024-01-01'` — **PARTIALLY.** Uses the index for `user_id = 123` (leftmost prefix), but SKIPS `status` (the second column), so `created_at` range scan cannot use the index efficiently — it scans all statuses within user_id=123.

c) `WHERE status = 'active'` — **NO.** `status` is the second column; without `user_id` (the leftmost prefix), the index cannot be used.

d) `WHERE user_id = 123 AND status = 'active' AND created_at > '2024-01-01'` — **YES, perfectly.** Matches all three columns of the index in order: equality on user_id, equality on status, range on created_at.

e) `WHERE status = 'active' AND user_id = 123` — **YES.** The query optimizer reorders predicates to match the index — the written order of WHERE clauses doesn't matter, only the columns present.

---

**Q9 [SQL/MVCC]:**

a) Readers never block writers because PostgreSQL keeps **multiple versions of each row** (tuples). A reader's transaction sees a snapshot from its start time and reads the version that was current at that snapshot, while writers create new versions without modifying the old ones. No lock contention between reads and writes.

b) The cost is **dead tuples** — old row versions that are no longer visible to any active transaction accumulate on disk, bloating tables and indexes. The **VACUUM** process (autovacuum in normal operation) cleans up these dead tuples by marking their space as reusable.

---

**Q10 [NoSQL — Cassandra Write Path]:**

```
[1] Commit log append         ← durability guarantee (sequential disk write)
[2] Memtable write            ← in-memory, fast
    ═══════════════════════
    "write successful" returned to client HERE (after steps 1+2)
    ═══════════════════════
[3] SSTable flush             ← async, when memtable is full
[4] Compaction                ← async background, merges SSTables
```

The write is acknowledged after commit log append + memtable write. SSTable flush and compaction happen asynchronously and are invisible to the client.

---

**Q11 [NoSQL — Cassandra QUORUM]:**

a) With 2 surviving nodes and QUORUM=2, you need BOTH to respond. Failures are intermittent because they occur when one surviving node is **transiently slow** — GC pause, compaction I/O, thread pool saturation — and misses the read timeout. When both nodes are responsive, QUORUM succeeds; when either is momentarily degraded, it fails.

b) RF=3 on 3 nodes means every piece of data is stored on ALL nodes — losing one node leaves exactly QUORUM available with **zero margin**. You can tolerate 1 node failure but cannot tolerate 1 node failure + any transient degradation on a survivor.

c) RF=3 on 6 nodes: each piece of data is on 3 of 6 nodes. If one node dies, its data still has 2 remaining replicas on other healthy nodes, BUT the surviving 5 nodes each only owned a fraction of the data — the load redistribution is spread across more nodes. More importantly, QUORUM (2 of 3) for any given key still requires 2 responses from 2 surviving replicas, but those 2 replicas aren't also absorbing ALL the dead node's coordinator duties — the load increase per survivor is ~20% (1/5) instead of ~50% (1/2), making transient failures far less likely.

---

**Q12 [NoSQL/Redis — Eviction Policy]:**

`volatile-lru` evicts the Least Recently Used key **only among keys with a TTL set**. Type A (hot sessions WITH TTL) get evicted despite being accessed 100x/sec. Type B (cold config WITHOUT TTL) are **immune from eviction** despite being accessed 1x/hour.

This is backwards — the eviction policy is protecting cold, rarely-used data while destroying hot, critical data. The correct policy is **allkeys-lru**, which evicts based purely on access recency regardless of TTL presence. The cold config keys (1x/hour) would be evicted first because they're the least recently used, preserving the hot session data.

---

**Q13 [Caching — Stampede]:**

a) **Cache stampede** (also called thundering herd or dogpile).

b) Fix 1: **Request coalescing / singleflight** — only the first of 5,000 concurrent requests actually queries the database; the other 4,999 wait for and share that one result. Fix 2: **Stale-while-revalidate / background refresh** — serve the stale cached value immediately while one background process refreshes the cache, so users never see a miss. Fix 3: **Probabilistic early expiration (jittered TTL)** — each cache entry expires at a slightly random time, preventing mass simultaneous expiration.

---

**Q14 [Caching — Invalidation Race]:**

a) PostgreSQL uses **MVCC with READ COMMITTED** isolation by default. The reader's SELECT sees only the **last committed version** of the row. Since the UPDATE transaction hasn't committed yet, the reader sees the old (pre-update) data. This is MVCC working correctly — uncommitted changes are invisible to other transactions.

b) Commit the database transaction FIRST, then delete the cache key SECOND. After commit, any concurrent reader that misses the cache will read the NEW committed data from PostgreSQL, so re-caching cannot poison the cache with stale data.

---

**Q15 [Cross-Topic — Read-After-Write]:**

a) **Read-after-write consistency** (also called read-your-writes consistency).

b) DATABASE REPLICA case: After a write, route the SAME user's subsequent reads to the **primary** for a brief window (e.g., 15 seconds), or track the write's WAL LSN and only route to a replica once its replay position has passed that LSN.

c) CACHE case: Use **write-through caching** — after committing the write to the database, immediately write the new value to the cache (instead of deleting and letting the next read repopulate). The user's immediate read hits the cache and sees the new data.

d) Both fixes share the same principle: **after a write, ensure the "copy" (replica or cache) that the user will read from has the updated data before routing the read to it.** The write path takes responsibility for updating (or bypassing) the stale copy, rather than hoping the copy catches up in time.

---

# Part 2: Compound Scenario

---

## Question 1: All Problems

### Problem 1: Entitlement Cache Stampede (Cascade — Traffic Surge Trigger)

**Component:** Redis entitlement cache → gRPC entitlement service → PostgreSQL

**Root cause:** 1.4M new users hit "Watch Live" simultaneously. Their entitlement keys (`entitled:<user_id>`) are not cached because they haven't accessed the platform during the cache TTL window (600s). All 1.4M requests miss Redis and fall through to the gRPC entitlement service and PostgreSQL simultaneously — a textbook cache stampede at massive scale.

**Evidence:**
```
→ Redis hit rate: 97% → 34% (1.4M new users = 1.4M cache misses)
→ gRPC requests/sec: 800 → 41,000 (51x increase — every miss 
  generates a gRPC call)
→ PostgreSQL queries/sec: 220 → 18,500 (84x increase)
→ PgBouncer cl_waiting: 2,340 (pool completely exhausted)
→ Pool: 150/150 active (zero headroom)
→ The 400K existing viewers had cached entitlements from pre-show 
  → they're fine. Only NEW arrivals are affected.
```

### Problem 2: Redis Hot Node — Slot Imbalance (Pre-existing/Independent)

**Component:** Redis Cluster node 4

**Root cause:** 73% of entitlement keys hash to slots owned by Redis node 4. This is a key distribution / hash slot assignment problem — analyzed in Q2. Node 4 is handling 73% of 410K ops/sec = ~299K ops/sec while other nodes handle ~22K each. Node 4 is at 99% CPU not because of big keys (0.3ms per op is normal) but because of sheer volume concentration.

**Evidence:**
```
→ Redis node 4 CPU: 99% (other nodes presumably normal)
→ Node 4 has 73% of all entitlement keys
→ slowlog shows 0.3ms per op (normal — NOT a big key issue)
→ This is INDEPENDENT of the traffic surge: the slot imbalance 
  existed before the event. The surge made it VISIBLE.
→ With even distribution, node 4 would be at ~16.7% of load 
  instead of 73%, and all nodes would handle the traffic fine.
```

### Problem 3: gRPC L4 Load Balancer Black Hole (Pre-existing/Independent)

**Component:** gRPC entitlement service (6 replicas behind L4 LB)

**Root cause:** The entitlement service sits behind an **L4 load balancer**. gRPC uses long-lived HTTP/2 connections. The L4 LB pinned TCP connections to replica 1, concentrating all 41,000 gRPC requests/sec onto a single replica. Replicas 2-6 are idle.

**Evidence:**
```
→ Replica 1: 94% CPU, replicas 2-6: 11% (binary distribution)
→ "6 replicas behind L4 load balancer" (architecture states L4)
→ gRPC + L4 = black hole pattern (Week 1, learned twice now)
→ 11% on idle replicas = healthcheck baseline, zero app traffic
→ This is INDEPENDENT: the L4+gRPC misconfiguration existed 
  before the event. The surge exposed it.
```

### Problem 4: PostgreSQL Connection Pool Exhaustion (Cascade)

**Component:** PostgreSQL via PgBouncer

**Root cause:** The entitlement query (`SELECT e.*, p.payment_status FROM entitlements e JOIN payments p ...`) is averaging 67ms under load (normally 1.2ms — 56x slower due to contention and I/O pressure from 84x query volume increase). At 67ms per query, each connection is held 56x longer, draining the 150-connection pool. 2,340 client connections are queued waiting.

**Evidence:**
```
→ PgBouncer cl_waiting: 2,340
→ Pool: 150/150 (fully exhausted)
→ avg_exec_time: 67ms (normally 1.2ms)
→ 15,200 calls/minute = 253/sec
→ At 67ms per query: 253 × 67ms = 17 seconds of connection-time 
  per second — needs ~17 connections just for this query. 
  But with 15,200 queries queued and only 150 connections, 
  most time is spent WAITING in the PgBouncer queue, not executing.
→ Error: "Connection pool exhausted" at 3,100/minute
```

### Problem 5: WebSocket Server Memory Pressure (Cascade)

**Component:** WebSocket servers (20 servers)

**Root cause:** 1.46M connected users sending chat messages during the fight. Chat message delivery latency spiked from 50ms to 2,400ms. At 14.2GB/16GB (89%) memory per server, the servers are approaching OOM. The message broadcast to 1.46M users requires per-connection write buffers. Slow message delivery means buffers accumulate. New WebSocket upgrades are being rejected with 503s because servers can't accept more connections.

**Evidence:**
```
→ Memory: 14.2GB / 16GB per server (89%)
→ Connected: 1.46M (should be 1.8M — 340K can't connect 
  because of entitlement failures, but also some rejected by 503)
→ Chat delivery latency: 50ms → 2,400ms
→ HTTP 503 on new WebSocket upgrade requests
→ 1.46M / 20 servers = 73K connections per server 
  → per-connection write buffers accumulating during 
    high-volume chat message broadcast
```

### Problem 6: Cassandra Write Saturation (Cascade)

**Component:** Cassandra (chat message storage + analytics)

**Root cause:** Cassandra's MutationStage thread pool is fully saturated at 256/256 active threads with 12,847 mutations pending. 1.46M viewers sending chat messages and generating analytics events during the live fight overwhelm the write capacity.

**Evidence:**
```
→ Write latency: 3ms → 45ms (15x increase)
→ MutationStage active: 256/256 (thread pool fully consumed)
→ MutationStage pending: 12,847 (massive backlog)
→ Read latency: normal (8ms) — reads aren't affected, 
  confirming this is write-side saturation only
```

### Problem 7: CoreDNS Overload from ndots + Retries (Cascade)

**Component:** Kubernetes CoreDNS

**Root cause:** The entitlement service FQDN `entitlement-svc.payments.internal.cluster.local` has 4 dots, which is less than ndots:5, so each DNS lookup generates search domain expansion queries. Failed gRPC calls are retried, each retry generating 5+ DNS queries. The combination of 41,000 gRPC calls/sec + retries + 5 DNS queries each overwhelms CoreDNS.

**Evidence:**
```
→ CoreDNS: 48,000 queries/sec (6x normal 8,000)
→ ndots:5, no trailing dot on the FQDN
→ "entitlement-svc.payments.internal.cluster.local" = 4 dots < 5
→ Each failed+retried gRPC call generates 5+ DNS lookups
→ 8,400 gRPC timeouts/minute = 140/sec of retries 
  × 5 DNS queries = 700 extra DNS queries/sec just from retries
```

**Wait** — actually, `entitlement-svc.payments.internal.cluster.local` already has 4 dots. With ndots:5, hostnames with fewer than 5 dots get search domains appended. 4 < 5, so YES, search domain expansion applies. But this FQDN ends in `.cluster.local` — one of the search domains IS `.svc.cluster.local`, so the resolution of `entitlement-svc.payments.internal.cluster.local.default.svc.cluster.local` would NXDOMAIN, etc. Each lookup generates unnecessary queries before finding the actual record.

### Problem 8: CDN Caching 503 Error Responses (Independent/Pre-existing)

**Component:** CloudFront CDN

**Root cause:** The API responses go through CloudFront and have `Cache-Control: max-age=2, stale-while-revalidate=2`. When the backend returned 503 errors at 21:02, CloudFront cached those error responses with the same cache policy. For up to 4 seconds (2s max-age + 2s stale-while-revalidate), users receive cached 503s even after the backend recovers. The CDN doesn't distinguish between success and error responses for caching.

**Evidence:**
```
→ "CloudFront is returning cached 503 errors"
→ Cache-Control: max-age=2, stale-while-revalidate=2
→ "cached ERROR RESPONSES for up to 4 seconds"
→ This is a configuration issue: error responses should 
  not be cached with the same policy as success responses
```

### Classification

```
┌──────────────────────────┬───────────────────────────────┐
│ CASCADE (traffic surge)  │ INDEPENDENT / PRE-EXISTING    │
├──────────────────────────┼───────────────────────────────┤
│ Entitlement stampede     │ Redis slot imbalance (73%)    │
│ PostgreSQL pool exhaust  │ gRPC L4 black hole            │
│ WebSocket memory pressure│ CDN caching error responses   │
│ Cassandra write saturate │                               │
│ CoreDNS overload         │                               │
└──────────────────────────┴───────────────────────────────┘

The three independent problems are FORCE MULTIPLIERS:
→ Redis slot imbalance makes the stampede worse 
  (73% of load on one node instead of distributed)
→ gRPC black hole makes entitlement checks 6x slower 
  (1 replica doing all work instead of 6)
→ CDN caching errors extends user-facing impact by 4 seconds 
  after backend recovery
```

---

## Question 2: Redis Node 4 — 73% Key Concentration

### The Technical Explanation

```
Redis Cluster divides the keyspace into 16,384 hash slots.
Each master node is assigned a range of slots.

When a key is stored, Redis computes:
  SLOT = CRC16(key) mod 16384

The slot determines which node owns the key.

With 6 masters and even slot distribution:
  Node 1: slots 0-2730       (16.7%)
  Node 2: slots 2731-5460    (16.7%)
  Node 3: slots 5461-8191    (16.7%)
  Node 4: slots 8192-10922   (16.7%)
  Node 5: slots 10923-13652  (16.7%)
  Node 6: slots 13653-16383  (16.7%)
```

### Why 73% of Entitlement Keys Land on Node 4

```
The keys are formatted as: "entitled:<user_id>"

The problem: if user_ids have a PATTERN (e.g., sequential 
integers, UUIDs with common prefixes), the CRC16 hash of 
"entitled:1234", "entitled:1235", "entitled:1236"... may 
cluster into a narrow range of hash slots.

BUT — CRC16 is generally well-distributed for sequential 
integers. 73% concentration is TOO extreme for simple 
hash collision.

MORE LIKELY CAUSE: Redis hash tags.

If the keys are formatted as:
  "entitled:{user_id}"     (with curly braces)

Redis Cluster only hashes the portion INSIDE the curly 
braces for slot assignment:
  SLOT = CRC16("user_id") mod 16384

But the keys in the scenario are "entitled:<user_id>" 
with angle brackets, not curly braces. So hash tags 
aren't the issue.

MOST LIKELY CAUSE: Uneven slot assignment.

During cluster creation or after a failed resharding/
rebalancing operation, node 4 was assigned MORE hash 
slots than other nodes. Instead of ~2,731 slots each:

  Node 1: 1,200 slots  (7.3%)
  Node 2: 1,100 slots  (6.7%)
  Node 3: 1,000 slots  (6.1%)
  Node 4: 11,884 slots (72.5%) ← OWNS MOST SLOTS
  Node 5: 600 slots    (3.7%)
  Node 6: 600 slots    (3.7%)

This can happen when:
  → A node was added but resharding wasn't completed
  → A node was removed and its slots were assigned to 
    node 4 as a temporary measure and never rebalanced
  → Manual slot migration was interrupted
  → The cluster was initially created with uneven 
    slot assignment

The CRC16 hash distributes keys evenly across 16,384 
slots — but if one node OWNS 73% of the slots, it gets 
73% of ALL keys regardless of hash distribution quality.
```

### The Fix

```bash
# Check current slot distribution:
redis-cli --cluster check redis-node-1:6379

# This will show how many slots each master owns.
# If node 4 owns ~12,000 slots, that confirms the diagnosis.

# Rebalance slots evenly across all 6 masters:
redis-cli --cluster rebalance redis-node-1:6379

# This redistributes slots so each master owns ~2,731 slots.
# Data migrates live — keys in moved slots are transferred 
# to their new owner node.

# For more control, specify weights:
redis-cli --cluster rebalance redis-node-1:6379 \
  --cluster-use-empty-masters \
  --cluster-weight node1-id=1 node2-id=1 node3-id=1 \
                   node4-id=1 node5-id=1 node6-id=1

# CAUTION: Rebalancing during an active incident moves data 
# across nodes, consuming network and CPU. This adds 
# temporary load to an already stressed cluster.
# 
# SAFER: Do this AFTER the immediate incident is mitigated.
# For NOW, the hot-node problem is better addressed by 
# read-from-replicas (immediate) + the creative fix in Q5.
```

---

## Question 3: gRPC L4 Black Hole — Again

### a) The Problem (One Sentence)

L4 load balancer distributes TCP connections (not requests), pinning all 41,000 gRPC requests/sec to replica 1's single HTTP/2 connection while replicas 2-6 receive zero application traffic.

### b) Universal Monitoring Alert

```yaml
# This alert detects CPU skew across replicas of ANY service.
# It catches the L4+gRPC black hole pattern regardless of 
# which service is affected.

# Prometheus alert rule:
groups:
  - name: replica_skew_detection
    rules:
      - alert: ReplicaCPUSkewCritical
        expr: |
          (
            max by (deployment) (
              rate(container_cpu_usage_seconds_total{container!=""}[5m])
            )
            /
            avg by (deployment) (
              rate(container_cpu_usage_seconds_total{container!=""}[5m])
            )
          ) > 3.0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: >
            Replica CPU skew detected in {{ $labels.deployment }}.
            The hottest replica is using {{ $value }}x the average 
            CPU of all replicas. This typically indicates L4 LB + 
            gRPC connection pinning or a hot-partition problem.
          runbook: >
            1. Check if this service uses gRPC behind an L4 LB.
            2. If yes: restart gRPC client pods to redistribute 
               connections, then plan L7 LB migration.
            3. If no: investigate for hot partitions or uneven 
               data distribution.

# WHAT THIS CATCHES:
# max/avg ratio > 3.0 means the hottest replica is using 
# 3x the average CPU. 
#
# In this incident: 94% / ((94+11+11+11+11+11)/6) = 94/24.8 = 3.8
# → Alert fires at 3.8 > 3.0 ✅
#
# In normal operation: all replicas at ~15% CPU
# max/avg = 15/15 = 1.0 → no alert ✅
#
# This is SERVICE-AGNOSTIC. It works for:
# → gRPC entitlement service
# → gRPC bid service (Week 2 scenario)
# → gRPC anything behind any L4 LB
# → Any uneven load distribution, even non-gRPC
```

---

## Question 4: CDN Caching 503 Errors

### a) How max-age=2, stale-while-revalidate=2 Caches Errors

```
At 21:02, the backend returns an HTTP 503 with the SAME 
Cache-Control header as success responses:
  Cache-Control: max-age=2, stale-while-revalidate=2

CloudFront treats this like ANY cacheable response:

T=0 (21:02:00): Backend returns 503.
  CloudFront caches the 503 response.
  max-age=2 → fresh for 2 seconds.

T=0 to T=2 (21:02:00-21:02:02): 
  All requests to this URL get the CACHED 503.
  CloudFront doesn't even contact the backend.
  Even if the backend recovered at 21:02:01, users 
  still get the cached error until T=2.

T=2 to T=4 (21:02:02-21:02:04):
  Content is stale. stale-while-revalidate=2 activates.
  CloudFront serves the STALE 503 immediately and 
  revalidates asynchronously in the background.
  If the background revalidation gets a 200, the cache 
  updates — but the user who triggered it already got 
  the stale 503.

T=4+ (21:02:04+):
  Beyond stale-while-revalidate window.
  CloudFront revalidates synchronously.
  If backend is healthy, user finally gets a 200.

RESULT: Up to 4 seconds of cached 503 errors per URL.
With millions of users hitting thousands of unique 
entitlement-check URLs, the errors are STAGGERED — 
different URLs cached their 503 at different milliseconds 
during 21:02-21:03, so the 4-second window is rolling, 
not simultaneous. But at any given moment, some users 
are hitting a cached 503 for a URL whose backend 
has already recovered.
```

### b) How Error Responses Should Be Handled

```
Error responses (4xx, 5xx) should NEVER be cached with 
the same policy as success responses.

FIX 1: Origin sets different headers for errors.

  # In the application:
  if response.status >= 500:
      response.headers['Cache-Control'] = 'no-store, no-cache'
  else:
      response.headers['Cache-Control'] = 'max-age=2, s-w-r=2'

  # 503 responses get no-store → CDN never caches them
  # Users always get a fresh request to origin for errors
  # If origin is down, they get a real-time 503 (not a cached one)

FIX 2: CloudFront custom error response configuration.

  # CloudFront allows overriding error response caching:
  aws cloudfront update-distribution --id $DIST_ID \
    --custom-error-responses '{
      "Items": [
        {
          "ErrorCode": 503,
          "ErrorCachingMinTTL": 0,
          "ResponseCode": "503"
        },
        {
          "ErrorCode": 502,
          "ErrorCachingMinTTL": 0
        },
        {
          "ErrorCode": 504,
          "ErrorCachingMinTTL": 0
        }
      ]
    }'

  # ErrorCachingMinTTL: 0 → CloudFront caches 5xx errors 
  # for 0 seconds (effectively no caching).
  # Every request for a 5xx URL retries origin immediately.

FIX 3 (defense in depth): stale-if-error for SUCCESSES only.

  # For success responses, ADD stale-if-error:
  Cache-Control: max-age=2, stale-while-revalidate=2, stale-if-error=10

  # If origin returns a 5xx during revalidation, serve the 
  # LAST SUCCESSFUL response (stale but correct) instead of 
  # caching and serving the error.
  # This is the opposite of the current behavior: serve stale 
  # SUCCESS instead of fresh ERROR.
```

---

## Question 5: The ONE Fastest Mitigation — Creative Thinking

**The entitlement check is answering one question: "Has this user paid for this event?"**

340,000 users have paid. They have payment records in PostgreSQL. The entitlement check is CORRECT — they ARE entitled. The system just can't verify it fast enough.

### The Fix: Bypass the Entitlement Check Entirely — Grant Access to All Authenticated Users

```python
# Deploy a feature flag / emergency override:
# For this specific event, skip the entitlement check 
# and return "entitled" for ALL authenticated users.

async def check_entitlement(user_id, event_id):
    # EMERGENCY OVERRIDE: Main event live, entitlement 
    # system degraded. Grant access to all authenticated users.
    if event_id == "boxing-main-event-2024" and \
       FEATURE_FLAGS.get("emergency_entitlement_bypass"):
        return EntitlementResponse(
            entitled=True,
            stream_url=generate_stream_url(event_id)
        )
    
    # Normal path (for all other events):
    cached = await redis.get(f"entitled:{user_id}")
    if cached:
        return deserialize(cached)
    return await grpc_entitlement_service.check(user_id, event_id)
```

```bash
# Deploy:
kubectl set env deployment/api-service \
  EMERGENCY_ENTITLEMENT_BYPASS=true \
  BYPASS_EVENT_ID=boxing-main-event-2024

# TIME TO EFFECT: ~30-60 seconds (rolling deployment)
# RESULT: 
#   → ALL authenticated users immediately get stream access
#   → Redis, gRPC, PostgreSQL load drops to near zero for 
#     entitlement queries
#   → 340,000 stuck users start watching within 60 seconds
#   → PgBouncer cl_waiting drops to 0
#   → gRPC timeout errors stop
```

**The tradeoff — and why it's acceptable:**

```
RISK: Users who DIDN'T pay can watch for free.

MITIGATION OF THAT RISK:
  → To watch, users must be AUTHENTICATED (logged in)
  → You have their user_id — you can reconcile later
  → After the event, query PostgreSQL at leisure:
    SELECT user_id FROM viewing_logs 
    WHERE event_id = 'boxing-main-event-2024'
    AND user_id NOT IN (
      SELECT user_id FROM entitlements 
      WHERE event_id = 'boxing-main-event-2024'
    );
  → Bill unpaid viewers after the fact, or write it off 
    as the cost of the incident

BUSINESS MATH:
  → 340,000 paying customers × $79.99 PPV price = $27.2M at risk
  → Some fraction of non-paying users watch for free = maybe 
    $50K-$200K in lost revenue (most non-payers wouldn't have 
    paid anyway)
  → Refund liability from 340K angry paying customers >> 
    revenue loss from a few thousand freeloaders

  → REFUNDING $27.2M vs LOSING $200K
  → The business decision is obvious.

THIS IS THE SRE PRINCIPLE:
  "Graceful degradation means choosing WHICH property to 
  sacrifice when you can't maintain all of them."

  You sacrifice: strict entitlement enforcement (temporarily)
  You preserve: paying customer experience (the core product)
```

---

## Question 6: Complete Prioritized Mitigation Plan

### Priority Framework

```
This is a LIVE PAY-PER-VIEW EVENT.
340,000 paying customers can't watch.
Every minute = refund liability + brand damage + trending hashtag.

PRIORITY: Get users watching FIRST, fix infrastructure SECOND.
```

### Step 1: Emergency Entitlement Bypass (Second 0-60)

```bash
# THE business-critical fix. Gets 340K users watching immediately.
kubectl set env deployment/api-service \
  EMERGENCY_ENTITLEMENT_BYPASS=true \
  BYPASS_EVENT_ID=boxing-main-event-2024

# VERIFY (within 60 seconds):
# → "Watch Live" success rate should jump from ~60% to ~99%
# → gRPC timeout errors should drop to ~0 (no entitlement calls)
# → PostgreSQL queries/sec should drop from 18,500 toward baseline
# → PgBouncer cl_waiting should drop toward 0
# → Customer complaints should start decreasing

# DO NOT proceed to Step 2 until verified:
# → Users are successfully getting stream URLs
# → CDN is serving video to newly-entitled users
```

### Step 2: Fix CDN Error Caching (Minute 1-3)

```bash
# Even with the bypass, some users may still be hitting 
# cached 503 errors from 21:02-21:03.

# ACTION 2A: Purge all cached error responses
aws cloudfront create-invalidation \
  --distribution-id $CF_DIST_ID \
  --paths "/api/entitlement/*" "/api/stream/*"

# ACTION 2B: Configure CloudFront to not cache 5xx errors
aws cloudfront update-distribution --id $CF_DIST_ID \
  --custom-error-responses '{
    "Quantity": 3,
    "Items": [
      {"ErrorCode": 502, "ErrorCachingMinTTL": 0},
      {"ErrorCode": 503, "ErrorCachingMinTTL": 0},
      {"ErrorCode": 504, "ErrorCachingMinTTL": 0}
    ]
  }'

# VERIFY:
# → No more cached 503 responses 
# → All API calls reaching backend successfully
```

### Step 3: Fix gRPC Black Hole (Minute 3-5)

```bash
# Even with the entitlement bypass, the gRPC black hole 
# affects any OTHER gRPC service behind this L4 LB.
# Fix it now while load is reduced.

# Restart API servers to redistribute gRPC connections:
kubectl rollout restart deployment/api-service

# WAIT — this is the same API service we just deployed 
# the bypass on. A rollout restart will apply the bypass 
# AND redistribute connections.
# 
# Actually, the Step 1 env change already triggered a 
# rolling restart. The new pods will create new gRPC 
# connections distributed across all 6 replicas.

# VERIFY:
kubectl top pods -l app=entitlement-service
# → All 6 replicas should show roughly equal CPU
# → No single replica above 30%
```

### Step 4: Fix CoreDNS Overload (Minute 5-7)

```bash
# The entitlement bypass should have dramatically reduced 
# gRPC calls and thus DNS queries. But fix the root cause.

# ACTION 4A: Add trailing dot to the entitlement service FQDN
# In the service config:
kubectl set env deployment/api-service \
  ENTITLEMENT_SVC_HOST="entitlement-svc.payments.internal.cluster.local."

# ACTION 4B: Scale CoreDNS if still elevated
kubectl -n kube-system scale deployment/coredns --replicas=8

# VERIFY:
# → CoreDNS queries/sec declining toward 8,000 baseline
# → CoreDNS CPU well below 80%
```

### Step 5: Address WebSocket Memory Pressure (Minute 7-10)

```bash
# WebSocket servers at 89% memory with 1.46M connections.
# Chat delivery latency at 2,400ms.

# ACTION 5A: Scale WebSocket servers
kubectl scale deployment/websocket-server --replicas=30
# 20 → 30 servers. New connections will go to new servers.
# Existing connections stay on current servers.

# ACTION 5B: If chat is non-essential during the fight, 
# temporarily rate-limit chat messages:
kubectl set env deployment/websocket-server \
  CHAT_RATE_LIMIT_PER_USER=1msg/5sec

# This reduces write volume to Cassandra AND reduces 
# broadcast volume per WebSocket server.

# VERIFY:
# → WebSocket server memory stabilizing
# → Chat delivery latency declining
# → No more 503s on WebSocket upgrades
```

### Step 6: Address Cassandra Write Saturation (Minute 7-10, parallel)

```bash
# MutationStage is saturated: 256/256 active, 12,847 pending.
# The chat rate limit from Step 5 will help.

# Additionally, reduce analytics event granularity temporarily:
kubectl set env deployment/analytics-service \
  ANALYTICS_SAMPLE_RATE=0.1

# Only record 10% of viewer analytics events during the fight.
# Reduces Cassandra write load by ~90% for analytics.
# Full analytics can be estimated by multiplying by 10.

# VERIFY:
# → MutationStage pending declining toward 0
# → Write latency declining toward 3ms
```

### Step 7: Warm Entitlement Cache for Eventual Bypass Removal (Minute 10-15)

```bash
# The bypass is a temporary measure. We need to eventually 
# re-enable proper entitlement checks.
# Do this by pre-warming the Redis cache while load is low.

# Background job: iterate through all users who have 
# entitlements for this event and pre-cache them:
python3 -c "
import redis, psycopg2

db = psycopg2.connect(host='primary')
r = redis.RedisCluster(startup_nodes=[...])
cursor = db.cursor()
cursor.execute('''
    SELECT e.user_id, e.event_id, p.payment_status 
    FROM entitlements e 
    JOIN payments p ON e.payment_id = p.id 
    WHERE e.event_id = %s AND p.payment_status = %s
''', ('boxing-main-event-2024', 'completed'))

for row in cursor:
    r.set(f'entitled:{row[0]}', serialize_entitlement(row), ex=3600)
    
print(f'Pre-warmed {cursor.rowcount} entitlement cache entries')
"

# This runs against the primary (which is now unloaded) 
# and populates Redis with correct entitlements.
# 
# Once complete, the bypass can be safely disabled — 
# 97%+ of requests will hit the warm cache.
```

### Step 8: Rebalance Redis Slots (Post-Incident)

```bash
# NOT during the live event — resharding moves data and 
# adds load. Do this after the fight ends.

redis-cli --cluster rebalance redis-node-1:6379

# Verify even distribution:
redis-cli --cluster check redis-node-1:6379
# Each node should own ~2,731 slots (16.7%)
```

### Step 9: Disable Bypass and Restore Normal Operation (After Cache Warm)

```bash
# Only after Step 7 completes and cache is warm:
kubectl set env deployment/api-service \
  EMERGENCY_ENTITLEMENT_BYPASS=false

# VERIFY:
# → Entitlement cache hit rate > 95%
# → gRPC entitlement calls low
# → No user-facing impact from re-enabling checks
```

### Complete Timeline

```
┌────────────┬────────────────────────────────────────────────────┐
│ TIME       │ ACTION                                             │
├────────────┼────────────────────────────────────────────────────┤
│ 0-60s      │ EMERGENCY BYPASS — get 340K users watching         │
│            │ VERIFY: users getting stream URLs                  │
├────────────┼────────────────────────────────────────────────────┤
│ 1-3min     │ Purge CDN cached errors + configure no-cache       │
│            │ for 5xx responses                                  │
│            │ VERIFY: no cached 503s                             │
├────────────┼────────────────────────────────────────────────────┤
│ 3-5min     │ Verify gRPC redistribution (from bypass rollout)   │
│            │ Fix CoreDNS (trailing dot + scale)                 │
│            │ VERIFY: even CPU across gRPC replicas              │
├────────────┼────────────────────────────────────────────────────┤
│ 5-10min    │ Scale WebSocket servers + rate limit chat          │
│            │ Sample analytics events at 10%                     │
│            │ VERIFY: WS memory stable, Cassandra catching up    │
├────────────┼────────────────────────────────────────────────────┤
│ 10-15min   │ Pre-warm entitlement cache from PostgreSQL         │
│            │ VERIFY: Redis hit rate climbing toward 97%         │
├────────────┼────────────────────────────────────────────────────┤
│ 15min+     │ Disable bypass, restore normal entitlement flow    │
│            │ VERIFY: normal operation, no user impact           │
├────────────┼────────────────────────────────────────────────────┤
│ POST-      │ Rebalance Redis slots (when load is low)           │
│ EVENT      │ Post-incident review                               │
│            │ Reconcile: identify non-paying viewers             │
│            │ Plan: L7 LB for gRPC, pre-event cache warming      │
└────────────┴────────────────────────────────────────────────────┘
```

---

## Question 7: Three Things to Do BEFORE the Event

### 1. Pre-Warm the Entitlement Cache Before the Push Notification

```
THE SPECIFIC PROBLEM TO PREVENT:
  1.4M users arriving simultaneously, all missing the 
  entitlement cache, all stampeding PostgreSQL.

THE SPECIFIC PRE-WORK:

  BEFORE sending the push notification at 20:55:
  → Query all users who purchased the PPV event
  → Pre-populate their Redis entitlement cache entries
  → SET entitled:<user_id> with TTL=3600 (1 hour, 
    covering the entire event duration)

  python3 warm_entitlement_cache.py \
    --event-id=boxing-main-event-2024 \
    --ttl=3600

  With 2M expected viewers pre-cached:
  → Push notification arrives → users click "Watch Live"
  → Redis HIT rate stays at ~97%
  → gRPC entitlement service sees ~3% of traffic (new signups)
  → PostgreSQL stays at baseline load
  → The entire stampede is PREVENTED

  Also: set the cache TTL to cover the ENTIRE event 
  (3600s, not 600s). A 600s TTL means entitlements 
  expire MID-FIGHT, causing a second stampede.
```

### 2. Fix gRPC L4 Load Balancer → L7 BEFORE the Event

```
THE SPECIFIC PROBLEM TO PREVENT:
  gRPC entitlement service behind L4 LB → connection 
  pinning → 1 of 6 replicas handling all traffic.

THE SPECIFIC PRE-WORK:

  Replace the L4 internal LB with an L7-aware load 
  balancer for ALL gRPC services:

  Option A: Deploy Istio/Envoy sidecar with 
  LEAST_REQUEST load balancing:

  apiVersion: networking.istio.io/v1alpha3
  kind: DestinationRule
  metadata:
    name: entitlement-service-lb
  spec:
    host: entitlement-svc.payments.internal
    trafficPolicy:
      loadBalancer:
        simple: LEAST_REQUEST

  Option B: Configure gRPC client-side load balancing 
  with round_robin in the API service.

  DEPLOY AND VERIFY at least 1 week before the event.
  Load test at 2x expected peak to confirm even 
  distribution across all replicas.

  Also: set the alert from Q3 to catch any future 
  replica skew across ANY gRPC service.
```

### 3. Load Test the EXACT Traffic Pattern: Spike from Push Notification

```
THE SPECIFIC PROBLEM TO PREVENT:
  The entire cascade — traffic spike overwhelming the 
  cache hierarchy, connection pools, and downstream services.

THE SPECIFIC PRE-WORK:

  Don't just "load test at 2M users."
  Test the EXACT pattern that caused the incident:

  SCENARIO 1 — "Push notification spike":
    → Start with 400K simulated users (steady state)
    → At T=0, add 1.4M users in 4 minutes (ramp)
    → All 1.4M users call the entitlement check endpoint
    → Measure: Redis hit rate, gRPC latency, PostgreSQL 
      queries/sec, PgBouncer cl_waiting, error rate
    → Pass criteria: p99 < 500ms, error rate < 0.1%

  SCENARIO 2 — "Cold cache spike":
    → Flush the entitlement cache entirely
    → Hit 1.8M concurrent entitlement checks 
      against empty cache
    → This simulates the worst case: what if pre-warming 
      fails or cache evicts?
    → Measure the same metrics
    → This test WOULD HAVE revealed:
      - Redis slot imbalance (73% on node 4)
      - gRPC black hole (1 replica saturated)
      - PostgreSQL pool exhaustion at 150 connections
      - CoreDNS overload from ndots expansion

  SCENARIO 3 — "Chat flood":
    → 1.8M WebSocket connections
    → Each sending 1 message/5 seconds (chat during fight)
    → Measure: WebSocket server memory, Cassandra write 
      latency, MutationStage thread pool utilization
    → Size WebSocket servers and Cassandra for THIS load

  Run all three scenarios AT LEAST 1 week before the event.
  Fix everything that breaks. Re-test until clean.

  Also from these tests, determine:
    → Correct PgBouncer pool size (may need 300, not 150)
    → Correct Redis maxmemory (may need more headroom)
    → Correct WebSocket server count and memory limits
    → Correct Cassandra write thread pool size
    → Correct CoreDNS replica count
```
