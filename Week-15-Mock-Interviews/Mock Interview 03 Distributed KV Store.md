> **Run under** [`00-Curriculum/TIMED_INTERVIEW_OS.md`](../00-Curriculum/TIMED_INTERVIEW_OS.md). Communication scorecard hard gate applies. Use ≥2 interrupts.

# Mock Interview 03 — Design a Distributed Key-Value Store

> **Format:** 45-minute timed mock interview
> **Level:** L5–L6 (Senior / Staff)
> **Prerequisites:** Week 3 (Consistent Hashing, CAP Theorem, Consistency Models), Week 4 (Replication, Sharding), Interview Rubric.md
> **Use this module as:** Interviewer script, self-practice guide, or peer mock with scoring worksheet

---

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS MOCK INTERVIEW, YOU WILL BE ABLE TO:              ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Run or complete a 45-minute distributed KV store          ║
║      interview at Dynamo-style scale (1M+ nodes)               ║
║                                                                ║
║   2. Design partition-tolerant storage with eventual           ║
║      consistency using consistent hashing, virtual nodes,      ║
║      and quorum reads/writes                                   ║
║                                                                ║
║   3. Explain hinted handoff, anti-entropy (Merkle trees),      ║
║      and gossip protocols as production repair mechanisms      ║
║                                                                ║
║   4. Articulate CAP/PACELC trade-offs for a KV store           ║
║      where availability and partition tolerance are P0         ║
║                                                                ║
║   5. Score answers on the 8-dimension rubric with              ║
║      KV-specific calibration                                   ║
║                                                                ║
║   6. Diagnose failure modes: split brain, hot partitions,      ║
║      cascading failures — with detection and mitigation        ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Strong consistency is always better"               ║
╟────────────────────────────────────────────────────────────────────────╢
║   WRONG AT THIS SCALE. At 1M nodes across continents,                  ║
║   partition events are continuous — not edge cases. A KV store         ║
║   optimizing AP (Dynamo, Cassandra, Riak) chooses eventual             ║
║   consistency with tunable quorums. Strong consistency requires        ║
║   coordination that doesn't survive partition + latency SLOs.          ║
╠════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Consistent hashing = perfect load balance"         ║
╟────────────────────────────────────────────────────────────────────────╢
║   WRONG. Without virtual nodes, ring segments are uneven.              ║
║   Even with vnodes, TRAFFIC not KEYS must be balanced — hot            ║
║   keys create hot partitions regardless of hash algorithm.             ║
╠════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Replication factor 3 means always consistent"      ║
╟────────────────────────────────────────────────────────────────────────╢
║   WRONG. RF=3 with W=1, R=1 gives you durability-ish writes            ║
║   with stale reads. Quorum (W+R>N) gives consistency bounds,           ║
║   not magic. Sloppy quorums and hinted handoff add complexity.         ║
╠════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Anti-entropy runs constantly — problem solved"     ║
╟────────────────────────────────────────────────────────────────────────╢
║   WRONG. Merkle tree repair is expensive; rate-limited; runs           ║
║   on schedule (hours). Read repair handles hot keys faster.            ║
║   Anti-entropy catches what read repair misses on cold data.           ║
╠════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "1M nodes = one giant cluster"                      ║
╟────────────────────────────────────────────────────────────────────────╢
║   WRONG. Production systems use hierarchical / multi-datacenter        ║
║   topology: local clusters of 100–1000 nodes, gossip within            ║
║   cluster, cross-DC async replication. 1M nodes is aggregate           ║
║   fleet size, not one membership ring.                                 ║
╠════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Leader election prevents split brain"              ║
╟────────────────────────────────────────────────────────────────────────╢
║   WRONG FOR AP STORES. Dynamo-style systems avoid single               ║
║   leader per key. Split brain = divergent replica versions             ║
║   during partition; resolved via vector clocks + last-write-wins       ║
║   or application-level conflict resolution — not prevented.            ║
╚════════════════════════════════════════════════════════════════════════╝
```

---

## Mock Interview Setup

### Roles and Materials

```
INTERVIEWER NEEDS:
  → This document (Interviewer Script section)
  → Whiteboard / Excalidraw / shared doc
  → Interview Rubric.md scoring worksheet
  → Timer (visible to interviewer only)
  → Problem card (copy Problem Statement section to candidate)

