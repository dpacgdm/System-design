# Week 4 Retention Test — Part 1: Rapid-Fire (Q1–Q20)

---

## Q1 — TCP: `EADDRNOTAVAIL` with Short-Lived HTTP Connections

**The Problem:** Each short-lived HTTP/1.1 connection consumes an ephemeral port. After the connection closes, the socket enters `TIME_WAIT` state for 2×MSL (typically 60 seconds on Linux). At 50,000 connections/minute, there are ~50,000 sockets in `TIME_WAIT` at any given time. The default ephemeral port range (`32768–60999`) provides only ~28,000 ports. The sockets accumulate faster than they recycle, exhausting all available ephemeral ports for the destination IP:port tuple → `EADDRNOTAVAIL`.

**Kernel parameter:** `net.ipv4.tcp_tw_reuse` (allows reuse of `TIME_WAIT` sockets for *outgoing* connections when the new timestamp is greater than the last recorded timestamp of the old connection). The port range itself is controlled by `net.ipv4.ip_local_port_range`.

**Two fixes:**

| Level | Fix | Mechanism |
|-------|-----|-----------|
| **Kernel** | Set `net.ipv4.tcp_tw_reuse = 1` | Allows the kernel to reuse sockets in `TIME_WAIT` for new outbound connections, effectively recycling ports immediately rather than waiting 60s |
| **Application** | Use **HTTP connection pooling** (Keep-Alive) | Reuse persistent TCP connections across multiple HTTP requests, reducing the number of connections opened from 50,000/min to a small pool (e.g., 50–100 persistent connections) |

---

## Q2 — gRPC + L4 Load Balancer: Imbalanced Backend Load

**The Mechanism:** gRPC uses HTTP/2, which multiplexes all RPCs over a **single long-lived TCP connection** per backend. The NLB is an L4 (TCP-level) load balancer — it distributes *TCP connections*, not individual *requests/streams*. Once the HTTP/2 connection is established from the client to one backend pod, **all subsequent RPCs from that client flow over that single connection** to the same pod. With few client instances (or connection reuse), one pod receives the vast majority of connections/requests.

**Why NLB can't fix it:** The NLB has no visibility into HTTP/2 frames or gRPC streams — it only sees a single TCP connection that looks healthy and active. It has no mechanism to redistribute individual RPCs within that connection.

