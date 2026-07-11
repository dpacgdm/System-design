# Week 3, Topic 2: Consistency Models

---

## Learning Objectives
```
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Name and define every consistency model on the spectrum ║
║      from eventual consistency to linearizability            ║
║                                                              ║
║   2. Explain the precise ANOMALY that each model prevents    ║
║      (each model exists because a specific bad thing happens ║
║      without it)                                             ║
║                                                              ║
║   3. Given a product requirement, select the MINIMUM         ║
║      consistency model that satisfies it (stronger than      ║
║      needed = wasted latency; weaker than needed = bugs)     ║
║                                                              ║
║   4. Identify which consistency model a real system          ║
║      (PostgreSQL, Cassandra, DynamoDB, Redis) provides       ║
║      at each configuration level                             ║
║                                                              ║
║   5. Diagnose a production bug as a consistency model        ║
║      violation and prescribe the exact fix                   ║
║                                                              ║
║   6. Articulate in an interview why "eventual consistency"   ║
║      is not one thing — it's a family of guarantees, and     ║
║      the specific guarantee matters enormously               ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Eventual consistency = stale data forever"          ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Eventual consistency guarantees convergence when writes        ║
║   stop — replicas reach the same state. The window of staleness         ║
║   is bounded by replication lag, not infinite. The question is          ║
║   whether your product tolerates that window.                           ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Strong consistency = ACID consistency"              ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Distributed "strong consistency" (linearizability) is          ║
║   about all nodes agreeing on operation order. ACID consistency         ║
║   is about constraint enforcement within one database. Same word,       ║
║   different guarantees — conflating them causes design bugs.            ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Linearizability is always required"                 ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Social feeds, view counts, and "last seen" timestamps          ║
║   tolerate seconds of staleness. Linearizability costs latency          ║
║   (quorum round-trips). Use the MINIMUM model that satisfies            ║
║   the product requirement — not the maximum available.                  ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Read-your-writes is free with replication"          ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Reading from a random replica after writing to the             ║
║   leader violates read-your-writes unless you route reads to the        ║
║   leader, use session tokens, or wait for replication sync.             ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Causal consistency is the same as sequential"       ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Sequential consistency requires a global order visible         ║
║   to all clients. Causal consistency only preserves cause-effect        ║
║   chains (if A→B, everyone sees A before B). Weaker, cheaper,           ║
║   sufficient for many collaboration features.                           ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "If users don't complain, consistency is fine"       ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Consistency bugs are intermittent and hard to reproduce.       ║
║   Double-charged payments, duplicate orders, and lost updates           ║
║   surface under race conditions — often reported as "random UI          ║
║   glitches" until finance finds the discrepancy.                        ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching
### Why This Topic Exists

```
In Topic 1 (CAP/PACELC), we established that the real
tradeoff is Consistency vs Latency (or Availability
during partitions).

But CAP defines consistency as LINEARIZABILITY — the
strongest possible guarantee. And the alternative is
often described as "eventual consistency."

This creates a FALSE BINARY:

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   LINEARIZABILITY ◄──── huge gap ────► EVENTUAL              ║
  ║   (perfect)                          (chaos?)                ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

In reality, there are MANY useful consistency models
between these extremes. Each one prevents a specific
anomaly while allowing better performance than
linearizability.

THE REAL SPECTRUM:

  STRONGEST ◄──────────────────────────────► WEAKEST

  Linearizability
    │
  Sequential Consistency
    │
  Causal Consistency
    │
  Read-your-writes
    │
  Monotonic Reads
    │
  Monotonic Writes
    │
  Consistent Prefix Reads
    │
  Eventual Consistency

Each step down the spectrum:
  → Allows ONE MORE type of anomaly
  → Gains performance (less coordination between nodes)

Each step UP the spectrum:
  → Prevents one more anomaly
  → Costs performance (more coordination required)

THE ENGINEERING QUESTION:
  What's the WEAKEST (cheapest) consistency model that
  still gives correct behavior for my use case?
```

### The Full Spectrum — Top to Bottom

---

#### 1. LINEARIZABILITY (Strongest)

```
DEFINITION:
  Every operation appears to execute ATOMICALLY at some
  single point in time between its invocation and
  completion. All operations form a SINGLE TOTAL ORDER
  that every observer agrees on.

  Informally: "The system behaves as if there's only
  ONE copy of the data, and every operation happens
  instantly."

WHAT IT GUARANTEES:
  → After a write completes, ALL subsequent reads from
    ANY client on ANY node return the new value
  → There is ONE global timeline of operations
  → All clients agree on the ORDER of operations
  → No "time travel" — you never see a new value and
    then see an old value again

VISUAL:

  REAL TIME ──────────────────────────────────►

  Client A: ──write(X=1)──╮
                           │ write completes
                           ▼
  Client B:                   ──read(X)──► returns 1 ✓
  Client C:                      ──read(X)──► returns 1 ✓

  After the write completes at the wall-clock moment,
  EVERY read returns 1. No exceptions. No windows.

ANOMALY IT PREVENTS:
  "Stale read after acknowledged write"

  IMPOSSIBLE under linearizability:
    Client A: write(X=5) → ACK ✓
    Client B: read(X) → returns 3 (old value)  ✗ CANNOT HAPPEN

COST:
  → Every write must be confirmed by enough replicas to
    guarantee all subsequent reads see it
  → Cross-node coordination on EVERY operation
  → Latency: bounded by the slowest replica in the
    write quorum
  → Cannot scale reads by adding replicas (every replica
    must be up-to-date before ANY read can proceed)

WHO PROVIDES THIS:
  → etcd (Raft consensus — all reads go through leader)
  → ZooKeeper (ZAB protocol)
  → Spanner (TrueTime + Paxos)
  → PostgreSQL single-node (trivially — one copy)
  → CockroachDB (serializable + Raft)

  → NOT: Cassandra, DynamoDB (eventually consistent mode),
    Redis Cluster, MongoDB (for cross-shard reads)

WHEN YOU NEED IT:
  → Leader election ("who is the primary?")
  → Distributed locks ("is this resource locked?")
  → Unique constraints ("does this username exist?")
  → Account balance checks before financial transactions
    ← THIS IS ALICE'S TRADE from Topic 1
```

#### 2. SEQUENTIAL CONSISTENCY

```
DEFINITION:
  All operations appear to execute in SOME sequential
  order, and each client's operations appear in the
  order that client issued them. But different clients
  may disagree about where OTHER clients' operations
  fall in the timeline.

  Informally: "There's a valid ordering of all operations,
  and each client's operations are in the right order
  within it — but it might not match real-time."

DIFFERENCE FROM LINEARIZABILITY:

  Linearizability: operations are ordered by REAL TIME.
  Sequential: operations are ordered CONSISTENTLY, but
  not necessarily by real time.

  EXAMPLE:

  REAL TIME ──────────────────────────────────►

  Client A: write(X=1)     (at time T=1)
  Client B:    write(X=2)  (at time T=2, slightly after A)
  Client C:                      read(X) → ???

  Linearizable: C MUST read 2 (B's write was last in real time)

  Sequential: C could read 1 OR 2, as long as ALL clients
  agree on the same ordering. If the system decided the
  order is [B writes 2, A writes 1], then C reads 1 and
  that's VALID — even though A's write was first in real time.

  The constraint: if Client A does write(X=1) then read(Y),
  then in the sequential order, write(X=1) MUST come before
  read(Y). Each client's operations preserve their order.

ANOMALY IT PREVENTS:
  → A client's operations appear out of order
  → Operations from the same client get reordered

ANOMALY IT ALLOWS (that linearizability prevents):
  → Ordering may not match real time
  → "I wrote X=5 and it was acknowledged, but another
    client still reads X=3 for a moment — and that's
    valid as long as EVENTUALLY everyone agrees on the
    same order"

COST:
  → Less expensive than linearizability (no real-time
    ordering requirement)
  → Still requires global agreement on an order
  → Still expensive in practice

WHO PROVIDES THIS:
  → Most systems don't explicitly advertise "sequential
    consistency" — it's more of a theoretical reference
    point between linearizability and causal consistency
  → Some memory models (hardware CPU caches) provide this

WHEN YOU NEED IT:
  → Rare in distributed databases
  → More relevant in shared-memory multiprocessor systems
  → Useful as a conceptual stepping stone
```

#### 3. CAUSAL CONSISTENCY

```
DEFINITION:
  Operations that are CAUSALLY RELATED are seen by all
  nodes in the same order. Operations that are NOT
  causally related (concurrent) can be seen in any order.

  "If operation A could have INFLUENCED operation B,
  then everyone sees A before B."

WHAT IS "CAUSALLY RELATED"?

  Two operations are causally related if:

  1. SAME CLIENT: A client does op1 then op2.
     op1 → op2 (op1 causally precedes op2)

  2. READS-FROM: Client B reads a value that Client A
     wrote. B's subsequent operations are causally
     after A's write.

  3. TRANSITIVE: If A → B and B → C, then A → C.

  Operations with NO causal relationship are CONCURRENT.
  They can be seen in any order by different observers.

EXAMPLE:

  ╔══════════════════════════════════════════════════════════════╗
  ║  Social Media Comment Thread                                 ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║  Alice posts:  "I got the job!"         (op A)               ║
  ║  Bob reads Alice's post, then replies:                       ║
  ║    "Congratulations!"                   (op B)               ║
  ║  Carol (hasn't seen anything) posts:                         ║
  ║    "Nice weather today"                 (op C)               ║
  ║                                                              ║
  ║  CAUSAL RELATIONSHIPS:                                       ║
  ║    A → B  (Bob's reply was caused by Alice's post)           ║
  ║    C is CONCURRENT with A and B (no causal link)             ║
  ║                                                              ║
  ║  VALID orderings (causal consistency):                       ║
  ║    [A, B, C]  ✓ (A before B, C anywhere)                     ║
  ║    [A, C, B]  ✓ (A before B, C anywhere)                     ║
  ║    [C, A, B]  ✓ (A before B, C anywhere)                     ║
  ║                                                              ║
  ║  INVALID ordering:                                           ║
  ║    [B, A, C]  ✗ (B before A violates causality)              ║
  ║    If you see "Congratulations!" BEFORE "I got               ║
  ║    the job!" — that's nonsensical. Causal                    ║
  ║    consistency prevents this.                                ║
  ╚══════════════════════════════════════════════════════════════╝

ANOMALY IT PREVENTS:
  "Seeing an effect before its cause"
  → Seeing a reply before the original message
  → Seeing a "like" count update before the post exists
  → Seeing a permission revocation but still seeing
    actions that happened BECAUSE of the old permission

ANOMALY IT ALLOWS:
  → Concurrent operations (no causal link) can appear
    in different orders on different nodes
  → Two users in different regions might see concurrent
    posts in different orders — and that's fine

COST:
  → Much cheaper than linearizability
  → Only needs to track causal dependencies, not a
    global total order
  → Can be implemented with VECTOR CLOCKS or
    LAMPORT TIMESTAMPS (Week 8 topics)
  → Nodes don't need to coordinate on concurrent
    operations — only on causally related ones

WHO PROVIDES THIS:
  → MongoDB (causal consistency sessions, since 3.6)
  → Some research databases (COPS, Eiger)
  → Can be layered on top of eventually consistent
    systems with causal metadata

WHEN YOU NEED IT:
  → Social media (comments must appear after their
    parent posts)
  → Chat applications (messages in a thread must be
    ordered causally)
  → Collaborative editing (edits that depend on
    previous edits must be ordered)
  → Access control (permission revocations must be
    visible before actions that depend on old permissions)
```

#### 4. READ-YOUR-WRITES (aka Read-After-Write)

```
DEFINITION:
  If a client writes a value, that SAME CLIENT will
  always read the new value (or a later value).
  The client never sees their own write "disappear."

  Other clients are NOT guaranteed to see the write.

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Client A: write(X=5) → ACK                                 ║
  ║   Client A: read(X) → returns 5 ✓ GUARANTEED                 ║
  ║                                                              ║
  ║   Client B: read(X) → returns 3 (old) ALLOWED                ║
  ║   (B hasn't seen A's write yet — that's OK)                  ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

ANOMALY IT PREVENTS:
  "User updates their profile, refreshes the page,
   sees the OLD profile"

  This is THE most common consistency complaint
  from users. It's deeply confusing:

  "I JUST changed my display name. I can SEE the
   confirmation. I refresh the page and my old name
   is back?!"

  Without read-your-writes:
    → User updates profile → write goes to primary
    → User refreshes page → read goes to replica
    → Replica is 500ms behind → OLD profile is shown
    → User thinks the system is broken

ANOMALY IT ALLOWS:
  → Other users may not see your write immediately
  → Different users may see different states of the data
  → That's fine for many use cases (Alice doesn't care
    that Bob doesn't IMMEDIATELY see her new display name)

IMPLEMENTATION APPROACHES:

  APPROACH 1: Read from primary for "own" data
    → After a write, route reads for that key/user
      to the primary for N seconds
    → After N seconds (replication lag window),
      switch back to replica reads
    → N must be > max expected replication lag

    async def read_profile(user_id, request_user_id):
        if user_id == request_user_id:
            last_write = await get_last_write_time(user_id)
            if time.now() - last_write < 5:  # 5s window
                return await primary_db.fetch(user_id)
        return await replica_db.fetch(user_id)

  APPROACH 2: Client-side timestamp tracking
    → Client sends the timestamp of its last write
      with every read request
    → Server ensures the read comes from a replica
      that is at least as fresh as that timestamp
    → If no replica is fresh enough → read from primary

    # Client sends:  X-Last-Write-Timestamp: 1705329600123
    # Server checks: replica WAL position ≥ that timestamp?
    #   Yes → serve from replica
    #   No  → route to primary

  APPROACH 3: Session stickiness
    → After a write, pin the user's session to the
      primary (or to a specific replica that received
      the write) for a time window
    → Simple but creates load imbalance on primary

WHO PROVIDES THIS:
  → DynamoDB: strongly consistent reads (per-request opt-in)
  → PostgreSQL: if you read from the primary after writing
  → Cassandra: if W + R > N for the same client's operations
  → Most systems: requires APPLICATION-LEVEL implementation
    (the database doesn't track "which client wrote what")

WHEN YOU NEED IT:
  → User profile updates (display name, avatar, settings)
  → Shopping cart (add item → cart page shows item)
  → Post creation (write post → timeline shows your post)
  → Any user-facing write-then-read flow

  THIS IS THE MINIMUM CONSISTENCY MODEL FOR MOST
  USER-FACING APPLICATIONS.
```

#### 5. MONOTONIC READS

```
DEFINITION:
  If a client reads a value X at time T, any subsequent
  read by THAT CLIENT will return the same value or a
  NEWER value. Never an older one.

  "Time doesn't go backwards for reads."

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Client A: read(X) → returns 5                              ║
  ║   Client A: read(X) → returns 5 or 6 or 7...                 ║
  ║                        BUT NEVER 4 or 3                      ║
  ║                                                              ║
  ║   Without monotonic reads:                                   ║
  ║   Client A: read(X) → 5 (from replica-1)                     ║
  ║   Client A: read(X) → 3 (from replica-2!)                    ║
  ║             ↑ TIME WENT BACKWARDS                            ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

HOW THE VIOLATION HAPPENS:

  ╔══════════════════════════════════════════════════════════════╗
  ║  Primary  │  │Replica 1 │  │Replica 2                        ║
  ║  X=5      │  │ X=5      │  │ X=3                             ║
  ║  (latest) │  │ (caught  │  │ (behind)                        ║
  ║           │  │  up)     │  │                                 ║
  ╚══════════════════════════════════════════════════════════════╝

  Request 1: load balancer → Replica 1 → returns X=5
  Request 2: load balancer → Replica 2 → returns X=3 !

  The user sees X go from 5 to 3.
  "My bank balance was $5,000 a second ago.
   Now it says $3,000?! Where did $2,000 go?!"

  Then they refresh again:
  Request 3: load balancer → Replica 1 → returns X=5
  "$5,000 is back? What is happening?!"

ANOMALY IT PREVENTS:
  "Value goes backward" — seeing a newer value, then
  on the next read, seeing an older value.

ANOMALY IT ALLOWS:
  → You might see a stale value CONSISTENTLY (that's
    eventual consistency — you'll catch up eventually)
  → But you'll never see a NEW value and then REVERT
    to an old one

IMPLEMENTATION:

  APPROACH 1: Sticky sessions to one replica
    → Route all reads from the same client to the
      same replica
    → That replica's state only moves forward
    → Simple, but loses load balancing benefit

  APPROACH 2: Client tracks read position
    → After each read, the server returns its
      replication position (e.g., WAL LSN)
    → Client sends this position on next read
    → Server ensures it only serves from a replica
      whose position is ≥ client's last position
    → If no replica qualifies → read from primary

    # Response header: X-Read-Position: WAL/0/15A2B8C0
    # Next request:    X-Min-Read-Position: WAL/0/15A2B8C0
    # Server routes to replica with WAL ≥ 0/15A2B8C0

WHEN YOU NEED IT:
  → ANY dashboard or monitoring display (metrics going
    backward is confusing and causes false alerts)
  → Bank balance display (even if stale, must not jump
    backward)
  → Social media feed (post disappears then reappears
    = confusing)
  → Any paginated list (item appears on page 1,
    disappears on page 2, reappears on page 3)
```

#### 6. MONOTONIC WRITES

```
DEFINITION:
  If a client performs write W1 before write W2, then
  W1 is applied before W2 on ALL replicas. A client's
  writes are applied in order everywhere.

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Client A: write(X=1)  then  write(X=2)                     ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   On ALL replicas:                                           ║
  ║     X=1 is applied before X=2                                ║
  ║     Final state: X=2 on every replica ✓                      ║
  ║                                                              ║
  ║   WITHOUT monotonic writes:                                  ║
  ║     Replica 1: receives X=1, then X=2 → X=2 ✓                ║
  ║     Replica 2: receives X=2, then X=1 → X=1 ✗                ║
  ║     Replicas DISAGREE on final state!                        ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

HOW THE VIOLATION HAPPENS:

  Client writes X=1 → routed to Node A
  Client writes X=2 → routed to Node B (load balancer
  chose a different node)

  Node A replicates X=1 to all replicas.
  Node B replicates X=2 to all replicas.

  But replication is async. Some replicas receive X=2
  BEFORE X=1. They apply X=2, then overwrite it with
  X=1. Final state: X=1 (wrong — should be X=2).

ANOMALY IT PREVENTS:
  "Writes from the same client arrive out of order
  at some replicas, causing the wrong final state."

  Real-world example:
    User changes password to "abc123"
    User changes password again to "xyz789"

    If replica receives "xyz789" first, then "abc123":
    → Final password: "abc123" (the old one!)
    → User can't log in with "xyz789"
    → "But I JUST changed my password!"

IMPLEMENTATION:
  → Route all writes from the same client to the same
    primary/node (session affinity for writes)
  → OR: include a sequence number with each write,
    replicas apply in sequence order
  → OR: use a write-ahead log that preserves order
    (Kafka, PostgreSQL WAL)

WHEN YOU NEED IT:
  → Password changes (must be in order)
  → Counter updates (increment, then decrement — order
    matters for intermediate state)
  → Any multi-step workflow where order matters
  → State machine transitions (state A → B → C must
    not be reordered to A → C → B on some replicas)
```

#### 7. CONSISTENT PREFIX READS

```
DEFINITION:
  If a sequence of writes happens in order A, B, C,
  then any reader sees them in that order. A reader
  might see [A], or [A, B], or [A, B, C], but NEVER
  [A, C] (skipping B) or [B, A] (reordered).

  "You see a consistent PREFIX of the write history."

ANOMALY IT PREVENTS:
  "Seeing an effect without its predecessor"

  THE CLASSIC EXAMPLE:

  ╔══════════════════════════════════════════════════════════════╗
  ║  Conversation:                                               ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║  Alice (at T=1): "What time is the meeting?"                 ║
  ║  Bob   (at T=2): "3pm"                                       ║
  ║                                                              ║
  ║  CORRECT orderings a reader might see:                       ║
  ║    []                              (seen nothing)            ║
  ║    ["What time is the meeting?"]   (prefix of 1)             ║
  ║    ["What time is the meeting?",                             ║
  ║     "3pm"]                         (full)                    ║
  ║                                                              ║
  ║  VIOLATION:                                                  ║
  ║    ["3pm"]  ← sees Bob's answer without                      ║
  ║               Alice's question                               ║
  ║               "3pm" makes no sense in isolation!             ║
  ║                                                              ║
  ║  ALSO A VIOLATION:                                           ║
  ║    ["3pm", "What time is the meeting?"]                      ║
  ║    Reordered — answer before question                        ║
  ╚══════════════════════════════════════════════════════════════╝

HOW THE VIOLATION HAPPENS:

  In a SHARDED (partitioned) database:

  → Alice's message: stored on Shard 1
  → Bob's message: stored on Shard 2
  → A reader queries both shards
  → Shard 2 is faster than Shard 1
  → Reader sees Bob's reply but not Alice's question yet

  Each shard is internally consistent, but ACROSS shards,
  there's no coordination on ordering.

COST:
  → Preventing this requires some form of cross-shard
    ordering (global timestamps, causal tracking)
  → OR: keep causally related data on the SAME shard
    (partition by conversation_id, not by user_id)

WHO IS AFFECTED:
  → Any sharded database where related data spans shards
  → Microservices where events are published to different
    topics/partitions in different order

WHEN YOU NEED IT:
  → Chat applications (messages in order)
  → Audit logs (events in order)
  → Financial transaction history (chronological)
  → Any causal chain of events visible to users
```

#### 8. EVENTUAL CONSISTENCY (Weakest)

```
DEFINITION:
  If no new writes are made, EVENTUALLY all replicas
  will converge to the same value. No guarantee about
  WHEN, and no guarantee about what you'll see WHILE
  converging.

  "It'll get there... eventually."

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Write X=5 to primary                                       ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   T+0ms:   Primary=5, Replica1=3, Replica2=3                 ║
  ║   T+50ms:  Primary=5, Replica1=5, Replica2=3                 ║
  ║   T+120ms: Primary=5, Replica1=5, Replica2=5                 ║
  ║                                                              ║
  ║   At T+120ms: all replicas converged. ✓                      ║
  ║   Between T+0 and T+120ms:                                   ║
  ║     → You might read 3 or 5 depending on which               ║
  ║       replica you hit                                        ║
  ║     → You might read 5, then 3 (time travel!)                ║
  ║     → You might never see 3 → 5 transition                   ║
  ║       (jump straight from 3 to 7 if another                  ║
  ║        write happened)                                       ║
  ║                                                              ║
  ║   ALL of these are valid under eventual                      ║
  ║   consistency. There are NO ordering guarantees              ║
  ║   during the convergence window.                             ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

WHAT IT GUARANTEES:
  → Convergence (eventually, all replicas agree)
  → Durability (the write won't be lost — it'll propagate)

  THAT'S IT. Nothing else.

WHAT IT ALLOWS (all previous anomalies):
  → Stale reads ✓
  → Time-traveling reads (new → old → new) ✓
  → Out-of-order writes ✓
  → Seeing effects before causes ✓
  → Different clients seeing different states ✓

WHO PROVIDES THIS:
  → Cassandra at CL=ONE
  → DynamoDB (eventually consistent reads — the default!)
  → Redis Cluster (async replication between master/replica)
  → DNS (TTL-based propagation)
  → CDN caches (stale until purged/expired)

WHEN THIS IS ACCEPTABLE:
  → Like counts ("4,523 likes" vs "4,527 likes" — who cares)
  → View counters
  → Recommendation engines
  → Analytics dashboards (approximate is fine)
  → Session data where stale reads are harmless
  → Any data where the COST OF BEING WRONG is low
```

---

### The Complete Spectrum — Visual Summary

```
STRONGEST                                        WEAKEST
    │                                                │
    ▼                                                ▼
╔══════════════════════════════════════════════════════════════╗
║ LINEARIZ-   │ │SEQUENTIAL  │ │CAUSAL      │ │EVENTUAL        ║
║ ABILITY     │ │CONSISTENCY │ │CONSISTENCY │ │CONSISTENCY     ║
║             │ │            │ │            │ │                ║
║ All ops     │ │All ops in  │ │Causally    │ │Replicas        ║
║ ordered by  │ │some agreed │ │related ops │ │converge        ║
║ real time.  │ │order, per- │ │ordered.    │ │eventually.     ║
║ One global  │ │client order│ │Concurrent  │ │No ordering     ║
║ timeline.   │ │preserved.  │ │ops: any    │ │guarantee       ║
║             │ │            │ │order OK.   │ │in between.     ║
╚══════════════════════════════════════════════════════════════╝
       │                            │
       │    "SESSION GUARANTEES"    │
       │    (can be mixed/matched)  │
       │                            │
       │   ╔══════════════════════════════════════════════════════════════╗
       │   ║    │Read-your-writes  │                                      ║
       │   ║    │Monotonic reads   │                                      ║
       │   ║    │Monotonic writes  │                                      ║
       │   ║    │Consistent prefix │                                      ║
       │   ╚══════════════════════════════════════════════════════════════╝
       │                            │
       │   These FOUR guarantees    │
       │   sit between causal and   │
       │   eventual. They are       │
       │   INDEPENDENT — you can    │
       │   have any combination.    │
       │                            │
       │   All four combined ≈      │
       │   causal consistency       │

KEY INSIGHT:
  The four session guarantees are COMPOSABLE.
  You can have:
  → Read-your-writes WITHOUT monotonic reads
  → Monotonic reads WITHOUT read-your-writes
  → Both together
  → Neither

  They address DIFFERENT anomalies, so they're
  independently useful.
```

### Mapping Models to Real Systems

```
╔══════════════════════════════════════════════════════════════╗
║  SYSTEM         │ CONSISTENCY MODEL                          ║
╠══════════════════════════════════════════════════════════════╣
║  PostgreSQL     │ LINEARIZABLE (single node)                 ║
║  (single node)  │ One copy of data. All reads see latest.    ║
║                 │ Trivially linearizable.                    ║
╠══════════════════════════════════════════════════════════════╣
║  PostgreSQL     │ READ-YOUR-WRITES (if reading from          ║
║  (primary +     │ primary after writing to primary)          ║
║  async replica) │                                            ║
║                 │ EVENTUAL CONSISTENCY (reading from         ║
║                 │ replica — may be behind primary)           ║
║                 │                                            ║
║                 │ MONOTONIC READS if sticky to one replica   ║
║                 │ (that replica only moves forward)          ║
╠══════════════════════════════════════════════════════════════╣
║  PostgreSQL     │ LINEARIZABLE (for committed data)          ║
║  (primary +     │ Sync replica has everything primary has.   ║
║  sync replica)  │ Reads from either node are consistent.     ║
╠══════════════════════════════════════════════════════════════╣
║  Cassandra      │ EVENTUAL (CL=ONE for both R and W)         ║
║  CL=ONE         │ No guarantees about what you read.         ║
╠══════════════════════════════════════════════════════════════╣
║  Cassandra      │ LINEARIZABLE (for that key)                ║
║  CL=QUORUM R+W  │ R + W > N guarantees overlap.              ║
║  (RF=3)         │ At least one node in the read quorum       ║
║                 │ has the latest write.                      ║
║                 │ Read-repair returns the latest value.      ║
╠══════════════════════════════════════════════════════════════╣
║  Cassandra      │ READ-YOUR-WRITES                           ║
║  CL=ONE write   │ W=1, R=QUORUM → R+W = 1+2 = 3 = N          ║
║  CL=QUORUM read │ Overlap of 1. The node you wrote to        ║
║  (RF=3)         │ is in the read quorum.                     ║
║                 │ (Probabilistic — depends on RF and         ║
║                 │ node health)                               ║
╠══════════════════════════════════════════════════════════════╣
║  DynamoDB       │ EVENTUAL (default)                         ║
║  (default read) │ Reads may return stale data.               ║
╠══════════════════════════════════════════════════════════════╣
║  DynamoDB       │ LINEARIZABLE (per-item)                    ║
║  (strongly      │ Returns latest committed write.            ║
║  consistent     │ Costs 2x the read capacity units.          ║
║  read)          │ Only works against the leader.             ║
╠══════════════════════════════════════════════════════════════╣
║  MongoDB        │ CAUSAL (within a causal session)           ║
║  (causal        │ Reads reflect all writes that causally     ║
║  session)       │ precede them in the session.               ║
║                 │ Monotonic reads + read-your-writes +       ║
║                 │ monotonic writes + consistent prefix.      ║
╠══════════════════════════════════════════════════════════════╣
║  Redis Cluster  │ EVENTUAL (async replication)               ║
║                 │ Master→replica is async. Reads from        ║
║                 │ replica may be stale. After failover,      ║
║                 │ acknowledged writes may be lost.           ║
╠══════════════════════════════════════════════════════════════╣
║  etcd / Raft    │ LINEARIZABLE                               ║
║                 │ All reads go through leader (or use        ║
║                 │ ReadIndex/LeaseRead for followers).        ║
║                 │ Raft guarantees linearizability.           ║
╠══════════════════════════════════════════════════════════════╣
║  ZooKeeper      │ LINEARIZABLE (writes)                      ║
║                 │ SEQUENTIAL CONSISTENCY (reads from         ║
║                 │ followers — may be stale but monotonic)    ║
║                 │ sync() call upgrades a read to             ║
║                 │ linearizable.                              ║
╚══════════════════════════════════════════════════════════════╝
```

### The Decision Framework for Interviews

```
When designing a system, apply this framework PER FEATURE:

STEP 1: Identify the WORST ANOMALY that would be acceptable.

  "If a user reads stale data for this feature,
   what's the worst thing that happens?"

STEP 2: Pick the WEAKEST model that prevents unacceptable
anomalies.

  ╔══════════════════════════════════════════════════════════════╗
  ║  IF THIS ANOMALY IS UNACCEPTABLE:  │ YOU NEED AT LEAST:      ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Any stale read, ever              │ Linearizability         ║
  ║  (distributed locks, elections,    │                         ║
  ║   balance checks for transactions) │                         ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Seeing effect before cause        │ Causal                  ║
  ║  (reply before question,           │ Consistency             ║
  ║   child before parent)             │                         ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  User can't see their own writes   │ Read-your-writes        ║
  ║  (profile update invisible,        │                         ║
  ║   cart item disappears)            │                         ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Value goes backward               │ Monotonic reads         ║
  ║  (balance jumps from $500 to $300  │                         ║
  ║   then back to $500)               │                         ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Writes applied out of order       │ Monotonic writes        ║
  ║  (password reset reordered,        │                         ║
  ║   state machine violation)         │                         ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  None of the above is a problem    │ Eventual                ║
  ║  (like counts, view counts,        │ Consistency             ║
  ║   analytics, recommendations)      │                         ║
  ╚══════════════════════════════════════════════════════════════╝

STEP 3: Choose the implementation that provides that model.

  Linearizable → etcd, ZK, Spanner, or "read from primary"
  Causal → MongoDB causal sessions, or vector clocks
  Read-your-writes → route to primary after write, or
                      client-side timestamp tracking
  Monotonic reads → sticky sessions, or position tracking
  Eventual → any async-replicated database, default mode
```

---

## Production Patterns
```
╔═══════════════════════════════════════════════════════════════╗
║   FAILURE MODE #1: THE VANISHING CART ITEM                    ║
║                                                               ║
║   System: E-commerce, PostgreSQL primary + 2 async replicas   ║
║   Load balancer: round-robin across replicas for reads        ║
║                                                               ║
║   User adds item to cart (writes to primary).                 ║
║   User's next page load → round-robin → hits replica-2.       ║
║   Replica-2 is 200ms behind → cart appears EMPTY.             ║
║   User adds the item again.                                   ║
║   Next page load → hits replica-1 (caught up) → TWO items.    ║
║   User is confused: "I only added one!"                       ║
║                                                               ║
║   Root cause: No read-your-writes guarantee.                  ║
║                                                               ║
║   Fix: After any cart write, set a cookie with the write      ║
║   timestamp. For reads within 2 seconds of the cookie,        ║
║   route to primary. After 2s, resume replica reads.           ║
║                                                               ║
║   # Nginx example:                                            ║
║   map $cookie_last_write $backend {                           ║
║     default replica_pool;                                     ║
║     ~.     primary_if_recent;                                 ║
║   }                                                           ║
╠═══════════════════════════════════════════════════════════════╣
║   FAILURE MODE #2: THE FLICKERING DASHBOARD                   ║
║                                                               ║
║   System: Monitoring dashboard, reads from 3 replicas         ║
║   Load balancer: round-robin across replicas                  ║
║                                                               ║
║   Dashboard auto-refreshes every 5 seconds.                   ║
║   Refresh 1 → Replica-1 (caught up)   → 4,523 requests/s      ║
║   Refresh 2 → Replica-3 (behind)      → 4,100 requests/s      ║
║   Refresh 3 → Replica-1 (caught up)   → 4,530 requests/s      ║
║   Refresh 4 → Replica-2 (slightly behind) → 4,480 requests/s  ║
║                                                               ║
║   The graph BOUNCES: 4523 → 4100 → 4530 → 4480                ║
║   It looks like traffic is oscillating wildly.                ║
║   An on-call SRE investigates a "traffic anomaly."            ║
║   Hours wasted on a phantom problem.                          ║
║                                                               ║
║   Root cause: No monotonic reads guarantee.                   ║
║   Each refresh hits a different replica at a different        ║
║   replication lag, causing apparent backward movement.        ║
║                                                               ║
║   Fix: Sticky sessions for the dashboard.                     ║
║   OR: Return the replica's WAL position with each response.   ║
║   Next request includes it: "give me data at least this       ║
║   fresh." Routes to appropriate replica.                      ║
╠═══════════════════════════════════════════════════════════════╣
║   FAILURE MODE #3: THE PHANTOM NOTIFICATION                   ║
║                                                               ║
║   System: Social media. Sharded by user_id.                   ║
║   Alice posts a photo (stored on shard A).                    ║
║   System generates notifications for Alice's followers        ║
║   (stored on shard B, C, D for different followers).          ║
║                                                               ║
║   Bob (shard B) gets a notification: "Alice posted a photo!"  ║
║   Bob clicks the notification.                                ║
║   Bob's request fetches the photo from shard A.               ║
║   But shard A hasn't finished replicating/indexing the photo. ║
║   Bob sees: "Photo not found."                                ║
║   "But I JUST got a notification about it!"                   ║
║                                                               ║
║   Root cause: No consistent prefix reads.                     ║
║   The notification (effect) is visible before the             ║
║   photo (cause) is visible.                                   ║
║                                                               ║
║   Fix: Don't send the notification until the photo is         ║
║   confirmed readable from all relevant replicas.              ║
║   OR: When Bob clicks, if photo isn't found, retry from       ║
║   primary with a "causal read" (read at the timestamp         ║
║   of the write that created the notification).                ║
╠═══════════════════════════════════════════════════════════════╣
║   FAILURE MODE #4: THE DOUBLE DEBIT                           ║
║                                                               ║
║   System: Payment service. Two replicas.                      ║
║   User requests $100 transfer.                                ║
║                                                               ║
║   Primary: balance = $500. Debit $100. Balance = $400.        ║
║   Primary ACKs the transfer.                                  ║
║   Primary crashes BEFORE replicating to replica.              ║
║                                                               ║
║   Replica promoted. Balance = $500 (never got the update).    ║
║   User sees $500. "Transfer didn't go through."               ║
║   User requests $100 transfer AGAIN.                          ║
║   New primary: balance = $500. Debit $100. Balance = $400.    ║
║                                                               ║
║   When old primary recovers (if it recovers):                 ║
║   Its log says balance = $400 (after first debit).            ║
║   But the new primary also says $400 (after second debit).    ║
║   Two debits happened. User was charged $200, not $100.       ║
║                                                               ║
║   Root cause: Async replication (EL) for financial data.      ║
║   The first debit was acknowledged but not replicated.        ║
║   After failover, the system lost the first debit and         ║
║   allowed a second one.                                       ║
║                                                               ║
║   Fix: Synchronous replication (EC) for financial data.       ║
║   Write is not acknowledged until replica confirms.           ║
║   If primary crashes after ACK, replica has the data.         ║
║   After failover, balance = $400 (correct).                   ║
║   User sees $400, knows transfer succeeded.                   ║
║   No double debit.                                            ║
║                                                               ║
║   Additional fix: Idempotency keys.                           ║
║   Each transfer has a unique ID. If the same ID is            ║
║   submitted twice, the second one is a no-op.                 ║
║   Even if the system DOES lose the first debit,               ║
║   the retry with the same ID is detected and rejected.        ║
║   Defense in depth: EC replication + idempotency.             ║
╚═══════════════════════════════════════════════════════════════╝
```

### SRE Toolkit — Measuring and Debugging Consistency

```
# PostgreSQL: Check replication lag
psql -h primary -c "
  SELECT client_addr,
         state,
         sent_lsn,
         write_lsn,
         flush_lsn,
         replay_lsn,
         (sent_lsn - replay_lsn) AS replication_lag_bytes,
         now() - pg_last_xact_replay_timestamp() AS lag_time
  FROM pg_stat_replication;"

# If lag_time > your consistency window → reads from
# that replica may violate read-your-writes

# Cassandra: Check consistency achieved
# Enable tracing on a query:
cqlsh> TRACING ON;
cqlsh> CONSISTENCY QUORUM;
cqlsh> SELECT * FROM users WHERE id = 'alice';

# Tracing output shows:
# → Which nodes were contacted
# → Which node(s) had the latest data
# → Whether read-repair was triggered
# → Latency breakdown per replica

# Redis: Check replication lag
redis-cli -h master INFO replication
# Output includes:
#   slave0: ip=10.0.0.2, port=6379, state=online,
#   offset=1234567, lag=0
# lag=N means replica is N seconds behind
# If lag > 0 during a failover → data may be lost

# MongoDB: Check replication lag
mongosh --eval "rs.printSlaveReplicationInfo()"
# Shows lag for each secondary
# Also: db.adminCommand({replSetGetStatus: 1})

# DynamoDB: Can't directly measure lag, but you can
# compare reads:
aws dynamodb get-item \
  --table-name accounts \
  --key '{"user_id": {"S": "alice"}}' \
  --consistent-read  # strongly consistent

aws dynamodb get-item \
  --table-name accounts \
  --key '{"user_id": {"S": "alice"}}'
  # eventually consistent (default) — compare values
```

---

## SRE Diagnostic Toolkit

```
THE CORE SYMPTOM: "I wrote it, then couldn't read it" (or read an old value).
Almost every consistency bug reduces to replication lag + wrong read routing.

METRICS TO INSTRUMENT
  Replica lag (per replica):
    Postgres:  SELECT (now() - pg_last_xact_replay_timestamp()) AS lag;
    MySQL:     SHOW REPLICA STATUS -> Seconds_Behind_Source
    Aurora:    CloudWatch AuroraReplicaLag (ms)
    Mongo:     rs.printSecondaryReplicationInfo()
  Read-after-write violation rate (custom SLI):
    On critical flows, tag the write LSN/timestamp, then on the next read
    assert replica_replay >= write_lsn. Emit a counter when it is not.
  Staleness distribution:
    Histogram of (read_time - value_write_time) at the app layer.

COMMANDS / QUERIES
  Postgres primary vs replica LSN gap:
    SELECT client_addr,
           pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS bytes_behind
    FROM pg_stat_replication;
  Aurora: aurora_replica_status() / CloudWatch per-instance lag.
  Mongo causal session (guarantees read-your-writes across nodes):
    session.startTransaction(); ... afterClusterTime is tracked automatically.
  DynamoDB: use ConsistentRead=true for the read-your-writes path only.

DECISION TREE WHEN A STALE READ IS REPORTED
  1. Is the read hitting a replica? (check connection routing / reader endpoint)
  2. What is current replica lag vs the age of the write?
       lag > write_age  -> expected staleness; route this flow to primary
  3. Is lag itself anomalous? -> replica IO-bound, long-running query, or
     slot bloat (Week 5). Fix the lag, not just the routing.
  4. Is it truly concurrent (two writers)? -> this is a conflict, not lag;
     you need causal metadata / version vectors (Week 8), not primary reads.

LOG PATTERNS
  "row not found" immediately after successful insert  -> replica read of new row
  count/balance flips between refreshes                -> replica lag jitter
  monotonic read violation (value goes backward)       -> load-balanced replicas
                                                          with different lag
```

---

## Decision Framework

```
PRINCIPLE: Choose the WEAKEST model that still preserves the user-visible
invariant. Stronger models cost latency, availability, and throughput.

MAP THE INVARIANT -> THE MODEL

  ┌────────────────────────────┬──────────────────────┬─────────────────────┐
  │ User-visible requirement   │ Model needed         │ Mechanism           │
  ├────────────────────────────┼──────────────────────┼─────────────────────┤
  │ No double-spend, unique    │ Linearizable /       │ single-leader +     │
  │ constraint, inventory=0    │ serializable         │ primary reads, or   │
  │                            │                      │ consensus (Raft)    │
  ├────────────────────────────┼──────────────────────┼─────────────────────┤
  │ "See my own change now"    │ Read-your-writes     │ route user to       │
  │ (profile, order history)   │ (session)            │ primary or sticky   │
  │                            │                      │ replica; wait-for-  │
  │                            │                      │ LSN                 │
  ├────────────────────────────┼──────────────────────┼─────────────────────┤
  │ Reply never appears before │ Causal               │ version vectors /   │
  │ the message it answers     │                      │ causal tokens (Wk8) │
  ├────────────────────────────┼──────────────────────┼─────────────────────┤
  │ Value never goes backward  │ Monotonic reads      │ pin session to one  │
  │ on refresh                 │                      │ replica             │
  ├────────────────────────────┼──────────────────────┼─────────────────────┤
  │ Analytics, search, CDN,    │ Eventual             │ async replication,  │
  │ counters that converge     │                      │ read any replica    │
  └────────────────────────────┴──────────────────────┴─────────────────────┘

PER-FLOW, NOT PER-SYSTEM
  The same database can serve linearizable checkout AND eventual product
  browsing. Pick the model per endpoint. Do not make the whole app pay
  primary-read latency because ONE flow needs it.

COST LADDER (weak -> strong)
  eventual  <  monotonic/RYW  <  causal  <  linearizable/serializable
     cheap, HA                                    expensive, CP under partition

COMMON MISTAKES
  - "SERIALIZABLE everywhere" -> retry storms, throughput collapse.
  - Read-your-writes solved by reading primary for ALL reads -> primary melts.
  - Assuming replicas are strongly consistent because they are "in the same DB".
```

---

## Hands-On Exercises
```
╔═══════════════════════════════════════════════════════════════╗
║   EXERCISE 1: Observe Stale Reads (PostgreSQL)                ║
║                                                               ║
║   # Terminal 1 (primary):                                     ║
║   while true; do                                              ║
║     psql -h primary -c \                                      ║
║       "UPDATE test SET value = (SELECT value + 1              ║
║        FROM test WHERE id = 1) WHERE id = 1;"                 ║
║     sleep 0.01                                                ║
║   done                                                        ║
║                                                               ║
║   # Terminal 2 (replica — run simultaneously):                ║
║   while true; do                                              ║
║     psql -h replica -c "SELECT value FROM test WHERE id = 1;" ║
║     sleep 0.01                                                ║
║   done                                                        ║
║                                                               ║
║   # OBSERVE: The replica value LAGS behind the primary.       ║
║   # Sometimes it jumps forward (catches up to primary).       ║
║   # Sometimes it appears to go BACKWARD (you read from        ║
║   # replica during a lag spike, then it catches up,           ║
║   # then another lag spike makes it seem to go back).         ║
║   # This is eventual consistency in action.                   ║
║                                                               ║
║   # Now: Monitor the lag while this runs:                     ║
║   watch -n 0.5 "psql -h primary -c \"                         ║
║     SELECT now() - pg_last_xact_replay_timestamp()            ║
║     AS lag FROM pg_stat_replication;\""                       ║
╠═══════════════════════════════════════════════════════════════╣
║   EXERCISE 2: Break Read-Your-Writes, Then Fix It             ║
║                                                               ║
║   # Setup: PostgreSQL primary + async replica, load balancer  ║
║   # in front that round-robins reads.                         ║
║                                                               ║
║   # Step 1: Write to primary, immediately read from LB        ║
║   psql -h primary -c "UPDATE users SET name='NewName'         ║
║     WHERE id=1;"                                              ║
║   psql -h loadbalancer -c "SELECT name FROM users             ║
║     WHERE id=1;"                                              ║
║   # Repeat this rapidly. You'll occasionally see 'OldName'.   ║
║   # This is a read-your-writes violation.                     ║
║                                                               ║
║   # Step 2: Fix it — always read from primary after write     ║
║   psql -h primary -c "UPDATE users SET name='NewName2'        ║
║     WHERE id=1;"                                              ║
║   psql -h primary -c "SELECT name FROM users WHERE id=1;"     ║
║   # Always returns 'NewName2'. ✓                              ║
║                                                               ║
║   # Step 3: Smarter fix — read from replica only if fresh     ║
║   # Check replica freshness:                                  ║
║   psql -h primary -c "SELECT pg_current_wal_lsn();"           ║
║   # Returns: 0/15A2B8C0                                       ║
║   psql -h replica -c "SELECT pg_last_wal_replay_lsn();"       ║
║   # Returns: 0/15A2B8C0 → caught up, safe to read from here   ║
║   # Returns: 0/15A2A000 → behind, read from primary instead   ║
╠═══════════════════════════════════════════════════════════════╣
║   EXERCISE 3: Observe Monotonic Read Violations               ║
║                                                               ║
║   # Setup: 2 replicas at different replication lag            ║
║                                                               ║
║   # Rapidly alternate reads between replicas:                 ║
║   for i in $(seq 1 20); do                                    ║
║     if [ $((i % 2)) -eq 0 ]; then                             ║
║       psql -h replica1 -c "SELECT value FROM test             ║
║         WHERE id=1;" -t                                       ║
║     else                                                      ║
║       psql -h replica2 -c "SELECT value FROM test             ║
║         WHERE id=1;" -t                                       ║
║     fi                                                        ║
║   done                                                        ║
║                                                               ║
║   # While a writer is incrementing on primary:                ║
║   # You'll see values like: 105, 98, 106, 99, 107, 100...     ║
║   # The values BOUNCE — monotonic reads are violated.         ║
║   # replica1 is further ahead, replica2 is behind.            ║
║                                                               ║
║   # Fix: send all reads to ONE replica (sticky sessions).     ║
║   # The values only go up: 98, 99, 100, 101, 102...           ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Incident Scenario
```
╔══════════════════════════════════════════════════════════════╗
║   SCENARIO: Healthcare Patient Records Platform              ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   You're the on-call SRE for a healthcare platform used by   ║
║   hospitals across the US. The platform stores patient       ║
║   records, prescriptions, allergies, and lab results.        ║
║                                                              ║
║   ARCHITECTURE:                                              ║
║   → PostgreSQL primary (us-east-1) with 3 async replicas:    ║
║     → replica-1 (us-east-1, same AZ): ~2ms lag               ║
║     → replica-2 (us-east-1, different AZ): ~5ms lag          ║
║     → replica-3 (us-west-2, cross-region): ~60ms lag         ║
║                                                              ║
║   → Application load balancer distributes reads:             ║
║     → 40% to replica-1                                       ║
║     → 40% to replica-2                                       ║
║     → 20% to replica-3                                       ║
║     → Writes always go to primary                            ║
║     → NO session stickiness — round-robin per request        ║
║                                                              ║
║   → Redis cache (in each region):                            ║
║     → Caches patient records for 60 seconds                  ║
║     → Cache-aside pattern: read from cache, miss → read      ║
║       from DB replica, populate cache                        ║
║                                                              ║
║   → Prescription service (microservice):                     ║
║     → Receives new prescriptions                             ║
║     → Writes to PostgreSQL primary                           ║
║     → Publishes "prescription_created" event to Kafka        ║
║     → Allergy-check service consumes the event and           ║
║       reads the patient's allergy list to flag conflicts     ║
║                                                              ║
║   INCIDENT TIMELINE:                                         ║
║                                                              ║
║   09:00 — Normal operation. Everything green.                ║
║                                                              ║
║   09:15 — Dr. Martinez at Memorial Hospital (us-east-1):     ║
║     → Updates Patient #4521's allergy list:                  ║
║       ADDS "Penicillin — severe anaphylaxis"                 ║
║     → Write goes to primary → committed ✓                    ║
║     → Dr. Martinez refreshes the patient page                ║
║     → ALLERGY LIST SHOWS THE OLD VERSION (no penicillin)     ║
║     → Dr. Martinez refreshes again → now it shows correctly  ║
║     → "Weird, but it's there now"                            ║
║                                                              ║
║   09:22 — Dr. Chen at Pacific Medical (us-west-2):           ║
║     → Opens Patient #4521's record                           ║
║     → Allergy list does NOT show penicillin allergy          ║
║     → (replica-3 is 60ms behind, but patient's allergy       ║
║       was updated 7 minutes ago — should have replicated)    ║
║     → Actually: the allergy was replicated to replica-3      ║
║       within 100ms. But the Redis cache in us-west-2         ║
║       cached the OLD allergy list and has 47 seconds         ║
║       remaining on its 60-second TTL.                        ║
║     → Dr. Chen prescribes AMOXICILLIN (a penicillin-         ║
║       class antibiotic)                                      ║
║     → Prescription service writes to primary ✓               ║
║     → Publishes "prescription_created" event                 ║
║                                                              ║
║   09:22:05 — Allergy-check service:                          ║
║     → Consumes the "prescription_created" event              ║
║     → Reads Patient #4521's allergy list to check for        ║
║       conflicts                                              ║
║     → WHERE does it read from?                               ║
║     → It reads from the REDIS CACHE in us-east-1             ║
║     → The us-east-1 Redis cache was populated 45 seconds     ║
║       ago (before the allergy update)                        ║
║     → Cache returns: allergy list WITHOUT penicillin         ║
║     → Allergy check: NO CONFLICT FOUND ✓                     ║
║     → Prescription approved!                                 ║
║                                                              ║
║   09:23 — Patient #4521 receives amoxicillin.                ║
║     → Patient has a severe anaphylactic reaction.            ║
║     → Emergency response. Patient stabilized.                ║
║                                                              ║
║   09:45 — Incident declared after clinical staff reports     ║
║     the allergy information was not visible to Dr. Chen      ║
║     and was not caught by the allergy-check service.         ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

QUESTIONS:

Q1: Identify EVERY consistency model violation in this
    incident. For each, state:
    → Which specific consistency model was violated
    → The exact mechanism that caused the violation
    → The component responsible (DB, cache, application)

Q2: The allergy-check service is the LAST LINE OF DEFENSE
    against dangerous prescriptions. Its current architecture
    has a fundamental consistency flaw.

    a) Explain the flaw in consistency model terms.
    b) Design a fix that provides the MINIMUM consistency
       model required for patient safety. State explicitly
       which model you're targeting and why anything
       stronger is unnecessary.
    c) What consistency model does the fixed allergy-check
       service provide? Justify.

Q3: Dr. Martinez's experience at 09:15 (allergy shows
    old value on first refresh, correct value on second)
    is a classic consistency violation.

    a) Which TWO consistency model violations occurred?
    b) Give a fix that solves BOTH violations with one
       change. What consistency model does your fix provide?

Q4: The Redis cache in us-west-2 served stale allergy
    data to Dr. Chen 7 MINUTES after the update. The
    TTL is 60 seconds. Why wasn't the cache updated?

    Trace the exact data path that led to this stale read
    and explain when the cache was populated with stale data.

Q5: Design the incident's post-mortem action items.
    For each action item:
    → State which consistency anomaly it prevents
    → State the PACELC tradeoff it makes
    → State whether it's immediate (do this week) or
      strategic (next quarter)

    This is a HEALTHCARE platform. Regulatory context
    (HIPAA, patient safety) matters.
```

---

## Targeted Reading
```
╔══════════════════════════════════════════════════════════════╗
║   READ AFTER THIS LESSON:                                    ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   DDIA Chapter 5: "Replication"                              ║
║   → Pages 161-167 (Problems with Replication Lag)            ║
║     - "Reading Your Own Writes" (p. 162-164)                 ║
║     - "Monotonic Reads" (p. 164-165)                         ║
║     - "Consistent Prefix Reads" (p. 165-167)                 ║
║     These are the EXACT session guarantees we covered.       ║
║     Kleppmann's examples are different from mine — reading   ║
║     both reinforces the concepts from multiple angles.       ║
║                                                              ║
║   DDIA Chapter 9: "Consistency and Consensus"                ║
║   → Pages 321-332 (Linearizability)                          ║
║     - "What Makes a System Linearizable?" (p. 324-327)       ║
║     - "Relying on Linearizability" (p. 327-332)              ║
║       Focus on: locking, leader election, uniqueness         ║
║       constraints — these are the USE CASES for              ║
║       linearizability you need to cite in interviews.        ║
║                                                              ║
║   → Pages 332-338 (The Cost of Linearizability)              ║
║     This ties directly to Topic 1 (CAP). Kleppmann shows     ║
║     why linearizability is expensive and when you can        ║
║     accept weaker models. Read this AFTER Topic 1 and        ║
║     this topic — it synthesizes both.                        ║
║                                                              ║
║   TOTAL: ~25 pages from DDIA.                                ║
║   Read this material specifically looking for: "which        ║
║   anomaly does each consistency model prevent?"              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Ops Sim: Northstar Order History Time Travel

**Time box:** 30 minutes
**Severity:** P2
**Service / domain:** Order history replicas, Redis cache, checkout confirmation
**Northstar system:** Checkout OLTP, Session Redis

### Rules

1. Answer from memory; do not re-read the consistency models section mid-drill.
2. Write decisions in order (T+0 -> T+60).
3. Cite the anomaly and evidence for every claim.
4. Do not open the answer key until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  After purchase, "My Orders" sometimes shows no order, then shows it, then
  disappears on refresh. Checkout confirmation email was sent.

WHAT ON-CALL SEES:
  Write primary is healthy. Read replicas differ in lag, and cache invalidation
  only happens in the writer region.

BUSINESS CONSTRAINT:
  Do not duplicate orders to "fix" the display. Customer support needs a safe
  explanation and a way to verify the source of truth.
```

### 2. Telemetry pack

```text
METRICS:
  primary order writes p99=42ms; error_rate=0.02%
  replica-a lag=80ms; replica-b lag=4.8s; replica-c lag=11.2s
  order_history cache hit rate=88%; TTL=60s
  read router: round_robin across replicas, no session stickiness
  support contacts: "order disappeared" 310/hour

LOG LINES:
  order-api: created order_id=o-9921 lsn=8/B92A11 user=u-77
  order-history: read replica=replica-c last_lsn=8/B8FF00 required_lsn=8/B92A11
  cache: HIT order_history:u-77 populated_region=eu-west-1 age=47s

TRACE:
  checkout confirmation reads primary; My Orders reads Redis -> replica round-robin.
```

### 3. Config pack

```yaml
order_history:
  read_source: replicas_round_robin
  session_stickiness: false
  require_read_your_writes_lsn: false
  cache_ttl_seconds: 60

# wrong/dangerous client behavior
mobile:
  retry_purchase_if_order_missing: true
```

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | P2: users see order history time travel after confirmed purchase. | |
| T+5 | You find replica lag and no session stickiness. | |
| T+15 | Mobile proposes retrying purchase when order missing. | |
| T+60 | Display is stable for new orders; old cache entries remain. | |

### 5. Questions

**Q1 - Layer & root cause:** Which consistency guarantees are violated?

**Q2 - Evidence:** Which signals prove read-your-writes and monotonic-read issues?

**Q3 - Sequencing:** What do you change first to stop user harm without duplicating orders?

**Q4 - Bad fix gallery:** Why is retrying purchase dangerous? Why is reading all order history from primary potentially costly?

**Q5 - Capacity / blast radius:** If 40% of order-history reads move to primary, what DB and cache metrics must you check first?

**Q6 - Durable fix:** What LSN/session/caching contract prevents recurrence?

**Answer key:** [`../answers/Week-03-Distributed-Systems-Theory/Consistency Models Answers.md`](../answers/Week-03-Distributed-Systems-Theory/Consistency%20Models%20Answers.md)

---

## Key Takeaways
```
╔══════════════════════════════════════════════════════════════╗
║   5 THINGS TO REMEMBER IF YOU FORGET EVERYTHING ELSE         ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Consistency is a SPECTRUM, not a binary choice.         ║
║      Between linearizability and eventual consistency are    ║
║      causal consistency, read-your-writes, monotonic reads,  ║
║      monotonic writes, and consistent prefix reads. Each     ║
║      prevents a SPECIFIC anomaly at a SPECIFIC cost.         ║
║                                                              ║
║   2. Pick the WEAKEST model that prevents your anomaly.      ║
║      Stronger than needed = wasted latency.                  ║
║      Weaker than needed = bugs (or worse — patient harm).    ║
║      The decision framework: "what's the worst thing that    ║
║      happens if this read is stale?"                         ║
║                                                              ║
║   3. The four session guarantees are INDEPENDENT and         ║
║      COMPOSABLE. You can have read-your-writes without       ║
║      monotonic reads, or vice versa. Each addresses a        ║
║      different failure mode. Combine as needed.              ║
║                                                              ║
║   4. Most production consistency bugs come from CACHING      ║
║      and REPLICATION LAG, not from the database itself.      ║
║      The database might be perfectly consistent, but a       ║
║      60-second Redis TTL or a round-robin load balancer      ║
║      destroys your consistency guarantees at the             ║
║      application layer.                                      ║
║                                                              ║
║   5. Every system in the mapping table provides a DIFFERENT  ║
║      consistency model at different configuration levels.    ║
║      Cassandra at CL=ONE ≠ Cassandra at CL=QUORUM.           ║
║      DynamoDB default ≠ DynamoDB strongly consistent read.   ║
║      PostgreSQL reading from primary ≠ reading from replica. ║
║      The database doesn't have ONE consistency model —       ║
║      YOUR CONFIGURATION AND ACCESS PATTERN determine it.     ║
╚══════════════════════════════════════════════════════════════╝
```
> **Answer key (do not open until you attempt the scenario questions):**
> [`../answers/Week-03-Distributed-Systems-Theory/Consistency%20Models%20Answers.md`](../answers/Week-03-Distributed-Systems-Theory/Consistency%20Models%20Answers.md)