CANDIDATE NEEDS:
  → Problem statement only (do NOT share script or expert answer)
  → Whiteboard tool
  → 45 uninterrupted minutes

OPTIONAL CONSTRAINT CARDS (inject if candidate is ahead):
  → "One datacenter loses network for 30 minutes"
  → "Key 'user:celebrity_123' receives 40% of all traffic"
  → "Client requires linearizable reads for a subset of keys"
```

### Interview Flow Overview

```
╔══════════════════════════════════════════════════════════════════════╗
║   45-MINUTE SCHEDULE                                                 ║
╟──────────────────────────────────────────────────────────────────────╢
║   MIN  0–5  │ Requirements & scope clarification                     ║
║   MIN  5–10 │ Capacity estimation (QPS, storage, replication)        ║
║   MIN 10–15 │ API design & data model                                ║
║   MIN 15–25 │ High-level architecture                                ║
║   MIN 25–40 │ Deep dive (interviewer picks: consistent hash,         ║
║             │             quorums, hinted handoff, or anti-entropy)  ║
║   MIN 40–45 │ Failure modes, wrap-up, candidate questions            ║
╠══════════════════════════════════════════════════════════════════════╣
║   REDIRECT RULE: If candidate proposes strong consistency for        ║
║   all keys by minute 15, probe: "Network partition between           ║
║   US-East and EU-West — what happens to writes?"                     ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Level Calibration

```
L5 BAR:  Consistent hashing + RF=3 + quorum basics; 3 failure modes
L6 BAR:  Vnodes, sloppy quorum, hinted handoff, Merkle repair;
         hot partition mitigation; hierarchical topology
L7 BAR:  PACELC analysis; CRDT vs LWW trade-offs; production ops
         (hinted handoff SLA, entropy bandwidth budgeting); references
         Dynamo/Cassandra papers
```

---

## Problem Statement (Give to Candidate)

```
DESIGN A DISTRIBUTED KEY-VALUE STORE

Design a Dynamo-style distributed key-value storage system for a
large cloud provider. Clients are internal services (not end users)
storing session data, feature flags, shopping cart state, and
configuration blobs.

REQUIREMENTS (stated by interviewer if not asked):

  Functional:
    → put(key, value, ttl?) — write or overwrite
    → get(key) — read latest available value
    → delete(key)
    → Optional: conditional writes (compare-and-swap on version)

  Scale:
    → 1 million+ storage nodes globally (aggregate fleet)
    → 10 million requests per second aggregate read+write
    → Values: 100 bytes to 1 MB (majority < 4 KB)
    → 100 PB total data stored

  Non-functional:
    → High availability: 99.99% for reads and writes
    → Partition tolerant: must operate during network splits
    → Eventual consistency acceptable (stale reads OK within bounds)
    → p99 read latency < 10ms within same datacenter
    → p99 write latency < 20ms within same datacenter
    → Durability: survive simultaneous failure of 2 nodes per key

OUT OF SCOPE (unless candidate has time):
    → SQL queries / secondary indexes (pure KV)
    → Multi-key transactions
    → Strong consistency for all keys

Start by clarifying requirements. You have 45 minutes.
```

---

## Interviewer Script

### Phase 1: Opening (Minute 0–5)

```
SAY:
  "Design a distributed key-value store at Dynamo scale. Ask me
   clarifying questions before you start drawing."

LISTEN FOR:
  → Consistency model (eventual vs strong)
  → Read/write ratio
  → Value size distribution
  → TTL / ephemeral data percentage
  → CAP trade-off articulation (AP vs CP)
  → Conflict resolution strategy
  → Multi-datacenter / multi-region

IF CANDIDATE JUMPS TO DIAGRAM:
  "What's the consistency model? What happens during a partition?"

IF CANDIDATE ASKS FEW QUESTIONS:
  "Is this read-heavy or write-heavy?"
  "Can clients tolerate stale reads? How stale?"
  "What durability guarantee per key?"
```

### Phase 2: Estimation (Minute 5–10)

