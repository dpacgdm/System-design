# Week 8, Topic 2 — CRDTs and Conflict Resolution

---

## Learning Objectives
```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Explain WHY conflict resolution exists — connect it       ║
║      to multi-leader replication, network partitions, and      ║
║      the AP side of CAP from Week 3 Topic 1                    ║
║                                                                ║
║   2. Distinguish state-based CRDTs (CvRDT) from                ║
║      operation-based CRDTs (CmRDT) and state when each         ║
║      representation is appropriate in production               ║
║                                                                ║
║   3. Implement merge semantics for the core CRDT types:        ║
║      LWW-Register, G-Counter, PN-Counter, OR-Set, and RGA      ║
║      — including the mathematical properties that make         ║
║      convergence guaranteed                                    ║
║                                                                ║
║   4. Articulate when CRDTs BEAT Last-Writer-Wins (LWW) and     ║
║      when LWW is still the correct engineering choice          ║
║                                                                ║
║   5. Compare Operational Transformation (Google Docs) with     ║
║      CRDTs — convergence model, coordination requirements,     ║
║      and failure modes under partition                         ║
║                                                                ║
║   6. Map CRDT usage to real systems: Redis CRDT module,        ║
║      Riak, Automerge, Yjs, AWS AppSync, DynamoDB LWW           ║
║                                                                ║
║   7. Diagnose CRDT failure modes in production: tombstone      ║
║      accumulation, clock skew, semantic loss, metadata         ║
║      explosion, and "convergent but wrong" merges              ║
║                                                                ║
║   8. Design conflict resolution for a multi-region system      ║
║      given product semantics — not default to "use CRDTs"      ║
║      or "use LWW" without analysis                             ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════╗
║   DESTROY THESE BEFORE GOING FURTHER                           ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   WRONG #1: "CRDTs eliminate conflicts."                       ║
║   ─────────────────────────────────────                        ║
║   Conflicts STILL HAPPEN. Two users edit the same field        ║
║   concurrently. Two nodes increment the same counter           ║
║   offline. The difference: CRDTs guarantee that when           ║
║   replicas eventually exchange state, they CONVERGE to the     ║
║   same value WITHOUT a central coordinator.                    ║
║   The conflict is RESOLVED AUTOMATICALLY — but the             ║
║   resolution may not match what a human wanted.                ║
║                                                                ║
║   WRONG #2: "LWW is just a bad CRDT."                          ║
║   ───────────────────────────────────                          ║
║   LWW-Register IS a CRDT — the simplest one. It merges         ║
║   by timestamp. The problem isn't that LWW "isn't a CRDT."     ║
║   The problem is that LWW's merge SEMANTICS silently           ║
║   discard data. "Last writer wins" means earlier writers       ║
║   LOSE with no audit trail. For a shopping cart quantity,      ║
║   that's catastrophic. For a profile bio update, it may be     ║
║   exactly right.                                               ║
║                                                                ║
║   WRONG #3: "CRDTs require no coordination."                   ║
║   ──────────────────────────────────────────                   ║
║   CRDTs require no coordination for CONVERGENCE. They may      ║
║   still require coordination for MEANING:                      ║
║   → Unique ID generation (still need clocks or UUIDs)          ║
║   → Garbage collection of tombstones (often needs sync)        ║
║   → Size limits (OR-Set metadata grows forever without GC)     ║
║   → User-visible semantics ("did my edit survive?")            ║
║                                                                ║
║   WRONG #4: "Google Docs uses CRDTs."                          ║
║   ─────────────────────────────────────                        ║
║   Google Docs uses Operational Transformation (OT), not        ║
║   CRDTs. OT transforms concurrent operations against each      ║
║   other so all clients reach the same document state.          ║
║   OT typically assumes a central server (or ordered            ║
║   delivery). CRDTs assume eventual message delivery and        ║
║   commutative/associative/idempotent merges. Different         ║
║   tradeoffs. We'll compare them precisely in Section 8.        ║
║                                                                ║
║   WRONG #5: "Eventual consistency = CRDTs."                    ║
║   ─────────────────────────────────────────                    ║
║   From Week 3 Topic 2: eventual consistency is a family        ║
║   of guarantees. CRDTs provide STRONG EVENTUAL CONSISTENCY:    ║
║   all replicas converge, AND convergence is deterministic      ║
║   (same inputs → same output). Plain eventual consistency      ║
║   with ad-hoc merge logic may NEVER converge if two            ║
║   developers write incompatible merge functions.               ║
║                                                                ║
║   WRONG #6: "Just use vector clocks instead."                  ║
║   ───────────────────────────────────────────                  ║
║   Vector clocks DETECT conflicts (they tell you two writes     ║
║   are concurrent). They do NOT RESOLVE them. You still         ║
║   need a merge function. CRDTs ARE merge functions with        ║
║   proven mathematical properties. Vector clocks + LWW is       ║
║   one combination. Vector clocks + OR-Set is another.          ║
║                                                                ║
║   WRONG #7: "CRDTs are only for offline mobile apps."          ║
║   ───────────────────────────────────────────────────          ║
║   Offline-first is the MOTIVATING use case, but CRDTs          ║
║   appear wherever concurrent writes happen without a           ║
║   single leader: multi-region active-active databases,         ║
║   collaborative editors (Yjs, Automerge), distributed          ║
║   counters (PN-Counter for analytics), shopping carts          ║
║   (OR-Set for item sets), and Redis Enterprise CRDT for        ║
║   geo-distributed caches.                                      ║
╚════════════════════════════════════════════════════════════════╝
```

### Where This Fits in the Curriculum

```
╔═════════════════════════════════════════════════════════════════╗
║   PRIOR REFERENCE             │  CRDT CONNECTION                ║
╠═════════════════════════════════════════════════════════════════╣
║  Week 3 T1: CAP Theorem       │ AP systems during partition     ║
║                               │ MUST resolve write conflicts.   ║
║                               │ CRDTs are one resolution path.  ║
╠═════════════════════════════════════════════════════════════════╣
║  Week 3 T2: Consistency       │ CRDTs target strong eventual    ║
║  Models                       │ consistency — stronger than     ║
║                               │ "eventually maybe consistent"   ║
╠═════════════════════════════════════════════════════════════════╣
║  Week 4 T1: Multi-leader      │ Every concurrent write to the   ║
║  Replication                  │ same key is a conflict. LWW,    ║
║                               │ CRDTs, or custom merge — pick   ║
║                               │ one explicitly.                 ║
╠═════════════════════════════════════════════════════════════════╣
║  Week 5 T1: Cassandra         │ Counters are NOT CRDTs in       ║
║                               │ Cassandra — they're eventually  ║
║                               │ consistent with no merge on     ║
║                               │ concurrent updates. Different.  ║
╠═════════════════════════════════════════════════════════════════╣
║  Week 8 T1: Clocks (Lamport,  │ CRDTs depend on causality       ║
║  Vector Clocks)               │ tracking. LWW-Register uses     ║
║                               │ timestamps. OR-Set uses unique  ║
║                               │ tags. RGA uses (id, clock).     ║
╚═════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

### 3.1 — The Problem CRDTs Solve

```
THE SETUP:

  You have a distributed system with MULTIPLE WRITERS.
  No single leader. Or: writers that continue during
  network partition (AP mode from CAP).

  Two clients write to the same data concurrently:

    Client A (us-east-1):  SET cart.quantity = 3
    Client B (eu-west-1):  SET cart.quantity = 5

  Both writes succeed locally. Both replicate asynchronously.
  When the replicas sync — WHAT IS cart.quantity?

  OPTIONS:

  ┌─────────────────────┬────────────────────────────────────┐
  │ STRATEGY            │ RESULT                             │
  ├─────────────────────┼────────────────────────────────────┤
  │ Reject one write    │ Requires coordination (CP).        │
  │ (linearizability)   │ One client gets an error.          │
  ├─────────────────────┼────────────────────────────────────┤
  │ Last-Writer-Wins    │ quantity = 3 OR 5 (by timestamp)   │
  │ (LWW)               │ The other value is LOST.           │
  ├─────────────────────┼────────────────────────────────────┤
  │ Custom merge        │ quantity = ??? (your code decides) │
  │ (application logic) │ May not converge if buggy.         │
  ├─────────────────────┼────────────────────────────────────┤
  │ CRDT merge          │ Deterministic, proven convergence  │
  │                     │ Semantics depend on CRDT type.     │
  └─────────────────────┴────────────────────────────────────┘

