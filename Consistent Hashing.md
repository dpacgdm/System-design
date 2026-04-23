# Week 3, Topic 3: Consistent Hashing

---

## Step 1: Learning Objectives

```
┌──────────────────────────────────────────────────────────────┐
│  AFTER THIS TOPIC, YOU WILL BE ABLE TO:                      │
│                                                              │
│  1. Explain WHY naive hash-mod-N breaks catastrophically     │
│     when nodes are added or removed, with exact math         │
│                                                              │
│  2. Draw and explain the consistent hashing ring, including  │
│     how keys are assigned to nodes and what happens when     │
│     a node joins or leaves                                   │
│                                                              │
│  3. Explain virtual nodes (vnodes) — why they exist, the     │
│     math behind how many you need, and the tradeoff of       │
│     more vs fewer vnodes                                     │
│                                                              │
│  4. Describe how Cassandra, DynamoDB, and Redis Cluster      │
│     each implement (or diverge from) consistent hashing      │
│     and WHY they made different choices                      │
│                                                              │
│  5. Calculate the blast radius of a node failure in a        │
│     consistent hashing ring (how much data moves, which      │
│     nodes absorb it)                                         │
│                                                              │
│  6. Diagnose hot-partition problems in production systems    │
│     using consistent hashing and prescribe fixes             │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 2: Core Teaching

### The Problem: Why We Need Consistent Hashing

```
SCENARIO: You have a distributed cache with 4 nodes.
You need to decide which node stores each key.

THE NAIVE APPROACH: hash(key) mod N

  node = hash(key) % 4
  
  key="user:1001" → hash=7423  → 7423 % 4 = 3 → Node 3
  key="user:1002" → hash=9281  → 9281 % 4 = 1 → Node 1
  key="user:1003" → hash=5540  → 5540 % 4 = 0 → Node 0
  key="user:1004" → hash=3817  → 3817 % 4 = 1 → Node 1

  This works fine. Keys are distributed roughly evenly 
  across 4 nodes. Simple, fast, deterministic.

THE PROBLEM: Add a 5th node.

  Now N = 5. EVERY key gets rehashed:
  
  key="user:1001" → 7423 % 5 = 2 → Node 2  (was Node 3!)
  key="user:1002" → 9281 % 5 = 1 → Node 1  (same)
  key="user:1003" → 5540 % 5 = 0 → Node 0  (same)
  key="user:1004" → 3817 % 5 = 2 → Node 2  (was Node 1!)

  How many keys moved?
```

#### The Math of Catastrophe

```
When you go from N nodes to N+1 nodes with hash-mod-N:

  Fraction of keys that STAY on the same node: 1/(N+1)
  
  Wait — that's not right intuitively. Let me be precise.
  
  For a key to stay on the same node:
    hash(key) % N == hash(key) % (N+1)
  
  This only happens when hash(key) is a multiple of 
  both N and N+1, which means it's a multiple of 
  LCM(N, N+1) = N × (N+1) [since consecutive integers 
  are coprime].
  
  Probability: 1/N × 1/(N+1) × N(N+1)... 
  
  Actually, the simpler way to think about it:

  For N → N+1:
    Approximately N/(N+1) of keys MOVE.
    Only ~1/(N+1) stay on the same node.

  N=4 → N=5:  ~80% of keys move (4/5)
  N=10 → N=11: ~91% of keys move
  N=100 → N=101: ~99% of keys move

  REMOVING a node is equally catastrophic:
  N=5 → N=4:  ~80% of keys move

THIS IS A DISASTER IN PRODUCTION:

  You have 100 cache servers. You add 1 more (scaling up 
  for a traffic spike).
  
  hash-mod-N: 99% of cached data is now on the WRONG server.
  → 99% cache miss rate
  → All 99% of requests hit the database simultaneously
  → Database instantly overloaded
  → You added a server to HELP with load, and instead 
    you caused a cache stampede that takes down the DB
  
  Same problem in reverse: one server crashes.
  → N goes from 100 to 99
  → 99% of keys rehash to different servers
  → 99% cache miss → DB stampede → cascade failure

  Adding or removing a SINGLE node invalidates nearly 
  ALL your cached data. This makes the system fragile 
  to any topology change.
```

### The Solution: Consistent Hashing

```
CORE IDEA (Karger et al., 1997):

  Instead of hash(key) % N, place both KEYS and NODES 
  on a circular hash space (a "ring"). Each key is 
  assigned to the nearest node CLOCKWISE on the ring.

THE RING:

  Imagine a circle representing the full hash space 
  (0 to 2^32 - 1, or 0 to 2^128, or 0 to 2^256):

                        0 / 2^32
                          │
                    ┌─────┴─────┐
                 ╱                 ╲
               ╱                     ╲
             ╱                         ╲
            │                           │
   3/4 ─────┤         HASH RING         ├───── 1/4
   of space │                           │ of space
             ╲                         ╱
               ╲                     ╱
                 ╲                 ╱
                    └─────┬─────┘
                          │
                       1/2 of space

  STEP 1: Hash each NODE to a position on the ring.
  
    hash("Node-A") = 0.15  (15% around the ring)
    hash("Node-B") = 0.42  (42% around the ring)
    hash("Node-C") = 0.68  (68% around the ring)
    hash("Node-D") = 0.91  (91% around the ring)

  Place them on the ring:

                       0.0
                        │
                   ╱────┴────╲
                ╱               ╲
              ╱    A (0.15)       ╲
             │     ●               │
             │                     │
    D (0.91) ●                     ● B (0.42)
             │                     │
             │                     │
              ╲                  ╱
                ╲    C (0.68) ╱
                  ╲  ●      ╱
                    ╲──┬──╱
                       │
                      0.5

  STEP 2: To find which node owns a key, hash the key 
  and walk CLOCKWISE until you hit a node.

    hash("user:1001") = 0.23
    Walk clockwise from 0.23 → next node is B (0.42)
    → "user:1001" is stored on Node B

    hash("user:1002") = 0.55
    Walk clockwise from 0.55 → next node is C (0.68)
    → "user:1002" is stored on Node C

    hash("user:1003") = 0.95
    Walk clockwise from 0.95 → wraps past 0.0 → 
    next node is A (0.15)
    → "user:1003" is stored on Node A

  EACH NODE OWNS a range of the ring:
    Node A: (0.91, 0.15]  → 24% of ring
    Node B: (0.15, 0.42]  → 27% of ring
    Node C: (0.42, 0.68]  → 26% of ring
    Node D: (0.68, 0.91]  → 23% of ring
```

### What Happens When a Node Joins or Leaves

```
THIS IS WHERE CONSISTENT HASHING SHINES.

