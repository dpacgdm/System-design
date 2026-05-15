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
╔══════════════════════════════════════════════════════════════╗
║  CASCADE (traffic surge)  │ INDEPENDENT / PRE-EXISTING       ║
╠══════════════════════════════════════════════════════════════╣
║  Entitlement stampede     │ Redis slot imbalance (73%)       ║
║  PostgreSQL pool exhaust  │ gRPC L4 black hole               ║
║  WebSocket memory pressure│ CDN caching error responses      ║
║  Cassandra write saturate │                                  ║
║  CoreDNS overload         │                                  ║
╚══════════════════════════════════════════════════════════════╝

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
╔════════════════════════════════════════════════════════════════╗
║  TIME       │ ACTION                                           ║
╠════════════════════════════════════════════════════════════════╣
║  0-60s      │ EMERGENCY BYPASS — get 340K users watching       ║
║             │ VERIFY: users getting stream URLs                ║
╠════════════════════════════════════════════════════════════════╣
║  1-3min     │ Purge CDN cached errors + configure no-cache     ║
║             │ for 5xx responses                                ║
║             │ VERIFY: no cached 503s                           ║
╠════════════════════════════════════════════════════════════════╣
║  3-5min     │ Verify gRPC redistribution (from bypass rollout) ║
║             │ Fix CoreDNS (trailing dot + scale)               ║
║             │ VERIFY: even CPU across gRPC replicas            ║
╠════════════════════════════════════════════════════════════════╣
║  5-10min    │ Scale WebSocket servers + rate limit chat        ║
║             │ Sample analytics events at 10%                   ║
║             │ VERIFY: WS memory stable, Cassandra catching up  ║
╠════════════════════════════════════════════════════════════════╣
║  10-15min   │ Pre-warm entitlement cache from PostgreSQL       ║
║             │ VERIFY: Redis hit rate climbing toward 97%       ║
╠════════════════════════════════════════════════════════════════╣
║  15min+     │ Disable bypass, restore normal entitlement flow  ║
║             │ VERIFY: normal operation, no user impact         ║
╠════════════════════════════════════════════════════════════════╣
║  POST-      │ Rebalance Redis slots (when load is low)         ║
║  EVENT      │ Post-incident review                             ║
║             │ Reconcile: identify non-paying viewers           ║
║             │ Plan: L7 LB for gRPC, pre-event cache warming    ║
╚════════════════════════════════════════════════════════════════╝
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


# Week 3 Retention Test — Full Answers

---

# PART 1: RAPID-FIRE

---

## Q1: TIME_WAIT and EADDRNOTAVAIL

Each TCP connection is identified by a 4-tuple: `(src_ip, src_port, dst_ip, dst_port)`. A socket in TIME_WAIT still holds its 4-tuple for 2×MSL (60 seconds on Linux) to catch delayed packets from the old connection. With 28,000 connections in TIME_WAIT to the **same destination IP:port**, 28,000 source ports are locked. The Linux ephemeral port range defaults to `32768-60999` = **28,232 ports**. Nearly all ephemeral ports are consumed → `EADDRNOTAVAIL` (no available source port for the 4-tuple).

```
Parameter: net.ipv4.tcp_tw_reuse = 1

This allows the kernel to reuse TIME_WAIT sockets for 
NEW OUTGOING connections, provided TCP timestamps 
(net.ipv4.tcp_timestamps = 1) are enabled. Timestamps 
let the kernel distinguish old packets from new ones.

RISK: If the remote end doesn't support TCP timestamps 
(or timestamps are disabled), a late packet from the 
old connection could be misinterpreted as belonging to 
the new connection → data corruption on the socket.

NOTE: net.ipv4.tcp_fin_timeout controls FIN-WAIT-2 
duration, NOT TIME_WAIT. Common misconception. TIME_WAIT 
duration (2×MSL = 60s) is hardcoded in the kernel and 
cannot be changed without recompilation.
```

---

## Q2: HTTP/2 HOL Blocking

**All 6 streams are blocked.** HTTP/2 multiplexes all streams over a single TCP connection. TCP sees one contiguous byte stream — it has no concept of HTTP/2 streams. When the packet carrying stream 3 data is lost, TCP's in-order delivery guarantee halts the entire receive buffer until retransmission completes. Streams 1, 2, 4, 5, and 6 all have data waiting in the TCP receive buffer behind the gap, but TCP won't release any of it until the lost packet for stream 3 is retransmitted and fills the gap. This is **TCP-level head-of-line blocking**.

HTTP/3 solves this by running over **QUIC (UDP-based)**. QUIC implements per-stream flow control and ordering. Each stream has its own independent receive buffer. A lost packet on stream 3 blocks **only stream 3**. Streams 1, 2, 4, 5, 6 continue receiving and delivering data immediately. This is **per-stream loss isolation**.

---

## Q3: gRPC NLB Hot Replica

**Root cause:** The AWS NLB operates at L4 (TCP). gRPC uses HTTP/2 which creates **persistent, long-lived TCP connections**. The NLB balanced connections at creation time, but product-svc-7 has been running for 9 days. Early on, it accepted a connection from the NLB that became the long-lived channel carrying a disproportionate share of gRPC requests. The NLB distributes **connections**, not **requests** — once a connection is established, all multiplexed HTTP/2 streams on that connection go to the same backend. The other 7 replicas received connections later with less traffic pinned to them.

**Fix 1 — Client-side:** Enable **gRPC client-side load balancing**. Use the `round_robin` or `pick_first` LB policy with a name resolver (e.g., DNS or Kubernetes service discovery) that returns all 8 replica addresses. The gRPC client creates connections to **all** replicas and distributes requests across them at the application level.

```python
channel = grpc.insecure_channel(
    'dns:///product-service.prod.svc.cluster.local:50051',
    options=[
        ('grpc.lb_policy_name', 'round_robin'),
        ('grpc.service_config', '{"loadBalancingConfig": [{"round_robin":{}}]}')
    ]
)
```

**Fix 2 — Infrastructure-side:** Replace the NLB with an **L7 load balancer** that understands HTTP/2 framing (AWS ALB with gRPC support, or Envoy/Istio service mesh). An L7 balancer terminates the HTTP/2 connection and distributes individual **requests** across backends, regardless of which TCP connection they arrived on.

---

## Q4: WebSockets vs SSE

**SSE. Two reasons:**

1. **SSE is purpose-built for unidirectional server→client.** The requirement is server→client only — users don't send messages. WebSockets establish a full-duplex channel (bidirectional handshake, ping/pong frames, masking overhead). SSE uses plain HTTP with `text/event-stream` content type — lighter protocol, lower overhead per connection, and works through HTTP proxies and CDNs without special configuration (WebSockets require upgrade headers that some intermediaries strip).

2. **SSE has built-in automatic reconnection with resume.** If a user's connection drops, the browser automatically reconnects and sends a `Last-Event-ID` header. The server can resume from that point — the user doesn't miss score updates during the disconnection. WebSockets have no built-in reconnection — you must implement exponential backoff, jitter, state reconciliation, and missed-message replay manually.

---

## Q5: Kubernetes DNS ndots:5

`api.payment.prod.svc.cluster.local` has **4 dots**. With `ndots:5`, any name with fewer than 5 dots is treated as a relative name and search domains are tried first.

```
Default search domains:
  <namespace>.svc.cluster.local
  svc.cluster.local
  cluster.local

DNS queries issued (assuming pod is in "default" namespace):

1. api.payment.prod.svc.cluster.local.default.svc.cluster.local → NXDOMAIN
2. api.payment.prod.svc.cluster.local.svc.cluster.local → NXDOMAIN
3. api.payment.prod.svc.cluster.local.cluster.local → NXDOMAIN
4. api.payment.prod.svc.cluster.local. (absolute) → SUCCESS

4 DNS queries before getting an answer.
```

**Fix: Append a trailing dot.** `api.payment.prod.svc.cluster.local.` — the trailing dot marks it as a fully-qualified domain name (FQDN). The resolver skips all search domain expansion and issues **exactly 1 query** directly to the authoritative DNS.

---

## Q6: CDN Cache-Control Behavior at T=15

**T=15, origin is UP:**

Content is stale (past max-age=10). We're within the stale-while-revalidate window (T=10 to T=30). The CDN **immediately serves the stale cached response** to the client (zero latency penalty). Simultaneously, the CDN sends a **background revalidation request** to the origin. The origin responds with fresh content. The CDN updates its cache. The next request after revalidation completes gets fresh content.