**Fix:** Use **client-side load balancing** (e.g., gRPC's built-in `round_robin` or `xds` resolver) that opens connections to all backends and distributes RPCs across them at the stream level — or replace the NLB with an **L7 load balancer** (e.g., Envoy, Istio) that understands HTTP/2 and can balance per-request.

---

## Q3 — DNS: Java App Slow External Resolution with `ClusterFirst`

**The Exact Behavior:** With `dnsPolicy: ClusterFirst`, Kubernetes configures `/etc/resolv.conf` with `ndots:5` (default) and search domains like `<ns>.svc.cluster.local`, `svc.cluster.local`, `cluster.local`. For an external name like `api.payment.com` (2 dots < 5 = `ndots`), the resolver appends each search domain *first*:

1. `api.payment.com.default.svc.cluster.local` → NXDOMAIN
2. `api.payment.com.svc.cluster.local` → NXDOMAIN
3. `api.payment.com.cluster.local` → NXDOMAIN
4. `api.payment.com.<host-search-domain>` → NXDOMAIN
5. `api.payment.com` → **SUCCESS** (finally the actual query)

That's **4–5 wasted DNS round-trips** before the real resolution. With Java's DNS caching quirks (and dual A/AAAA queries), this compounds to ~10 unnecessary queries per lookup → 5× latency.

**Two fixes:**

| Scope | Fix |
|-------|-----|
| **Pod spec** | Add `dnsConfig: { options: [{ name: ndots, value: "1" }] }` — names with ≥1 dot (like `api.payment.com`) are tried as absolute first |
| **Query** | Append a **trailing dot** to all external FQDNs: `api.payment.com.` — the trailing dot marks the name as absolute, bypassing all search domain expansion entirely |

---

## Q4 — CDN: Cache-Control Header

```
Cache-Control: s-maxage=86400, max-age=3600, stale-while-revalidate=60, stale-if-error=300
```

| Directive | Effect |
|-----------|--------|
| `s-maxage=86400` | CDN (shared cache) caches for 24 hours (86,400s) |
| `max-age=3600` | Browser (private cache) caches for 1 hour (3,600s) |
| `stale-while-revalidate=60` | Serve stale for up to 60s while asynchronously revalidating in the background |
| `stale-if-error=300` | Serve stale for up to 300s if the origin returns a 5xx or is unreachable |

---

## Q5 — PostgreSQL Read Committed: Three Anomalies

Read Committed prevents only **dirty reads**. Serializable additionally prevents:

| Anomaly | Definition | Real-World Example |
|---------|------------|--------------------|
| **Non-repeatable read** | A transaction reads the same row twice and gets different values because another transaction committed a modification between reads | A banking transfer reads an account balance as $1,000, yields control, another transaction withdraws $500 and commits, the first transaction re-reads and sees $500 — its logic (e.g., interest calculation) used two different balances |
| **Phantom read** | A transaction re-executes a range query and gets different *rows* because another transaction inserted or deleted rows | A report counts "all pending orders" and gets 42, another transaction inserts a new pending order, the report re-counts and gets 43 — subtotals no longer reconcile |
| **Write skew (serialization anomaly)** | Two transactions read overlapping data, make disjoint writes based on that data, and together violate an invariant that neither violated individually | Two on-call doctors both read "2 doctors on-call," both decide it's safe to remove themselves (each writes their own row), both commit — result is 0 doctors on-call, violating the "minimum 1" invariant |

---

## Q6 — Composite Index: `(customer_id, order_date, status)`

Composite B-tree indexes are sorted left-to-right. They can only be efficiently traversed by following the **leftmost prefix** and stopping at the first range scan or gap.

| Query | Efficient? | Why |
|-------|-----------|-----|
| **(A)** `WHERE customer_id = 42 AND order_date > '2024-01-01'` | ✅ **Yes** | Equality on `customer_id` (first column) allows an index seek to that partition, then a range scan on `order_date` (second column) within that partition. This follows the leftmost prefix perfectly. |
| **(B)** `WHERE order_date > '2024-01-01' AND status = 'pending'` | ❌ **No** | Skips the leftmost column (`customer_id`). The index is sorted first by `customer_id`, so without constraining it, the planner cannot seek — it must do a **full index scan** (or table scan) and filter. The `order_date` and `status` values are scattered across all `customer_id` partitions. |
| **(C)** `WHERE customer_id = 42 AND status = 'pending'` | ⚠️ **Partially** | Equality on `customer_id` (first column) allows a seek to all rows for customer 42. But `status` is the *third* column with `order_date` (second column) skipped. The index can narrow to `customer_id = 42` efficiently, but must then **scan all `order_date` values** for that customer and apply `status = 'pending'` as a filter predicate — not a seek. Better than a full table scan, but not fully indexed. |

---

## Q7 — Cassandra: CL=QUORUM Write + CL=ONE Read

**RF=3, W=QUORUM=2, R=ONE=1.**

Strong consistency requires: **R + W > N** → 1 + 2 = 3, which is **NOT > 3** (equals, not exceeds). ❌ **Strong consistency is NOT guaranteed.**

**The Math:** With W=QUORUM, 2 of 3 replicas acknowledge the write. With R=ONE, the read goes to 1 replica. There is a **1-in-3 probability** the read hits the one replica that has NOT yet received the write. In that case, the reader sees stale (old) data.

**The Anomaly:** The reader can experience a **stale read** — reading a value that is older than the most recently committed write. This is eventual consistency, not strong consistency. To guarantee strong consistency, the reader would need `CL=QUORUM` (R=2), giving R+W = 2+2 = 4 > 3.

---

## Q8 — Three Cache Stampede Prevention Strategies

| Strategy | Mechanism | Code Changes Required? |
|----------|-----------|----------------------|
| **1. Locking (Mutex)** | On cache miss, acquire a distributed lock (e.g., Redis `SETNX`); only the lock holder recomputes the value; all other requesters wait or receive the stale value until the lock holder populates the cache | ✅ Yes — client must implement lock-acquire-on-miss logic |
| **2. Probabilistic Early Recomputation (XFetch / PER)** | Each cache read checks `currentTime + Δ * β * log(rand())` > `expiry`; with increasing probability as expiry approaches, a request proactively recomputes the value *before* the TTL expires, staggering recomputation so only one request recomputes near expiry | ✅ Yes — client must implement the probabilistic check on each read |
| **3. Stale-While-Revalidate (Background Refresh)** | The caching layer serves stale content while asynchronously refreshing in the background; only one refresh occurs regardless of concurrent demand; configured at the CDN/proxy level via `Cache-Control: stale-while-revalidate=N` or equivalent proxy config | ❌ **No client code changes** — purely infrastructure/header configuration |

---

## Q9 — PACELC Classification

| Config | PACELC | Explanation |
|--------|--------|-------------|
| **(A)** PostgreSQL with synchronous replication to **all** standbys | **PC/EC** | During partition: chooses Consistency over Availability (writes block if any standby is unreachable). Else: chooses Consistency over Latency (every commit waits for all standbys to acknowledge, adding latency for durability). |
| **(B)** Cassandra with CL=ONE | **PA/EL** | During partition: chooses Availability over Consistency (CL=ONE can be satisfied by any single live node, so the system stays available even if most nodes are partitioned). Else: chooses Latency over Consistency (reading/writing one replica is fastest but provides no consistency guarantee). |
| **(C)** DynamoDB with strongly consistent reads | **PC/EC** | During partition: chooses Consistency over Availability (strongly consistent reads must reach the leader/current replica; if partitioned from the leader, the read fails rather than returning stale data). Else: chooses Consistency over Latency (strongly consistent reads go to the leader replica, adding latency vs. eventual reads from any replica). |

---

## Q10 — Consistency Violation: Old → New → Old

**Old → New → Old** demonstrates a violation of **monotonic read consistency**. Monotonic reads guarantee that if a process reads value V at time T, it will never subsequently read a value older than V. Seeing the new photo and then reverting to the old photo violates this — the read "went backward in time." This typically happens when successive reads are served by different replicas with inconsistent replication states.

**Old → New (without the third refresh):** This violates **read-your-writes (read-after-write) consistency**. The user performed a write (updated their photo), and their *first* read returned the old value — meaning the system did not guarantee the user sees the effect of their own write. However, it does **not** violate monotonic read consistency (reads progressed forward: old → new, never backward). It also does not violate causal consistency in isolation — the progression from old to new is causally valid.

---

## Q11 — Consistent Hashing: Key Movement Math

### Modular Hashing: `hash(key) mod N`

Going from N=100 to N'=105. A key stays on the same node only if `hash(key) % 100 == hash(key) % 105`.

Let `h = 100a + r` (where `0 ≤ r < 100`). Need `(100a + r) % 105 = r`, meaning `100a ≡ 0 (mod 105)`. Since `gcd(100, 105) = 5`, this simplifies to `20a ≡ 0 (mod 21)`, so `a ≡ 0 (mod 21)`.

Only **1 in every 21** hash values keeps the same assignment → **20/21 ≈ 95.2% of keys must move**.

> For K total keys: **~K × 20/21 keys move**.

### Consistent Hashing: 200 vnodes per node

- Before: 100 nodes × 200 vnodes = 20,000 points on the ring
- After: 105 nodes × 200 vnodes = 21,000 points on the ring
- New points added: 5 × 200 = 1,000 vnodes

Each new vnode claims a segment from its clockwise neighbor. The fraction of the ring reassigned = `1,000 / 21,000 = 1/21 ≈ 4.76%`.

> For K total keys: **~K/21 ≈ 4.76% of keys move**.

**Comparison:** Consistent hashing moves **20× fewer keys** than modular hashing (K/21 vs. 20K/21).

---

## Q12 — PostgreSQL `synchronous_commit` Levels

Five levels, weakest to strongest:

| # | Level | Guarantee |
|---|-------|-----------|
| 1 | **`off`** | No durability guarantee — returns immediately, WAL is flushed asynchronously. Risk of data loss on crash. |
| 2 | **`local`** | WAL flushed to **primary's local disk** (fsync). Durable on primary, but replicas may not have the data. |
| 3 | **`remote_write`** | WAL received by standby and written to the standby's **OS page cache** (kernel buffer), but NOT fsynced to disk. |
| 4 | **`on`** (default) | WAL flushed to **standby's disk** (fsync on standby). Durable on both primary and standby. |
| 5 | **`remote_apply`** | WAL applied to standby's state machine — changes are **visible to read queries on the standby**. |

**For `remote_write` specifically:** The WAL bytes have been transmitted over the network and written into the standby's **operating system page cache (kernel buffer)** via `write()` but NOT `fsync()`'d to the physical disk. If PostgreSQL on the standby crashes but the OS stays up, the OS will eventually flush the data to disk. But if the **standby machine itself crashes** (power loss, kernel panic), those bytes in the page cache are lost.

---

## Q13 — CDC vs. Cache-Aside for Redis Consistency

**Why CDC is superior:**

Cache-aside has a fundamental **race condition** between the database write and the cache invalidation. Two concurrent writes can interleave:

```
T1: Write A to DB     →     T2: Write B to DB
T2: Invalidate cache   →     T2: Reader fills cache with B
T1: Invalidate cache   →     T1: Reader fills cache with A  ← STALE! B is latest in DB
```

Additionally, if the application crashes *between* the DB write and the cache invalidation, the cache remains stale **indefinitely** with no self-healing mechanism.

**CDC (Debezium → Kafka → Redis)** eliminates both problems:
1. **Ordering:** Changes are captured from the WAL in **commit order** — the WAL is the single source of truth, so concurrent write races are resolved by the database's own serialization.
2. **Completeness:** Every committed transaction is captured — no "crash between write and invalidation" gap.
3. **Decoupling:** The cache update is driven by the WAL, not application code, so no application-level bugs can skip invalidation.

**Patient safety incident from the course:** In the cache-aside scenario, a patient's **medication allergy** was updated in the database (from "no known allergies" to "allergic to penicillin"). The application wrote to PostgreSQL but the cache invalidation either failed silently or was interleaved with another update. The cache continued serving the old "no known allergies" record. A prescribing system read the stale cache and approved a penicillin prescription for an allergic patient — a direct patient safety incident caused by a stale cache. CDC would have captured the allergy update from the WAL and propagated it to the cache in commit order, preventing the stale read.

---

## Q14 — Leader-Follower Failover: Four Failure Modes

| # | Failure | Description | Prevention |
|---|---------|-------------|------------|
| 1 | **Data loss** | Async replica is behind the primary; transactions committed on the primary but not yet replicated are permanently lost when the primary is decommissioned | **Synchronous replication** (or semi-sync) |
| 2 | **Split-brain** | The old primary recovers and begins accepting writes, creating two divergent primaries simultaneously | **Fencing (STONITH)** — Shoot The Other Node In The Head; revoke the old primary's ability to write |
| 3 | **Timeline divergence** | The old primary accepted writes after the failover decision but before being fenced; its WAL diverges from the new primary, making it impossible to re-add as a replica without intervention | **`pg_rewind`** — rewinds the old primary's timeline to the point of divergence and replays the new primary's WAL |
| 4 | **Stale reads on other replicas** | Other async replicas may be replicating from the old primary's WAL position and are even further behind; clients reading from these replicas see stale or inconsistent data | **Monotonic-read session routing** — pin client reads to a specific replica with a known replication position, or wait for replicas to catch up before serving reads |

---

## Q15 — DynamoDB GSI Update Semantics

**Synchronous or asynchronous?** GSI updates are **asynchronous**. The write to the base table returns success to the client *before* the GSI is updated. GSI updates are propagated in the background.

**Consistency anomaly:** A reader of the GSI can experience **stale reads** — the GSI may not yet reflect a recently committed write to the base table. All GSI reads are **eventually consistent only** (you cannot do a strongly consistent read against a GSI, only against the base table). This means a query on `status = 'pending'` via the GSI might return items whose status has already been changed to `'completed'` in the base table.

**Operational problem — GSI back-pressure throttling:** If the GSI's write capacity is insufficient to keep up with base table write throughput (e.g., the `status` GSI creates a hot partition because most items have `status = 'pending'`), DynamoDB will **throttle writes to the base table itself**. This is called **GSI back-pressure** — a slow or overloaded GSI directly degrades write availability of the entire table, even for writes to attributes that have nothing to do with the GSI.

---

## Q16 — Elasticsearch: Adding Shards to an Existing Index

**Can you add primary shards?** **No.** The number of primary shards is fixed at index creation time. The document routing formula is `shard = hash(_routing) % num_primary_shards` — changing the shard count would break all document routing, making existing documents unfindable.

**Migration strategy:**
1. Create a **new index** with the desired shard count (e.g., 10 or 15 primary shards, targeting ~30–50GB per shard)
2. Use the **`_reindex` API** to copy all documents from the old index to the new index
3. Use an **index alias** to atomically swap reads from the old index to the new index with zero downtime: `POST _aliases { "actions": [{ "remove": { "index": "old", "alias": "my-index" }}, { "add": { "index": "new", "alias": "my-index" }}]}`
4. Delete the old index after verification

**ILM rollover condition to prevent recurrence:**
```json
{
  "rollover": {
    "max_primary_shard_size": "50gb"
  }
}
```
Configure Index Lifecycle Management (ILM) with a **`max_primary_shard_size`** condition (e.g., 50GB). When any primary shard exceeds this threshold, ILM automatically creates a new index (with the correct shard count) and rolls the write alias to it. This prevents shards from ever growing to 80GB again. Combine with `max_age` (e.g., 30 days) for time-series data.

---

## Q17 — Raft Election Restriction: Can Node D Win?

**No. Node D cannot win the election.** Here is the proof:

**Setup:** 5-node cluster {A, B, C, D, E}. Entry X is committed on {A, B, C}. A (leader) has crashed. D (log does NOT contain X) starts an election.

**Election restriction (§5.4.1 of Raft paper):** A voter grants its vote only if the candidate's log is **at least as up-to-date** as the voter's log. "At least as up-to-date" = the candidate's last log entry has a higher term, OR the same term and a higher-or-equal index.

**D's attempt:**
- D needs **3 votes** (majority of 5) to win.
- D votes for itself → 1 vote.
- D requests votes from {B, C, E}.
- **B has entry X; D does not.** D's log is strictly less up-to-date than B's → **B rejects D's vote request.**
- **C has entry X; D does not.** Same reasoning → **C rejects D's vote request.**
- **E may or may not vote for D** (E doesn't have X either, so D's log may be as up-to-date) → at most 1 vote.
- D's maximum votes: **2 (D + E) < 3 (majority).** ❌ D cannot win.

**Majority overlap argument:** Any majority (≥3) of the 5 nodes must intersect with the set {A, B, C} (the nodes that have entry X) in at least one node. Since A is crashed, any electable majority drawn from {B, C, D, E} must include **at least one of {B, C}**. That node has entry X, and since D does not, that node will refuse to vote for D. Therefore, **no candidate whose log is behind a committed entry can ever assemble a majority** — this is the fundamental safety guarantee that committed entries are never lost.

---

## Q18 — etcd: Leader Crashes Before Replicating

**Is the entry committed?** **No.** Raft requires replication to a **majority** for commitment. The entry exists only on the crashed leader (1 of 5 nodes) — far short of a majority (3).

**Is the entry lost?** **Yes.** When a new leader is elected (from the remaining 4 nodes, none of which have the entry), the new leader's log becomes authoritative. When the old leader eventually recovers and rejoins, Raft's **Log Matching Property** forces it to truncate any uncommitted entries that conflict with the new leader's log. The entry is permanently discarded.

**What must the client do?** The client received no response (neither success nor failure), so it is in an **ambiguous state**. The client must **retry the write**.

**What property must the write have?** The write must be **idempotent** — retrying it must produce the same result whether the original write was applied zero times or (in edge cases with other failure modes) once. In etcd, this is achieved using **lease-based or revision-conditional writes** (e.g., `If-Match` on the `mod_revision`), or by designing operations to be naturally idempotent (e.g., "set X = 5" rather than "increment X").

---

## Q19 — Multi-Raft

**Multi-Raft** runs a **separate, independent Raft consensus group per data range (partition)** rather than funneling all writes through a single monolithic Raft group. CockroachDB assigns each range (~512MB of data) its own Raft group with its own leader. This means different ranges can have leaders on different nodes, and writes to different ranges proceed **in parallel** without contending for a single leader's serialization point. This is critical because the "replication scales reads but not writes" principle tells us that in a single-leader replication setup, the leader must sequentially process every write — adding more replicas helps absorb read traffic but does nothing for write throughput, which remains bottlenecked on the one leader. Multi-Raft breaks this bottleneck by **partitioning leadership** across ranges: with 45,000 ranges spread across 18 nodes, each node leads ~2,500 ranges and processes writes for those ranges independently. Write throughput scales horizontally with the number of nodes, because adding nodes means redistributing range leaderships. This is, in essence, the combination of **partitioning** (for write scalability) with **replication** (for fault tolerance and read scalability) — each range gets the safety of Raft consensus while the system as a whole gets the parallelism of partitioning.

---

## Q20 — Stale Reads from a Partitioned Raft Leader

**When does the old leader serve a stale read?** The old leader (term 7) serves a stale read if it **serves reads directly from its local state machine without verifying it is still the legitimate leader**. Since it is partitioned, it has no knowledge of the term 8 election. If it blindly trusts its own leader status and reads from its local state, it returns data that may be arbitrarily stale (the new leader in term 8 may have committed many new writes).

**Three mechanisms Raft provides to prevent this:**

| # | Mechanism | How It Works |
|---|-----------|-------------- |
| 1 | **ReadIndex** | Before serving a read, the leader sends a **heartbeat to a majority** and confirms it receives acknowledgments. If the leader is partitioned, it cannot reach a majority → the read is rejected. This adds one round-trip of latency but guarantees linearizability. |
| 2 | **Lease-based reads (LeaseRead)** | The leader holds a **time-bound lease** (renewed with each successful heartbeat). Reads are served only while the lease is valid. Once the partitioned leader's lease expires (it can't renew because it can't reach a majority), it stops serving reads. Requires tightly synchronized clocks. |
| 3 | **Log reads (Raft consensus reads)** | The read is treated as a **no-op log entry** that goes through full Raft consensus. It is committed like a write, guaranteeing it reflects the latest state. Safest but adds full Raft round-trip latency. |

**etcd's default:** etcd uses **ReadIndex** by default for linearizable reads. When a client requests a linearizable read, the leader records the current commit index, sends heartbeats to confirm leadership, and only serves the read once the state machine has applied up to that commit index. Serializable reads (opt-in, non-default) bypass this check and can return stale data for lower latency.


# Week 4 Retention Test — Part 2: Compound Scenario

---

## Q1: Root Cause Chain (10 pts)

### Complete Cascade — Link by Link

| # | Time | System | Degradation | Mechanism | Direct or Consequence? |
|---|------|--------|-------------|-----------|----------------------|
| **L1** | 09:29:55 | Network/Firewall | CockroachDB ports blocked us-east-1 ↔ eu-west-1 | Misconfigured firewall rule on transit gateway | **DIRECT** (root cause) |
| **L2** | 09:30:05 | CockroachDB Raft | eu-west-1 ↔ us-east-1 replicas lose direct communication; latency increases for ranges that relied on local eu-west-1 ACKs | **Raft requires direct leader→follower communication** — no relay through intermediaries. Ranges with leaseholders in eu-west-1 needing us-east-1 replicas can only reach us-west-2, not us-east-1 directly. Quorum still holds (2/3) for most ranges but via longer path. | Consequence of L1 |
| **L3** | 09:30:15 | CockroachDB Leaseholder Rebalancer | 8,000 ranges simultaneously initiate leaseholder transfers away from eu-west-1 | CockroachDB's **automatic leaseholder rebalancing** detects suboptimal placement (eu-west-1 leaseholders can't efficiently reach us-east-1 replicas) and triggers Raft leadership transfers to us-east-1/us-west-2 nodes | Consequence of L2 |
| **L4** | 09:30:30 | CockroachDB Multi-Raft (ALL ranges) | Commit latency spikes 4ms → 340ms on **unaffected** ranges | **Raft proposal queue contention** — Multi-Raft shares a per-node proposal pipeline across all ranges. 8,000 concurrent leadership elections flood the shared Raft scheduler, starving normal range proposals of processing time. | Consequence of L3 |
| **L5** | 09:30:35 | Debezium CDC / Matching Engine | CDC lag spikes; matching engine input queue grows; matched trades delayed | CDC changefeeds read from CockroachDB's **resolved timestamps**, which advance only as commits complete. 340ms commit latency directly delays changefeed emission. | Consequence of L4 |
| **L6** | 09:30:35 | Kafka Market Data | Stale prices in market data feed | Matching engine delays → stale trade/price data published to Kafka `market-data` topic. **Data staleness propagates downstream.** | Consequence of L5 |
| **L7** | 09:30:45 | API Gateway / Brokers | Traffic spikes 180K → 340K req/sec | **Retry amplification** — automated trading systems detect staleness (stale market data, delayed confirmations) and retry aggressively, creating a positive feedback loop | Consequence of L6 |
| **L8** | 09:31:00 | PostgreSQL / PgBouncer | Margin checks queue and timeout (US brokers) | **Connection pool exhaustion** — PgBouncer's 300-connection limit hit; 120K queries/sec (doubled by retries) far exceeds capacity. Queries queue behind the pool. | Consequence of L7 |
| **L9** | 09:31:00 | PostgreSQL eu-west-1 Replica | Account balances 45 seconds stale | **Compounded replication lag**: CockroachDB commit delay (L4) → CDC lag (L5) → Kafka consumer lag → PostgreSQL primary application lag → async replication lag to eu-west-1 replica. Each hop adds latency; they compound to 45s total. | Consequence of L4 + L5 |
| **L10** | 09:31:15 | Account Service / Trade Execution | $2.1M unauthorized margin trade accepted | **Stale read on safety-critical path** — margin check reads $2.4M available from 45s-stale replica; real available margin is $600K. Trade passes validation on stale data. | Consequence of L9 |