NODE LEAVES (Node C crashes):

  Before:
    A owns (0.91, 0.15]
    B owns (0.15, 0.42]
    C owns (0.42, 0.68]  ← this node crashes
    D owns (0.68, 0.91]

  After C is removed:
    A owns (0.91, 0.15]   ← UNCHANGED
    B owns (0.15, 0.42]   ← UNCHANGED
    D owns (0.42, 0.91]   ← EXPANDED (absorbed C's range)

                       0.0
                        │
                   ╱────┴────╲
                ╱               ╲
              ╱    A (0.15)       ╲
             │     ●               │
             │                     │
    D (0.91) ●                     ● B (0.42)
             │                     │
             │     C's range       │
              ╲    → goes to D   ╱
                ╲              ╱
                  ╲──┬──────╱
                     │
                    0.5

  WHAT MOVED:
    → Only C's keys moved (to D)
    → A's keys: untouched
    → B's keys: untouched
    → D absorbs C's ~26% of the ring

  FRACTION OF KEYS THAT MOVED: ~1/N (≈25% with 4 nodes)
  Compare to hash-mod-N: ~75% would have moved!

NODE JOINS (Node E added at position 0.55):

  Before:
    A owns (0.91, 0.15]
    B owns (0.15, 0.42]
    C owns (0.42, 0.68]
    D owns (0.68, 0.91]

  After E joins at 0.55:
    A owns (0.91, 0.15]   ← UNCHANGED
    B owns (0.15, 0.42]   ← UNCHANGED
    C owns (0.55, 0.68]   ← SHRUNK (gave some range to E)
    D owns (0.68, 0.91]   ← UNCHANGED
    E owns (0.42, 0.55]   ← NEW (took from C)

  WHAT MOVED:
    → Only keys in the range (0.42, 0.55] moved from C to E
    → All other keys: untouched

  FRACTION OF KEYS THAT MOVED: ~1/N (≈13% from C to E)

THE GUARANTEE:
┌─────────────────────────────────────────────────────┐
│                                                     │
│  When a node joins or leaves:                       │
│    → Only ~K/N keys need to move                    │
│      (K = total keys, N = total nodes)              │
│    → Only the NEIGHBORING node(s) are affected      │
│    → All other nodes and keys are untouched         │
│                                                     │
│  hash-mod-N: ~K×(N-1)/N keys move (nearly all)      │
│  consistent hashing: ~K/N keys move (minimum)       │
│                                                     │
│  This is OPTIMAL — you can't do better than K/N     │
│  because the new/removed node must take/give up     │
│  its fair share.                                    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### The Problem with Basic Consistent Hashing: Non-Uniform Distribution

```
With only N physical nodes on the ring, the ranges 
are likely to be UNEVEN:

  4 nodes placed randomly on the ring might land at:
    0.05, 0.12, 0.78, 0.95
  
  Ranges:
    Node 1: (0.95, 0.05] =  10% of ring
    Node 2: (0.05, 0.12] =   7% of ring
    Node 3: (0.12, 0.78] =  66% of ring  ← HOT!
    Node 4: (0.78, 0.95] =  17% of ring

  Node 3 owns 66% of all keys! That's ~10x the load 
  of Node 2. This creates a massive hot spot.

  WITH FEW NODES, RANDOM PLACEMENT PRODUCES UNEVEN 
  DISTRIBUTION. The standard deviation of load per 
  node with N nodes is O(1/√N):
  
  4 nodes:   expected 25% each, std dev ≈ 25%
             → actual range: 0% to 50% (terrible)
  100 nodes: expected 1% each, std dev ≈ 1%
             → actual range: 0% to 2% (acceptable)

  With a small number of physical nodes (3-20, which 
  is typical), the distribution is unacceptably uneven.
```

### Virtual Nodes (Vnodes): The Solution

```
IDEA: Instead of placing each physical node at ONE 
position on the ring, place it at MANY positions.

Each physical node creates V "virtual nodes" (vnodes), 
each at a different position on the ring.

EXAMPLE: 4 physical nodes, 8 vnodes each (32 total):

  Physical Node A → vnodes: A-0, A-1, A-2, ..., A-7
  Physical Node B → vnodes: B-0, B-1, B-2, ..., B-7
  Physical Node C → vnodes: C-0, C-1, C-2, ..., C-7
  Physical Node D → vnodes: D-0, D-1, D-2, ..., D-7

  Each vnode is hashed to a position on the ring:
    hash("A-0") = 0.03
    hash("B-0") = 0.06
    hash("A-1") = 0.11
    hash("C-0") = 0.14
    hash("D-0") = 0.19
    hash("B-1") = 0.23
    ... (32 positions total)

  The ring now has 32 evenly-ish distributed points 
  instead of 4:

    ●B ●A  ●C ●D  ●B ●A  ●D ●C  ●A ●B  ●C ●D  ...
    ────────────────────────────────────────────────►
    0.0                                           1.0

  Because there are 32 points instead of 4, the 
  distribution is MUCH more uniform.

  Node A owns the ranges behind each of its 8 vnodes.
  Total: approximately 8/32 = 25% (close to ideal).

THE MATH OF VNODES:

  With V vnodes per physical node and N physical nodes:
  → Total ring positions: V × N
  → Expected load per physical node: 1/N (perfect)
  → Standard deviation of load: O(1/√(V×N))
  
  V=1 (no vnodes), N=4:   std dev ≈ 50% of mean
  V=8, N=4 (32 total):    std dev ≈ 18% of mean
  V=32, N=4 (128 total):  std dev ≈ 9% of mean
  V=128, N=4 (512 total): std dev ≈ 4% of mean
  V=256, N=4 (1024 total): std dev ≈ 3% of mean

  MORE VNODES = MORE UNIFORM DISTRIBUTION.
  
  Diminishing returns past ~100-200 vnodes per node.
  Most production systems use 128-256 vnodes per node.
```

#### Vnodes and Node Departure/Arrival

```
VNODES ALSO IMPROVE REBALANCING.

Without vnodes (1 position per node):
  Node C crashes → ALL of C's data goes to ONE node (D)
  → D now has 2x the data and 2x the traffic
  → D becomes the hot spot

  ┌───────────────────────────────────────────────┐
  │                                               │
  │  Before: A=25%, B=25%, C=25%, D=25%           │
  │  After C crashes: A=25%, B=25%, D=50%         │
  │  D is instantly overloaded.                   │
  │                                               │
  └───────────────────────────────────────────────┘

With vnodes (many positions per node):
  Node C crashes → C's vnodes are scattered across the ring
  → Each of C's vnodes is absorbed by a DIFFERENT successor
  → The load spreads across multiple surviving nodes

  ┌───────────────────────────────────────────────┐
  │                                               │
  │  Ring with vnodes:                            │
  │  ...●A ●C ●B ●D ●C ●A ●C ●B ●D ●A ●C ●D...    │
  │                                               │
  │  C crashes. Each C-vnode's range goes to the  │
  │  next non-C vnode clockwise:                  │
  │                                               │
  │  C-0's range → goes to B (the next node)      │
  │  C-1's range → goes to A                      │
  │  C-2's range → goes to B                      │
  │  C-3's range → goes to D                      │
  │  ...                                          │
  │                                               │
  │  Result: C's 25% is distributed roughly:      │
  │  A absorbs ~8%, B absorbs ~8%, D absorbs ~9%  │
  │                                               │
  │  After: A≈33%, B≈33%, D≈34%                   │
  │  EVEN distribution of C's load!               │
  │                                               │
  └───────────────────────────────────────────────┘

THIS IS CRITICAL for production systems. When a node 
fails, you want the load to spread EVENLY across all 
surviving nodes, not dump onto one node (which would 
then also fail under the extra load, causing a cascade).
```

#### The Vnodes Tradeoff

```
MORE VNODES IS NOT ALWAYS BETTER:

┌───────────────────┬───────────────────────────────────┐
│ MORE VNODES       │ FEWER VNODES                      │
├───────────────────┼───────────────────────────────────┤
│ Better uniformity │ Worse uniformity                  │
│ Better rebalancing│ Rebalancing creates hot spots     │
│ (load spreads     │ (load dumps onto one neighbor)    │
│  across all nodes)│                                   │
├───────────────────┼───────────────────────────────────┤
│ More metadata     │ Less metadata                     │
│ (ring has V×N     │ (ring has N entries)              │
│  entries to store │                                   │
│  and replicate)   │                                   │
├───────────────────┼───────────────────────────────────┤
│ Slower ring       │ Faster ring lookups               │
│ lookups (more     │                                   │
│ entries to search)│                                   │
├───────────────────┼───────────────────────────────────┤
│ Slower rebalancing│ Faster rebalancing                │
│ (more ranges to   │ (fewer, larger ranges to move)    │
│  move, each small)│                                   │
├───────────────────┼───────────────────────────────────┤
│ More repair       │ Less repair traffic               │
│ traffic (Cassandra│                                   │
│ repairs are per-  │                                   │
│ vnode range)      │                                   │
└───────────────────┴───────────────────────────────────┘

PRODUCTION CHOICES:

  Cassandra (pre-3.0):   256 vnodes per node (default)
  Cassandra (3.0+):      Reduced to 16-32 vnodes
    → Why? 256 vnodes caused excessive repair traffic 
      and slow streaming during node replacement.
      With improved token allocation algorithms, 
      16-32 vnodes achieve similar uniformity.
  
  DynamoDB: Does NOT use vnodes. Uses a different 
    approach (covered below).
  
  Redis Cluster: Does NOT use vnodes. Uses fixed 
    16384 hash slots (covered below).
```

### How Real Systems Implement This

#### Cassandra: Consistent Hashing with Vnodes

```
Cassandra uses consistent hashing as its CORE 
data distribution mechanism.

THE RING:
  → Hash space: -2^63 to +2^63 (Murmur3 hash)
  → Each node owns multiple TOKEN RANGES
  → Tokens = positions on the ring
  → Default: num_tokens: 16 (configurable in cassandra.yaml)

  # In cassandra.yaml:
  num_tokens: 16

PARTITION KEY → TOKEN → NODE:

  Every table has a PARTITION KEY. The partition key 
  determines which node owns the data.

  CREATE TABLE users (
      user_id UUID PRIMARY KEY,
      name text,
      email text
  );

  INSERT INTO users (user_id, name, email) 
  VALUES (550e8400-e29b-41d4-a716-446655440000, 
          'Alice', 'alice@example.com');

  Cassandra computes:
    token = murmur3(550e8400-e29b-41d4-a716-446655440000)
    token = -4069959284402364209 (some 64-bit integer)
    → Walk the ring clockwise → find the node that owns 
      the range containing this token

VIEWING THE RING:

  $ nodetool ring

  Address     Rack   Status  Load       Owns   Token
  10.0.0.1    rack1  Up      125.6 GB   24.8%  -9223372036854775808
  10.0.0.1    rack1  Up      125.6 GB   24.8%  -7686143364045646507
  10.0.0.2    rack1  Up      131.2 GB   25.6%  -6148914691236517206
  10.0.0.2    rack1  Up      131.2 GB   25.6%  -4611686018427387905
  10.0.0.3    rack2  Up      119.8 GB   23.1%  -3074457345618258604
  ...
  (each node appears multiple times — once per vnode)

  $ nodetool describering <keyspace>
  → Shows exact token ranges and which node owns each

REPLICATION:
  Cassandra combines consistent hashing with replication:
  
  With RF=3 (replication factor 3):
  → A key is stored on the PRIMARY node (clockwise successor)
  → PLUS the next 2 nodes clockwise on the ring
  → These 3 nodes form the key's "replica set"

                 ●A    ●B    ●C    ●D    ●A    ●B
  ──────────────────────────────────────────────────►
                       ▲
                  key lands here
                  
  Primary: B (clockwise successor)
  Replica 1: C (next clockwise)
  Replica 2: D (next clockwise)
  
  Key is stored on B, C, and D.

  WITH NetworkTopologyStrategy (multi-datacenter):
  → RF=3 per datacenter
  → Key is replicated to 3 nodes in DC1 AND 3 in DC2
  → Nodes are chosen to be in different RACKS 
    (for fault tolerance)

NODE JOINS IN CASSANDRA:
  1. New node announces itself to the cluster (via gossip)
  2. New node is assigned tokens (positions on the ring)
  3. Existing nodes STREAM data for the new node's ranges
  4. Once streaming completes, new node starts serving traffic
  5. Other nodes stop serving the ranges now owned by new node

  The key insight: only data in the new node's ranges 
  is streamed. The rest of the cluster is unaffected.
```

#### DynamoDB: Consistent Hashing Without Vnodes

```
DynamoDB uses a MODIFIED consistent hashing approach.

Instead of vnodes, DynamoDB uses:
  → Fixed partitions (similar to Redis Cluster's slots)
  → Partitions are assigned to storage nodes
  → When capacity changes, partitions SPLIT or MERGE

THE PARTITION SPLIT:

  Initially: Partition P1 covers range [0, 1000)
  P1 is on Node A.
  
  Traffic to P1 increases beyond Node A's capacity.
  
  DynamoDB SPLITS P1:
    P1a covers [0, 500)    → stays on Node A
    P1b covers [500, 1000) → moves to Node B
  
  Only the data in [500, 1000) moves. Minimal disruption.

WHY NOT VNODES?
  → DynamoDB is a managed service. AWS controls the 
    infrastructure topology.
  → Partition splitting gives finer-grained control 
    over where data lives
  → Allows automatic scaling without operator intervention
  → Vnodes are an operator-friendly approach; partition 
    splitting is an automation-friendly approach

HOT PARTITION HANDLING:
  DynamoDB can detect a hot partition (one that receives 
  disproportionate traffic) and split it further, moving 
  the hot range to a less-loaded node.
  
  This is "adaptive" consistent hashing — the ring 
  topology changes based on actual traffic patterns, 
  not just hash uniformity.
```

#### Redis Cluster: Fixed Hash Slots

```
Redis Cluster uses a SIMPLIFIED version of consistent 
hashing with FIXED SLOTS.

  → Hash space: 16384 slots (0 to 16383)
  → Key → slot: CRC16(key) mod 16384
  → Each node is assigned a RANGE of slots
  → No ring walking — direct slot-to-node mapping table

EXAMPLE (3-node cluster):
  Node 1: slots 0-5460      (5461 slots)
  Node 2: slots 5461-10922  (5462 slots)
  Node 3: slots 10923-16383 (5461 slots)

  SET user:1001 "Alice"
  → CRC16("user:1001") = 7438
  → 7438 mod 16384 = 7438
  → Slot 7438 → Node 2

WHY 16384?
  → Each node must know the slot→node mapping for ALL slots
  → This mapping is exchanged via gossip protocol
  → With 16384 slots, the mapping is a 16KB bitmap
    (2 bytes per slot for node ID)
  → 16KB is small enough to exchange in heartbeat messages
  → With 65536 slots, it would be 64KB — too large for 
    frequent gossip exchange

WHY NOT A TRUE RING WITH VNODES?
  → Redis Cluster is designed for SIMPLICITY
  → Fixed slots are easier to reason about
  → Resharding is explicit: operator moves slot ranges 
    between nodes
  → No need for complex ring metadata replication

ADDING A NODE:
  When you add Node 4 to a 3-node cluster:
  → You must MANUALLY (or via redis-cli --cluster) 
    move slots from existing nodes to Node 4
  → redis-cli --cluster reshard <node>
  → This moves slots one at a time (or in batches)
  → During migration, a slot is in "MIGRATING" state 
    on the source and "IMPORTING" on the destination
  → Clients that hit the migrating slot get a MOVED or 
    ASK redirect

  After resharding:
    Node 1: slots 0-4095      (4096 slots)
    Node 2: slots 4096-8191   (4096 slots)
    Node 3: slots 8192-12287  (4096 slots)
    Node 4: slots 12288-16383 (4096 slots)

RECALL FROM WEEK 2:
  The Redis slot imbalance in the boxing platform scenario 
  was caused by Kubernetes pod restarts accumulating slots 
  on surviving nodes. This is because Redis Cluster does 
  NOT automatically rebalance slots — it requires explicit 
  resharding. This is a direct consequence of the fixed-
  slot design: simpler, but requires operator intervention.
```

### Comparing the Three Approaches

```
┌──────────────┬──────────────────┬──────────────────┬──────────────────┐
│              │ CASSANDRA        │ DYNAMODB         │ REDIS CLUSTER    │
│              │ (Vnodes)         │ (Partition Split)│ (Fixed Slots)    │
├──────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Hash function│ Murmur3          │ Internal (MD5    │ CRC16            │
│              │                  │ based)           │                  │
├──────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Ring/Space   │ -2^63 to +2^63  │ Internal ranges  │ 0 to 16383        │
│ size         │                  │                  │ (16384 slots)    │
├──────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Granularity  │ 16-256 tokens   │ Automatic        │ 16384 fixed       │
│ of placement │ per node         │ partition splits │ slots            │
├──────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Rebalancing  │ Automatic on     │ Fully automatic  │ MANUAL           │
│              │ node join/leave  │ (managed service)│ (operator must   │
│              │                  │                  │ reshard)         │
├──────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Node failure │ Load spreads to  │ Automatic        │ Replica promoted │
│ behavior     │ multiple nodes   │ failover to      │ for affected     │
│              │ (vnode neighbors)│ healthy nodes    │ slots. Load NOT  │
│              │                  │                  │ spread evenly.   │
├──────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Hot spot     │ Split token      │ Automatic        │ Manual slot      │
│ handling     │ range (manual)   │ partition split  │ migration        │
├──────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Metadata     │ Token ring       │ Partition map    │ 16KB slot bitmap │
│ overhead     │ (V×N entries)    │ (internal)       │ (fixed size)     │
├──────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Best for     │ Large clusters,  │ Variable scale,  │ Simple caching,  │
│              │ self-managed     │ managed service  │ known cluster    │
│              │ infrastructure   │                  │ size             │
└──────────────┴──────────────────┴──────────────────┴──────────────────┘
```

### Consistent Hashing for Load Balancing

```
Consistent hashing isn't just for databases. It's used 
in LOAD BALANCERS too.

USE CASE: Sticky sessions without a session store.

  Traditional load balancing: round-robin
  → Request 1 → Server A
  → Request 2 → Server B  (different server!)
  → User's session state is on A, not B → broken

  Hash-based load balancing:
  → hash(client_IP) → always routes to the same server
  → But: if a server is added/removed, hash-mod-N 
    reshuffles nearly ALL clients

  Consistent hashing load balancing:
  → Servers are placed on a ring
  → hash(client_IP) → walk clockwise → server
  → If a server is removed, only ITS clients move
    to the next server. All other clients stay.

  Used by:
  → Nginx (upstream consistent hash)
  → HAProxy (hash-type consistent)
  → Envoy (ring hash load balancer)
  → Maglev (Google's load balancer — uses a different 
    algorithm called "Maglev hashing" that provides 
    even better uniformity)

  # Nginx configuration:
  upstream backend {
      hash $request_uri consistent;
      server 10.0.0.1;
      server 10.0.0.2;
      server 10.0.0.3;
  }
  
  # HAProxy configuration:
  backend servers
      balance source
      hash-type consistent
      server s1 10.0.0.1:80
      server s2 10.0.0.2:80
      server s3 10.0.0.3:80

CDN ROUTING:
  CDNs use consistent hashing to decide which edge 
  server caches which content:
  
  hash(URL) → edge server
  
  This ensures the same URL always goes to the same 
  edge server → maximizes cache hit rate. If an edge 
  server is removed, only its URLs move to the next 
  server. Cache hit rate drops minimally.
```

### Consistent Hashing + Replication: Putting It Together

```
In a real distributed database, consistent hashing 
determines BOTH placement AND replication:

CASSANDRA EXAMPLE (RF=3, 6 nodes, vnodes simplified):

  Ring positions (simplified — no vnodes for clarity):
  
  ●A (0°) → ●B (60°) → ●C (120°) → ●D (180°) → ●E (240°) → ●F (300°)

  Key K hashes to position 75° (between A and B).
  
  Primary replica: B (first node clockwise from 75°)
  Replica 2: C (second node clockwise)
  Replica 3: D (third node clockwise)

  WRITE PATH (CL=QUORUM, RF=3):
    Coordinator receives write for key K.
    → Sends write to B, C, D (the 3 replicas)
    → Waits for 2 of 3 ACKs (QUORUM = ⌊3/2⌋ + 1 = 2)
    → ACKs the write to the client

  READ PATH (CL=QUORUM, RF=3):
    Coordinator receives read for key K.
    → Sends read to B, C, D
    → Waits for 2 of 3 responses
    → Returns the MOST RECENT value (by timestamp)
    → If responses DISAGREE: triggers read-repair
      (sends the newest value to the stale replica)

  NODE B CRASHES:
    → Key K's replicas are now: C, D (only 2 surviving)
    → CL=QUORUM (2) still achievable ✓
    → Reads and writes for K continue without interruption
    → Cassandra starts "hinted handoff" — 
      writes meant for B are stored temporarily on 
      another node and replayed when B recovers

  NODES B AND C CRASH:
    → Key K's replicas: only D survives (1 of 3)
    → CL=QUORUM (2) NOT achievable ✗
    → Reads/writes at QUORUM fail for key K
    → CL=ONE still works (can read from D)
    → This is the CAP tradeoff in action:
      QUORUM = CP (refuses when can't guarantee consistency)
      ONE = AP (serves from whatever's available)
```

---

## Step 3: Production Patterns & Failure Modes

```
┌──────────────────────────────────────────────────────────────┐
│  FAILURE MODE #1: HOT PARTITION                              │
│                                                              │
│  Scenario: Social media. Posts are partitioned by post_id.   │
│  A celebrity posts something viral.                          │
│  post_id=98765 → hashes to Node 3.                           │
│  Millions of reads for post_id=98765 ALL hit Node 3.         │
│                                                              │
│  Consistent hashing can't help here — the KEY itself is      │
│  hot, not the hash distribution. No matter how uniform       │
│  the ring is, all requests for the same key go to the        │
│  same node.                                                  │
│                                                              │
│  FIXES:                                                      │
│  1. READ REPLICAS: Read from any of the RF replicas,         │
│     not just the primary. Spreads read load across           │
│     RF nodes instead of 1.                                   │
│                                                              │
│  2. CLIENT-SIDE CACHING: Cache hot objects at the            │
│     application tier. Don't even hit the database.           │
│                                                              │
│  3. KEY SHARDING (scatter-gather):                           │
│     Instead of storing post_id=98765 on one node:            │
│     Split into post_id=98765:shard0, post_id=98765:shard1,   │
│     ..., post_id=98765:shardN                                │
│     Each shard hashes to a different node on the ring.       │
│     Read from a random shard. Write to all shards.           │
│     → Spreads one hot key across N nodes.                    │
│     → Cost: writes are N× more expensive.                    │
│                                                              │
│  4. DYNAMODB APPROACH: Automatic partition splitting.        │
│     The hot partition is split into sub-partitions,          │
│     each on a different node. Transparent to the client.     │
├──────────────────────────────────────────────────────────────┤
│  FAILURE MODE #2: CASCADE DURING REBALANCING                 │
│                                                              │
│  Scenario: 6-node Cassandra cluster. Node 3 crashes.         │
│  Node 3's data should be served by neighboring nodes.        │
│                                                              │
│  Without vnodes:                                             │
│  → ALL of Node 3's range goes to Node 4                      │
│  → Node 4's load doubles: 33% → 50%+                         │
│  → Node 4 is now under heavy load (CPU, disk, memory)        │
│  → Node 4's response times increase                          │
│  → Gossip protocol marks Node 4 as slow                      │
│  → If Node 4 also crashes: Node 5 absorbs BOTH               │
│    Node 3 and Node 4's data → Node 5 overwhelmed             │
│  → CASCADE FAILURE                                           │
│                                                              │
│  With vnodes (e.g., 16 per node):                            │
│  → Node 3's 16 vnode ranges are absorbed by ~16 different    │
│    successor nodes (some may overlap, but spread is good)    │
│  → Each surviving node absorbs ~1/5 of Node 3's load         │
│  → No single node is overwhelmed                             │
│  → CASCADE PREVENTED                                         │
│                                                              │
│  LESSON: Vnodes are not just about uniform distribution.     │
│  They're about CASCADE PREVENTION during node failures.      │
├──────────────────────────────────────────────────────────────┤
│  FAILURE MODE #3: HASH FUNCTION COLLISION                    │
│                                                              │
│  If the hash function produces CLUSTERS of similar values    │
│  for related keys, multiple "hot" keys might hash to the     │
│  same region of the ring → same node.                        │
│                                                              │
│  Example:                                                    │
│    key="order:10001" → hash = 42001                          │
│    key="order:10002" → hash = 42002                          │
│    key="order:10003" → hash = 42003                          │
│    Sequential IDs produce sequential hashes!                 │
│    All recent orders hash to the same ring region.           │
│                                                              │
│  FIX: Use a hash function with GOOD DISTRIBUTION.            │
│  → Murmur3 (Cassandra's choice): excellent distribution      │
│    for sequential inputs                                     │
│  → CRC16 (Redis Cluster): good distribution for most         │
│    inputs                                                    │
│  → MD5 (DynamoDB): cryptographic — excellent uniformity      │
│    but slower than Murmur3                                   │
│  → DO NOT USE: Java's hashCode() — terrible distribution     │
│    for sequential integers                                   │
│                                                              │
│  Verify distribution with:                                   │
│    # Python: check hash distribution                         │
│    import mmh3  # murmurhash3                                │
│    from collections import Counter                           │
│    buckets = Counter()                                       │
│    for i in range(1000000):                                  │
│        h = mmh3.hash(f"order:{i}") % 100                     │
│        buckets[h] += 1                                       │
│    # Each bucket should have ~10000 (±300)                   │
│    print(max(buckets.values()) - min(buckets.values()))      │
│    # Should be < 1000 for good distribution                  │
├──────────────────────────────────────────────────────────────┤
│  FAILURE MODE #4: UNEQUAL NODE CAPACITY                      │
│                                                              │
│  Not all nodes are identical. In cloud environments:         │
│  → Some nodes have more RAM (r5.2xlarge vs r5.xlarge)        │
│  → Some have faster disks (io2 vs gp3)                       │
│  → After a replacement, a new node might have different      │
│    specs                                                     │
│                                                              │
│  Standard consistent hashing assigns equal ranges to all     │
│  nodes, regardless of capacity.                              │
│                                                              │
│  FIX: WEIGHTED vnodes.                                       │
│  → Assign MORE vnodes to higher-capacity nodes               │
│  → Node with 2x RAM → 2x vnodes → 2x data                    │
│  → Cassandra: set different num_tokens per node              │
│                                                              │
│  # cassandra.yaml on a bigger node:                          │
│  num_tokens: 32   # (vs 16 on standard nodes)                │
│                                                              │
│  FIX: WEIGHTED slots (Redis Cluster).                        │
│  → Assign more slots to higher-capacity nodes                │
│  → redis-cli --cluster rebalance --cluster-weight            │
│    node1=2 node2=1 node3=1                                   │
│  → Node1 gets 2x the slots (and 2x the data)                 │
└──────────────────────────────────────────────────────────────┘
```

### SRE Toolkit

```
# Cassandra: Check ring balance
nodetool status
# Shows: load per node, ownership percentage
# If one node shows 40%+ ownership → imbalanced ring

nodetool ring
# Shows every token and which node owns it
# Look for large gaps between adjacent tokens on the 
# same node → that node owns a disproportionately large range

nodetool describering <keyspace>
# Shows ranges with start/end tokens and assigned nodes
# Useful for identifying which node owns a hot key's range

# Find which node a specific key hashes to:
nodetool getendpoints <keyspace> <table> <partition_key>
# Returns the nodes that own replicas of that key

# Redis Cluster: Check slot distribution
redis-cli --cluster check <any-node>:6379
# Shows: slots per node, keys per node
# If one node has >> 16384/N slots → imbalanced

redis-cli --cluster info <any-node>:6379
# Shows: keys, slots, and slaves per node

# Redis: Find which slot a key maps to
redis-cli CLUSTER KEYSLOT "user:1001"
# Returns: (integer) 7438

# Redis: Find which node owns a slot
redis-cli CLUSTER SLOTS
# Returns: slot ranges and their assigned nodes

# Rebalance Redis Cluster:
redis-cli --cluster rebalance <any-node>:6379
# Automatically redistributes slots evenly

# DynamoDB: Check partition metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name ConsumedReadCapacityUnits \
  --dimensions Name=TableName,Value=my-table \
  --statistics Maximum \
  --period 60 \
  --start-time $(date -u -d '1 hour ago' +%FT%TZ) \
  --end-time $(date -u +%FT%TZ)
# Compare consumed vs provisioned
# Large spikes on a per-partition basis indicate hot partitions

# DynamoDB: Enable Contributor Insights to find hot keys
aws dynamodb update-contributor-insights \
  --table-name my-table \
  --contributor-insights-action ENABLE
# Shows the most frequently accessed partition keys
```

---

## Step 4: Hands-On Exercises

```
┌──────────────────────────────────────────────────────────────┐
│  EXERCISE 1: Visualize the Hash-Mod-N Problem                │
│                                                              │
│  # Python script: compare key movement                       │
│  import hashlib                                              │
│                                                              │
│  def hash_key(key, n_nodes):                                 │
│      h = int(hashlib.md5(key.encode()).hexdigest(), 16)      │
│      return h % n_nodes                                      │
│                                                              │
│  # Generate 10000 keys                                       │
│  keys = [f"user:{i}" for i in range(10000)]                  │
│                                                              │
│  # Assign to 10 nodes                                        │
│  assignment_10 = {k: hash_key(k, 10) for k in keys}          │
│                                                              │
│  # Add an 11th node                                          │
│  assignment_11 = {k: hash_key(k, 11) for k in keys}          │
│                                                              │
│  # Count how many keys MOVED                                 │
│  moved = sum(1 for k in keys                                 │
│              if assignment_10[k] != assignment_11[k])        │
│  print(f"Keys moved: {moved}/{len(keys)}")                   │
│  print(f"Percentage: {moved/len(keys)*100:.1f}%")            │
│  # Expected: ~90.9% moved (10/11)                            │
│                                                              │
│  # Now implement consistent hashing and compare:             │
│  # (exercise continues below)                                │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 2: Build a Consistent Hash Ring                    │
│                                                              │
│  # Python: minimal consistent hashing implementation         │
│  import hashlib                                              │
│  from bisect import bisect_right                             │
│                                                              │
│  class ConsistentHashRing:                                   │
│      def __init__(self, vnodes=150):                         │
│          self.vnodes = vnodes                                │
│          self.ring = []      # sorted list of (hash, node)   │
│          self.nodes = set()                                  │
│                                                              │
│      def _hash(self, key):                                   │
│          return int(hashlib.md5(                             │
│              key.encode()).hexdigest(), 16)                  │
│                                                              │
│      def add_node(self, node):                               │
│          self.nodes.add(node)                                │
│          for i in range(self.vnodes):                        │
│              h = self._hash(f"{node}:vnode{i}")              │
│              self.ring.append((h, node))                     │
│          self.ring.sort()                                    │
│                                                              │
│      def remove_node(self, node):                            │
│          self.nodes.discard(node)                            │
│          self.ring = [(h, n) for h, n in self.ring           │
│                       if n != node]                          │
│                                                              │
│      def get_node(self, key):                                │
│          if not self.ring:                                   │
│              return None                                     │
│          h = self._hash(key)                                 │
│          hashes = [r[0] for r in self.ring]                  │
│          idx = bisect_right(hashes, h) % len(self.ring)      │
│          return self.ring[idx][1]                            │
│                                                              │
│  # Test: add 10 nodes, then add an 11th                      │
│  ring = ConsistentHashRing(vnodes=150)                       │
│  for i in range(10):                                         │
│      ring.add_node(f"node-{i}")                              │
│                                                              │
│  keys = [f"user:{i}" for i in range(10000)]                  │
│  assignment_before = {k: ring.get_node(k) for k in keys}     │
│                                                              │
│  ring.add_node("node-10")  # add 11th node                   │
│  assignment_after = {k: ring.get_node(k) for k in keys}      │
│                                                              │
│  moved = sum(1 for k in keys                                 │
│              if assignment_before[k] != assignment_after[k]) │
│  print(f"Keys moved: {moved}/{len(keys)}")                   │
│  print(f"Percentage: {moved/len(keys)*100:.1f}%")            │
│  # Expected: ~9% moved (1/11) ← MUCH better than 91%!        │
│                                                              │
│  # Experiment with different vnode counts:                   │
│  # vnodes=1: poor distribution, ~30% variation               │
│  # vnodes=10: better, ~15% variation                         │
│  # vnodes=150: good, ~5% variation                           │
│  # vnodes=500: diminishing returns, ~3% variation            │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 3: Observe Redis Cluster Slot Distribution         │
│                                                              │
│  # Start a Redis Cluster (3 masters, 3 replicas):            │
│  # Using docker:                                             │
│  docker run -d --name redis-cluster \                        │
│    -e REDIS_CLUSTER_CREATOR=yes \                            │
│    -e REDIS_NODES="redis-0 redis-1 redis-2 \                 │
│                    redis-3 redis-4 redis-5" \                │
│    bitnami/redis-cluster                                     │
│                                                              │
│  # Check slot distribution:                                  │
│  redis-cli --cluster check 127.0.0.1:6379                    │
│                                                              │
│  # Insert 100K keys and check distribution:                  │
│  for i in $(seq 1 100000); do                                │
│    redis-cli -c SET "key:$i" "value:$i" > /dev/null          │
│  done                                                        │
│                                                              │
│  redis-cli --cluster check 127.0.0.1:6379                    │
│  # Observe: keys per node should be roughly equal            │
│  # (±5% with CRC16 distribution)                             │
│                                                              │
│  # Check which slot a key belongs to:                        │
│  redis-cli CLUSTER KEYSLOT "key:12345"                       │
│                                                              │
│  # Simulate node failure: pause one master                   │
│  docker pause redis-0                                        │
│  # Watch the cluster detect the failure:                     │
│  redis-cli --cluster check 127.0.0.1:6380                    │
│  # The replica of redis-0 should be promoted                 │
│  # Slots are NOT redistributed — just failover to replica    │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 5: SRE Scenario

```
┌──────────────────────────────────────────────────────────────┐
│  SCENARIO: Global Session Store Migration Gone Wrong         │
│                                                              │
│  You're the SRE for a large SaaS platform (Slack-like        │
│  team messaging). The platform has 12 million daily active   │
│  users across 3 regions (US, EU, APAC).                      │
│                                                              │
│  ARCHITECTURE:                                               │
│  → User sessions are stored in a distributed cache           │
│    (Memcached cluster using consistent hashing)              │
│  → Each region has its own independent session cluster       │
│  → US cluster: 20 Memcached nodes                            │
│    → Consistent hashing ring with 150 vnodes per node        │
│    → ~4M active sessions at peak                             │
│    → Session data: user prefs, auth tokens, active           │
│      channels, notification state (~4KB per session)         │
│  → Load balancer uses consistent hashing on user_id          │
│    to route requests (sticky sessions via ring)              │
│                                                              │
│  THE MIGRATION:                                              │
│  Engineering decided to migrate from Memcached to Redis      │
│  Cluster for better data structure support and persistence.  │
│                                                              │
│  NEW REDIS CLUSTER:                                          │
│  → 12 nodes (6 masters, 6 replicas)                          │
│  → 16384 hash slots distributed across 6 masters             │
│  → Key mapping: CRC16(session_key) mod 16384                 │
│                                                              │
│  MIGRATION PLAN (approved last week):                        │
│  → Phase 1: Dual-write to both Memcached and Redis           │
│  → Phase 2: Switch reads from Memcached to Redis             │
│  → Phase 3: Decommission Memcached                           │
│                                                              │
│  CURRENT STATE: Phase 2 just completed. Reads are now        │
│  from Redis Cluster. Memcached still receiving writes.       │
│                                                              │
│  INCIDENT TIMELINE:                                          │
│                                                              │
│  10:00 — Phase 2 completed. All session reads now from       │
│          Redis Cluster. Monitoring shows:                    │
│          → Redis hit rate: 98.2% (good)                      │
│          → p99 latency: 2.3ms (good)                         │
│          → Error rate: 0.01% (acceptable)                    │
│                                                              │
│  11:30 — US traffic ramp. DAU climbing toward peak.          │
│          Redis CPU utilization across 6 masters:             │
│          Node 1: 34%    Node 4: 31%                          │
│          Node 2: 78%    Node 5: 29%                          │
│          Node 3: 32%    Node 6: 35%                          │
│                                                              │
│  11:45 — Alert fires:                                        │
│          "Redis master-2 CPU > 75% sustained 10 min"         │
│          Redis master-2 owns slots 2731-5460.                │
│                                                              │
│  11:50 — Investigation reveals:                              │
│          Top keys on master-2 by access frequency:           │
│          1. session:workspace:acme-corp (820 reads/sec)      │
│          2. session:workspace:globex (340 reads/sec)         │
│          3. session:workspace:initech (290 reads/sec)        │
│          These are WORKSPACE SESSION KEYS — shared state     │
│          for all users in a workspace (presence indicators,  │
│          typing indicators, active channel list).            │
│          "acme-corp" has 47,000 active users.                │
│                                                              │
│  12:00 — acme-corp users report:                             │
│          "Presence indicators are wrong"                     │
│          "Typing indicators are delayed by 3-5 seconds"      │
│          "Channel list takes forever to load"                │
│          Redis master-2 CPU: 92%                             │
│          Master-2 p99 latency: 89ms (was 2.3ms)              │
│                                                              │
│  12:05 — Team decides to add a 7th master to spread load.    │
│          Running: redis-cli --cluster reshard                │
│          Moving slots 2731-3413 from master-2 to master-7.   │
│          (Moving ~683 slots — 1/4 of master-2's slots)       │
│                                                              │
│  12:10 — DURING the reshard:                                 │
│          Master-2 CPU spikes to 99%.                         │
│          Reshard is MIGRATING keys from master-2 to master-7.│
│          This migration reads ALL keys in each slot and      │
│          transfers them. On an already-overloaded node,      │
│          this additional I/O makes things WORSE.             │
│                                                              │
│          Users across ALL workspaces on master-2 (not just   │
│          acme-corp) now experience:                          │
│          → 5-15 second delays on session operations          │
│          → Timeouts on presence updates                      │
│          → Some users logged out (session read timeout →     │
│            app treats as expired session → forces re-login)  │
│                                                              │
│  12:12 — Reshard is 60% complete. master-7 has 410 slots.    │
│          master-2 still has ~2320 slots and is at 99% CPU.   │
│          Some slots are in MIGRATING state: reads for keys   │
│          in those slots get ASK redirects → extra round trip │
│          → additional latency.                               │
│                                                              │
│  12:15 — master-2's replica detects master-2 as unhealthy    │
│          (response time > cluster-node-timeout).             │
│          Replica initiates FAILOVER.                         │
│          But master-2 is not actually down — it's just slow. │
│          Failover completes: replica becomes new master-2.   │
│                                                              │
│          PROBLEM: the reshard was in progress.               │
│          Slots that were in MIGRATING state on old master-2  │
│          are now in an INCONSISTENT state:                   │
│          → master-7 has SOME keys from those slots           │
│          → new master-2 (the replica) has the OLD keys       │
│            (before migration started — replica was behind)   │
│          → Some keys exist on BOTH nodes                     │
│          → Some keys exist on NEITHER node                   │
│                                                              │
│  12:17 — User reports escalate:                              │
│          "I can't see any of my channels"                    │
│          "The app is logging me out repeatedly"              │
│          "My messages are disappearing"                      │
│                                                              │
│  12:18 — Error rate: 4.7% (was 0.01%).                       │
│          Cache miss rate: 23% (was 1.8%).                    │
│          The 23% misses are hitting the auth service         │
│          (session miss → re-authenticate → rebuild session). │
│          Auth service load: 3x normal.                       │
│          Auth service database connection pool: 87% utilized.│
│                                                              │
│  12:20 — You're the on-call SRE. The incident is yours.      │
│                                                              │
└──────────────────────────────────────────────────────────────┘

QUESTIONS:

Q1: The hot-node problem (master-2 at 78% while others 
    are at 29-35%) is NOT caused by uneven slot distribution.
    Master-2 has 2730 slots — almost exactly 1/6 of 16384.
    
    a) Explain precisely why consistent hashing CANNOT solve 
       this specific hot-node problem.
    b) What key design decision created this hot spot?
    c) Propose a fix that prevents this hot spot entirely.
       Show the new key structure.

