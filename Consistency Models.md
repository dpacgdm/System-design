# Week 3, Topic 2: Consistency Models

---

## Step 1: Learning Objectives

```
┌──────────────────────────────────────────────────────────────┐
│  AFTER THIS TOPIC, YOU WILL BE ABLE TO:                      │
│                                                              │
│  1. Name and define every consistency model on the spectrum  │
│     from eventual consistency to linearizability             │
│                                                              │
│  2. Explain the precise ANOMALY that each model prevents     │
│     (each model exists because a specific bad thing happens  │
│     without it)                                              │
│                                                              │
│  3. Given a product requirement, select the MINIMUM          │
│     consistency model that satisfies it (stronger than       │
│     needed = wasted latency; weaker than needed = bugs)      │
│                                                              │
│  4. Identify which consistency model a real system           │
│     (PostgreSQL, Cassandra, DynamoDB, Redis) provides        │
│     at each configuration level                              │
│                                                              │
│  5. Diagnose a production bug as a consistency model         │
│     violation and prescribe the exact fix                    │
│                                                              │
│  6. Articulate in an interview why "eventual consistency"    │
│     is not one thing — it's a family of guarantees, and      │
│     the specific guarantee matters enormously                │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 2: Core Teaching

### Why This Topic Exists

```
In Topic 1 (CAP/PACELC), we established that the real 
tradeoff is Consistency vs Latency (or Availability 
during partitions).

But CAP defines consistency as LINEARIZABILITY — the 
strongest possible guarantee. And the alternative is 
often described as "eventual consistency."