### The SINGLE Link to Break

> **Link 9 → 10: The decision to serve margin checks from the eu-west-1 async replica.**

If margin checks for EU brokers were routed to the **primary** (or a synchronous standby with bounded lag), the stale balance would never have been read. The $2.1M trade would have been rejected with the correct $600K available margin, **even with all other systems still degraded**. Every other link in the cascade causes performance degradation; only this link causes **financial exposure**.

Specifically, the architectural flaw is: **a safety-critical financial decision (margin validation) depends on an eventually consistent data source with no staleness bound.** No amount of latency, retry storms, or CDC lag causes financial harm if the margin gate reads from a strongly consistent source.

---

## Q2: The Unauthorized Trade — Data Path Analysis (10 pts)

### Exact Data Path: Real Balance → Stale Read

```
                    COMMIT LATENCY: 340ms
                         ↓
┌──────────────┐    ┌─────────┐    ┌───────┐    ┌──────────────┐    ┌────────────────┐
│ CockroachDB  │───→│Debezium │───→│ Kafka │───→│  PostgreSQL  │───→│  PostgreSQL    │
│ (trade exec) │    │  CDC    │    │       │    │  Primary     │    │  eu-west-1     │
│              │    │ +lag    │    │+consu-│    │  (us-east-1) │    │  async replica │
│ Real balance │    │         │    │mer lag│    │  +apply lag  │    │  +repl lag     │
│ = $600K      │    │         │    │       │    │              │    │  Balance=$2.4M │
└──────────────┘    └─────────┘    └───────┘    └──────────────┘    └───────┬────────┘
                                                                           │
                                                                    ┌──────▼──────┐
                                                                    │ EU Broker's │
                                                                    │ Margin Check│
                                                                    │ "Pass: $2.4M│
                                                                    │  available" │
                                                                    └─────────────┘
```