CRDTs (Conflict-free Replicated Data Types) are data structures
whose merge operation is:

  1. COMMUTATIVE:   merge(A, B) = merge(B, A)
  2. ASSOCIATIVE:   merge(merge(A, B), C) = merge(A, merge(B, C))
  3. IDEMPOTENT:    merge(A, A) = A

These three properties together guarantee STRONG EVENTUAL
CONSISTENCY: given the same set of updates (delivered in any
order, any number of times), all replicas converge to the same
state.

THE FORMAL DEFINITION (Shapiro et al., 2011):

  A CRDT is a state (or sequence of operations) such that
  all replicas that have received the same updates (possibly
  in different orders) compute the same state after merge.

  "Conflict-free" does NOT mean "conflict-free for the user."
  It means "conflict-free for the SYSTEM" — the merge always
  produces a result without manual intervention.
```

### 3.2 — State-Based vs Operation-Based CRDTs

```
╔═══════════════════════════════════════════════════════════════════╗
║   TWO REPRESENTATIONS OF THE SAME IDEA                            ║
╟───────────────────────────────────────────────────────────────────╢
║                                                                   ║
║   STATE-BASED CRDTs (CvRDT — Convergent Replicated Data Types)    ║
║   ─────────────────────────────────────────────────────────       ║
║   Replicas exchange their FULL STATE (or state deltas).           ║
║   Merge happens on the state directly.                            ║
║                                                                   ║
║   Update locally → propagate state → remote merge(state)          ║
║                                                                   ║
║   Example: G-Counter                                              ║
║     State = map of {node_id → local_count}                        ║
║     Merge = pointwise MAX of each node's count                    ║
║                                                                   ║
║   Pros:                                                           ║
║     → Simple reasoning: "here's my state, merge it"               ║
║     → Idempotent by design (re-sending state is safe)             ║
║     → Works well over unreliable transports (SQS, gossip)         ║
║                                                                   ║
║   Cons:                                                           ║
║     → State can be LARGE (entire counter map, entire set)         ║
║     → Bandwidth grows with number of replicas/nodes               ║
║                                                                   ║
║   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━         ║
║                                                                   ║
║   OPERATION-BASED CRDTs (CmRDT — Commutativ Replicated Data Types)║
║   ─────────────────────────────────────────────────────────       ║
║   Replicas exchange OPERATIONS (small deltas).                    ║
║   Assumes RELIABLE DELIVERY and CAUSAL ORDERING of ops.           ║
║                                                                   ║
║   Update locally → propagate op → remote apply(op)                ║
║                                                                   ║
║   Example: G-Counter as CmRDT                                     ║
║     Operation = increment(node_id, delta)                         ║
║     Apply = add delta to that node's slot                         ║
║     (No merge needed if all ops eventually delivered)             ║
║                                                                   ║
║   Pros:                                                           ║
║     → Small messages (one increment, one add-to-set)              ║
║     → Efficient for high-churn data                               ║
║                                                                   ║
║   Cons:                                                           ║
║     → Requires causal delivery (or deduplication)                 ║
║     → Duplicate delivery must be handled (idempotent ops)         ║
║     → Harder to implement correctly                               ║
║                                                                   ║
║   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━         ║
║                                                                   ║
║   EQUIVALENCE: Every CmRDT has an equivalent CvRDT and            ║
║   vice versa. The choice is an ENGINEERING tradeoff, not          ║
║   a capability difference.                                        ║
╚═══════════════════════════════════════════════════════════════════╝

VISUAL — STATE-BASED MERGE:

  Node A state:  {n1: 5, n2: 0, n3: 0}   (A incremented n1 five times)
  Node B state:  {n1: 0, n2: 3, n3: 0}   (B incremented n2 three times)

  A and B exchange full state maps:

    merge(A, B) = {n1: max(5,0), n2: max(0,3), n3: max(0,0)}
                = {n1: 5, n2: 3, n3: 0}

  Total count = 5 + 3 + 0 = 8  ✓ (both increments preserved)

VISUAL — OPERATION-BASED:

  Node A sends:  inc(n1, 1), inc(n1, 1), inc(n1, 1), inc(n1, 1), inc(n1, 1)
  Node B sends:  inc(n2, 1), inc(n2, 1), inc(n2, 1)

  Node C receives all ops (in any order, deduplicated):
    apply each → {n1: 5, n2: 3}
    Total = 8  ✓

WHEN TO USE WHICH:

  ┌──────────────────────────────────┬─────────────────────────┐
  │ SITUATION                        │ PREFER                  │
  ├──────────────────────────────────┼─────────────────────────┤
  │ Gossip protocol, unreliable net  │ State-based (CvRDT)     │
  │ Infrequent sync (mobile offline) │ State-based             │
  │ High-frequency updates           │ Operation-based (CmRDT) │
  │ Ordered log (Kafka) available    │ Operation-based         │
  │ Small state, few replicas        │ Either                  │
  │ Large document, many edits/sec   │ Op-based (Automerge)    │
  └──────────────────────────────────┴─────────────────────────┘
```

### 3.3 — The Lattice Foundation (Why Merge Works)

```
CRDTs form a JOIN-SEMILATTICE:

  Every state has a "partial order" — we can say state S1
  is "dominated by" state S2 if S2 contains all information
  in S1 (S1 ≤ S2).

  Merge = the LEAST UPPER BOUND (join) of two states.

  For G-Counter:
    {n1: 3} ≤ {n1: 5, n2: 2}   (3 ≤ 5 for n1, and n2 is new)
    merge({n1:3}, {n1:5, n2:2}) = {n1:5, n2:2}

  The semilattice property guarantees:
    → Merge always produces a unique result
    → Repeated merges don't change the result (idempotent)
    → Order of merges doesn't matter (commutative + associative)

  THIS IS WHY "just write a merge function" is dangerous:
  If your merge doesn't form a semilattice, replicas DIVERGE.

  Example of a BAD merge (NOT a CRDT):

    merge inventory:
      A says stock = 10
      B says stock = 8
      merge = average(10, 8) = 9

    Node C merges A then B: average(average(10,8), 8) if B arrives twice?
    Node D merges B then A: different path → different result.
    NOT associative. NOT a CRDT. WILL DIVERGE.
```

---

### 3.4 — LWW-Register (Last-Writer-Wins Register)

```
DEFINITION:
  A register (single value) where concurrent writes are resolved
  by picking the write with the highest timestamp.

  State: (value, timestamp, writer_id)
  Merge: pick the tuple with the greatest timestamp.
         Tie-break by writer_id (deterministic).

UPDATE:
  write(value):
    ts = now()  // or HLC, or Lamport clock
    state = (value, ts, my_node_id)

MERGE:
  merge(local, remote):
    if remote.ts > local.ts: return remote
    if remote.ts < local.ts: return local
    if remote.ts == local.ts: return max(remote.writer_id, local.writer_id)

EXAMPLE — CONCURRENT WRITES:

  T=100, Node A: write("Alice")
  T=105, Node B: write("Bob")     ← B wins (later timestamp)

  After merge everywhere: "Bob"

  T=100, Node A: write("Alice")
  T=100, Node B: write("Bob")     ← CLOCK SKEW: same timestamp!

  Tie-break by writer_id:
    Node A id = "aaa", Node B id = "bbb"
    "Bob" wins (bbb > aaa lexicographically)

  Deterministic. All nodes agree. ✓

WHY LWW IS A CRDT:
  Merge is commutative (max is commutative).
  Merge is associative (max of maxes = max).
  Merge is idempotent (max(s, s) = s).

