# WEEKS 2 AND 3 RETENTION TEST

## Rules of Engagement

```text
+---------------------------------------------------------------+
| RULES OF ENGAGEMENT                                           |
+---------------------------------------------------------------+
| 1. Answer from memory first. Do not open teaching modules or   |
|    answer keys until you have written your attempt.            |
|                                                               |
| 2. Rapid-fire questions should be concise: 2-4 sentences,     |
|    a small table, or a short code/config snippet when asked.   |
|                                                               |
| 3. Compound scenarios require incident-depth reasoning. Trace  |
|    symptoms to layers, identify root causes vs amplifiers, and |
|    prioritize mitigations in time order.                       |
|                                                               |
| 4. If you do not remember something, write "I don't remember" |
|    and keep going. Honest misses make the review loop useful.  |
|                                                               |
| 5. After finishing, compare against the answer key and score   |
|    error types, not just right/wrong answers.                  |
+---------------------------------------------------------------+
```

> **Answer key (do not open until you attempt all questions):**
> [`../answers/Retention-Tests/Weeks-02-and-03%20Answers.md`](../answers/Retention-Tests/Weeks-02-and-03%20Answers.md)

---

## Part 1: Rapid-Fire Concept Recall

Answer every question. Keep each response tight unless the prompt asks for math, a timeline, or a command.

### Week 2 Review: Storage, NoSQL, and Caching

**Q1 [TCP -- TIME_WAIT]:**

A service is failing outbound connections with high `TIME_WAIT` counts.

1. What does `TIME_WAIT` protect against?
2. Why does it last `2 * MSL`?
3. What Linux sysctl can reduce outbound `TIME_WAIT` reuse risk during a P1, and what safety condition makes it acceptable?

**Q2 [HTTP -- HoL Blocking]:**

HTTP/2 fixed HTTP-layer head-of-line blocking through multiplexed streams, yet it can make TCP-layer head-of-line blocking worse than HTTP/1.1.

Explain the mechanism, then state how HTTP/3/QUIC changes the failure domain.

**Q3 [gRPC -- L4 Black Hole]:**

Six gRPC replicas sit behind a layer-4 load balancer. One or two replicas run hot while the rest are nearly idle.

1. What is the root cause?
2. Give two concrete fixes that distribute requests instead of pinned TCP connections.

**Q4 [WebSockets -- 60s Drops]:**

WebSocket clients disconnect exactly every 60 seconds when idle.

1. What kind of component is likely dropping the connection?
2. What heartbeat interval would you implement?
3. Why is an AWS NLB an unlikely explanation for a 60-second cutoff?

**Q5 [DNS -- Kubernetes `ndots:5`]:**

A pod calls `fraud-api.payments.example.com` from a namespace with Kubernetes default `ndots:5` and several search domains.

1. How many DNS queries can one lookup generate before success?
2. List the likely search-expanded names.
3. What one-character change makes the name absolute and skips search expansion?

**Q6 [CDN -- Cache-Control]:**

For this header:

```http
Cache-Control: public, max-age=300, stale-while-revalidate=60, stale-if-error=86400
```

Describe what the CDN does at:

- `T=0`
- `T=200`
- `T=350`
- `T=400`
- `T=350` when the origin is down

**Q7 [SQL/ACID -- Isolation Levels]:**

Transaction A reads account balance `$1000`. Transaction B updates it to `$500` and commits. Transaction A reads again.

1. What does Transaction A see under `READ COMMITTED`?
2. What does it see under `REPEATABLE READ`?
3. What anomaly is this testing?

**Q8 [SQL/Indexing -- Composite Index]:**

Given an index on `(user_id, status, created_at)`, say whether each query can use the index well, partially, or not at all. Explain via the leftmost-prefix rule.