**Lag accumulation at each hop:**

| Hop | Source → Destination | Lag Source |
|-----|---------------------|-----------|
| 1 | CockroachDB commits | 340ms commit latency delays changefeed resolved timestamps |
| 2 | Debezium CDC | Changefeed entries queued behind slow commits; CDC consumer falls behind |
| 3 | Kafka → PG consumer | Consumer processing backlog (8M msgs/sec surge) |
| 4 | PostgreSQL primary apply | Logical replication apply on primary adds latency under load |
| 5 | Primary → eu-west-1 async replica | Standard async streaming replication lag, compounded by primary being under load |
| **Total** | | **~45 seconds of compounded staleness** |

### Where Should the Protection Exist?

**Layer: The margin check query routing layer (Account Service).**

The specific mechanism: **A staleness-bounded read guard.** Before executing a margin check against any replica, the service must:

1. **Check the replica's replication lag** (e.g., `pg_stat_replication.replay_lag` or `pg_last_xact_replay_timestamp()`)
2. **If lag exceeds a threshold** (e.g., 5 seconds for financial operations), **reject the read and either route to the primary or fail the margin check entirely**
3. Additionally, margin checks should carry a **"data freshness requirement"** — e.g., "balance must reflect all trades up to T-2s" — and the replica must prove it meets this requirement