**T=15, origin is DOWN:**

Content is stale (past max-age=10). The CDN attempts revalidation → origin is unreachable → error. The stale-if-error window applies (T=10 to T=310). The CDN **serves the stale cached response** to the client. No cache update occurs. The client gets stale-but-usable content instead of a 502/504 error. The CDN will retry revalidation on subsequent requests until the origin recovers.

---

## Q7: PostgreSQL READ COMMITTED — Phantom and Non-Repeatable Reads

**Phantom read: YES.** A transaction executing the same range query twice can see additional rows on the second execution if another transaction inserts and commits a matching row between the two queries — READ COMMITTED re-evaluates each statement against currently committed data.

**Non-repeatable read: YES.** A transaction reading the same row twice can see different values if another transaction updates and commits that row between the two reads — each statement in READ COMMITTED sees a fresh snapshot of committed data, not the snapshot from the transaction start.

---

## Q8: Composite Index Usage

Index: `(customer_id, status, created_at)` — B-tree, leftmost prefix rule applies.

**(a) FULLY.** All three columns used in order: equality on customer_id, equality on status, range on created_at. The index traverses the full tree: customer_id=5 → status='shipped' → range scan on created_at.

**(b) NOT AT ALL.** Missing the leftmost column (customer_id). A B-tree composite index cannot skip the first column — it's like looking up a last name in a phone book sorted by (first_name, last_name). Full table scan (or uses a different index if available).

**(c) PARTIALLY.** Uses customer_id (first column) to narrow results. Skips status (second column), so created_at (third column) cannot be used for range scanning. The index narrows to all rows where customer_id=5, then PostgreSQL must scan those rows and filter on created_at.

**(d) FULLY.** The query optimizer reorders WHERE clause conditions to match the index's column order. The SQL text ordering is irrelevant — the optimizer sees customer_id=5, status='shipped', created_at range and uses the index identically to (a).

**(e) PARTIALLY.** Uses customer_id (first column). The index narrows to customer_id=5 entries and counts them. This can be an **index-only scan** (covering) since no table columns beyond the index are needed — the count can be derived purely from the index structure.

---

## Q9: Cassandra Stale Reads at CL=ONE

**Yes, this can produce a stale read.** W=1, R=1, N=3. R+W = 2, which is NOT > N (3). There is no guaranteed overlap between the replica that received the write and the replica that serves the read. You could read from one of the 2 replicas that did NOT receive the write.

**Minimum read CL: ALL (R=3).** With W=1, we need R+W > N for guaranteed overlap: R + 1 > 3, so R > 2, meaning R = 3 (ALL). Only by reading from ALL replicas do we guarantee that at least one of them is the node that acknowledged the write. Cassandra's read path returns the value with the highest timestamp across all contacted replicas, so contacting all 3 ensures the latest write is included.

QUORUM (R=2) is NOT sufficient: R+W = 2+1 = 3 = N, not > N. There's a possibility (1/3 chance) that neither of the 2 contacted replicas is the one that received the write.

---

## Q10: Cassandra Write Path on Replica Node

```
Mutation arrives at replica from coordinator:

1. APPEND TO COMMIT LOG (sequential disk write)
   → Durability guarantee — survives node crash
   → This is a sequential append, very fast

2. WRITE TO MEMTABLE (in-memory sorted structure)
   → Current memtable for this column family
   → Sorted by partition key + clustering columns
   → This is a memory write, sub-millisecond

3. SEND ACK TO COORDINATOR ← ACK happens HERE
   → Replica has the data durable (commit log) 
     and queryable (memtable)
   → Coordinator tallies ACKs toward CL requirement

4. (LATER — asynchronous, not part of the write path)
   → Memtable reaches threshold → FLUSH to SSTable on disk
   → SSTables accumulate → COMPACTION merges them
   → Neither flush nor compaction blocks the write path
   → The ACK was already sent at step 3
```

The critical point: the ACK is sent **after** commit log append and memtable write, but **before** any SSTable flush. This makes writes fast (only one sequential I/O + one memory write before acknowledging) while maintaining durability (commit log survives crashes).

---

## Q11: Cache-Aside Staleness

**T=55 read: Returns V1 (stale).** The cache entry was set at T=0 with TTL=60s, so it expires at T=60. At T=55, the entry is still valid (5 seconds remaining). Cache-aside returns the cached value V1. The database update to V2 at T=30 did not invalidate the cache. The cache has no knowledge of the database change.

**T=61 read: Returns V2 (current).** The cache entry expired at T=60. At T=61, the cache lookup is a MISS. Cache-aside falls through to the database, reads V2 (the current value), populates the cache with V2 and a new 60-second TTL, then returns V2.

---

## Q12: Probabilistic Early Expiry

```
Each request INDEPENDENTLY computes whether to 
proactively refresh the key BEFORE it actually expires.

FORMULA:
  expiry_time - (delta × beta × ln(random())) 

  delta = estimated time to recompute the value
  beta = tuning parameter (typically 1.0)
  random() = uniform random in (0, 1)
  ln(random()) = always negative (range: -∞ to 0)

So: -ln(random()) is always positive, with an 
exponential distribution. Sometimes small (key 
refreshed very close to expiry), sometimes large 
(key refreshed well before expiry).

HOW IT WORKS:
  current_time ≥ expiry_time - (delta × beta × ln(random()))

  As current_time approaches expiry_time, the LEFT 
  side grows. The probability of the inequality being 
  true INCREASES. But because random() is different 
  for each request, they trigger at DIFFERENT times.

EFFECT:
  10,000 concurrent requests, key expiring at T=60:
  → At T=55: maybe 1 request triggers early refresh
  → That 1 request hits the DB, fetches new value, 
    updates cache with new TTL
  → At T=60: the other 9,999 requests find the cache 
    ALREADY REFRESHED
  → Thundering herd avoided: 1 DB query instead of 10,000

WHY IT SPREADS LOAD:
  The randomness ensures requests independently select 
  different early-refresh times. The first one to 
  trigger does the refresh. All subsequent requests 
  find a fresh cache entry. The exponential distribution 
  means most requests trigger close to expiry (not 
  wastefully early), but some trigger early enough to 
  guarantee at least one refresh before TTL.
```

---

## Q13: DynamoDB PACELC Classification

**DynamoDB with eventually consistent reads: PA/EL**
- During partition: Available — serves responses from any reachable replica, even if stale. Reads don't fail due to partition.
- Normal operation: Low latency — reads served from the nearest replica without leader coordination. May return stale data. Costs 1× read capacity unit.

**DynamoDB with strongly consistent reads: PC/EC**
- During partition: Consistent — reads are served from the **leader** only. If the leader is in the partitioned segment and unreachable, the read **fails** rather than returning stale data.
- Normal operation: Consistent — always reads from the leader, which has the latest committed write. Higher latency (leader may not be the closest replica). Costs 2× read capacity units.

---

## Q14: etcd as Session Store

**This proposal trades latency and throughput for a consistency guarantee that sessions don't need.**

etcd provides **linearizable reads** via Raft consensus — every read goes through the leader or uses ReadIndex protocol. In PACELC terms, etcd is **PC/EC**: it always prioritizes consistency, even at the cost of latency and availability.