1. `WHERE user_id = 123`
2. `WHERE user_id = 123 AND created_at > '2024-01-01'`
3. `WHERE status = 'active'`
4. `WHERE user_id = 123 AND status = 'active' AND created_at > '2024-01-01'`
5. `WHERE status = 'active' AND user_id = 123`

**Q9 [SQL/MVCC]:**

In PostgreSQL MVCC:

1. Why do readers not block writers?
2. What storage cost accumulates because of that design?
3. What process cleans it up?

**Q10 [NoSQL -- Cassandra Write Path]:**

A Cassandra coordinator receives a write.

List the write path in order, including commit log, memtable, acknowledgment, SSTable flush, and why the commit log exists.

**Q11 [NoSQL -- Cassandra QUORUM]:**

A Cassandra table has replication factor 3.

1. What is `QUORUM` for reads/writes?
2. What availability/correctness tradeoff does `QUORUM` make compared with `ONE`?
3. What happens when one replica is down and another is slow or unreachable?

**Q12 [NoSQL/Redis -- Eviction Policy]:**

Explain the difference between `volatile-lru` and `allkeys-lru`.

When can `volatile-lru` evict hot cache entries while protecting cold keys?

**Q13 [Caching -- Stampede]:**

A hot key expires and thousands of requests miss simultaneously.

1. Name the failure pattern.
2. Give at least three mitigation patterns.
3. Which mitigation prevents duplicate backend recomputation per process?

**Q14 [Caching -- Invalidation Race]:**

A service deletes a cache key before committing the database transaction. A concurrent reader misses cache, reads the database, and repopulates cache.

1. Under PostgreSQL `READ COMMITTED`, what version can the reader see before commit?
2. What ordering should the writer use instead?
3. Why does that ordering prevent stale re-caching?

**Q15 [Cross-Topic -- Read-After-Write]:**

A user updates profile data and immediately reads stale data.

1. Name the consistency guarantee violated.
2. Give a database-replica fix.
3. Give a cache-specific fix.
4. What principle do both fixes share?

### Week 3 Review: Consistency, CAP/PACELC, and Hashing

**Q16 [TCP -- EADDRNOTAVAIL]:**

A service shows `connect() EADDRNOTAVAIL`, very high `TIME_WAIT`, low CPU, low memory, and normal database CPU.

What is the likely root cause, and what evidence distinguishes it from a slow database?

**Q17 [HTTP/2 -- HoL Blocking]:**

A single packet loss event causes all multiplexed HTTP/2 streams on a connection to pause.

Explain why this occurs even though HTTP/2 has independent stream IDs.

**Q18 [gRPC -- NLB Hot Replica]:**

A gRPC service behind an AWS NLB has one pod at 94% CPU and the rest near idle.

What exact load-balancing failure pattern is this, and what monitoring alert would catch it generically across services?

**Q19 [WebSockets vs SSE]:**

Choose WebSockets or Server-Sent Events for each case and justify briefly:

1. Bidirectional collaborative editing.
2. Server-to-client notifications only.
3. Mobile clients behind restrictive proxies.
4. Live chat with typing indicators.

**Q20 [Kubernetes DNS -- `ndots:5`]:**

Why does Kubernetes default `ndots:5` amplify DNS traffic for external or partially-qualified names? Give one config-level fix and one naming-level fix.

**Q21 [CDN -- Cache-Control at T=15]:**

A response has:

```http
Cache-Control: max-age=10, stale-while-revalidate=20, stale-if-error=86400
```

At `T=15`, what should the CDN serve, what background action should it take, and what changes if the origin is down?

**Q22 [PostgreSQL READ COMMITTED -- Phantoms and Non-Repeatable Reads]:**

Under `READ COMMITTED`, explain the difference between:

1. A non-repeatable read.
2. A phantom read.

Give a one-sentence example of each.

**Q23 [Composite Index Usage]:**

Given an index `(tenant_id, created_at, status)`, evaluate whether these predicates use it well:

1. `tenant_id = ?`
2. `tenant_id = ? AND status = ?`
3. `tenant_id = ? AND created_at BETWEEN ? AND ?`
4. `status = ?`
5. `tenant_id = ? AND created_at BETWEEN ? AND ? AND status = ?`

**Q24 [Cassandra -- Stale Reads at CL=ONE]:**

A write succeeds to replica A, replica B is temporarily behind, and a later read at consistency level `ONE` hits replica B.

What can the client see, and what read/write consistency combination would reduce that risk?

**Q25 [Cassandra -- Write Path on Replica Node]:**

On a replica receiving a Cassandra write, explain the role and order of:

- Commit log append
- Memtable update
- Acknowledgment
- Memtable flush
- Compaction

**Q26 [Cache-Aside Staleness]:**

In cache-aside, a writer updates the database but fails before deleting the cache key.

What stale-read behavior follows, and what two design patterns can reduce this window?

**Q27 [Probabilistic Early Expiry]:**

What problem does probabilistic early expiry solve? Describe how it spreads refresh work before TTL expiration.

**Q28 [DynamoDB -- PACELC]:**

Classify DynamoDB using PACELC for:

1. Default eventually consistent reads.
2. Strongly consistent reads in a single region.
3. Global tables across regions.

Explain the latency/consistency tradeoff.

**Q29 [etcd as Session Store]:**

Why is etcd a poor fit for high-volume user session storage? Name the system property etcd optimizes for and the workload characteristic sessions require.

**Q30 [Consistency Model Violations -- Trap]:**

A system is eventually consistent and sometimes returns older data. Not every stale read violates every session guarantee.

Given a user writes value `v2`, then the same user reads `v1`, which guarantee is violated? Which stronger guarantee would also prevent it?

**Q31 [Consistent Prefix Reads]:**

A user sees message 2 of a conversation before message 1.

What consistency guarantee is violated, and what ordering metadata or partitioning strategy can prevent it?

**Q32 [Consistent Hashing -- Key Remapping]:**

A cluster has 100 nodes and one node is added.

Roughly what fraction of keys should move under consistent hashing, and why is that better than `hash(key) mod N`?

**Q33 [Redis Cluster -- Resharding Hot Key]:**

One Redis key receives 70% of traffic.

Why does resharding slots not solve the hot-key problem? Give two application-level fixes.

**Q34 [PostgreSQL Round-Robin Reads]:**

An application round-robins reads across async replicas after writes.

Name two consistency/session guarantees this can violate and give a routing fix.

**Q35 [Flash Sale Inventory Decrement]:**

A flash sale decrements inventory concurrently.

What SQL pattern prevents overselling on a single PostgreSQL primary? State the lock or predicate that makes it safe.

---

## Part 2: Compound Scenarios

### Scenario A: Live Event Entitlement Meltdown