**The specific prevention mechanism:**

```sql
-- Before margin check, verify replica freshness
SELECT CASE
  WHEN (now() - pg_last_xact_replay_timestamp()) > interval '5 seconds'
  THEN RAISE EXCEPTION 'Replica too stale for margin check'
END;
```

Or better — **route ALL margin checks to the primary** unconditionally. Margin validation is a **safety-critical write gate** and should never depend on eventually consistent data.

### Should EU Brokers Read from the eu-west-1 Replica at All?

**For margin checks: absolutely not.** Margin validation is a financial safety gate — it decides whether to accept or reject trades involving real money. This is analogous to the "medication allergy check" from the CDC lesson: you never serve safety-critical reads from an eventually consistent source.

**For non-critical reads** (e.g., portfolio display, historical order views): reading from the eu-west-1 replica is acceptable — these are latency-optimized, user-facing reads where eventual consistency is tolerable.

**The correct architecture:**
- **Read path for margin checks:** Always hit the PostgreSQL primary (us-east-1) or a synchronous standby. Accept the cross-region latency cost (~70ms us-east-1 ↔ eu-west-1) as the price of correctness.
- **Read path for display/non-critical:** eu-west-1 async replica is fine.
- **Fallback:** If the primary is unreachable, **fail closed** (reject the trade) rather than fall back to a stale replica.