```
SAY (if candidate doesn't start math):
  "Walk me through storage and QPS math."

EXPECTED ANCHORS:
  → 10M req/sec aggregate given
  → Assume 80/20 read/write → 8M reads, 2M writes/sec
  → 100 PB total given
  → Per node (1M nodes): ~100 TB average ( heterogeneous — OK)
  → With RF=3: logical 33 PB, physical ~100 PB ✓ (sanity check)
  → Metadata per key: ~100 bytes key + pointer; 1B keys × 100B = 100GB
    (order of magnitude check only)

PROBE:
  "What's the per-node QPS if traffic is uniform?"
  → 10M / 1M = 10 req/sec/node average ( trivial — but hot keys break this)
  "What's the real bottleneck?"
  → Hot partitions, NOT average QPS

IF CANDIDATE USES 1M NODE RING:
  "Does gossip scale to 1M members on one ring?"
  → Redirect to hierarchical clusters
```

### Phase 3: API & Data Model (Minute 10–15)

```
SAY (if APIs not defined):
  "Define the client-facing API."

EXPECTED:
  put(key, value, options?)
    options: { ttl_seconds, consistency: ONE | QUORUM | ALL }

  get(key, options?)
    options: { consistency: ONE | QUORUM | ALL }

  delete(key)

  Internal record:
    { key, value, vector_clock, timestamp, ttl_expiry }

PROBE:
  "How does a client know it's reading stale data?"
  → Vector clock / version; client can request QUORUM for fresher read

  "How do you handle a 1 MB value?"
  → Reject or route to blob tier; mention chunking if creative
```

### Phase 4: High-Level Architecture (Minute 15–25)

```
SAY (at minute 15):
  "Draw the architecture. Walk me through a put(key, value)."

EXPECTED COMPONENTS:

  Client Library (smart client)
       │
       ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Consistent Hash Ring → locate coordinator + N replicas │
  └─────────────────────────────────────────────────────────┘
       │
       ▼
  ┌──────────┐    ┌──────────┐    ┌──────────┐
  │ Node A   │    │ Node B   │    │ Node C   │   (RF=3)
  │ (coord)  │───▶│ (replica)│───▶│ (replica)│
  └──────────┘    └──────────┘    └──────────┘
       │
       ▼
  ┌───────────────────────────────────────────────────────────┐
  │  Local storage engine (LSM: LevelDB/RocksDB) per node     │
  └───────────────────────────────────────────────────────────┘

  Gossip protocol for membership / failure detection
  Anti-entropy service (Merkle trees) per node pair

PROBE:
  "Who is the coordinator for a key?"
  "Sync or async replication?"
  "Where does the client run — dumb or smart?"

CONSTRAINT INJECTION (minute 20):
  "US-East and US-West lose connectivity for 30 minutes. Writes
   continue in both. What happens to key K?"
  → Expect: divergent versions, vector clocks, conflict on heal
```

### Phase 5: Deep Dive (Minute 25–40)