```text
INCIDENT REPORT
Severity: P1
Service: Global live-streaming platform for a championship fight
Time: 21:00 UTC

Business context:
  - 400,000 paying viewers are already watching the pre-show.
  - At 21:00, a push notification brings 1,400,000 additional
    authenticated users to the "Watch Live" button within 90 seconds.
  - Users must receive a valid stream URL quickly or they churn/refund.

Architecture:
  Users -> CloudFront -> API Gateway -> 40 API pods
  API pods -> Redis Cluster for entitlement cache
  API pods -> gRPC Entitlement Service, 6 replicas behind an L4 LB
  Entitlement Service -> PgBouncer -> PostgreSQL
  Web/mobile clients -> NLB -> 20 WebSocket servers for chat/events
  Chat + analytics events -> Cassandra
  Kubernetes CoreDNS handles service discovery

Important implementation details:
  - Entitlement cache key: entitled:<user_id>
  - Entitlement TTL: 600 seconds
  - Entitlement service name in config:
      entitlement-svc.payments.internal.cluster.local
  - Kubernetes resolver option: ndots:5
  - API responses through CloudFront use:
      Cache-Control: max-age=2, stale-while-revalidate=2

Symptoms at 21:02:
  - "Watch Live" success rate: 99% -> 61%
  - 340,000 users are authenticated but cannot obtain stream URLs
  - Redis hit rate: 97% -> 34%
  - Redis cluster ops: 410,000/sec
  - Redis node 4 CPU: 99%; node 4 owns 73% of entitlement keys
  - Redis slowlog: 0.3ms per op
  - gRPC Entitlement Service requests: 800/sec -> 41,000/sec
  - Entitlement replica 1 CPU: 94%; replicas 2-6 CPU: 11%
  - gRPC timeout errors: 8,400/min
  - PostgreSQL queries: 220/sec -> 18,500/sec
  - PgBouncer pool: 150/150 active; cl_waiting: 2,340
  - Entitlement query avg_exec_time: 1.2ms -> 67ms
  - Connected WebSocket clients: 1.46M out of expected 1.8M
  - WebSocket server memory: 14.2GB/16GB each
  - Chat delivery latency: 50ms -> 2,400ms
  - New WebSocket upgrade requests return some HTTP 503s
  - Cassandra write latency: 3ms -> 45ms
  - Cassandra MutationStage: 256/256 active, 12,847 pending
  - Cassandra read latency: normal at 8ms
  - CoreDNS: 8,000 qps baseline -> 48,000 qps
  - CloudFront is returning cached 503 responses for up to 4 seconds
```

**Question A1: All Problems**

Identify every distinct problem. For each one, list:

- Component/layer
- Root cause hypothesis
- Evidence from the report
- Whether it is cascade-triggered or independent/pre-existing

**Question A2: Redis Node 4**

Explain how 73% of entitlement keys can concentrate on one Redis Cluster node.

- What Redis Cluster concept determines key placement?
- What commands/data would you inspect?
- What fix is safe immediately, and what fix should wait until after the event?

**Question A3: gRPC L4 Black Hole**

Explain the entitlement replica CPU distribution in one sentence.

Then design a generic monitoring alert that catches this pattern across any replicated service, not just this incident.

**Question A4: CDN Caching 503 Errors**

Explain how `max-age=2, stale-while-revalidate=2` can extend user-visible 503s.

How should error responses be configured so the CDN does not cache transient backend failures like successful API responses?

**Question A5: Fastest Mitigation**

You can make exactly one production change in the first minute.

What action gets the most users watching fastest? Justify it against the alternatives.

**Question A6: Prioritized Mitigation Plan**

Write the first 15 minutes of incident response in priority order.

For each step include:

- Action
- Why it comes now
- Expected metric movement
- Verification before moving on

**Question A7: Pre-Event Prevention**

Name the top three things the team should have done before the event to prevent this incident class.

---

### Scenario B: Global Flash Sale Consistency and Inventory Failure