This creates a FALSE BINARY:

  ┌────────────────────────────────────────────────┐
  │                                                │
  │  LINEARIZABILITY ◄──── huge gap ────► EVENTUAL │
  │  (perfect)                          (chaos?)   │
  │                                                │
  └────────────────────────────────────────────────┘

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
  
  Client A: ──write(X=1)──┐
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

  ┌───────────────────────────────────────────────────┐
  │ Social Media Comment Thread                       │
  │                                                   │
  │ Alice posts:  "I got the job!"         (op A)     │
  │ Bob reads Alice's post, then replies:             │
  │   "Congratulations!"                   (op B)     │
  │ Carol (hasn't seen anything) posts:               │
  │   "Nice weather today"                 (op C)     │
  │                                                   │
  │ CAUSAL RELATIONSHIPS:                             │
  │   A → B  (Bob's reply was caused by Alice's post) │
  │   C is CONCURRENT with A and B (no causal link)   │
  │                                                   │
  │ VALID orderings (causal consistency):             │
  │   [A, B, C]  ✓ (A before B, C anywhere)          │
  │   [A, C, B]  ✓ (A before B, C anywhere)          │
  │   [C, A, B]  ✓ (A before B, C anywhere)          │
  │                                                   │
  │ INVALID ordering:                                 │
  │   [B, A, C]  ✗ (B before A violates causality)   │
  │   If you see "Congratulations!" BEFORE "I got     │
  │   the job!" — that's nonsensical. Causal          │
  │   consistency prevents this.                      │
  └───────────────────────────────────────────────────┘

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

  ┌────────────────────────────────────────────────┐
  │                                                │
  │  Client A: write(X=5) → ACK                    │
  │  Client A: read(X) → returns 5 ✓ GUARANTEED    │
  │                                                │
  │  Client B: read(X) → returns 3 (old) ALLOWED   │
  │  (B hasn't seen A's write yet — that's OK)     │
  │                                                │
  └────────────────────────────────────────────────┘

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

  ┌────────────────────────────────────────────────┐
  │                                                │
  │  Client A: read(X) → returns 5                 │
  │  Client A: read(X) → returns 5 or 6 or 7...    │
  │                       BUT NEVER 4 or 3         │
  │                                                │
  │  Without monotonic reads:                      │
  │  Client A: read(X) → 5 (from replica-1)        │
  │  Client A: read(X) → 3 (from replica-2!)       │
  │            ↑ TIME WENT BACKWARDS               │
  │                                                │
  └────────────────────────────────────────────────┘

HOW THE VIOLATION HAPPENS:

  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │ Primary  │  │Replica 1 │  │Replica 2 │
  │ X=5      │  │ X=5      │  │ X=3      │
  │ (latest) │  │ (caught  │  │ (behind) │
  │          │  │  up)     │  │          │
  └──────────┘  └──────────┘  └──────────┘
  
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

  ┌────────────────────────────────────────────────┐
  │                                                │
  │  Client A: write(X=1)  then  write(X=2)        │
  │                                                │
  │  On ALL replicas:                              │
  │    X=1 is applied before X=2                   │
  │    Final state: X=2 on every replica ✓         │
  │                                                │
  │  WITHOUT monotonic writes:                     │
  │    Replica 1: receives X=1, then X=2 → X=2 ✓  │
  │    Replica 2: receives X=2, then X=1 → X=1 ✗  │
  │    Replicas DISAGREE on final state!           │
  │                                                │
  └────────────────────────────────────────────────┘

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

  ┌─────────────────────────────────────────────────┐
  │ Conversation:                                   │
  │                                                 │
  │ Alice (at T=1): "What time is the meeting?"     │
  │ Bob   (at T=2): "3pm"                           │
  │                                                 │
  │ CORRECT orderings a reader might see:           │
  │   []                              (seen nothing)│
  │   ["What time is the meeting?"]   (prefix of 1) │
  │   ["What time is the meeting?",                 │
  │    "3pm"]                         (full)        │
  │                                                 │
  │ VIOLATION:                                      │
  │   ["3pm"]  ← sees Bob's answer without          │
  │              Alice's question                   │
  │              "3pm" makes no sense in isolation! │
  │                                                 │
  │ ALSO A VIOLATION:                               │
  │   ["3pm", "What time is the meeting?"]          │
  │   Reordered — answer before question            │
  └─────────────────────────────────────────────────┘

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

  ┌────────────────────────────────────────────────┐
  │                                                │
  │  Write X=5 to primary                          │
  │                                                │
  │  T+0ms:   Primary=5, Replica1=3, Replica2=3    │
  │  T+50ms:  Primary=5, Replica1=5, Replica2=3    │
  │  T+120ms: Primary=5, Replica1=5, Replica2=5    │
  │                                                │
  │  At T+120ms: all replicas converged. ✓         │
  │  Between T+0 and T+120ms:                      │
  │    → You might read 3 or 5 depending on which  │
  │      replica you hit                           │
  │    → You might read 5, then 3 (time travel!)   │
  │    → You might never see 3 → 5 transition      │
  │      (jump straight from 3 to 7 if another     │
  │       write happened)                          │
  │                                                │
  │  ALL of these are valid under eventual         │
  │  consistency. There are NO ordering guarantees │
  │  during the convergence window.                │
  │                                                │
  └────────────────────────────────────────────────┘

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
┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
│LINEARIZ-   │ │SEQUENTIAL  │ │CAUSAL      │ │EVENTUAL    │
│ABILITY     │ │CONSISTENCY │ │CONSISTENCY │ │CONSISTENCY │
│            │ │            │ │            │ │            │
│All ops     │ │All ops in  │ │Causally    │ │Replicas    │
│ordered by  │ │some agreed │ │related ops │ │converge    │
│real time.  │ │order, per- │ │ordered.    │ │eventually. │
│One global  │ │client order│ │Concurrent  │ │No ordering │
│timeline.   │ │preserved.  │ │ops: any    │ │guarantee   │
│            │ │            │ │order OK.   │ │in between. │
└────────────┘ └────────────┘ └────────────┘ └────────────┘
       │                            │
       │    "SESSION GUARANTEES"    │
       │    (can be mixed/matched)  │
       │                            │
       │   ┌──────────────────┐     │
       │   │Read-your-writes  │     │
       │   │Monotonic reads   │     │
       │   │Monotonic writes  │     │
       │   │Consistent prefix │     │
       │   └──────────────────┘     │
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
┌────────────────┬──────────────────────────────────────────┐
│ SYSTEM         │ CONSISTENCY MODEL                        │
├────────────────┼──────────────────────────────────────────┤
│ PostgreSQL     │ LINEARIZABLE (single node)               │
│ (single node)  │ One copy of data. All reads see latest.  │
│                │ Trivially linearizable.                  │
├────────────────┼──────────────────────────────────────────┤
│ PostgreSQL     │ READ-YOUR-WRITES (if reading from        │
│ (primary +     │ primary after writing to primary)        │
│ async replica) │                                          │
│                │ EVENTUAL CONSISTENCY (reading from       │
│                │ replica — may be behind primary)         │
│                │                                          │
│                │ MONOTONIC READS if sticky to one replica │
│                │ (that replica only moves forward)        │
├────────────────┼──────────────────────────────────────────┤
│ PostgreSQL     │ LINEARIZABLE (for committed data)        │
│ (primary +     │ Sync replica has everything primary has. │
│ sync replica)  │ Reads from either node are consistent.   │
├────────────────┼──────────────────────────────────────────┤
│ Cassandra      │ EVENTUAL (CL=ONE for both R and W)       │
│ CL=ONE         │ No guarantees about what you read.       │
├────────────────┼──────────────────────────────────────────┤
│ Cassandra      │ LINEARIZABLE (for that key)              │
│ CL=QUORUM R+W  │ R + W > N guarantees overlap.            │
│ (RF=3)         │ At least one node in the read quorum     │
│                │ has the latest write.                    │
│                │ Read-repair returns the latest value.    │
├────────────────┼──────────────────────────────────────────┤
│ Cassandra      │ READ-YOUR-WRITES                         │
│ CL=ONE write   │ W=1, R=QUORUM → R+W = 1+2 = 3 = N        │
│ CL=QUORUM read │ Overlap of 1. The node you wrote to      │
│ (RF=3)         │ is in the read quorum.                   │
│                │ (Probabilistic — depends on RF and       │
│                │ node health)                             │
├────────────────┼──────────────────────────────────────────┤
│ DynamoDB       │ EVENTUAL (default)                       │
│ (default read) │ Reads may return stale data.             │
├────────────────┼──────────────────────────────────────────┤
│ DynamoDB       │ LINEARIZABLE (per-item)                  │
│ (strongly      │ Returns latest committed write.          │
│ consistent     │ Costs 2x the read capacity units.        │
│ read)          │ Only works against the leader.           │
├────────────────┼──────────────────────────────────────────┤
│ MongoDB        │ CAUSAL (within a causal session)         │
│ (causal        │ Reads reflect all writes that causally   │
│ session)       │ precede them in the session.             │
│                │ Monotonic reads + read-your-writes +     │
│                │ monotonic writes + consistent prefix.    │
├────────────────┼──────────────────────────────────────────┤
│ Redis Cluster  │ EVENTUAL (async replication)             │
│                │ Master→replica is async. Reads from      │
│                │ replica may be stale. After failover,    │
│                │ acknowledged writes may be lost.         │
├────────────────┼──────────────────────────────────────────┤
│ etcd / Raft    │ LINEARIZABLE                             │
│                │ All reads go through leader (or use      │
│                │ ReadIndex/LeaseRead for followers).      │
│                │ Raft guarantees linearizability.         │
├────────────────┼──────────────────────────────────────────┤
│ ZooKeeper      │ LINEARIZABLE (writes)                    │
│                │ SEQUENTIAL CONSISTENCY (reads from       │
│                │ followers — may be stale but monotonic)  │
│                │ sync() call upgrades a read to           │
│                │ linearizable.                            │
└────────────────┴──────────────────────────────────────────┘
```

### The Decision Framework for Interviews

```
When designing a system, apply this framework PER FEATURE:

STEP 1: Identify the WORST ANOMALY that would be acceptable.

  "If a user reads stale data for this feature, 
   what's the worst thing that happens?"

STEP 2: Pick the WEAKEST model that prevents unacceptable 
anomalies.

  ┌───────────────────────────────────┬───────────────────┐
  │ IF THIS ANOMALY IS UNACCEPTABLE:  │ YOU NEED AT LEAST:│
  ├───────────────────────────────────┼───────────────────┤
  │ Any stale read, ever              │ Linearizability   │
  │ (distributed locks, elections,    │                   │
  │  balance checks for transactions) │                   │
  ├───────────────────────────────────┼───────────────────┤
  │ Seeing effect before cause        │ Causal            │
  │ (reply before question,           │ Consistency       │
  │  child before parent)             │                   │
  ├───────────────────────────────────┼───────────────────┤
  │ User can't see their own writes   │ Read-your-writes  │
  │ (profile update invisible,        │                   │
  │  cart item disappears)            │                   │
  ├───────────────────────────────────┼───────────────────┤
  │ Value goes backward               │ Monotonic reads   │
  │ (balance jumps from $500 to $300  │                   │
  │  then back to $500)               │                   │
  ├───────────────────────────────────┼───────────────────┤
  │ Writes applied out of order       │ Monotonic writes  │
  │ (password reset reordered,        │                   │
  │  state machine violation)         │                   │
  ├───────────────────────────────────┼───────────────────┤
  │ None of the above is a problem    │ Eventual          │
  │ (like counts, view counts,        │ Consistency       │
  │  analytics, recommendations)      │                   │
  └───────────────────────────────────┴───────────────────┘

STEP 3: Choose the implementation that provides that model.

  Linearizable → etcd, ZK, Spanner, or "read from primary"
  Causal → MongoDB causal sessions, or vector clocks
  Read-your-writes → route to primary after write, or 
                      client-side timestamp tracking
  Monotonic reads → sticky sessions, or position tracking
  Eventual → any async-replicated database, default mode
```

---

## Step 3: Production Patterns & Failure Modes

```
┌──────────────────────────────────────────────────────────────┐
│  FAILURE MODE #1: THE VANISHING CART ITEM                    │
│                                                              │
│  System: E-commerce, PostgreSQL primary + 2 async replicas   │
│  Load balancer: round-robin across replicas for reads        │
│                                                              │
│  User adds item to cart (writes to primary).                 │
│  User's next page load → round-robin → hits replica-2.       │
│  Replica-2 is 200ms behind → cart appears EMPTY.             │
│  User adds the item again.                                   │
│  Next page load → hits replica-1 (caught up) → TWO items.    │
│  User is confused: "I only added one!"                       │
│                                                              │
│  Root cause: No read-your-writes guarantee.                  │
│                                                              │
│  Fix: After any cart write, set a cookie with the write      │
│  timestamp. For reads within 2 seconds of the cookie,        │
│  route to primary. After 2s, resume replica reads.           │
│                                                              │
│  # Nginx example:                                            │
│  map $cookie_last_write $backend {                           │
│    default replica_pool;                                     │
│    ~.     primary_if_recent;                                 │
│  }                                                           │
├──────────────────────────────────────────────────────────────┤
│  FAILURE MODE #2: THE FLICKERING DASHBOARD                   │
│                                                              │
│  System: Monitoring dashboard, reads from 3 replicas         │
│  Load balancer: round-robin across replicas                  │
│                                                              │
│  Dashboard auto-refreshes every 5 seconds.                   │
│  Refresh 1 → Replica-1 (caught up)   → 4,523 requests/s      │
│  Refresh 2 → Replica-3 (behind)      → 4,100 requests/s      │
│  Refresh 3 → Replica-1 (caught up)   → 4,530 requests/s      │
│  Refresh 4 → Replica-2 (slightly behind) → 4,480 requests/s  │
│                                                              │
│  The graph BOUNCES: 4523 → 4100 → 4530 → 4480                │
│  It looks like traffic is oscillating wildly.                │
│  An on-call SRE investigates a "traffic anomaly."            │
│  Hours wasted on a phantom problem.                          │
│                                                              │
│  Root cause: No monotonic reads guarantee.                   │
│  Each refresh hits a different replica at a different        │
│  replication lag, causing apparent backward movement.        │
│                                                              │
│  Fix: Sticky sessions for the dashboard.                     │
│  OR: Return the replica's WAL position with each response.   │
│  Next request includes it: "give me data at least this       │
│  fresh." Routes to appropriate replica.                      │
├──────────────────────────────────────────────────────────────┤
│  FAILURE MODE #3: THE PHANTOM NOTIFICATION                   │
│                                                              │
│  System: Social media. Sharded by user_id.                   │
│  Alice posts a photo (stored on shard A).                    │
│  System generates notifications for Alice's followers        │
│  (stored on shard B, C, D for different followers).          │
│                                                              │
│  Bob (shard B) gets a notification: "Alice posted a photo!"  │
│  Bob clicks the notification.                                │
│  Bob's request fetches the photo from shard A.               │
│  But shard A hasn't finished replicating/indexing the photo. │
│  Bob sees: "Photo not found."                                │
│  "But I JUST got a notification about it!"                   │
│                                                              │
│  Root cause: No consistent prefix reads.                     │
│  The notification (effect) is visible before the             │
│  photo (cause) is visible.                                   │
│                                                              │
│  Fix: Don't send the notification until the photo is         │
│  confirmed readable from all relevant replicas.              │
│  OR: When Bob clicks, if photo isn't found, retry from       │
│  primary with a "causal read" (read at the timestamp         │
│  of the write that created the notification).                │
├──────────────────────────────────────────────────────────────┤
│  FAILURE MODE #4: THE DOUBLE DEBIT                           │
│                                                              │
│  System: Payment service. Two replicas.                      │
│  User requests $100 transfer.                                │
│                                                              │
│  Primary: balance = $500. Debit $100. Balance = $400.        │
│  Primary ACKs the transfer.                                  │
│  Primary crashes BEFORE replicating to replica.              │
│                                                              │
│  Replica promoted. Balance = $500 (never got the update).    │
│  User sees $500. "Transfer didn't go through."               │
│  User requests $100 transfer AGAIN.                          │
│  New primary: balance = $500. Debit $100. Balance = $400.    │
│                                                              │
│  When old primary recovers (if it recovers):                 │
│  Its log says balance = $400 (after first debit).            │
│  But the new primary also says $400 (after second debit).    │
│  Two debits happened. User was charged $200, not $100.       │
│                                                              │
│  Root cause: Async replication (EL) for financial data.      │
│  The first debit was acknowledged but not replicated.        │
│  After failover, the system lost the first debit and         │
│  allowed a second one.                                       │
│                                                              │
│  Fix: Synchronous replication (EC) for financial data.       │
│  Write is not acknowledged until replica confirms.           │
│  If primary crashes after ACK, replica has the data.         │
│  After failover, balance = $400 (correct).                   │
│  User sees $400, knows transfer succeeded.                   │
│  No double debit.                                            │
│                                                              │
│  Additional fix: Idempotency keys.                           │
│  Each transfer has a unique ID. If the same ID is            │
│  submitted twice, the second one is a no-op.                 │
│  Even if the system DOES lose the first debit,               │
│  the retry with the same ID is detected and rejected.        │
│  Defense in depth: EC replication + idempotency.             │
└──────────────────────────────────────────────────────────────┘
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

## Step 4: Hands-On Exercises

```
┌──────────────────────────────────────────────────────────────┐
│  EXERCISE 1: Observe Stale Reads (PostgreSQL)                │
│                                                              │
│  # Terminal 1 (primary):                                     │
│  while true; do                                              │
│    psql -h primary -c \                                      │
│      "UPDATE test SET value = (SELECT value + 1              │
│       FROM test WHERE id = 1) WHERE id = 1;"                 │
│    sleep 0.01                                                │
│  done                                                        │
│                                                              │
│  # Terminal 2 (replica — run simultaneously):                │
│  while true; do                                              │
│    psql -h replica -c "SELECT value FROM test WHERE id = 1;" │
│    sleep 0.01                                                │
│  done                                                        │
│                                                              │
│  # OBSERVE: The replica value LAGS behind the primary.       │
│  # Sometimes it jumps forward (catches up to primary).       │
│  # Sometimes it appears to go BACKWARD (you read from        │
│  # replica during a lag spike, then it catches up,           │
│  # then another lag spike makes it seem to go back).         │
│  # This is eventual consistency in action.                   │
│                                                              │
│  # Now: Monitor the lag while this runs:                     │
│  watch -n 0.5 "psql -h primary -c \"                         │
│    SELECT now() - pg_last_xact_replay_timestamp()            │
│    AS lag FROM pg_stat_replication;\""                       │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 2: Break Read-Your-Writes, Then Fix It             │
│                                                              │
│  # Setup: PostgreSQL primary + async replica, load balancer  │
│  # in front that round-robins reads.                         │
│                                                              │
│  # Step 1: Write to primary, immediately read from LB        │
│  psql -h primary -c "UPDATE users SET name='NewName'         │
│    WHERE id=1;"                                              │
│  psql -h loadbalancer -c "SELECT name FROM users             │
│    WHERE id=1;"                                              │
│  # Repeat this rapidly. You'll occasionally see 'OldName'.   │
│  # This is a read-your-writes violation.                     │
│                                                              │
│  # Step 2: Fix it — always read from primary after write     │
│  psql -h primary -c "UPDATE users SET name='NewName2'        │
│    WHERE id=1;"                                              │
│  psql -h primary -c "SELECT name FROM users WHERE id=1;"     │
│  # Always returns 'NewName2'. ✓                              │
│                                                              │
│  # Step 3: Smarter fix — read from replica only if fresh     │
│  # Check replica freshness:                                  │
│  psql -h primary -c "SELECT pg_current_wal_lsn();"           │
│  # Returns: 0/15A2B8C0                                       │
│  psql -h replica -c "SELECT pg_last_wal_replay_lsn();"       │
│  # Returns: 0/15A2B8C0 → caught up, safe to read from here   │
│  # Returns: 0/15A2A000 → behind, read from primary instead   │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 3: Observe Monotonic Read Violations               │
│                                                              │
│  # Setup: 2 replicas at different replication lag            │
│                                                              │
│  # Rapidly alternate reads between replicas:                 │
│  for i in $(seq 1 20); do                                    │
│    if [ $((i % 2)) -eq 0 ]; then                             │
│      psql -h replica1 -c "SELECT value FROM test             │
│        WHERE id=1;" -t                                       │
│    else                                                      │
│      psql -h replica2 -c "SELECT value FROM test             │
│        WHERE id=1;" -t                                       │
│    fi                                                        │
│  done                                                        │
│                                                              │
│  # While a writer is incrementing on primary:                │
│  # You'll see values like: 105, 98, 106, 99, 107, 100...     │
│  # The values BOUNCE — monotonic reads are violated.         │
│  # replica1 is further ahead, replica2 is behind.            │
│                                                              │
│  # Fix: send all reads to ONE replica (sticky sessions).     │
│  # The values only go up: 98, 99, 100, 101, 102...           │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 5: SRE Scenario

```
┌──────────────────────────────────────────────────────────────┐
│  SCENARIO: Healthcare Patient Records Platform               │
│                                                              │
│  You're the on-call SRE for a healthcare platform used by    │
│  hospitals across the US. The platform stores patient        │
│  records, prescriptions, allergies, and lab results.         │
│                                                              │
│  ARCHITECTURE:                                               │
│  → PostgreSQL primary (us-east-1) with 3 async replicas:     │
│    → replica-1 (us-east-1, same AZ): ~2ms lag                │
│    → replica-2 (us-east-1, different AZ): ~5ms lag           │
│    → replica-3 (us-west-2, cross-region): ~60ms lag          │
│                                                              │
│  → Application load balancer distributes reads:              │
│    → 40% to replica-1                                        │
│    → 40% to replica-2                                        │
│    → 20% to replica-3                                        │
│    → Writes always go to primary                             │
│    → NO session stickiness — round-robin per request         │
│                                                              │
│  → Redis cache (in each region):                             │
│    → Caches patient records for 60 seconds                   │
│    → Cache-aside pattern: read from cache, miss → read       │
│      from DB replica, populate cache                         │
│                                                              │
│  → Prescription service (microservice):                      │
│    → Receives new prescriptions                              │
│    → Writes to PostgreSQL primary                            │
│    → Publishes "prescription_created" event to Kafka         │
│    → Allergy-check service consumes the event and            │
│      reads the patient's allergy list to flag conflicts      │
│                                                              │
│  INCIDENT TIMELINE:                                          │
│                                                              │
│  09:00 — Normal operation. Everything green.                 │
│                                                              │
│  09:15 — Dr. Martinez at Memorial Hospital (us-east-1):      │
│    → Updates Patient #4521's allergy list:                   │
│      ADDS "Penicillin — severe anaphylaxis"                  │
│    → Write goes to primary → committed ✓                     │
│    → Dr. Martinez refreshes the patient page                 │
│    → ALLERGY LIST SHOWS THE OLD VERSION (no penicillin)      │
│    → Dr. Martinez refreshes again → now it shows correctly   │
│    → "Weird, but it's there now"                             │
│                                                              │
│  09:22 — Dr. Chen at Pacific Medical (us-west-2):            │
│    → Opens Patient #4521's record                            │
│    → Allergy list does NOT show penicillin allergy           │
│    → (replica-3 is 60ms behind, but patient's allergy        │
│      was updated 7 minutes ago — should have replicated)     │
│    → Actually: the allergy was replicated to replica-3       │
│      within 100ms. But the Redis cache in us-west-2          │
│      cached the OLD allergy list and has 47 seconds          │
│      remaining on its 60-second TTL.                         │
│    → Dr. Chen prescribes AMOXICILLIN (a penicillin-          │
│      class antibiotic)                                       │
│    → Prescription service writes to primary ✓                │
│    → Publishes "prescription_created" event                  │
│                                                              │
│  09:22:05 — Allergy-check service:                           │
│    → Consumes the "prescription_created" event               │
│    → Reads Patient #4521's allergy list to check for         │
│      conflicts                                               │
│    → WHERE does it read from?                                │
│    → It reads from the REDIS CACHE in us-east-1              │
│    → The us-east-1 Redis cache was populated 45 seconds      │
│      ago (before the allergy update)                         │
│    → Cache returns: allergy list WITHOUT penicillin          │
│    → Allergy check: NO CONFLICT FOUND ✓                      │
│    → Prescription approved!                                  │
│                                                              │
│  09:23 — Patient #4521 receives amoxicillin.                 │
│    → Patient has a severe anaphylactic reaction.             │
│    → Emergency response. Patient stabilized.                 │
│                                                              │
│  09:45 — Incident declared after clinical staff reports      │
│    the allergy information was not visible to Dr. Chen       │
│    and was not caught by the allergy-check service.          │
│                                                              │
└──────────────────────────────────────────────────────────────┘

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

## Step 6: Targeted Reading

```
┌──────────────────────────────────────────────────────────────┐
│  READ AFTER THIS LESSON:                                     │
│                                                              │
│  DDIA Chapter 5: "Replication"                               │
│  → Pages 161-167 (Problems with Replication Lag)             │
│    - "Reading Your Own Writes" (p. 162-164)                  │
│    - "Monotonic Reads" (p. 164-165)                          │
│    - "Consistent Prefix Reads" (p. 165-167)                  │
│    These are the EXACT session guarantees we covered.        │
│    Kleppmann's examples are different from mine — reading    │
│    both reinforces the concepts from multiple angles.        │
│                                                              │
│  DDIA Chapter 9: "Consistency and Consensus"                 │
│  → Pages 321-332 (Linearizability)                           │
│    - "What Makes a System Linearizable?" (p. 324-327)        │
│    - "Relying on Linearizability" (p. 327-332)               │
│      Focus on: locking, leader election, uniqueness          │
│      constraints — these are the USE CASES for               │
│      linearizability you need to cite in interviews.         │
│                                                              │
│  → Pages 332-338 (The Cost of Linearizability)               │
│    This ties directly to Topic 1 (CAP). Kleppmann shows      │
│    why linearizability is expensive and when you can         │
│    accept weaker models. Read this AFTER Topic 1 and         │
│    this topic — it synthesizes both.                         │
│                                                              │
│  TOTAL: ~25 pages from DDIA.                                 │
│  Read this material specifically looking for: "which         │
│  anomaly does each consistency model prevent?"               │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 7: Key Takeaways

```
┌──────────────────────────────────────────────────────────────┐
│  5 THINGS TO REMEMBER IF YOU FORGET EVERYTHING ELSE          │
│                                                              │
│  1. Consistency is a SPECTRUM, not a binary choice.          │
│     Between linearizability and eventual consistency are     │
│     causal consistency, read-your-writes, monotonic reads,   │
│     monotonic writes, and consistent prefix reads. Each      │
│     prevents a SPECIFIC anomaly at a SPECIFIC cost.          │
│                                                              │
│  2. Pick the WEAKEST model that prevents your anomaly.       │
│     Stronger than needed = wasted latency.                   │
│     Weaker than needed = bugs (or worse — patient harm).     │
│     The decision framework: "what's the worst thing that     │
│     happens if this read is stale?"                          │
│                                                              │
│  3. The four session guarantees are INDEPENDENT and          │
│     COMPOSABLE. You can have read-your-writes without        │
│     monotonic reads, or vice versa. Each addresses a         │
│     different failure mode. Combine as needed.               │
│                                                              │
│  4. Most production consistency bugs come from CACHING       │
│     and REPLICATION LAG, not from the database itself.       │
│     The database might be perfectly consistent, but a        │
│     60-second Redis TTL or a round-robin load balancer       │
│     destroys your consistency guarantees at the              │
│     application layer.                                       │
│                                                              │
│  5. Every system in the mapping table provides a DIFFERENT   │
│     consistency model at different configuration levels.     │
│     Cassandra at CL=ONE ≠ Cassandra at CL=QUORUM.            │
│     DynamoDB default ≠ DynamoDB strongly consistent read.    │
│     PostgreSQL reading from primary ≠ reading from replica.  │
│     The database doesn't have ONE consistency model —        │
│     YOUR CONFIGURATION AND ACCESS PATTERN determine it.      │
└──────────────────────────────────────────────────────────────┘
```

# Incident Deep-Dive: Healthcare Consistency Failure — Patient Safety Event

---

## Question 1: Every Consistency Model Violation

### Violation 1: Read-Your-Writes (Dr. Martinez, 09:15)

**Consistency model violated:** Read-your-writes consistency — a user who performs a write should immediately see that write on subsequent reads.

**Exact mechanism:** Dr. Martinez writes the penicillin allergy to the PostgreSQL primary. The write commits. Dr. Martinez refreshes the patient page. The read is served from the **Redis cache in us-east-1**, which was populated BEFORE the allergy update and has not been invalidated. The cache returns the old allergy list (no penicillin). The write path does NOT invalidate or update the cache — it's pure cache-aside with no write-side invalidation.

**Component responsible:** Application architecture — cache-aside pattern with no write-through or invalidation-on-write. The application writes to PostgreSQL but does not touch Redis. Redis continues serving stale data until TTL expires.

```
TIMELINE:
  09:15:00.000 — Write: ADD penicillin allergy → Primary ✅
  09:15:01.000 — Read: GET allergy list → Redis cache HIT
                 → Returns OLD list (no penicillin) ❌
                 → Redis was populated before 09:15
                 → No invalidation happened on write
  
  Dr. Martinez just WROTE penicillin allergy but 
  CANNOT SEE her own write. Classic read-your-writes violation.
```

### Violation 2: Monotonic Reads (Dr. Martinez, 09:15)

**Consistency model violated:** Monotonic reads — once a user has seen a value, subsequent reads should never return an OLDER value.

**Exact mechanism:** Dr. Martinez's second refresh shows the correct allergy list (with penicillin). This means between the first and second refresh, either the Redis cache TTL expired (causing a cache miss → DB replica read → correct data) or the second request bypassed cache. The problem: the FIRST read returned OLD data, the SECOND read returned NEW data. If a third read were routed differently (e.g., back to a stale cache or a more-lagged replica), she could potentially see the old data again.

**Component responsible:** Round-robin load balancing with no session stickiness + Redis cache. Successive reads can hit different data sources with different staleness, producing non-monotonic results.

```
Read 1: Redis cache → old allergy list (no penicillin)
Read 2: Cache miss → replica-1 → new allergy list (penicillin ✅)
Read 3: (hypothetical) If another service re-populates Redis 
         cache with old data from a different source → old list again

The user's view of the data is NON-MONOTONIC:
  old → new → potentially old again
```

### Violation 3: Causal Consistency (Allergy-Check Service, 09:22:05)

**Consistency model violated:** Causal consistency — if event B is causally dependent on event A, then any process that sees B must also see A.

**Exact mechanism:** The prescription_created event exists BECAUSE Patient #4521 exists, who now HAS a penicillin allergy. The causal chain is:

```
CAUSAL CHAIN:
  Event A: Penicillin allergy added to Patient #4521 (09:15)
           ↓ (7 minutes later, same patient)
  Event B: Amoxicillin prescribed to Patient #4521 (09:22)
           ↓ (triggers)
  Event C: Allergy-check service processes prescription_created
           ↓ (reads allergy data)
  READ:    Allergy-check reads Patient #4521's allergy list
           → Gets list WITHOUT penicillin allergy

  The allergy-check service observes Event B (the prescription) 
  which is causally AFTER Event A (the allergy update).
  But when it reads the allergy list, it gets a version 
  from BEFORE Event A.

  This violates causal consistency: the service sees the 
  EFFECT (prescription for this patient) but not the CAUSE 
  (the allergy that should prevent this prescription).
```

**Component responsible:** The allergy-check service reads from the Redis cache (us-east-1) instead of the PostgreSQL primary. The cache has stale data from before the allergy update. The Kafka event carries no causal metadata (like a WAL LSN or version number) that could be used to ensure the allergy read reflects at least the state at the time of the prescription.

**This is the CRITICAL violation that caused patient harm.**

### Violation 4: Stale Cache Serving Safety-Critical Data (Dr. Chen, 09:22)

**Consistency model violated:** This is an excessive staleness violation in a context where eventual consistency is insufficient. The system provides eventual consistency (data will converge within TTL), but the application requires **strong consistency** for allergy data used in clinical decisions.

**Exact mechanism:** Dr. Chen in us-west-2 reads Patient #4521's allergy list. The Redis cache in us-west-2 has a cached copy of the allergy list from BEFORE the penicillin update, with 47 seconds remaining on its TTL. The cache returns the stale data. Dr. Chen sees no penicillin allergy and prescribes amoxicillin.

**Component responsible:** Redis cache-aside with 60-second TTL and no write-side invalidation. The allergy data was updated in PostgreSQL 7 minutes ago and replicated to all replicas, but the cache was never invalidated. A recent read re-populated the cache with stale data (traced in Q4).

```
SUMMARY OF ALL VIOLATIONS:

┌─────────────────────────┬────────────────────┬───────────────────┐
│ VIOLATION               │ COMPONENT          │ CONSEQUENCE       │
├─────────────────────────┼────────────────────┼───────────────────┤
│ Read-your-writes        │ Redis cache-aside  │ Dr. Martinez sees │
│ (Dr. Martinez)          │ (no invalidation)  │ old allergy list  │
│                         │                    │ after her update  │
├─────────────────────────┼────────────────────┼───────────────────┤
│ Monotonic reads         │ Round-robin LB +   │ Dr. Martinez sees │
│ (Dr. Martinez)          │ Redis cache        │ old then new data │
├─────────────────────────┼────────────────────┼───────────────────┤
│ Causal consistency      │ Allergy-check reads│ Safety check sees │
│ (Allergy-check service) │ from stale cache   │ pre-update data   │
│                         │ instead of primary │ for post-update   │
│                         │                    │ prescription      │
├─────────────────────────┼────────────────────┼───────────────────┤
│ Excessive staleness for │ Redis 60s TTL,     │ Dr. Chen sees no  │
│ safety-critical data    │ no invalidation    │ penicillin allergy│
│ (Dr. Chen)              │                    │ 7 min after update│
└─────────────────────────┴────────────────────┴───────────────────┘
```

---

## Question 2: The Allergy-Check Service — Flaw and Fix

### a) The Flaw in Consistency Model Terms

```
The allergy-check service provides the WEAKEST possible 
consistency for the MOST SAFETY-CRITICAL operation in the 
entire system.

The service processes a CAUSAL EVENT:
  "Prescription X was created for Patient Y"

This event is causally AFTER any prior updates to 
Patient Y's record — including allergy updates.

But the service reads from the Redis cache, which 
provides NO causal guarantees:
  → No read-your-writes (doesn't see recent writes)
  → No monotonic reads (may see different versions 
    on successive reads)
  → No causal ordering (doesn't know about the 
    relationship between the prescription event 
    and the allergy data)

The cache provides only EVENTUAL CONSISTENCY with a 
60-second staleness window. For a safety-critical 
check where "stale = potentially lethal," eventual 
consistency is categorically insufficient.

THE FUNDAMENTAL FLAW:
  The allergy-check service performs a CAUSAL READ 
  (reading data that must reflect all updates prior 
  to the triggering event) but uses an EVENTUALLY 
  CONSISTENT data source (Redis cache populated from 
  async replicas).

  It's reading from a source that has NO OBLIGATION 
  to reflect the state at the time of the triggering 
  event. The cache might be 1 second stale or 59 
  seconds stale — it makes no guarantees.
```

### b) Fix: Minimum Consistency Model for Patient Safety

**Target consistency model: Causal consistency — specifically, "read reflects all writes that causally precede the triggering event."**

```python
# The allergy-check service MUST read allergy data that 
# reflects ALL updates made BEFORE the prescription was created.

# The minimum guarantee needed:
#   "When checking allergies for prescription P,
#    the allergy data must include all updates that 
#    happened before P was created."
#
# This is CAUSAL CONSISTENCY: the read is causally 
# linked to the write (the prescription), and must 
# reflect all prior causal state.

# IMPLEMENTATION: Read from PostgreSQL PRIMARY, not cache.

async def check_allergies(prescription_event):
    patient_id = prescription_event['patient_id']
    drug = prescription_event['drug_name']
    
    # CRITICAL: Read ONLY from primary.
    # NOT from cache. NOT from replica.
    # The primary is the ONLY source guaranteed to have 
    # ALL committed writes, including the allergy update 
    # that may have happened moments before this prescription.
    
    allergies = await primary_db.fetch(
        "SELECT allergen, severity, drug_classes "
        "FROM patient_allergies "
        "WHERE patient_id = $1",
        patient_id
    )
    
    # Check for conflicts
    for allergy in allergies:
        if drug_conflicts_with_allergy(drug, allergy):
            await alert_prescriber(
                prescription_event, 
                allergy,
                severity='CRITICAL'
            )
            await block_prescription(prescription_event)
            return AllergyCheckResult.CONFLICT_FOUND
    
    return AllergyCheckResult.NO_CONFLICT
```

**Why causal consistency is the MINIMUM and why anything stronger is unnecessary:**

```
WHY CAUSAL IS SUFFICIENT:
  The allergy-check needs to see all allergy updates 
  that happened BEFORE the prescription was created.
  It does NOT need:
  
  → Linearizability: It doesn't need real-time ordering 
    of all operations across all patients. It only needs 
    to see THIS PATIENT's data as of the prescription time.
  
  → Serializability: It doesn't need to coordinate with 
    concurrent transactions on other patients. Only 
    Patient #4521's causal history matters.
  
  → Strong consistency across ALL reads: Other parts of 
    the system (display, history) can tolerate staleness. 
    Only the SAFETY CHECK needs causal consistency.

WHY EVENTUAL IS INSUFFICIENT:
  Eventual consistency says "you'll see the update... 
  eventually." For allergies, "eventually" could mean 
  60 seconds (cache TTL). In 60 seconds:
    → A prescription can be written, approved, dispensed
    → A patient can receive medication
    → An anaphylactic reaction can occur
  
  "Eventually" is too late when "now" determines 
  whether a patient lives or dies.

WHY READING FROM PRIMARY ACHIEVES CAUSAL:
  The prescription was WRITTEN to the primary.
  The allergy was WRITTEN to the primary.
  Both writes are committed on the primary.
  Reading from the primary guarantees we see BOTH.
  
  The primary's commit order IS the causal order:
    1. Allergy update committed (09:15)
    2. Prescription committed (09:22)
    3. Read allergies from primary → sees allergy (09:22:05)
  
  Causality is preserved because all writes and the 
  safety read happen against the SAME data source.
```

### c) Consistency Model of the Fixed Service

```
The fixed allergy-check service provides CAUSAL CONSISTENCY 
for the specific operation of allergy checking.

Specifically, it provides READ-YOUR-WRITES + CAUSAL:
  → Any allergy written to the primary BEFORE a 
    prescription is created will be visible when the 
    allergy-check reads for that prescription
  → This is guaranteed because both the write (allergy) 
    and the read (allergy check) go to the same node 
    (the primary), which provides a total order of all 
    committed transactions

The rest of the system (display reads, history, etc.) 
remains eventually consistent — we haven't changed 
their data paths. We've ONLY upgraded the consistency 
model for the one operation where staleness is dangerous.

This is PER-OPERATION CONSISTENCY SELECTION:
  → Safety-critical reads: causal consistency (primary)
  → Display reads: eventual consistency (replica + cache)
  → History reads: eventual consistency (replica)

PACELC:
  → Allergy check: PC/EC (sacrifice latency for consistency)
  → Display: PA/EL (sacrifice consistency for latency)
```

---

## Question 3: Dr. Martinez's Experience — Two Violations, One Fix

### a) The Two Consistency Model Violations

**Violation 1: Read-Your-Writes**

Dr. Martinez writes the penicillin allergy to the primary. She immediately refreshes. The read is served from the Redis cache, which was populated BEFORE her write and has not been invalidated. She does not see her own write. Read-your-writes requires that a process that performs a write W can subsequently read and see W reflected in the result. The cache broke this guarantee.

**Violation 2: Monotonic Reads**

Dr. Martinez's first read returns the OLD allergy list (no penicillin). Her second read returns the NEW allergy list (penicillin present). If a third read were routed to a different replica or hit a re-poisoned cache, she might see the old list again. Monotonic reads requires that once a process has seen a value at version V, all subsequent reads return V or newer — never older. With round-robin load balancing across replicas of varying staleness and a cache that may or may not be populated, successive reads can oscillate between old and new data.

```
Dr. Martinez's reads:
  Read 1: Redis HIT → old data (before her write)     ← sees V1
  Read 2: Redis MISS → replica → new data (her write) ← sees V2
  
  V1 → V2: OK so far (newer)
  
  But if Read 3 hits another service that repopulates 
  cache from a stale source, or a different replica 
  with lag: could see V1 again.
  
  Read-your-writes: violated at Read 1 (doesn't see own write)
  Monotonic reads: violated if Read 3 returns V1 after 
  seeing V2 at Read 2 (regression to older version)
```

### b) One Fix That Solves Both

**Fix: Write-through cache invalidation — on every write to PostgreSQL, immediately delete (or overwrite) the corresponding Redis cache key. Then route the writing user's subsequent reads to the primary for a brief window.**

```python
# Combined fix: write-through invalidation + 
# session-aware read routing

async def update_allergy(patient_id, allergy_data, session):
    # Step 1: Write to primary
    async with primary_db.transaction():
        await primary_db.execute(
            "INSERT INTO patient_allergies (patient_id, allergen, severity) "
            "VALUES ($1, $2, $3)",
            patient_id, allergy_data.allergen, allergy_data.severity
        )
    # Transaction COMMITTED
    
    # Step 2: Invalidate cache in ALL regions
    # Write-through: overwrite with correct data
    updated_allergies = await primary_db.fetch(
        "SELECT * FROM patient_allergies WHERE patient_id = $1",
        patient_id
    )
    
    # Invalidate us-east-1 Redis
    await redis_east.set(
        f"patient:{patient_id}:allergies",
        serialize(updated_allergies),
        ex=60
    )
    
    # Invalidate us-west-2 Redis (cross-region, async is OK 
    # because the safety-critical check reads from primary anyway)
    asyncio.create_task(
        redis_west.set(
            f"patient:{patient_id}:allergies",
            serialize(updated_allergies),
            ex=60
        )
    )
    
    # Step 3: Mark session for primary reads
    session['read_from_primary_until'] = time.time() + 30
    # For the next 30 seconds, THIS USER's reads go to primary


async def get_patient_allergies(patient_id, session):
    # Check if this user recently wrote (read-your-writes guarantee)
    if session.get('read_from_primary_until', 0) > time.time():
        # Route to primary — guarantees read-your-writes
        return await primary_db.fetch(
            "SELECT * FROM patient_allergies WHERE patient_id = $1",
            patient_id
        )
    
    # Normal path: cache-aside from replica
    cached = await redis.get(f"patient:{patient_id}:allergies")
    if cached:
        return deserialize(cached)
    
    # Cache miss: read from replica, populate cache
    allergies = await replica_db.fetch(
        "SELECT * FROM patient_allergies WHERE patient_id = $1",
        patient_id
    )
    await redis.set(f"patient:{patient_id}:allergies", 
                    serialize(allergies), ex=60)
    return allergies
```

**This fix provides READ-YOUR-WRITES + MONOTONIC READS consistency for the writing user:**

```
HOW IT SOLVES READ-YOUR-WRITES:
  → Dr. Martinez writes allergy → session flagged
  → Dr. Martinez reads → routed to PRIMARY
  → Primary has the committed write → she sees it ✅

HOW IT SOLVES MONOTONIC READS:
  → For 30 seconds after writing, ALL of Dr. Martinez's 
    reads go to PRIMARY (single, consistent source)
  → Primary provides total order → reads are monotonic ✅
  → After 30 seconds, reads return to replica/cache path
  → By then, all replicas and caches have converged
  → No regression to older versions

HOW WRITE-THROUGH HELPS OTHER USERS:
  → The cache is immediately overwritten with correct data
  → Other users (not Dr. Martinez) who read from cache 
    see the updated allergy list immediately
  → No 60-second staleness window
  → The combination of write-through + session routing 
    provides read-your-writes for the writer AND 
    reduces staleness for all other readers

CONSISTENCY MODEL PROVIDED:
  → For the writing user: read-your-writes + monotonic reads
  → For all other users: much stronger eventual consistency 
    (staleness reduced from 60s to near-zero via write-through)
```

---

## Question 4: Why Dr. Chen Saw Stale Data 7 Minutes After the Update

### Tracing the Exact Data Path

```
KEY FACTS:
  → Allergy updated at 09:15 on PostgreSQL primary
  → Replicated to replica-3 (us-west-2) within 100ms
  → Redis cache in us-west-2 has OLD allergy list at 09:22
  → Cache has 47 seconds remaining on 60-second TTL
  → Therefore: cache was populated at approximately 09:21:07
  → The data in the cache is from BEFORE the 09:15 update
  → ALL database replicas have the correct data since 09:15

QUESTION: How does the cache get populated at 09:21:07 
with data from before 09:15, when every replica has had 
the correct data for over 6 minutes?
```

### The Stale Cache Chain

```
The answer lies in HOW cache-aside populates the cache 
and WHERE the stale data originates.

STEP 1: Before 09:15
  → Patient #4521's allergy list (WITHOUT penicillin) is 
    cached in us-west-2 Redis with TTL=60s
  → At some point, this entry expires (TTL=60s)
  → Cache is empty for this key

STEP 2: 09:15:00 — Dr. Martinez updates the allergy
  → Write goes to primary ✅
  → Replicates to all replicas within 100ms ✅
  → NO CACHE INVALIDATION in any region ❌
  → But the old cache entry already expired, so 
    the cache is empty at this point

STEP 3: ~09:21:07 — Another read populates the cache with stale data
  → A process or user in us-west-2 (or routed through 
    us-west-2) reads Patient #4521's record
  → Redis cache: MISS (empty)
  → Application falls through to database read
  → The read is routed through the application's 
    load balancer which distributes reads:
    40% replica-1, 40% replica-2, 20% replica-3
  
  → ALL replicas have the correct data at this point
  → A direct replica read WOULD return correct data

  → BUT: the cache-aside implementation may read from 
    ANOTHER stale source. The critical question is 
    whether the read path goes:
    
    Path A: Redis MISS → DB replica → correct data ✅
    Path B: Redis MISS → another service → THAT service's 
            stale cache → stale data ❌

  The most likely explanation for stale data at 09:21:07:
  
  The us-west-2 application doesn't read from the DB 
  replica DIRECTLY on cache miss. It calls the PATIENT 
  SERVICE API, which is in us-east-1. The patient service 
  checks ITS Redis cache (us-east-1). The us-east-1 
  Redis cache ALSO has stale data (populated before 
  the allergy update, and returns it to the us-west-2 caller, which dutifully caches that stale response in its own regional Redis with a fresh 60-second TTL.

But that only pushes the question upstream: why does the us-east-1 Redis cache contain stale data at 09:21, when all DB replicas in us-east-1 have had the correct allergy list since 09:15:00.100?

The answer is **multi-layer caching with misaligned TTLs**. The patient service in us-east-1 doesn't go straight to the DB on a Redis miss. It has its own **application-level in-memory cache** (Hibernate L2 cache, Guava/Caffeine cache, or framework-level query memoization) sitting in front of the DB read:

```
THE FULL READ PATH (what cache-aside actually looks like 
in a real microservice architecture):

  ┌──────────────────────────────────────────────────────────┐
  │                                                          │
  │  Dr. Chen's browser (us-west-2)                          │
  │        │                                                 │
  │        ▼                                                 │
  │  us-west-2 App Server                                    │
  │        │                                                 │
  │        ├─► L1: us-west-2 Redis ── MISS (expired)         │
  │        │                                                 │
  │        ├─► Calls Patient Service API (us-east-1)         │
  │        │        │                                        │
  │        │        ├─► L2: us-east-1 Redis ── MISS          │
  │        │        │                                        │
  │        │        ├─► L3: In-memory cache ── HIT ❌        │
  │        │        │   (ORM/Hibernate L2 cache,             │
  │        │        │    TTL = 300s, populated at 09:17      │
  │        │        │    from a read BEFORE the allergy      │
  │        │        │    update reached this app instance)   │
  │        │        │                                        │
  │        │        │   Returns STALE allergy list           │
  │        │        │                                        │
  │        │        ├─► Populates us-east-1 Redis            │
  │        │        │   with stale data, TTL=60s             │
  │        │        │   (SET at 09:21:20, 45s remaining      │
  │        │        │    at 09:22:05)                        │
  │        │        │                                        │
  │        │        ▼                                        │
  │        │   Returns stale allergy list to caller          │
  │        │                                                 │
  │        ├─► Populates us-west-2 Redis                     │
  │        │   with stale data, TTL=60s                      │
  │        │   (SET at 09:21:07, 47s remaining at 09:22)     │
  │        │                                                 │
  │        ▼                                                 │
  │  Returns stale allergy list to Dr. Chen                  │
  │  → No penicillin allergy shown                           │
  │                                                          │
  └──────────────────────────────────────────────────────────┘
```

### The Staleness Amplification Effect

```
THREE CACHE LAYERS, THREE TTLs:

  Layer              │ TTL     │ Location
  ───────────────────┼─────────┼──────────────
  In-memory (L3)     │ 300s    │ Patient service process
  Redis us-east-1    │ 60s     │ Regional Redis
  Redis us-west-2    │ 60s     │ Regional Redis

THE PROBLEM: TTL misalignment creates a STALENESS CASCADE.

  09:15:00 — Allergy updated on primary. 
             Replicates to all replicas within 100ms.
             NO CACHE INVALIDATION AT ANY LAYER.

  09:15:00-09:17:00 — In-memory cache in patient service 
             still has old allergy list (TTL=300s, 
             populated at some time between 09:12-09:15).

  09:15:30 — us-east-1 Redis expires. Next request:
             → Redis MISS
             → In-memory cache HIT (stale) ❌
             → Redis RE-POPULATED with stale data, 
               fresh TTL=60s
             → The DB is NEVER QUERIED because the 
               in-memory cache intercepted first.

  09:16:30 — us-east-1 Redis expires AGAIN. Same thing:
             → Redis MISS → in-memory HIT (stale) 
             → Redis re-populated with stale data

  This cycle repeats EVERY 60 SECONDS as long as the 
  in-memory cache holds stale data.

  09:17:00 — If in-memory was populated at 09:12 with 
             TTL=300s, it expires at 09:17:00.
             Next request: in-memory MISS → DB replica 
             → CORRECT data → populates in-memory + Redis

  BUT: if the patient service runs MULTIPLE INSTANCES 
  (which it does — it's a microservice behind a load 
  balancer), each instance has its OWN in-memory cache.
  
  Instance A: in-memory populated at 09:12 → expires 09:17
  Instance B: in-memory populated at 09:14 → expires 09:19
  Instance C: in-memory populated at 09:16 → expires 09:21

  Instance C populated its in-memory cache at 09:16 by 
  reading from... Redis, which at that moment had stale 
  data (re-populated by Instance A's stale in-memory cache).

  So Instance C's in-memory cache is stale until 09:21.
  Any Redis miss between 09:19-09:21 that routes to 
  Instance C gets stale data.

  The us-west-2 cache miss at 09:21:07 was served by 
  Instance C (or similar) — still serving stale data 
  from its in-memory cache.

TIMELINE OF STALENESS PROPAGATION:

  09:15:00 ─ Allergy updated in DB
  09:15:00 ─ In-memory caches (instances A,B,C): ALL STALE
  09:15:30 ─ Redis expires, repopulated from stale in-memory
  09:16:30 ─ Redis expires, repopulated from stale in-memory
  09:17:00 ─ Instance A's in-memory expires → correct on miss
  09:17:30 ─ Redis expires. If next request hits Instance A:
             correct data. If it hits Instance B: stale.
  09:19:00 ─ Instance B expires → correct on miss
  09:21:00 ─ Instance C expires → correct on miss
  09:21:07 ─ us-west-2 request routes to Instance C 
             (just before or just after its expiry)
             → Gets stale data → populates us-west-2 Redis

  TOTAL STALENESS: 6+ minutes, despite 60-second Redis TTL.
  The in-memory cache TTL (300s) is the TRUE staleness 
  bound, multiplied by the number of service instances 
  with staggered population times.
```

### Why This Is Invisible in the Architecture Diagram

```
The architecture description says:
  "Cache-aside pattern: read from cache, miss → read 
   from DB replica, populate cache"

This describes the INTENDED behavior. In reality, 
the read path includes:
  → Framework-level caching (ORM, Hibernate L2)
  → Application-level memoization
  → Service-to-service calls with their own caching
  → Connection pooler caching (PgBouncer query caching)

NONE of these appear in architecture diagrams. They're 
INVISIBLE caching layers that silently extend staleness 
windows far beyond the Redis TTL.

This is why the stale read at 09:21:07 happened:
  → The 60-second TTL was a LIE. The actual staleness 
    bound was 300+ seconds (in-memory cache TTL × 
    number of service instances × cache-repopulation 
    cascading between layers).
  → The database had correct data within 100ms.
  → The caching infrastructure kept the old data alive 
    for 7 MINUTES.

THE LESSON:
  Your consistency guarantee is only as strong as your 
  WEAKEST (most stale) cache layer. If ANY layer in 
  the read path serves stale data, it poisons all 
  downstream caches with fresh TTLs on stale content.
  
  A 60-second Redis TTL means NOTHING if the upstream 
  source that repopulates Redis on a miss is itself 
  serving 5-minute-old data from an in-memory cache.
```

---

## Question 5: Post-Mortem Action Items

### Priority Framework (Healthcare-Specific)

```
PRIORITY HIERARCHY FOR HEALTHCARE PLATFORM:
  1. PATIENT SAFETY (prevent harm)
  2. REGULATORY COMPLIANCE (HIPAA, FDA, Joint Commission)
  3. CLINICAL WORKFLOW (doctors can trust the system)
  4. SYSTEM AVAILABILITY (uptime)
  5. PERFORMANCE (latency)

  Patient safety ALWAYS outranks performance.
  If the choice is "200ms slower" or "patient might 
  receive a lethal prescription," there is no choice.
```

---

### Action Item 1: Allergy-Check Service Reads From Primary [IMMEDIATE — This Week]

```
WHAT: The allergy-check service MUST read from the 
PostgreSQL PRIMARY for all allergy data used in 
safety checks. Remove Redis and replica from the 
safety-critical read path entirely.

WHICH ANOMALY IT PREVENTS:
  → Causal consistency violation. The allergy-check 
    processes a prescription_created event (which is 
    causally AFTER any prior allergy updates for that 
    patient). Reading from the primary guarantees the 
    allergy list reflects ALL committed writes — 
    including updates made moments before the prescription.
  → Also prevents ALL stale-cache poisoning for this 
    specific read path. The cache is bypassed entirely.

PACELC TRADEOFF:
  → Moves from PA/EL (available + low latency via cache/
    replica) to PC/EC (consistent reads from primary, 
    higher latency).
  → Latency impact: ~2ms (local primary read) instead 
    of ~0.5ms (Redis cache hit). Negligible.
  → For cross-region prescriptions (Dr. Chen in us-west-2):
    allergy check reads from us-east-1 primary, ~60ms.
    Still well within acceptable bounds for a safety check 
    that runs asynchronously after prescription creation.
  → During partition: allergy check BLOCKS. Prescription 
    is NOT approved until allergy data is confirmed. 
    FAIL CLOSED, not fail open. A doctor waiting 30 
    extra seconds for a prescription is infinitely 
    preferable to a patient in anaphylaxis.

IMPLEMENTATION:
  async def check_allergies(prescription_event):
      allergies = await primary_db.fetch(
          "SELECT allergen, severity, drug_classes "
          "FROM patient_allergies "
          "WHERE patient_id = $1",
          prescription_event['patient_id']
      )
      # ... conflict check logic ...

  # If primary is UNREACHABLE:
  #   DO NOT fall back to cache or replica.
  #   BLOCK the prescription. Return PENDING.
  #   Alert on-call. Alert prescribing physician.
  #   "Allergy check temporarily unavailable. 
  #    Prescription held for manual review."

TIMELINE: Implement and deploy THIS WEEK. This is the 
single change that would have prevented the incident.
```

---

### Action Item 2: Cache Invalidation on Safety-Critical Data Writes [IMMEDIATE — This Week]

```
WHAT: When ANY allergy data is written to PostgreSQL, 
immediately invalidate the corresponding cache entries 
in ALL regions AND all caching layers (Redis + in-memory).

WHICH ANOMALY IT PREVENTS:
  → Read-your-writes violation (Dr. Martinez's experience).
    After writing an allergy, the writing clinician 
    immediately sees the updated allergy list.
  → Staleness amplification across cache layers. 
    Invalidation breaks the cascade where stale in-memory 
    caches repopulate stale Redis caches indefinitely.

PACELC TRADEOFF:
  → Moves display reads from EL (tolerate staleness for 
    speed) toward EC (fresher data, slightly more latency 
    on cache misses after invalidation).
  → Impact: slightly higher DB read load on cache misses 
    immediately after allergy updates. Allergy updates 
    are LOW FREQUENCY (a patient's allergies change rarely), 
    so the additional DB load is negligible.

IMPLEMENTATION:
  async def update_allergy(patient_id, allergy_data):
      async with primary_db.transaction():
          await primary_db.execute(
              "INSERT INTO patient_allergies (...) VALUES (...)",
              ...
          )
      # Transaction committed.
      
      # Invalidate ALL cache layers, ALL regions:
      cache_key = f"patient:{patient_id}:allergies"
      
      # L1: Invalidate local in-memory cache
      local_cache.invalidate(cache_key)
      
      # L2: Invalidate Redis in all regions
      await redis_east.delete(cache_key)
      await redis_west.delete(cache_key)  # cross-region, async OK
      
      # L3: Broadcast invalidation to all service instances
      # (so their in-memory caches are also cleared)
      await kafka_produce(
          topic="cache_invalidation",
          key=cache_key,
          value={"action": "invalidate", "timestamp": time.time()}
      )
      
      # Each patient service instance consumes this topic 
      # and evicts the key from its in-memory cache.

  # WHY KAFKA FOR BROADCAST:
  # There are N instances of the patient service, each 
  # with its own in-memory cache. You can't HTTP-call 
  # each one. A Kafka topic with a consumer group where 
  # each instance is its OWN consumer group (broadcast 
  # pattern) ensures ALL instances see the invalidation.

TIMELINE: Implement THIS WEEK alongside Action Item 1.
```

---

### Action Item 3: Fail-Closed Circuit Breaker on Allergy Check [IMMEDIATE — This Week]

```
WHAT: If the allergy-check service cannot confirm allergy 
safety (primary unreachable, timeout, error), the 
prescription is BLOCKED, not approved. 

The current implicit behavior is FAIL-OPEN: if the 
allergy check reads stale data that shows no conflict, 
it approves the prescription. This is equivalent to 
fail-open — absence of evidence is treated as evidence 
of absence.

WHICH ANOMALY IT PREVENTS:
  → Any future consistency violation (cache staleness, 
    replication lag, network partition) that causes the 
    allergy check to read incomplete data. Even if 
    Actions 1 and 2 fail or regress, the circuit breaker 
    catches it.
  → Defense in depth: this is the safety net BEHIND 
    the consistency fixes.

PACELC TRADEOFF:
  → Explicitly chooses PC over PA for prescription 
    approval. During a partition or degradation, 
    prescriptions are DELAYED rather than approved 
    with incomplete safety data.
  → Availability impact: prescriptions queue up during 
    outages. Clinicians see "pending safety review" 
    rather than instant approval.
  → This is the CORRECT tradeoff for healthcare. 
    No regulator will fault you for delaying a 
    prescription during an outage. Every regulator 
    will fault you for approving a lethal prescription 
    because your cache was stale.

IMPLEMENTATION:
  async def check_allergies(prescription_event):
      try:
          allergies = await asyncio.wait_for(
              primary_db.fetch(
                  "SELECT * FROM patient_allergies "
                  "WHERE patient_id = $1",
                  prescription_event['patient_id']
              ),
              timeout=5.0  # 5-second hard timeout
          )
      except (asyncio.TimeoutError, ConnectionError) as e:
          # FAIL CLOSED: do NOT approve the prescription
          await hold_prescription(
              prescription_event,
              reason="ALLERGY_CHECK_UNAVAILABLE",
              alert=True
          )
          await page_oncall(
              severity="P2",
              message=f"Allergy check failed for Rx "
                      f"{prescription_event['id']}: {e}"
          )
          return AllergyCheckResult.HELD_FOR_REVIEW
      
      # ... normal conflict check logic ...

TIMELINE: Implement THIS WEEK. Deploy with Actions 1 & 2.
```

---

### Action Item 4: Classify ALL Patient Data by Required Consistency Model [IMMEDIATE — Next 2 Weeks]

```
WHAT: Audit every data type in the platform. Assign each 
one a consistency model based on the consequence of 
staleness. Encode this classification in the application's 
data access layer so the correct read path is enforced 
automatically.

WHICH ANOMALY IT PREVENTS:
  → The ROOT CAUSE of this incident: treating all patient 
    data with the same (weak) consistency model. Allergies, 
    prescriptions, and lab results were all cached the same 
    way. They have radically different staleness tolerances.

PACELC TRADEOFF:
  → Per-feature PACELC. Each data type gets the cheapest 
    consistency model that is safe for its use case.

CLASSIFICATION TABLE:

┌──────────────────────┬────────────────────┬───────────────────┐
│ DATA TYPE            │ CONSISTENCY MODEL  │ READ PATH         │
├──────────────────────┼────────────────────┼───────────────────┤
│ Allergies (for       │ LINEARIZABLE       │ Primary only.     │
│ prescription check)  │                    │ No cache. Ever.   │
├──────────────────────┼────────────────────┼───────────────────┤
│ Allergies (for       │ READ-YOUR-WRITES   │ Primary for 30s   │
│ clinician display)   │ + MONOTONIC READS  │ after write, then │
│                      │                    │ cache with 10s    │
│                      │                    │ TTL.              │
├──────────────────────┼────────────────────┼───────────────────┤
│ Current medications  │ LINEARIZABLE       │ Primary only for  │
│ (for interaction     │                    │ drug interaction  │
│ checks)              │                    │ checks.           │
├──────────────────────┼────────────────────┼───────────────────┤
│ Current medications  │ READ-YOUR-WRITES   │ Same as allergy   │
│ (for display)        │                    │ display.          │
├──────────────────────┼────────────────────┼───────────────────┤
│ Lab results          │ READ-YOUR-WRITES   │ Primary for 30s   │
│                      │                    │ after write, then │
│                      │                    │ replica. Cache    │
│                      │                    │ with 30s TTL.     │
├──────────────────────┼────────────────────┼───────────────────┤
│ Patient demographics │ EVENTUAL           │ Cache-aside,      │
│ (name, address, DOB) │ CONSISTENCY        │ 300s TTL. Stale   │
│                      │                    │ reads are harmless│
├──────────────────────┼────────────────────┼───────────────────┤
│ Appointment history  │ EVENTUAL           │ Cache-aside,      │
│                      │ CONSISTENCY        │ 120s TTL.         │
├──────────────────────┼────────────────────┼───────────────────┤
│ Audit log            │ MONOTONIC WRITES   │ Write to primary  │
│                      │                    │ with sequence     │
│                      │                    │ numbers. Append   │
│                      │                    │ only.             │
└──────────────────────┴────────────────────┴───────────────────┘

IMPLEMENTATION (data access layer enforcement):

  class PatientDataAccess:
      CONSISTENCY_POLICY = {
          'allergies_safety_check':  ReadPolicy.PRIMARY_ONLY,
          'allergies_display':       ReadPolicy.READ_YOUR_WRITES,
          'medications_interaction': ReadPolicy.PRIMARY_ONLY,
          'medications_display':     ReadPolicy.READ_YOUR_WRITES,
          'lab_results':             ReadPolicy.READ_YOUR_WRITES,
          'demographics':            ReadPolicy.EVENTUAL,
          'appointments':            ReadPolicy.EVENTUAL,
      }

      async def read(self, data_type, patient_id, session=None):
          policy = self.CONSISTENCY_POLICY[data_type]
          
          if policy == ReadPolicy.PRIMARY_ONLY:
              return await self.primary_db.fetch(...)
          
          elif policy == ReadPolicy.READ_YOUR_WRITES:
              if session and session.wrote_recently(data_type, patient_id):
                  return await self.primary_db.fetch(...)
              cached = await self.redis.get(...)
              if cached:
                  return cached
              return await self.replica_db.fetch(...)
          
          elif policy == ReadPolicy.EVENTUAL:
              cached = await self.redis.get(...)
              if cached:
                  return cached
              return await self.replica_db.fetch(...)

  # The policy is ENFORCED at the data access layer.
  # Individual services cannot bypass it.
  # A developer calling read('allergies_safety_check') 
  # gets PRIMARY_ONLY whether they know it or not.

TIMELINE: Classification complete within 2 weeks. 
Data access layer enforcement within 4 weeks.
```

---

### Action Item 5: Audit and Eliminate Hidden Cache Layers [STRATEGIC — Next Quarter]

```
WHAT: Discover and document EVERY caching layer in the 
read path for safety-critical data. This includes layers 
that don't appear in architecture diagrams:
  → ORM/Hibernate L2 caches
  → Application-level memoization (Guava, Caffeine, lru_cache)
  → Connection pooler query caching (PgBouncer)
  → HTTP response caches (Varnish, CDN edge caches)
  → Service mesh caches (Envoy, Istio response caching)
  → DNS caching (stale service discovery)

This incident's Q4 root cause was a HIDDEN cache layer 
(in-memory ORM cache with 300s TTL) that repeatedly 
repopulated Redis with stale data. The 60-second Redis 
TTL was meaningless because the UPSTREAM source feeding 
Redis was itself stale for 5+ minutes.

WHICH ANOMALY IT PREVENTS:
  → Staleness amplification cascade. A single hidden 
    cache layer with a long TTL poisons ALL downstream 
    caches. Every time a downstream cache expires and 
    re-fetches, it gets stale data from the upstream 
    hidden cache and resets its own TTL — creating an 
    indefinite staleness loop.
  → The general principle: your ACTUAL staleness bound 
    is not min(TTL across layers). It's 
    max(TTL across layers) × number of layers, because 
    each layer can re-poison the one below it.

PACELC TRADEOFF:
  → Removing hidden caches from safety-critical paths 
    increases DB load slightly (more cache misses reach 
    the database). This is an EL → EC shift: accepting 
    higher latency on cache misses for consistent reads.
  → For non-safety data: hidden caches can remain. 
    Demographics cached in ORM for 300s is fine.
  → The tradeoff is SELECTIVE: only safety-critical 
    data paths are de-cached.

IMPLEMENTATION:

  # Step 1: DISCOVER hidden caches
  # Add read-path tracing to safety-critical queries.
  # Every layer that serves data logs its source:

  async def traced_read(data_type, patient_id):
      trace = ReadTrace(data_type, patient_id)
      
      # Layer 1: Redis
      cached = await redis.get(key)
      if cached:
          trace.log("REDIS_HIT", age=cached.age)
          return cached, trace
      trace.log("REDIS_MISS")
      
      # Layer 2: In-memory
      mem_cached = local_cache.get(key)
      if mem_cached:
          trace.log("INMEMORY_HIT", age=mem_cached.age)
          # ← THIS is the hidden layer. If this fires 
          #   for safety-critical data, it's a finding.
          return mem_cached, trace
      trace.log("INMEMORY_MISS")
      
      # Layer 3: DB
      result = await db.fetch(...)
      trace.log("DB_READ", replica=db.current_host())
      return result, trace

  # Emit traces to observability platform.
  # Alert on: INMEMORY_HIT for any safety-critical data type.
  # That means a hidden cache is serving safety data.

  # Step 2: DISABLE hidden caches for safety-critical data
  
  # Hibernate/SQLAlchemy: disable L2 cache for specific entities
  @Entity
  @Cache(usage = CacheConcurrencyStrategy.NONE)  // Hibernate
  public class PatientAllergy { ... }

  # Or in SQLAlchemy:
  class PatientAllergy(Base):
      __tablename__ = 'patient_allergies'
      # Expire on access — no ORM-level caching
      __mapper_args__ = {"eager_defaults": True}

  # PgBouncer: if using query caching, exclude safety tables
  # (PgBouncer doesn't cache queries by default, but some 
  # connection poolers like ProxySQL do)

  # Step 3: VALIDATE with integration test
  
  async def test_no_hidden_caches_on_safety_reads():
      """Write allergy, immediately read via safety path.
         Verify the read hits the DB, not any cache."""
      
      patient_id = create_test_patient()
      
      # Write allergy
      await update_allergy(patient_id, "Penicillin", "severe")
      
      # Read via safety path with tracing
      result, trace = await traced_read(
          'allergies_safety_check', patient_id
      )
      
      # Verify: must NOT hit any cache layer
      assert "REDIS_HIT" not in trace.layers
      assert "INMEMORY_HIT" not in trace.layers
      assert trace.layers[-1] == "DB_READ"
      assert trace.db_host == PRIMARY_HOST
      
      # Verify: correct data returned
      assert "Penicillin" in [a.allergen for a in result]

TIMELINE: Audit within 4 weeks. Remediation within 8 weeks. 
Integration tests within 2 weeks (can run before full audit 
to catch the known ORM cache issue immediately).
```

---

### Action Item 6: Prescription-Allergy Causal Linking via Event Metadata [STRATEGIC — Next Quarter]

```
WHAT: When the prescription service publishes a 
"prescription_created" event to Kafka, include the 
PRIMARY's WAL LSN (Log Sequence Number) at the time 
the prescription was committed. The allergy-check 
service uses this LSN to guarantee its read reflects 
at least that point in the database's history.

This is defense-in-depth BEHIND Action Item 1 (read 
from primary). Even if the allergy-check service is 
later refactored to read from a replica (performance 
optimization by a future engineer who doesn't know 
the history), the LSN check prevents stale reads.

WHICH ANOMALY IT PREVENTS:
  → Causal consistency violation. The LSN is a CAUSAL 
    MARKER: "this event was created when the database 
    was at position X. Any read that informs a decision 
    about this event must be at position ≥ X."
  → Prevents future regressions. If someone changes the 
    allergy-check service to read from a replica for 
    performance, the LSN check will reject reads from 
    replicas that haven't reached the required position.

PACELC TRADEOFF:
  → No latency impact when reading from primary (primary 
    is always at or beyond any committed LSN).
  → If reading from replica: adds a staleness check. 
    If replica is behind the LSN → reject and retry 
    from primary. This is a SAFETY VALVE, not a 
    performance path.

IMPLEMENTATION:

  # Prescription service — writing the event:
  async def create_prescription(prescription_data):
      async with primary_db.transaction() as tx:
          rx_id = await tx.execute(
              "INSERT INTO prescriptions (...) VALUES (...) "
              "RETURNING id", ...
          )
          # Get the WAL position AFTER the commit
          wal_lsn = await tx.fetchval(
              "SELECT pg_current_wal_lsn()::text"
          )
      
      # Include LSN in the Kafka event
      await kafka_produce(
          topic="prescription_created",
          key=str(rx_id),
          value={
              "prescription_id": rx_id,
              "patient_id": prescription_data.patient_id,
              "drug": prescription_data.drug_name,
              "causal_lsn": wal_lsn,  # ← CAUSAL MARKER
              "created_at": time.time()
          }
      )

  # Allergy-check service — consuming the event:
  async def check_allergies(prescription_event):
      required_lsn = prescription_event['causal_lsn']
      
      # Verify read source is at or past the causal LSN
      current_lsn = await primary_db.fetchval(
          "SELECT pg_current_wal_lsn()::text"
      )
      # Primary is always >= any committed LSN, so this 
      # always passes. But if this is ever changed to 
      # read from a replica:
      #
      # replica_lsn = await replica_db.fetchval(
      #     "SELECT pg_last_wal_replay_lsn()::text"
      # )
      # if replica_lsn < required_lsn:
      #     # Replica is behind — FAIL SAFE, read from primary
      #     log.warn("Replica behind causal LSN, routing to primary")
      #     return await read_from_primary(prescription_event)
      
      allergies = await primary_db.fetch(
          "SELECT * FROM patient_allergies "
          "WHERE patient_id = $1",
          prescription_event['patient_id']
      )
      # ... conflict check ...

TIMELINE: Design and implement next quarter. Requires 
Kafka schema evolution (adding causal_lsn field to 
prescription events) and consumer-side LSN validation.
```

---
```
### Action Item 7: Regulatory Notification and Clinical Follow-Up [IMMEDIATE — This Week]

```
WHAT: Notify regulatory bodies and initiate clinical 
review of the incident. This is not an engineering 
action item — it's a COMPLIANCE action item that 
engineering supports with data.

WHICH ANOMALY IT PREVENTS:
  → Not a consistency anomaly. This is a REGULATORY 
    requirement. Healthcare platforms in the US operate 
    under:
    → HIPAA (patient data integrity)
    → FDA 21 CFR Part 11 (electronic records)
    → Joint Commission patient safety event reporting
    → State medical board notification requirements

REQUIRED ACTIONS:

  a) PATIENT SAFETY EVENT REPORT:
     → File with the hospital's Patient Safety Officer 
       within 24 hours of discovery
     → Include: timeline, root cause, patient outcome, 
       corrective actions
     → Joint Commission requires reporting of "sentinel 
       events" — an anaphylactic reaction from a 
       system failure qualifies

  b) AFFECTED PATIENT AUDIT:
     → Query: How many OTHER prescriptions were approved 
       by the allergy-check service while reading from 
       stale cache?
     
     SELECT p.id, p.patient_id, p.drug_name, 
            p.created_at, p.approved_at,
            a.allergen, a.severity, a.updated_at
     FROM prescriptions p
     JOIN patient_allergies a 
       ON p.patient_id = a.patient_id
     WHERE a.updated_at < p.created_at
       AND a.updated_at > p.created_at - INTERVAL '10 minutes'
       AND drug_conflicts_with_allergy(p.drug_name, a.allergen)
       AND p.safety_check_result = 'NO_CONFLICT'
       AND p.created_at > NOW() - INTERVAL '90 days';
     
     -- This finds prescriptions where:
     -- 1. An allergy was added BEFORE the prescription
     -- 2. The drug conflicts with that allergy
     -- 3. The safety check said "no conflict" 
     --    (meaning it read stale data)
     -- 4. Within the last 90 days

     → For EACH result: clinical pharmacist review
     → For any that were dispensed: patient outreach
     → This is not optional — it's legally required

  c) ENGINEERING DATA PACKAGE FOR LEGAL:
     → Preserve all logs, Kafka events, Redis cache 
       dumps, PostgreSQL WAL positions for the incident 
       window
     → Litigation hold: do NOT delete or rotate these logs
     → Provide to legal team with chain of custody

PACELC TRADEOFF: N/A — this is regulatory compliance, 
not a distributed systems tradeoff.

TIMELINE: Begin IMMEDIATELY. Regulatory notification 
within 24 hours. Patient audit within 48 hours. 
Engineering data package within 24 hours.
```

---

### Action Item 8: Automated Safety Circuit Breaker on Cache Staleness [STRATEGIC — Next Quarter]

```
WHAT: Implement automated monitoring that detects when 
ANY cache layer is serving safety-critical data that 
is older than a defined threshold. When triggered, 
automatically bypass all caches for safety-critical 
reads.

WHICH ANOMALY IT PREVENTS:
  → Future staleness events caused by cache 
    misconfiguration, cache poisoning, replication 
    lag spikes, or new hidden cache layers introduced 
    by future code changes.
  → This is the AUTOMATION OVER HUMAN JUDGMENT principle: 
    the system protects itself rather than waiting for 
    a human to notice stale data.

PACELC TRADEOFF:
  → Normal operation: no impact (caches serve fresh data, 
    circuit breaker stays open).
  → Degraded operation: automatically shifts safety reads 
    to PC/EC (primary-only, bypassing all caches). 
    Higher latency on safety reads, but guaranteed 
    consistency.
  → This is identical in principle to the trading 
    platform's replication lag → auto-disable trades 
    from Topic 1.

IMPLEMENTATION:

  # Prometheus metrics from the traced_read (Action Item 5):
  
  - alert: SafetyDataStaleness
    expr: |
      max(safety_read_cache_age_seconds{
        data_type=~"allergies_safety_check|medications_interaction"
      }) > 1
    for: 10s
    labels:
      severity: critical
      automation: safety_cache_bypass
    annotations:
      runbook: |
        AUTOMATED ACTION:
        1. Set feature flag SAFETY_READS_BYPASS_CACHE=true
        2. All safety-critical reads route to primary
        3. Page on-call SRE (P2)
        4. Page clinical safety officer
        
  # Thresholds:
  #   > 1s stale on safety data:  AUTO-BYPASS all caches
  #   > 5s stale on clinical display data: WARNING to SRE
  #   > 60s stale on any clinical data: P2 page

  # The feature flag is checked in the data access layer:
  async def read(self, data_type, patient_id, session=None):
      policy = self.CONSISTENCY_POLICY[data_type]
      
      # Override: if safety bypass is active, ALL safety 
      # reads go to primary regardless of normal policy
      if (feature_flags.get('SAFETY_READS_BYPASS_CACHE') 
          and data_type in SAFETY_CRITICAL_TYPES):
          return await self.primary_db.fetch(...)
      
      # ... normal policy-based routing ...

TIMELINE: Design next month. Implement next quarter. 
Requires Action Item 5 (tracing) to be in place first 
so the staleness metrics exist.
```

---

### Action Items Summary

```
┌──────┬─────────────────────────────────┬────────────┬────────────┐
│  #   │ ACTION                          │ TIMELINE   │ PREVENTS   │
├──────┼─────────────────────────────────┼────────────┼────────────┤
│  1   │ Allergy-check reads from        │ THIS WEEK  │ Causal     │
│      │ primary only                    │            │ violation  │
├──────┼─────────────────────────────────┼────────────┼────────────┤
│  2   │ Cache invalidation on           │ THIS WEEK  │ Read-your- │
│      │ safety-critical writes          │            │ writes +   │
│      │                                 │            │ staleness  │
│      │                                 │            │ cascade    │
├──────┼─────────────────────────────────┼────────────┼────────────┤
│  3   │ Fail-closed circuit breaker     │ THIS WEEK  │ All future │
│      │ on allergy check                │            │ stale      │
│      │                                 │            │ approvals  │
├──────┼─────────────────────────────────┼────────────┼────────────┤
│  4   │ Per-data-type consistency       │ 2-4 WEEKS  │ Root cause │
│      │ classification + enforcement    │            │ (uniform   │
│      │                                 │            │ weak       │
│      │                                 │            │ consistency│
│      │                                 │            │ for all    │
│      │                                 │            │ data)      │
├──────┼─────────────────────────────────┼────────────┼────────────┤
│  5   │ Audit and eliminate hidden      │ 4-8 WEEKS  │ Staleness  │
│      │ cache layers                    │            │ amplific-  │
│      │                                 │            │ ation      │
│      │                                 │            │ cascade    │
├──────┼─────────────────────────────────┼────────────┼────────────┤
│  6   │ Causal LSN linking in           │ NEXT QTR   │ Future     │
│      │ Kafka events                    │            │ causal     │
│      │                                 │            │ regression │
├──────┼─────────────────────────────────┼────────────┼────────────┤
│  7   │ Regulatory notification +       │ IMMEDIATE  │ Legal/     │
│      │ affected patient audit          │ (24-48 hrs)│ regulatory │
│      │                                 │            │ exposure   │
├──────┼─────────────────────────────────┼────────────┼────────────┤
│  8   │ Automated safety circuit        │ NEXT QTR   │ Future     │
│      │ breaker on cache staleness      │            │ staleness  │
│      │                                 │            │ events     │
└──────┴─────────────────────────────────┴────────────┴────────────┘

DEFENSE IN DEPTH (how these layer):

  Layer 1: Primary-only reads for safety checks (#1)
    → Eliminates the most common consistency violation path
  
  Layer 2: Cache invalidation on writes (#2)
    → Reduces staleness for ALL readers, not just safety checks
  
  Layer 3: Fail-closed circuit breaker (#3)
    → If Layer 1 fails (primary unreachable), prescriptions 
      are held rather than approved with incomplete data
  
  Layer 4: Data classification enforcement (#4)
    → Prevents future developers from accidentally routing 
      safety reads through weak-consistency paths
  
  Layer 5: Hidden cache elimination (#5)
    → Removes the staleness amplification cascade that 
      made a 60-second TTL produce 7-minute staleness
  
  Layer 6: Causal LSN markers (#6)
    → Even if someone changes the read path later, the 
      LSN check catches stale reads at the data level
  
  Layer 7: Automated staleness detection (#8)
    → Catches any NEW consistency violation path that 
      future code changes might introduce

  If ANY SINGLE LAYER fails, the others still protect 
  patient safety. An attacker (or an unlucky bug) would 
  need to bypass ALL SEVEN layers to cause another 
  stale-data prescription approval.
```

---

That completes all five questions. Ready for evaluation. 🎯