Q2: The team's decision to reshard at 12:05 was wrong.
    
    a) Explain why resharding an overloaded node makes 
       things worse, not better (immediate vs eventual).
    b) What should they have done INSTEAD as immediate 
       mitigation?
    c) At what point would resharding become appropriate,
       and what preconditions should be met?

Q3: The failover at 12:15 during an in-progress reshard 
    created an inconsistent state (some keys on both nodes, 
    some on neither).
    
    a) In consistency model terms, what guarantee has been 
       violated?
    b) Describe the exact recovery procedure to fix the 
       slot inconsistency between master-2 (new, promoted 
       replica) and master-7 (partial migration target).
    c) What Redis Cluster configuration could have 
       prevented the failover from triggering during 
       the reshard?

Q4: Design a proper migration plan from Memcached to Redis 
    Cluster that would have avoided this entire incident.
    Consider:
    → How to handle the different hashing algorithms
       (Memcached consistent hashing vs Redis CRC16 slots)
    → How to detect hot keys BEFORE cutting over reads
    → How to handle the workspace session key pattern
    → Rollback strategy at each phase

Q5: Give your mitigation plan for the incident as it 
    stands at 12:20. You have:
    → master-2 (new, promoted replica) with old data
    → master-7 with partial migrated data
    → Slots in inconsistent state
    → 4.7% error rate
    → 23% cache miss rate
    → Auth service at 87% connection pool utilization
    → 4M active sessions, 12M DAU approaching peak

    Prioritize and sequence your actions.