```text
INCIDENT REPORT
Severity: P1
Service: Global e-commerce flash sale
Time: Friday 06:00 UTC

Business context:
  - 2,000 limited-stock products go live at 06:00.
  - Traffic jumps from 15,000 req/s to 180,000 req/s.
  - Users expect inventory display and checkout decisions to be correct.

Architecture:
  Users -> CloudFront -> regional API clusters
  Product pages include data-initial-stock in cached HTML
  Inventory Service -> Redis inventory cache -> PostgreSQL primary
  EU/APAC read inventory from local async PostgreSQL replicas
  Order Service writes to the US PostgreSQL primary
  Product Service is gRPC behind an NLB, 12 replicas
  Inventory updates publish Kafka events to WebSocket servers
  User sessions and inventory cache share one Redis Cluster
  flash.shop.example.com DNS TTL is 3600 seconds

Implementation details:
  - 2,000 flash-sale products were added at 05:59.
  - Cache pre-warming did not run.
  - Inventory cache TTL is 30 seconds.
  - Checkout flow:
      1. Read stock from Redis cache.
      2. If stock > 0, continue.
      3. UPDATE inventory SET stock = stock - 1
         WHERE product_id = ?;
      4. Create order record.
  - DNS was changed at 06:00 to point to a larger cluster.

Symptoms by 06:10:
  - Cache hit rate: 96% -> 31%
  - PostgreSQL replica read qps: normal -> 124,000 cache-miss reads/sec
  - Checkout failure rate: 23%
  - PostgreSQL connection pools: 200/200 active per region
  - Product page p99: 4.2s
  - product-svc-7 CPU: 94%; other product replicas: 12-18%
  - EU replica lag: 40ms -> 3.8s
  - APAC replica lag: 120ms -> 8.2s
  - SKU-8812 stock becomes -14 even though only 100 units existed
  - WebSocket inventory update lag: 8-15 seconds
  - CloudFront serves product HTML with stock values up to 30s old
  - 30% of users still hit the old smaller cluster
  - New cluster sits at 20% capacity
  - Redis session reads time out; users get logged out mid-checkout
```

**Question B1: Every Distinct Problem**

Identify every distinct problem, not just the first domino. For each, classify it as:

- Pre-existing/dormant
- Triggered by the flash sale
- Cascade from another failure
- Amplifier of user impact

**Question B2: The Overselling Bug**

Explain the exact concurrency mechanism that allows stock to go negative.

Then give two safe fixes: one database-centered and one architecture/application-centered.

**Question B3: Consistency Analysis**

For each data type below, state the consistency model the current system effectively provides and what it should provide during checkout:

- Inventory count displayed to the user
- Inventory count used for purchase decision/decrement
- Product catalog data
- Shopping cart
- Order record
- Session

**Question B4: Three Layers of Staleness for EU Users**

Trace the staleness stack for an EU user viewing a product page:

- CDN HTML/template staleness
- Async replica lag
- WebSocket event lag

Explain how these layers combine and which one is safety-critical.

**Question B5: Mitigation Plan**

Write a prioritized response from 06:10 to 06:25.

Include what to stop immediately, what to route to primary, what to purge or bypass, what to scale, and how to verify recovery.

**Question B6: Pre-Event Prevention**

List the top five pre-event actions that would have prevented or contained this failure.

---

## Error-Type Self-Score Table

After checking the answer key, classify each miss by error type. Count patterns; do not just total points.

| Error Type | What It Means | Tally | Review Action |
|---|---|---:|---|
| Recall gap | I did not remember the concept or term. |  | Re-read the smallest relevant section and make a flashcard. |
| Mechanism gap | I named the concept but could not explain how it works. |  | Draw the sequence/data path from memory. |
| Evidence miss | I had the right concept but ignored or misread the metric/log clue. |  | Re-run the diagnosis using only evidence from the scenario. |
| Layer confusion | I blamed the wrong layer (CDN vs DNS vs DB vs cache vs LB). |  | Label each symptom by OSI/system layer before proposing fixes. |
| Cascade confusion | I mixed up root cause, amplifier, and victim. |  | Build a failure-chain diagram with arrows. |
| Consistency mistake | I chose the wrong consistency/isolation guarantee. |  | Write the read/write timeline and mark what each actor can see. |
| Mitigation ordering | My fix was valid but too late, risky, or lower priority. |  | Write a minute-by-minute plan with verification gates. |
| Over-fix / under-fix | I proposed a long-term redesign as an immediate fix, or only a band-aid as prevention. |  | Split answers into immediate, near-term, and permanent controls. |
| Math/scale miss | I did not quantify fan-out, quorum, slots, pools, TTLs, or connection counts. |  | Recalculate with units and compare to capacity limits. |

### Final Reflection

Write three bullets before moving on:

1. The highest-risk topic I missed was:
2. The failure pattern I can now recognize fastest is:
3. The next module I should review for reinforcement is:
