# Answer Key - Mock Interview 03 Distributed KV Store

> Open only after attempting the learner file questions.

## Expert Model Answer

### Minute 0–5: Requirements

```
QUESTIONS:

  1. "Consistency — can reads return stale data? How stale is OK?"
     → Seconds OK for carts/sessions; client can request QUORUM

  2. "Read/write ratio?"
     → 80/20 read-heavy

  3. "Value size — median and max?"
     → Median 2 KB, max 1 MB; reject >1 MB or tier to object store

  4. "Durability — survive 1 or 2 node failures?"
     → 2 simultaneous failures per key → RF=3 minimum

  5. "Delete semantics — immediate or tombstone?"
     → Tombstone with grace period for eventual propagation

  6. "Multi-DC — same key writable in two DCs?"
     → Yes for availability; conflict resolution on heal

  7. "1M nodes — one cluster?"
     → No — hierarchical; ~200 nodes per ring, thousands of clusters

CAP STATEMENT:
  "Network partitions will happen at this scale. I choose AP:
   availability + partition tolerance, with tunable consistency
   via quorums. We sacrifice strong consistency globally."

DESIGN DRIVER: Partition tolerance + 99.99% availability → AP + quorums
```

### Minute 5–10: Estimation

```
QPS: 10M aggregate (8M read, 2M write)

PER CLUSTER (200 nodes):
  If 5000 clusters in fleet: 10M / 5000 = 2000 QPS/cluster
  Per node average: 10 QPS — easy

HOT KEY REALITY:
  Top 0.01% keys → 10% traffic = 1M QPS on handful of keys
  → MUST design hot partition mitigation (not average math)

STORAGE:
  100 PB physical with RF=3 → ~33 PB logical keys
  Average value 4 KB → ~8 trillion keys (upper bound check)
  Per 200-node cluster: 100PB / 5000 clusters ≈ 20 TB/node

REPLICATION BANDWIDTH:
  2M writes × 4 KB × 2 replicas = 16 GB/sec replication traffic
  → Acceptable on DC internal network; monitor cap during peak

GOSSIP:
  200 members × 1KB state × periodic = KB/sec — fine
  1M member ring would be GB/sec — why we don't do that
```

### Minute 10–15: API

```
put(key, value, { consistency: QUORUM, ttl: 3600 })
get(key, { consistency: QUORUM })
delete(key, { consistency: QUORUM })

Stored record:
{
  key: "cart:user123",
  value: <bytes>,
  vector_clock: { "nodeA": 3, "nodeC": 1 },
  timestamp: 1712345678,  // for LWW tie-break only
  tombstone: false,
  ttl_expiry: 1712349278
}

Client library:
  - Caches ring topology (refresh every 10s or on error)
  - Retries on coordinator failure (next replica in list)
  - Exposes consistency level per call
```

### Minute 15–25: Architecture

```
"I'll describe a single 200-node cluster; fleet repeats this pattern."

WRITE PATH SUMMARY:
  Client → hash(key) → coordinator vnode → parallel replica writes
  → W acks → success → async completion of remaining replicas

COMPONENTS:
  1. Smart client — ring cache, direct to coordinator (no central proxy)
  2. Storage node — coordinator + replica roles; local RocksDB
  3. Gossip (SWIM) — failure detection, membership diffusion
  4. Anti-entropy daemon — Merkle sync scheduler
  5. Hint manager — temporary ownership during node absence

WHY NO CENTRAL PROXY:
  10M QPS through proxies = proxy fleet bottleneck
  Smart client scales with clients (Dynamo/Cassandra model)

WHY LSM (RocksDB):
  High write throughput, sequential I/O, bloom filters for reads
  Compaction strategy tuned for TTL-heavy workload
```

### Minute 25–40: Deep Dive — Quorum + Hinted Handoff + Anti-Entropy

```
QUORUM CONFIG (default):
  N=3, W=2, R=2
  W+R=4 > N=3 → new write visible to quorum read

  Low-latency reads: R=1 (accept stale)
  Critical reads: R=QUORUM or R=ALL

HINTED HANDOFF (concrete):
  Preference [A,B,C], B dead:
    Write A + D(hint→B) → success
    B returns → D pushes hints → B has full replica set

ANTI-ENTROPY:
  Weekly Merkle sync between replica pairs
  After DC partition heal → priority sync for affected ranges

CONFLICT (partition heal):
  Vector clocks concurrent → application merge OR LWW
  Cart: merge item lists
  Feature flag: higher version wins
  Counter: CRDT increment (if asked)

VNODE COUNT:
  256 per node × 200 nodes = 51200 vnodes on ring
  ~1/51200 keys move per vnode add/remove
```

### Minute 40–45: Failure Modes

```
FAILURE 1: HOT PARTITION
  Cause: key "flash_sale:item42" → 500K QPS to one vnode
  Symptom: p99 latency 500ms on one node; others idle
  Detection: per-vnode QPS metric > 10× cluster median
  Mitigation:
    - Client-side caching (1s TTL for hot keys)
    - Key salting: flash_sale:item42 → flash_sale:item42:{0..7}
      (application merges on read — cost: complexity)
    - Dedicated hot-key service (separate cache tier)
  Prevention: identify hot keys proactively; pre-salt known campaigns

FAILURE 2: SPLIT BRAIN / DIVERGENT REPLICAS
  Cause: Network partition splits {A,B} from {C}; writes on both sides
  Symptom: get() returns different values from different coordinators
  Detection: vector clock divergence; Merkle root mismatch
  Mitigation:
    - Application conflict resolution on read
    - Anti-entropy sync when partition heals
    - For carts: merge; for flags: LWW with timestamp
  Prevention: prefer local-DC quorum during partition (sloppy quorum
    limited to same DC when possible)

FAILURE 3: CASCADING FAILURE
  Cause: Node failure → hints pile on neighbors → disk full →
         more failures → gossip storm → CPU saturation
  Symptom: Cluster-wide latency spike; death spiral
  Detection: hint_backlog, gossip_message_rate, compaction_pending
  Mitigation:
    - Rate limit hinted handoff acceptance
    - Admission control: reject new writes if disk > 85%
    - Circuit breaker on anti-entropy during overload
  Prevention: headroom planning; automated node replacement;
    isolate failing nodes quickly (phi-accrual tuning)

FAILURE 4: REPAIR STORM AFTER MASS FAILURE
  Cause: 20 nodes die in rack failure → massive data rereplication
  Symptom: Network saturation; live traffic starved
  Detection: replication_bytes_sec >> baseline
  Mitigation: Throttle rebuild bandwidth (max 30% of link capacity)
  Prevention: rack-aware replica placement (replicas on different racks)
```

---


---