WHY LWW IS DANGEROUS:

  T=100, Node A: write(cart_qty = 3)
  T=105, Node B: write(cart_qty = 5)

  Result: cart_qty = 5. Node A's write is SILENTLY DISCARDED.
  User A thought they set quantity to 3. They were wrong.

  LWW IS CORRECT WHEN:
    → The field is truly "single authoritative value"
    → Losing an intermediate write is acceptable
    → Examples: user bio, profile picture URL, feature flag

  LWW IS WRONG WHEN:
    → Both writes represent ACCUMULATED intent (counters, sets)
    → Both writes must be preserved (collaborative editing)
    → Clock skew can cause "future" writes to win incorrectly
```

#### LWW-Register: Clock Skew Failure

```
SCENARIO:

  Node A clock is 5 minutes AHEAD of Node B.

  Real time 10:00 — User on Node B writes bio = "Engineer"
  Real time 10:01 — User on Node A writes bio = "Senior Engineer"

  Node A timestamp: 10:06 (skewed)
  Node B timestamp: 10:00 (correct)

  LWW merge: "Engineer" wins — the OLDER edit wins because
  Node A's clock made the "Senior Engineer" write look EARLIER.

  THE USER'S MOST RECENT INTENT WAS LOST.

  MITIGATIONS:
    → Hybrid Logical Clocks (HLC) — bounded skew
    → TrueTime (Spanner) — globally synchronized clocks
    → Don't use wall-clock LWW for user-visible semantics
    → Use logical timestamps (Lamport) for ordering only
    → Prefer CRDTs that don't depend on physical time
```

---

### 3.5 — G-Counter (Grow-Only Counter)

```
DEFINITION:
  A counter that can ONLY be incremented, never decremented.
  Each node has its own slot. Total = sum of all slots.

  State: map {node_id → count}
  Default: all counts start at 0.

UPDATE (increment):
  increment(delta):
    state[my_node_id] += delta

MERGE:
  merge(local, remote):
    for each node_id in (local.keys ∪ remote.keys):
      result[node_id] = max(local[node_id], remote[node_id])
    return result

READ:
  value() = sum(result.values())

WHY MAX WORKS:
  Each node ONLY increments its own slot. No node ever decreases
  any slot. So the count for node_id can only go UP. When two
  replicas merge, they each take the highest count they've seen
  for each node — preserving all increments from both sides.

EXAMPLE:

  3-node G-Counter: nodes A, B, C

  Initial: {A:0, B:0, C:0}

  Node A: increment(5)  →  {A:5, B:0, C:0}   total = 5
  Node B: increment(3)  →  {A:0, B:3, C:0}   total = 3
  (concurrent, no sync yet)

  Merge A and B:
    {A: max(5,0), B: max(0,3), C: max(0,0)}
    = {A:5, B:3, C:0}
    total = 8  ✓

  Both increments preserved. No coordination needed.

STATE SIZE:
  O(number of nodes). With 100 nodes, state has 100 entries.
  For a global counter with millions of clients, this does NOT
  scale — use PN-Counter with client sharding, or a different
  architecture (central counter with async aggregation).

WHEN TO USE:
  → Page view counts (only increment)
  → Download counters
  → "Like" counts where unlikes are rare or handled separately
  → Metrics aggregation across edge nodes
```

---

### 3.6 — PN-Counter (Positive-Negative Counter)

```
DEFINITION:
  A counter that supports BOTH increment AND decrement.
  Implemented as TWO G-Counters: P (increments) and N (decrements).

  State: (P: map {node → inc_count}, N: map {node → dec_count})
  Value: sum(P) - sum(N)

UPDATE:
  increment(delta):
    P[my_node_id] += delta

  decrement(delta):
    N[my_node_id] += delta

MERGE:
  merge(local, remote):
    P' = merge_gcounter(local.P, remote.P)   // max per node
    N' = merge_gcounter(local.N, remote.N)
    return (P', N')

EXAMPLE:

  Node A: increment(10)  →  P={A:10}, N={A:0}   value = 10
  Node B: decrement(3)   →  P={B:0},  N={B:3}   value = -3

  Merge:
    P = {A:10, B:0}, N = {A:0, B:3}
    value = 10 - 3 = 7  ✓

CONCURRENT INCREMENT AND DECREMENT:

  Node A: increment(5)   →  P={A:5}, N={A:0}
  Node B: decrement(5)   →  P={B:0}, N={B:5}

  Merge: value = 5 - 5 = 0  ✓

  Both operations preserved. Neither "wins" — both apply.

LIMITATIONS:

  1. Cannot go below zero with GUARANTEE if you need
     "inventory cannot be negative" — PN-Counter converges
     to the arithmetic result, which may be negative.

  2. State size: 2 × O(nodes). Grows with replica count.

  3. NOT suitable for "exactly-once decrement" semantics
     (e.g., "decrement only if stock > 0") — that requires
     coordination (compare-and-set, linearizability).

WHEN TO USE:
  → Shopping cart item count (increment add, decrement remove)
  → Seat reservation tallies (with separate overbooking logic)
  → Distributed scoreboards
  → Analytics: +1 view, -1 bot-filtered view
```

---

### 3.7 — OR-Set (Observed-Remove Set)

```
DEFINITION:
  A set that supports add and remove with correct merge.
  The "Observed-Remove" semantics solve the classic problem:
  "If I remove an element while you add it concurrently,
  what happens?"

  Each element has a UNIQUE TAG (uuid) for each add operation.

  State:
    elements: map {element → set of tags}
    (element "apple" might have tags {t1, t3} if added twice)

ADD(element):
  tag = generate_unique_uuid()
  elements[element].add(tag)
  broadcast add(element, tag)

REMOVE(element):
  tags = elements[element]   // observe current tags
  remove element from local set
  broadcast remove(element, tags)   // remove ALL observed tags

MERGE:
  merge(local, remote):
    for each element in (local.keys ∪ remote.keys):
      result[element] = local[element] ∪ remote[element]  // set union of tags
    // Remove elements with empty tag sets
    return result

READ:
  members = {e for e, tags in result.items() if tags != ∅}

THE CLASSIC ADD-REMOVE RACE:

  Initial: {}

  Node A: add("apple")     →  apple: {tag-A1}
  Node B: remove("apple")  →  (observed nothing) → broadcast remove(apple, {})

  Merge:
    apple tags = {tag-A1} ∪ {} = {tag-A1}
    apple is IN the set.  ✓

  A's add wins because B's remove observed ZERO tags for apple.
  B didn't know about A's concurrent add.

  REVERSE:

  Initial: apple: {tag-0}

  Node A: remove("apple")  →  observes {tag-0}, removes, broadcast remove(apple, {tag-0})
  Node B: add("apple")     →  apple: {tag-B1}

  Merge:
    apple tags = {} ∪ {tag-B1} = {tag-B1}
    apple is IN the set.  ✓

  B's add wins. Correct — concurrent add should not be lost
  to a remove that happened before the add was observed.

WHEN REMOVE SHOULD WIN:

  If A removes AFTER seeing B's add (causally), the remove
  includes tag-B1 in its observed set:

  Node B: add("apple")     →  apple: {tag-B1}
  (sync)
  Node A: remove("apple")  →  observes {tag-B1}, broadcast remove(apple, {tag-B1})

  Merge with any future add:
    If no new add: apple tags = {} → apple REMOVED ✓

METADATA EXPLOSION:

  Each add creates a tag. Tags are NEVER removed from merged
  state (they're in the remove broadcast but union keeps
  new tags). After many add/remove cycles:

    apple: {t1, t2, t3, t4, t5, ... t10000}

  Element is "removed" (empty active set) but metadata grows.
  Production systems need GARBAGE COLLECTION of tombstoned tags.

WHEN TO USE:
  → Shopping cart product IDs (add item, remove item)
  → Bookmark lists
  → Tag collections
  → Any set where concurrent add/remove must converge