```

---

## Step 6: Targeted Reading

```
┌──────────────────────────────────────────────────────────────┐
│  READ AFTER THIS LESSON:                                     │
│                                                              │
│  DDIA Chapter 6: "Partitioning"                              │
│  → Pages 199-207 (Partitioning of Key-Value Data)            │
│    - "Partitioning by Hash of Key" (p. 203-204)              │
│    This is consistent hashing explained in Kleppmann's       │
│    terminology. He uses the term "hash partitioning"         │
│    and discusses the tradeoffs between hash-based and        │
│    range-based partitioning.                                 │
│                                                              │
│  → Pages 207-211 (Partitioning and Secondary Indexes)        │
│    Relevant for understanding how consistent hashing         │
│    interacts with secondary indexes (scatter-gather).        │
│                                                              │
│  → Pages 211-216 (Rebalancing Partitions)                    │
│    - "Fixed number of partitions" (p. 212-213)               │
│      ← This is the Redis Cluster / DynamoDB approach         │
│    - "Dynamic partitioning" (p. 214)                         │
│      ← This is the DynamoDB partition split approach         │
│    - "Partitioning proportionally to nodes" (p. 214-215)     │
│      ← This is Cassandra's vnode approach                    │
│    READ ALL THREE and compare — Kleppmann lays out the       │
│    exact tradeoffs we covered.                               │
│                                                              │
│  → Pages 216-217 (Automatic vs Manual Rebalancing)           │
│    Directly relevant to the SRE scenario (what goes wrong    │
│    with automatic rebalancing during incidents).             │
│                                                              │
│  OPTIONAL:                                                   │
│  → Original consistent hashing paper (Karger et al., 1997)   │
│    "Consistent Hashing and Random Trees"                     │
│    Short, readable, and historically important.              │
│    Focus on Section 4 (the ring construction).               │
│                                                              │
│  TOTAL: ~20 pages from DDIA + optional paper.                │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 7: Key Takeaways

```
┌──────────────────────────────────────────────────────────────┐
│  5 THINGS TO REMEMBER IF YOU FORGET EVERYTHING ELSE          │
│                                                              │
│  1. hash-mod-N is catastrophic for topology changes.         │
│     Adding or removing one node moves ~(N-1)/N of all keys.  │
│     With 100 nodes, adding 1 node invalidates 99% of your    │
│     cache. Consistent hashing moves only ~1/N (1%).          │
│     This is the ENTIRE REASON consistent hashing exists.     │
│                                                              │
│  2. Virtual nodes solve TWO problems: uneven distribution    │
│     AND cascade prevention. With basic consistent hashing    │
│     (1 position per node), ranges are uneven AND a node      │
│     failure dumps all load onto one neighbor. Vnodes         │
│     spread both data AND failure-load across all nodes.      │
│     Production systems use 16-256 vnodes per node.           │
│                                                              │
│  3. Consistent hashing CANNOT solve hot-key problems.        │
│     If one key receives 1M reads/sec, all those reads go     │
│     to the same node regardless of how perfect the ring is.  │
│     Solutions: read replicas, client-side caching, key       │
│     sharding (scatter-gather), or DynamoDB-style adaptive    │
│     partition splitting.                                     │
│                                                              │
│  4. Three implementations, three philosophies:               │
│     Cassandra (vnodes): flexible, self-managing, complex     │
│     Redis Cluster (16384 fixed slots): simple, manual        │
│     DynamoDB (auto-split): managed, adaptive, opaque         │
│     Know which one your system uses and WHY — it determines  │
│     how you handle rebalancing, failures, and hot spots.     │
│                                                              │
│  5. NEVER reshard/rebalance an overloaded node under load.   │
│     Migration reads ALL keys and transfers them — this is    │
│     heavy I/O on a node that's already at capacity.          │
│     Mitigate the immediate problem first (scale reads,       │
│     cache hot keys, redirect traffic), THEN rebalance        │
│     when the node is healthy.                                │
└──────────────────────────────────────────────────────────────┘
```

# Incident Deep-Dive: Global Session Store Migration Gone Wrong

---

## Q1: Why Consistent Hashing Cannot Solve This Hot-Node Problem

### a) Why Consistent Hashing Fails Here

```
Consistent hashing solves ONE problem: distributing 
MANY KEYS evenly across MANY NODES so that adding 
or removing a node only remaps a minimal subset of keys.

It CANNOT solve the HOT KEY problem.

THE DISTINCTION:

  HOT PARTITION: Many keys land on the same node due 
  to uneven distribution. Consistent hashing WITH 
  vnodes solves this — 150 vnodes per node produces 
  near-uniform distribution.

  HOT KEY: One SINGLE KEY receives disproportionate 
  traffic regardless of which node it's on. Moving 
  the key to another node just makes THAT node hot.

Master-2's problem is NOT uneven slot distribution. 
It has 2730 slots — almost exactly 1/6 of 16384. 
The distribution is PERFECT.

The problem is that ONE KEY — session:workspace:acme-corp 
— receives 820 reads/sec. This single key hashes to 
ONE slot, which lives on ONE master. No amount of 
resharding, rebalancing, or vnode tuning changes this.

  ┌─────────────────────────────────────────────────┐
  │  CONSISTENT HASHING DISTRIBUTES KEYS.           │
  │  IT CANNOT DISTRIBUTE A SINGLE KEY.             │
  │                                                 │
  │  CRC16("session:workspace:acme-corp") = 4127    │
  │  Slot 4127 → master-2. ALWAYS.                  │
  │                                                 │
  │  Even if you reshard slot 4127 to master-7:     │
  │  → master-7 now gets 820 reads/sec              │
  │  → master-7 becomes the new hot node            │
  │  → You've MOVED the problem, not solved it      │
  │                                                 │
  │  Resharding redistributes slots.                │
  │  It doesn't split traffic within a slot.        │
  │  It doesn't split traffic to a single key.      │
  └─────────────────────────────────────────────────┘
```

### b) The Key Design Decision That Created This Hot Spot

```
The design decision: using a SINGLE KEY per workspace 
for shared mutable state that ALL workspace members 
read from.

  session:workspace:acme-corp → {
    presence: {user1: online, user2: away, ...},  // 47,000 entries
    typing: {channel1: [user5, user9], ...},
    active_channels: [general, engineering, ...],
    notification_state: {...}
  }

47,000 users polling presence/typing indicators for 
their workspace. ALL of them read the SAME key. The 
key becomes a convergence point — every user in the 
workspace funnels through one Redis slot on one master.

IN MEMCACHED, THIS WAS HIDDEN:
  Memcached's consistent hashing with 150 vnodes per 
  node and 20 nodes distributed the load differently. 
  The workspace key still went to ONE node, but:
  → 20 nodes meant each node had 5% of keys (vs 16.7% 
    with 6 masters)
  → Memcached is simpler (no cluster protocol, no slot 
    redirection) — pure get/set with lower per-operation 
    CPU cost
  → The workspace key was hot on Memcached too, but the 
    node could absorb it because Memcached is more 
    CPU-efficient for simple key-value operations
  
  Moving to Redis Cluster with 6 masters (vs 20 Memcached 
  nodes) concentrated traffic onto fewer nodes. The hot 
  key that was "warm" on Memcached became "scalding" on 
  Redis.

THE ROOT CAUSE IS THE DATA MODEL:
  Shared mutable state for N users should not live in 
  a single key when N can be 47,000. This is a 
  fan-in/fan-out problem disguised as a caching problem.
```

### c) Fix: Eliminate the Hot Key

```
APPROACH: Shard the workspace session data across 
multiple keys, distributed across multiple slots 
(and therefore multiple masters).

OLD KEY STRUCTURE (hot key):
  session:workspace:acme-corp → {everything}
  CRC16 → slot 4127 → master-2 → ALL 820 reads/sec

NEW KEY STRUCTURE (sharded):

  # Presence: shard by user_id hash
  session:workspace:acme-corp:presence:{shard_id}
  
  # 16 presence shards (adjustable per workspace size):
  session:workspace:acme-corp:presence:0   → slot X → master-1
  session:workspace:acme-corp:presence:1   → slot Y → master-4
  session:workspace:acme-corp:presence:2   → slot Z → master-6
  ...
  session:workspace:acme-corp:presence:15  → slot W → master-3

  # Each user's presence goes to:
  shard_id = CRC16(user_id) % 16
  key = f"session:workspace:acme-corp:presence:{shard_id}"

  # Typing indicators: shard by channel_id
  session:workspace:acme-corp:typing:{channel_id}
  
  # Each channel's typing state is its own key:
  session:workspace:acme-corp:typing:general     → slot A
  session:workspace:acme-corp:typing:engineering → slot B
  session:workspace:acme-corp:typing:random      → slot C

  # Active channels: per-user (not shared)
  session:user:{user_id}:active_channels
  
  # This was never shared state — it's per-user. 
  # It was incorrectly bundled into the workspace key.

TRAFFIC DISTRIBUTION AFTER SHARDING:

  BEFORE: 1 key × 820 reads/sec = 820 reads/sec on ONE node
  
  AFTER:  16 presence shards across multiple masters:
          → ~51 reads/sec per shard, spread across 6 masters
          → No single master gets more than ~140 reads/sec 
            from acme-corp presence alone (3 shards per master)
          
          Typing indicators: per-channel keys
          → acme-corp has ~200 channels
          → ~4 reads/sec per channel (most channels are quiet)
          → Spread across all 6 masters
          
          Active channels: per-user keys
          → Already distributed by user_id across all masters
          → No hot key possible

  ┌─────────────────────────────────────────────────────┐
  │  Node 1: ~140 reads/s (presence shards 0,5,11)      │
  │  Node 2: ~135 reads/s (presence shards 2,8,14)      │
  │  Node 3: ~130 reads/s (presence shards 3,6,12)      │
  │  Node 4: ~140 reads/s (presence shards 1,9,13)      │
  │  Node 5: ~125 reads/s (presence shards 4,7,15)      │
  │  Node 6: ~150 reads/s (presence shards 10 + typing) │
  │                                                     │
  │  vs BEFORE: Node 2: 820 reads/s, others: ~30 reads/s│
  └─────────────────────────────────────────────────────┘

IMPLEMENTATION NOTE ON REDIS HASH TAGS:
  
  Redis Cluster determines the slot using hash tags: 
  if a key contains {tag}, only the tag portion is hashed.
  
  DO NOT USE: session:{acme-corp}:presence:0
  This would hash ONLY "acme-corp" → ALL shards land 
  on the same slot → defeats the purpose entirely.
  
  DO USE: session:workspace:acme-corp:presence:0
  No hash tags → the FULL key is hashed → each shard 
  lands on a different slot → distributed across masters.
  
  TRADEOFF: Without hash tags, you CANNOT use Redis 
  multi-key operations (MGET, transactions) across 
  shards. Each shard must be read independently.
  
  This is acceptable: presence reads are already 
  per-channel or per-view, not "give me all 47,000 
  users' presence in one operation."

READ PATTERN FOR CLIENTS:

  # When a user opens a channel, they need:
  # 1. Their own session (already per-user key)
  # 2. Presence for users IN THAT CHANNEL (not all 47K)
  # 3. Typing indicators for that channel

  async def get_channel_view(user_id, channel_id, workspace_id):
      # Get channel members (from separate service/DB)
      members = await get_channel_members(channel_id)
      
      # Determine which presence shards we need
      shards_needed = set()
      for member_id in members:
          shard = crc16(member_id) % 16
          shards_needed.add(shard)
      
      # Fetch presence from each shard (parallel)
      presence_tasks = [
          redis.hgetall(
              f"session:workspace:{workspace_id}:presence:{shard}"
          )
          for shard in shards_needed
      ]
      presence_results = await asyncio.gather(*presence_tasks)
      
      # Fetch typing for this channel (single key)
      typing = await redis.smembers(
          f"session:workspace:{workspace_id}:typing:{channel_id}"
      )
      
      # Assemble and return
      return ChannelView(
          presence=merge_presence(presence_results, members),
          typing=typing
      )
```

---

## Q2: Why Resharding Was Wrong and What To Do Instead

### a) Why Resharding an Overloaded Node Makes Things Worse

```
RESHARDING MECHANICS:

  redis-cli --cluster reshard moves slots from a source 
  node to a target node. For each slot, it:

  1. Sets the slot to MIGRATING state on source node
  2. Sets the slot to IMPORTING state on target node
  3. For EVERY KEY in that slot:
     a) DUMP the key on source (serializes to memory)
     b) RESTORE the key on target (deserializes, writes)
     c) DEL the key on source (after confirmed on target)
  4. Update cluster slot ownership

  EACH KEY MIGRATION IS:
  → A full key read on the source node (CPU + memory)
  → A serialization operation (CPU)
  → A network transfer (bandwidth)
  → A write on the target node
  → A deletion on the source node

MASTER-2's STATE AT 12:05:
  → CPU: 92%
  → Serving 820+ reads/sec for acme-corp alone
  → Serving normal traffic for all other keys in 
    2730 slots
  → p99 latency already at 89ms (degraded)

WHAT THE RESHARD DOES TO MASTER-2:

  ┌──────────────────────────────────────────────────┐
  │  EXISTING LOAD:                                  │
  │  → 820 reads/sec (acme-corp)                     │
  │  → ~300 reads/sec (other workspace keys)         │
  │  → ~1500 reads/sec (individual session keys)     │
  │  → Total: ~2620 reads/sec                        │
  │  → CPU: 92%                                      │
  │                                                  │
  │  RESHARD ADDS:                                   │
  │  → DUMP + serialize for every key in 683 slots   │
  │  → Each slot may have hundreds or thousands of   │
  │    keys (4M sessions / 16384 slots ≈ 244 keys    │
  │    per slot average)                             │
  │  → 683 slots × 244 keys = ~166,000 keys to       │
  │    serialize and transfer                        │
  │  → Each DUMP+DEL is CPU work on an already-      │
  │    saturated node                                │
  │                                                  │
  │  IMMEDIATE EFFECT:                               │
  │  → CPU: 92% → 99% (migration I/O added)          │
  │  → Latency: 89ms → seconds (CPU saturated)       │
  │  → ALL keys on master-2 affected (not just the   │
  │    migrating slots — CPU is shared)              │
  │  → Users on master-2 who had nothing to do with  │
  │    acme-corp now experience degradation          │
  │  → BLAST RADIUS EXPANDED from "acme-corp users"  │
  │    to "all users with sessions on master-2"      │
  │                                                  │
  │  EVENTUAL EFFECT (if it completes):              │
  │  → master-2 has fewer slots → less load          │
  │  → But the HOT KEY is still on master-2          │
  │    (unless you specifically moved slot 4127)     │
  │  → Even then: master-7 just becomes hot          │
  └──────────────────────────────────────────────────┘

  TIMELINE:

  LOAD ▲
       │   ╔══════════════════════════════════╗
  100% │───║─reshard─starts──────────────────║──────
       │   ║                                  ║
   92% │───║──────────────────────────────────║──────
       │   ║        migration I/O overhead    ║
       │   ║                                  ║
       │   ╚══════════╗                       ║
       │              ║  if reshard completes  ║
       │              ║  load EVENTUALLY drops ║
       │              ╚═══════════════════════╝
       │                         maybe here: 70%?
       │                         BUT hot key still here
       └────────────────────────────────────────────► time
           12:05   12:10    12:15    12:20

  The reshard makes the patient SICKER before the 
  medicine works. On a node at 92% CPU, the additional 
  I/O pushes it past the point of recovery. The node 
  becomes so slow that the cluster declares it dead 
  and triggers a failover — which interrupts the 
  reshard and creates an INCONSISTENT STATE.

  The cure was worse than the disease.
```

### b) What They Should Have Done Instead

```
IMMEDIATE MITIGATION (should have done at 12:05):

STEP 1: REDUCE TRAFFIC TO THE HOT KEY (seconds to execute)

  The hot key is session:workspace:acme-corp. 47,000 
  users polling presence from it. The application 
  layer can absorb this WITHOUT touching Redis.

  Option A: Application-level local cache for hot keys
  
  # In each application server's memory (Caffeine/Guava):
  # Cache the hot workspace key with a 500ms TTL.
  # 47,000 users hitting 50 app servers = 940 users/server
  # Instead of 940 Redis reads/sec/server → 2 reads/sec/server
  # (one cache miss every 500ms)
  # Total Redis reads: 50 servers × 2/sec = 100 reads/sec
  # Down from 820 reads/sec → 87% reduction
  
  async def get_workspace_presence(workspace_id):
      cache_key = f"workspace_presence:{workspace_id}"
      
      cached = local_cache.get(cache_key)
      if cached:
          return cached  # In-memory hit, no Redis call
      
      # Cache miss: read from Redis
      result = await redis.get(
          f"session:workspace:{workspace_id}"
      )
      local_cache.set(cache_key, result, ttl_ms=500)
      return result

  # This can be deployed as a feature flag toggle:
  # HOT_KEY_LOCAL_CACHE=true
  # Enable it in 30 seconds via config push.

  Option B: Rate-limit reads to the hot key
  
  # If local caching isn't available, throttle at the 
  # Redis proxy layer:
  # Allow max 100 reads/sec to any single key.
  # Excess reads get a cached response from the proxy.

  EITHER OPTION: master-2 CPU drops from 92% to ~45% 
  within seconds of deployment. Crisis averted.

STEP 2: STOP DUAL-WRITES TO MEMCACHED (minutes)

  The system is currently dual-writing to both Memcached 
  AND Redis. This doubles write load. Since reads are 
  already on Redis (Phase 2 complete), Memcached writes 
  are pure waste.

  # Disable Memcached writes:
  feature_flag.set("DUAL_WRITE_MEMCACHED", False)
  
  This doesn't help master-2 specifically (the hot key 
  is a READ problem, not a write problem), but it 
  reduces overall Redis write load and frees CPU 
  headroom across all masters.

STEP 3: VERIFY STABILIZATION (5-10 minutes)

  # Monitor master-2 CPU, latency, error rate
  # Expect: CPU < 50%, p99 < 5ms, error rate < 0.1%
  # ONE CHANGE → VERIFY → NEXT CHANGE
  
  redis-cli -h master-2 INFO cpu
  redis-cli -h master-2 INFO stats | grep instantaneous_ops
  redis-cli -h master-2 --latency-history -i 5
```

### c) When Resharding Becomes Appropriate

```
PRECONDITIONS FOR RESHARDING:

  1. NODE CPU < 50% (headroom for migration overhead)
     → The reshard itself consumes 10-30% additional CPU
     → At 50% base, you peak at 80% during migration
     → At 92% base, you peak at >100% → cascade failure

  2. HOT KEY MITIGATED FIRST
     → The hot key problem is solved via key sharding 
       (Q1c) or application-level caching
     → Resharding without solving the hot key just 
       MOVES the hot key to another node

  3. LOW TRAFFIC PERIOD
     → Reshard during off-peak hours (3-5 AM local time)
     → Migration I/O competes with user traffic
     → Lower baseline = more headroom for migration

  4. MIGRATION THROTTLED
     → redis-cli --cluster reshard supports 
       --cluster-pipeline option to batch key migrations
     → Set a low pipeline count to throttle migration speed
     → Slower migration = less I/O spike = safer

  5. FAILOVER PREVENTION DURING RESHARD
     → Temporarily increase cluster-node-timeout to prevent 
       false failover detection during migration-induced 
       latency spikes (covered in Q3c)

  6. ROLLBACK PLAN DEFINED
     → If migration causes CPU > 80% on source, STOP
     → Slots partially migrated can be rolled back with:
       redis-cli --cluster fix (repairs inconsistent slots)

  WHEN TO RESHARD:
  → After Steps 1-3 from (b) above stabilize the node
  → During the next maintenance window (off-peak)
  → With the hot key already sharded (Q1c fix deployed)
  → With preconditions 1-6 all satisfied
  → NOT during an active incident. NEVER during an 
    active incident.
```

---

## Q3: Failover During Reshard — Consistency Violation and Recovery

### a) Consistency Model Violation

```
THE VIOLATION: LINEARIZABILITY for keys in the 
migrating slots.

During a reshard, slots in MIGRATING/IMPORTING state 
have a specific protocol:

  1. Client requests key K in a MIGRATING slot on master-2
  2. If K still EXISTS on master-2 → serve it normally
  3. If K has been MIGRATED to master-7 → respond with 
     ASK redirect → client re-asks master-7
  4. This provides linearizability: every key is served 
     from exactly ONE authoritative source at all times

THE FAILOVER BROKE THIS PROTOCOL:

  Old master-2 (now demoted):
  → Had slots in MIGRATING state
  → Had already deleted some keys (migrated to master-7)
  → Had NOT yet deleted other keys (migration in progress)

  New master-2 (promoted replica):
  → Was an async replica of old master-2
  → Was BEHIND old master-2 (async replication lag)
  → Has NO knowledge of MIGRATING state
     (replication doesn't replicate cluster slot metadata)
  → Has OLD versions of keys that were already migrated
  → Does NOT have keys that were written to old master-2 
     after the replica's last sync

  Master-7 (migration target):
  → Has keys that were successfully migrated from old 
     master-2 before the failover
  → Believes it OWNS those slots (IMPORTING state 
     partially complete)
  → But new master-2 ALSO believes it owns those slots 
     (it inherited slot ownership from old master-2's 
     cluster config, minus the MIGRATING metadata)

  RESULT — SPLIT OWNERSHIP:

  ┌────────────┬───────────────┬───────────────┐
  │ KEY STATE  │ NEW MASTER-2  │ MASTER-7      │
  ├────────────┼───────────────┼───────────────┤
  │ Key A      │ HAS (old ver) │ HAS (new ver) │
  │ (migrated  │ Stale copy    │ Current copy  │
  │  before    │ from replica  │ received via  │
  │  failover) │ replication   │ RESTORE       │
  ├────────────┼───────────────┼───────────────┤
  │ Key B      │ HAS           │ DOESN'T HAVE  │
  │ (not yet   │ (current)     │               │
  │  migrated) │               │               │
  ├────────────┼───────────────┼───────────────┤
  │ Key C      │ DOESN'T HAVE  │ DOESN'T HAVE  │
  │ (written   │ (replica was  │ (not yet      │
  │  to old    │ behind)       │  migrated)    │
  │  master-2  │               │               │
  │  after     │               │               │
  │  replica   │               │               │
  │  sync)     │               │               │
  ├────────────┼───────────────┼───────────────┤
  │ Key D      │ HAS           │ HAS           │
  │ (migrated  │ (old version  │ (new version  │
  │  but DEL   │  from before  │  received via │
  │  not yet   │  replica lag) │  RESTORE)     │
  │  replicated│               │               │
  │  to replica│               │               │
  │  before    │               │               │
  │  failover) │               │               │
  └────────────┴───────────────┴───────────────┘

  VIOLATIONS:

  1. LINEARIZABILITY VIOLATED (Key A, Key D):
     Two nodes both have the key. Which is authoritative?
     New master-2 believes it owns the slot.
     Master-7 has the NEWER version from the migration.
     A client reading from new master-2 gets STALE data.
     A client redirected to master-7 gets NEWER data.
     The system has lost its single-source-of-truth 
     for these keys.

  2. DURABILITY VIOLATED (Key C):
     The key was written to old master-2 and acknowledged 
     to the client. But async replication hadn't synced 
     it to the replica. After failover, the key is GONE.
     An acknowledged write has been lost. This is the 
     async replication durability gap — the same failure 
     mode as the double-debit scenario from the teaching 
     material.

  3. MONOTONIC READS VIOLATED:
     A client that read Key A from old master-2 (new value) 
     now reads from new master-2 (old value from replica).
     The value went BACKWARD. Time travel.
```

### b) Recovery Procedure

```
RECOVERY: Fix slot ownership and key conflicts between 
new master-2 and master-7.

STEP 1: STOP ALL CLIENT WRITES TO AFFECTED SLOTS
  
  # Identify which slots are in inconsistent state.
  # These are the slots that were in MIGRATING state 
  # on old master-2 when the failover happened.
  # Slots 2731-3413 were being moved. The reshard was 
  # 60% complete at 12:12, so approximately:
  # Slots 2731-3140: fully migrated to master-7 (~410 slots)
  # Slots 3141-3413: in-flight or not yet started (~273 slots)
  
  # Check actual state:
  redis-cli --cluster check <any-cluster-node>:6379
  
  # This will show:
  # [ERR] Nodes disagree about configuration!
  # [ERR] Slots X-Y are open (MIGRATING/IMPORTING state)
  # [ERR] Slots A-B have multiple owners

STEP 2: USE redis-cli --cluster fix TO RESOLVE

  redis-cli --cluster fix <any-cluster-node>:6379
  
  # What --cluster fix does for each inconsistent slot:
  #
  # Case 1: Slot has IMPORTING flag on master-7 but no 
  #   MIGRATING flag on new master-2 (because the promoted 
  #   replica doesn't have the migration metadata):
  #   → Clears the IMPORTING flag on master-7
  #   → Assigns slot ownership back to new master-2
  #   → Keys that were already migrated to master-7 
  #     are now ORPHANED on master-7 (exist but the 
  #     slot is owned by new master-2)
  #
  # Case 2: Both nodes claim to own the slot:
  #   → fix resolves based on cluster consensus
  #   → Typically assigns to the node that the majority 
  #     of the cluster agrees on

  # PROBLEM: --cluster fix resolves SLOT OWNERSHIP but 
  # does NOT reconcile KEY CONFLICTS.
  # Key A may exist on both nodes with different versions.
  # Key C may exist on neither.

STEP 3: RECONCILE KEYS IN FORMERLY-MIGRATING SLOTS

  # For slots that were fully migrated (2731-3140):
  # master-7 has the AUTHORITATIVE data (it received 
  # the keys via migration, which includes the latest 
  # version from old master-2).
  # New master-2 has STALE data (from async replication 
  # which was behind).
  
  # Decision: master-7's data wins for these slots.
  # Re-assign slots 2731-3140 to master-7:
  
  redis-cli --cluster reshard <node>:6379 \
    --cluster-from <new-master-2-id> \
    --cluster-to <master-7-id> \
    --cluster-slots 410 \
    --cluster-yes
  
  # BUT WAIT — we just said resharding an overloaded 
  # node is dangerous. New master-2 is no longer at 
  # 99% CPU (it's a fresh replica with less data), 
  # and traffic has been disrupted (23% miss rate means 
  # many requests aren't hitting Redis at all).
  # CPU should be lower. Verify before proceeding:
  
  redis-cli -h new-master-2 INFO cpu
  # If used_cpu_sys < 50%: safe to reshard these slots

  # For slots that were in-flight (3141-3413):
  # Neither node may have complete data.
  # New master-2 has whatever the replica had (potentially 
  # stale). Master-7 has partial data (some keys migrated, 
  # some not).
  
  # SAFEST APPROACH: Assign these slots to new master-2.
  # Accept that some keys are lost (Key C scenario).
  # The application must handle cache misses gracefully 
  # (rebuild session from auth service).
  
  redis-cli --cluster setslot <slot> NODE <new-master-2-id>
  # Repeat for each slot in 3141-3413 range

  # Delete orphaned keys on master-7 for slots owned 
  # by new master-2 (they're stale copies):
  for slot in range(3141, 3414):
      keys = redis_cli(f"CLUSTER GETKEYSINSLOT {slot} 1000", 
                        host="master-7")
      for key in keys:
          redis_cli(f"DEL {key}", host="master-7")

STEP 4: VERIFY CLUSTER HEALTH

  redis-cli --cluster check <node>:6379
  # Expected: [OK] All 16384 slots covered
  # No ERR messages
  # All nodes agree on slot ownership
  
  redis-cli --cluster info <node>:6379
  # Verify key counts per master are reasonable
  
  # Run application-level health check:
  # Pick 100 random sessions, verify they're readable
  # Check error rate: should drop from 4.7% to < 0.1%
```

### c) Preventing Failover During Reshard

```
THE CONFIGURATION: cluster-node-timeout

  # Default: 15000ms (15 seconds)
  # If a master doesn't respond to PING within this 
  # window, replicas initiate failover.
  
  # At 12:10, master-2 was at 99% CPU. Response times 
  # to PING exceeded 15 seconds. The replica interpreted 
  # this as "master is down" and triggered failover.
  
  # But master-2 wasn't DOWN — it was SLOW. The 
  # reshard's I/O load pushed response times above 
  # the timeout threshold.

PREVENTION — INCREASE TIMEOUT BEFORE RESHARD:

  # Before starting any reshard operation:
  redis-cli -h master-2 CONFIG SET cluster-node-timeout 60000
  redis-cli -h replica-2 CONFIG SET cluster-node-timeout 60000
  
  # Set on ALL nodes (replicas won't trigger failover 
  # unless the timeout is exceeded):
  for node in $(redis-cli --cluster nodes | awk '{print $2}'); do
    redis-cli -h ${node%:*} -p ${node#*:} \
      CONFIG SET cluster-node-timeout 60000
  done
  
  # 60 seconds gives the overloaded node time to be 
  # slow without being declared dead.

  # AFTER reshard completes: restore original timeout
  for node in $(redis-cli --cluster nodes | awk '{print $2}'); do
    redis-cli -h ${node%:*} -p ${node#*:} \
      CONFIG SET cluster-node-timeout 15000
  done

ADDITIONAL SAFEGUARD — DISABLE AUTOMATIC FAILOVER:

  # On the specific replica of the resharding node:
  redis-cli -h replica-2 CLUSTER FAILOVER ABORT
  
  # Or: temporarily set the replica to not participate 
  # in elections:
  redis-cli -h replica-2 CONFIG SET cluster-replica-no-failover yes
  
  # This PREVENTS the replica from initiating failover 
  # under ANY circumstances.
  # Risk: if master-2 truly dies during reshard, there's 
  # no automatic failover. Manual intervention required.
  # But that's BETTER than an automatic failover that 
  # corrupts the migration state.
  
  # Re-enable after reshard:
  redis-cli -h replica-2 CONFIG SET cluster-replica-no-failover no

TRADEOFF:
  → During the reshard window: no automatic failover 
    for the resharding node
  → If the node truly crashes: manual intervention needed 
    (slower recovery, ~5-10 minutes)
  → But: this prevents the CATASTROPHIC outcome of a 
    failover during migration, which is far worse than 
    a brief manual recovery
  → Increased timeout + disabled auto-failover is the 
    standard operational practice for Redis Cluster 
    resharding in production
```

---

## Q4: Proper Migration Plan

```
┌──────────────────────────────────────────────────────────────┐
│  MIGRATION PLAN: MEMCACHED → REDIS CLUSTER                   │
│                                                              │
│  DESIGN PRINCIPLES:                                          │
│  1. Detect problems BEFORE they affect users                 │
│  2. Maintain rollback capability at EVERY phase              │
│  3. One change at a time → verify → next change              │
│  4. The hashing algorithm change is a MIGRATION              │
│     of key mapping, not just a backend swap                  │
│                                                              │
│  TOTAL PHASES: 6 (not 3)                                     │
│  ESTIMATED DURATION: 3-4 weeks                               │
└──────────────────────────────────────────────────────────────┘
```

### Phase 0: Pre-Migration Analysis [Week 1]

```
OBJECTIVE: Understand traffic patterns BEFORE touching 
anything. Find hot keys before they find you.

STEP 1: KEY ACCESS PROFILING ON MEMCACHED

  # Enable Memcached verbose logging (or use extstore 
  # metrics, or proxy-level logging):
  
  # Use mcrouter (Facebook's Memcached proxy) or 
  # mctop (Memcached top):
  mctop --host memcached-node1 --port 11211 --sort calls
  
  # Run for 24 hours during peak traffic.
  # Identify:
  # → Top 100 keys by read frequency
  # → Top 100 keys by size
  # → Keys with read:write ratio > 100:1 (hot reads)
  # → Keys with size > 10KB (large values)

  EXPECTED FINDING:
  → session:workspace:acme-corp — 820 reads/sec
  → session:workspace:globex — 340 reads/sec
  → session:workspace:initech — 290 reads/sec
  → These workspace keys are HOT KEYS.

STEP 2: KEY REDESIGN

  → BEFORE migration, redesign the workspace key 
    structure (Q1c solution):
    → Shard presence by user_id
    → Shard typing by channel_id
    → Move active_channels to per-user keys
  
  → Deploy the new key structure to Memcached FIRST.
  → Run for 1 week. Verify hot keys are eliminated.
  → The key sharding fix is independent of the 
    Memcached → Redis migration. Do it first.
  
  RATIONALE: Fix the data model BEFORE changing the 
  infrastructure. Two simultaneous changes = impossible 
  to diagnose if something goes wrong.

STEP 3: HASHING ALGORITHM ANALYSIS

  Memcached consistent hashing and Redis CRC16 slot 
  mapping produce COMPLETELY DIFFERENT key distributions.
  
  # For every active key in Memcached, compute:
  memcached_node = consistent_hash(key, nodes=20, vnodes=150)
  redis_slot = CRC16(key) % 16384
  redis_master = slot_to_master(redis_slot)
  
  # Build a heat map:
  # For each Redis master, sum the access frequency of 
  # all keys that will land on it.
  # 
  # If any master's projected load is >2x the average:
  # → Adjust the slot distribution BEFORE migration
  # → Or add more masters to reduce per-node load

STEP 4: REDIS CLUSTER SIZING

  Current Memcached: 20 nodes, ~16GB total
  Proposed Redis: 6 masters → too few.
  
  SIZING CALCULATION:
  → 4M sessions × 4KB = 16GB data
  → Memcached spreads across 20 nodes = 800MB per node
  → Redis 6 masters = 2.67GB per node (3.3x more per node)
  → Redis is more CPU-intensive than Memcached per 
    operation (richer data structures, cluster protocol)
  → 6 masters cannot absorb 20 Memcached nodes' worth 
    of load, even without hot keys
  
  RECOMMENDATION: Start with 12 masters (not 6).
  → 1.33GB per master, ~333K sessions per master
  → More headroom for CPU spikes
  → Slots better distributed
  → Can scale down later if over-provisioned 
    (removing nodes is safer than adding under pressure)

ROLLBACK: N/A (this phase is analysis only, no 
production changes except the key redesign, which 
rolls back by reverting the application code).
```

### Phase 1: Shadow Reads [Week 2, Days 1-3]

```
OBJECTIVE: Prove Redis returns the SAME data as Memcached 
for every read, at acceptable latency, without affecting 
users.

IMPLEMENTATION:
  Every read request goes to MEMCACHED (the source of 
  truth). In parallel, a SHADOW READ goes to Redis.
  The Redis result is COMPARED to the Memcached result 
  but NOT returned to the user.

  async def get_session(session_key):
      # Primary read: Memcached (user sees this)
      mc_result = await memcached.get(session_key)
      
      # Shadow read: Redis (user doesn't see this)
      try:
          redis_result = await asyncio.wait_for(
              redis.get(session_key), timeout=0.05  # 50ms
          )
          # Compare
          if redis_result and mc_result:
              if redis_result != mc_result:
                  metrics.increment("shadow_read.mismatch")
                  log.warn(f"Mismatch: key={session_key}")
              else:
                  metrics.increment("shadow_read.match")
          elif mc_result and not redis_result:
              metrics.increment("shadow_read.redis_miss")
          # Redis miss is expected initially — dual-write 
          # hasn't run long enough to populate everything
      except asyncio.TimeoutError:
          metrics.increment("shadow_read.redis_timeout")
      
      return mc_result  # Always return Memcached result

METRICS TO WATCH:
  → shadow_read.mismatch: should be 0% after warm-up
  → shadow_read.redis_miss: should decrease over time 
    as dual-write populates Redis
  → shadow_read.redis_timeout: should be < 0.1%
  → Redis node CPU: verify no hot node developing
  → Redis p99 latency: should be < 5ms

  ┌────────────────────────────────────────────────┐
  │  KEY INSIGHT: Shadow reads reveal the hot key  │
  │  problem BEFORE it affects users. If master-2  │
  │  shows 78% CPU during shadow reads, you KNOW   │
  │  it will be worse under real read traffic.     │
  │  You can fix it (Q1c) before Phase 2.          │
  └────────────────────────────────────────────────┘

EXIT CRITERIA FOR PHASE 1:
  → Mismatch rate: 0% for 48 hours
  → Redis miss rate: < 2%
  → Redis p99: < 5ms
  → NO hot node (max CPU across masters < 40%)
  → All criteria met for 48 consecutive hours

ROLLBACK: Remove shadow read code path. Zero user impact 
(shadow reads were never user-facing).
```

### Phase 2: Dual-Write [Week 2, Day 3 — ongoing]

```
OBJECTIVE: Every write goes to both Memcached and Redis.
Reads still from Memcached.

  async def write_session(session_key, session_data, ttl):
      # Primary: Memcached
      await memcached.set(session_key, session_data, ttl)
      
      # Secondary: Redis (async, fire-and-forget with retry)
      try:
          await asyncio.wait_for(
              redis.set(session_key, session_data, ex=ttl),
              timeout=0.05
          )
      except Exception as e:
          # Log and retry asynchronously
          # DO NOT fail the user's request because Redis 
          # write failed. Memcached is still primary.
          await retry_queue.enqueue(
              "redis_write", session_key, session_data, ttl
          )
          metrics.increment("dual_write.redis_failure")

  # Redis write failures: queue and retry.
  # If retry queue grows: Redis is unhealthy → investigate 
  # before proceeding to Phase 3.

EXIT CRITERIA:
  → dual_write.redis_failure rate: < 0.01%
  → Shadow read mismatch: 0% (still running from Phase 1)
  → Redis hit rate on shadow reads: > 99%
  → No hot nodes on Redis

ROLLBACK: Stop Redis writes. Memcached remains primary.
No user impact.
```

### Phase 3: Canary Read Switch [Week 3, Days 1-3]

```
OBJECTIVE: Switch a SMALL percentage of reads to Redis. 
Validate with real user traffic. Detect problems at 
small blast radius.

  CANARY STRATEGY:
  → 1% of reads from Redis (99% still Memcached)
  → Target: non-critical workspaces first 
    (internal test workspaces, low-activity workspaces)
  → Exclude top-10 workspaces by size from canary
  
  → If 1% clean for 4 hours: increase to 5%
  → If 5% clean for 4 hours: increase to 10%
  → If 10% clean for 12 hours: increase to 25%
  → If 25% clean for 24 hours: increase to 50%
  → If 50% clean for 24 hours: increase to 100%

  async def get_session(session_key, user_id):
      if should_use_redis(user_id):  # Canary selection
          result = await redis.get(session_key)
          if result is None:
              # Redis miss: fall back to Memcached
              # This shouldn't happen if dual-write is 
              # working, but defense in depth
              metrics.increment("canary.redis_miss_fallback")
              return await memcached.get(session_key)
              # Also backfill Redis:
              # await redis.set(session_key, result, ex=ttl)
          return result
      else:
          return await memcached.get(session_key)

MONITORING AT EACH CANARY STEP:
  → Error rate: per-canary vs control group
  → Latency: per-canary vs control group
  → User-facing metrics: presence accuracy, typing 
    indicator delay, session expiry rate
  → Redis cluster: per-node CPU, per-node connections, 
    per-node memory
  → Hot key detection: continuous top-key monitoring

  IF ANY METRIC DEGRADES:
  → STOP canary ramp
  → Investigate
  → If Redis-specific: fix and restart canary from 
    current percentage
  → If unfixable: roll back to 0% Redis reads

ROLLBACK: Set canary percentage to 0%. All reads 
return to Memcached instantly. Redis data remains 
populated via dual-write for future attempt.
```