```
INTERVIEWER CHOOSES ONE TRACK:

─────────────────────────────────────────────────────────────────────
TRACK A: CONSISTENT HASHING + VNODES (default)
─────────────────────────────────────────────────────────────────────

SAY:
  "Draw the hash ring. A node joins — what moves? A node dies?"

EXPECTED:
  Ring: hash space 0 → 2^128
  Each physical node → 256 virtual nodes on ring
  Key maps to clockwise first vnode

  Node joins: ~1/N keys move to new node (N = node count in cluster)
  Node leaves: keys redistribute to next vnode on ring

  Without vnodes: uneven load; one physical node may own large arc
  With vnodes: load variance ~5-10% at 256 vnodes/node

PROBE:
  "256 vnodes per node — why not 10? Why not 10,000?"
  → 256: good balance (Dynamo paper uses 256)
  → Too few: hot nodes; too many: metadata overhead in gossip

  "How does client know the ring topology?"
  → Gossip propagates membership; client caches ring; refresh on miss

─────────────────────────────────────────────────────────────────────
TRACK B: QUORUM READS/WRITES
─────────────────────────────────────────────────────────────────────

SAY:
  "Replication factor 3. Walk me through W=2, R=2. Why does that
   give you consistency bounds?"

EXPECTED:
  N=3 replicas
  W=2: coordinator waits for 2 acks before write success
  R=2: coordinator reads 2 replicas, returns latest by vector clock

  W + R > N → overlap → read sees latest write (eventual → strong-ish)
  W=1, R=1 → fast but stale reads possible
  W=N, R=1 → write slow, read may still be stale if read wrong node

  SLoppy quorum: if preferred nodes down, write to alternate nodes
  (hinted handoff) — W still met but not on preferred list

PROBE:
  "Coordinator fails mid-write — which replicas have the data?"
  → Hinted handoff + anti-entropy repair divergence

─────────────────────────────────────────────────────────────────────
TRACK C: HINTED HANDOFF
─────────────────────────────────────────────────────────────────────

SAY:
  "Node B is down. Write for key K normally goes to A, B, C.
   Walk me through what happens."

EXPECTED:
  1. Coordinator hashes K → preference list [A, B, C]
  2. B is down (gossip failure detector marked B unavailable)
  3. Coordinator writes to A and D (D is B's temporary substitute)
  4. D stores hint: "this belongs to B when B returns"
  5. B comes back → D pushes hinted data to B → deletes local copy

  Purpose: maintain W acks during temporary failure without
  lowering consistency guarantees permanently

PROBE:
  "B is down for 7 days. D holds hints — disk pressure?"
  → Hint expiration; anti-entropy as backup; alert on hint backlog

─────────────────────────────────────────────────────────────────────
TRACK D: ANTI-ENTROPY (MERKLE TREES)
─────────────────────────────────────────────────────────────────────

SAY:
  "Two replicas diverged during a partition. How do you detect and
   repair without comparing every key?"

EXPECTED:
  1. Each node builds Merkle tree over key ranges (hash of hashes)
  2. Compare root hashes with replica → if match, done
  3. If root differs → compare child buckets → recurse to leaves
  4. Transfer only differing key ranges (efficient sync)

  Runs on schedule (e.g., weekly per replica pair) + triggered after
  node recovery

  Complements read repair: on read, coordinator fetches R replicas,
  returns latest, pushes update to stale replicas (hot keys)

PROBE:
  "Read repair vs anti-entropy — when each?"
  → Read repair: hot keys, low latency fix
  → Anti-entropy: cold keys, comprehensive, expensive
```

### Phase 6: Failure Modes & Wrap-Up (Minute 40–45)

```
SAY:
  "What breaks first at scale? Three failure modes."

PROMPT IF MISSING:
  → Hot partition / celebrity key
  → Split brain / divergent replicas
  → Cascading failure from gossip storm or repair storm

SAY (minute 43):
  "Questions for me?"
```

---

## Candidate Expectations

### By Phase — What "Meets Bar" Looks Like

```
REQUIREMENTS (min 0–5):
  ✓ Accepts eventual consistency; asks how stale
  ✓ CAP: chooses AP for this problem
  ✓ RF=2 or 3 durability requirement
  ✓ Distinguishes 1M fleet vs single ring topology

ESTIMATION (min 5–10):
  ✓ Uses 10M QPS; separates read/write
  ✓ Sanity-checks 100 PB with RF=3
  ✓ Identifies hot keys as real bottleneck (not avg QPS)

API & DATA MODEL (min 10–15):
  ✓ put/get/delete with consistency level parameter
  ✓ Version vector or timestamp for conflict detection
  ✓ TTL support mentioned

ARCHITECTURE (min 15–25):
  ✓ Consistent hashing for partition
  ✓ Coordinator + replicas (RF=3)
  ✓ Smart client or proxy routing
  ✓ Local storage engine per node
  ✓ Gossip for membership

DEEP DIVE (min 25–40):
  ✓ Vnodes explained
  ✓ Quorum W/R/N math
  ✓ OR Hinted handoff flow
  ✓ OR Merkle tree anti-entropy

FAILURE MODES (min 40–45):
  ✓ Hot partition + mitigation (salting, cache)
  ✓ Split brain / divergent writes
  ✓ Cascading failure scenario
```

### Red Flags

```
  ✗ Single global leader (SPoF, doesn't partition-tolerate)
  ✗ hash(key) mod N without consistent hashing
  ✗ Strong consistency for all keys without partition analysis
  ✗ "1M nodes in one gossip ring"
  ✗ No conflict resolution during partition heal
  ✗ Ignore hot key problem at 10M QPS
  ✗ RF=3 with no quorum discussion
```

### Green Flags

```
  ✓ "Dynamo chose AP; Cassandra tunable consistency"
  ✓ W + R > N explained with numeric example
  ✓ Sloppy quorum + hinted handoff for temporary failures
  ✓ Read repair for hot keys + Merkle anti-entropy for cold
  ✓ Hierarchical topology: clusters of 500 nodes, not 1M ring
  ✓ Vector clocks for conflict detection (not naive timestamps)
```