```

---

### 3.8 — RGA (Replicated Growable Array)

```
DEFINITION:
  A CRDT for ordered sequences — text documents, todo lists,
  collaborative arrays. Each element has a unique ID and
  a position identifier.

  Element: (id, value, timestamp_or_clock)

  Position is determined by (prev_id, id) — each element
  points to its predecessor in the list.

INSERT:
  insert_after(prev_id, value):
    my_id = (my_node_id, my_counter++)   // unique, ordered
    create element (my_id, value)
    broadcast insert

DELETE:
  delete(id):
    tombstone id (don't remove from structure — mark deleted)
    broadcast delete(id)

MERGE:
  1. Union all elements from both replicas
  2. Apply tombstones (deleted ids are hidden)
  3. Sort by id (which embeds causal order via clock)
  4. Reconstruct list

EXAMPLE — CONCURRENT INSERT:

  Initial list: [A, B, C]
  Element ids: (A,1), (B,1), (C,1)

  Node 1: insert X after A  →  id = (N1, 1)
  Node 2: insert Y after A  →  id = (N2, 1)  (concurrent)

  Both inserts have same predecessor (A).

  Sort by id:
    (N1, 1) vs (N2, 1) — lexicographic on node id
    If N1 < N2: order is [A, X, Y, B, C]
    All nodes agree. ✓

  THIS IS THE CRDT APPROACH TO COLLABORATIVE TEXT.
  Yjs and Automerge use more sophisticated variants (YATA, etc.)
  but the principle is the same: unique IDs + deterministic
  ordering + tombstones.

RGA vs OT:

  RGA (CRDT):
    → No central server required
    → Tombstones accumulate (deleted chars still in state)
    → Deterministic merge everywhere

  OT (Google Docs):
    → Central server orders operations
    → Transforms ops against each other
    → No tombstone accumulation in the same way
    → Requires connectivity to server for ordering

LIMITATIONS:

  1. Tombstone accumulation — deleted elements stay in state
  2. Memory grows with edit history
  3. "Intended" order may not match user intent for concurrent
     inserts at same position (both appear — order is arbitrary
     but deterministic)
```

---

### 3.9 — Merge Semantics Summary

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║   CRDT TYPE      │  MERGE OPERATION           │  WHAT CONCURRENT WRITES DO       ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  LWW-Register    │  max(timestamp, tie-break) │  Later write wins. Other lost.   ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  G-Counter       │  max per node slot         │  All increments preserved.       ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  PN-Counter      │  max on P and N separately │  All incs and decs preserved.    ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  OR-Set          │  union of element tags     │  Adds and removes compose.       ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  RGA             │  union + tombstone filter  │  All inserts appear; order by id.║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  LWW-Map         │  merge per key recursively │  Key-level LWW. Lost keys.       ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  OR-Map          │  merge per key with OR-Set │  Key add/remove composes.        ║
╚══════════════════════════════════════════════════════════════════════════════════╝

COMPOSING CRDTs:

  Real systems compose CRDTs into structures:

    Shopping Cart CRDT:
      items: OR-Set(product_id)
      quantities: OR-Map(product_id → PN-Counter)

    User Session CRDT:
      profile: LWW-Register(name, bio)
      preferences: LWW-Map(key → LWW-Register)
      cart: (OR-Set + PN-Counter as above)

  Each field picks the CRDT type matching its SEMANTICS.
  This is the key design skill — not "use CRDT" but
  "which CRDT per field."
```

---

## Concrete Examples

### 4.1 — DynamoDB: LWW at Scale (Not Full CRDTs)

```
DynamoDB multi-region active-active (global tables) uses
LAST-WRITER-WINS per attribute, NOT composable CRDTs.

HOW IT WORKS:

  Each write carries a timestamp (from the writer's region).
  On conflict (concurrent writes to same item):
    → Highest timestamp wins per attribute
    → Tie-break: region priority (configured table order)

EXAMPLE — GLOBAL TABLE CONFLICT:

  Item: {user_id: "alice", cart_count: ???}

  us-east-1 at T1: UPDATE cart_count = 3
  eu-west-1 at T2: UPDATE cart_count = 5   (T2 > T1)

  After replication settles: cart_count = 5 everywhere.

  The "3" is gone. Same as LWW-Register.

AWS CONFIGURATION:

  # Enable global tables (CloudFormation excerpt)
  GlobalTable:
    Type: AWS::DynamoDB::GlobalTable
    Properties:
      Replicas:
        - Region: us-east-1
        - Region: eu-west-1
      StreamSpecification:
        StreamViewType: NEW_AND_OLD_IMAGES

  Conflict resolution: Last Writer Wins (default, not configurable
  to OR-Set or PN-Counter).

WHEN THIS IS FINE:
  → Profile fields (name, avatar URL)
  → Configuration flags
  → "Latest status" fields

WHEN THIS BREAKS:
  → Counters (use DynamoDB atomic counters on SINGLE region,
    or DAX, or application-level PN-Counter stored as JSON)
  → Sets (cart product IDs — use a SET type with application
    merge, or separate line items with idempotency keys)
  → Append-only logs (use conditional writes or a queue)

LESSON: DynamoDB gives you LWW for free. That's ONE CRDT type.
If your data needs OR-Set or PN-Counter semantics, YOU build it
on top — or choose a different store.
```

### 4.2 — Riak Data Types (Reference CRDT Implementation)

```
Riak 2.0+ shipped built-in CRDTs via "Riak Data Types":

  ┌───────────┬───────────────────┬──────────────────────┐
  │ Riak Type │ CRDT Equivalent   │ Operations           │
  ├───────────┼───────────────────┼──────────────────────┤
  │ counter   │ PN-Counter        │ increment, decrement │
  │ set       │ OR-Set            │ add, remove          │
  │ map       │ OR-Map            │ nested CRDTs         │
  │ register  │ LWW-Register      │ set                  │
  │ flag      │ Enable-wins /     │ enable, disable      │
  │           │ Disable-wins flag │                      │
  └───────────┴───────────────────┴──────────────────────┘

EXAMPLE — RIAK COUNTER (PN-Counter):

  # Using riak-python-client
  bucket = client.bucket_type('counters').bucket('page_views')
  counter = bucket.new('homepage')
  counter.increment(1)
  counter.store()

  # Another datacenter concurrently:
  counter.increment(5)
  counter.store()

  # After sync: value = 6 (both preserved)

EXAMPLE — RIAK OR-Set:

  bucket = client.bucket_type('sets').bucket('cart')
  cart = bucket.new('user_123')
  cart.add('product_456')
  cart.add('product_789')
  cart.store()

  # Concurrent remove elsewhere:
  cart.remove('product_456')  # removes only observed tags

  # Merge preserves correct semantics

WHY RIAK MATTERS FOR INTERVIEWS:
  Riak is the canonical "CRDTs in production" case study from
  the academic papers (Shapiro, Preguiça). Even if Riak usage
  has declined, the DATA TYPES are the reference implementation
  engineers copied into Redis CRDT, Akka Distributed Data, etc.
```

### 4.3 — Redis Enterprise CRDT (Active-Active)

```
Redis Enterprise Active-Active Geo-Distribution uses CRDTs
under the hood for conflict-free replication across regions.

ARCHITECTURE:

  us-east-1 Redis  ←── CRDT sync ──→  eu-west-1 Redis
       │                                      │
   App writes                             App writes
   locally                                locally

  Both regions accept writes. CRDT merge on replication.

SUPPORTED CRDT TYPES (Redis Enterprise 7.x):

  → String (LWW-Register semantics for plain SET)
  → Counter (PN-Counter)
  → Set (OR-Set)
  → Hash (CRDT hash — field-level merge)
  → JSON (partial — nested CRDT support in RedisJSON)

EXAMPLE — ACTIVE-ACTIVE COUNTER:

  # Region us-east-1
  INCRBY pageviews:homepage 1

  # Region eu-west-1 (concurrent)
  INCRBY pageviews:homepage 5

  # After CRDT sync: value = 6

EXAMPLE — ACTIVE-ACTIVE SET (OR-Set):

  # us-east-1
  SADD cart:user123 "sku-111"

  # eu-west-1 (concurrent)
  SADD cart:user123 "sku-222"
  SREM cart:user123 "sku-111"

  # OR-Set merge: result depends on observed-remove semantics
  # If remove didn't observe sku-111's tag from east: sku-111 stays
  # sku-222 also present

AWS DEPLOYMENT PATTERN:

  Redis Enterprise Cloud on AWS:
    → VPC peering between us-east-1 and eu-west-1
    → Active-Active CRDB (Conflict-free Replicated Database)
    → Sub-ms local reads/writes per region
    → CRDT sync over private link (~ms latency)

  NOT the same as open-source Redis Cluster:
    Open-source Redis replication is PRIMARY-REPLICA.
    Concurrent writes to two primaries = split brain.
    You NEED Redis Enterprise CRDT or application-level CRDTs.

COST TRADEOFF:

  Active-Active CRDB: ~2x single-region Enterprise pricing
  + cross-region data transfer
  Benefit: local write latency in each region, no failover
  write redirection during regional outage
```

### 4.4 — Automerge and Yjs (Collaborative CRDTs)

```
MODERN COLLABORATIVE EDITORS use CRDTs, not OT:

  ┌─────────────────────────────────────────────────────────────┐
  │  Library     │  CRDT Type           │  Used By              │
  ├─────────────────────────────────────────────────────────────┤
  │  Automerge   │  Multi-Value Register,│  Local-first apps,   │
  │              │  List (RGA-like), Map │  Ink & Switch, etc.  │
  ├─────────────────────────────────────────────────────────────┤
  │  Yjs         │  YATA (list CRDT)     │  Tiptap, Liveblocks, │
  │              │                       │  Notion-like editors │
  ├─────────────────────────────────────────────────────────────┤
  │  Diamond     │  List + Text          │  Obsidian Sync       │
  └─────────────────────────────────────────────────────────────┘

AUTOMERGE EXAMPLE (JavaScript):

  import * as Automerge from '@automerge/automerge'

  let doc1 = Automerge.init()
  doc1 = Automerge.change(doc1, d => { d.text = 'Hello' })

  let doc2 = Automerge.init()
  doc2 = Automerge.change(doc2, d => { d.text = 'World' })

  // Concurrent edits to same field — Multi-Value Register
  // keeps BOTH values until explicitly resolved

  const merged = Automerge.merge(doc1, doc2)
  // merged.text contains both "Hello" and "World"
  // (semantics depend on schema — may need manual pick)

YJS EXAMPLE:

  import * as Y from 'yjs'

  const ydoc = new Y.Doc()
  const ytext = ydoc.getText('shared')

  ytext.insert(0, 'Hello')
  // Concurrent insert at position 0 on another client
  // Yjs CRDT determines deterministic order

  // Sync via WebSocket provider:
  // y-websocket, y-webrtc (peer-to-peer CRDT sync)

WHY THESE MATTER:

  → Prove CRDTs work at human typing speed (60+ WPM)
  → Handle offline editing (merge on reconnect)
  → No central server REQUIRED (WebRTC peer sync)
  → State-based sync: send full doc or binary delta

PERFORMANCE:

  Automerge 2.x: binary encoding, ~10x smaller than JSON
  Yjs: extremely optimized — handles 100+ concurrent editors
  Both: garbage collection APIs for tombstone cleanup
```

### 4.5 — AWS AppSync with Delta Sync (Managed CRDT-ish)

```
AWS AppSync (GraphQL) supports optimistic concurrency and
conflict detection via _version and conditional writes.

PATTERN FOR MOBILE OFFLINE:

  1. Client reads data with _version field
  2. Client edits locally while offline
  3. On reconnect, mutation includes expected _version
  4. If _version mismatch → conflict handler Lambda fires

CONFLICT HANDLER (Lambda):

  export const handler = async (event) => {
    const { newImage, oldImage, context } = event;
    // context: { identity, source, args, ... }

    // Strategy 1: LWW
    if (newImage.updatedAt > oldImage.updatedAt) {
      return newImage;
    }
    return oldImage;

    // Strategy 2: Merge cart items (OR-Set logic)
    // Strategy 3: Reject and return conflict to client
  };

DynamoDB + AppSync is LWW by default. Custom conflict
handlers implement YOUR merge semantics — they are NOT
automatic CRDTs unless YOU write CRDT merge logic in Lambda.

RECOMMENDED PATTERN FOR SETS:

  Store cart as:
    PK: user_id
    SK: CART#product_id
    (one row per product — no set merge needed)

  Add = PUT item. Remove = DELETE item.
  Concurrent add/remove on DIFFERENT products: no conflict.
  Concurrent on SAME product: LWW on quantity field — STILL
  risky. Use conditional update: quantity = quantity + :delta
  with idempotency key per add-to-cart action.
```

### 4.6 — Akka Distributed Data (JVM CRDTs)

```
For JVM microservices (common in enterprise):

  akka-cluster-sharding + Distributed Data (DdData)

  Built-in CRDTs:
    → GCounter, PNCounter
    → ORSet, ORMap, ORMultiMap
    → LWWRegister, LWWMap
    → Flag (Enable-wins / Disable-wins)

EXAMPLE — CLUSTER-WIDE COUNTER:

  // Scala
  val counter = distributedData.replicator.get(
    PNCounterKey("page-views")
  )
  replicator ! Update(PNCounterKey("page-views"), PNCounter.Increment)

  // Replicates via gossip to all nodes
  // Merge automatic on read

USE CASE:
  → In-memory CRDTs for session state across Akka cluster
  → Not durable — pair with event sourcing for persistence
  → Good for: real-time dashboards, game state, chat presence
```

---

### Staff

## Production Patterns

### 5.1 — Pattern: CRDT-Per-Field Schema Design

```
THE MOST COMMON PRODUCTION MISTAKE:

  "We use CRDTs" — but the entire document is one LWW-Register.

CORRECT PATTERN — SEMANTIC FIELD DECOMPOSITION:

  Document: ShoppingCart
  ┌─────────────────────────────────────────────────────────────┐
  │  Field              │  CRDT Type     │  Why                 │
  ├─────────────────────────────────────────────────────────────┤
  │  line_items (keys)  │  OR-Set        │  add/remove products │
  │  qty per item       │  PN-Counter    │  inc/dec quantity    │
  │  coupon_code        │  LWW-Register  │  one code wins       │
  │  shipping_address   │  LWW-Register  │  latest address      │
  │  notes              │  RGA / Text    │  collaborative notes │
  └─────────────────────────────────────────────────────────────┘

  Each field merged independently. A concurrent coupon update
  doesn't destroy a concurrent quantity increment.

IMPLEMENTATION OPTIONS:

  A) Store as JSON blob with CRDT merge in application layer
  B) Use Riak OR-Map / Redis CRDT Hash with nested types
  C) Normalize: one DB row per CRDT cell (DynamoDB pattern)
  D) Event sourcing: ops log per CRDT, materialize on read
```

### 5.2 — Pattern: Idempotency Keys + CRDTs (Defense in Depth)

```
CRDTs handle REPLICA convergence. They do NOT handle
DUPLICATE CLIENT REQUESTS.

  User double-clicks "Add to Cart"
  → Two identical add operations
  → OR-Set: two tags for same product → product appears once ✓
  → PN-Counter: two increments → quantity += 2 ✗ (maybe wrong)

PATTERN:

  Client sends: {op: "add", product_id: "sku-123", idempotency_key: "uuid-abc"}

  Server:
    1. Check idempotency store (Redis/DynamoDB TTL 24h)
    2. If key seen → return cached result, do NOT re-apply
    3. If new → apply CRDT op, store result under key

  CRDT convergence + idempotency = correct under:
    → Network retries
    → Duplicate delivery
    → Client double-submit
```

### 5.3 — Pattern: Hybrid Leader + CRDT Edge

```
Many production systems DON'T go full active-active:

  ┌──────────────┐     async CRDT      ┌──────────────┐
  │  Region A    │ ◄──────────────────► │  Region B    │
  │  (leader for │                     │  (leader for │
  │   writes X)  │                     │   writes Y)  │
  └──────────────┘                     └──────────────┘

  OR:

  ┌──────────────┐                     ┌──────────────┐
  │  Edge PoP    │  CRDT local writes  │  Central     │
  │  (offline    │ ──── sync ────────► │  PostgreSQL  │
  │   cache)     │                     │  (source of  │
  └──────────────┘                     │   truth)     │
                                       └──────────────┘

  Edge accepts writes as CRDT ops during partition.
  On heal: merge into central store OR replay ops log.

  WHEN TO USE:
    → Retail POS offline mode
    → Field service apps (technician offline)
    → CDN edge configuration with central audit
```

### 5.4 — Pattern: Conflict Visibility (Don't Hide Merges)

```
SILENT MERGE IS A UX BUG:

  User A sets quantity to 3.
  User B sets quantity to 5.
  LWW: shows 5. User A's edit vanished without notice.

PRODUCTION PATTERN — CONFLICT NOTIFICATION:

  After merge, if concurrent writes detected (vector clock
  incomparable, or multi-value register has >1 value):

    UI: "Your change conflicted with another edit. Current
         value: 5. Your value was: 3. [Keep yours] [Keep theirs]"

  Automerge Multi-Value Register supports this natively.
  Custom systems: store conflict metadata alongside CRDT state.

  HEALTHCARE / FINANCE:
    Never silent LWW. Always surface conflicts for human review.
```

### 5.5 — Pattern: Tombstone Garbage Collection

```
OR-Set, RGA, and deletion-heavy CRDTs accumulate metadata.

GC STRATEGIES:

  1. STABLE-STATE GC:
     When all replicas confirm they've seen remove(tag-X),
     permanently delete tag-X from state.
     Requires: sync barrier or epoch-based protocol.

  2. EPOCH ROTATION:
     Partition time into epochs (weekly). CRDT state from
     epoch N is compacted after all nodes ack epoch N+1 started.
     Riak uses dotted version vectors for this.

  3. SIZE-BASED COMPACTION:
     When tombstone ratio > 50%, trigger full-state compact
     merge across replicas (maintenance window).

  4. RESET:
     For ephemeral data (presence, session flags): periodic
     full reset acceptable. Not for cart data.

WITHOUT GC:
  OR-Set for high-churn cart: 10K add/remove/day/user × 365 days
  = millions of tags per element → OOM on mobile client sync.
```

### 5.6 — Pattern: CRDT Sync Transport

```
HOW REPLICAS EXCHANGE CRDT STATE:

  ┌──────────────────┬──────────────────┬──────────────────┐
  │ Transport        │ CvRDT vs CmRDT   │ Notes            │
  ├──────────────────┼──────────────────┼──────────────────┤
  │ Gossip (SWIM)    │ CvRDT preferred  │ Anti-entropy     │
  │ Kafka topic      │ CmRDT ops log    │ Ordered per key  │
  │ WebSocket push   │ Either           │ Real-time collab │
  │ S3 snapshot      │ CvRDT full state │ Mobile offline   │
  │ DynamoDB Streams │ Application ops  │ Not native CRDT  │
  └──────────────────┴──────────────────┴──────────────────┘

DELTA-STATE CRDTs (optimization):

  Instead of sending full state, send ONLY the diff since
  last sync (using version vectors to track what remote has).

  If remote has version vector V_remote and local is V_local:
    delta = {entries where tag > V_remote}
    send delta only

  Reduces bandwidth 100-1000x for large OR-Sets.
```

---

## Failure Modes

```
╔══════════════════════════════════════════════════════════════════╗
║   FAILURE MODE #1: CONVERGENT BUT SEMANTICALLY WRONG             ║
║                                                                  ║
║   System: E-commerce, active-active DynamoDB global table        ║
║   Field: inventory_count (stored as plain integer, LWW)          ║
║                                                                  ║
║   us-east-1: decrement inventory by 1 (sale) → count = 9         ║
║   eu-west-1: decrement inventory by 1 (sale) → count = 9         ║
║   (both started from 10, concurrent)                             ║
║                                                                  ║
║   LWW merge: count = 9 (one decrement LOST)                      ║
║   System CONVERGED. All regions agree on 9.                      ║
║   Reality: 2 items sold, count should be 8.                      ║
║   Oversell risk on next purchase.                                ║
║                                                                  ║
║   Root cause: LWW on a counter field. Should be PN-Counter       ║
║   or single-leader atomic decrement.                             ║
║                                                                  ║
║   Fix: inventory decrements through regional leader OR           ║
║   use PN-Counter CRDT OR conditional write with retry.           ║
╠══════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #2: TOMBSTONE EXPLOSION (OR-Set)                  ║
║                                                                  ║
║   System: Mobile app, OR-Set cart synced to phone                ║
║   User adds/removes items obsessively (comparison shopping)      ║
║                                                                  ║
║   After 6 months: cart OR-Set has 50,000 tags for 3 items.       ║
║   Initial sync on new phone: 12 MB CRDT state.                   ║
║   App OOM on low-end Android. Crash loop on login.               ║
║                                                                  ║
║   Root cause: No garbage collection of removed element tags.     ║
║                                                                  ║
║   Fix: Epoch-based compaction. Or: don't use OR-Set on           ║
║   client — use normalized line-item rows, CRDT only on server.   ║
╠══════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #3: CLOCK SKEW LWW REVERSAL                       ║
║                                                                  ║
║   System: Multi-region user profiles, LWW-Register               ║
║   Node in ap-southeast-1 has NTP drift +8 minutes                ║
║                                                                  ║
║   User updates bio at real T=10:00 from Singapore.               ║
║   Timestamp recorded: 10:08.                                     ║
║   User updates bio at real T=10:05 from us-east-1.               ║
║   Timestamp recorded: 10:05.                                     ║
║                                                                  ║
║   LWW: Singapore's EARLIER edit wins (10:08 > 10:05).            ║
║   User's newer US edit silently discarded.                       ║
║                                                                  ║
║   Root cause: Wall-clock LWW without bounded clock sync.         ║
║                                                                  ║
║   Fix: Hybrid Logical Clocks. Or client-supplied logical         ║
║   timestamps. Or CRDT that doesn't use wall clock.               ║
╠══════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #4: FALSE CONVERGENCE ON CUSTOM MERGE             ║
║                                                                  ║
║   System: Custom "smart merge" for JSON documents                ║
║   Developer writes: merge arrays by concatenating and            ║
║   deduplicating.                                                 ║
║                                                                  ║
║   Node A: array = [1, 2, 3]                                      ║
║   Node B: array = [2, 3, 4]                                      ║
║   merge = [1, 2, 3, 4]  (dedupe)                                 ║
║                                                                  ║
║   Node C had [1, 2, 3], merges B → [1, 2, 3, 4]                  ║
║   Node D had [2, 3, 4], merges A → [1, 2, 3, 4]                  ║
║   Looks converged...                                             ║
║                                                                  ║
║   But: Node E had [1, 2], merges C then D:                       ║
║   merge(merge([1,2], [1,2,3,4]), [1,2,3,4])                      ║
║   If merge is not associative → DIVERGENCE.                      ║
║                                                                  ║
║   Root cause: Ad-hoc merge without semilattice proof.            ║
║   Fix: Use proven CRDT (OR-Set for set semantics) or             ║
║   formalize and TEST merge associativity.                        ║
╠══════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #5: RGA TOMBSTONE MEMORY LEAK                     ║
║                                                                  ║
║   System: Collaborative doc editor (RGA-based)                   ║
║   500-page legal document, 2 years of edits                      ║
║                                                                  ║
║   Every deleted character remains as tombstone in CRDT state.    ║
║   Document display: 500 pages. CRDT state: 2.3 GB.               ║
║   Load time: 45 seconds. Browser tab crash.                      ║
║                                                                  ║
║   Root cause: No snapshot + GC strategy.                         ║
║   Fix: Periodic snapshot (compact to plain text + new CRDT       ║
║   genesis). Yjs/Automerge provide snapshot APIs.                 ║
╠══════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #6: PN-COUNTER NEGATIVE INVENTORY                 ║
║                                                                  ║
║   System: Ticket sales, PN-Counter for remaining seats           ║
║   Initial: 100 seats → PN-Counter value = 100                    ║
║                                                                  ║
║   Partition between us-east-1 and eu-west-1.                     ║
║   Each region sells 80 tickets concurrently (no coordination).   ║
║   East: 100 - 80 = 20 local view                                 ║
║   West: 100 - 80 = 20 local view                                 ║
║   Merge: P=100, N=160 → value = -60                              ║
║                                                                  ║
║   CONVERGED to -60. Sold 160 tickets with 100 seats.             ║
║                                                                  ║
║   Root cause: PN-Counter is NOT a constraint solver.             ║
║   It counts operations, not enforces invariants.                 ║
║   Fix: Reserve seats via regional leader + ledger, OR            ║
║   accept oversell + waitlist, OR CRDT + coordination for         ║
║   the decrement-only-if-positive invariant.                      ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## SRE Diagnostic Toolkit
### 7.1 — Detecting CRDT / Conflict Issues in Production

```
SYMPTOMS THAT SCREAM "CONFLICT RESOLUTION BUG":

  → "Data came back after I deleted it"
  → "My edit disappeared but my colleague's stayed"
  → "Count is wrong but all servers agree on the wrong count"
  → "Mobile app sync takes forever after reinstall"
  → "Different regions show different cart contents — then
     suddenly they're the same but wrong"
  → "Customer charged for item that showed out-of-stock"
```

### 7.2 — Redis Enterprise CRDT Diagnostics

```bash
# Check CRDT sync lag between geo-replicas
redis-cli -h crdb-us-east.example.com CRDT.INFO

# Output fields to watch:
#   crdt_syncer_status: up/down
#   crdt_repl_id: replication stream identity
#   crdt_backlog_size: pending CRDT ops bytes
#   crdt_peer lag: seconds behind peer

# Alert if:
#   crdt_backlog_size > 10MB for > 5 min
#   crdt_peer lag > 30s during steady state

# Inspect key type (must be CRDT-enabled at creation)
redis-cli TYPE cart:user123
# Expected: string|crdt-set|crdt-hashes (Enterprise-specific)

# Compare value across regions (should converge)
redis-cli -h us-east GET counter:pageviews
redis-cli -h eu-west GET counter:pageviews
# If diverged > 60s after write quiescence → CRDT sync broken
```

### 7.3 — DynamoDB Global Tables Conflict Detection

```bash
# Enable CloudWatch metric: ConflictResolutionDiscardedCheckAttempts
# (indicates conditional check conflicts during replication)

aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name ReplicationLatency \
  --dimensions Name=TableName,Value=GlobalCart \
  --start-time 2026-07-06T00:00:00Z \
  --end-time 2026-07-06T23:59:59Z \
  --period 300 \
  --statistics Average,Maximum

# Stream-based conflict audit:
# Enable DynamoDB Streams NEW_AND_OLD_IMAGES
# Lambda compares _version and timestamps on replicated writes

# Manual item compare across regions:
aws dynamodb get-item \
  --table-name GlobalCart \
  --key '{"pk":{"S":"user#123"},"sk":{"S":"METADATA"}}' \
  --region us-east-1 > east.json

aws dynamodb get-item \
  --table-name GlobalCart \
  --key '{"pk":{"S":"user#123"},"sk":{"S":"METADATA"}}' \
  --region eu-west-1 > west.json

diff east.json west.json
# If different after replication lag window (typically < 1s):
# conflict resolution or replication failure
```

### 7.4 — Application-Level CRDT Debugging

```python
# Log vector clock or version vector on every merge
def merge_and_log(local, remote, key):
    before = local.value()
    merged = local.merge(remote)
    after = merged.value()

    if detect_concurrent(local.vv, remote.vv):
        logger.warning(
            "crdt_concurrent_merge",
            extra={
                "key": key,
                "local_vv": local.vv,
                "remote_vv": remote.vv,
                "before": before,
                "after": after,
                "local_node": local.node_id,
                "remote_node": remote.node_id,
            }
        )
    return merged

# Metric: crdt_concurrent_merge_total (counter, labels: crdt_type, field)
# Alert if rate spikes 10x baseline → possible partition or bug
```

### 7.5 — Automerge / Yjs Debug Checklist

```javascript
// Automerge: dump change history
import * as Automerge from '@automerge/automerge'

const history = Automerge.getHistory(doc)
console.log(history.map(h => ({
  time: h.time,
  hash: h.hash.slice(0, 8),
  message: h.message,
})))

// Check for unresolved conflicts (multi-value registers)
const conflicts = Automerge.getConflicts(doc, 'fieldName')
if (conflicts.length > 0) {
  console.error('Unresolved conflicts:', conflicts)
}

// Yjs: state vector for sync debugging
const sv = Y.encodeStateVector(ydoc)
const update = Y.encodeStateAsUpdate(ydoc, remoteStateVector)
// Compare update size — if MB-scale, tombstone bloat likely
```

### 7.6 — Key Metrics Dashboard

```
╔═════════════════════════════════════════════════════════════════╗
║   METRIC                          │  THRESHOLD    │  MEANING    ║
╠═════════════════════════════════════════════════════════════════╣
║  crdt_merge_latency_p99           │  > 100ms      │  Hot key    ║
║                                   │               │  or bloat   ║
╠═════════════════════════════════════════════════════════════════╣
║  crdt_state_size_bytes (per key)  │  > 1MB        │  Tombstone  ║
║                                   │               │  explosion  ║
╠═════════════════════════════════════════════════════════════════╣
║  crdt_sync_lag_seconds            │  > 30s        │  Replication║
║                                   │               │  backlog    ║
╠═════════════════════════════════════════════════════════════════╣
║  crdt_concurrent_merge_rate       │  10x baseline │  Partition  ║
║                                   │               │  or dual    ║
║                                   │               │  write      ║
╠═════════════════════════════════════════════════════════════════╣
║  conflict_resolution_overrides    │  any increase │  User edits ║
║  (manual conflict picks)          │               │  lost       ║
╠═════════════════════════════════════════════════════════════════╣
║  idempotency_duplicate_blocked    │  drop to 0    │  Idempotency║
║                                   │               │  store down ║
╚═════════════════════════════════════════════════════════════════╝
```

---

## Decision Framework
### 8.1 — When CRDTs Beat LWW

```
╔═════════════════════════════════════════════════════════════════╗
║   USE CRDT (not LWW) WHEN:                                      ║
╠═════════════════════════════════════════════════════════════════╣
║   ✓ Concurrent writes must ALL be preserved (counters, sets)    ║
║   ✓ Active-active multi-region with local write latency         ║
║   ✓ Offline-first clients that sync on reconnect                ║
║   ✓ No central coordinator available during partition           ║
║   ✓ Merge semantics map cleanly to a known CRDT type            ║
║   ✓ Collaborative editing (text, arrays)                        ║
╠═════════════════════════════════════════════════════════════════╣
║   USE LWW WHEN:                                                 ║
╠═════════════════════════════════════════════════════════════════╣
║   ✓ Single authoritative value is correct (bio, status)         ║
║   ✓ Losing intermediate writes is acceptable                    ║
║   ✓ Infrastructure provides LWW (DynamoDB global tables)        ║
║   ✓ Clock sync is reliable (HLC, TrueTime)                      ║
╠═════════════════════════════════════════════════════════════════╣
║   USE COORDINATION (not CRDT) WHEN:                             ║
╠═════════════════════════════════════════════════════════════════╣
║   ✓ Invariants must hold (balance ≥ 0, inventory ≥ 0)           ║
║   ✓ Uniqueness constraints (username, seat number)              ║
║   ✓ Linearizability required (locks, leader election)           ║
╚═════════════════════════════════════════════════════════════════╝
```

### 8.2 — Google Docs OT vs CRDT

```
OPERATIONAL TRANSFORMATION (OT) — Google Docs:

  1. Client sends op: insert("Hello", pos=0)
  2. Server assigns global sequence number
  3. Server broadcasts; concurrent ops TRANSFORM against each other
  4. All clients apply same transformed ops → same document

  Requires: central server for ordering, connected clients
  Strengths: no tombstones, mature, intuitive ordering
  Weaknesses: SPoF for edit order, offline is hard, N² transform matrix

CRDT — Yjs / Automerge:

  1. Client applies op locally (optimistic)
  2. Op broadcast to peers (any order)
  3. Deterministic merge — same ops → same state

  Requires: eventual delivery, unique op IDs, tombstone GC
  Strengths: offline-native, P2P, partition-tolerant, provably convergent
  Weaknesses: metadata growth, arbitrary concurrent insert order

CHOOSE OT: central server always up, dense real-time collab, Google-scale
CHOOSE CRDT: offline-first, P2P, local-first, multi-region active-active
```

### 8.3 — Technology Selection Matrix

```
┌────────────────────┬──────────────┬──────────────┬──────────────┐
│  Requirement       │  DynamoDB    │  Redis Ent.  │  Automerge/  │
│                    │  Global      │  CRDT        │  Yjs         │
├────────────────────┼──────────────┼──────────────┼──────────────┤
│  LWW single value  │  native      │  yes         │  yes         │
│  PN-Counter        │  roll own    │  native      │  yes         │
│  OR-Set            │  roll own    │  native      │  yes         │
│  Text/RGA          │  no          │  partial     │  native      │
│  Offline mobile    │  partial     │  partial     │  best        │
│  Strong invariant  │  no          │  no          │  no          │
└────────────────────┴──────────────┴──────────────┴──────────────┘
```

---

### Principal stretch

## Ops Sim: Northstar Cart Remove-Add Merge Conflict

**Time box:** 50 minutes  
**Severity:** P1  
**Service / domain:** CRDT carts, mobile offline sync, conflict resolution  
**Northstar system:** Northstar Commerce

### Drill rules

1. Answer from memory of the CRDTs and Conflict Resolution teaching section; do not re-read mid-drill.
2. Write decisions in order: T+0, T+5, T+15, T+30, T+60, and follow-up.
3. Tie every claim to a metric, log line, trace, query output, or config key from this packet.
4. Name the correctness invariant before proposing scale, failover, replay, or data repair.
5. Do not open the answer key until your response is written.

---

### Page summary

```text
WHAT USERS SEE:
  - Removed items reappear in offline mobile carts and reach checkout.
  - Source-of-truth records and derived projections disagree.
  - Support reports cluster in the named slice, not the full fleet.
  - A proposed generic mitigation would hide or worsen the invariant risk.

WHAT ON-CALL SEES:
  - LWW trusts skewed device timestamps and remove tombstones expire in 5 minutes.
  - Fleet-average dashboards understate the incident.
  - The config fragment below changed recently or lacks a guardrail.
  - Repair must wait for a bounded affected set and idempotent operation key.

BUSINESS CONSTRAINT:
  Do not charge for items the user removed; ambiguous carts must stop before payment.
```

### Failure model

Offline carts use last-write-wins timestamps and 5-minute remove tombstones. Skewed devices resurrect removed items and checkout charges for stale cart contents.

Break it into these forces before answering:
- trigger: the release/config/data shape that started the failure
- amplifier: retry, cache, routing, projection, or observability behavior that widened it
- scarce resource: the metric that reaches a limit first
- invariant: what must remain conservative even while users see degraded experience
- repair boundary: the source of truth and operation id used after mitigation

### Diff from normal

- The suspicious production lever is `cart.merge_strategy: lww_timestamp`; tie it to the first bad minute before changing capacity.
- The dashboard that stayed calm does not expose `removed_items_reappeared_total` for the damaged slice.
- The runbook move closest to "trust the newest device timestamp" needs an explicit no-go decision on the bridge.
- The repair path is allowed only after the source-of-truth query and operation key are written down.

### Metrics logs traces

```text
METRICS:
  - removed_items_reappeared_total: +88000
  - checkout_cart_price_mismatch_rate: 6.1%
  - mobile_sync_conflict_total: +310k
  - device_clock_skew_seconds{p99}: 420
  - cart_merge_lww_wins{source="offline"}: 72%
  - refund_requests_wrong_item_total: +2100
  - remove_tombstone_expired_before_sync_total: +54000
  - payment_void_due_cart_conflict_total: +7300

LOG LINES:
  - cart-sync: lww chose offline add timestamp over server remove
  - Northstar Cart Remove-Add Merge Conflict: derived projection disagrees with source of truth
  - Northstar Cart Remove-Add Merge Conflict: unsafe repair or fallback proposed on bridge
  - Northstar Cart Remove-Add Merge Conflict: affected-slice metric exceeds fleet average
  - Northstar Cart Remove-Add Merge Conflict: capacity check missing before replay/scale

TRACE / QUERY / INSPECTION NOTES:
  - Inspect server cart event log, tombstone TTL, and device clock skew.
  - Before/after config diff aligns with the first bad metric.
  - The affected set is bounded by time window plus business key.
  - One generic health check remains green and is a red herring.
```

### Wrong config pack

```yaml
cart.merge_strategy: lww_timestamp
cart.remove_tombstone_ttl_seconds: 300
device_time_trusted: true
or_set.enabled: false
server_merge_requires_observed_remove: false
```

### Triage timeline

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | Removed items reappear in mobile carts. | Stop conflicted carts before payment. |
| T+5 | Team proposes trusting newest timestamp. | Reject device-time LWW. |
| T+15 | Short remove tombstones and skew confirmed. | Extend tombstones and require server merge. |
| T+30 | New checkouts hold on conflicts. | Bound affected orders. |
| T+60 | Refund/void queue is ready. | Repair from server cart event log. |
| T+24h | Mobile sync design review starts. | Move to observed-remove semantics. |

### Available runbook moves

- Roll back or disable the specific dangerous config from the packet.
- Shed decorative, derived, notification, or analytics work before weakening source-of-truth correctness.
- Throttle retry/replay using the narrowest downstream capacity limit.
- Keep an affected-record ledger before customer-visible repair.
- Verify recovery with the sliced SLI plus the scarce-resource metric, not a fleet average.

### Unsafe shortcuts

For each proposal, name the concrete failure mode it creates.

- trust the newest device timestamp
- delete all offline carts
- repair from search/cart cache
- charge first and refund later

### Questions

**Q01.** What exact layer owns the failure and why is the most obvious graph a red herring?

**Q02.** Which config line is wrong, and what failure physics does it create?

**Q03.** Select three metrics and two log/inspection clues that prove your diagnosis.

**Q04.** What is the safe T+0 to T+5 announcement and freeze/rollback decision?

**Q05.** What do you stop first: trigger, amplifier, or repair job? Explain sequencing.

**Q06.** What invariant must remain true if every dashboard is stale?

**Q07.** Which bad fix is most tempting in this incident, and why does it make recovery worse?

**Q08.** What numeric capacity or blast-radius check is required before scale/failover/replay?

**Q09.** What is the source-of-truth query or ledger for the affected set?

**Q10.** Which derived systems may lag, and which external side effects require idempotency?

**Q11.** Write the durable config/architecture change and its acceptance test.

**Q12.** Who joins by T+10, and what is pre-authorized versus escalated?

### Self-score

| Error type | Count | Notes |
|------------|-------|-------|
| Wrong layer/root cause | | |
| Evidence gap | | |
| Unsafe first action | | |
| Capacity/blast-radius miss | | |
| Correctness invariant miss | | |
| Repair/replay mistake | | |
| Org/runbook gap | | |

**Pass bar:** correct mechanism, safe sequencing, explicit rejection of the bad fix, one numeric capacity check, and a repair plan grounded in source of truth.

**Answer key:** [answers/Week-08-Advanced-Patterns/CRDTs and Conflict Resolution Answers.md](../answers/Week-08-Advanced-Patterns/CRDTs%20and%20Conflict%20Resolution%20Answers.md)