### Phase 4: Full Read Cutover [Week 3, Day 4]

```
OBJECTIVE: 100% of reads from Redis.

  This is where the original plan jumped to immediately.
  We arrive here only after the canary has been at 100% 
  for 24 hours with zero issues.

  → Memcached is still receiving dual-writes (safety net)
  → If anything goes wrong: revert to Memcached reads 
    in one config change (< 30 seconds)

DURATION: Run for 1 FULL WEEK at 100% Redis reads + 
Memcached dual-write before proceeding.

ROLLBACK: Revert read config to Memcached. Dual-write 
ensures Memcached has current data. Instant rollback.
```

### Phase 5: Stop Dual-Write [Week 4, Day 1]

```
OBJECTIVE: Stop writing to Memcached. Redis is now 
the sole session store.

  BEFORE THIS STEP:
  → Redis has been serving 100% of reads for 1 week
  → Zero Redis-attributable incidents
  → All monitoring baselines established on Redis-only 
    read path

  AFTER STOPPING DUAL-WRITE:
  → Memcached data immediately starts aging out (TTLs 
    expire, no new writes)
  → Rollback to Memcached becomes IMPOSSIBLE once 
    Memcached data expires
  → This is the POINT OF NO RETURN

  THEREFORE:
  → Memcached remains running (but not receiving writes) 
    for 48 hours
  → During those 48 hours: if Redis fails, re-enable 
    dual-write + switch reads to Memcached
  → Memcached data may be stale (up to 48 hours old), 
    but stale sessions > no sessions
  → After 48 hours: Memcached can be decommissioned

ROLLBACK: Re-enable dual-write + Memcached reads.
Sessions written in the last 48 hours may be lost 
(users re-login). Acceptable for a messaging platform.
```

### Phase 6: Decommission Memcached [Week 4, Day 3+]

```
OBJECTIVE: Remove Memcached infrastructure.

  → Drain Memcached nodes
  → Remove dual-write code path
  → Remove Memcached client libraries
  → Terminate Memcached instances
  → Update architecture documentation
  → Close migration project

ROLLBACK: None. This is irreversible. Only proceed 
when confident Redis is stable.
```

---

## Q5: Mitigation Plan at 12:20

### Situation Assessment

```
┌──────────────────────────────────────────────────────────────┐
│  CURRENT STATE AT 12:20                                      │
│                                                              │
│  REDIS CLUSTER:                                              │
│  → master-2 (NEW — promoted replica): has stale data         │
│  → master-7: has partially migrated data                     │
│  → Slots 2731-3413: inconsistent state                       │
│  → Error rate: 4.7% (was 0.01%)                              │
│  → Cache miss rate: 23% (was 1.8%)                           │
│                                                              │
│  DOWNSTREAM IMPACT:                                          │
│  → Auth service load: 3x normal (session misses →            │
│    re-authentication flood)                                  │
│  → Auth service DB pool: 87% (approaching exhaustion)        │
│  → If auth DB pool exhausts: ALL logins fail, not just       │
│    the 23% with cache misses → TOTAL OUTAGE                  │
│                                                              │
│  RISK HIERARCHY:                                             │
│  1. Auth service cascade failure (imminent, affects ALL)     │
│  2. Continued data loss in inconsistent slots                │
│  3. User experience (presence, typing, sessions)             │
│  4. Redis cluster stability                                  │
│                                                              │
│  CRITICAL INSIGHT: Memcached is still receiving writes       │
│  (Phase 2 = reads switched, but dual-write still active).    │
│  Memcached has CURRENT data. It's a ready rollback target.   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Step-by-Step Mitigation

```
STEP 1: PROTECT THE AUTH SERVICE [IMMEDIATE — 12:20]

  The auth service at 87% DB pool utilization is the 
  most dangerous element. If it exhausts, we go from 
  "23% of users have session issues" to "100% of users 
  can't log in." This is the cascade.

  # Rate-limit session-miss-triggered re-authentication:
  # Instead of every cache miss triggering a full 
  # re-auth against the DB, implement a token bucket:
  
  # OPTION A: Return a temporary "session rebuilding" 
  # state to the client. Client retries in 5 seconds.
  # This spreads the re-auth load over time instead 
  # of a thundering herd.
  
  # OPTION B: Queue re-auth requests with a concurrency 
  # limit matching the DB pool headroom:
  
  AUTH_SEMAPHORE = asyncio.Semaphore(50)  # Max 50 concurrent re-auths
  
  async def handle_session_miss(user_id):
      if AUTH_SEMAPHORE.locked():
          # Queue is full. Tell client to retry.
          return Response(status=503, 
                         headers={"Retry-After": "5"})
      async with AUTH_SEMAPHORE:
          return await rebuild_session(user_id)
  
  # This caps auth DB load regardless of cache miss rate.
  # Pool stays at safe utilization.
  
  VERIFY: Auth service DB pool drops below 70%.
  TIME: 2-3 minutes to deploy config change.
```

```
STEP 2: ROLL BACK READS TO MEMCACHED [12:23]

  Memcached has been receiving dual-writes this entire 
  time. It has CURRENT DATA for all sessions. It's the 
  fastest path to stability.

  # Feature flag or config change:
  feature_flag.set("SESSION_READ_SOURCE", "memcached")
  
  # Immediately:
  # → All session reads go to Memcached (known-good)
  # → Cache miss rate drops from 23% to ~1.8% (baseline)
  # → Auth service load drops from 3x to 1x
  # → Error rate drops from 4.7% to ~0.01%
  # → Users stop being logged out
  # → Presence and typing indicators recover

  # DO NOT touch Redis Cluster yet. Just stop reading 
  # from it. Let it sit in its inconsistent state while 
  # users recover.

  VERIFY: 
  → Error rate < 0.1% within 2 minutes
  → Cache miss rate < 2% within 2 minutes
  → Auth service DB pool < 50% within 5 minutes
  → User-facing symptoms (presence, typing) recovering
  
  TIME: 30 seconds to change config. 2-5 minutes to verify.
```

```
STEP 3: STABILIZE — STOP DIGGING [12:28]

  # Do NOT:
  # → Attempt further resharding
  # → Attempt manual failover or failback
  # → Try to fix Redis cluster state under pressure
  
  # DO:
  # → Confirm Memcached is serving all reads correctly
  # → Confirm dual-write is still active (Redis still 
  #   receiving writes for later recovery)
  # → Communicate to stakeholders: "Service restored. 
  #   Migration rolled back. Redis cluster repair will 
  #   happen during maintenance window."

  VERIFY: All user-facing metrics at baseline for 
  15 minutes before proceeding.
```

```
STEP 4: FIX REDIS CLUSTER STATE [12:45, after stabilization]

  Users are on Memcached. Redis is not serving traffic.
  We can now repair Redis WITHOUT user impact.

  # Step 4a: Check cluster state
  redis-cli --cluster check <node>:6379
  # Identify all inconsistent slots
  
  # Step 4b: Fix slot ownership
  redis-cli --cluster fix <node>:6379
  # Resolves IMPORTING/MIGRATING states
  # Assigns disputed slots to single owners
  
  # Step 4c: If --cluster fix doesn't fully resolve:
  # Manually set slot ownership for each affected slot:
  for slot in range(2731, 3414):
      # Assign all contested slots back to new master-2
      redis-cli -h <each-master> \
        CLUSTER SETSLOT $slot NODE <new-master-2-id>
  done
  
  # Step 4d: Clean up orphaned keys on master-7
  # Keys in slots now owned by new master-2 that 
  # exist on master-7 are orphans:
  for slot in range(2731, 3414):
      keys=$(redis-cli -h master-7 \
        CLUSTER GETKEYSINSLOT $slot 100)
      for key in $keys; do
          redis-cli -h master-7 DEL $key
      done
  done
  
  # Step 4e: Verify cluster health
  redis-cli --cluster check <node>:6379
  # [OK] All 16384 slots covered
  # [OK] All nodes agree on configuration
  
  # Step 4f: Repopulate Redis from Memcached
  # Dual-write is still active, so new writes land 
  # in Redis. But keys that were lost during the 
  # failover need to be backfilled.
  # Option: temporarily enable shadow-reads from Redis 
  # (reads go to Memcached, shadow to Redis).
  # On shadow miss: backfill Redis from Memcached result.
  # Run for 1 hour to warm up Redis.

  VERIFY: Redis cluster healthy, all slots covered, 
  hit rate recovering toward 98%+ on shadow reads.
```

```
STEP 5: ROOT CAUSE FIXES BEFORE RE-ATTEMPTING MIGRATION [Next Week]

  Before re-attempting the Memcached → Redis migration:

  1. FIX THE HOT KEY (Q1c)
     → Deploy workspace key sharding
     → Verify on Memcached first (1 week)
     → Then proceed with proper migration plan (Q4)

  2. RIGHT-SIZE THE REDIS CLUSTER
     → 12 masters instead of 6
     → Verify projected load per master < 40% CPU 
       at peak traffic

  3. IMPLEMENT THE PROPER MIGRATION PLAN (Q4)
     → Phase 0 through Phase 6
     → Shadow reads before live reads
     → Canary before full cutover
     → Rollback capability at every phase

  4. OPERATIONAL SAFEGUARDS FOR FUTURE RESHARDS
     → Increase cluster-node-timeout before resharding
     → Disable auto-failover on resharding node
     → Never reshard a node above 50% CPU
     → Never reshard during peak traffic

  5. POST-INCIDENT REVIEW
     → Why was the hot key not detected before migration?
       → No pre-migration traffic profiling
     → Why was the cluster sized at 6 masters for 
       workload that ran on 20 Memcached nodes?
       → Undersizing without load testing
     → Why was resharding attempted on an overloaded node 
       during peak traffic?
       → Panic response without pre-defined playbook
     → Why was there no rollback plan for Phase 2?
       → Memcached was the rollback, but nobody explicitly 
         documented "if Redis fails, revert reads to 
         Memcached" as a runbook step
```

### Mitigation Timeline Summary

```
┌────────┬─────────────────────────────────┬───────────────┐
│  TIME  │ ACTION                          │ EFFECT        │
├────────┼─────────────────────────────────┼───────────────┤
│ 12:20  │ Rate-limit auth re-auth flood   │ Prevent auth  │
│        │ (semaphore on concurrent auths) │ DB cascade    │
├────────┼─────────────────────────────────┼───────────────┤
│ 12:23  │ Roll back reads to Memcached    │ Error rate    │
│        │                                 │ 4.7% → <0.1%  │
│        │                                 │ Miss rate     │
│        │                                 │ 23% → <2%     │
├────────┼─────────────────────────────────┼───────────────┤
│ 12:28  │ Verify stabilization. Stop.     │ Confirm       │
│        │ Communicate to stakeholders.    │ baseline      │
├────────┼─────────────────────────────────┼───────────────┤
│ 12:45  │ Fix Redis cluster state         │ Redis healthy │
│        │ (--cluster fix, slot reassign,  │ but not       │
│        │  orphan cleanup)                │ serving reads │
├────────┼─────────────────────────────────┼───────────────┤
│ 13:00  │ Backfill Redis via shadow reads │ Redis warm    │
│        │ from Memcached                  │ cache ready   │
├────────┼─────────────────────────────────┼───────────────┤
│ Next   │ Fix hot key, resize cluster,    │ Proper        │
│ week   │ re-attempt with proper plan     │ migration     │
└────────┴─────────────────────────────────┴───────────────┘

KEY PRINCIPLE APPLIED:
  → Step 1: Stop the bleeding (protect auth service)
  → Step 2: Restore service (rollback to Memcached)
  → Step 3: Stabilize and verify (one change, verify)
  → Step 4: Fix the broken thing (Redis cluster repair)
  → Step 5: Fix the root cause (hot key, sizing, process)
  
  NEVER try to fix the root cause during an active 
  incident. Restore service FIRST, root-cause LATER.
```