---

## Reference Architecture

### Cluster Topology (1M Node Fleet)

```
GLOBAL FLEET (1M+ nodes) — NOT one ring:

  ┌─────────────────────────────────────────────────────────────────┐
  │                        GLOBAL CONTROL PLANE                     │
  │   Cluster registry │ Capacity planning │ Cross-DC replication   │
  └───────────────────────────────┬─────────────────────────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
  ┌───────────────┐        ┌───────────────┐        ┌───────────────┐
  │  DC: US-EAST  │        │  DC: US-WEST  │        │  DC: EU-WEST  │
  │  50 clusters  │        │  50 clusters  │        │  40 clusters  │
  │  × 200 nodes  │        │  × 200 nodes  │        │  × 200 nodes  │
  │  = 10K nodes  │        │  = 10K nodes  │        │  = 8K nodes   │
  └───────┬───────┘        └───────┬───────┘        └───────┬───────┘
          │                        │                        │
          ▼                        ▼                        ▼
  ┌────────────────────────────────────────────────────────┐
  │ CLUSTER (200 nodes) — one consistent hash ring         │
  │                                                        │
  │    ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐          ┌─────┐ │
  │    │ N1  │  │ N2  │  │ N3  │  │ N4  │     ...  │N200 │ │
  │    │ 256 │  │ 256 │  │ 256 │  │ 256 │          │ 256 │ │
  │    │vnode│  │vnode│  │vnode│  │vnode│          │vnode│ │
  │    └──│──┘  └──│──┘  └──│──┘  └──│──┘          └──│──┘ │
  │       └────────┴────────┴────────┴────────────────┘    │
  │                                                        │
  │ Gossip membership (SWIM)                               │
  │ Anti-entropy (Merkle sync)                             │
  └────────────────────────────────────────────────────────┘

  Cross-DC: async replication (last-write-wins or CRDT per use case)
  Client routing: geo-DNS → local DC cluster → consistent hash
```

### Consistent Hash Ring (Single Cluster)

```
                        hash ring (0 → 2^128)

            vnode C1 ●────────────────────● vnode A3
                   ╱                        ╲
                  ╱                          ╲
       vnode B2 ●                            ● vnode D1
                 │                              │
                 │         KEY "user:42"         │
                 │              ↓                │
                 │         hash → position ●     │
                 │              │                │
                 │    walk clockwise → first vnode
                 │              ↓                │
                 │         coordinator: A3       │
                 │         replicas: D1, B2      │
                 │                              │
       vnode A1 ●                            ● vnode C3
                  ╲                          ╱
                   ╲                        ╱
            vnode D2 ●────────────────────● vnode B1

  Physical node A owns vnodes: A1, A2, A3 (spread on ring)
  Physical node B owns vnodes: B1, B2, B3

  Node failure: vnodes reassigned via gossip-coordinated ring update
  Data movement: only keys in failed node's vnode ranges move
```

### Write Path (Quorum W=2, N=3)

```
put("cart:user123", value, { W: 2 })

  1. Client library hashes key → coordinator = Node A (vnode owner)

  2. Coordinator computes preference list: [A, B, C]

  3. Coordinator writes locally (A) — 1 ack

  4. Coordinator sends replicate request to B and C (parallel)

  5. B acks → 2 acks (W met) → return SUCCESS to client
     (C may still be in flight — async completion OK)

  6. If B is down:
     → Sloppy quorum: write to D with hint for B
     → W=2 met via A + D

  7. Each replica stores:
     { key, value, vector_clock: {A:1, B:1}, timestamp, ttl }

TIMING (same DC):
  Coordinator local write: 1ms
  Network + replica write: 3-5ms
  Total p99 target: < 20ms ✓
```

### Read Path (Quorum R=2, N=3)

```
get("cart:user123", { R: 2 })

  1. Client → Coordinator A

  2. A sends read to B and C (R=2 from {A,B,C})

  3. Collect responses with vector clocks:
     A: {value: v1, clock: {A:2, B:1}}
     B: {value: v1, clock: {A:2, B:1}}  ← same generation
     (if C had {A:1} only → stale, discarded)

  4. Return value with highest clock (merge if concurrent)

  5. READ REPAIR (background):
     If B was stale → A pushes latest value to B

CONSISTENCY:
  W=2, R=2, N=3 → W+R>N → read-after-write for same coordinator
  Not linearizable across all clients without W=N or strong leader
```

### Hinted Handoff Detail

```
NORMAL: key K → preference list [A, B, C]

NODE B DOWN:

  Coordinator A:
    1. Detect B unavailable (gossip phi-accrual or SWIM)
    2. Select D as temporary replica (next in ring)
    3. Write to A (local) + D (with HINT metadata)
    4. D stores: { key: K, value: V, hint: "owner=B", expires: T+7d }

NODE B RECOVERS:

  D:
    1. Gossip detects B is alive
    2. D streams all hinted keys where hint.owner=B to B
    3. B acks → D deletes hinted copies
    4. Preference list [A,B,C] restored

FAILURE CASE — B down too long:
  Hint expires → rely on anti-entropy from A or C to rebuild B
  Alert: hinted_handoff_backlog_bytes > threshold
```

### Anti-Entropy with Merkle Trees

```
Node A and Node B — sync key range [0x0000, 0xFFFF]:

  Step 1: Build Merkle tree (4 levels example)

              root: H(H1,H2)
             /              \
        H(Ha,Hb)          H(Hc,Hd)
        /      \          /      \
      Ha       Hb       Hc       Hd
    keys     keys     keys     keys
   0-3FFF  4000-7FFF 8000-BFFF C000-FFFF

  Step 2: Exchange root hashes
    A.root == B.root → IN SYNC (done, O(1) comparison)

  Step 3: Roots differ → exchange level-2 hashes
    Ha == Hb, Hc != Hd → drill into Hd subtree only

  Step 4: Transfer differing keys in Hd range only

COST CONTROL:
  → Rate limit: 10 MB/sec per replica pair
  → Schedule: round-robin pairs, full scan over 7 days
  → Priority: pairs with recent partition events first
```

---

## Rubric Scoring — Distributed KV Specific

### Dimension 1: Requirements & Scope

```
SCORE 4:
  → Explicit AP choice with partition scenario
  → Asks stale read tolerance (seconds? minutes?)
  → Scopes out secondary indexes / transactions
  → 1M nodes as fleet — asks cluster topology

SCORE 2:
  → Strong consistency for everything
  → Ignores partition tolerance requirement
```

### Dimension 2: Capacity Estimation

```
SCORE 4:
  → 10M QPS split read/write
  → 100 PB with RF=3 sanity check
  → Hot key identified as bottleneck over avg QPS
  → Per-cluster node count derived (not 1M ring)

SCORE 2:
  → No estimation or wrong by 1000×
```

### Dimension 3: API & Data Model

```
SCORE 4:
  → Consistency level on get/put (ONE/QUORUM/ALL)
  → Vector clock or version in stored record
  → TTL for session/cart use cases

SCORE 2:
  → Simple get/put with no consistency tuning
```

### Dimension 4: High-Level Architecture

```
SCORE 4:
  → Consistent hash ring + coordinator pattern
  → RF=3 replicas on distinct nodes/racks
  → Smart client with ring cache
  → Gossip membership
  → Local LSM storage engine

SCORE 2:
  → Single database or single leader
  → mod-N hashing
```

### Dimension 5: Deep Dive

```
SCORE 4 (any track):
  VNODES: join/leave data movement ~1/N; 256 vnodes rationale
  QUORUM: W+R>N with numeric walkthrough
  HINTED HANDOFF: full failure + recovery flow
  ANTI-ENTROPY: Merkle tree drill-down

SCORE 2:
  → Names Dynamo without explaining mechanics
```

### Dimension 6: Trade-offs & Alternatives

```
SCORE 4:
  → AP vs CP (Dynamo vs etcd/Zookeeper)
  → W=1 vs W=QUORUM latency trade-off
  → Read repair vs anti-entropy cost
  → Vector clocks vs LWW vs CRDTs
  → Sloppy quorum availability vs strict quorum consistency

SCORE 2:
  → No alternatives; "eventual consistency is fine" hand-wave
```

### Dimension 7: Failure Modes & Reliability

```
SCORE 4:
  → Hot partition: detection + salting + local cache
  → Split brain: divergent versions + merge on heal
  → Cascading: gossip storm, repair bandwidth saturation
  → Detection: per-partition QPS metrics, hint backlog alerts

SCORE 2:
  → "Replication handles failures"
```

### Dimension 8: Communication & Structure

```
SCORE 4:
  → Logical flow; draw ring before deep dive
  → Manages time; reaches quorum or handoff by min 30

SCORE 2:
  → Random component list; no write path walkthrough
```

### Scoring Worksheet

```
╔═════════════════════════════════════════════════════════════════════╗
║   MOCK INTERVIEW 03 — DISTRIBUTED KV STORE                          ║
╠═════════════════════════════════════════════════════════════════════╣
║   Candidate: _______________  Date: ___________                     ║
║   Interviewer: _____________  Duration: 45 min                      ║
╠═════════════════════════════════════════════════════════════════════╣
║   Dimension                    │ Score (1-4) │ Notes                ║
║   ─────────────────────────────┼─────────────┼──────────────────    ║
║   1. Requirements & Scope        │             │ AP? stale reads?   ║
║   2. Capacity Estimation         │             │ 10M QPS, 100 PB    ║
║   3. API & Data Model            │             │ consistency levels ║
║   4. High-Level Architecture     │             │ ring, RF=3         ║
║   5. Deep Dive                   │             │ track: __________  ║
║   6. Trade-offs & Alternatives   │             │                    ║
║   7. Failure Modes & Reliability │             │ hot/split/cascade  ║
║   8. Communication & Structure   │             │                    ║
║   ─────────────────────────────┼─────────────┼──────────────────    ║
║   TOTAL                          │    /32      │                    ║
╠═════════════════════════════════════════════════════════════════════╣
║   TOP STRENGTH: ___________________________________________         ║
║   TOP GAP:      ___________________________________________         ║
║   NEXT FOCUS:   ___________________________________________         ║
║   HIRE SIGNAL:  [ ] Strong Yes  [ ] Yes  [ ] Lean  [ ] No           ║
╚═════════════════════════════════════════════════════════════════════╝
```

---

> **Answer key (do not open until you attempt the Ops Sim / questions):**
> [`../answers/Week-15-Mock-Interviews/Mock Interview 03 Distributed KV Store Answers.md`](../answers/Week-15-Mock-Interviews/Mock%20Interview%2003%20Distributed%20KV%20Store%20Answers.md)

## Debrief Guide

### Interviewer Debrief Script

```
1. "What was hardest — quorums, handoff, or anti-entropy?"
2. Reveal one gap:
   - No vnodes → draw ring with/without
   - No hot key plan → flash sale scenario
   - 1M node ring → hierarchical topology
3. Share scores on dimensions 5 and 7 (deep dive + failures)
4. Action item: "Read Dynamo paper Section 4 before next mock"
```

### Self-Debrief Checklist

```
[ ] Did I explicitly choose AP and defend it?
[ ] Did I draw consistent hash ring with vnodes?
[ ] Did I explain W+R>N with N=3, W=2, R=2?
[ ] Did I cover hinted handoff OR anti-entropy?
[ ] Did I address hot partitions (not just average QPS)?
[ ] Did I reject 1M-node single ring?
[ ] Did I name split brain and cascading failure?
[ ] Score all 8 dimensions
```

---

## Key Takeaways

```
1. Dynamo-style KV at scale is AP: partition tolerance + availability
   with tunable consistency — not global strong consistency.

2. Consistent hashing with virtual nodes (256/node) minimizes data
   movement on membership change and balances load.

3. Quorum math (W+R>N) is the consistency dial — know the defaults
   and when to turn them (R=1 for speed, QUORUM for freshness).

4. Hinted handoff maintains write availability during temporary node
   failure without permanently violating replica placement.

5. Read repair fixes hot keys fast; Merkle anti-entropy fixes cold
   divergence comprehensively — you need both.

6. 1M nodes means hierarchical clusters (~200/ring), not one gossip
   group — fleet topology is a first-class design decision.

7. Hot partitions are the real scaling enemy at 10M QPS — average
   per-node math is misleading.

8. Split brain produces concurrent versions — vector clocks + app-level
   merge beat naive last-write-wins for cart/session data.
```

---

## Targeted Reading

```
CURRICULUM:
  → Week 3: Consistent Hashing — ring, vnodes, blast radius
  → Week 3: CAP Theorem — AP vs CP positioning
  → Week 3: Consistency Models — eventual, quorum, linearizable
  → Week 4: Replication Strategies — sync/async, failover
  → Week 4: Sharding — hot key mitigation
  → Week 8: CRDTs and Conflict Resolution — when LWW fails
  → Interview Rubric.md

EXTERNAL:
  → Dynamo paper (DeCandia et al., 2007) — Sections 4–5
  → Cassandra architecture docs — tunable consistency
  → Riak vector clocks documentation
  → DDIA Chapter 5 (Replication), Chapter 6 (Partitioning)
  → SWIM gossip protocol paper (Hashicorp memberlist)
```

---

## Appendix: Constraint Injection Cards

```
CARD A (minute 20): NETWORK PARTITION
  "US-East and US-West split for 30 minutes. Both accept writes for
   key K. Walk me through heal."
  → Divergent vector clocks; anti-entropy; app merge policy

CARD B (minute 25): HOT KEY
  "Key 'election:results' gets 40% of 10M QPS. Fix it."
  → Client cache, read replicas for hot key, key splitting, dedicated
    cache cluster, request coalescing (singleflight)

CARD C (minute 30): LINEARIZABLE SUBSET
  "Finance team needs linearizable reads for keys matching 'lock:*'"
  → W=N or Raft partition per lock key; separate CP subsystem;
    don't force linearizability on entire AP store

CARD D (minute 35): NODE JOIN STORM
  "You add 50 nodes at once for capacity. What breaks?"
  → Mass key migration; throttle bootstrap; vnode addition rate limit;
    avoid thundering herd on anti-entropy
```

---

## Appendix: PACELC Analysis

```
PACELC extends CAP: if Partition → choose A or C;
                    Else → choose Latency or Consistency

THIS KV STORE:

  P (partition):     Availability — both sides accept writes
  E (normal):        Latency — W=2 not W=3; R=1 default for speed

Compare to etcd (CP):
  P: Consistency — minority partition rejects writes
  E: Consistency — linearizable reads via Raft

Compare to Cassandra (PACELC same as Dynamo):
  Tunable: LOCAL_QUORUM for DC-local balance

WHEN TO FLIP TO CP SUBSYSTEM:
  Distributed locks, leader election, fencing tokens → use etcd/ZK
  Not the general KV path — hybrid architecture is production norm
```

---

## Appendix: Vector Clock Merge Example

```
PARTITION SCENARIO — shopping cart key "cart:user99"

  Before partition: { items: [A, B] }, clock: {N1:2}

  Partition 1 (nodes A,B):
    Add item C → { items: [A,B,C] }, clock: {N1:3}

  Partition 2 (node C):
    Add item D → { items: [A,B,D] }, clock: {N2:1}

  Partition heals — concurrent clocks:
    {N1:3} vs {N2:1} — neither dominates

  RESOLUTION OPTIONS:
    1. Application merge: items = union([A,B,C], [A,B,D]) = [A,B,C,D]
    2. LWW with timestamp: one side wins (loses C or D — BAD for cart)
    3. CRDT OR-Set: automatic union (preferred for cart use case)

  Store merged result with clock: {N1:4, N2:2} (increment both)
```

---

## Appendix: Gossip Protocol (SWIM) Sketch

```
FAILURE DETECTION (per node):

  Every T seconds:
    1. Pick random peer P
    2. Ping P
    3. If no ack in timeout → indirect ping (ask K peers to ping P)
    4. If still no ack → mark P SUSPECT
    5. If multiple suspect → mark P DEAD
    6. Broadcast membership change via gossip dissemination

  Phi-accrual failure detector: adaptive timeout based on latency history

WHY NOT HEARTBEAT TO CENTRAL COORDINATOR:
  Coordinator SPOF; doesn't scale to 200+ nodes at ms precision

MEMBERSHIP STATE DIFFUSED:
  Each node maintains versioned membership list
  Ring updated when DEAD confirmed → trigger hinted handoff + rebalancing
```

---

## Appendix: Rack-Aware Replica Placement

```
RF=3, cluster has racks R1, R2, R3, R4:

  Preference list for key K: [A, B, C]

  RULE: replicas must be on DISTINCT racks

  A on R1, B on R2, C on R3  ✓

  If R1 fails (A,B,C affected if naive):
    Rack-aware: only one replica per rack lost
    Quorum may survive with nodes on R2, R3

  Prevents single rack failure from losing quorum for key range
```
