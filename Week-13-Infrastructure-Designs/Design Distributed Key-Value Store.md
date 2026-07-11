# Design Distributed Key-Value Store
> Week 13 — Infrastructure System Design | Dynamo-style | Consistent Hashing (Week 3) | Replication & Quorum (Week 4)
> **Interview framing:** This module teaches you to *design* a production-grade distributed KV store in a 45-minute interview — not just explain DynamoDB features.

---

## Learning Objectives
```
╔═════════════════════════════════════════════════════════════════════════╗
║ AFTER THIS MODULE, YOU WILL BE ABLE TO:                                 ║
╟─────────────────────────────────────────────────────────────────────────╢
║ 1. Run a 45-minute system design interview for a distributed KV store   ║
║ 2. Choose AP vs CP per feature using PACELC, not slogans                ║
║ 3. Design partition placement with consistent hashing + vnodes          ║
║ 4. Specify replication (RF, CL, R/W quorums) with exact math            ║
║ 5. Explain conflict resolution: LWW, vector clocks, CRDTs               ║
║ 6. Design anti-entropy, hinted handoff, and failure detection           ║
║ 7. Map your design to DynamoDB, Cassandra, Riak, and Redis Cluster      ║
║ 8. Diagnose hot partitions, quorum failures, and split-brain in prod    ║
╚═════════════════════════════════════════════════════════════════════════╝
```
---

## Section 2: Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "KV store = Redis at scale"                        ║
╟─────────────────────────────────────────────────────────────────────╢
║ WRONG. Redis Cluster is CP-ish, in-memory, slot-based.              ║
║ Dynamo-style stores are AP-first, disk-backed, leaderless quorum.   ║
║ Different failure modes, different interview answers.               ║
╚═════════════════════════════════════════════════════════════════════╝



╔═══════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #2: "Strong consistency everywhere"                  ║
╟───────────────────────────────────────────────────────────────────╢
║ WRONG. Amazon Dynamo explicitly chose availability + partition    ║
║ tolerance with eventual consistency. Strong consistency costs     ║
║ latency and availability during partitions. Pick per operation.   ║
╚═══════════════════════════════════════════════════════════════════╝



╔═══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #3: "Consistent hashing = even load"             ║
╟───────────────────────────────────────────────────────────────╢
║ WRONG (Week 3). Consistent hashing distributes KEYS evenly.   ║
║ A single hot key still lands on ONE partition. You need       ║
║ key splitting, caching, or write-behind for hot keys.         ║
╚═══════════════════════════════════════════════════════════════╝



╔═══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #4: "RF=3 means triple storage cost only"        ║
╟───────────────────────────────────────────────────────────────╢
║ WRONG. RF=3 also means 3x write amplification on every put,   ║
║ 3x repair traffic, 3x anti-entropy work. Capacity math must   ║
║ include replication factor in write bandwidth AND disk.       ║
╚═══════════════════════════════════════════════════════════════╝



╔══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #5: "Quorum guarantees no conflicts"            ║
╟──────────────────────────────────────────────────────────────╢
║ WRONG (Week 4). R+W>N prevents stale reads but concurrent    ║
║ writes to the same key still conflict. You need version      ║
║ vectors or application-level merge.                          ║
╚══════════════════════════════════════════════════════════════╝
```
---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

```
THE SYSTEM DESIGN INTERVIEW OPENING (45 MINUTES TOTAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Minutes 0-5:   CLARIFY requirements (functional + non-functional)
  Minutes 5-10:  ESTIMATE scale (QPS, storage, bandwidth)
  Minutes 10-15: HIGH-LEVEL design (boxes and arrows — get buy-in)
  Minutes 15-35: DEEP DIVE (2-3 areas interviewer picks)
  Minutes 35-42: BOTTLENECKS, failure modes, tradeoffs
  Minutes 42-45: SUMMARY and extensions

  RULE: Never jump to micro-optimizations before the interviewer
  agrees on the high-level shape. A beautiful consistent-hashing
  explanation that solves the wrong problem scores zero.



REQUIREMENTS CLARIFICATION CHECKLIST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  FUNCTIONAL (what the system DOES):
    □ CRUD operations supported?
    □ Key size limits? Value size limits?
    □ TTL / expiration?
    □ Conditional writes (CAS)?
    □ Range queries or point lookups only?
    □ Multi-key transactions?

  NON-FUNCTIONAL (how well it must work):
    □ Read/write ratio?
    □ Latency targets (p50, p99)?
    □ Durability (can we lose data on crash)?
    □ Consistency (stale reads acceptable?)
    □ Availability target (99.9%? 99.99%)?
    □ Geographic distribution?
    □ Multi-tenancy / isolation?

  OUT OF SCOPE (say explicitly):
    □ Authentication (assume handled upstream)
    □ Analytics / reporting (separate pipeline)
    □ Full-text search (different system)
```
### 3.1 — Canonical Prompt: "Design a Distributed Key-Value Store"

```
TYPICAL INTERVIEW PROMPT:
  "Design a distributed key-value store like DynamoDB or Cassandra.
   It should support get/put/delete by key, scale to billions of keys,
   and remain available during node failures."

YOUR FIRST RESPONSE (before any diagram):
  "Let me clarify requirements..."

  Questions you MUST ask:
    1. What consistency do reads need? (strong vs eventual)
    2. What's the read/write ratio?
    3. Max value size? (1 KB vs 1 MB changes everything)
    4. Do we need conditional writes / transactions?
    5. Multi-datacenter or single region?
    6. Durability: can we lose last 1 second of writes on crash?

  Default assumptions (state aloud if interviewer says "assume typical"):
    → Billions of keys, values up to 1 MB (but p99 << 10 KB)
    → High availability > strong consistency (AP bias)
    → 100:1 read:write ratio
    → Single-region initially, multi-DC as extension
    → No cross-key transactions
```
### 3.2 — Capacity Estimation

```
BACK-OF-ENVELOPE (say these numbers aloud in the interview):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Assumptions:
    → 500M daily active users
    → Each user: 10 reads/day, 1 write/day
    → Reads: 500M × 10 / 86400 ≈ 58K read QPS (peak 3× ≈ 175K)
    → Writes: 500M × 86400 ≈ 5.8K write QPS (peak ≈ 17K)

  Storage (10 year retention):
    → 500M users × 50 keys each = 25B keys
    → Avg value 2 KB → 25B × 2 KB = 50 TB raw
    → RF=3 → 150 TB replicated
    → With 30% overhead (WAL, indexes, compaction) → ~200 TB

  Bandwidth:
    → Reads: 175K × 2 KB = 350 MB/s egress
    → Writes: 17K × 2 KB = 34 MB/s ingress (× RF=3 replicas ≈ 100 MB/s internal)

  These numbers drive: shard count, node count, network design.
```
### 3.3 — High-Level Architecture

```
HIGH-LEVEL ARCHITECTURE (draw this first):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

                    ┌─────────────────┐
                    │  Load Balancer  │
                    │  (stateless)    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Coordinator│ │ Coordinator│ │ Coordinator│
        │  Node     │  │  Node     │  │  Node     │
        └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
         Consistent hash ring determines replica set
                             │
    ┌────────┬────────┬──────┴──────┬────────┬────────┐
    ▼        ▼        ▼             ▼        ▼        ▼
  ┌────┐  ┌────┐  ┌────┐       ┌────┐  ┌────┐  ┌────┐
  │ N1 │  │ N2 │  │ N3 │  ...  │ N98│  │ N99│  │N100│
  │disk│  │disk│  │disk│       │disk│  │disk│  │disk│
  └────┘  └────┘  └────┘       └────┘  └────┘  └────┘

  Coordinator responsibilities:
    → Hash key → find partition → find replica set (Week 3 ring)
    → Send read/write to replicas, wait for quorum (Week 4)
    → Merge versions on read if conflicts detected
    → ANY node can coordinate (leaderless at request level)

  Storage node responsibilities:
    → Persist key-value on local disk (LSM-tree or B-tree)
    → Participate in gossip (membership, failure detection)
    → Anti-entropy repair with peers
    → Stream writes to other replicas in the set
```
### 3.4 — Partitioning: Consistent Hashing (Week 3 Connection)

```
CONSISTENT HASHING RING (Week 3 — applied in interview):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  WHY NOT hash(key) % N?
    → Adding/removing 1 node remaps ~N/(N+1) of ALL keys
    → Cache stampede + mass data movement on every scale event
    → Week 3 proved: only ~1/N keys move with consistent hashing

  THE RING:
    → Hash space: 0 to 2^128 (MD5/SHA-1/Murmur3 token)
    → Each physical node gets V virtual nodes (vnodes)
    → Key's token = hash(key)
    → Owner = first vnode clockwise from key's token
    → RF=3: walk clockwise, collect 3 distinct physical nodes

  VNODE COUNT (say in interview):
    → Default: 256 vnodes per physical node (Cassandra default)
    → More vnodes → better load balance when nodes differ in capacity
    → Fewer vnodes → less metadata overhead
    → Rule of thumb: vnodes ≥ 10 × node_count for even distribution

  DATA MOVEMENT ON NODE ADD:
    → Only keys between predecessor vnode and new vnode move
    → ~1/N of data — bounded, predictable
    → Background streaming — don't block writes during migration

  INTERVIEW TIP:
    Draw the ring. Mark 3 vnodes for Node A. Show key K landing
    between vnode2 and vnode3. Name the 3 replicas. This 60-second
    diagram separates senior from junior candidates.
```
### 3.5 — Replication & Quorum (Week 4 Connection)

```
LEADERLESS REPLICATION WITH QUORUM (Week 4):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Replication Factor (RF): number of copies per key
  Consistency Level (CL): how many replicas must respond

  N = RF (typically 3)
  R = read quorum (replicas contacted on read)
  W = write quorum (replicas that must ack write)

  THE GOLDEN RULE: R + W > N  →  strong read consistency
                   R + W ≤ N  →  possible stale reads

  Common configurations (N=3):
    ┌─────────┬────┬────┬───────────────────────────────────────┐
    │ Profile │ R  │ W  │ Behavior                              │
    ├─────────┼────┼────┼───────────────────────────────────────┤
    │ Fast W  │ 1  │ 1  │ AP, eventual, highest availability    │
    │ Balanced│ 2  │ 2  │ R+W=4>3, strong per-key consistency   │
    │ Fast R  │ 1  │ 2  │ Write-durable, stale reads possible   │
    │ Strong  │ 3  │ 3  │ Linearizable per key (highest latency)│
    └─────────┴────┴────┴───────────────────────────────────────┘

  WRITE PATH (coordinator):
    1. Hash key → identify N replicas
    2. Send write to ALL N replicas in parallel
    3. Wait for W acknowledgments
    4. Return success to client (or timeout/fail)

  READ PATH (coordinator):
    1. Hash key → identify N replicas
    2. Send read to ALL N replicas in parallel
    3. Wait for R responses
    4. Return highest version (vector clock / timestamp)
    5. If versions diverge → read repair (push latest to stale replicas)

  SLoppy QUORUM + HINTED HANDOFF (Dynamo paper):
    → If primary replica down, write goes to alternate node
    → Alternate stores HINT: "deliver to N3 when it returns"
    → Maintains availability during failure
    → Tradeoff: temporary inconsistency until hint delivered
```
### 3.6 — Data Model & Versioning

```
VERSIONING AND CONFLICT RESOLUTION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Every write carries a version:
    Option A: Hybrid Logical Clock (HLC) timestamp
    Option B: Vector clock (client_id, counter) per replica
    Option C: Dotted version vector (Cassandra 4.0+)

  READ returns:
    → Single version if all R replicas agree
    → Multiple versions if concurrent writes detected (siblings)

  RESOLUTION STRATEGIES:
    1. Last-Writer-Wins (LWW): pick highest timestamp
       → Simple, loses data silently on clock skew
       → DynamoDB default for conditional conflicts

    2. Application merge: return all siblings to client
       → Shopping cart: union of items
       → Requires idempotent merge function

    3. CRDTs (Week 8 extension): automatic commutative merge
       → Counters, sets, registers with proven merge semantics

  INTERVIEW ANSWER:
    "For a shopping cart, I'd return siblings to the application
     and merge with set-union semantics. For user profile name,
     LWW with server-side HLC is acceptable. I'd never use LWW
     for financial balances."
```
### 3.7 — Storage Engine on Each Node

```
PER-NODE STORAGE (pick one, justify in interview):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  LSM-TREE (Cassandra, RocksDB, DynamoDB):
    → Sequential writes to memtable + WAL
    → Periodic flush to immutable SSTables
    → Background compaction merges SSTables
    → Excellent write throughput
    → Read amplification grows with SSTable count
    → Bloom filters reduce unnecessary disk reads

  B-TREE (PostgreSQL-style, less common at Dynamo scale):
    → In-place page updates
    → Lower read amplification
    → Random write I/O — harder at high write QPS

  INTERVIEW DEFAULT: LSM-tree
    "High write QPS + large values + sequential disk I/O
     favors LSM. I'd use RocksDB as embedded engine per node."

  DISK LAYOUT PER KEY:
    key → partition_id → (version, value, tombstone_flag, ttl)
    Tombstones: delete marker, not immediate purge
    TTL: lazy expiration on read or compaction
```
### 3.8 — API Design

```
CLIENT API (REST or gRPC — state your choice):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PUT /v1/keys/{key}
    Body: { "value": "<base64>", "version": "<optional>" }
    Headers: Consistency-Level: QUORUM
    Response: 201 { "version": "vc:3" }

  GET /v1/keys/{key}
    Query: ?consistency=QUORUM
    Response: 200 { "value": "...", "version": "vc:3" }
    Response: 200 { "siblings": [...] }  // if conflict

  DELETE /v1/keys/{key}
    Writes tombstone with new version

  Conditional write (compare-and-swap):
    PUT with If-Version: vc:2 → 412 if version mismatch

  Batch (optional extension):
    GET /v1/keys?keys=k1,k2,k3
    → Coordinator fan-out, parallel quorum reads
    → Must be same partition for atomic batch (DynamoDB constraint)
```
### 3.9 — Gossip Protocol & Failure Detection

```
GOSSIP MEMBERSHIP (SWIM / Cassandra gossip):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Each node maintains a membership list:
    node_id, heartbeat_generation, status (UP/SUSPECT/DOWN)

  Every T seconds (default 1s):
    → Pick random peer
    → Exchange membership state
    → Increment heartbeat generation if alive
    → Mark nodes as SUSPECT if no heartbeat for X seconds
    → Mark DOWN after Y suspect rounds (phi accrual in Cassandra)

  WHY GOSSIP:
    → O(log N) convergence, no central coordinator
    → Survives partition: each side may have different view
    → Application must handle split views (quorum prevents writes
      to minority partition when W > N/2)

  INTERVIEW EXTENSION:
    "For faster failure detection, I'd add health checks from
     coordinators on failed reads — don't wait for gossip alone."
### 3.10 — Anti-Entropy & Merkle Trees

```
ANTI-ENTOMY REPAIR:
━━━━━━━━━━━━━━━━━━━

  Problem: hinted handoff + temporary failures leave divergence

  Naive: compare every key between replicas → O(keys) bandwidth

  Merkle tree approach (Dynamo paper):
    → Hash keyspace into buckets
    → Build Merkle tree per bucket per replica
    → Compare tree roots → drill into differing branches
    → Sync only divergent ranges

  Schedule: continuous background (1% of keyspace/day minimum)
  Production: Cassandra nodetool repair, DynamoDB auto-repair

  INTERVIEW:
    "Repairs are mandatory, not optional. Without anti-entropy,
     RF=3 is wishful thinking after 6 months of node churn."
### 3.11 — Multi-Datacenter Replication

```
MULTI-DC (extension question — common in senior interviews):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Network Partition Between DCs is NORMAL, not exceptional.

  Strategies:
    1. LOCAL_QUORUM: R/W within local DC only
       → Lower latency, possible cross-DC staleness

    2. EACH_QUORUM: W in each DC independently
       → Higher durability across DC failure

    3. Async cross-DC replication stream
       → Primary DC accepts writes, streams to secondary
       → RPO > 0 for cross-DC reads

  PACELC: during partition, choose A; else choose latency (L)
    → Dynamo-style: AP during partition, CL tunable otherwise
### 3.12 — DynamoDB vs Cassandra vs Riak (Real Systems)

```
REAL SYSTEM MAPPING:
━━━━━━━━━━━━━━━━━━━━

  DynamoDB (AWS managed):
    → Partition key + optional sort key
    → Single-digit ms at any scale
    → Strongly consistent reads optional (2× cost)
    → On-demand or provisioned capacity
    → Not open source — interview: "I'd reference Dynamo paper"

  Cassandra (LSM, CQL, tunable consistency):
    → Wide rows, partition key determines node
    → Operational complexity: compaction, repair, tombstones
    → Used: Netflix, Apple, Discord messaging metadata

  Riak (Dynamo faithful, convergent CRDTs):
    → Simpler ops than Cassandra, smaller community
    → Basho legacy — know the design, not necessarily deploy

  Redis Cluster (contrast — NOT Dynamo-style):
    → 16384 hash slots, CP failover with majority
    → In-memory, not your answer for "billions of keys on disk"

---

## Concrete Examples
### Example 1: Session Store for 500M Users

```
REQUIREMENTS:
  → get(session_id), put(session_id, user_data), TTL 24h
  → 99.99% availability, stale session OK for 30 seconds
  → 50 KB average session blob

DESIGN CHOICES:
  → Key: session_id (UUID, well distributed — no hot keys)
  → RF=3, R=1, W=2 (fast reads, durable writes)
  → TTL enforced at compaction
  → 500M active sessions × 50 KB × RF3 = 75 TB

WHY NOT Redis:
  → 75 TB RAM is expensive; disk-backed LSM is cost-effective
  → Session loss on Redis failover unacceptable at this scale
### Example 2: User Profile Store (Read-Heavy)

```
REQUIREMENTS:
  → get(user_id), put(user_id, profile_json)
  → 1000:1 read:write, p99 read < 10ms
  → Eventual consistency OK

DESIGN:
  → Cache layer (Week 2): CDN/Redis in front for hot profiles
  → KV backend: RF=3, R=1, W=2
  → Read repair on cache miss path
  → Celebrity users: replicate hot keys to extra nodes (manual override)
### Example 3: Shopping Cart (Conflict-Prone)

```
REQUIREMENTS:
  → Add/remove items from multiple devices concurrently
  → Must not lose items (never LWW the whole cart)

DESIGN:
  → Key: cart_id
  → Value: map of item_id → quantity
  → Vector clocks on every mutation
  → On sibling conflict: union merge at read time
  → Or: CRDT OR-Set for cart items

INTERVIEW GOLD:
  "This is THE example that proves you understand Dynamo
   vs naive LWW."
### Example 4: URL Shortener Backend

```
  Key: short_code (6 chars)
  Value: { long_url, created_at, owner_id }

  Hot key risk: popular short links (e.g. bit.ly/xyz)
  Mitigation:
    → Read replicas + aggressive edge cache
    → Separate counter service for click analytics (don't write
      to KV on every click)

  RF=3, N=3, R=2, W=2 for strong read-after-write on create
### Example 5: Feature Flag Store

```
  Small values, high read QPS, low write QPS
  → Consider dedicated config store (Section 3 sibling module)
  → If KV: local cache on app servers with gossip pub/sub for updates
  → Version every flag for rollback

---

### Staff

## Production Patterns
```
HOW TEAMS ACTUALLY SHIP DYNAMO-STYLE STORES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. START WITH MANAGED (DynamoDB, Cosmos DB)
     → Only self-host Cassandra if you have 3+ dedicated DBAs
     → Interview: "Production I'd use DynamoDB; design follows paper"

  2. CAPACITY PLANNING
     → Provision per partition throughput (DynamoDB RCU/WCU)
     → Monitor hot partitions (ConsumedReadCapacity skew)
     → Auto-split when partition exceeds threshold

  3. SCHEMA DESIGN = PARTITION DESIGN
     → Partition key determines node AND hot spot risk
     → Composite keys: (user_id, timestamp) for time-range queries
     → Avoid monotonically increasing partition keys (write hotspots)

  4. OPERATIONAL RUNBOOKS
     → Node replacement: bootstrap + repair before decommission
     → Compaction strategy matches access pattern (STCS vs TWCS)
     → gc_grace_seconds > max repair interval (Cassandra)

  5. CLIENT DRIVERS
     → Smart clients know topology (gossip metadata)
     → Exponential backoff on coordinator timeout
     → Idempotent writes with client-generated UUID
#### Production Pattern 1: Rolling upgrades without quorum loss

```
  Context: Rolling upgrades without quorum loss in a 100-node Cassandra cluster serving 200K QPS.

  Implementation notes:
    → Monitor p99 coordinator latency during rollout
    → Verify RF satisfaction after each node join
    → Run repair verification before declaring upgrade complete
    → Document rollback: snapshot IDs, schema version, token ranges

  AWS equivalent: DynamoDB point-in-time recovery, global tables
  for multi-region; MSK not applicable here.
```
#### Production Pattern 2: Backup: incremental SSTable snapshots to S3

```
  Context: Backup: incremental SSTable snapshots to S3 in a 100-node Cassandra cluster serving 200K QPS.

  Implementation notes:
    → Monitor p99 coordinator latency during rollout
    → Verify RF satisfaction after each node join
    → Run repair verification before declaring upgrade complete
    → Document rollback: snapshot IDs, schema version, token ranges

  AWS equivalent: DynamoDB point-in-time recovery, global tables
  for multi-region; MSK not applicable here.
```
#### Production Pattern 3: Encryption at rest per node (KMS)

```
  Context: Encryption at rest per node (KMS) in a 100-node Cassandra cluster serving 200K QPS.

  Implementation notes:
    → Monitor p99 coordinator latency during rollout
    → Verify RF satisfaction after each node join
    → Run repair verification before declaring upgrade complete
    → Document rollback: snapshot IDs, schema version, token ranges

  AWS equivalent: DynamoDB point-in-time recovery, global tables
  for multi-region; MSK not applicable here.
```
#### Production Pattern 4: Network: separate replication VLAN

```
  Context: Network: separate replication VLAN in a 100-node Cassandra cluster serving 200K QPS.

  Implementation notes:
    → Monitor p99 coordinator latency during rollout
    → Verify RF satisfaction after each node join
    → Run repair verification before declaring upgrade complete
    → Document rollback: snapshot IDs, schema version, token ranges

  AWS equivalent: DynamoDB point-in-time recovery, global tables
  for multi-region; MSK not applicable here.
```
#### Production Pattern 5: Rate limiting per tenant at coordinator

```
  Context: Rate limiting per tenant at coordinator in a 100-node Cassandra cluster serving 200K QPS.

  Implementation notes:
    → Monitor p99 coordinator latency during rollout
    → Verify RF satisfaction after each node join
    → Run repair verification before declaring upgrade complete
    → Document rollback: snapshot IDs, schema version, token ranges

  AWS equivalent: DynamoDB point-in-time recovery, global tables
  for multi-region; MSK not applicable here.
```
#### Production Pattern 6: Dark reads for validation during migration

```
  Context: Dark reads for validation during migration in a 100-node Cassandra cluster serving 200K QPS.

  Implementation notes:
    → Monitor p99 coordinator latency during rollout
    → Verify RF satisfaction after each node join
    → Run repair verification before declaring upgrade complete
    → Document rollback: snapshot IDs, schema version, token ranges

  AWS equivalent: DynamoDB point-in-time recovery, global tables
  for multi-region; MSK not applicable here.
```
#### Production Pattern 7: Dual-write migration from legacy DB

```
  Context: Dual-write migration from legacy DB in a 100-node Cassandra cluster serving 200K QPS.

  Implementation notes:
    → Monitor p99 coordinator latency during rollout
    → Verify RF satisfaction after each node join
    → Run repair verification before declaring upgrade complete
    → Document rollback: snapshot IDs, schema version, token ranges

  AWS equivalent: DynamoDB point-in-time recovery, global tables
  for multi-region; MSK not applicable here.
```
#### Production Pattern 8: Partition autoscaling triggers

```
  Context: Partition autoscaling triggers in a 100-node Cassandra cluster serving 200K QPS.

  Implementation notes:
    → Monitor p99 coordinator latency during rollout
    → Verify RF satisfaction after each node join
    → Run repair verification before declaring upgrade complete
    → Document rollback: snapshot IDs, schema version, token ranges

  AWS equivalent: DynamoDB point-in-time recovery, global tables
  for multi-region; MSK not applicable here.
```

---

## Failure Modes
### Failure: Hot Partition / Hot Key

```
SYMPTOM: One node at 100% CPU, others at 20%
CAUSE: Celebrity key or sequential write pattern
FIX: Key splitting (key#0, key#1), local cache, async aggregation
WEEK 3 LINK: Consistent hashing does NOT fix single-key hotspots
### Failure: Quorum Unavailable

```
SYMPTOM: Writes fail with UnavailableException
CAUSE: W replicas down, or network partition isolates coordinator
FIX: Lower CL temporarily (ops decision), add capacity, fix network
MATH: N=3, W=3 requires ALL nodes — avoid W=N in prod
### Failure: Hinted Handoff Storm

```
SYMPTOM: Massive internode traffic after node recovery
CAUSE: Thousands of hints delivered simultaneously
FIX: Rate-limit hint delivery, stagger node restarts
### Failure: Tombstone Accumulation

```
SYMPTOM: Reads slow down, disk fills, queries timeout
CAUSE: Heavy deletes without compaction; gc_grace too high
FIX: TWCS compaction, lower gc_grace after repair, avoid delete-heavy
### Failure: Clock Skew / LWW Data Loss

```
SYMPTOM: "My write disappeared"
CAUSE: NTP drift, LWW picked wrong version
FIX: HLC, vector clocks, never LWW for merge-sensitive data
### Failure: Split Brain (Minority Partition)

```
SYMPTOM: Two subsets both accepting writes
CAUSE: W ≤ N/2 or misconfigured CL during partition
FIX: W > N/2 (majority), fencing stale coordinators
WEEK 4 LINK: Quorum majority is split-brain prevention
### Failure: Cascade Failure on Node Loss

```
SYMPTOM: One node dies → others overload → more die
CAUSE: Hinted handoff + read repair redirect all traffic to survivors
FIX: Capacity headroom 30%, circuit breakers on coordinators
### Failure: Merkle Repair During Peak

```
SYMPTOM: Latency spike every night
CAUSE: Full repair competing with production I/O
FIX: Incremental repair, throttle bandwidth, off-peak scheduling

---

## SRE Diagnostic Toolkit
```
CASSANDRA / SELF-HOSTED DIAGNOSTICS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  nodetool status          → cluster membership, load per node
  nodetool tpstats         → thread pool backpressure
  nodetool tablestats      → SSTable count, tombstones, latency
  nodetool cfhistograms    → read/write latency percentiles
  nodetool netstats        → streaming, hints pending
  nodetool repair          → manual anti-entropy trigger

  JMX / Metrics:
    → org.apache.cassandra.metrics.Table.ReadLatency.p99
    → org.apache.cassandra.metrics.Compaction.PendingTasks
    → HintedHandoffManager.TotalHints

DYNAMODB (AWS):
━━━━━━━━━━━━━━━

  CloudWatch:
    → ConsumedReadCapacityUnits (max per partition!)
    → UserErrors (throttling)
    → SystemErrors (AWS-side)
    → SuccessfulRequestLatency

  aws dynamodb describe-table → partition key schema
  Enable Contributor Insights for hot key identification

GENERIC KV COORDINATOR:
━━━━━━━━━━━━━━━━━━━━━━━

  Metrics to dashboard:
    → quorum_success_rate by CL
    → read_sibling_rate (conflict frequency)
    → coordinator_timeout_rate
    → replication_lag_seconds per replica
    → disk_usage_percent per node
    → hint_queue_depth

---

## Decision Framework
```
WHEN TO USE WHAT:
━━━━━━━━━━━━━━━━━

  ┌─────────────────────┬──────────────────────────────────────────┐
  │ Requirement         │ Recommendation                           │
  ├─────────────────────┼──────────────────────────────────────────┤
  │ Billions of keys,   │ DynamoDB or Cassandra                    │
  │ disk-backed         │                                          │
  ├─────────────────────┼──────────────────────────────────────────┤
  │ Sub-ms, in-memory   │ Redis Cluster                            │
  ├─────────────────────┼──────────────────────────────────────────┤
  │ Strong consistency  │ etcd/Consul (small metadata) or          │
  │ small data          │ DynamoDB with consistent read            │
  ├─────────────────────┼──────────────────────────────────────────┤
  │ Graph relationships │ NOT KV — use Neptune/Neo4j               │
  ├─────────────────────┼──────────────────────────────────────────┤
  │ Full-text search    │ NOT KV — use OpenSearch                  │
  ├─────────────────────┼──────────────────────────────────────────┤
  │ Cross-key ACID      │ NOT pure Dynamo — use Spanner/Cockroach  │
  └─────────────────────┴──────────────────────────────────────────┘

  CONSISTENCY LEVEL CHEAT SHEET (N=3):
    Need strong read-after-write → R=2, W=2
    Need max availability        → R=1, W=1 (+ app tolerance)
    Need write durability        → W=2 minimum

---

## Section 9: Incident Scenario — Multi-Symptom, No Hand-Holding


# 🔥 SRE SCENARIO — Distributed KV Store

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: Global session store (Cassandra-backed, RF=3, CL=LOCAL_QUORUM)
Time: 2:47 AM UTC (peak Asia traffic)

ARCHITECTURE:
  500M sessions, 100 nodes, 3 DCs (us-east, eu-west, ap-southeast)
  App servers → coordinators → Cassandra ring
  CL: LOCAL_QUORUM (R=2, W=2 in local DC)

TIMELINE:
  2:47 AM — P99 login latency 50ms → 800ms (ap-southeast)
  2:49 AM — Error rate 0.1% → 4.2% (WriteTimeoutException)
  2:51 AM — Node ap-sg-42 CPU 98%, disk I/O wait 45%
  2:52 AM — Node ap-sg-42 marked DOWN by gossip
  2:53 AM — Hinted handoff queue on ap-sg-17 grows to 2.3M hints
  2:55 AM — ap-sg-17 CPU 95% (was 35%)
  2:58 AM — Cascading: 3 more nodes SUSPECT in ap-southeast
  3:01 AM — EU and US traffic normal; only ap-southeast degraded

METRICS:
  nodetool tablestats sessions: SSTable count on ap-sg-42 = 847 (avg 45)
  Read latency p99 on ap-sg-42: 1.2s
  Partition key scan: session_id prefix "sg-prod-batch-" = 40% of writes
  Deployment at 2:30 AM: new batch job writing sessions with shared prefix

YOUR TASK (interview / SRE exercise):
  Question 1: Root cause chain — trace from deployment to cascade
  Question 2: Immediate mitigation — ordered steps, 2:52 AM perspective
  Question 3: Why did LOCAL_QUORUM not prevent user impact?
  Question 4: Long-term fixes — architecture + process
```

---


## Section 10: Expert Analysis — Full Worked Response

The incident in Section 9 is analyzed question-by-question in the appendix
(**Incident Deep-Dive: Hot Partition Cascade — Q1 through Q4**). Each answer
is 200+ lines with timeline forensics, Week 3/4 cross-references, and
production commands.

**Summary for quick review:**

```
Q1 ROOT CAUSE CHAIN:
  2:30 AM batch job → correlated session_id prefix → hot token range
  → ap-sg-42 absorbs 40% writes → 847 SSTables → read/write amplification
  → node OOM → hinted handoff storm → cascade across ap-southeast DC

Q2 IMMEDIATE MITIGATION (2:52 AM):
  1. Kill batch job (stop hot write source)
  2. Emergency rate-limit prefix sg-prod-batch- at coordinator
  3. Do NOT restart nodes (more hints)
  4. Shed non-critical traffic in ap-southeast
  5. After stabilization: throttle hint delivery, increase compaction

Q3 WHY LOCAL_QUORUM FAILED TO HELP:
  Quorum is per-replica-set, not global fairness.
  When 2 of 3 replicas for THE hot range are melting, W=2 cannot be met.
  Other partitions unaffected — blast radius is partition-local.

Q4 LONG-TERM:
  → Random suffix in batch partition keys
  → Per-partition write rate alarms
  → Shadow-cluster load test for batch jobs
  → 30% capacity headroom per node
  → TWCS compaction for session TTL workload
```

See appendix for full worked answers suitable for interview debrief practice.

## Key Takeaways
```
╔════════════════════════════════════════════════════════════════════╗
║ IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:                     ║
╟────────────────────────────────────────────────────────────────────╢
║ 1. Clarify consistency BEFORE drawing architecture.                ║
║ 2. Consistent hashing (Week 3): ~1/N data move on scale;           ║
║    does NOT fix hot keys — key design matters.                     ║
║ 3. Quorum (Week 4): R+W>N for strong reads; siblings still         ║
║    happen on concurrent writes — plan merge strategy.              ║
║ 4. Dynamo-style = AP-first, leaderless, tunable CL.                ║
║ 5. Production: managed DynamoDB unless you employ Cassandra ops.   ║
╚════════════════════════════════════════════════════════════════════╝
```
---

## Targeted Reading
```
REQUIRED:
  1. Amazon Dynamo paper (DeCandia et al., 2007)
     → Original consistent hashing + quorum + vector clocks
     → 60 minute read — THE interview primary source

  2. DDIA Chapter 5 (Replication) + Chapter 6 (Partitioning)
     → Kleinrock-level foundation for Week 4 connections

  3. Week 3 module: Consistent Hashing.md (this repo)
     → Vnodes, ring math, blast radius calculations

  4. Week 4 module: Replication Strategies.md (this repo)
     → Leaderless quorum, sloppy quorum, hinted handoff

OPTIONAL:
  5. Cassandra: "Rules for Cassandra data modeling" (DataStax docs)
  6. DynamoDB Developer Guide: "Best practices for tables and partitions"
  7. Riak docs: Vector clocks and sibling resolution
```

---

# Appendix: Design Distributed Key-Value Store — Interview Deep-Dive

> **Append to:** `Design Distributed Key-Value Store.md` (Week 13 — Infrastructure System Design)
> **Purpose:** Replace weak Appendix A/B content with production-grade drills, incident forensics, whiteboard templates, and mock dialogue.
> **Prerequisites:** Week 3 `Consistent Hashing.md`, Week 4 `Replication Strategies.md`
> **Systems referenced:** Cassandra 4.x, DynamoDB, Riak KV, ScyllaDB, Redis Cluster (contrast only)

---

## Appendix A: 45-Minute Interview Whiteboard Walkthrough

This timed script replaces the placeholder Appendix A. Each phase has **unique** talking points. Practice with a timer and a blank whiteboard.

```
INTERVIEW CLOCK (45 MINUTES) — DISTRIBUTED KV STORE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 1 │ 0:00 – 5:00  │ Requirements & consistency tradeoffs
  Phase 2 │ 5:00 – 10:00 │ Back-of-envelope capacity (QPS, disk, RF)
  Phase 3 │ 10:00 – 15:00│ High-level architecture (coordinators + ring)
  Phase 4 │ 15:00 – 22:00│ Deep dive A: consistent hashing + vnodes (Week 3)
  Phase 5 │ 22:00 – 30:00│ Deep dive B: replication, quorum, CL (Week 4)
  Phase 6 │ 30:00 – 38:00│ Versioning, conflicts, anti-entropy
  Phase 7 │ 38:00 – 45:00│ Failure modes, monitoring, summary

  RULE: Never draw vnodes before clarifying whether reads can be stale.
  Interviewers dock candidates who optimize partitioning before locking
  consistency requirements.
```

### Phase 1 (0:00 – 5:00): Requirements & Scope Lock

```
WHAT TO SAY (structure — adapt to interviewer answers):

  "Before I draw a ring, I need to know what 'correct' means for reads
   and what we can sacrifice during a partition."

FUNCTIONAL (write on board):
  □ Operations: GET / PUT / DELETE by key (point lookup only?)
  □ Key size limit? Value size limit? (1 MB values change compaction math)
  □ TTL / expiration per key?
  □ Conditional writes (compare-and-swap on version)?
  □ Multi-key transactions? (usually OUT OF SCOPE)
  □ Range scans? (secondary indexes — expensive, call out separately)

NON-FUNCTIONAL:
  □ Read:write ratio? (100:1 typical for session/cart metadata)
  □ Latency targets: p50 / p99 for read and write paths
  □ Durability: lose last N seconds on crash acceptable?
  □ Availability: 99.9% vs 99.99% — drives RF and multi-DC cost
  □ Geographic: single region MVP vs active-active multi-DC
  □ Tenancy: shared cluster vs isolated keyspaces per tenant

DEFAULT ASSUMPTIONS (state aloud if interviewer says "typical"):
  → Billions of keys, values median 2 KB, p99 value 20 KB
  → AP bias: availability over strong consistency during partition
  → 100:1 read:write, no cross-key transactions
  → Single region first; multi-DC as extension with LOCAL_QUORUM

DECISION OUT LOUD:
  "This is a Dynamo-style leaderless quorum store, not Redis Cluster.
   I'll design for tunable consistency per operation, not one global mode."

INTERVIEWER PUSHBACK TO INVITE:
  → "Why not just use Postgres?" → "Horizontal partition at billions
     of keys; single-node SQL doesn't fit write/read scale without
     painful sharding we would be rebuilding anyway."
  → "Why not Redis?" → "Redis Cluster is memory-bound, slot migration
     complexity, different failure model. Fine for cache; we're designing
     durable primary storage."
```

**Whiteboard sketch (Phase 1 — labels only):**

```
  [Mobile] [Web] [Batch jobs]
         \      |      /
          API / BFF layer
                │
                ▼
         ┌──────────────┐
         │ Coordinators │  ← stateless, hash key → route
         └──────┬───────┘
                │
                ▼
         ┌───────────────┐
         │  Storage ring │  ← you haven't said "Cassandra" yet
         │  RF=3, CL=?   │
         └───────────────┘
```

### Phase 2 (5:00 – 10:00): Back-of-Envelope Capacity

```
WRITE ON BOARD — show arithmetic aloud:

  Scale inputs (example after clarify):
    500M DAU × 10 reads/day  = 5B reads/day  ≈ 58K read QPS avg
    500M DAU × 1 write/day   = 500M writes/day ≈ 5.8K write QPS avg
    Peak factor 3×            ≈ 175K read QPS, 17K write QPS peak

  Storage (3-year retention, median value 2 KB):
    500M users × 10 keys/user × 2 KB = 10 TB logical
    RF=3                             = 30 TB replicated
    +30% compaction/SSTable overhead ≈ 39 TB cluster disk

  Write bandwidth (peak, RF=3):
    17K writes/sec × 2 KB × 3 replicas = 102 MB/s cluster write

  Per-node budget (100 nodes):
    ≈ 1.7K write QPS/node, 1.75K read QPS/node at peak
    ≈ 390 GB disk/node

  INTERVIEW CHECK: "Does any SINGLE key exceed per-node budget?"
    Celebrity login, flash sale SKU, viral post counter → HOT KEY path
    (Phase 6 failure modes — do NOT skip)
```

### Phase 3 (10:00 – 15:00): High-Level Architecture

```
DRAW (left to right):

  Clients
    → L7 load balancer (consistent hash on connection optional)
    → Coordinator tier (any node can coordinate; smart clients skip hop)
    → Partitioned storage tier (Dynamo ring / Cassandra vnode ring)

  Coordinator responsibilities (bullets on board):
    1. Hash partition key → token → replica list (Week 3)
    2. Send parallel read/write to R or W replicas (Week 4)
    3. Read repair / digest merge on responses
    4. Hinted handoff when replica down (sloppy quorum)
    5. Attach vector clock or version on write

  Data path one-liner:
    PUT: coord → W closest replicas → ack when W respond
    GET: coord → R replicas → merge versions → return

  Explicit NON-GOALS on board:
    ✗ Global secondary index at billion-key scale (mention LSI pattern)
    ✗ Cross-partition ACID transaction in v1
```

### Phase 4 (15:00 – 22:00): Consistent Hashing Deep Dive (Week 3)

```
ON BOARD — hash ring with 5 physical nodes, 15 vnodes each:

       Token space [0 .. 2^64)
       ───────────────────────────────────────►

         N1    N3        N2    N4    N5
          ●─────●─────────●─────●─────●
               ▲
          key K hashes here → primary = N3
          successors on ring → replicas N2, N4 (RF=3)

  Week 3 connections (say explicitly):
    → Adding node N6: only ~1/N keys move (minimal data transfer)
    → Vnodes: 256 tokens/node → smoother load than 1 token/node
    → Hot key: K_hot still maps to ONE primary vnode — hashing ≠ load balance

  Quantify vnode benefit:
    100 nodes × 256 vnodes = 25,600 slices
    Expected keys per slice: total_keys / 25,600
    Std deviation of slice size ↓ vs 100 slices

  Interviewer probe: "50% traffic to one key?"
    Answer stack (unique to this phase):
      1. Application: random suffix partition key (K#uuid)
      2. Coordinator cache in front of hot key (read path)
      3. Write coalescing / counter sharding (K#0..15)
      4. Rate limit + queue at coordinator
      5. Last resort: dedicated micro-store for that key (DynamoDB DAX pattern)
    WRONG: "add 50 nodes" — key still lands on one primary
```

### Phase 5 (22:00 – 30:00): Replication & Quorum (Week 4)

```
WRITE THE MATH ON BOARD:

  N = replica count in replica set (often RF when CL=QUORUM)
  W = write quorum, R = read quorum
  Strong read guarantee (same timeline): R + W > N

  Example RF=3, W=2, R=2:
    R+W=4 > 3 → overlapping quorum → no stale read IF no concurrent writes
    Tolerates 1 replica down for both read and write

  Consistency Levels (Cassandra vocabulary — map to Dynamo W/R):
    ONE      : W=1 or R=1 — lowest latency, highest staleness risk
    QUORUM   : W=⌊N/2⌋+1 — general purpose
    LOCAL_QUORUM : quorum in local DC only (multi-DC)
    ALL      : W=N — CP behavior, partition = unavailability

  Sloppy quorum + hinted handoff:
    Target down → write goes to temporary node + hint
    Hint replay when target returns → repair amplification

  Week 4 connection:
    Leaderless: no single writer; conflicts possible on concurrent PUTs
    → vector clocks or application merge (Phase 6)
```

### Phase 6 (30:00 – 38:00): Versioning, Conflicts, Anti-Entropy

```
VERSIONING OPTIONS (table on board):

  LWW (timestamp)     : simple, loses concurrent updates silently
  Vector clocks         : detect concurrent writes → siblings
  CRDTs                 : merge without coordination (counters, OR-sets)
  Application merge     : shopping cart union, session field merge

  Anti-entropy paths:
    Read repair         : on read, fix lagging replica inline
    Background repair   : Merkle tree compare ranges (Cassandra repair)
    Hinted handoff      : eager repair on write path when node down

  Failure story (30 sec — foreshadows incident appendix):
    Hot partition → compaction backlog → read amp → node death
    → hint storm → cascade. Monitoring: per-partition write rate.
```

### Phase 7 (38:00 – 45:00): Failure Modes, Monitoring, Summary

```
FAILURE MODES CHECKLIST:
  □ Node crash        → hinted handoff, reduced quorum capacity
  □ Network partition → AP path continues; split-brain siblings
  □ Hot partition     → single-node overload, NOT fixed by RF alone
  □ Rolling upgrade   → transient quorum loss if RF nodes down
  □ Operator error    → wrong CL, truncate, repair during peak

METRICS TO MONITOR (prod):
  p99 read/write latency per DC
  WriteTimeoutException / UnavailableException rate
  SSTable count per node, compaction pending tasks
  Hinted handoff queue depth
  Per-partition load (DynamoDB Contributor Insights analog)
  Repair progress, gc grace exceeded tombstones

CLOSING SUMMARY (30 sec):
  "AP-first leaderless KV with tunable CL. Consistent hashing for
   partition placement; quorum for overlap reads. Hot keys and conflict
   merge are the interview differentiators. I'd start managed (DynamoDB)
   unless we have a Cassandra ops bench."

EXTENSIONS IF TIME:
  → Multi-DC: LOCAL_QUORUM + async cross-DC replication
  → Strong consistency: R=W=N or external lock (DynamoDB TransactWrite)
  → Change capture: CDC stream from commit log (separate module)
```

---

## Appendix B: Common Interview Follow-Up Questions (Expanded)

Each follow-up includes a **short answer** (first 10 seconds) and a **deep answer** (if interviewer says "go deeper").

### B.1 — "How would you add strong consistency?"

**Short:** R=W=N for that operation, or a separate consensus path per key; you pay latency and lose availability during partition.

**Deep:**

```
STRONG CONSISTENCY PATHS (pick one in interview):

  1. R=W=N=RF (Dynamo 'R+W' all)
     → Any read sees latest successful write
     → Partition with minority replicas: writes fail (CP)
     → Latency: wait for slowest replica every time

  2. Linearizable leader per partition (Cockroach / Spanner style)
     → Raft group per range — NOT classic Dynamo
     → Cross-key transactions possible
     → Ops cost: many Raft groups

  3. External lock / transaction coordinator
     → DynamoDB TransactWriteItems across items
     → 2PC across partitions — fragile, rarely in pure Dynamo

  4. Read-your-writes session token
     → Coordinator tracks version; R=1 but route to node that acked write
     → Weaker than linearizable; good UX for session store

QUANTIFY:
  AP path p99 write 5 ms (W=1) → strong path p99 25–80 ms (W=N, geo)

Week 4 tie-in:
  "Quorum overlap R+W>N prevents stale reads only when writes serialize.
   Concurrent writers still need vector clocks — strong quorum ≠ no conflicts."
```

### B.2 — "How would you support range queries?"

**Short:** Avoid global secondary indexes at scale; use composite partition keys or a separate index store (Elasticsearch).

**Deep:**

```
OPTIONS (rank for interview):

  1. Compound partition key (Cassandra clustering columns)
     → PK=(user_id), CK=(timestamp) — range within partition
     → Bounded partition size — still hot if user_id huge

  2. Local secondary index (LSI) — same partition key, alternate sort
     → Query stays on one node IF partition key specified

  3. Global secondary index (GSI)
     → Hidden partition per index entry — write amp 2×, hot index risk
     → Interview: "I'd avoid GSI at billion scale unless query pattern narrow"

  4. External search (Elasticsearch, Scylla Alternator + OpenSearch)
     → KV remains source of truth; search async indexed

  5. Time-series bucketing
     → PK=(metric, day_bucket), CK=timestamp — range = single partition scan

Failure to mention: unbounded partition scan — "SELECT * WHERE ts > X" without
partition key = full cluster scan = interviewer red flag.
```

### B.3 — "How do you handle adding a node?"

**Short:** Assign vnodes to new node; stream SSTables from existing replicas; dual-read during migration; remove old tokens.

**Deep:**

```
NODE ADDITION STEPS (Cassandra mental model):

  1. Configure new node with token ranges (or let autosplit assign vnodes)
  2. Bootstrap: stream data from current replica owners per range
  3. During bootstrap: extra read load on donors — throttle stream throughput
  4. Gossip marks node UP; clients refresh ring topology
  5. Run repair after bootstrap completes (verify Merkle hash match)
  6. Decommission old node (reverse: stream away, rebuild RF elsewhere)

INTERVIEW NUMBERS:
  Cluster 100 nodes, 40 TB data, add 10 nodes (~10% capacity)
  Data to move ≈ 4 TB (only keys owned by new ranges)
  At 100 MB/s stream → ~11 hours — plan maintenance window or throttle

Week 3 tie-in:
  Consistent hashing minimizes moved keys (~1/N) vs modulo hash (100% reshuffle)
```

### B.4 — "DynamoDB vs Cassandra for this design?"

**Short:** DynamoDB if you want managed scaling and per-partition monitoring; Cassandra if you need on-prem, multi-DC control, and ops team.

**Deep:**

```
COMPARISON TABLE (whiteboard):

  Dimension          │ DynamoDB              │ Cassandra self-hosted
  ───────────────────┼───────────────────────┼────────────────────────
  Partition model    │ Managed partitions    │ Vnodes + operator tuning
  Hot key detection  │ Contributor Insights  │ nodetool + custom metrics
  Consistency        │ Per-request CL        │ CL per query
  Cost model         │ RCU/WCU/on-demand     │ Hardware + ops headcount
  Repair             │ Automatic             │ nodetool repair scheduling
  Multi-DC           │ Global tables         │ NetworkTopologyStrategy

Interview line:
  "I'd default DynamoDB unless regulatory or cost-at-scale forces Cassandra.
   The DESIGN patterns (hash, quorum, versions) transfer either way."
```

### B.5 — "Explain CAP / PACELC for this system."

**Short:** During partition we choose AP (availability + eventual consistency); else (PACELC) we choose latency over consistency with tunable CL.

**Deep:**

```
CAP (simplified — say nuance):
  Network partition happens → KV store picks:
    CP: reject writes/reads that can't meet quorum (Postgres primary)
    AP: accept writes on available replicas, resolve later (Dynamo)

PACELC (better interview frame):
  If Partition → AP for this design (hinted handoff, sloppy quorum)
  Else → Latency vs Consistency:
    CL=ONE → low latency, stale reads possible
    CL=QUORUM → middle ground
    CL=ALL → strong, higher tail latency

Real incident hook:
  LOCAL_QUORUM during DC degradation — still AP within DC but if hot
  partition kills 2 of 3 local replicas for a KEY, that key fails (see incident Q3).
```

### B.6 — "What happens on a network partition?"

**Short:** Both sides accept writes with sloppy quorum; vector clocks detect conflicts; merge on heal.

**Deep:**

```
SCENARIO: RF=3, nodes {A,B,C}, partition isolates A from {B,C}

  Writes to key K (replicas A,B,C):
    Side {B,C}: W=2 succeeds on B,C
    Side {A}  : W=2 cannot succeed (only A) — unless sloppy quorum + hint

  Sloppy quorum:
    A writes to D (non-replica) + hint for A
    After heal: hints replay, read repair merges

  Siblings after heal:
    VC shows concurrent updates → application merge or LWW policy

  Interview MUST say:
    "We don't get free strong consistency — business logic resolves conflicts."
```

---

### Principal stretch

## Hands-On Exercises

These exercises build **operational muscle memory** for Dynamo-style stores. Run against Docker Cassandra, Scylla, or AWS DynamoDB Local. Commands are copy-paste ready; replace hostnames and credentials.

### Exercise 0: Local Cassandra Cluster (Docker)

```
PREREQUISITES:
  Docker Desktop / Podman
  Image: cassandra:4.1
  Network: cassandra-net

START 3-NODE CLUSTER:

  docker network create cassandra-net

  docker run -d --name cass-1 --network cassandra-net \
    -p 9042:9042 \
    -e CASSANDRA_CLUSTER_NAME=kv-lab \
    -e CASSANDRA_DC=dc1 \
    -e CASSANDRA_RACK=rack1 \
    -e CASSANDRA_ENDPOINT_SNITCH=GossipingPropertyFileSnitch \
    cassandra:4.1

  # Wait for cass-1 ready (~90s), then seed join:
  for i in 2 3; do
    docker run -d --name cass-$i --network cassandra-net \
      -e CASSANDRA_CLUSTER_NAME=kv-lab \
      -e CASSANDRA_DC=dc1 \
      -e CASSANDRA_RACK=rack1 \
      -e CASSANDRA_SEEDS=cass-1 \
      -e CASSANDRA_ENDPOINT_SNITCH=GossipingPropertyFileSnitch \
      cassandra:4.1
  done

VERIFY RING:
  docker exec -it cass-1 nodetool status
  docker exec -it cass-1 nodetool describecluster
```

### Exercise 1: Observe Quorum Behavior with cqlsh

```bash
# Connect to coordinator
docker exec -it cass-1 cqlsh

# Create keyspace RF=3, SimpleStrategy (lab only)
CREATE KEYSPACE IF NOT EXISTS kv_lab
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 3};

CREATE TABLE kv_lab.sessions (
  session_id text PRIMARY KEY,
  user_id uuid,
  last_active timestamp,
  payload text
);

# Write with QUORUM (W=2 of 3)
CONSISTENCY QUORUM;
INSERT INTO kv_lab.sessions (session_id, user_id, last_active, payload)
  VALUES ('sess-001', uuid(), toTimestamp(now()), '{"cart":[]}');

# Read with ONE — may hit lagging replica after stress
CONSISTENCY ONE;
SELECT * FROM kv_lab.sessions WHERE session_id = 'sess-001';

# Read with QUORUM — overlapping read
CONSISTENCY QUORUM;
SELECT * FROM kv_lab.sessions WHERE session_id = 'sess-001';
```

**Interview takeaway:** Changing CONSISTENCY in cqlsh is per-query tunable CL — exactly the Dynamo design point.

### Exercise 2: Simulate Node Failure and Hinted Handoff

```bash
# Terminal 1 — continuous writes
docker exec cass-1 bash -c '
  i=0
  while true; do
    cqlsh -e "CONSISTENCY QUORUM; INSERT INTO kv_lab.sessions (session_id,user_id,last_active,payload) VALUES ('\''failtest-$i'\'', uuid(), toTimestamp(now()), '\''{}'\'');"
    i=$((i+1))
    sleep 0.1
  done
'

# Terminal 2 — stop one node mid-write
docker stop cass-3
sleep 30
docker exec cass-1 nodetool status | grep -E "Down|UN"

# Check hints on surviving nodes
docker exec cass-1 nodetool tablestats system.hints
docker exec cass-1 nodetool hintsstatus

# Restart node — watch hint delivery
docker start cass-3
sleep 60
docker exec cass-1 nodetool tablestats system.hints
```

**Observe:** WriteTimeout rate rises when RF replicas unavailable; hints queue grows; restart triggers replay traffic.

### Exercise 3: Hot Partition Signatures with nodetool

```bash
# Write skewed keys (bad partition key design — intentional)
docker exec cass-1 bash -c '
  for i in $(seq 1 5000); do
    cqlsh -e "CONSISTENCY ONE; INSERT INTO kv_lab.sessions (session_id,user_id,last_active,payload) VALUES ('\''hot-key-same'\'', uuid(), toTimestamp(now()), '\''x'\'');"
  done
'

# Compare table stats per node
docker exec cass-1 nodetool tablestats kv_lab.sessions

# Check SSTable count — hot node diverges
for n in 1 2 3; do
  echo "=== cass-$n ==="
  docker exec cass-$n nodetool tablestats kv_lab.sessions | grep -E "SSTable|Partition"
done

# Flush memtables — observe compaction pressure
docker exec cass-1 nodetool flush kv_lab sessions
docker exec cass-1 nodetool compactionstats
```

**Interview takeaway:** Identical partition key → one token → one primary replica owns all writes regardless of ring size.

### Exercise 4: Token Ring Inspection

```bash
# List tokens owned by node (vnode count)
docker exec cass-1 nodetool ring | head -40

# Where does a key hash? (Cassandra 4 murmur3)
docker exec cass-1 nodetool getendpoints kv_lab sessions hot-key-same

# Compare to well-distributed key
docker exec cass-1 nodetool getendpoints kv_lab sessions "$(uuidgen)"
```

**Draw on paper:** replica list returned = coordination target for that partition key.

### Exercise 5: AWS DynamoDB — On-Demand Table and Contributor Insights

```bash
# Create table (AWS CLI v2)
aws dynamodb create-table \
  --table-name SessionStoreLab \
  --attribute-definitions AttributeName=session_id,AttributeType=S \
  --key-schema AttributeName=session_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1

aws dynamodb wait table-exists --table-name SessionStoreLab

# Put item
aws dynamodb put-item \
  --table-name SessionStoreLab \
  --item '{"session_id":{"S":"aws-sess-001"},"user_id":{"S":"u-42"},"ttl":{"N":"1735689600"}}'

# Strongly consistent read (R+W path — consumes 2× RCU for large items)
aws dynamodb get-item \
  --table-name SessionStoreLab \
  --key '{"session_id":{"S":"aws-sess-001"}}' \
  --consistent-read

# Eventually consistent (default)
aws dynamodb get-item \
  --table-name SessionStoreLab \
  --key '{"session_id":{"S":"aws-sess-001"}}'

# Enable Contributor Insights (hot key detection — prod analog)
aws dynamodb update-contributor-insights \
  --table-name SessionStoreLab \
  --contributor-insights-action ENABLE

aws dynamodb describe-contributor-insights \
  --table-name SessionStoreLab
```

### Exercise 6: DynamoDB Local with curl (HTTP API)

```bash
# Start DynamoDB Local (Java)
docker run -d --name dynamodb-local -p 8000:8000 \
  amazon/dynamodb-local:latest -jar DynamoDBLocal.jar -sharedDb

# Create table via AWS CLI pointing at local endpoint
aws dynamodb create-table \
  --endpoint-url http://localhost:8000 \
  --table-name LocalKV \
  --attribute-definitions AttributeName=pk,AttributeType=S \
  --key-schema AttributeName=pk,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# Put with curl (JSON API — useful when debugging SDK issues)
curl -s -X POST http://localhost:8000 \
  -H "Content-Type: application/x-amz-json-1.0" \
  -H "X-Amz-Target: DynamoDB_20120810.PutItem" \
  -d '{
    "TableName": "LocalKV",
    "Item": {
      "pk": {"S": "demo-key"},
      "value": {"S": "hello-dynamo"},
      "version": {"N": "1"}
    }
  }' | jq .

# GetItem
curl -s -X POST http://localhost:8000 \
  -H "Content-Type: application/x-amz-json-1.0" \
  -H "X-Amz-Target: DynamoDB_20120810.GetItem" \
  -d '{
    "TableName": "LocalKV",
    "Key": {"pk": {"S": "demo-key"}},
    "ConsistentRead": true
  }' | jq .
```

### Exercise 7: Measure Read Repair Latency (cqlsh tracing)

```bash
docker exec -it cass-1 cqlsh -e "TRACING ON; CONSISTENCY QUORUM; SELECT * FROM kv_lab.sessions WHERE session_id = 'sess-001';"

# Inspect trace — see requests to multiple replicas
docker exec -it cass-1 cqlsh -e "TRACING ON; CONSISTENCY ONE; SELECT * FROM kv_lab.sessions WHERE session_id = 'sess-001';"
```

Compare trace event counts: QUORUM read contacts multiple replicas; ONE may contact single replica.

### Exercise 8: Compaction Backlog Diagnostic Drill

```bash
# Generate write amplification
docker exec cass-1 bash -c '
  for i in $(seq 1 20000); do
    cqlsh -e "INSERT INTO kv_lab.sessions (session_id,user_id,last_active,payload) VALUES ('\''bulk-$i'\'', uuid(), toTimestamp(now()), '\''$(python3 -c "print(\"a\"*2000)")'\'');"
  done
'

docker exec cass-1 nodetool tablestats kv_lab.sessions
docker exec cass-1 nodetool tpstats | grep -i compaction
docker exec cass-1 nodetool compactionstats

# Interview question: "p99 read latency spiked — first three commands?"
# Answer: tablestats SSTable count, compactionstats pending, tpstats threads
```

### Exercise 9: Rate Limit Simulation at Coordinator (curl to app layer)

```bash
# If your app exposes HTTP KV proxy with rate limit headers:
for i in $(seq 1 100); do
  curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" \
    -X PUT "http://localhost:8080/kv/sg-prod-batch-$i" \
    -H "Content-Type: application/json" \
    -d '{"session":"data"}'
done

# Emergency block pattern (nginx/coordinator config concept):
# limit_req_zone $binary_remote_addr zone=hot:10m rate=10r/s;
# return 429 for offending key prefix at edge BEFORE ring overload
```

### Exercise 10: Repair and Merkle Tree (maintenance window)

```bash
# Full cluster repair (expensive — lab only, small dataset)
docker exec cass-1 nodetool repair kv_lab sessions -full

# Verify no mismatch
docker exec cass-1 nodetool verify kv_lab sessions

# Interview: "When to run repair?"
# → After node replacement, before gc_grace_seconds expires on tombstones,
#   scheduled weekly at low traffic — NOT during active incident
```

---

## Incident Deep-Dive: Hot Partition Cascade — Expert Analysis

> **Scenario reference:** Section 9 incident report (global session store, Cassandra, RF=3, LOCAL_QUORUM, ap-southeast cascade).
> **Goal:** Replace placeholder Section 10 with production-grade forensics suitable for senior/staff interview debriefs.

---

## Question 1: Root Cause Chain — From Deployment to Cascade

### Executive Summary (say this first in a debrief)

The incident is **not** a quorum misconfiguration. It is a **partition key design failure** amplified by **read-modify-write session traffic**, **compaction debt**, and **hinted handoff replay storm**. Consistent hashing worked correctly — it placed correlated keys on the same vnode. LOCAL_QUORUM correctly required two local replicas — but both replicas for the hot range were overloaded, so quorum failed for that keyspace slice.

### Timeline Reconstruction — Minute by Minute

```
2:30 AM UTC — DEPLOYMENT (trigger)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Change ticket: BATCH-4412 "Optimize APAC session pre-warm"
  New job writes session rows:
    session_id = "sg-prod-batch-" + zeroPad(batchSeq, 8)

  Code review miss:
    → Sequential suffix produces correlated murmur3 hashes
    → Not identical key (that would be trivial hot key)
    → CLUSTER of keys landing in adjacent token ranges
    → Primary replica for that arc: ap-sg-42

  Expected write rate: 2K/sec (documented)
  Actual write rate: 18K/sec (config error: batchSize × workerCount)
  Read path unchanged: every login = GET session + PUT last_active
```

```
2:30 – 2:46 AM — SILENT OVERLOAD PHASE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ap-sg-42 metrics (Datadog / Prometheus):
    write_requests/sec: 900 → 4,200 → 11,000 (vs baseline 220)
    memtable_flush_pending: 0 → 3 → 12
    SSTable count (sessions): 45 → 180 → 412
    compaction_pending_tasks: 2 → 38

  Why other nodes look healthy:
    Consistent hashing isolates load by token ownership.
    100 nodes → hot arc affects ~3–5 nodes holding adjacent vnodes.
    Cluster-average CPU misleading — max-node CPU is the alert that matters.

  Week 3 concept:
    Uniform key distribution assumption violated.
    hash("sg-prod-batch-00000001") ≈ nearby hash("...00000002")
    → keys cluster on ring → ONE vnode primary gets firehose
```

```
2:47 AM — USER-VISIBLE LATENCY (symptom)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Login flow (read-modify-write):
    1. GET session by session_id        (QUORUM read → 2 replicas)
    2. Validate token
    3. PUT last_active timestamp        (QUORUM write → 2 replicas)

  ap-sg-42 read path cost explosion:
    412 SSTables → 412 bloom filter checks per read (upper bound)
    row cache ineffective (unique session_ids in batch)
    p99 read latency: 50 ms → 380 ms → 800 ms (APAC LB metric)

  Error budget:
    Timeouts begin at client 950 ms threshold
    Not yet widespread errors — latency SLO burn only
```

```
2:49 AM — WRITE TIMEOUTS (4.2% error rate)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Cassandra client exceptions:
    WriteTimeoutException: "Received 1 responses but 2 required"
    Coordinator: ap-sg-coord-07
    CL=LOCAL_QUORUM, RF=3, local replicas {42, 17, 23}

  Write path breakdown for hot keys:
    Replica 42: accepting but 800 ms+ (overloaded)
    Replica 17: accepting, 120 ms (healthy)
    Replica 23: accepting, 95 ms (healthy)

  Why timeouts anyway?
    Coordinator waits for W=2 responses within 2s (write_request_timeout)
    Replica 42 sometimes exceeds timeout → only 1 ack in window → fail

  Week 4 concept:
    Quorum is count-based, not latency-based.
    "2 of 3 replicas responded" can still fail if one response too slow.
```

```
2:51 AM — RESOURCE EXHAUSTION ON ap-sg-42
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Node ap-sg-42:
    CPU: 98% (compaction threads + read path + writes)
    iowait: 45% (SSTable components on EBS gp3)
    heap: 92% ( bloom filter + row cache churn)
    pending compactions: 41

  GC pause: 1.8s (G1 Old Gen promotion failure precursor)

  Ops runbook temptation: "restart cassandra" — NOT YET (see Q2)
```

```
2:52 AM — NODE MARKED DOWN
━━━━━━━━━━━━━━━━━━━━━━━━━━

  ap-sg-42 JVM OOM or systemd watchdog restart (exact mechanism secondary)
  Gossip: ap-sg-42 status DN (Down)

  Effect on hot token ranges:
    Primary for hot arc DOWN
    Remaining local replicas {17, 23} must absorb 100% of hot writes
    PLUS hinted handoff for replica 42's share

  Week 4 — hinted handoff:
    Writes destined for 42 redirected to 17 with hint metadata
    Hint = extra write + future replay cost
```

```
2:53 AM — HINT STORM ON ap-sg-17
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  nodetool tablestats system.hints:
    hints pending: 2.3M (was ~12K baseline)
    hint size on disk: 4.1 GB

  ap-sg-17 CPU: 35% → 78% → 95% in 4 minutes

  Death spiral mechanics:
    Normal traffic + hinted writes + hint replay worker
    + read repair triggered by inconsistent replicas
    + compaction on 17 now falling behind

  Cascading gossip:
    2:58 AM — ap-sg-17, ap-sg-23, ap-sg-51 marked SUSPECT
    Inter-node latency spikes → false positive suspicion
    Clients retry → more load (retry storm)
```

```
3:01 AM — BLAST RADIUS CONTAINED BY GEOGRAPHY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  us-east, eu-west: normal p99, error rate < 0.01%
  ap-southeast: degraded

  Why geography mattered:
    LOCAL_QUORUM scopes reads/writes to local DC replica set
    Hot keys owned by ap-southeast nodes → APAC users hit hot range
    US users different token arc → unaffected

  NOT a global cluster failure — regional partition load incident
```

### Causal Chain Diagram (draw on whiteboard)

```
  BATCH-4412 deploy
        │
        ▼
  Correlated partition keys (sg-prod-batch-*)
        │
        ▼
  Token arc concentrated on ap-sg-42 (Week 3: hash clustering)
        │
        ▼
  Write QPS 50× on single node → memtable flush lag
        │
        ▼
  SSTable count 45 → 847 → read amplification on login RMW
        │
        ▼
  p99 latency 800ms → client timeouts begin
        │
        ▼
  ap-sg-42 OOM/DOWN → hinted handoff to ap-sg-17
        │
        ▼
  2.3M hints + normal traffic → ap-sg-17 melts
        │
        ▼
  SUSPECT cascade (3 nodes) → QUORUM failures for APAC session keys
        │
        ▼
  P1: 4.2% login errors APAC only
```

### Evidence Checklist (what you'd pull in prod)

```
DATA SOURCES:
  □ Git deploy log 2:30 AM — batch job partition key format
  □ Cassandra slow query log — top partition keys by write count
  □ nodetool tablestats sessions on ap-sg-42 — SSTable count 847 vs avg 45
  □ Prometheus: cassandra_table_write_latency by node
  □ Partition key histogram: prefix "sg-prod-batch-" = 40% writes
  □ system.hints growth rate 2:52–2:55 AM
  □ Client trace: WriteTimeoutException replica list {42,17,23}

COMMANDS RUN DURING RCA:
  nodetool status
  nodetool tablehistograms keyspace sessions
  nodetool getendpoints keyspace sessions 'sg-prod-batch-00004200'
  nodetool tpstats
  nodetool compactionstats
```

### Why "Add More Nodes" Would NOT Have Fixed This

```
Interview critical point:

  Adding 10 nodes to ap-southeast BEFORE fixing key design:
    → Moves ~10% of token ranges (consistent hashing benefit)
    → Hot correlated keys STILL hash to adjacent tokens
    → Same arc, possibly different owner — still 1–3 nodes absorb 40% writes
    → Bootstrap streaming adds MORE I/O during incident

  Correct lever: key design (random suffix) OR rate limit batch job
  Capacity headroom helps AFTER key distribution fixed
```

### Week 3 + Week 4 Integration (explicit interview points)

```
Week 3 — Consistent Hashing:
  ✓ Ring correctly mapped correlated keys to same vnode arc
  ✗ Misconception: "hash ring balances load" — balances KEY SPACE,
    not traffic. Skewed access patterns ≠ skewed key space.

Week 4 — Replication & Quorum:
  ✓ LOCAL_QUORUM requires 2 of 3 local replicas — mathematical guarantee
  ✗ Guarantee applies per operation IF replicas respond in time
  ✗ Hinted handoff preserves availability but creates repair debt
  ✗ Quorum does not serialize concurrent writers — irrelevant here but mention
```

### Root Cause Statement (single paragraph for postmortem)

**Primary:** Batch job BATCH-4412 introduced high-rate writes with sequentially correlated partition keys (`sg-prod-batch-*`), concentrating ~40% of cluster write traffic onto the vnode arc owned primarily by ap-sg-42, causing compaction backlog and read amplification on the session read-modify-write path.

**Contributing:** Insufficient per-partition rate monitoring; missing pre-production load test on shadow cluster; write_request_timeout tuned for median not tail; operator instinct to restart nodes (avoided in this narrative but common); ap-southeast node headroom below 2× partition firehose capacity.

**Not root cause:** LOCAL_QUORUM misconfiguration, network partition between DCs, Cassandra version bug, gossip algorithm failure.


## Question 2: Immediate Mitigation — Ordered Steps at 2:52 AM

### Framing: Incident Commander Mindset

At 2:52 AM you know: ap-sg-42 is DOWN, ap-sg-17 hint queue 2.3M, APAC login errors 4.2%, US/EU clean. **Goal order:** stop new damage → shed load → stabilize ring → recover data → postmortem later.

**Do NOT:** rolling restart all APAC nodes, full repair, truncate sessions, bump RF, or disable hinted handoff globally without understanding hint backlog.

### Action 0: Declare Incident & Assign Roles (Minute 0–2)

```
INCIDENT BRIDGE:
  IC: SRE on-call (coordinates only — no debugging in parallel alone)
  Storage: Cassandra DBA
  App: Session service owner
  Comms: Customer support liaison

STATUS PAGE (internal):
  "Elevated login latency and errors in APAC region. US/EU unaffected.
   Investigating session storage tier."

Customer-facing: delay until mitigation started — avoid premature all-clear
```

### Action 1: STOP THE BATCH JOB — Kill Switch (Minute 2–4) **HIGHEST PRIORITY**

```bash
# Kubernetes — scale batch deployment to zero
kubectl scale deployment/session-prewarm-batch --replicas=0 -n production

# OR disable cron / workflow
aws events disable-rule --name apac-session-prewarm --region ap-southeast-1

# Verify write rate dropping (Prometheus)
# rate(cassandra_table_writes{keyspace="sessions"}[1m]) by (node)
# Expect: ap-sg-17 write slope decreases within 60–90s after job stop
```

**Why first:** Every second the batch runs adds memtable pressure, new hints, and SSTables. No storage tuning outruns 18K bad writes/sec.

**Interview line:** "Remove the source before tuning the sink."

### Action 2: Emergency Rate Limit at Coordinator / API Gateway (Minute 4–8)

```bash
# Block offending key prefix at session API (example nginx map)
# /etc/nginx/conf.d/emergency_hot_key.conf
# map $request_uri $block_batch {
#   default 0;
#   ~*^/sessions/sg-prod-batch- 1;
# }
# if ($block_batch) { return 429; }

# App-layer feature flag (LaunchDarkly / internal)
curl -X PATCH https://flags.internal/api/v1/flags/block-sg-batch \
  -H "Authorization: Bearer $FLAG_ADMIN_TOKEN" \
  -d '{"enabled": true, "reason": "P1 hot partition INC-8842"}'

# DynamoDB analog: throttle via WCU cap on table + client backoff
aws application-autoscaling register-scalable-target \
  --service-namespace dynamodb \
  --resource-id table/SessionStore \
  --scalable-dimension dynamodb:table:WriteCapacityUnits \
  --min-capacity 100 --max-capacity 100  # temporary write ceiling
```

**Scope:** Block `sg-prod-batch-*` prefix ONLY — not all logins. Over-broad blocks become second incident.

### Action 3: Shed Read Load — Session Service (Minute 8–12)

```
READ SHEDDING (non-destructive):
  □ Extend session TTL in JWT — validate locally without KV read for 5 min
  □ Skip last_active PUT on read path (async queue or drop — document data loss)
  □ Route APAC login to read-only fallback cache (Redis) if populated
  □ Increase client timeout ONLY after load drop (raising timeout under load worsens retry storm)

WRITE SHEDDING:
  □ Disable non-critical session fields in PUT payload
  □ Sample last_active updates (1 in 10) — explicit product approval on bridge
```

**Quantify tradeoff:** Skipping last_active loses freshness of "last seen" — acceptable vs 4% hard failures during peak Asia hours.

### Action 4: DO NOT Mass-Restart Cassandra Nodes (Minute 0–∞ — standing order)

```
WHY RESTART IS TOXIC MID-HINT-STORM:

  Restart ap-sg-17:
    → Hint replay interrupted
    → On boot: gossip flaps, bootstrap hints, compaction cold start
    → Clients retry → thundering herd

  Restart ap-sg-42:
    → Node rejoins with empty memtable
    → Streaming + hint delivery compete for disk
    → Hot range ownership confusion during UP/DOWN flap

  ALLOWED: restart SINGLE node only if JVM hung AND IC approves AND job stopped
```

### Action 5: Cassandra Tuning — After Load Drops 30%+ (Minute 12–20)

```bash
# ONLY after batch stopped — increase compaction throughput on survivors
docker exec cass-1 nodetool setcompactionthroughput 256  # MB/s, default 64

# Pause non-critical secondary index builds (if any)
# nodetool disableautocompact keyspace table  — USE SPARINGLY, re-enable after

# Increase write_request_timeout temporarily (conf/client cassandra.yaml)
# write_request_timeout_in_ms: 2000 → 5000
# Requires rolling client config — coordinate with app team

# Check hinted handoff still enabled (don't disable unless extreme)
docker exec cass-1 nodetool statushandoff
```

**Interview caution:** `setcompactionthroughput` trades write amp for read recovery — correct AFTER load source removed.

### Action 6: Traffic Shift Within APAC (Minute 15–25) — if multi-cluster

```
IF architecture has standby read cluster ( rare ):
  □ Shift read traffic via DNS / service mesh weighted route
  □ 80% traffic to passive replica cluster (stale reads possible — comms)

IF single cluster (this scenario):
  □ Focus on key block + batch stop, not magic failover
  □ CDN / edge cannot help — session store is origin data path
```

### Action 7: Monitor Recovery Signals (Minute 20–40)

```bash
# Recovery dashboard — watch THESE in order:

# 1. Hint queue draining
watch -n 10 'docker exec cass-1 nodetool tablestats system.hints | grep -E "Count|Size"'

# 2. SSTable count falling on ap-sg-42 after rejoin
docker exec cass-42 nodetool tablestats sessions | grep SSTable

# 3. Write latency p99 < 100ms sustained 10 min
# Prometheus: histogram_quantile(0.99, rate(cassandra_write_latency_bucket[5m]))

# 4. Error rate < 0.1%
# App: sum(rate(login_errors[5m])) / sum(rate(login_attempts[5m]))

# 5. Gossip all UN (Up Normal)
docker exec cass-1 nodetool status | grep -v "^UN"
```

### Action 8: Rejoin ap-sg-42 Safely (Minute 30–60 — after hints stable)

```bash
# If ap-sg-42 still DOWN after OOM:
# Start cassandra — do NOT run repair immediately

systemctl start cassandra   # or k8s pod reschedule

# Wait for status UN
nodetool status | grep ap-sg-42

# Monitor hint delivery TO ap-sg-42 — should drain, not grow
nodetool hintsstatus

# DO NOT nodetool repair full cluster during recovery window
```

### Action 9: Communication Checkpoints

```
T+15 min (after batch stop):
  Internal: "Write source stopped. Error rate plateauing at 2.1%."

T+45 min (hints draining):
  Internal: "Hint queue 2.3M → 400K. p99 latency 180ms."

T+90 min (stable):
  Customer: "Resolved elevated login issues in Southeast Asia."

NEVER tell customers "Cassandra quorum misconfigured" — inaccurate and erodes trust
```

### Mitigation Priority Matrix (whiteboard)

```
┌────────────────────────────┬──────────┬─────────────────────────────┐
│ Action                     │ Priority │ Risk if skipped             │
├────────────────────────────┼──────────┼─────────────────────────────┤
│ Stop batch job             │ P0       │ Incident indefinite         │
│ Block hot key prefix       │ P0       │ Restart loop on survivors   │
│ Shed last_active writes    │ P1       │ Prolonged compaction debt   │
│ Increase compaction thrpt  │ P2       │ Slow read recovery          │
│ Restart all APAC nodes     │ NEVER    │ Hint storm × node count     │
│ Full nodetool repair       │ DEFER    │ Competes with user traffic  │
└────────────────────────────┴──────────┴─────────────────────────────┘
```

### Commands Cheat Sheet (copy to runbook)

```bash
# Status snapshot bundle for IC
nodetool status > /tmp/inc-status.txt
nodetool tpstats >> /tmp/inc-status.txt
nodetool compactionstats >> /tmp/inc-status.txt
nodetool tablestats sessions >> /tmp/inc-status.txt
nodetool tablestats system.hints >> /tmp/inc-status.txt

# Identify top partitions (Cassandra 4.x diagnostic)
nodetool toppartitions sessions 20 write

# Confirm key location
nodetool getendpoints sessions 'sg-prod-batch-00012345'
```

### Interview Closing (Q2)

"In the first five minutes I stop the write source and block the offending prefix at the coordinator. I explicitly forbid mass restarts because hinted handoff has already queued millions of writes. Only after load drops do I tune compaction and monitor hint drain. Repair is a next-day activity."


## Question 3: Why LOCAL_QUORUM Did Not Prevent User Impact

### The Misconception to Destroy First

**Wrong answer:** "LOCAL_QUORUM was misconfigured — we should have used EACH_QUORUM or ALL."

**Right answer:** LOCAL_QUORUM worked exactly as designed. It guarantees that a read or write succeeds only when a quorum of **local DC replicas** respond in time. When two of the three local replicas for the **hot token range** are overloaded or down, quorum cannot be assembled **for keys in that range**. Other keys in APAC continue to work. Users whose sessions hash to the hot arc fail login.

Quorum prevents stale reads from minority partitions — it does **not** prevent overload, hint storms, or tail-latency timeouts.

### LOCAL_QUORUM Mechanics Refresher (Week 4)

```
Setup:
  NetworkTopologyStrategy RF=3 per DC
  ap-southeast DC nodes holding replica set for key K:
    {ap-sg-42, ap-sg-17, ap-sg-23}

  LOCAL_QUORUM:
    W = ⌊RF_local/2⌋ + 1 = 2
    R = 2

  Write succeeds if ANY 2 of {42, 17, 23} acknowledge within timeout
  Read succeeds if ANY 2 return data within timeout
```

```
Healthy state (before incident):
  Write to K → coord sends to 42, 17, 23
  42 ack 8ms, 17 ack 9ms, 23 ack 7ms → W=2 satisfied at 9ms ✓

Degraded state (2:49 AM):
  42 ack 2100ms (timeout), 17 ack 110ms, 23 ack 95ms
  Coordinator window 2000ms → only 2 acks if 42 occasionally fast enough
  When 42 slow: 1 ack in window → WriteTimeoutException ✗

  User impact: login PUT last_active fails → 4.2% errors
```

### Reason 1: Quorum Is Per-Replica-Set, Not Per-Cluster

```
GLOBAL cluster health:
  97 of 100 nodes UN → cluster "healthy"

LOCAL_QUORUM for key K:
  Needs 2 of 3 replicas for K's token range
  If K's range maps to melting nodes → K fails
  Independent key K2 different range → succeeds

Interview diagram:

  Key K_hot  → replicas {42↓, 17↓, 23} → QUORUM FAIL
  Key K_norm → replicas {08, 51, 62} → QUORUM OK

  Same DC, same CL, different outcomes — partition key determines fate
```

### Reason 2: Tail Latency Breaks Count Quorum

```
Week 4 math assumes replicas respond before timeout.

Cassandra defaults (typical):
  write_request_timeout_in_ms = 2000
  read_request_timeout_in_ms  = 5000

Replica 42 under compaction:
  p50 ack: 40ms
  p99 ack: 1800ms
  p999 ack: 3500ms → write fails even though node eventually succeeds

  "Eventually written" ≠ "quorum satisfied within client deadline"

DynamoDB parallel:
  Provisioned WCU exhausted → throttling → same tail failure mode
  On-demand throttling → ProvisionedThroughputExceededException
```

### Reason 3: Node Down Shrinks Effective Quorum Capacity

```
After ap-sg-42 DOWN:
  Available local replicas for K: {17, 23} — exactly 2 nodes

  W=2 still mathematically satisfiable BUT:
    Every write to K must hit BOTH surviving nodes (no redundancy margin)
    Any slowdown on 17 OR 23 → immediate failure

  Before: 3 choose 2 = 3 combinations for quorum
  After:  2 choose 2 = 1 combination only {17,23} — brittle

  Hinted handoff adds writes to 17 → 17 overloaded → both required nodes slow
  → cascade
```

### Reason 4: Hinted Handoff Increases Load on Survivors

```
Write with 42 down:
  Coordinator sends write to 17 (data) + stores hint for 42
  OR sends to 23 + hint

  Hint storage:
    system.hints table on 17 grows 2.3M entries
    Hint replay thread competes for CPU/disk with live writes

  LOCAL_QUORUM still satisfied on live path — but survivor melting
  causes quorum failures for ALL keys on 17's vnodes, not just hot keys

  Blast radius expansion: hot key incident → node failure → hint storm
  → secondary victims on shared nodes
```

### Reason 5: Read-Modify-Write Doubles Quorum Exposure

```
Login path:
  1. QUORUM READ  (need 2 of 3 respond)
  2. QUORUM WRITE (need 2 of 3 respond)

  Independent failure probability:
    P(read ok) × P(write ok) — if each 96% → 92.2% success (rough intuition)

  Under load:
    Read checks 847 SSTables on 42 → read timeout
    Even if read succeeds, write may fail

  Interview: "Session pattern amplifies hot partition — not just write QPS"
```

### Reason 6: LOCAL_QUORUM Does Not Load-Balance Traffic

```
Week 3 connection:

  LOCAL_QUORUM scopes replicas to DC — correct for latency
  Does NOT spread hot key load across DCs
  Does NOT split hot key across vnodes

  Cross-DC QUORUM (EACH_QUORUM) would add WAN latency on every login — worse UX

  Hot key fixes remain application/coordinator layer:
    random suffix, local cache, write coalescing
```

### Reason 7: AP Availability ≠ Every Operation Succeeds

```
PACELC During partition → AP choice:
  System remains available for keys with healthy replica sets
  Hot keys unavailable — partial outage

  CAP nuance:
    "Available" means nodes accept requests — not all requests succeed
    Cassandra returns UnavailableException / WriteTimeout — honest failure

  Contrast CP:
    Minority partition rejects writes entirely — smaller blast radius per key
    but whole DC might reject vs partial key-level failures in AP
```

### What LOCAL_QUORUM DID Prevent (credit where due)

```
WITHOUT local quorum (CL=ONE):
  Reads after write might hit lagging replica 42 → stale session token
  Security: revoked session still appears valid

WITH LOCAL_QUORUM (when replicas healthy):
  R+W overlap → read sees previous quorum write
  Correct tradeoff for session store WHEN load normal

Incident period:
  Quorum correctness intact — failures are overload, not stale ghost reads
  Post-incident data: no widespread session corruption reported — timeout errors
```

### Counterfactual Table (interview gold)

```
┌─────────────────────┬────────────────────────────────────────────────────┐
│ If we had used...   │ Outcome during this incident                       │
├─────────────────────┼────────────────────────────────────────────────────┤
│ CL=ONE              │ Lower error rate BUT stale sessions / auth bugs    │
│ CL=ALL              │ Higher error rate earlier — any slow node fails    │
│ CL=EACH_QUORUM      │ WAN latency on every op — APAC p99 worse baseline  │
│ CL=LOCAL_QUORUM     │ Correct DC scope; still fails on hot replica set   │
│ RF=5 LOCAL_QUORUM   │ W=3 — more margin IF 3 healthy nodes remain        │
│                     │ BUT more nodes hit by hint storm — worse cascade   │
└─────────────────────┴────────────────────────────────────────────────────┘
```

### The Answer in One Sentence (memorize)

**LOCAL_QUORUM did not prevent user impact because the incident was a capacity and hot-partition failure on the specific replica set serving correlated keys — quorum guarantees overlapping reads and writes when enough replicas respond in time, but cannot survive a 50× write firehose, compaction debt, and hinted handoff amplification on that replica set.**

### Follow-Up Probes (interviewer may ask)

```
Q: "Would DynamoDB on-demand avoid this?"
A: "Throttling instead of cascade — still user errors, but per-partition
    isolation and Contributor Insights detect hot keys faster. Design fix
    still required."

Q: "Increase RF to 5?"
A: "W=3 needs 3 responsive nodes — more replicas receive hot writes if
    same key — WORSE for identical hot key. RF helps node failure tolerance,
    not skewed key traffic."

Q: "Strong consistency?"
A: "R=W=N=3 makes slowest replica gate every op — fails faster under load."
```


## Question 4: Long-Term Fixes — Architecture and Process

### Principle: Defense in Depth

No single control prevents recurrence. Layer **key design guardrails**, **automated detection**, **capacity headroom**, **change management**, and **runbooks** so a batch job cannot silently melt a vnode arc again.

---

### Architecture Fix 1: Partition Key Schema Enforcement

```
CURRENT (bad):
  session_id = "sg-prod-batch-" + sequential_id
  → correlated hashes → adjacent tokens

TARGET (good):
  session_id = "sg-prod-batch-" + sequential_id + "#" + uuid4()
  OR
  partition_key = hash(user_id)   clustering_key = batch_seq

WHY uuid suffix works:
  murmur3(uuid) decorrelates token placement
  Each session independent vnode — write rate spreads ~1/N nodes

TRADEOFF:
  Range scan on batch prefix requires secondary index or batch table
  → acceptable — batch analytics via separate OLAP pipeline, not KV scan
```

```
IMPLEMENTATION:
  □ JSON Schema / Protobuf validation at API gateway
  □ Reject session_id matching ^sg-prod-batch-\d+$ without random suffix
  □ Cassandra partition key lint in CI (custom static analyzer)

CODE REVIEW CHECKLIST (mandatory for KV writes):
  □ Does partition key have high cardinality?
  □ Any sequential or time-prefix only component?
  □ Expected QPS per key documented vs node budget?
```

### Architecture Fix 2: Per-Partition Rate Monitoring

```
METRICS (export to Prometheus/Datadog):

  cassandra_table_partition_write_rate{keyspace,table,partition}
  top 10 partitions by write rate — alert threshold

  DynamoDB analog:
    Contributor Insights — OperationType Write, TopContributor

ALERT RULES:
  WARNING:  any partition > 5× cluster mean write rate for 5 min
  CRITICAL: any partition > 20× cluster mean OR > 10K writes/sec absolute
  PAGE:     partition rate × RF > single node write capacity estimate

EXAMPLE PromQL (conceptual):
  topk(10, sum by (partition) (rate(cassandra_partition_writes[5m])))
    > 5000
```

```bash
# Weekly automated report — nodetool toppartitions
0 6 * * 1 nodetool toppartitions sessions 50 write > /var/log/top-partitions.log

# AWS DynamoDB Contributor Insights weekly review
aws dynamodb describe-contributor-insights --table-name SessionStore \
  | jq '.ContributorInsightsStatus, .LastUpdateDateTime'
```

### Architecture Fix 3: Coordinator Hot-Key Cache Layer

```
ARCHITECTURE ADDITION:

  Session API
      │
      ▼
  ┌─────────────────┐
  │ Hot-key cache   │  Redis / in-process Caffeine
  │ (read-through)  │  Key: session_id, TTL 30s
  └────────┬────────┘
           │ miss
           ▼
  Cassandra coordinators

  Write path:
    □ Write-through for hot keys detected dynamically
    □ Or write-behind with loss acceptance for last_active only

  Detection:
    Coordinator tracks key QPS — promote to cache at 1K/sec threshold

  Interview: "DynamoDB DAX pattern — same idea"
```

### Architecture Fix 4: Separate Batch Write Path

```
ANTI-PATTERN:
  Batch pre-warm writes same table/CF as interactive sessions

TARGET:
  ┌──────────────────┐     ┌──────────────────┐
  │ sessions_live    │     │ sessions_batch   │
  │ CL LOCAL_QUORUM  │     │ CL ONE / async   │
  │ low latency SLO  │     │ higher latency OK│
  └──────────────────┘     └──────────────────┘
           │                          │
           └──────── merge ───────────┘
                 (stream processor)

  Batch table CL=ONE or even separate cheap object store (S3) + async ingest
  Interactive path never shares partition key space with batch prefixes
```

### Architecture Fix 5: Capacity Headroom SLO

```
NODE CAPACITY MODEL (document in runbook):

  Per-node sustainable write QPS: 3K (measured load test)
  Per-node hard limit: 6K (p99 latency doubles)

  HEADROOM RULE:
    Any single partition's write rate × RF replicas on node ≤ 50% sustainable
    For RF=3 hot key on one primary: hot key QPS < 3K/3 × 0.5 = 500 writes/sec

  Cluster autoscaler:
    Scale nodes on p99 latency AND max-node CPU — NOT average CPU
```

### Architecture Fix 6: Compaction and Disk Governance

```
PREVENT SSTable EXPLOSION:

  □ table compaction strategy: STCS vs LCS vs TWCS
    sessions with TTL → TWCS (time window) if time-series pattern
    random session IDs → STCS with aggressive tombstone_gc

  □ monitoring:
      SSTable count per node alert > 200 (below incident 847)
      compaction_pending_tasks > 20 for 10 min → page

  □ disk: iops provisioning matched to compaction + write amp
      gp3 baseline 3000 IOPS — hot node may need io2 or local NVMe
```

### Architecture Fix 7: Hinted Handoff & Repair Policy

```
TUNING (after architecture fixes — not primary):

  max_hints_in_progress throttle
  hint_window_ms — drop hints older than window if extreme

  Repair schedule:
    □ incremental repair weekly per DC
    □ never full repair during business hours APAC
    □ post-incident: incremental repair hot token ranges only

  gc_grace_seconds:
    ensure tombstones not resurrected during long hint delay
    document: 864000s default — validate for session TTL
```

### Process Fix 1: Shadow Cluster Load Test Gate

```
CHANGE MANAGEMENT:

  Before BATCH-* production deploy:
    □ replay 24h write profile on shadow cluster (10% size)
    □ inject new batch write pattern at 2× expected rate
    □ pass criteria:
        - no node SSTable count > 2× baseline
        - p99 write latency < 50ms at shadow scale
        - toppartitions shows no partition > 10× mean

  CI artifact: load test report attached to change ticket
  Block deploy if fail — no manual override without VP Eng
```

### Process Fix 2: Partition Key Design Review Board

```
MEMBERS: storage team + service owner + SRE

TRIGGERS:
  □ New table / keyspace
  □ New high-QPS write path
  □ Batch job touching KV

DELIVERABLE:
  One-page "Partition Key Risk Assessment"
  signed before merge to main
```

### Process Fix 3: Incident Runbook Updates

```
RUNBOOK ADDITIONS (from this incident):

  P1 Hot Partition Playbook:
    1. nodetool toppartitions <ks> <n> write
    2. identify key prefix / deploy correlation
    3. kill batch source
    4. coordinator rate limit prefix
    5. forbid mass restart — IC verbal confirm
    6. compaction throughput after load drop
    7. repair deferred 24h

  Game day: simulate correlated key batch quarterly in staging
```

### Process Fix 4: Client Resilience Standards

```
SESSION SERVICE CLIENT POLICY:

  □ Exponential backoff on WriteTimeout — max 2 retries
  □ Jitter — prevent synchronized retry storm
  □ Idempotent session PUT (version column / LWT)
  □ Circuit breaker: after 10% failures, shed last_active writes
  □ Fallback: JWT-only auth path for read-only degrade mode

  Cassandra driver:
    speculative retry policy ONLY for idempotent reads — not writes
```

### Process Fix 5: Observability Dashboard (single pane)

```
DASHBOARD: "KV Session Store — Golden Signals"

  Row 1: write/read p99 by DC
  Row 2: error rate WriteTimeout by AZ
  Row 3: max node SSTable count vs mean
  Row 4: system.hints queue depth
  Row 5: top 5 partitions by write rate (live)
  Row 6: deploy markers overlay

  On-call rotates dashboard during APAC peak automatically
```

### Multi-Quarter Roadmap (if interviewer asks "prioritize")

```
Q1 (immediate):
  ✓ Partition key fix + API validation
  ✓ Contributor Insights / toppartitions alerts
  ✓ Runbook + game day

Q2:
  ✓ Shadow load test gate in CI
  ✓ Hot-key cache at coordinator
  ✓ SSTable / compaction alerts

Q3:
  ✓ Batch path separation
  ✓ Incremental repair automation
  ✓ Client circuit breakers standardized

Q4:
  ✓ Evaluate managed DynamoDB Global Tables for session tier
  ✓ Cost / ops retrospective
```

### Success Metrics (post-fix validation)

```
MEASURE 90 DAYS POST-FIX:

  □ Zero partitions > 10K writes/sec sustained
  □ Max node SSTable count < 100 under peak
  □ APAC login p99 < 80ms during batch jobs
  □ Hint queue baseline < 50K always
  □ No P1 storage incidents related to hot partitions

  If metrics fail — architecture fix insufficient, revisit key design
```

### Closing Statement (staff-level interview)

"We don't fix this with CL=ALL or more nodes. We fix partition key cardinality, detect hot partitions before SSTable explosion, isolate batch from interactive paths, and enforce load test gates. LOCAL_QUORUM stays — it's the right consistency for sessions — but quorum math assumes per-partition load within node capacity. Operations and architecture share ownership of that assumption."

---

## Appendix C: Whiteboard Templates for Interview

Copy these templates to paper before the interview starts. Leave space between boxes for interviewer-driven deep dives.

### Template 1: Requirements Snapshot (fill in Phase 1)

```
┌─────────────────────────────────────────────────────────────────────┐
│ DISTRIBUTED KV — REQUIREMENTS                                       │
├─────────────────────────────────────────────────────────────────────┤
│ Ops:        GET / PUT / DELETE                                      │
│ Key size:   _________    Value size: _________                      │
│ R:W ratio:  _________    Peak QPS:  read ______ write ______        │
│ Consistency: □ strong  □ eventual  □ tunable per op                 │
│ Durability:  lose ______ sec on crash OK?                           │
│ Scope OUT:   □ txn  □ range scan  □ search                          │
└─────────────────────────────────────────────────────────────────────┘
```

### Template 2: Capacity Math Block

```
┌──────────────────────────────────────────────────────────────────────┐
│ CAPACITY (3-year)                                                    │
├──────────────────────────────────────────────────────────────────────┤
│ Keys:     ______ × ______ bytes = ______ TB logical                  │
│ RF=___:   × replication = ______ TB                                  │
│ Overhead: +30% compaction → ______ TB total                          │
│ Nodes:    ______ TB / ______ GB per node = ______ nodes              │
│ Peak W BW: ______ QPS × ______ KB × RF = ______ MB/s                 │
│ CHECK: hot key QPS ______ vs node budget ______  ← MUST DO           │
└──────────────────────────────────────────────────────────────────────┘
```

### Template 3: High-Level Architecture

```
                    ┌─────────────┐
                    │   Clients   │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │     LB      │
                    └──────┬──────┘
                           │
              ┌────────────▼────────────┐
              │     Coordinators        │
              │  (stateless, CL aware)  │
              └────────────┬────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
    │ Node A  │◄────►│ Node B  │◄────►│ Node C  │
    │ vnodes  │ gossip│ vnodes  │ gossip│ vnodes  │
    └─────────┘       └─────────┘       └─────────┘
         RF=3, quorum W=__ R=__, hash ring (Week 3)
```

### Template 4: Consistent Hash Ring (Week 3)

```
Token space 0 ──────────────────────────────────────────────► 2^64

      N1      N3           N2       N4      N5
       ●───────●─────────────●────────●───────●
              ↑
         hash(K) lands here
         primary=N3, replicas=N2,N4 (clockwise)

Add N6: only keys between N5-N6 and N6-N1 move (~1/N)

HOT KEY: K* always here — adding nodes doesn't split K*
FIX: K* → K*#uuid or counter shards K*#0..15
```

### Template 5: Quorum Overlap (Week 4)

```
     N=3 replicas {A, B, C}

     Write quorum W=2: ───●───●───  (any 2)
     Read quorum  R=2:      ●───●───  (any 2)

     R+W=4 > N=3 → overlap at ≥1 node → no stale read
     (concurrent writes still conflict — vector clock)

     1 node down: still W=2 of {A,B}? need 2 alive — margin lost
```

### Template 6: Write Path Sequence

```
Client          Coordinator        Replica1   Replica2   Replica3
   │                 │                  │          │          │
   │── PUT K,v ─────►│                  │          │          │
   │                 │── write ────────►│          │          │
   │                 │── write ───────────────────►│          │
   │                 │── write ──────────────────────────────►│
   │                 │◄── ack ──────────│          │          │
   │                 │◄── ack ──────────────────────│          │
   │◄── 200 OK ──────│  (W=2 satisfied)  │          │          │
```

### Template 7: Hinted Handoff (Node Down)

```
Target replica T DOWN for key K

Coordinator → send write to R1 (normal replica)
           → store HINT on R2 for T

        ┌──────┐
        │  T   │  X DOWN
        └──────┘
   ┌──────┐    ┌──────┐
   │  R1  │    │  R2  │ ← hint queued
   └──────┘    └──────┘

T returns UP → R2 replays hints → repair amplification
```

### Template 8: Vector Clock Conflict

```
Concurrent writes (no causal order):

  Replica A: (A:1) value=red
  Replica B: (B:1) value=blue

  Read merge: siblings {red, blue} → app resolves

  After merge write: (A:2)(B:2) value=purple
```

### Template 9: PACELC One-Liner Box

```
┌───────────────────────────────────────────┐
│ PACELC for THIS design                    │
├───────────────────────────────────────────┤
│ If Partition → AP (availability)          │
│ Else → Latency vs Consistency tunable     │
│   CL=ONE fast / QUORUM middle / ALL strong│
└───────────────────────────────────────────┘
```

### Template 10: Monitoring Checklist (prod extension)

```
□ p99 read/write by DC
□ WriteTimeout / Unavailable rate
□ SSTable count max/mean
□ compaction pending
□ hints queue depth
□ top partitions write rate
□ repair progress
□ gc grace tombstone age
```

---

## Practice Problems: Quorum, Hot Keys, Vector Clocks

Fifteen **unique** scenarios. Work each on paper before reading the solution.


### Problem 1: E-Commerce Cart Quorum

**Scenario:**

RF=3, N=3, W=2, R=2. One replica permanently failed. Can writes succeed? Can reads guarantee no stale data?

<details>
<summary>Solution (click to reveal after attempting)</summary>

Writes: YES — 2 of 2 remaining satisfy W=2. Reads: R+W>N still holds for surviving set IF you treat N=2 — but Cassandra still considers RF=3; coordinator may require 2 of 3 and fail if third unreachable. Production: run repair, replace node. Stale read: if dead replica had old data and CL=ONE on misconfigured client, stale possible — QUORUM read from 2 live avoids dead copy.

</details>


### Problem 2: Flash Sale Counter

**Scenario:**

Single key `SKU-8842-qty` receives 50K updates/sec. 200-node cluster RF=3. Why doesn't RF help?

<details>
<summary>Solution (click to reveal after attempting)</summary>

All updates hash to ONE partition primary. 200 nodes × vnodes doesn't split a single key. RF=3 means 3 nodes each get 50K/sec = 150K replica writes/sec on 3 nodes. Fix: sharded counter SKU-8842-qty#0..63 — 64 partitions ~780 updates/sec each.

</details>


### Problem 3: RF=5 W=3 R=3 Network Split

**Scenario:**

Five replicas split 3|2. Minority side 2 nodes. Can minority accept writes with W=3?

<details>
<summary>Solution (click to reveal after attempting)</summary>

NO — only 2 nodes on minority. W=3 unsatisfied. Majority side 3 nodes CAN write W=3. AP: majority continues; minority stale. Heal: vector clocks or LWW merge conflicts on keys written on both sides (if sloppy quorum allowed hints — scenario dependent).

</details>


### Problem 4: DynamoDB RCU Calculation

**Scenario:**

Item size 12 KB. Eventually consistent read. How many RCU?

<details>
<summary>Solution (click to reveal after attempting)</summary>

EC read: ceil(12/4)=3 RCU. Strongly consistent: 2× = 6 RCU. Interview: 4 KB rounding blocks — 12 KB = 3 units not 2.

</details>


### Problem 5: Vector Clock Domination

**Scenario:**

VC1: (A:2,B:1) val=X. VC2: (A:1,B:3) val=Y. Concurrent?

<details>
<summary>Solution (click to reveal after attempting)</summary>

Compare: A:2>1, B:3>1 — neither dominates. Siblings {X,Y}. NOT concurrent if VC2 were (A:2,B:2) after sync — dominates VC1 if B also incremented.

</details>


### Problem 6: LOCAL_QUORUM RF=3 Two DCs

**Scenario:**

RF=6 (3 per DC). LOCAL_QUORUM in us-east. How many local replicas must ack write?

<details>
<summary>Solution (click to reveal after attempting)</summary>

W = floor(3/2)+1 = 2 local us-east replicas. Cross-DC replicas not counted. Latency win vs global QUORUM needing 4 of 6.

</details>


### Problem 7: Hint Storm Estimate

**Scenario:**

Node down 10 min. Hot key 5K writes/sec. RF=3. Rough hints generated?

<details>
<summary>Solution (click to reveal after attempting)</summary>

Writes destined for down replica ≈ 1/3 of 5K = ~1.67K hints/sec × 600 sec ≈ 1M hints (order of magnitude). Actual depends on CL and which replica down. Shows hint replay cost — kill source first.

</details>


### Problem 8: CL=ONE After CL=QUORUM Write

**Scenario:**

Writer uses QUORUM. Reader uses ONE immediately. Stale read possible?

<details>
<summary>Solution (click to reveal after attempting)</summary>

YES — reader may hit lagging replica not in write quorum by luck (unlikely immediately) or replica not yet received write. Fix: R+W>N with same CL, or read-your-writes token routing to coordinator that got write ack.

</details>


### Problem 9: Tombstone Read Amplification

**Scenario:**

Session TTL 30 days. gc_grace 10 days. Node down 15 days. Risk?

<details>
<summary>Solution (click to reveal after attempting)</summary>

Hints delay deletion propagation. Tombstones accumulate. gc_grace exceeded on some replicas → resurrected deleted sessions on repair. Fix: ensure node replacement within gc_grace; incremental repair.

</details>


### Problem 10: Modulo Hash vs Consistent Hash

**Scenario:**

100 nodes. Modulo hash k%100. Add node 101. How many keys move?

<details>
<summary>Solution (click to reveal after attempting)</summary>

~100% keys remap — nearly all data moves. Consistent hash: ~1/101 ≈ 1%. Interview classic.

</details>


### Problem 11: Sloppy Quorum W=2 N=3 One Down

**Scenario:**

Strict quorum: 2 of 3. Sloppy with hint: write to non-replica D + hint. Availability gain?

<details>
<summary>Solution (click to reveal after attempting)</summary>

Write succeeds with 1 live replica + hint on D. Risk: D not in replica set — temporary inconsistency until hint replay. Dynamo availability during failure.

</details>


### Problem 12: R=1 W=3 Stale Read Probability

**Scenario:**

RF=3. W=3 (all). R=1. Write completes. Stale read after write?

<details>
<summary>Solution (click to reveal after attempting)</summary>

After W=3 all replicas updated, R=1 read from any → always fresh for that version. Stale only if concurrent writer elsewhere. W=3 ensures all copies equal before ack.

</details>


### Problem 13: Hot Key Detection Math

**Scenario:**

Cluster 50 nodes, 1B keys uniform. One hot key 10K W/sec. Node budget 2K W/sec. Hot node replicas=3. Fail?

<details>
<summary>Solution (click to reveal after attempting)</summary>

Hot key primary ~10K > 2K budget — FAIL. Uniform keys average 20 writes/sec/node. Hot key 500× over budget. Detection: partition rate alarm > 2K.

</details>


### Problem 14: Vector Clock Size

**Scenario:**

1000-node cluster causal writes. Vector clock size?

<details>
<summary>Solution (click to reveal after attempting)</summary>

Dynamo vector clocks per key track participating nodes — grows with concurrent writers not cluster size. Practical: prune on sync, use dotted version vectors, or switch to hybrid logical clocks for bounded size.

</details>


### Problem 15: TransactWrite Strong Path

**Scenario:**

DynamoDB TransactWrite 2 items different partitions. Consensus mechanism?

<details>
<summary>Solution (click to reveal after attempting)</summary>

DynamoDB uses centralized transaction coordinator + pessimistic locking across partitions — NOT naive quorum overlap. 2PC-style with idempotency tokens. Interview: strong cross-key ≠ single-key R+W math.

</details>


## Mock Interview Transcript Snippets

Use these dialogues to practice verbal pacing. Interviewer lines marked **I:**, candidate **C:**.

### Snippet 1: Opening Clarification (first 3 minutes)

```
I: Design a distributed key-value store like Dynamo.

C: I'll start with requirements. We need get/put/delete by key —
   are range queries in scope?

I: Point lookups only.

C: Read-write ratio and latency targets?

I: Assume 100:1 read-heavy, p99 read under 100 milliseconds.

C: Consistency — can reads be stale?

I: Prefer availability during failures. Eventual is OK unless I specify.

C: Value size and durability?

I: Median 2 KB, max 1 MB. Durability: don't lose acknowledged writes.

C: I'll assume AP-first Dynamo-style, tunable consistency per request,
   single region with multi-DC extension. I'll estimate capacity next,
   then draw coordinators and a consistent hash ring.
```

### Snippet 2: Hot Key Probe (minute 18)

```
I: What if one key gets 50% of traffic?

C: Consistent hashing won't help — one key maps to one primary vnode.
   I'd layer mitigations: first, application key splitting with random
   suffix or counter shards; second, coordinator-side cache for reads;
   third, rate limiting; last, dedicated store for that key pattern.
   Adding nodes alone redistributes other keys, not the hot one.

I: Good. Where would you cache?

C: Between API and coordinators — Redis or in-process with short TTL.
   Write-through or invalidate on write for session-like data.
   I'd also alert on per-partition write rate above 5× mean.
```

### Snippet 3: Quorum Math Trap (minute 22)

```
I: RF=3, W=1, R=1. Strong consistency?

C: No — R+W=2, not greater than N=3. Reader might hit replica that
   missed the write. For strong reads I'd use QUORUM both ways: W=2,R=2,
   sum 4 greater than 3.

I: Does that prevent all conflicts?

C: No — concurrent writes to the same key from two clients both succeed
   with QUORUM can still create siblings. I'd use vector clocks or
   conditional writes with version for merge.
```

### Snippet 4: Node Failure (minute 32)

```
I: A node dies mid-write. What happens?

C: Coordinator detects down replica via gossip. With LOCAL_QUORUM W=2 and
   RF=3, if two remain, write succeeds. For the down replica, hinted
   handoff queues writes on a live node. When it returns, hints replay —
   that can cause load spikes, so I'd monitor hint queue depth.

I: Should we disable hints during incidents?

C: Only in extreme cases — disabling loses durability for that replica's
   share. Better to stop the write source causing the storm first.
```

### Snippet 5: DynamoDB vs Cassandra (follow-up)

```
I: Why not just use DynamoDB?

C: For this exercise the design patterns match — partition key, RF,
   tunable consistency. I'd choose DynamoDB in production for managed
   scaling and Contributor Insights unless we need on-prem or fine-grained
   compaction tuning. The interview architecture transfers either way.
```

### Snippet 6: Vector Clock Sibling (minute 28)

```
I: Two clients write the same key concurrently. Walk me through resolution.

C: With vector clocks, neither write dominates — read returns siblings.
   Application merges: shopping cart unions SKUs, session might pick max
   timestamp for last_active. After merge, client writes merged value
   with updated vector clock incrementing all participants.

I: Why not LWW?

C: Last-write-wins loses data silently — fine for cache, risky for
   counters or carts. I'd LWW only when business accepts loss.
```

### Snippet 7: PACELC (minute 38)

```
I: Where are you on CAP?

C: PACELC is clearer: during partition we choose AP — accept writes
   on available replicas, resolve later. Else we choose latency versus
   consistency via consistency level — ONE for speed, QUORUM balanced,
   ALL when strong. Session store default LOCAL_QUORUM AP within DC.
```

### Snippet 8: Closing Summary (minute 43)

```
C: Summary: AP-first leaderless KV, consistent hashing with vnodes for
   partition placement, quorum for tunable consistency. Hot keys and
   conflict merge are the hard parts — not drawing the ring. I'd monitor
   per-partition rates, SSTable counts, and hints. Production I'd start
   managed unless ops requirements force Cassandra. Happy to deep dive
   anywhere you'd like.

I: That's time. Strong hire signal if you said that.
```

### Snippet 9: Incident Debrief Question

```
I: In the hot partition incident, why didn't LOCAL_QUORUM save us?

C: Quorum needs two local replicas to respond in time for that key's
   token range. We overloaded two of three replicas on the hot arc —
   timeouts, not stale reads. LOCAL_QUORUM is correct for DC scope;
   the fix is partition key design and hot partition detection, not
   changing to CL=ALL.
```

### Snippet 10: Strong Consistency Extension

```
I: Add linearizable reads for one key.

C: Options: R=W=N=RF for that operation — waits for all replicas,
   fails if any slow. Or attach a per-partition Raft group — different
   architecture. Or DynamoDB TransactWrite with version checks for
   compare-and-swap semantics without full linearizable store.
```

---

## Appendix D: Quick Reference Card (Interview Day)

```
┌────────────────────────────────────────────────────────────────────────┐
│ DYNAMO-STYLE KV — 60 SECOND REVIEW                                     │
├────────────────────────────────────────────────────────────────────────┤
│ Hash: consistent hashing + vnodes (Week 3) — hot keys separate fix     │
│ Replication: RF, leaderless, hinted handoff (Week 4)                   │
│ Quorum: R+W>N → no stale read (if no concurrent write)                 │
│ CL: ONE / QUORUM / LOCAL_QUORUM / ALL                                  │
│ Conflicts: vector clocks → siblings → app merge                        │
│ Anti-entropy: read repair + Merkle repair                              │
│ Prod: per-partition metrics, SSTables, hints, compaction               │
│ Managed default: DynamoDB | operable: Cassandra                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

*End of appendix. Merge after Section 12 in `Design Distributed Key-Value Store.md`. Replace duplicate Appendix A/B and placeholder Section 10 content with cross-references to this file.*

---

## Design Gates (mandatory)

Answer these before calling the design complete. Keep responses concise in the
learner notes; compare against the answer key only after attempting the gates.

> Gate template: [`../templates/DESIGN_MODULE_GATES.md`](../templates/DESIGN_MODULE_GATES.md)
> Model responses: [`../answers/Week-13-Infrastructure-Designs/Design Distributed Key-Value Store Answers.md`](../answers/Week-13-Infrastructure-Designs/Design%20Distributed%20Key-Value%20Store%20Answers.md)

### Gate 1 - Authn/z trust boundary

1. Who is authenticated in this design: end user, admin, service, device, worker, tenant, or partner?
2. Where does the first untrusted request cross into your trusted control plane?
3. Which component makes the final authorization decision for each protected object or action?
4. What identity artifact is accepted: session cookie, bearer token, API key, mTLS SPIFFE ID, signed URL, or job identity?
5. What does the system do when the identity provider, policy store, or trust bundle is unavailable?

### Gate 2 - Abuse and misuse

6. Which actor can generate the largest write amplification or fan-out?
7. Which endpoint or background job can be abused while still authenticated?
8. What per-user, per-tenant, per-key, per-IP, per-region, and global quotas are required?
9. What telemetry distinguishes a legitimate flash crowd from abuse or scraping?
10. Which retry policy could amplify a partial outage into a full outage?

### Gate 3 - Multi-tenant isolation, if multi-tenant

11. What is the tenancy model for API, database, cache, queue/topic, search/index, and object storage?
12. Where is tenant context required, and how is it propagated through async jobs and support tools?
13. Which shared resource has reserved capacity or fair-share limits per tenant or tier?
14. How can one tenant be throttled, disabled, migrated, or isolated without affecting others?
15. What test proves a tenant cannot read another tenant's data through cache, search, export, or logs?

### Gate 4 - Unit cost at target scale

16. What is the business unit for cost: request, message, ride, order, document, query, minute, or tenant?
17. At the stated target scale and peak multiplier, what is the rough unit cost?
18. Which line items dominate: compute, storage, replication, egress, NAT, observability, ML inference, third-party APIs, or idle headroom?
19. What cost metric pages before margin, budget, or SLO error budget is breached?
20. What graceful degradation lowers cost without damaging the correctness-critical path?

### Gate 5 - Failure blast radius

21. What is the smallest unit that can fail independently: partition, shard, cell, topic, region, tenant, cache key, model, worker pool, or queue?
22. Which dependencies are shared between critical and non-critical paths?
23. What fails closed, what serves stale, and what can be disabled first?
24. Which runbook action could accidentally widen blast radius?
25. What game day proves the blast radius stays inside the intended boundary?