User sessions need **EL (low latency)**, not EC. A session read that returns slightly stale data (user's theme preference is 2 seconds behind) is completely harmless. A session read that takes 50ms because it must go through Raft consensus — or fails entirely because the Raft leader is unreachable — actively harms user experience.

Beyond PACELC:
- etcd is designed for **small metadata** (leader election, config, service discovery) — default storage limit is 8GB
- 12M DAU × 4KB session = ~48GB of session data — **6x etcd's capacity**
- etcd doesn't scale horizontally for reads (all reads go through leader)
- Thousands of session reads/sec would saturate the Raft leader
- The correct choice: Redis or Memcached (PA/EL) — optimized for high-throughput, low-latency key-value access with eventual consistency that sessions can tolerate

---

## Q15: Consistency Model Violations (TRAP QUESTION)

**Only ONE violation: Read-Your-Writes.**

The user wrote name="Alice" and it was acknowledged. The immediately following read returned "Bob" (an older value). The user could not see their own write. This is a textbook read-your-writes violation.

**Monotonic reads is NOT violated.** Monotonic reads requires that once a process sees value V, subsequent reads never return a value older than V. The sequence was:

```
Read 1: "Bob" (older value)
Read 2: "Alice" (newer value — the user's write)

"Bob" → "Alice" is FORWARD in time. The values never 
went backward. Monotonic reads would only be violated 
if the user saw "Alice" FIRST and then "Bob" on a 
subsequent read. That's the reverse of what happened.
```

---

## Q16: Consistent Prefix Reads Violation

**Consistent prefix reads is violated.** User C sees an effect ("I am!" — a reply) without its cause ("Who's coming to dinner?" — the original question). The reply is causally dependent on the original message — it only exists because User B read the question. A consistent prefix requires that observers see a **prefix** of the causal history: either nothing, or the question alone, or the question followed by the reply. Seeing the reply without the question is seeing a non-contiguous slice of the causal chain.

**(Also a causal consistency violation: seeing an effect before its cause.)**

**Simplest fix:** Partition by **conversation_id** (or channel_id) instead of by user_id. Both the question and the reply belong to the same conversation. If both messages are on the same shard, any reader querying that shard sees them in order — the shard's internal ordering preserves the causal chain. Cross-shard ordering issues disappear because causally related messages are co-located.

---



## Q17: Consistent Hashing — Key Remapping

**Consistent hashing (adding 5 nodes to 50):**

```
Each of the 5 new nodes takes responsibility for a 
portion of the ring. With 150 vnodes per node, each 
new node's vnodes are placed around the ring and 
absorb keys from their clockwise neighbors.

Keys remapped ≈ 5/55 ≈ 9.1% of total keys.

Only keys that land in the arc between a new vnode 
and the next existing vnode are remapped. The other 
~91% of keys stay on their current nodes untouched.
```

**Hash-mod-N (going from 50 to 55):**

```
key_assignment = hash(key) % N

When N changes from 50 to 55, almost EVERY key's 
assignment changes. hash(key) % 50 ≠ hash(key) % 55 
for the vast majority of keys.

Keys remapped ≈ 50/55 ≈ 90.9% of total keys.

Only keys where hash(key) % 50 == hash(key) % 55 
survive (those whose hash value is divisible by both 
50 and 55 — i.e., divisible by LCM(50,55) = 550).
Approximately 1/11 ≈ 9.1% survive unremapped.

~91% of keys remapped — near-total cache invalidation.
```

**Summary: 9% remapped (consistent hashing) vs 91% remapped (mod-N). This is WHY consistent hashing exists — adding nodes causes minimal disruption.**

---

## Q18: Redis Cluster Reshard for Hot Key

**No. Adding a 7th master and resharding does NOT fix this.**

`leaderboard:global` is a **single key**. It hashes to exactly ONE slot: `CRC16("leaderboard:global") % 16384 = slot X`. That slot lives on one master. Resharding redistributes **slots** across masters — it does NOT split traffic for a single key within a single slot.

If you move slot X to master-7, you move the 50,000 reads/sec to master-7. Master-7 becomes the hot node. You've relocated the problem, not resolved it.

**This is the hot key problem, identical to Q1 of the session store scenario.** Consistent hashing (whether ring-based or slot-based) distributes keys, not traffic within a key. The fix must happen at the **application or data model layer**:
- Read replicas for that specific key (Redis `READONLY` on replicas of the hot master — spreads reads across master + replica)
- Application-level local caching (cache the leaderboard in each app server's memory for 500ms)
- Key sharding (`leaderboard:global:shard:{0-15}`, reads scatter across masters)

---

## Q19: Two Consistency Violations in PostgreSQL Round-Robin

**Violation 1: Read-Your-Writes**

The user updates their email (write goes to primary). The next read is routed by the load balancer to a **replica** that hasn't received the write yet via async replication. The user sees the OLD email — they can't see their own write.

**Cause: Load balancer.** The load balancer routes the post-write read to a replica instead of the primary. The database itself is functioning correctly — the primary has the new email, and the replica will eventually get it. The LB made no distinction between "this user just wrote" and any other read.

**Violation 2: Monotonic Reads**

The sequence: OLD email → NEW email (second refresh) → OLD email (third refresh). The user saw the new value, then on the next read **went backward** to the old value. Values must only go forward — once you've seen the new email, you should never see the old one again.

**Cause: Load balancer.** Round-robin without session stickiness sends successive reads to different replicas at different replication lag positions. Refresh 2 hit a caught-up replica (new email), refresh 3 hit a lagging replica (old email). The database replicas are individually consistent — each one's state only moves forward. The LB's rotation across replicas with different lag is what creates the apparent backward movement.

---

## Q20: Flash Sale Inventory Decrement

**Minimum consistency model: Linearizability.**

The stock decrement is a read-modify-write on a shared counter where overselling has direct financial and operational consequences (shipping items you don't have, cancelling orders, refunding angry customers). Every decrement must see the **true current stock** at the moment of execution. Stale reads → overselling. Concurrent decrements that don't see each other → stock goes negative.

**PACELC: PC/EC.**

During partition: prefer consistency — reject purchases rather than risk overselling. A user getting "temporarily unavailable, try again" is vastly better than selling 517 units of 500-unit inventory. During normal operation: prefer consistency — every read and write goes through a single authoritative source with serializable guarantees.

**Technology choice: PostgreSQL with `SELECT ... FOR UPDATE` (row-level locking).**

```sql
BEGIN;
SELECT stock FROM inventory 
  WHERE product_id = 'SKU-8812' FOR UPDATE;
-- Row is locked. No other transaction can read 
-- or modify this row until we commit.
-- If stock > 0: proceed. If stock = 0: rollback.
UPDATE inventory SET stock = stock - 1 
  WHERE product_id = 'SKU-8812';
COMMIT;
```

Single PostgreSQL primary provides linearizability trivially (one copy of data, serializable access via row lock). The `FOR UPDATE` lock prevents concurrent decrements from interleaving. Only one transaction can hold the lock at a time — serialized access to the stock counter.

---

# PART 2: COMPOUND SCENARIO

---

## Q1: Every Distinct Problem

### Problem 1: Inventory Cache Stampede

```
ROOT CAUSE: 2,000 flash sale products added at 05:59 
had no cache entries. At 06:00, 180K req/s arrived — 
69% cache miss rate → 124K misses/s all fall through 
to PostgreSQL replicas simultaneously.

COMPONENTS: Redis inventory cache, PostgreSQL replicas
CLASSIFICATION: TRIGGERED by flash sale (products weren't 
pre-warmed in cache before the sale started)
ROLE: INDEPENDENT origin point → AMPLIFIER of all 
downstream problems

This is the FIRST DOMINO. Every problem below either 
originates from or is amplified by this cache stampede.
```

### Problem 2: PostgreSQL Connection Pool Exhaustion

```
ROOT CAUSE: 124K cache misses/s overwhelm the PostgreSQL 
connection pools (200 max per region). Inventory reads 
(cache miss fallthrough) consume ALL available connections, 
starving the Order Service of connections for writes.

COMPONENTS: PostgreSQL connection pools, Inventory Service, 
Order Service
CLASSIFICATION: CASCADE from Problem 1 (cache stampede 
floods DB with reads)
ROLE: AMPLIFIER — turns a cache problem into an ORDER 
FAILURE problem. 23% checkout failure rate.

CRITICAL DETAIL: Reads and writes share the SAME connection 
pool. Inventory reads (non-critical, stale-tolerant) are 
blocking order writes (critical, revenue-generating).
```

### Problem 3: gRPC Load Balancing (Product Service)

```
ROOT CAUSE: NLB operates at L4. gRPC uses persistent 
HTTP/2 connections. product-svc-7 has been running 9 
days, accumulated a disproportionate share of persistent 
connections → receives 40% of traffic on 1/12 of capacity.

COMPONENTS: NLB, Product Service, gRPC/HTTP/2
CLASSIFICATION: PRE-EXISTING. This problem existed 
before the flash sale. The 2x→12x traffic spike 
made it visible (product-svc-7 at 94% CPU), but 
the uneven distribution existed for 9 days.
ROLE: INDEPENDENT — not caused by the cache stampede. 
Contributes independently to degraded product page 
load times (p99 = 4.2s).
```

### Problem 4: Stale Inventory Display (EU/APAC)

```
ROOT CAUSE: EU and APAC read inventory from local 
async PostgreSQL replicas. Under heavy replication load, 
lag grew from 40ms/120ms to 3.8s/8.2s. Users see 
inflated stock counts → click Buy → get rejected 
at the US primary → terrible UX.

COMPONENTS: PostgreSQL async replication, EU/APAC replicas
CLASSIFICATION: TRIGGERED by flash sale (heavy write 
load on primary → increased replication lag)
ROLE: VICTIM of the write load on primary. 
AMPLIFIER of user frustration and support tickets.
Does NOT cause overselling (the primary correctly 
rejects purchases at stock=0).
```

### Problem 5: Overselling (SKU-8812)

```
ROOT CAUSE: Race condition between the cache-based 
inventory check (step 2) and the PostgreSQL UPDATE 
(step 3). The cache check passes (stock=23 from a 
4.8-second-old cache entry) but by the time the UPDATE 
executes, actual stock has changed. The SQL itself 
has a concurrency bug allowing stock to go negative 
(detailed in Q2).

COMPONENTS: Redis cache, PostgreSQL, Inventory Service 
application logic
CLASSIFICATION: TRIGGERED by flash sale (high concurrency 
on limited-stock items exposes the race window)
ROLE: INDEPENDENT root cause (the concurrency bug 
exists regardless of the stampede, but high concurrency 
triggers it). Most financially and legally consequential 
problem.
```

### Problem 6: WebSocket Broadcast Lag

```
ROOT CAUSE: inventory_updated Kafka events arrive 
faster than WebSocket servers can broadcast to 340K 
connections. Consumer lag grows → users see stock 
counts 8-15 seconds behind reality.

COMPONENTS: Kafka consumer, WebSocket servers, 
Notification Service
CLASSIFICATION: TRIGGERED by flash sale (event volume 
exceeds broadcast capacity)
ROLE: AMPLIFIER of stale inventory display. Users 
already see stale data from CDN → WebSocket is supposed 
to correct it → but WebSocket is also behind → 
staleness compounds.
```

### Problem 7: CDN Template Caching

```
ROOT CAUSE: Product page HTML templates cached at 
CloudFront with max-age=30. Templates include a 
"data-initial-stock" attribute stamped at render time. 
Users loading pages get stock counts from up to 30 
seconds ago baked into the HTML. The WebSocket is 
supposed to override with real-time data, but is 
8-15s behind itself.

COMPONENTS: CloudFront CDN, Product page rendering
CLASSIFICATION: PRE-EXISTING. Caching HTML with stock 
counts embedded was always wrong for rapidly-changing 
inventory data. The flash sale exposed it.
ROLE: AMPLIFIER. Adds 30 seconds of staleness on top 
of the 8-15s WebSocket lag → total 38-45 seconds stale.
```

### Problem 8: DNS TTL (Flash Sale Microsite)

```
ROOT CAUSE: DNS record for flash.shop.example.com had 
TTL=3600s (1 hour). DNS was changed at 06:00 to point 
to the new larger cluster. Clients cached the old record 
→ 30% of traffic hits the old (smaller) cluster → 
overwhelmed. New cluster at 20% capacity (underutilized).

COMPONENTS: Route 53, DNS caching, flash sale infrastructure
CLASSIFICATION: PRE-EXISTING (should have been mitigated 
days before by lowering TTL) TRIGGERED at 06:00 by 
the DNS change.
ROLE: INDEPENDENT. Unrelated to the cache stampede or 
database issues. Directly causes overload on the old 
cluster and underutilization of the new one.
```

### Problem 9: Session/Inventory Cache Contention (Redis)

```
ROOT CAUSE: User sessions and inventory cache share 
the SAME Redis cluster. The inventory cache stampede 
(124K misses/s → high write rate repopulating cache 
+ high read rate) consumes Redis CPU. Session reads 
start timing out → users logged out mid-checkout.

COMPONENTS: Redis Cluster (shared), Session Service, 
Inventory Service
CLASSIFICATION: CASCADE from Problem 1 (cache stampede 
consumes shared Redis resources, starving sessions)
ROLE: VICTIM of the cache stampede. AMPLIFIER of user 
impact — users not only can't check out (pool exhaustion), 
they're actively logged out and must re-authenticate, 
creating a retry storm that further loads the auth system.
```

### Failure Chain Diagram

```
PRE-EXISTING (dormant):

                    ╔══════════════════════════════════════════════════════════════╗
                    ║  gRPC L4 LB     │  │ CDN template   │  │ DNS TTL=3600        ║
                    ║  imbalance      │  │ stock embed    │  │ not lowered         ║
                    ║  (9 days)       │  │                │  │                     ║
                    ╚══════════════════════════════════════════════════════════════╝
                            │                   │                   │
FLASH SALE 06:00 ═══════════╪═══════════════════╪═══════════════════╪══════════
                            │                   │                   │
                            ▼                   ▼                   ▼
                       Product svc       Stale HTML stock    30% traffic to
                       p99: 4.2s         (+30s staleness)    old cluster
                       (independent)     (amplifier)         (independent)
                                                │
                  ╔══════════════════════════════════════════════════════════════╗
                  ║  CACHE STAMPEDE              ▼                               ║
                  ║  (124K misses/s)                                             ║
                  ║     │                                                        ║
                  ║     ├──► PG Pool Exhaustion ────────► Order Write Failures   ║
                  ║     │    (cascade)                    (23% checkout fail)    ║
                  ║     │                                                        ║
                  ║     ├──► Redis CPU Saturation ──────► Session Timeouts       ║
                  ║     │    (cascade)                    (users logged out)     ║
                  ║     │                                         │              ║
                  ║     │                                         ▼              ║
                  ║     │                                 Auth Retry Storm       ║
                  ║     │                                 (amplifier)            ║
                  ║     │                                                        ║
                  ║     ├──► Heavy PG Replication Load ─► EU/APAC Stale          ║
                  ║     │    (cascade)                    Inventory              ║
                  ║     │                                 (+3.8-8.2s lag)        ║
                  ║     │                                         │              ║
                  ║     │                   WebSocket Lag ◄───────╯              ║
                  ║     │                   (+8-15s delay, cascade)              ║
                  ║     │                                                        ║
                  ║     ╰──► Overselling (SKU-8812)                              ║
                  ║          (triggered — concurrency bug exposed)               ║
                  ╚══════════════════════════════════════════════════════════════╝
```

---

## Q2: The Overselling Bug

### a) Exact Concurrency Mechanism

```
PostgreSQL default isolation: READ COMMITTED.

The inventory flow:
  Step 2: Read stock from Redis cache → stock=23 (stale)
  Step 3: UPDATE inventory SET stock = stock - 1 
          WHERE product_id = 'SKU-8812' AND stock > 0

These are TWO SEPARATE OPERATIONS — not in the same 
transaction. Even if they were, READ COMMITTED provides 
NO protection against the race.

HERE'S THE EXACT MECHANISM:

Under READ COMMITTED, the UPDATE statement evaluates 
the WHERE clause against the CURRENTLY COMMITTED state 
at the moment it acquires the row lock.

  Timeline with 20 concurrent transactions:

  T1: BEGIN; UPDATE ... WHERE stock > 0; 
      → Acquires row lock. Reads stock=5. 
      → stock > 0 is TRUE. 
      → Sets stock = 4. COMMIT. Lock released.

  T2-T20: All 19 transactions are BLOCKED waiting 
          for the row lock held by T1.

  T2: Acquires lock. Re-reads committed stock = 4.
      → stock > 0 is TRUE. Sets stock = 3. COMMIT.

  T3: Acquires lock. Re-reads committed stock = 3.
      → stock > 0 is TRUE. Sets stock = 2. COMMIT.

  ...continuing...

  T5: Acquires lock. Re-reads stock = 0.
      → stock > 0 is FALSE. UPDATE returns 0 rows.
      → No change. COMMIT.

  So with serialized row-level locking, stock CANNOT 
  go below 0 with this SQL. The WHERE stock > 0 check 
  IS re-evaluated after acquiring the lock under READ 
  COMMITTED.

  THEN HOW DID STOCK REACH -17?

  The answer: the application does NOT use a single 
  UPDATE statement. It reads from CACHE, then UPDATEs:

  Application code (simplified):
    cached_stock = redis.get(f"inventory:{product_id}")
    if cached_stock > 0:  # ← CHECKED AGAINST STALE CACHE
        result = db.execute(
            "UPDATE inventory SET stock = stock - 1 "
            "WHERE product_id = $1 AND stock > 0 "
            "RETURNING stock", product_id
        )

  Wait — even with the cache check, the SQL still has 
  "AND stock > 0". So the UPDATE should still prevent 
  going negative...

  UNLESS: the application ignores the RETURNING result 
  and considers any non-exception response as success.
  
  OR, more likely:

  The actual SQL is NOT "stock = stock - 1 WHERE stock > 0."
  The actual SQL uses the CACHED stock value:

    cached_stock = redis.get(f"inventory:{product_id}")  
    # cached_stock = 23 (stale, 4.8 seconds old)
    
    if cached_stock > 0:
        result = db.execute(
            "UPDATE inventory SET stock = $1 "
            "WHERE product_id = $2",
            cached_stock - 1,  # ← SETS stock = 22
            product_id
        )

  This is a BLIND WRITE using a stale cached value.
  No WHERE stock > 0 check in the actual SQL.
  No row-level locking coordination.
  
  18 concurrent transactions all read cached_stock=23,
  all execute UPDATE SET stock = 22. Last one wins.
  Then stock=22, but 18 orders were placed.
  Next batch reads cache again... eventually stock 
  goes to -17.

  THE ANOMALY: This is a LOST UPDATE under READ COMMITTED.
  Multiple transactions read the same stale value, 
  compute a new value independently, and write it.
  Each write overwrites the previous one. The 
  decrements are LOST.

  READ COMMITTED allows lost updates because each 
  transaction sees only the committed state at the 
  moment of its read — not the in-progress writes 
  of concurrent transactions.
```

### b) Two Fixes

**Fix 1: Atomic Conditional UPDATE (no cache in the write path)**

```sql
-- Remove the cache read from the purchase decision.
-- Use a SINGLE atomic SQL statement:

UPDATE inventory 
SET stock = stock - 1 
WHERE product_id = 'SKU-8812' AND stock > 0 
RETURNING stock;

-- If RETURNING returns 0 rows: out of stock. 
-- Reject the purchase.
-- If RETURNING returns 1 row: success. 
-- The returned stock value is the new count.
```

```
CONSISTENCY MODEL: Linearizable (for this specific 
operation). The UPDATE acquires a row-level lock, 
re-evaluates stock > 0 against the committed state 
after acquiring the lock, and atomically decrements. 
Concurrent transactions serialize on the row lock.
Stock CANNOT go below 0.

PERFORMANCE TRADEOFF: All concurrent purchases of the 
same product SERIALIZE on the row lock. Under 1000 
concurrent buyers for the same SKU, each waits for 
the previous transaction to commit before acquiring 
the lock. Throughput is bounded by single-row lock 
contention — roughly 5,000-10,000 transactions/sec 
on a single PostgreSQL row.

For 500 items with thousands of concurrent buyers: 
easily sufficient. The serialization takes ~0.1ms per 
transaction (in-memory row update), so 500 purchases 
complete in ~50ms total.

PACELC: PC/EC. Sacrifices concurrent throughput 
(serialized writes) for correctness (no overselling).
```

**Fix 2: SELECT FOR UPDATE with explicit transaction**

```sql
BEGIN;
SELECT stock FROM inventory 
WHERE product_id = 'SKU-8812' FOR UPDATE;
-- Row is LOCKED. No other transaction can read or 
-- modify until we commit.
-- Application checks: if stock <= 0, ROLLBACK.
-- Otherwise:
UPDATE inventory SET stock = stock - 1 
WHERE product_id = 'SKU-8812';
COMMIT;
```

```
CONSISTENCY MODEL: Linearizable (serializable access 
to the row). FOR UPDATE acquires an exclusive row lock 
at SELECT time. The read AND write are within the same 
transaction. No other transaction can interleave.

PERFORMANCE TRADEOFF: Same serialization as Fix 1 — 
concurrent transactions queue on the row lock. Slightly 
higher overhead than Fix 1: two round-trips to the 
database (SELECT + UPDATE) instead of one (atomic UPDATE).
But provides the application a chance to make decisions 
between the read and write (e.g., check additional 
business logic, per-customer purchase limits).

PACELC: PC/EC. Same as Fix 1.

Fix 1 is PREFERRED for simple "decrement if > 0" 
because it's a single statement — less code, fewer 
round-trips, same correctness guarantee.

Fix 2 is PREFERRED when the application needs to read 
the current stock, perform business logic (e.g., "max 
2 per customer"), then conditionally update.
```

---

## Q3: Consistency Analysis — Current vs Should

### Inventory Count (for display to user)

```
CURRENTLY PROVIDES: Eventual consistency.
  Read path: Redis cache (5s TTL) → PostgreSQL async 
  replica (40ms-8.2s lag). Multiple staleness layers.
  No monotonic reads (round-robin LB across replicas).
  No read-your-writes (cache not invalidated on purchase).

SHOULD PROVIDE: Monotonic reads + bounded staleness.
  Users should never see stock go BACKWARD (47 → 12 → 
  47 → 3 is confusing). Monotonic reads via sticky 
  sessions to a consistent cache/replica.
  
  Bounded staleness (≤5 seconds) is acceptable for 
  display. Showing "5 left" when reality is "3 left" 
  is tolerable. Showing "47 left" when reality is "0" 
  is not — but that's a staleness bound problem, not 
  a consistency model problem.

PACELC: PA/EL. Display availability and latency are 
more important than perfect accuracy. A stale count 
is better than a loading spinner. But bound the 
staleness — 5s cache TTL is reasonable, 38-45 seconds 
(current compound staleness) is not.
```

### Inventory Count (for purchase decision / stock decrement)

```
CURRENTLY PROVIDES: Eventual consistency (reads from 
stale Redis cache) followed by an UPDATE that may or 
may not enforce the constraint, depending on actual SQL.

SHOULD PROVIDE: Linearizability.
  The stock decrement MUST see the true current count. 
  Read from PostgreSQL PRIMARY only. No cache in the 
  purchase decision path. Use atomic conditional UPDATE 
  or SELECT FOR UPDATE.

PACELC: PC/EC. Consistency is non-negotiable. Overselling 
has direct financial cost (refunds, reputation, potential 
legal) that far exceeds the latency cost of reading 
from the primary.
```

### Product Catalog (descriptions, prices)

```
CURRENTLY PROVIDES: Strong consistency within each region.
  Cassandra at LOCAL_QUORUM for both reads and writes.
  RF=3 per region. R=2, W=2, R+W=4 > N=3.
  Within a single region: linearizable per-key.
  Across regions: eventually consistent (LOCAL means 
  no cross-region coordination).

SHOULD PROVIDE: This is CORRECT as-is.
  Product descriptions and prices change infrequently.
  LOCAL_QUORUM gives strong consistency within each 
  region for writes and reads. Cross-region eventual 
  consistency is fine — a price showing as $49.99 in 
  EU while US just updated to $39.99 is acceptable 
  for the seconds until async replication catches up.

PACELC: PA/EL per region (LOCAL_QUORUM doesn't block 
on cross-region replicas). PC/EC within region (quorum 
ensures consistency locally).
```

### Shopping Cart

```
CURRENTLY PROVIDES: Read-your-writes (probabilistic).
  Stored in Redis (per-region, keyed by user_id).
  Redis is single-master per slot — writes and reads 
  to the same master provide read-your-writes trivially.
  BUT: if Redis master fails over to replica, async 
  replication may lose recent cart writes.

SHOULD PROVIDE: Read-your-writes + monotonic reads.
  A user adds item to cart → must see it on next page 
  load (read-your-writes). Items must never appear, 
  disappear, reappear (monotonic reads). Durability 
  is important but not critical — a lost cart item 
  during failover is annoying but recoverable.

PACELC: PA/EL. Cart availability matters more than 
perfect durability. A user can re-add a lost item. 
A cart that's unavailable during checkout = lost sale.
```

### Order Record

```
CURRENTLY PROVIDES: Linearizable (on the US primary).
  Writes go to PostgreSQL primary. The primary provides 
  single-copy linearizability. But reads from EU/APAC 
  replicas are eventually consistent.

SHOULD PROVIDE: Linearizable for writes + 
read-your-writes for the purchasing user.
  The order write MUST NOT be lost (financial record).
  The user who placed the order must immediately see 
  their order confirmation. Other users never read 
  someone else's order, so cross-user consistency is 
  irrelevant.

PACELC: PC/EC for writes (order must be durably 
committed — consider synchronous replication to at 
least one local replica). PA/EL for order history 
reads (slightly stale order history page is fine for 
non-purchasing users or admin dashboards).
```

### Session

```
CURRENTLY PROVIDES: Eventual consistency (on the same 
Redis cluster as inventory cache, currently being 
starved of resources).

SHOULD PROVIDE: Read-your-writes + monotonic reads.
  User logs in → session created → next request must 
  see the session (read-your-writes). Session must not 
  appear/disappear/reappear (monotonic reads).

PACELC: PA/EL. Session availability is critical — 
a stale session preference (wrong theme for 2 seconds) 
is harmless. An unavailable session (user logged out 
mid-checkout) is catastrophic for revenue.

CRITICAL FIX: Sessions must be on a SEPARATE Redis 
cluster from inventory cache. Shared infrastructure 
means inventory load affects session availability — 
unacceptable blast radius.
```

---

## Q4: Three Layers of Staleness for EU Users

```
LAYER 1: REDIS INVENTORY CACHE (up to 5 seconds)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  EU Inventory Service reads inventory:{product_id} 
  from the EU-region Redis cache.
  
  This cache was populated from a read to the EU 
  PostgreSQL replica. TTL = 5 seconds.
  
  At time of read: cache entry could be up to 5 
  seconds old (populated from replica at some point 
  in the last 5 seconds).
  
  STALENESS CONTRIBUTION: 0 to 5 seconds.


LAYER 2: POSTGRESQL ASYNC REPLICATION LAG (up to 8.2 seconds)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  When the Redis cache was populated (on cache miss), 
  the read went to the EU PostgreSQL replica.
  
  The EU replica has async replication lag from the 
  US primary. Under heavy flash sale write load, this 
  lag grew from 40ms to 3.8 seconds (EU) / 8.2 
  seconds (APAC).
  
  So the cache was populated with data that was already 
  3.8 seconds stale at the time of the read.
  
  STALENESS CONTRIBUTION: 3.8 seconds (EU), 8.2 seconds (APAC).


  LAYER 1 + LAYER 2 COMBINED (display read path):
  5s (max cache age) + 3.8s (replica lag) = 8.8 seconds 
  stale for the inventory count shown via API read.


LAYER 3: CDN-CACHED HTML TEMPLATE (up to 30 seconds)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  But the user isn't making an API call for the initial 
  stock count. They're loading a PRODUCT PAGE.
  
  The product page HTML template is cached at CloudFront 
  with max-age=30. The template was rendered by the 
  origin server, which embedded "data-initial-stock=47" 
  at render time.
  
  When was that template rendered? Up to 30 seconds ago.
  At render time, the origin read the stock count — 
  which itself was stale by up to 8.8 seconds 
  (Layer 1 + Layer 2).
  
  So the stock count in the cached HTML is:
  30s (CDN cache age) + 5s (Redis cache at render time) 
  + 3.8s (replica lag at render time) = 38.8 seconds stale.
  
  STALENESS CONTRIBUTION: up to 30 seconds additional.


THE WEBSOCKET WAS SUPPOSED TO FIX THIS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  The HTML loads with stale stock (38.8 seconds old).
  The WebSocket connection is supposed to push real-time 
  updates that override the stale HTML value.
  
  But the WebSocket broadcast pipeline is backed up:
  → Kafka consumer lag: 12,000 messages
  → Broadcast delay: 8-15 seconds behind real-time
  
  So the WebSocket update that arrives is ALSO stale:
  8-15 seconds behind reality.
  
  The user's experience:
  
  T=0:   Page loads. HTML says "47 left" (38.8s stale)
  T=12:  WebSocket update arrives: "23 left" (12s stale)
         Better, but still wrong.
  T=24:  Next WebSocket update: "8 left" (catching up)
  T=30:  Hard refresh → new CDN page → still stale


FULL DATA PATH FOR EU USER AT 06:03:

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   REALITY: stock = 12 (on US primary)                        ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Layer 3: CDN served page rendered at 05:59:33              ║
  ║     → At render time, origin read from API                   ║
  ║     │                                                        ║
  ║     ╰─ Layer 1: Redis cache, populated at 05:59:30           ║
  ║         → On cache miss, read from replica                   ║
  ║         │                                                    ║
  ║         ╰─ Layer 2: EU replica, 3.8s behind primary          ║
  ║             → Replica had stock = 47 at that moment          ║
  ║             → Primary had stock = 44 at that moment          ║
  ║                                                              ║
  ║   User at 06:03:00 sees "47 left"                            ║
  ║   Reality: stock = 12                                        ║
  ║   Total staleness: ~38-45 seconds depending on               ║
  ║   exact cache/replica timing                                 ║
  ║                                                              ║
  ║   LAYER CONTRIBUTIONS:                                       ║
  ║   ╭──────────────────┬──────────┬──────────────────╮         ║
  ║   │ Layer            │ Max Stale│ Type             │         ║
  ║   ├──────────────────┼──────────┼──────────────────┤         ║
  ║   │ CDN HTML cache   │ 30s      │ HTTP cache       │         ║
  ║   │ Redis inv cache  │ 5s       │ App cache        │         ║
  ║   │ PG async replica │ 3.8s     │ Replication lag  │         ║
  ║   │ WebSocket lag    │ 8-15s    │ Consumer lag     │         ║
  ║   ├──────────────────┼──────────┼──────────────────┤         ║
  ║   │ TOTAL WORST CASE │ ~45s     │ Compounded       │         ║
  ╚══════════════════════════════════════════════════════════════╝
  │                                                     │
  │  Note: WebSocket lag doesn't ADD to CDN staleness   │
  │  — it FAILS TO CORRECT it. The page starts 38.8s    │
  │  stale, and the WebSocket correction arrives 8-15s  │
  │  late, so the correction itself is stale.           │
  │  Effective staleness experienced by the user is     │
  │  max(CDN_staleness, WebSocket_lag + its own         │
  │  staleness) ≈ 38-45 seconds at worst.               │
  ╰─────────────────────────────────────────────────────╯
```

---

## Q5: Mitigation Plan

### Priority Assessment

```
PRIORITY HIERARCHY:
  1. FINANCIAL INTEGRITY: Stop overselling (legal/financial)
  2. REVENUE PROTECTION: Fix checkout failures ($38K/sec)
  3. CASCADE PREVENTION: Protect auth/sessions from Redis 
     starvation (prevent TOTAL outage)
  4. USER EXPERIENCE: Fix stale inventory display
  5. INFRASTRUCTURE: DNS, gRPC balancing, CDN

$2.3M/minute revenue. Cannot shut down. Every action 
must preserve checkout for in-stock items.
```

### First 60 Seconds (06:10:00 - 06:11:00)

```
ACTION 1: FIX THE OVERSELLING BUG [06:10:00 — 30 seconds]

  This is the most financially dangerous problem. 
  Every second it runs, more items could be oversold.

  IMMEDIATE: Deploy a hotfix to the Inventory Service 
  that removes the cache read from the purchase path 
  and uses the atomic conditional UPDATE:

  # Feature flag (if available):
  feature_flag.set("INVENTORY_CHECK_BYPASS_CACHE", True)
  
  # This routes the purchase path directly to:
  UPDATE inventory SET stock = stock - 1 
  WHERE product_id = $1 AND stock > 0 
  RETURNING stock;
  
  # NO cache read. NO separate check. One atomic 
  # statement against the primary.

  If feature flag isn't available: roll forward with 
  a code change to the Inventory Service. This is a 
  ONE-LINE change in the purchase path.

  VERIFY: Monitor for new overselling events. 
  stock values should never go below 0.

  TIME: 15-30 seconds if feature flag exists.
  2-3 minutes if code deploy required.


ACTION 2: PROTECT SESSIONS — SEPARATE FROM INVENTORY [06:10:30]

  Sessions and inventory cache are on the SAME Redis 
  cluster. The inventory stampede is killing sessions.
  
  IMMEDIATE: Isolate session reads from inventory 
  cache load.

  OPTION A (fastest): Rate-limit inventory cache 
  operations at the Redis proxy level. Cap inventory 
  key reads to 10K/sec (vs current 124K/sec). Excess 
  reads get a "cache miss" response and must fall 
  through to DB — but this is already happening anyway 
  for 69% of requests.

  OPTION B: If the application can be configured per-key-
  prefix: set inventory cache reads to a separate Redis 
  connection pool with a lower max. This reserves 
  connection capacity for session operations.

  # Redis connection pool separation:
  redis_session_pool = RedisPool(max_connections=100)
  redis_inventory_pool = RedisPool(max_connections=50)
  # Sessions get 100 connections (protected)
  # Inventory cache gets 50 (throttled)

  VERIFY: Session read latency drops to <5ms.
  Users stop being logged out.
  
  TIME: 30 seconds (config change).
```

### Minutes 2-5 (06:12:00 - 06:15:00)

```
ACTION 3: FIX POSTGRESQL POOL EXHAUSTION [06:12:00]

  The root cause of checkout failures: inventory read 
  cache misses consume ALL 200 connections, starving 
  order writes.

  FIX: Separate connection pools for reads vs writes.

  # Application config:
  PG_POOL_INVENTORY_READS = 80   # cap inventory reads
  PG_POOL_ORDER_WRITES = 80      # reserved for orders
  PG_POOL_OTHER = 40             # everything else
  # Total: 200 (unchanged)
  
  # Order writes now have 80 GUARANTEED connections 
  # that inventory reads cannot steal.

  ALTERNATIVELY (faster if pool separation isn't 
  configurable): reduce inventory cache miss 
  fallthrough by pre-warming the cache.

  CACHE PRE-WARM: Fetch all 2,000 flash sale product 
  IDs and populate Redis cache from the PRIMARY 
  (not replica — we want accurate counts):

  # Run once, takes ~2 seconds:
  for product_id in flash_sale_product_ids:
      stock = primary_db.fetchval(
          "SELECT stock FROM inventory WHERE product_id = $1",
          product_id
      )
      redis.set(f"inventory:{product_id}", stock, ex=5)

  EFFECT: Cache hit rate recovers from 31% to ~95%.
  Cache miss fallthrough drops from 124K/sec to ~9K/sec.
  PostgreSQL connection pool pressure drops immediately.
  Order writes start succeeding.

  VERIFY: 
  → Cache hit rate > 90%
  → PG pool utilization < 70%
  → Checkout error rate drops from 23% to < 1%
  → ONE CHANGE → VERIFY → NEXT CHANGE

  TIME: 2-3 minutes.


ACTION 4: FIX gRPC LOAD IMBALANCE [06:13:00]

  product-svc-7 at 94% CPU. Quick fix:

  # Restart product-svc-7 to reset its connections:
  kubectl rollout restart deployment/product-svc -n us \
    -- this restarts ALL replicas, redistributing 
    connections across the NLB

  ACTUALLY — don't restart ALL 12. Rolling restart one 
  at a time. But even faster:

  # Just kill product-svc-7 specifically:
  kubectl delete pod product-svc-7 -n us
  # Kubernetes recreates it. New pod gets new connections.
  # NLB distributes new connections more evenly.

  VERIFY: All product-svc replicas at roughly equal CPU 
  (should be ~25-30% each at current traffic). Product 
  page p99 drops from 4.2s to <500ms.

  TIME: 30 seconds.

  NOTE: This is a band-aid. The underlying L4 LB + gRPC 
  problem will recur. Strategic fix (L7 LB or client-side 
  balancing) goes into post-incident items.
```

### Minutes 5-15 (06:15:00 - 06:25:00)

```
ACTION 5: FIX DNS TTL [06:15:00]

  30% of traffic is hitting the old cluster due to 
  cached DNS records (TTL=3600s changed at 06:00).

  THE DNS RECORD HAS ALREADY BEEN CHANGED. The problem 
  is that clients cached the OLD record and won't 
  refresh for up to 60 minutes.

  WE CANNOT FORCE CLIENT DNS CACHES TO EXPIRE.

  MITIGATION OPTIONS:

  OPTION A: Re-point the OLD cluster to proxy/redirect 
  to the new cluster.

  # On the old cluster's load balancer:
  # Add a 301 redirect or proxy rule that forwards 
  # all requests to the new cluster's IP
  # This handles the 30% of traffic with cached DNS

  OPTION B: Scale UP the old cluster to handle the load.
  # Add instances to the old cluster's autoscaling group
  # It's getting 30% of flash sale traffic — give it 
  # capacity to handle it until DNS propagates

  OPTION B is SAFER (no redirect latency, no additional 
  failure mode). Scale the old cluster to handle the 
  traffic. It will naturally drain as DNS propagates.

  VERIFY: Old cluster error rate drops. Both clusters 
  serving traffic successfully.

  LESSON FOR NEXT TIME: Lower DNS TTL to 60 seconds 
  AT LEAST 48 hours before changing the record. Then 
  change the record. Then raise TTL back.

  TIME: 3-5 minutes (autoscaling takes time to provision).


ACTION 6: REDUCE STALE INVENTORY DISPLAY [06:17:00]

  Three layers of staleness:

  Fix CDN staleness: Set stock count in HTML to 
  a placeholder. Never embed mutable data in cached HTML.

  # Immediate: Invalidate CloudFront cache for product pages
  aws cloudfront create-invalidation \
    --distribution-id E1234567 \
    --paths "/products/*"
  
  # Update Cache-Control for product pages with stock data:
  # Cache-Control: no-cache (for pages with stock counts)
  # OR: Cache-Control: max-age=5 (match Redis TTL)
  # The images stay cached (max-age=86400), only the 
  # HTML templates change.

  Fix WebSocket lag: Scale up WebSocket consumers.
  # Add more consumer instances to the Notification Service
  # to process inventory_updated events faster.
  # OR: batch broadcasts — instead of broadcasting each 
  # individual update, aggregate updates per product over 
  # 1-second windows and broadcast the latest value.

  Fix replication lag visibility: Add staleness indicator.
  # For EU/APAC users: display "Stock count may be 
  # approximate" during high-traffic periods.
  # Check replica lag before serving:
  # If lag > 2s: show "Estimated: ~X left" instead of "X left"

  VERIFY: Stock counts on product pages are <10s stale 
  instead of 38-45s stale.

  TIME: 5-10 minutes for CDN invalidation + consumer scaling.


ACTION 7: HANDLE THE 17 OVERSOLD SNEAKERS [06:20:00]

  517 orders placed for 500 units. 17 oversold.

  This is a BUSINESS decision, not an engineering decision.
  Engineering provides the data; business decides the action.

  # Identify the 17 oversold orders:
  SELECT o.order_id, o.user_id, o.created_at, o.total
  FROM orders o
  WHERE o.product_id = 'SKU-8812'
  ORDER BY o.created_at DESC
  LIMIT 17;
  -- The last 17 orders (by time) are the ones placed 
  -- after stock should have been 0.

  OPTIONS (business decides):
  
  a) HONOR ALL 517 ORDERS:
     → Source 17 additional units from supplier or 
       another warehouse
     → Cost: wholesale cost × 17 (maybe $1,500-3,000)
     → Best customer experience
     → Preferred if units are obtainable

  b) CANCEL THE 17 OVERSOLD ORDERS:
     → Contact the 17 customers proactively
     → Full refund + apology + discount code for 
       future purchase
     → "We're sorry, due to unprecedented demand..."
     → Worst case: 17 unhappy customers, some social 
       media complaints

  c) WAITLIST THE 17:
     → Contact customers: "Your order is confirmed but 
       shipping is delayed 2-3 weeks while we restock"
     → Customer can choose to wait or cancel for refund
     → Middle ground between (a) and (b)

  RECOMMENDATION TO BUSINESS: Option (a) if units are 
  available from supplier. Option (c) if not immediately 
  available. Option (b) only as last resort.

  ENGINEERING ACTION: Set stock=0 for SKU-8812 immediately 
  if not already. Verify the overselling fix (Action 1) 
  is preventing further oversales.

  UPDATE inventory SET stock = 0 
  WHERE product_id = 'SKU-8812' AND stock < 0;
```

### Mitigation Timeline Summary

```
╔══════════════════════════════════════════════════════════════╗
║   TIME   │ ACTION                           │ EFFECT         ║
╠══════════════════════════════════════════════════════════════╣
║  06:10:00│ Fix overselling bug              │ Stop financial ║
║          │ (bypass cache, atomic UPDATE)    │ bleeding       ║
╠══════════════════════════════════════════════════════════════╣
║  06:10:30│ Isolate session Redis from       │ Users stop     ║
║          │ inventory cache load             │ being logged   ║
║          │                                  │ out            ║
╠══════════════════════════════════════════════════════════════╣
║  06:12:00│ Pre-warm inventory cache +       │ Checkout error ║
║          │ separate PG connection pools     │ 23% → <1%      ║
╠══════════════════════════════════════════════════════════════╣
║  06:13:00│ Kill product-svc-7               │ Product p99    ║
║          │ (redistribute gRPC connections)  │ 4.2s → <500ms  ║
╠══════════════════════════════════════════════════════════════╣
║  06:15:00│ Scale old DNS cluster            │ 30% traffic    ║
║          │                                  │ handled        ║
╠══════════════════════════════════════════════════════════════╣
║  06:17:00│ Invalidate CDN, scale WS         │ Staleness      ║
║          │ consumers, staleness banners     │ 45s → <10s     ║
╠══════════════════════════════════════════════════════════════╣
║  06:20:00│ Handle 17 oversold orders        │ Business       ║
║          │ (provide data to business team)  │ resolution     ║
╚══════════════════════════════════════════════════════════════╝

DEPENDENCY ORDERING:
  Action 1 (overselling) → independent, do FIRST
  Action 2 (session isolation) → independent, do FIRST
  Action 3 (cache warm + pool split) → after Action 2 
    stabilizes Redis, verify sessions are healthy before 
    adding cache warm load
  Action 4 (gRPC) → independent, can run in parallel 
    with Action 3
  Action 5 (DNS) → independent, can run in parallel
  Action 6 (staleness) → after Actions 3-5 stabilize 
    the platform
  Action 7 (oversold orders) → after Action 1 stops 
    further overselling
```

---

## Q6: Pre-Event Prevention — Top 5 Actions

### 1. Pre-Warm Inventory Cache for Flash Sale Products

```
WHAT: Before the flash sale starts, populate Redis cache 
with stock counts for ALL 2,000 flash sale products.

# Scheduled job at 05:55 (5 minutes before sale):
for product_id in flash_sale_product_ids:
    stock = primary_db.fetchval(
        "SELECT stock FROM inventory WHERE product_id = $1",
        product_id
    )
    redis.set(f"inventory:{product_id}", stock, ex=10)

PREVENTS: Problem 1 (cache stampede), Problem 2 (PG pool 
exhaustion), Problem 9 (Redis/session contention).

WHY: The entire incident cascade started because 2,000 
products had zero cache entries at 06:00. 124K/s cache 
misses → PG pool exhaustion → checkout failures → 
session starvation. Pre-warming eliminates the first 
domino. Cache hit rate stays at 94%+ from the start. 
PG pool never exhausts. Sessions never starve.

This single action prevents 60-70% of the incident.
```

### 2. Separate Redis Clusters for Sessions and Inventory Cache

```
WHAT: Deploy sessions and inventory cache on SEPARATE 
Redis clusters. No shared infrastructure between 
session state and volatile cache data.

PREVENTS: Problem 9 (session/inventory contention). 

WHY: Inventory cache is HIGH-VOLUME, EXPENDABLE (cache 
miss just means a DB read). Sessions are LOW-VOLUME, 
CRITICAL (session loss = user logged out = lost sale). 
Sharing infrastructure means a problem in the expendable 
system (cache stampede) kills the critical system 
(sessions). Isolation ensures inventory cache load — 
even worst-case stampede — cannot affect session reads.

This is the "blast radius isolation" principle: failure 
domains for data with different criticality must not 
share resources.
```

### 3. Lower DNS TTL 48 Hours Before the Event

```
WHAT: At least 48 hours before Black Friday, lower 
the DNS TTL for flash.shop.example.com from 3600s 
to 60s. Wait for the old TTL to expire across all 
resolvers. THEN make the DNS change at 06:00.

# 48 hours before (Wednesday):
aws route53 change-resource-record-sets \
  --hosted-zone-id Z1234 \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "flash.shop.example.com",
        "Type": "A",
        "TTL": 60,
        "ResourceRecords": [{"Value": "OLD_IP"}]
      }
    }]
  }'

# By Friday 06:00: all resolvers have TTL=60s cached.
# Change the IP: all clients refresh within 60 seconds.
# No 30% split between old and new clusters.

PREVENTS: Problem 8 (DNS TTL). 

WHY: DNS propagation is bounded by the PREVIOUSLY 
cached TTL, not the new TTL. Lowering TTL after 
changing the record is useless — clients already 
cached the old record with the old (3600s) TTL. You 
must lower TTL FIRST, wait for the old TTL to expire, 
THEN change the record.
```

### 4. Fix the Overselling Bug in the Inventory Service

```
WHAT: Remove the Redis cache read from the purchase 
decision path. Use atomic conditional UPDATE:

  UPDATE inventory SET stock = stock - 1 
  WHERE product_id = $1 AND stock > 0 
  RETURNING stock;

No cache check. No separate read. One atomic statement.

PREVENTS: Problem 5 (overselling).

WHY: The overselling bug exists independently of the 
flash sale load. High concurrency during the sale 
exposes it, but the race condition between cache read 
and DB write is a latent bug that could be triggered 
anytime a popular item has limited stock. Fix it 
proactively during the pre-event review.

Load test the atomic UPDATE under expected concurrency 
(1000+ concurrent requests for the same SKU). Verify 
stock never goes below 0.
```

### 5. Fix gRPC Load Balancing

```
WHAT: Replace L4 NLB with L7 load balancing for the 
Product Service gRPC traffic. Either:
  → Switch to ALB with gRPC support (L7)
  → Deploy Envoy sidecar with client-side gRPC balancing
  → Add gRPC client-side round_robin LB policy

PREVENTS: Problem 3 (gRPC hot replica).

WHY: This problem was dormant for 9 days. Under normal 
load, product-svc-7 at 40% traffic was manageable. 
Under 12x flash sale load, it hit 94% CPU and degraded 
product pages to 4.2s p99. The fix must be in place 
before any traffic spike. 

Additionally: implement a SCHEDULED rolling restart 
policy (e.g., every 24 hours) for gRPC services behind 
L4 load balancers, to prevent connection pinning from 
accumulating over time. This is a band-aid until L7 
balancing is deployed, but prevents the 9-day 
accumulation scenario.
```

```
PREVENTION SUMMARY:

╔══════════════════════════════════════════════════════════════╗
║  # │ ACTION                     │ PROBLEMS PREVENTED         ║
╠══════════════════════════════════════════════════════════════╣
║  1 │ Pre-warm inventory cache   │ #1 stampede, #2 PG pool,   ║
║    │                            │ #9 session contention      ║
╠══════════════════════════════════════════════════════════════╣
║  2 │ Separate Redis clusters    │ #9 session contention      ║
║    │ (sessions vs cache)        │                            ║
╠══════════════════════════════════════════════════════════════╣
║  3 │ Lower DNS TTL 48hrs early  │ #8 DNS split traffic       ║
╠══════════════════════════════════════════════════════════════╣
║  4 │ Fix overselling bug        │ #5 overselling             ║
║    │ (atomic UPDATE)            │                            ║
╠══════════════════════════════════════════════════════════════╣
║  5 │ Fix gRPC L4 LB imbalance   │ #3 hot replica             ║
╠══════════════════════════════════════════════════════════════╣
║    │ COMBINED: 5 actions prevent│ 7 of 9 problems            ║
║    │ Remaining: #4 stale display│ (acceptable with cache     ║
║    │ #6 WebSocket lag, #7 CDN   │ warm + reduced staleness)  ║
╚══════════════════════════════════════════════════════════════╝

Problems #4 (stale display), #6 (WebSocket lag), and 
#7 (CDN template staleness) would still occur but with 
MUCH less severity:
  → Pre-warmed cache reduces staleness window
  → Cache stampede elimination reduces replication lag 
    (less write pressure on primary → less lag)
  → These become UX annoyances, not incident-level problems

An additional action beyond top 5: LOAD TEST the entire 
flash sale flow at 2x expected peak (360K req/s) the 
week before. This would reveal ALL of these problems 
in a controlled environment.
```

---

