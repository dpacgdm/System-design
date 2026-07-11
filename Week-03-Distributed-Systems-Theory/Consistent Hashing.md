# Week 3, Topic 3: Consistent Hashing

---

## Learning Objectives
```
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Explain WHY naive hash-mod-N breaks catastrophically    ║
║      when nodes are added or removed, with exact math        ║
║                                                              ║
║   2. Draw and explain the consistent hashing ring, including ║
║      how keys are assigned to nodes and what happens when    ║
║      a node joins or leaves                                  ║
║                                                              ║
║   3. Explain virtual nodes (vnodes) — why they exist, the    ║
║      math behind how many you need, and the tradeoff of      ║
║      more vs fewer vnodes                                    ║
║                                                              ║
║   4. Describe how Cassandra, DynamoDB, and Redis Cluster     ║
║      each implement (or diverge from) consistent hashing     ║
║      and WHY they made different choices                     ║
║                                                              ║
║   5. Calculate the blast radius of a node failure in a       ║
║      consistent hashing ring (how much data moves, which     ║
║      nodes absorb it)                                        ║
║                                                              ║
║   6. Diagnose hot-partition problems in production systems   ║
║      using consistent hashing and prescribe fixes            ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Hash-mod-N is fine until you outgrow it"            ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Adding or removing one node remaps ~N/(N±1) of ALL keys.       ║
║   On a 100-node cluster losing 1 node, ~99% of keys move — cache        ║
║   stampede, thundering herd, and hours of rebalancing. Not a            ║
║   "later problem" — it is catastrophic at scale.                        ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Consistent hashing guarantees perfect balance"      ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Without virtual nodes, physical nodes on the ring get          ║
║   uneven arc lengths. A node added between two dense clusters           ║
║   absorbs disproportionate keys. Vnodes fix distribution — not          ║
║   the base algorithm alone.                                             ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Consistent hashing means zero data movement"        ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Only ~1/N keys move per node change (vs ~100% with mod-N).     ║
║   On a 100-node ring, adding a node still moves ~1% of total data       ║
║   — which at petabyte scale is terabytes. Plan rebalancing capacity.    ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Virtual nodes are optional optimization"            ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Production systems (Cassandra, DynamoDB) use vnodes for        ║
║   load balance, faster rebalancing, and heterogeneous hardware.         ║
║   Without vnodes, one beefy node and one small node on the ring         ║
║   get equal key ranges — the small node dies.                           ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Consistent hashing solves hot keys"                 ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Consistent hashing distributes KEYS evenly — not TRAFFIC.      ║
║   A celebrity user's partition key creates a hot partition regardless   ║
║   of ring algorithm. Fix with key salting, write sharding, or           ║
║   caching — not more hash rings.                                        ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Jump/hash and rendezvous are the same thing"        ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Consistent hashing minimizes movement on node change.          ║
║   Jump consistent hash and rendezvous hashing optimize for              ║
║   different properties (minimal memory, zero metadata). Pick based      ║
║   on whether you prioritize rebalance cost or lookup speed.             ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

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
                    ╭─────┴─────╮
                 ╱                 ╲
               ╱                     ╲
             ╱                         ╲
            │                           │
   3/4 ─────┤         HASH RING         ├───── 1/4
   of space │                           │ of space
             ╲                         ╱
               ╲                     ╱
                 ╲                 ╱
                    ╰─────┬─────╯
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
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   When a node joins or leaves:                               ║
║     → Only ~K/N keys need to move                            ║
║       (K = total keys, N = total nodes)                      ║
║     → Only the NEIGHBORING node(s) are affected              ║
║     → All other nodes and keys are untouched                 ║
║                                                              ║
║   hash-mod-N: ~K×(N-1)/N keys move (nearly all)              ║
║   consistent hashing: ~K/N keys move (minimum)               ║
║                                                              ║
║   This is OPTIMAL — you can't do better than K/N             ║
║   because the new/removed node must take/give up             ║
║   its fair share.                                            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
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

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Before: A=25%, B=25%, C=25%, D=25%                         ║
  ║   After C crashes: A=25%, B=25%, D=50%                       ║
  ║   D is instantly overloaded.                                 ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

With vnodes (many positions per node):
  Node C crashes → C's vnodes are scattered across the ring
  → Each of C's vnodes is absorbed by a DIFFERENT successor
  → The load spreads across multiple surviving nodes

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Ring with vnodes:                                          ║
  ║   ...●A ●C ●B ●D ●C ●A ●C ●B ●D ●A ●C ●D...                  ║
  ║                                                              ║
  ║   C crashes. Each C-vnode's range goes to the                ║
  ║   next non-C vnode clockwise:                                ║
  ║                                                              ║
  ║   C-0's range → goes to B (the next node)                    ║
  ║   C-1's range → goes to A                                    ║
  ║   C-2's range → goes to B                                    ║
  ║   C-3's range → goes to D                                    ║
  ║   ...                                                        ║
  ║                                                              ║
  ║   Result: C's 25% is distributed roughly:                    ║
  ║   A absorbs ~8%, B absorbs ~8%, D absorbs ~9%                ║
  ║                                                              ║
  ║   After: A≈33%, B≈33%, D≈34%                                 ║
  ║   EVEN distribution of C's load!                             ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

THIS IS CRITICAL for production systems. When a node
fails, you want the load to spread EVENLY across all
surviving nodes, not dump onto one node (which would
then also fail under the extra load, causing a cascade).
```

#### The Vnodes Tradeoff

```
MORE VNODES IS NOT ALWAYS BETTER:

╔══════════════════════════════════════════════════════════════╗
║  MORE VNODES       │ FEWER VNODES                            ║
╠══════════════════════════════════════════════════════════════╣
║  Better uniformity │ Worse uniformity                        ║
║  Better rebalancing│ Rebalancing creates hot spots           ║
║  (load spreads     │ (load dumps onto one neighbor)          ║
║   across all nodes)│                                         ║
╠══════════════════════════════════════════════════════════════╣
║  More metadata     │ Less metadata                           ║
║  (ring has V×N     │ (ring has N entries)                    ║
║   entries to store │                                         ║
║   and replicate)   │                                         ║
╠══════════════════════════════════════════════════════════════╣
║  Slower ring       │ Faster ring lookups                     ║
║  lookups (more     │                                         ║
║  entries to search)│                                         ║
╠══════════════════════════════════════════════════════════════╣
║  Slower rebalancing│ Faster rebalancing                      ║
║  (more ranges to   │ (fewer, larger ranges to move)          ║
║   move, each small)│                                         ║
╠══════════════════════════════════════════════════════════════╣
║  More repair       │ Less repair traffic                     ║
║  traffic (Cassandra│                                         ║
║  repairs are per-  │                                         ║
║  vnode range)      │                                         ║
╚══════════════════════════════════════════════════════════════╝

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
╔════════════════════════════════════════════════════════════════════════╗
║               │ CASSANDRA        │ DYNAMODB         │ REDIS CLUSTER    ║
║               │ (Vnodes)         │ (Partition Split)│ (Fixed Slots)    ║
╠════════════════════════════════════════════════════════════════════════╣
║  Hash function│ Murmur3          │ Internal (MD5    │ CRC16            ║
║               │                  │ based)           │                  ║
╠════════════════════════════════════════════════════════════════════════╣
║  Ring/Space   │ -2^63 to +2^63  │ Internal ranges  │ 0 to 16383        ║
║  size         │                  │                  │ (16384 slots)    ║
╠════════════════════════════════════════════════════════════════════════╣
║  Granularity  │ 16-256 tokens   │ Automatic        │ 16384 fixed       ║
║  of placement │ per node         │ partition splits │ slots            ║
╠════════════════════════════════════════════════════════════════════════╣
║  Rebalancing  │ Automatic on     │ Fully automatic  │ MANUAL           ║
║               │ node join/leave  │ (managed service)│ (operator must   ║
║               │                  │                  │ reshard)         ║
╠════════════════════════════════════════════════════════════════════════╣
║  Node failure │ Load spreads to  │ Automatic        │ Replica promoted ║
║  behavior     │ multiple nodes   │ failover to      │ for affected     ║
║               │ (vnode neighbors)│ healthy nodes    │ slots. Load NOT  ║
║               │                  │                  │ spread evenly.   ║
╠════════════════════════════════════════════════════════════════════════╣
║  Hot spot     │ Split token      │ Automatic        │ Manual slot      ║
║  handling     │ range (manual)   │ partition split  │ migration        ║
╠════════════════════════════════════════════════════════════════════════╣
║  Metadata     │ Token ring       │ Partition map    │ 16KB slot bitmap ║
║  overhead     │ (V×N entries)    │ (internal)       │ (fixed size)     ║
╠════════════════════════════════════════════════════════════════════════╣
║  Best for     │ Large clusters,  │ Variable scale,  │ Simple caching,  ║
║               │ self-managed     │ managed service  │ known cluster    ║
║               │ infrastructure   │                  │ size             ║
╚════════════════════════════════════════════════════════════════════════╝
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

### Staff

## Production Patterns
```
╔══════════════════════════════════════════════════════════════╗
║   FAILURE MODE #1: HOT PARTITION                             ║
║                                                              ║
║   Scenario: Social media. Posts are partitioned by post_id.  ║
║   A celebrity posts something viral.                         ║
║   post_id=98765 → hashes to Node 3.                          ║
║   Millions of reads for post_id=98765 ALL hit Node 3.        ║
║                                                              ║
║   Consistent hashing can't help here — the KEY itself is     ║
║   hot, not the hash distribution. No matter how uniform      ║
║   the ring is, all requests for the same key go to the       ║
║   same node.                                                 ║
║                                                              ║
║   FIXES:                                                     ║
║   1. READ REPLICAS: Read from any of the RF replicas,        ║
║      not just the primary. Spreads read load across          ║
║      RF nodes instead of 1.                                  ║
║                                                              ║
║   2. CLIENT-SIDE CACHING: Cache hot objects at the           ║
║      application tier. Don't even hit the database.          ║
║                                                              ║
║   3. KEY SHARDING (scatter-gather):                          ║
║      Instead of storing post_id=98765 on one node:           ║
║      Split into post_id=98765:shard0, post_id=98765:shard1,  ║
║      ..., post_id=98765:shardN                               ║
║      Each shard hashes to a different node on the ring.      ║
║      Read from a random shard. Write to all shards.          ║
║      → Spreads one hot key across N nodes.                   ║
║      → Cost: writes are N× more expensive.                   ║
║                                                              ║
║   4. DYNAMODB APPROACH: Automatic partition splitting.       ║
║      The hot partition is split into sub-partitions,         ║
║      each on a different node. Transparent to the client.    ║
╠══════════════════════════════════════════════════════════════╣
║   FAILURE MODE #2: CASCADE DURING REBALANCING                ║
║                                                              ║
║   Scenario: 6-node Cassandra cluster. Node 3 crashes.        ║
║   Node 3's data should be served by neighboring nodes.       ║
║                                                              ║
║   Without vnodes:                                            ║
║   → ALL of Node 3's range goes to Node 4                     ║
║   → Node 4's load doubles: 33% → 50%+                        ║
║   → Node 4 is now under heavy load (CPU, disk, memory)       ║
║   → Node 4's response times increase                         ║
║   → Gossip protocol marks Node 4 as slow                     ║
║   → If Node 4 also crashes: Node 5 absorbs BOTH              ║
║     Node 3 and Node 4's data → Node 5 overwhelmed            ║
║   → CASCADE FAILURE                                          ║
║                                                              ║
║   With vnodes (e.g., 16 per node):                           ║
║   → Node 3's 16 vnode ranges are absorbed by ~16 different   ║
║     successor nodes (some may overlap, but spread is good)   ║
║   → Each surviving node absorbs ~1/5 of Node 3's load        ║
║   → No single node is overwhelmed                            ║
║   → CASCADE PREVENTED                                        ║
║                                                              ║
║   LESSON: Vnodes are not just about uniform distribution.    ║
║   They're about CASCADE PREVENTION during node failures.     ║
╠══════════════════════════════════════════════════════════════╣
║   FAILURE MODE #3: HASH FUNCTION COLLISION                   ║
║                                                              ║
║   If the hash function produces CLUSTERS of similar values   ║
║   for related keys, multiple "hot" keys might hash to the    ║
║   same region of the ring → same node.                       ║
║                                                              ║
║   Example:                                                   ║
║     key="order:10001" → hash = 42001                         ║
║     key="order:10002" → hash = 42002                         ║
║     key="order:10003" → hash = 42003                         ║
║     Sequential IDs produce sequential hashes!                ║
║     All recent orders hash to the same ring region.          ║
║                                                              ║
║   FIX: Use a hash function with GOOD DISTRIBUTION.           ║
║   → Murmur3 (Cassandra's choice): excellent distribution     ║
║     for sequential inputs                                    ║
║   → CRC16 (Redis Cluster): good distribution for most        ║
║     inputs                                                   ║
║   → MD5 (DynamoDB): cryptographic — excellent uniformity     ║
║     but slower than Murmur3                                  ║
║   → DO NOT USE: Java's hashCode() — terrible distribution    ║
║     for sequential integers                                  ║
║                                                              ║
║   Verify distribution with:                                  ║
║     # Python: check hash distribution                        ║
║     import mmh3  # murmurhash3                               ║
║     from collections import Counter                          ║
║     buckets = Counter()                                      ║
║     for i in range(1000000):                                 ║
║         h = mmh3.hash(f"order:{i}") % 100                    ║
║         buckets[h] += 1                                      ║
║     # Each bucket should have ~10000 (±300)                  ║
║     print(max(buckets.values()) - min(buckets.values()))     ║
║     # Should be < 1000 for good distribution                 ║
╠══════════════════════════════════════════════════════════════╣
║   FAILURE MODE #4: UNEQUAL NODE CAPACITY                     ║
║                                                              ║
║   Not all nodes are identical. In cloud environments:        ║
║   → Some nodes have more RAM (r5.2xlarge vs r5.xlarge)       ║
║   → Some have faster disks (io2 vs gp3)                      ║
║   → After a replacement, a new node might have different     ║
║     specs                                                    ║
║                                                              ║
║   Standard consistent hashing assigns equal ranges to all    ║
║   nodes, regardless of capacity.                             ║
║                                                              ║
║   FIX: WEIGHTED vnodes.                                      ║
║   → Assign MORE vnodes to higher-capacity nodes              ║
║   → Node with 2x RAM → 2x vnodes → 2x data                   ║
║   → Cassandra: set different num_tokens per node             ║
║                                                              ║
║   # cassandra.yaml on a bigger node:                         ║
║   num_tokens: 32   # (vs 16 on standard nodes)               ║
║                                                              ║
║   FIX: WEIGHTED slots (Redis Cluster).                       ║
║   → Assign more slots to higher-capacity nodes               ║
║   → redis-cli --cluster rebalance --cluster-weight           ║
║     node1=2 node2=1 node3=1                                  ║
║   → Node1 gets 2x the slots (and 2x the data)                ║
╚══════════════════════════════════════════════════════════════╝
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

## SRE Diagnostic Toolkit

```
WHAT GOES WRONG WITH A RING: load skew, migration storms, and hot keys that
no amount of rebalancing can fix.

METRICS TO WATCH
  Per-node load skew:
    max(node_request_rate) / avg(node_request_rate)   (target < 1.3)
    max(node_bytes_stored) / avg(node_bytes_stored)
  Vnode distribution:
    tokens (vnodes) per physical node; std-dev of key ownership %
  Rebalance health:
    fraction of keys moved on a membership change (should be ~1/N)
    streaming/bootstrap throughput and ETA
  Hot key detection:
    top-K key request rate vs median (Redis --bigkeys, Cassandra
    nodetool toppartitions ks tbl 1000)

COMMANDS
  Cassandra:
    nodetool status            # ownership % per node — uneven => token imbalance
    nodetool ring              # token ranges per node
    nodetool toppartitions     # hot partitions in a live window
    nodetool netstats          # streaming during bootstrap/decommission
  Redis Cluster:
    redis-cli cluster nodes    # slot ranges per node
    redis-cli cluster slots
    redis-cli --hotkeys        # (with LFU maxmemory-policy)

DIAGNOSTIC DECISION TREE
  One node hot, ownership even?
    -> HOT KEY (single partition), not a ring problem. Consistent hashing
       cannot split a single key. Fix: split the key (add a suffix bucket),
       add a client-side/edge cache, or replicate the key.
  One node hot, ownership UNeven?
    -> too few vnodes or bad token assignment. Increase vnodes (100-256/node)
       or rebalance tokens.
  Massive key movement on adding one node?
    -> you are NOT using consistent hashing (likely hash mod N) OR vnode
       count is tiny. Correct consistent hashing moves ~1/N of keys.

LOG / SIGNATURE PATTERNS
  Latency spike on ONE shard during a scale-out  -> streaming saturating that node
  Cache hit ratio cliff after adding a node      -> keys remapped (expected once,
                                                    warm the new node before cutover)
```

---

## Decision Framework

```
CHOOSING A PARTITIONING SCHEME

  ┌──────────────────┬─────────────────────────────┬─────────────────────────┐
  │ Scheme           │ Use when                    │ Cost / caveat           │
  ├──────────────────┼─────────────────────────────┼─────────────────────────┤
  │ Consistent hash  │ Dynamic membership (cache,  │ No efficient range      │
  │ + vnodes         │ KV ring, Cassandra/Dynamo); │ scans; hot single key   │
  │                  │ want ~1/N remap on change   │ still unsolved          │
  ├──────────────────┼─────────────────────────────┼─────────────────────────┤
  │ Range sharding   │ Ordered scans, time-series, │ Hot "latest" shard for  │
  │                  │ pagination by key           │ monotonic keys; needs   │
  │                  │                             │ split/merge machinery   │
  ├──────────────────┼─────────────────────────────┼─────────────────────────┤
  │ Hash mod N       │ Fixed cluster, batch jobs   │ NEVER for stateful prod │
  │                  │ only                        │ — N change reshuffles   │
  │                  │                             │ ~all keys               │
  ├──────────────────┼─────────────────────────────┼─────────────────────────┤
  │ Directory /      │ Arbitrary placement,        │ Extra lookup + the      │
  │ lookup table     │ controlled migration        │ directory is now a SPOF │
  └──────────────────┴─────────────────────────────┴─────────────────────────┘

VNODE SIZING
  Too few (1 per node)  -> uneven ownership, large chunks move on change.
  Sweet spot            -> ~128-256 tokens per physical node (Cassandra default
                           256; Dynamo-style "virtual nodes" similar).
  Trade-off             -> more vnodes = smoother distribution but more metadata
                           and more streaming ranges to track.

WEIGHTED / HETEROGENEOUS NODES
  Bigger instances should own more tokens (weight by capacity), or one node
  becomes the bottleneck at even token counts.

BOUNDED-LOAD VARIANT
  Plain consistent hashing can still produce 1.5-2x skew. "Consistent hashing
  with bounded loads" caps any node at (1+eps)*average by spilling to the next
  node — worth it for cache fleets where skew = origin overload.

HARD RULE: hashing distributes KEYS, not LOAD. A single hot key defeats every
ring. Detect hot keys first (SRE toolkit above); then cache/split/replicate.
```

---

## Hands-On Exercises
```
╔═══════════════════════════════════════════════════════════════╗
║   EXERCISE 1: Visualize the Hash-Mod-N Problem                ║
║                                                               ║
║   # Python script: compare key movement                       ║
║   import hashlib                                              ║
║                                                               ║
║   def hash_key(key, n_nodes):                                 ║
║       h = int(hashlib.md5(key.encode()).hexdigest(), 16)      ║
║       return h % n_nodes                                      ║
║                                                               ║
║   # Generate 10000 keys                                       ║
║   keys = [f"user:{i}" for i in range(10000)]                  ║
║                                                               ║
║   # Assign to 10 nodes                                        ║
║   assignment_10 = {k: hash_key(k, 10) for k in keys}          ║
║                                                               ║
║   # Add an 11th node                                          ║
║   assignment_11 = {k: hash_key(k, 11) for k in keys}          ║
║                                                               ║
║   # Count how many keys MOVED                                 ║
║   moved = sum(1 for k in keys                                 ║
║               if assignment_10[k] != assignment_11[k])        ║
║   print(f"Keys moved: {moved}/{len(keys)}")                   ║
║   print(f"Percentage: {moved/len(keys)*100:.1f}%")            ║
║   # Expected: ~90.9% moved (10/11)                            ║
║                                                               ║
║   # Now implement consistent hashing and compare:             ║
║   # (exercise continues below)                                ║
╠═══════════════════════════════════════════════════════════════╣
║   EXERCISE 2: Build a Consistent Hash Ring                    ║
║                                                               ║
║   # Python: minimal consistent hashing implementation         ║
║   import hashlib                                              ║
║   from bisect import bisect_right                             ║
║                                                               ║
║   class ConsistentHashRing:                                   ║
║       def __init__(self, vnodes=150):                         ║
║           self.vnodes = vnodes                                ║
║           self.ring = []      # sorted list of (hash, node)   ║
║           self.nodes = set()                                  ║
║                                                               ║
║       def _hash(self, key):                                   ║
║           return int(hashlib.md5(                             ║
║               key.encode()).hexdigest(), 16)                  ║
║                                                               ║
║       def add_node(self, node):                               ║
║           self.nodes.add(node)                                ║
║           for i in range(self.vnodes):                        ║
║               h = self._hash(f"{node}:vnode{i}")              ║
║               self.ring.append((h, node))                     ║
║           self.ring.sort()                                    ║
║                                                               ║
║       def remove_node(self, node):                            ║
║           self.nodes.discard(node)                            ║
║           self.ring = [(h, n) for h, n in self.ring           ║
║                        if n != node]                          ║
║                                                               ║
║       def get_node(self, key):                                ║
║           if not self.ring:                                   ║
║               return None                                     ║
║           h = self._hash(key)                                 ║
║           hashes = [r[0] for r in self.ring]                  ║
║           idx = bisect_right(hashes, h) % len(self.ring)      ║
║           return self.ring[idx][1]                            ║
║                                                               ║
║   # Test: add 10 nodes, then add an 11th                      ║
║   ring = ConsistentHashRing(vnodes=150)                       ║
║   for i in range(10):                                         ║
║       ring.add_node(f"node-{i}")                              ║
║                                                               ║
║   keys = [f"user:{i}" for i in range(10000)]                  ║
║   assignment_before = {k: ring.get_node(k) for k in keys}     ║
║                                                               ║
║   ring.add_node("node-10")  # add 11th node                   ║
║   assignment_after = {k: ring.get_node(k) for k in keys}      ║
║                                                               ║
║   moved = sum(1 for k in keys                                 ║
║               if assignment_before[k] != assignment_after[k]) ║
║   print(f"Keys moved: {moved}/{len(keys)}")                   ║
║   print(f"Percentage: {moved/len(keys)*100:.1f}%")            ║
║   # Expected: ~9% moved (1/11) ← MUCH better than 91%!        ║
║                                                               ║
║   # Experiment with different vnode counts:                   ║
║   # vnodes=1: poor distribution, ~30% variation               ║
║   # vnodes=10: better, ~15% variation                         ║
║   # vnodes=150: good, ~5% variation                           ║
║   # vnodes=500: diminishing returns, ~3% variation            ║
╠═══════════════════════════════════════════════════════════════╣
║   EXERCISE 3: Observe Redis Cluster Slot Distribution         ║
║                                                               ║
║   # Start a Redis Cluster (3 masters, 3 replicas):            ║
║   # Using docker:                                             ║
║   docker run -d --name redis-cluster \                        ║
║     -e REDIS_CLUSTER_CREATOR=yes \                            ║
║     -e REDIS_NODES="redis-0 redis-1 redis-2 \                 ║
║                     redis-3 redis-4 redis-5" \                ║
║     bitnami/redis-cluster                                     ║
║                                                               ║
║   # Check slot distribution:                                  ║
║   redis-cli --cluster check 127.0.0.1:6379                    ║
║                                                               ║
║   # Insert 100K keys and check distribution:                  ║
║   for i in $(seq 1 100000); do                                ║
║     redis-cli -c SET "key:$i" "value:$i" > /dev/null          ║
║   done                                                        ║
║                                                               ║
║   redis-cli --cluster check 127.0.0.1:6379                    ║
║   # Observe: keys per node should be roughly equal            ║
║   # (±5% with CRC16 distribution)                             ║
║                                                               ║
║   # Check which slot a key belongs to:                        ║
║   redis-cli CLUSTER KEYSLOT "key:12345"                       ║
║                                                               ║
║   # Simulate node failure: pause one master                   ║
║   docker pause redis-0                                        ║
║   # Watch the cluster detect the failure:                     ║
║   redis-cli --cluster check 127.0.0.1:6380                    ║
║   # The replica of redis-0 should be promoted                 ║
║   # Slots are NOT redistributed — just failover to replica    ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading
```
╔══════════════════════════════════════════════════════════════╗
║   READ AFTER THIS LESSON:                                    ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   DDIA Chapter 6: "Partitioning"                             ║
║   → Pages 199-207 (Partitioning of Key-Value Data)           ║
║     - "Partitioning by Hash of Key" (p. 203-204)             ║
║     This is consistent hashing explained in Kleppmann's      ║
║     terminology. He uses the term "hash partitioning"        ║
║     and discusses the tradeoffs between hash-based and       ║
║     range-based partitioning.                                ║
║                                                              ║
║   → Pages 207-211 (Partitioning and Secondary Indexes)       ║
║     Relevant for understanding how consistent hashing        ║
║     interacts with secondary indexes (scatter-gather).       ║
║                                                              ║
║   → Pages 211-216 (Rebalancing Partitions)                   ║
║     - "Fixed number of partitions" (p. 212-213)              ║
║       ← This is the Redis Cluster / DynamoDB approach        ║
║     - "Dynamic partitioning" (p. 214)                        ║
║       ← This is the DynamoDB partition split approach        ║
║     - "Partitioning proportionally to nodes" (p. 214-215)    ║
║       ← This is Cassandra's vnode approach                   ║
║     READ ALL THREE and compare — Kleppmann lays out the      ║
║     exact tradeoffs we covered.                              ║
║                                                              ║
║   → Pages 216-217 (Automatic vs Manual Rebalancing)          ║
║     Directly relevant to the SRE scenario (what goes wrong   ║
║     with automatic rebalancing during incidents).            ║
║                                                              ║
║   OPTIONAL:                                                  ║
║   → Original consistent hashing paper (Karger et al., 1997)  ║
║     "Consistent Hashing and Random Trees"                    ║
║     Short, readable, and historically important.             ║
║     Focus on Section 4 (the ring construction).              ║
║                                                              ║
║   TOTAL: ~20 pages from DDIA + optional paper.               ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Key Takeaways
```
╔══════════════════════════════════════════════════════════════╗
║   5 THINGS TO REMEMBER IF YOU FORGET EVERYTHING ELSE         ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. hash-mod-N is catastrophic for topology changes.        ║
║      Adding or removing one node moves ~(N-1)/N of all keys. ║
║      With 100 nodes, adding 1 node invalidates 99% of your   ║
║      cache. Consistent hashing moves only ~1/N (1%).         ║
║      This is the ENTIRE REASON consistent hashing exists.    ║
║                                                              ║
║   2. Virtual nodes solve TWO problems: uneven distribution   ║
║      AND cascade prevention. With basic consistent hashing   ║
║      (1 position per node), ranges are uneven AND a node     ║
║      failure dumps all load onto one neighbor. Vnodes        ║
║      spread both data AND failure-load across all nodes.     ║
║      Production systems use 16-256 vnodes per node.          ║
║                                                              ║
║   3. Consistent hashing CANNOT solve hot-key problems.       ║
║      If one key receives 1M reads/sec, all those reads go    ║
║      to the same node regardless of how perfect the ring is. ║
║      Solutions: read replicas, client-side caching, key      ║
║      sharding (scatter-gather), or DynamoDB-style adaptive   ║
║      partition splitting.                                    ║
║                                                              ║
║   4. Three implementations, three philosophies:              ║
║      Cassandra (vnodes): flexible, self-managing, complex    ║
║      Redis Cluster (16384 fixed slots): simple, manual       ║
║      DynamoDB (auto-split): managed, adaptive, opaque        ║
║      Know which one your system uses and WHY — it determines ║
║      how you handle rebalancing, failures, and hot spots.    ║
║                                                              ║
║   5. NEVER reshard/rebalance an overloaded node under load.  ║
║      Migration reads ALL keys and transfers them — this is   ║
║      heavy I/O on a node that's already at capacity.         ║
║      Mitigate the immediate problem first (scale reads,      ║
║      cache hot keys, redirect traffic), THEN rebalance       ║
║      when the node is healthy.                               ║
╚══════════════════════════════════════════════════════════════╝
```
> **Answer key (do not open until you attempt the scenario questions):**
> [`../answers/Week-03-Distributed-Systems-Theory/Consistent%20Hashing%20Answers.md`](../answers/Week-03-Distributed-Systems-Theory/Consistent%20Hashing%20Answers.md)

---

### Principal stretch

## Ops Sim: Northstar Session Store Hot Workspace Migration

**Drill note:** Answer from the incident timeline below. Distinguish even slot distribution from single-key load concentration.

```
╔════════════════════════════════════════════════════════════════╗
║   SCENARIO: Global Session Store Migration Gone Wrong          ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   You're the SRE for a large SaaS platform (Slack-like         ║
║   team messaging). The platform has 12 million daily active    ║
║   users across 3 regions (US, EU, APAC).                       ║
║                                                                ║
║   ARCHITECTURE:                                                ║
║   → User sessions are stored in a distributed cache            ║
║     (Memcached cluster using consistent hashing)               ║
║   → Each region has its own independent session cluster        ║
║   → US cluster: 20 Memcached nodes                             ║
║     → Consistent hashing ring with 150 vnodes per node         ║
║     → ~4M active sessions at peak                              ║
║     → Session data: user prefs, auth tokens, active            ║
║       channels, notification state (~4KB per session)          ║
║   → Load balancer uses consistent hashing on user_id           ║
║     to route requests (sticky sessions via ring)               ║
║                                                                ║
║   THE MIGRATION:                                               ║
║   Engineering decided to migrate from Memcached to Redis       ║
║   Cluster for better data structure support and persistence.   ║
║                                                                ║
║   NEW REDIS CLUSTER:                                           ║
║   → 12 nodes (6 masters, 6 replicas)                           ║
║   → 16384 hash slots distributed across 6 masters              ║
║   → Key mapping: CRC16(session_key) mod 16384                  ║
║                                                                ║
║   MIGRATION PLAN (approved last week):                         ║
║   → Phase 1: Dual-write to both Memcached and Redis            ║
║   → Phase 2: Switch reads from Memcached to Redis              ║
║   → Phase 3: Decommission Memcached                            ║
║                                                                ║
║   CURRENT STATE: Phase 2 just completed. Reads are now         ║
║   from Redis Cluster. Memcached still receiving writes.        ║
║                                                                ║
║   INCIDENT TIMELINE:                                           ║
║                                                                ║
║   10:00 — Phase 2 completed. All session reads now from        ║
║           Redis Cluster. Monitoring shows:                     ║
║           → Redis hit rate: 98.2% (good)                       ║
║           → p99 latency: 2.3ms (good)                          ║
║           → Error rate: 0.01% (acceptable)                     ║
║                                                                ║
║   11:30 — US traffic ramp. DAU climbing toward peak.           ║
║           Redis CPU utilization across 6 masters:              ║
║           Node 1: 34%    Node 4: 31%                           ║
║           Node 2: 78%    Node 5: 29%                           ║
║           Node 3: 32%    Node 6: 35%                           ║
║                                                                ║
║   11:45 — Alert fires:                                         ║
║           "Redis master-2 CPU > 75% sustained 10 min"          ║
║           Redis master-2 owns slots 2731-5460.                 ║
║                                                                ║
║   11:50 — Investigation reveals:                               ║
║           Top keys on master-2 by access frequency:            ║
║           1. session:workspace:acme-corp (820 reads/sec)       ║
║           2. session:workspace:globex (340 reads/sec)          ║
║           3. session:workspace:initech (290 reads/sec)         ║
║           These are WORKSPACE SESSION KEYS — shared state      ║
║           for all users in a workspace (presence indicators,   ║
║           typing indicators, active channel list).             ║
║           "acme-corp" has 47,000 active users.                 ║
║                                                                ║
║   12:00 — acme-corp users report:                              ║
║           "Presence indicators are wrong"                      ║
║           "Typing indicators are delayed by 3-5 seconds"       ║
║           "Channel list takes forever to load"                 ║
║           Redis master-2 CPU: 92%                              ║
║           Master-2 p99 latency: 89ms (was 2.3ms)               ║
║                                                                ║
║   12:05 — Team decides to add a 7th master to spread load.     ║
║           Running: redis-cli --cluster reshard                 ║
║           Moving slots 2731-3413 from master-2 to master-7.    ║
║           (Moving ~683 slots — 1/4 of master-2's slots)        ║
║                                                                ║
║   12:10 — DURING the reshard:                                  ║
║           Master-2 CPU spikes to 99%.                          ║
║           Reshard is MIGRATING keys from master-2 to master-7. ║
║           This migration reads ALL keys in each slot and       ║
║           transfers them. On an already-overloaded node,       ║
║           this additional I/O makes things WORSE.              ║
║                                                                ║
║           Users across ALL workspaces on master-2 (not just    ║
║           acme-corp) now experience:                           ║
║           → 5-15 second delays on session operations           ║
║           → Timeouts on presence updates                       ║
║           → Some users logged out (session read timeout →      ║
║             app treats as expired session → forces re-login)   ║
║                                                                ║
║   12:12 — Reshard is 60% complete. master-7 has 410 slots.     ║
║           master-2 still has ~2320 slots and is at 99% CPU.    ║
║           Some slots are in MIGRATING state: reads for keys    ║
║           in those slots get ASK redirects → extra round trip  ║
║           → additional latency.                                ║
║                                                                ║
║   12:15 — master-2's replica detects master-2 as unhealthy     ║
║           (response time > cluster-node-timeout).              ║
║           Replica initiates FAILOVER.                          ║
║           But master-2 is not actually down — it's just slow.  ║
║           Failover completes: replica becomes new master-2.    ║
║                                                                ║
║           PROBLEM: the reshard was in progress.                ║
║           Slots that were in MIGRATING state on old master-2   ║
║           are now in an INCONSISTENT state:                    ║
║           → master-7 has SOME keys from those slots            ║
║           → new master-2 (the replica) has the OLD keys        ║
║             (before migration started — replica was behind)    ║
║           → Some keys exist on BOTH nodes                      ║
║           → Some keys exist on NEITHER node                    ║
║                                                                ║
║   12:17 — User reports escalate:                               ║
║           "I can't see any of my channels"                     ║
║           "The app is logging me out repeatedly"               ║
║           "My messages are disappearing"                       ║
║                                                                ║
║   12:18 — Error rate: 4.7% (was 0.01%).                        ║
║           Cache miss rate: 23% (was 1.8%).                     ║
║           The 23% misses are hitting the auth service          ║
║           (session miss → re-authenticate → rebuild session).  ║
║           Auth service load: 3x normal.                        ║
║           Auth service database connection pool: 87% utilized. ║
║                                                                ║
║   12:20 — You're the on-call SRE. The incident is yours.       ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝

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

> **Answer key (open only after you have answered):**
> [`../answers/Week-03-Distributed-Systems-Theory/Consistent Hashing Answers.md`](../answers/Week-03-Distributed-Systems-Theory/Consistent Hashing Answers.md)