---

## Q3: Immediate Mitigation Plan — 09:32:00 (10 pts)

### Priority 1: Stop the Financial Bleeding (09:32:00 – 09:33:00)

**Action 1A: Halt margin checks on stale replicas**

```sql
-- On eu-west-1 PostgreSQL replica: block all margin-check queries
ALTER SYSTEM SET default_transaction_read_only = on;
SELECT pg_reload_conf();
```

- Or at the application layer: **set a feature flag** to route all margin checks to the us-east-1 primary
- **Fixes:** Prevents additional unauthorized trades from stale data
- **Does NOT fix:** Existing $2.1M trade already placed; doesn't fix latency or throughput
- **Verify before executing:** Confirm you can reach the eu-west-1 replica (it's PostgreSQL in eu-west-1, not affected by the CockroachDB port block). Confirm US-east-1 primary can handle the additional margin-check load (it may not — see Action 2)
- **If primary can't handle load:** Implement a **circuit breaker** — fail closed on margin checks (reject trades) rather than approving on stale data

**Action 1B: Reverse the $2.1M trade if possible**

- Contact the exchange's trade operations team to **halt/flag the $2.1M trade** for review
- If within the exchange's error trade window, initiate a **bust (trade cancellation)**
- This is a manual/process action, not a technical one

### Priority 2: Revert the Root Cause (09:33:00 – 09:34:00)

**Action 2: Revert the firewall rule**

```bash
# Exact command depends on the firewall/transit gateway tooling
# AWS Transit Gateway example:
aws ec2 revoke-security-group-ingress \
  --group-id <tgw-sg-id> \
  --protocol tcp \
  --port 26257-26259 \
  --source <eu-west-1-cidr>

# Or: roll back the firewall change via the change management system
```

- **Fixes:** Restores CockroachDB us-east-1 ↔ eu-west-1 Raft communication; stops the leaseholder storm at its source
- **Does NOT fix:** The 8,000 in-flight leaseholder transfers; the current PgBouncer saturation; the existing retry storm
- **Verify before executing:** Confirm the *exact* rule that was changed (don't blindly open all ports). Verify with the network engineer what was changed. Test with a targeted connectivity check (`nc -zv <eu-west-1-crdb-node> 26257`) after the revert.
- **Can you execute this?** Yes — this is a network-layer change, independent of CockroachDB's state. But coordinate with the network engineer who made the change.

### Priority 3: Stop the Retry Amplification (09:34:00 – 09:35:00)

**Action 3: Activate API gateway rate limiting / shed load**

```yaml
# Tighten per-broker rate limits at the API gateway
rate_limit_per_broker: 5000  # Halve from 10,000 to 5,000
# Enable retry budget / circuit breaker
circuit_breaker:
  error_threshold: 50%
  cooldown: 30s
```

- **Fixes:** Reduces traffic from 340K → ~120K req/sec; breaks the retry amplification feedback loop
- **Does NOT fix:** Underlying latency or staleness; brokers will see rejected requests
- **Verify before executing:** Ensure rate limiting won't reject legitimate high-priority orders. If possible, prioritize by order type (market orders > limit orders) rather than blanket throttling.

### Priority 4: Stabilize CockroachDB (09:35:00 – 09:37:00)

**Action 4: Pause CockroachDB leaseholder rebalancing**

```sql
-- CockroachDB SQL:
SET CLUSTER SETTING kv.allocator.load_based_rebalancing = 'off';
-- Also dampen lease transfer rate:
SET CLUSTER SETTING kv.allocator.lease_rebalance_threshold = 1.0;
```

- **Fixes:** Stops new leaseholder transfers from being initiated; allows the current 8,000 transfers to complete without new ones piling on; lets the Raft proposal pipeline drain
- **Does NOT fix:** The ~8,000 transfers already in flight (they must complete); doesn't immediately drop latency from 340ms
- **Verify before executing:** This is safe — it only pauses *future* rebalancing. Existing ranges will continue serving from their current leaseholders. After the firewall is reverted (Action 2), eu-west-1 communication is restored, so the original leaseholder placement becomes valid again.
- **Important:** Re-enable rebalancing after the incident stabilizes.

### Priority 5: Relieve PostgreSQL (09:37:00 – 09:38:00)

**Action 5: Increase PgBouncer pool and shed non-critical queries**

```ini
# pgbouncer.ini
max_client_conn = 10000   # Allow more client queueing
default_pool_size = 100    # Increase from current if lower
max_db_connections = 450   # Increase from 300 (verify PG max_connections allows this)
```

- Additionally: **shed non-critical queries** — temporarily disable or deprioritize non-margin queries (portfolio display, reporting) at the application layer
- **Fixes:** Allows more margin checks to reach PostgreSQL; reduces queue depth
- **Does NOT fix:** The fundamental load problem (120K queries/sec); need the retry storm (Action 3) to subside first
- **Verify before executing:** Check `max_connections` on PostgreSQL primary (`SHOW max_connections;`). PgBouncer's `max_db_connections` must not exceed PostgreSQL's limit minus reserved connections.

### Priority 6: Stabilize Ancillary Systems (09:38:00 – 09:40:00)

**Action 6A: Dampen etcd write load from Consul flapping**

```bash
# Increase Consul health check intervals to reduce flapping
consul reload -config-dir=/etc/consul.d/  # with updated check intervals
# Or: temporarily increase deregister_critical_service_after
```

- **Fixes:** Reduces etcd write load from 3× to ~1×
- **Verify:** Confirm etcd is not near its storage quota (`etcdctl endpoint status`)

**Action 6B: Address Redis hot key (AAPL)**

```bash
# Enable Redis read replicas for the AAPL master's slot
# Or: implement client-side local caching for AAPL order book with 100ms TTL
# Short-term: add a Redis replica specifically for AAPL reads
redis-cli --cluster add-node <new-replica-ip>:6379 <aapl-master-ip>:6379 --cluster-slave
```

- **Fixes:** Distributes AAPL read load across replicas
- **Does NOT fix:** The write load on that master (but writes are far fewer than reads)

---

## Q4: The CockroachDB Leaseholder Storm (10 pts)

### Why UNAFFECTED Ranges Hit 340ms

**The shared resource: the per-node Raft proposal pipeline (Raft scheduler / store-level proposal queue).**

In CockroachDB's Multi-Raft implementation, each node hosts many ranges (e.g., ~2,500 leaseholders per node). While each range has its own independent Raft group logically, they share **physical resources on the node**:

1. **Raft scheduler goroutine pool:** A bounded pool of goroutines processes Raft ticks, proposals, and messages for ALL ranges on that node. 8,000 simultaneous leadership transfers flood this pool with `MsgVote`, `MsgVoteResp`, `MsgTimeoutNow`, and `MsgApp` messages.

2. **Raft proposal queue (per-store):** Proposals from all ranges on a store are batched and processed through a shared pipeline. Leadership transfers generate proposal bursts (the new leader must re-propose any pending entries). 8,000 ranges simultaneously re-proposing entries saturate this queue.

3. **WAL write batching:** Raft log entries are written to the store's shared WAL. Leadership elections generate log entries (term changes, vote records) that compete with normal range proposals for WAL write bandwidth.

The result: a normal range's proposal (e.g., a simple trade write) enters the shared proposal queue and waits behind thousands of election-related Raft messages. The proposal-to-commit latency balloons from 4ms to 340ms — not because the range itself has any issue, but because the **node's shared Raft processing infrastructure is saturated**.

### Should CockroachDB Have Attempted These Transfers?

**No.** The rebalancer should NOT have initiated 8,000 leaseholder transfers simultaneously during an opening bell surge. The problems:

1. **Wrong timing:** The system was already under 15× peak load. Adding 8,000 leadership transfers on top of 180K trades/sec turns a partial degradation (some ranges slower) into a **total degradation** (all ranges slower).

2. **Unnecessary urgency:** The affected ranges still had quorum (eu-west-1 + us-west-2 = 2/3). They were functional, just suboptimal. The rebalancer treated a **performance optimization** as an **urgent action**, when it should have deferred.

3. **No rate limiting:** The rebalancer didn't throttle the transfer rate. Moving 8,000 ranges simultaneously is catastrophically different from moving them in batches of 50 over several minutes.

### Configuration to Prevent This

```sql
-- 1. Disable load-based rebalancing entirely during critical periods
--    (use a scheduled job or operational runbook)
SET CLUSTER SETTING kv.allocator.load_based_rebalancing = 'off';

-- 2. Rate-limit lease transfers to prevent storms
SET CLUSTER SETTING kv.allocator.lease_rebalance_threshold = 0.3;
--    (higher threshold = less sensitive to imbalance, fewer transfers)

-- 3. Set maximum concurrent lease transfers per node
SET CLUSTER SETTING kv.snapshot_rebalance.max_rate = '8 MiB';
--    (limits the rate of range data movement)

-- 4. CockroachDB ≥ v23.1: Use admission control to prioritize
--    foreground traffic over rebalancing
SET CLUSTER SETTING admission.kv.enabled = true;
SET CLUSTER SETTING admission.kv.bulk_penalty_multiplier = 100;
```

**The ideal design:**

| Mechanism | Purpose |
|-----------|---------|
| **Load-awareness gate** | Rebalancer checks current node QPS/latency before initiating transfers. If QPS > 80% of peak capacity, defer all non-critical rebalancing. |
| **Transfer rate limiter** | Maximum N concurrent leaseholder transfers per node (e.g., 10). Remaining transfers queue and execute as earlier ones complete. |
| **Priority inversion protection** | Raft scheduler prioritizes normal proposal processing over election/transfer messages. Leadership changes are processed in a lower-priority queue. |
| **Scheduled maintenance windows** | For known load patterns (like market open), pre-configure a "quiet period" where the rebalancer is automatically suppressed: `SET CLUSTER SETTING kv.allocator.load_based_rebalancing = 'off';` from 09:25–09:35 daily, re-enabled automatically after. |

---

## Q5: Post-Mortem Architecture Changes (10 pts)

### Defense-in-Depth: Three Layers

The financial exposure ($2.1M unauthorized margin trade) requires multiple independent layers of defense. Each layer must independently prevent the financial harm even if all other layers fail.

---

### L1 — Eliminate Stale Reads on Safety-Critical Path

**Change: Route ALL margin checks to the PostgreSQL primary (or synchronous standby), regardless of broker geography.**

| Attribute | Detail |
|-----------|--------|
| **Cascade link broken** | L9 → L10 (stale replica read → unauthorized trade) |
| **Implementation** | Modify the Account Service to use a **read/write splitting policy**: margin checks and balance holds always go to the primary connection pool; display queries can use regional replicas |
| **Cross-region latency cost** | EU brokers incur ~70ms additional latency for margin checks (us-east-1 round trip). This is acceptable — correctness over speed for financial safety gates |
| **If this layer fails** | (e.g., primary is unreachable) → **Fail closed**: reject all trades that can't be margin-validated. Never fall back to a stale replica for margin checks |

---

### L2 — Staleness-Bounded Replica Reads with Circuit Breaker

**Change: If any replica IS used for important reads, enforce a maximum replication lag threshold.**

| Attribute | Detail |
|-----------|--------|
| **Cascade link broken** | L9 (stale data reaches the application) |
| **Implementation** | Add a **replication lag monitor** to the Account Service. Before any replica query: check `pg_last_xact_replay_timestamp()`. If lag > 5 seconds → circuit breaker trips → route to primary or reject |
| **Code** | `SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())) < 5 AS is_fresh;` |
| **If this layer fails** | (e.g., lag monitor crashes, returns stale "is_fresh=true") → L1 should be the primary path anyway; this is a secondary guard. L3 (below) catches it. |

---

### L3 — Double-Entry Margin Validation (Application-Level Safety Gate)

**Change: Implement a two-phase margin check — pre-check + post-check with hold.**

| Attribute | Detail |
|-----------|--------|
| **Cascade link broken** | L10 (unauthorized trade accepted) |
| **Implementation** | **Phase 1:** Place a **margin hold** (like a credit card auth) on the primary before accepting the order. This atomically decrements available margin. **Phase 2:** After trade execution, convert the hold to a final debit. If the hold fails (insufficient margin), the trade is rejected *before* execution. |
| **Why this works** | Even if a stale read incorrectly shows $2.4M available, the **hold write** goes to the primary, which has the true balance of $600K. The hold for $2.1M fails because $2.1M > $600K. The write path is always consistent. |
| **If this layer fails** | (e.g., primary is down for holds) → Fail closed: no trade execution without a confirmed margin hold |

---

### L4 — CDC-Based Real-Time Margin Cache (Replace Replica Reads Entirely)

**Change: Replace PostgreSQL async replica reads with a CDC-powered Redis margin cache with sequence validation.**

| Attribute | Detail |
|-----------|--------|
| **Cascade link broken** | L9 (removes the async replica from the margin-check path entirely) |
| **Implementation** | CockroachDB → Debezium CDC → Kafka → Redis margin cache (per-account). Each cache entry carries a **sequence number** (from the CDC event's LSN). The margin check reads from Redis and validates the sequence number is within an acceptable window. If CDC lag causes the sequence to fall behind, the cache entry is **treated as invalid** → route to primary. |
| **Advantage over async replica** | The staleness is explicitly tracked (sequence numbers), not implicitly unknown. The system can make informed routing decisions. |
| **If this layer fails** | (e.g., CDC pipeline breaks) → Falls back to L1 (primary reads) and L3 (margin holds) |

---

### L5 — Organizational / Process Change: Firewall Change Freeze During Market Hours

**Change: Implement a network change freeze window during market hours (09:00–16:30 ET).**

| Attribute | Detail |
|-----------|--------|
| **Cascade link broken** | L1 (the root cause — the firewall change itself) |
| **Implementation** | **Policy:** No network infrastructure changes to production during market hours without VP-level approval + SRE co-sign. **Technical enforcement:** CI/CD pipeline for network changes rejects deployments during freeze windows. Infrastructure-as-code (Terraform) applies a `prevent_destroy` lifecycle rule during market hours. |
| **Additional process controls** | All firewall changes require **peer review** + **automated connectivity validation** (a pre-deploy check that verifies CockroachDB inter-node connectivity on ports 26257-26259 between all region pairs). A canary check post-deploy that runs a CockroachDB cross-region write and verifies success. |
| **If this layer fails** | (e.g., engineer bypasses the freeze) → L1 through L4 (technical controls) prevent financial harm even if the network change occurs |

---

### Summary: Defense-in-Depth Matrix

| Layer | What It Prevents | Type | Fails To |
|-------|-----------------|------|----------|
| **L1** — Primary-only margin reads | Stale data reaching margin checks | Technical (routing) | L2, L3 |
| **L2** — Lag-bounded replica guard | Stale replicas being used silently | Technical (monitoring) | L1, L3 |
| **L3** — Two-phase margin hold | Unauthorized trade execution | Technical (application) | Fail closed |
| **L4** — CDC margin cache with sequence validation | Async replica dependency | Technical (architecture) | L1, L3 |
| **L5** — Market-hours change freeze | Root cause from occurring | Organizational (process) | L1–L4 |

> **Key Principle:** No single technical failure should be able to cause financial exposure. The margin check is a **safety-critical gate** — it must be treated with the same rigor as a medication allergy check in healthcare. The system must **fail closed** (reject trades) rather than **fail open** (accept trades on uncertain data).
