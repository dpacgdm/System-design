# Week 3, Topic 1: CAP Theorem + PACELC

---

## Learning Objectives
```
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. State the CAP theorem precisely and explain why         ║
║      it's actually a theorem (proven, not an opinion)        ║
║                                                              ║
║   2. Destroy the three most common misconceptions about      ║
║      CAP that appear in interviews and blog posts            ║
║                                                              ║
║   3. Explain why "choosing P" is not a choice — and what     ║
║      the REAL choice is                                      ║
║                                                              ║
║   4. Classify any database or system as CP or AP with        ║
║      precise reasoning (not just from a memorized table)     ║
║                                                              ║
║   5. Explain PACELC — the extension that captures what       ║
║      CAP misses — and why it's more useful for real          ║
║      system design decisions                                 ║
║                                                              ║
║   6. Make consistency vs availability tradeoff decisions     ║
║      for a given system with justified reasoning that        ║
║      references both CAP and PACELC                          ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Pick any two of C, A, P at design time"             ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Partitions happen — P is not optional in distributed           ║
║   systems. The real choice during a partition is between C and A:       ║
║   reject requests (CP) or return potentially stale data (AP).           ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "CP systems are always available when healthy"       ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. CP means rejecting requests when a quorum cannot be            ║
║   reached — including during partitions AND leader elections.           ║
║   etcd, ZooKeeper, and CockroachDB go unavailable to preserve           ║
║   consistency. That is the point.                                       ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "AP means data is randomly wrong"                    ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. AP systems return responses during partitions — often          ║
║   stale but not random. Dynamo-style systems use vector clocks,         ║
║   quorums, and conflict resolution. The tradeoff is staleness           ║
║   bounds, not chaos.                                                    ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Network partitions are rare edge cases"             ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. GC pauses, switch failures, AZ outages, and misconfigured      ║
║   security groups cause partitions regularly. CAP describes             ║
║   behavior during these events — which you WILL experience in prod.     ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "CAP is outdated — modern systems beat it"           ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. PACELC extends CAP (latency vs consistency when no             ║
║   partition). Systems tune along the spectrum — they do not             ║
║   violate the theorem. Claiming "we have all three" redefines           ║
║   the terms.                                                            ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "MongoDB is CP, Cassandra is AP — memorize it"       ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Both are tunable. MongoDB with majority write concern is       ║
║   CP-ish; Cassandra with LOCAL_ONE is AP-ish. Classification            ║
║   depends on configuration, consistency level, and failure mode         ║
║   — not the logo on the box.                                            ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

### What CAP Actually Says

```
CAP THEOREM (Brewer's Theorem, 2000, proven by Gilbert & Lynch 2002):

  In a distributed data store, when a NETWORK PARTITION
  occurs, you can guarantee AT MOST TWO of:

    C — Consistency (linearizability)
    A — Availability (every non-failing node returns a response)
    P — Partition Tolerance (system continues despite
        network partitions between nodes)

THIS IS A PROVEN THEOREM, NOT A DESIGN GUIDELINE.

  It's not "pick any two." It's a mathematical proof that
  shows you CANNOT have all three simultaneously during
  a network partition. It's as rigorous as any theorem
  in mathematics.
```

Let me define each property precisely, because **every word matters** and most explanations get them subtly wrong:

#### C — Consistency (Linearizability)

```
CAP's "consistency" is NOT the same as ACID's "consistency."
This causes massive confusion. Let me be precise.

CAP CONSISTENCY = LINEARIZABILITY:
  Every read receives the most recent write or an error.

  More precisely: after a write completes successfully,
  ALL subsequent reads (from ANY node) MUST return that
  written value (or a later value).

  The system behaves AS IF there is only one copy of
  the data, even though there are multiple replicas.

EXAMPLE:

  LINEARIZABLE (CAP-consistent):

    Client A writes: X = 5     (to Node 1, propagated to Node 2)
    Write acknowledged ✓
    Client B reads X from Node 2 → MUST return 5

    There is NO window after the write is acknowledged
    where any client can read the old value.

  NOT LINEARIZABLE:

    Client A writes: X = 5     (to Node 1)
    Write acknowledged ✓
    Client B reads X from Node 2 → returns 3 (old value!)

    This happens because Node 2 hasn't received the
    update yet. The system has REPLICAS that are out of
    sync. This violates linearizability.

THIS IS A VERY STRONG GUARANTEE.

  It's stronger than "eventual consistency" (where B
  would EVENTUALLY see 5, but might temporarily see 3).

  It's stronger than "read-your-writes" (where only
  Client A is guaranteed to see their own write).

  Linearizability means ALL clients, reading from ANY
  node, see a single consistent timeline of operations.
```

#### A — Availability

```
CAP AVAILABILITY:
  Every request received by a non-failing node MUST
  result in a response (not an error).

  "Non-failing" is important: if a node has crashed,
  it's not expected to respond. But every node that
  is UP must return a valid response to every request.

  There is NO timeout specified. CAP availability means
  "eventually responds" — but in practice, we care about
  responding in reasonable time.

WHAT THIS MEANS IN PRACTICE:

  AVAILABLE: Client sends GET to Node 2 → Node 2 returns
  data (possibly stale, but returns SOMETHING).

  NOT AVAILABLE: Client sends GET to Node 2 → Node 2
  returns an error: "Cannot serve request, partition detected."

  Returning an error = unavailable (in CAP terms).
  Returning stale data = available (in CAP terms).

  This distinction matters enormously.
```

#### P — Partition Tolerance

```
NETWORK PARTITION:
  A break in communication between nodes. Some nodes
  can't talk to other nodes. Messages are lost or
  delayed indefinitely.

  ╔══════════════════════════════════════════════════════════════╗
  ║  Node 1 │── ✕ ──→│ Node 2                                    ║
  ║         │← ✕ ────│                                           ║
  ╚══════════════════════════════════════════════════════════════╝
        │                 │
  Both nodes are UP and can receive client requests.
  But they CANNOT communicate with each other.
  Messages between them are dropped.

PARTITION TOLERANCE:
  The system continues to operate (however it chooses
  to handle it) despite arbitrary message loss between
  nodes.

HERE'S THE CRITICAL INSIGHT THAT MOST PEOPLE MISS:

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   PARTITION TOLERANCE IS NOT OPTIONAL.                       ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   In a distributed system, network partitions                ║
  ║   WILL happen. It's not a question of if, but when.          ║
  ║                                                              ║
  ║   - Network cables get cut                                   ║
  ║   - Switches fail                                            ║
  ║   - Cloud availability zones lose connectivity               ║
  ║   - GC pauses make a node unreachable for seconds            ║
  ║   - Firewall misconfigurations block traffic                 ║
  ║                                                              ║
  ║   You MUST tolerate partitions because they                  ║
  ║   are a FACT OF DISTRIBUTED SYSTEMS, not a                   ║
  ║   design choice.                                             ║
  ║                                                              ║
  ║   Choosing "CA" (consistency + availability,                 ║
  ║   no partition tolerance) means your system                  ║
  ║   BREAKS when a partition occurs.                            ║
  ║                                                              ║
  ║   In a single-machine database (PostgreSQL on                ║
  ║   one server), there are no network partitions               ║
  ║   because there's no network between nodes.                  ║
  ║   So "CA" only applies to non-distributed systems.           ║
  ║                                                              ║
  ║   THE MOMENT YOU DISTRIBUTE DATA ACROSS NODES,               ║
  ║   P IS NOT OPTIONAL. IT'S MANDATORY.                         ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝
```

### The REAL Choice: CP vs AP

```
Since P is mandatory for any distributed system,
the real question is:

  WHEN A PARTITION OCCURS, DO YOU CHOOSE:

  CP — Consistency + Partition Tolerance
       "During a partition, refuse to serve requests
        that might return stale data."
       → Nodes that can't confirm they have the latest
         data return ERRORS instead of stale data.
       → System is CONSISTENT but UNAVAILABLE
         (for affected partitions).

  AP — Availability + Partition Tolerance
       "During a partition, serve requests even if the
        data might be stale."
       → Nodes return whatever data they have, even if
         they can't confirm it's the latest.
       → System is AVAILABLE but INCONSISTENT
         (for affected partitions).

VISUALIZING THE PARTITION:

  ╔══════════════════════════════════════════════════════════════╗
  ║  Data Center│── ── ── ✕ ── ──│ Data Center                   ║
  ║   East      │                │  West                         ║
  ║             │                │                               ║
  ║   Node 1    │                │  Node 2                       ║
  ║   X = 5     │                │  X = 3                        ║
  ║   (latest)  │                │  (stale)                      ║
  ╚══════════════════════════════════════════════════════════════╝
       │                              │
    Client A                       Client B
    writes X=5                     reads X

  CP BEHAVIOR:
    Client B reads from Node 2.
    Node 2 knows it can't confirm it has the latest data
    (it can't reach Node 1 to check).
    Node 2 returns: ERROR — "Cannot guarantee consistency."
    Client B gets no data (unavailable) but is protected
    from stale reads.

  AP BEHAVIOR:
    Client B reads from Node 2.
    Node 2 knows it might have stale data but serves
    the request anyway.
    Node 2 returns: X = 3 (stale but available).
    Client B gets data quickly but it might be wrong.

THE TRADEOFF IN PLAIN ENGLISH:

  CP: "I'd rather give you NO answer than a WRONG answer."
      → Banking: "Sorry, can't check your balance right now"
         is better than showing $10,000 when you have $0.

  AP: "I'd rather give you a POSSIBLY WRONG answer than
       NO answer at all."
      → Social media: Showing a like count of 4,523 when
         it's actually 4,527 is better than showing nothing.
```

### The Three Common Misconceptions

```
╔═══════════════════════════════════════════════════════════════╗
║   MISCONCEPTION #1: "CAP means pick any 2 of 3"               ║
║                                                               ║
║   WRONG. You don't "pick" partition tolerance.                ║
║   Partitions HAPPEN. You must handle them.                    ║
║                                                               ║
║   The real choice is: when a partition happens,               ║
║   do you sacrifice Consistency or Availability?               ║
║                                                               ║
║   There's no "CA" distributed database.                       ║
║   A single-node PostgreSQL is "CA" — but it's not             ║
║   distributed, so CAP doesn't apply.                          ║
║                                                               ║
║   The moment you add a second node, you must deal             ║
║   with partitions.                                            ║
╠═══════════════════════════════════════════════════════════════╣
║   MISCONCEPTION #2: "Consistency and availability are binary" ║
║                                                               ║
║   WRONG. CAP's definitions are binary (for the proof),        ║
║   but real systems exist on a SPECTRUM.                       ║
║                                                               ║
║   You don't have to choose "100% consistent always" or        ║
║   "100% available always."                                    ║
║                                                               ║
║   Real systems make NUANCED choices:                          ║
║   → Consistent for writes, eventually consistent for reads    ║
║   → Consistent for financial data, available for social data  ║
║   → Consistent within a region, eventually consistent         ║
║     across regions                                            ║
║   → Consistent for the first 5 seconds, then serve stale      ║
║                                                               ║
║   Cassandra's tunable consistency (ONE, QUORUM, ALL) is       ║
║   a perfect example: you choose PER QUERY where you           ║
║   fall on the spectrum.                                       ║
╠═══════════════════════════════════════════════════════════════╣
║   MISCONCEPTION #3: "CAP applies all the time"                ║
║                                                               ║
║   WRONG. CAP only applies DURING a partition.                 ║
║                                                               ║
║   When the network is healthy (no partition):                 ║
║   → You CAN have consistency AND availability!                ║
║   → This is normal operation for most systems                 ║
║   → There's no tradeoff to make                               ║
║                                                               ║
║   CAP says: "During a partition, you must sacrifice one."     ║
║   It does NOT say: "You can never have both."                 ║
║                                                               ║
║   This is why CAP alone is insufficient for system design.    ║
║   It tells you nothing about the system's behavior during     ║
║   NORMAL operation (no partition). And normal operation       ║
║   is 99.9%+ of the time.                                      ║
║                                                               ║
║   THIS IS EXACTLY WHY PACELC EXISTS.                          ║
╚═══════════════════════════════════════════════════════════════╝
```

---

### PACELC — The Extension That Matters

```
CAP's limitation: It only describes behavior DURING partitions.
But partitions are rare. Most of the time, the system is
operating normally with full connectivity between nodes.

WHAT TRADEOFFS EXIST WHEN THERE'S NO PARTITION?

PACELC (proposed by Daniel Abadi, 2012):

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   IF (Partition) THEN                                        ║
  ║     → Choose Availability (A) or Consistency (C)             ║
  ║                                                              ║
  ║   ELSE (no partition, normal operation)                      ║
  ║     → Choose Latency (L) or Consistency (C)                  ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

  P-A-C-E-L-C:
    P  → Partition?
    A  → Availability
    C  → Consistency
    E  → Else (no partition)
    L  → Latency
    C  → Consistency

THE "ELSE" CLAUSE IS WHERE THE REAL ENGINEERING HAPPENS.

When there's NO partition (99.9% of the time):
  → Do you make writes FAST by not waiting for all
    replicas to confirm? (choose Latency)
  → Or do you make writes SLOW by waiting for all
    replicas to confirm? (choose Consistency)

  Low latency: Write to primary → ACK immediately →
  replicate asynchronously.
  → Fast, but replicas are briefly stale.

  Strong consistency: Write to primary → wait for N
  replicas to confirm → then ACK.
  → Slow, but all replicas are consistent.

THIS IS THE TRADEOFF YOU MAKE EVERY DAY.
CAP only kicks in during rare partitions.
PACELC describes what happens ALL THE TIME.
```

#### How PACELC Classifies Real Systems

```
╔═══════════════════════════════════════════════════════════════╗
║  SYSTEM           │ During Partition │ Else (Normal)          ║
║                   │ (P → A or C?)    │ (E → L or C?)          ║
╠═══════════════════════════════════════════════════════════════╣
║  PostgreSQL       │ PC               │ EC                     ║
║  (sync replica)   │ Refuses writes   │ Waits for replica      ║
║                   │ if replica is    │ ACK before             ║
║                   │ unreachable      │ confirming commit      ║
║                   │                  │ → Higher latency,      ║
║                   │                  │   strong consistency   ║
╠═══════════════════════════════════════════════════════════════╣
║  PostgreSQL       │ PC               │ EL                     ║
║  (async replica)  │ Primary serves,  │ Write ACKed before     ║
║                   │ replica becomes  │ replica has the data   ║
║                   │ inconsistent.    │ → Lower latency,       ║
║                   │ (Actually: PA    │   eventual consistency ║
║                   │ at primary, PC   │                        ║
║                   │ if reading from  │   (This is what most   ║
║                   │ replica)         │    production PG uses) ║
╠═══════════════════════════════════════════════════════════════╣
║  Cassandra        │ PA               │ EL                     ║
║  (CL=ONE)         │ Serves requests  │ Returns after writing  ║
║                   │ from any live    │ to 1 node. Fast.       ║
║                   │ node. Stale data │ Other nodes catch up   ║
║                   │ possible.        │ asynchronously.        ║
╠═══════════════════════════════════════════════════════════════╣
║  Cassandra        │ PC (effectively) │ EC                     ║
║  (CL=QUORUM,RF=3)│ If partition     │ Waits for majority      ║
║                   │ isolates 2+ nodes│ of replicas before     ║
║                   │ → can't reach    │ returning. Slower      ║
║                   │ quorum → error   │ but consistent.        ║
╠═══════════════════════════════════════════════════════════════╣
║  DynamoDB         │ PA               │ EL                     ║
║  (eventually      │ Always serves    │ Fast writes, async     ║
║   consistent read)│ from any node    │ replication            ║
╠═══════════════════════════════════════════════════════════════╣
║  DynamoDB         │ PC               │ EC                     ║
║  (strongly        │ If partition →   │ Reads go to leader,    ║
║   consistent read)│ may fail reads   │ waits for consistency  ║
╠═══════════════════════════════════════════════════════════════╣
║  MongoDB          │ PC               │ EC                     ║
║  (default)        │ If primary is    │ Writes go to primary,  ║
║                   │ partitioned from │ wait for majority      ║
║                   │ majority →       │ ACK (w:majority).      ║
║                   │ primary steps    │ Reads from primary     ║
║                   │ down, cluster    │ are consistent.        ║
║                   │ becomes read-only│                        ║
╠═══════════════════════════════════════════════════════════════╣
║  Redis            │ PA               │ EL                     ║
║  (Cluster)        │ Serves from any  │ Async replication.     ║
║                   │ reachable master │ ACK before replica     ║
║                   │ Data may diverge │ has the data.          ║
║                   │ across partition │ Fast, not consistent.  ║
╠═══════════════════════════════════════════════════════════════╣
║  ZooKeeper        │ PC               │ EC                     ║
║                   │ Refuses writes   │ Waits for majority     ║
║                   │ if can't reach   │ consensus (ZAB         ║
║                   │ majority quorum  │ protocol) on every     ║
║                   │                  │ write. Consistent      ║
║                   │                  │ but slower.            ║
╠═══════════════════════════════════════════════════════════════╣
║  etcd / Raft      │ PC               │ EC                     ║
║                   │ Leader must have │ All writes go through  ║
║                   │ majority to      │ Raft consensus.        ║
║                   │ serve writes     │ Linearizable.          ║
╚═══════════════════════════════════════════════════════════════╝

KEY INSIGHT FROM THIS TABLE:

  Most systems are either PA/EL or PC/EC.

  PA/EL: "I prioritize speed. During partitions I serve
          stale data. During normal operation I don't
          wait for replicas."
          → Cassandra (CL=ONE), Redis, DynamoDB (eventual)

  PC/EC: "I prioritize correctness. During partitions I
          refuse to serve. During normal operation I wait
          for replicas."
          → MongoDB, ZooKeeper, etcd, PostgreSQL (sync)

  RARE BUT POSSIBLE: PA/EC or PC/EL

  PA/EC: "During partitions I serve stale data, but
          during normal operation I wait for consistency."
          → Cassandra with CL=QUORUM is close to this
          → During partition: serves from available nodes
            (some queries succeed at QUORUM, some fail)
          → Normal operation: waits for quorum before ACK

  PC/EL: "During partitions I refuse to serve, but
          during normal operation I don't wait for replicas."
          → PostgreSQL with async replication +
            failover that rejects writes during failover
          → Rare in practice
```

### Why PACELC Is More Useful Than CAP for System Design

```
SCENARIO: You're designing a user profile service.

USING ONLY CAP:
  "Do I want CP or AP?"
  → CP: "Profiles are always consistent"
  → AP: "Profiles are always available"
  → Not very helpful for making an actual design decision.

USING PACELC:
  "What do I want during normal operation AND during partitions?"

  Normal operation (99.9% of the time):
  → How much latency can I add for consistency?
  → If I use synchronous replication across 3 nodes:
    write_latency = max(network_to_node1, network_to_node2,
                        network_to_node3)
    → Within one datacenter: ~1ms additional → acceptable
    → Across US-East and US-West: ~70ms additional → maybe not
    → Across US and Europe: ~150ms additional → unacceptable
      for a user-facing API

  → DECISION: Within a region, EC (wait for consistency).
    Across regions, EL (async replication, tolerate staleness).

  During partition:
  → If a user can't read their own profile: frustrating but
    not catastrophic. No financial impact.
  → PA: serve stale profile data during partition.

  PACELC classification: PA/EL (cross-region), PA/EC (within region)

  This is a MUCH more nuanced and useful decision than just
  saying "AP" or "CP."
```

### The Per-Feature CAP Decision

```
IMPORTANT: You don't have to make ONE CAP choice for
your entire system. Different features can make
different choices.

EXAMPLE: E-commerce platform

  ╔══════════════════════════════════════════════════════════════╗
  ║  FEATURE                │ CHOICE │ REASONING                 ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Product catalog        │ PA/EL  │ Stale product             ║
  ║  (browse, search)       │        │ description for           ║
  ║                         │        │ 5 seconds = fine          ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Shopping cart          │ PA/EL  │ Cart is per-user.         ║
  ║                         │        │ Speed > consistency       ║
  ║                         │        │ across replicas.          ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Inventory count        │ PC/EC  │ Overselling is            ║
  ║  (stock check at        │        │ worse than "out           ║
  ║   checkout)             │        │ of stock" error.          ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Payment processing     │ PC/EC  │ Must be correct.          ║
  ║                         │        │ Double-charge is          ║
  ║                         │        │ a legal issue.            ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Order confirmation     │ PC/EC  │ Order must exist          ║
  ║                         │        │ in ALL replicas           ║
  ║                         │        │ before confirming.        ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Recommendations        │ PA/EL  │ Stale recs are            ║
  ║                         │        │ fine. Speed matters.      ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  User session           │ PA/EL  │ If session is lost,       ║
  ║                         │        │ user re-logs in.          ║
  ║                         │        │ Not catastrophic.         ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Analytics / metrics    │ PA/EL  │ Approximate counts        ║
  ║                         │        │ are fine. Speed           ║
  ║                         │        │ and availability.         ║
  ╚══════════════════════════════════════════════════════════════╝

  THE FRAMEWORK:
  Ask two questions about each feature:

  1. "If a user sees STALE data, what's the worst case?"
     → Mild annoyance → PA/EL
     → Financial loss / legal issue → PC/EC

  2. "If the feature is UNAVAILABLE, what's the worst case?"
     → Users can't browse → revenue loss → PA/EL
     → Users can't place orders → also revenue loss →
       BUT showing wrong price is worse → PC/EC

  THE DECISION RULE:
  → If stale data causes more damage than unavailability → PC/EC
  → If unavailability causes more damage than stale data → PA/EL
```

### How Partitions Actually Manifest

```
In interviews, people talk about partitions abstractly.
In production, partitions look like this:

PARTITION TYPE 1: NETWORK SPLIT
  ╔══════════════════════════════════════════════════════════════╗
  ║   AZ-1        │         │  AZ-2                              ║
  ║               │── ✕ ───│                                     ║
  ║   Node 1,2,3  │         │  Node 4,5,6                        ║
  ╚══════════════════════════════════════════════════════════════╝

  Cause: Switch failure, cable cut, AZ connectivity loss
  Duration: Seconds to hours
  Frequency: Rare but real (AWS has had AZ partitions)

PARTITION TYPE 2: ASYMMETRIC PARTITION
  ╭──────────────╮
  │   Node 1     │──────→ Node 2 (can send)
  │              │✕←────── Node 2 (can't receive from 2)
  ╰──────────────╯

  Node 1 thinks Node 2 is dead (no responses).
  Node 2 thinks Node 1 is alive (still receiving).
  This is WORSE than a clean split — each side has
  different information about the cluster state.

  Cause: Firewall rules, NIC failure (one direction),
  asymmetric routing

PARTITION TYPE 3: PROCESS PAUSE (Pseudo-Partition)

  Node 1 is technically on the network but UNRESPONSIVE:
  → GC pause (Java/JVM: stop-the-world GC for 10+ seconds)
  → CPU saturation (100% CPU, can't process heartbeats)
  → Disk I/O stall (waiting for fsync)
  → OS swap thrashing (out of RAM, paging to disk)

  From other nodes' perspective: Node 1 stopped responding.
  Same effect as a network partition.

  This is actually the MOST COMMON "partition" in production.
  Not a network problem — a node problem that LOOKS like
  a partition to the cluster.

PARTITION TYPE 4: DNS / SERVICE DISCOVERY FAILURE

  Nodes are connected but can't FIND each other:
  → DNS returns wrong IP
  → Service mesh sidecar crashes
  → Load balancer routes to wrong backend

  Functionally equivalent to a partition for the
  affected service.

PRODUCTION FREQUENCY:

  ╔══════════════════════════════════════════════════════════════╗
  ║   PARTITION TYPE           │ FREQUENCY                       ║
  ╠══════════════════════════════════════════════════════════════╣
  ║   Process pause / GC       │  Weekly                         ║
  ║   Single-node network blip │  Monthly                        ║
  ║   DNS / service discovery  │  Monthly                        ║
  ║   AZ-level network split   │  Yearly                         ║
  ║   Region-level partition   │  Multi-year                     ║
  ╚══════════════════════════════════════════════════════════════╝

  Process pauses are by far the most common.
  This is why CAP matters even within a single datacenter.
```

### How CP and AP Systems Handle Partitions In Practice

```
SCENARIO: 3-node cluster, nodes A, B, C.
Partition splits: {A, B} vs {C}.
Node C is isolated from A and B.

CP SYSTEM (e.g., MongoDB, etcd):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  {A, B} side:
  → A and B can communicate
  → They form a MAJORITY (2 of 3)
  → They elect a leader (if needed)
  → They continue accepting reads AND writes
  → Writes require majority ACK → A and B suffice

  {C} side:
  → C is alone (1 of 3)
  → C is a MINORITY
  → C REFUSES to accept writes (can't reach majority)
  → C may refuse reads too (depends on configuration)
  → C returns errors: "Cannot serve request"

  ╔══════════════════════════════════════════════════════════════╗
  ║   {A, B}: Fully operational (majority)                       ║
  ║   {C}:    Unavailable (minority)                             ║
  ║                                                              ║
  ║   DATA IS CONSISTENT across all serving nodes                ║
  ║   But clients connected to C get errors                      ║
  ╚══════════════════════════════════════════════════════════════╝

  When partition heals:
  → C reconnects to A and B
  → C catches up by replaying missed writes
  → Cluster is fully consistent and available again

AP SYSTEM (e.g., Cassandra CL=ONE, DynamoDB eventual):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  {A, B} side:
  → Accepts reads and writes normally
  → A and B keep their data synchronized

  {C} side:
  → C ALSO accepts reads and writes
  → C serves data from its local copy
  → Reads might return stale data (C missed recent writes)
  → Writes to C are stored locally

  ╔══════════════════════════════════════════════════════════════╗
  ║   {A, B}: Operational (possibly stale for                    ║
  ║           data written to C during partition)                ║
  ║   {C}:    Operational (possibly stale for                    ║
  ║           data written to A or B)                            ║
  ║                                                              ║
  ║   ALL NODES ARE AVAILABLE                                    ║
  ║   But data may be INCONSISTENT across sides                  ║
  ╚══════════════════════════════════════════════════════════════╝

  When partition heals:
  → C reconnects to A and B
  → CONFLICT RESOLUTION needed:
    → What if A wrote X=5 and C wrote X=7 during partition?
    → Last-write-wins (timestamp-based)
    → Vector clocks
    → Application-level merge (CRDTs)
  → This conflict resolution is the COST of AP availability
```

---

### The System Design Interview Framework

```
When an interviewer asks about CAP, here's the framework:

╔════════════════════════════════════════════════════════════════╗
║   STEP 1: Acknowledge CAP's actual meaning                     ║
║   "CAP says that during a network partition, we must           ║
║    choose between consistency and availability.                ║
║    Since partitions are inevitable in distributed systems,     ║
║    we're really choosing between CP and AP."                   ║
║                                                                ║
║   STEP 2: Explain that the choice is PER-FEATURE               ║
║   "Different parts of this system have different               ║
║    requirements. Let me classify each one."                    ║
║                                                                ║
║   STEP 3: Apply PACELC for the ELSE case                       ║
║   "But partitions are rare. Most of the time, the tradeoff     ║
║    is between latency and consistency. For this feature..."    ║
║                                                                ║
║   STEP 4: Make a concrete decision with justification          ║
║   "For [feature], I choose PA/EL because stale data for        ║
║    5 seconds is acceptable, and the latency improvement        ║
║    from async replication is significant for user experience." ║
║                                                                ║
║   STEP 5: Describe how the system handles BOTH cases           ║
║   "During normal operation: async replication, read replicas.  ║
║    During partition: serve stale data, queue writes for        ║
║    reconciliation after partition heals."                      ║
╚════════════════════════════════════════════════════════════════╝
```

---

### Staff

## Production Patterns
```
╔═══════════════════════════════════════════════════════════════╗
║   PRODUCTION PATTERN #1: SPLIT-BRAIN                          ║
║                                                               ║
║   Scenario: MongoDB replica set. Primary is in AZ-1.          ║
║   Network partition between AZ-1 and AZ-2.                    ║
║                                                               ║
║   AZ-1: Primary (can't reach secondaries in AZ-2)             ║
║   AZ-2: Secondaries (can't reach primary in AZ-1)             ║
║                                                               ║
║   What happens:                                               ║
║   → Secondaries in AZ-2 hold an election                      ║
║   → They elect a NEW primary (among themselves)               ║
║   → Now there are TWO primaries!                              ║
║   → Both accepting writes → data DIVERGES                     ║
║                                                               ║
║   This is SPLIT-BRAIN — the worst failure in CP systems.      ║
║                                                               ║
║   MongoDB's defense: Majority requirement for election.       ║
║   → 3-node replica set: majority = 2                          ║
║   → AZ-1 has 1 node (primary) → can't form majority → steps   ║
║     down to secondary → STOPS accepting writes                ║
║   → AZ-2 has 2 nodes → CAN form majority → elects new primary ║
║   → Only ONE primary exists at any time                       ║
║                                                               ║
║   BUT: what if the partition is 2-1 the other way?            ║
║   → AZ-1: 2 nodes (primary + secondary)                       ║
║   → AZ-2: 1 node (secondary)                                  ║
║   → AZ-1 has majority → primary continues                     ║
║   → AZ-2 can't form majority → read-only (or unavailable)     ║
║   → Clean. No split-brain.                                    ║
║                                                               ║
║   KEY PRINCIPLE: Always have an ODD number of voting          ║
║   members. 3, 5, 7 — never 2, 4, 6. Even numbers              ║
║   can split exactly in half with no majority.                 ║
╠═══════════════════════════════════════════════════════════════╣
║   PRODUCTION PATTERN #2: STALE READS AFTER FAILOVER           ║
║                                                               ║
║   Scenario: PostgreSQL with async replication.                ║
║   Primary crashes. Replica is promoted to primary.            ║
║                                                               ║
║   Problem: The replica was BEHIND the old primary.            ║
║   Some committed transactions on the old primary hadn't       ║
║   been replicated yet.                                        ║
║                                                               ║
║   → Old primary: WAL position 1000 (crashed)                  ║
║   → Replica: WAL position 980 (20 entries behind)             ║
║   → Replica promoted → new primary at position 980            ║
║   → Those 20 transactions are LOST.                           ║
║                                                               ║
║   This is the EL (Else Latency) cost of async replication.    ║
║   You got faster writes (EL) but lost data on failover.       ║
║                                                               ║
║   Fix:                                                        ║
║   → Synchronous replication (EC): primary waits for           ║
║     replica ACK before committing. No data loss on failover.  ║
║     Cost: ~2ms extra latency per write (within same DC).      ║
║   → Semi-synchronous: wait for at least ONE replica.          ║
║     Tolerate loss only if primary AND that one replica        ║
║     fail simultaneously (extremely unlikely).                 ║
║                                                               ║
║   PRODUCTION DECISION:                                        ║
║   → Financial data: synchronous (EC). 2ms is acceptable.      ║
║   → User activity data: async (EL). Losing 20 events          ║
║     on failover is acceptable.                                ║
╠═══════════════════════════════════════════════════════════════╣
║   PRODUCTION PATTERN #3: CHOOSING WRONG CAP FOR THE FEATURE   ║
║                                                               ║
║   Scenario: Team uses Cassandra (PA/EL) for an inventory      ║
║   management system. Two warehouses.                          ║
║                                                               ║
║   What breaks:                                                ║
║   → Warehouse A: reads stock = 1 (from local Cassandra node)  ║
║   → Warehouse B: reads stock = 1 (from its local node)        ║
║   → Both "sell" the last item simultaneously                  ║
║   → Stock is now -1 (oversold)                                ║
║                                                               ║
║   The team chose AP (Cassandra) for a feature that            ║
║   requires CP (inventory). Stale reads caused overselling.    ║
║                                                               ║
║   Fix: Use PostgreSQL (PC/EC) for inventory.                  ║
║   Cassandra is fine for product descriptions, reviews,        ║
║   and analytics — but NOT for inventory counts.               ║
║                                                               ║
║   THIS IS THE MOST COMMON CAP MISTAKE IN PRODUCTION:          ║
║   Using one database for everything instead of choosing       ║
║   the right consistency model PER FEATURE.                    ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## SRE Diagnostic Toolkit

```
DIAGNOSTIC QUESTIONS (partition drill):
  1. Which invariant broke first — availability or consistency?
  2. Did clients see stale reads, errors, or split-brain writes?
  3. Was the partition real (network) or slow node (GC pause)?

METRICS:
  Error rate by AZ, quorum ack latency, leader election count
  Cassandra UNAVAILABLE rate, etcd proposal failures

COMMANDS:
  kubectl get pods -o wide --field-selector spec.nodeName=...
  nodetool status / etcdctl endpoint health
```

---

## Decision Framework

```
CAP IS A PER-OPERATION CHOICE, NOT A DATABASE LABEL. The real question is:
"When THIS operation cannot reach a quorum, do I return an error (CP) or a
possibly-stale/divergent answer (AP)?"

STEP 1 — CLASSIFY EACH OPERATION DURING A PARTITION

  ┌──────────────────────────────┬──────────┬───────────────────────────────┐
  │ Operation                    │ Choose   │ Why                           │
  ├──────────────────────────────┼──────────┼───────────────────────────────┤
  │ Money movement, inventory    │ CP       │ A wrong answer is worse than  │
  │ decrement, unique constraint │          │ no answer; reject if unsure   │
  ├──────────────────────────────┼──────────┼───────────────────────────────┤
  │ Config / lock / leader       │ CP       │ Divergent config = split      │
  │ election (etcd, ZooKeeper)   │          │ brain; must agree             │
  ├──────────────────────────────┼──────────┼───────────────────────────────┤
  │ Feed, likes, cart add,       │ AP       │ Staleness is tolerable;       │
  │ product browsing, DNS        │          │ availability drives revenue   │
  ├──────────────────────────────┼──────────┼───────────────────────────────┤
  │ Shopping cart merge          │ AP + CRDT│ Stay writable, merge later    │
  │                              │          │ (Week 8) instead of blocking  │
  └──────────────────────────────┴──────────┴───────────────────────────────┘

STEP 2 — PACELC (the 99% case: NO partition)
  Else (no partition): Latency vs Consistency.
    Low-latency reads matter more?  -> async replicas, eventual reads (PA/EL)
    Correctness matters more?       -> sync replication / primary reads (PC/EC)
  Most systems live here — CAP only bites during the rare partition, PACELC
  governs the everyday latency/consistency trade.

STEP 3 — MAKE THE PARTITION BEHAVIOR EXPLICIT
  - Define, per endpoint, what happens when quorum is lost (error vs stale).
  - Surface staleness to clients (X-Data-Staleness header, "delayed" banner)
    instead of silently serving old data.
  - Fence before promoting on failover (Week 4) so "AP" doesn't become
    split-brain data corruption.

ANTI-PATTERNS
  - "We're CP" but reads go to async replicas -> you're actually AP for reads.
  - "We're AP" but writes block waiting on a downed replica -> neither A nor C.
  - Choosing one CAP stance for the WHOLE system instead of per-operation.
```

---

## Hands-On Exercises
```
╔════════════════════════════════════════════════════════════════╗
║   EXERCISE 1: Observe a Partition in Redis Cluster             ║
║                                                                ║
║   # Start a 3-node Redis Cluster with Docker Compose           ║
║   # (use a redis-cluster docker image or create manually)      ║
║                                                                ║
║   # Write a key:                                               ║
║   redis-cli -c -p 7000 SET mykey "hello"                       ║
║   # Note which node owns it (redis-cli shows the redirect)     ║
║                                                                ║
║   # Read from another node:                                    ║
║   redis-cli -c -p 7001 GET mykey                               ║
║   # Returns "hello" — cluster redirects to the right node      ║
║                                                                ║
║   # NOW: simulate a partition by pausing a container:          ║
║   docker pause redis-node-1                                    ║
║                                                                ║
║   # Try to read the key that was on node 1:                    ║
║   redis-cli -c -p 7001 GET mykey                               ║
║   # What happens?                                              ║
║   # → If the key was on node 1: CLUSTERDOWN or redirect        ║
║   #   to node 1's replica (if it has one and failover happens) ║
║   # → If the key was on another node: works fine               ║
║                                                                ║
║   # Try to write a key that routes to node 1:                  ║
║   redis-cli -c -p 7001 SET newkey "world"                      ║
║   # If newkey routes to node 1's slots: error                  ║
║   # If it routes to node 2 or 3's slots: success               ║
║                                                                ║
║   # OBSERVE: Redis Cluster is PA for reads (returns what       ║
║   # it has) but PC for writes to the downed node's slots       ║
║   # (refuses writes it can't guarantee).                       ║
║   # After failover: replica takes over, writes resume.         ║
║                                                                ║
║   # Unpause:                                                   ║
║   docker unpause redis-node-1                                  ║
║   # Node 1 rejoins. If a failover happened, node 1 becomes     ║
║   # a replica of the new master for those slots.               ║
╠════════════════════════════════════════════════════════════════╣
║   EXERCISE 2: Observe Consistency Differences                  ║
║                                                                ║
║   # Using PostgreSQL with 1 primary + 1 async replica:         ║
║   # (docker-compose with pg primary and standby)               ║
║                                                                ║
║   # Terminal 1 (write to primary):                             ║
║   psql -h primary -c "INSERT INTO test VALUES (1, 'hello');"   ║
║                                                                ║
║   # Terminal 2 (IMMEDIATELY read from replica):                ║
║   psql -h replica -c "SELECT * FROM test WHERE id = 1;"        ║
║                                                                ║
║   # If you're fast enough: row might not be there yet!         ║
║   # This is EL — async replication means the replica is        ║
║   # briefly behind.                                            ║
║                                                                ║
║   # Now switch to SYNCHRONOUS replication:                     ║
║   psql -h primary -c "ALTER SYSTEM SET                         ║
║     synchronous_standby_names = 'replica1';"                   ║
║   psql -h primary -c "SELECT pg_reload_conf();"                ║
║                                                                ║
║   # Repeat the test:                                           ║
║   # Terminal 1: INSERT                                         ║
║   # Terminal 2: SELECT (immediately)                           ║
║   # Row IS there. Every time. This is EC.                      ║
║                                                                ║
║   # But: measure the write latency difference.                 ║
║   # Async: INSERT takes ~1ms                                   ║
║   # Sync: INSERT takes ~3ms (waiting for replica ACK)          ║
║   # That's the PACELC tradeoff in action: EC costs latency.    ║
╠════════════════════════════════════════════════════════════════╣
║   EXERCISE 3: Cassandra Tunable Consistency                    ║
║                                                                ║
║   # If you have a Cassandra cluster (or use ccm for local):    ║
║                                                                ║
║   # Write at CL=ONE:                                           ║
║   cqlsh -e "CONSISTENCY ONE;                                   ║
║     INSERT INTO test.data (id, value) VALUES (1, 'hello');"    ║
║   # Returns immediately — wrote to 1 node only                 ║
║                                                                ║
║   # Read at CL=ONE from a DIFFERENT node:                      ║
║   # (might return nothing if the write hasn't propagated)      ║
║                                                                ║
║   # Write at CL=QUORUM:                                        ║
║   cqlsh -e "CONSISTENCY QUORUM;                                ║
║     INSERT INTO test.data (id, value) VALUES (2, 'world');"    ║
║   # Takes slightly longer — waited for 2 of 3 nodes            ║
║                                                                ║
║   # Read at CL=QUORUM:                                         ║
║   # Guaranteed to see the write (R + W > N → overlap)          ║
║                                                                ║
║   # OBSERVE: Same database, same data, different               ║
║   # consistency guarantees based on CL setting.                ║
║   # This is PACELC in action: you choose the tradeoff          ║
║   # PER QUERY, not per database.                               ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading
```
╔══════════════════════════════════════════════════════════════╗
║   READ AFTER THIS LESSON:                                    ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   DDIA Chapter 5: "Replication"                              ║
║   → Pages 151-167 (Leaders and Followers)                    ║
║     Focus on: Synchronous vs Asynchronous replication.       ║
║     This is the EL vs EC tradeoff in practice.               ║
║                                                              ║
║   → Pages 167-178 (Problems with Replication Lag)            ║
║     Focus on: "Reading Your Own Writes", "Monotonic Reads",  ║
║     "Consistent Prefix Reads"                                ║
║     These are the CONSISTENCY MODELS between                 ║
║     linearizability and eventual consistency.                ║
║     They connect directly to Week 3, Topic 2.                ║
║                                                              ║
║   DDIA Chapter 9: "Consistency and Consensus"                ║
║   → Pages 321-338 (Consistency Guarantees, Linearizability)  ║
║     Focus on: "What Makes a System Linearizable?"            ║
║     This is CAP's "C" defined rigorously.                    ║
║   → Pages 336-338 (The Cost of Linearizability)              ║
║     THIS IS THE CAP THEOREM explained precisely.             ║
║     Read this section CAREFULLY — it's the best              ║
║     explanation of CAP in any textbook.                      ║
║                                                              ║
║   OPTIONAL (for deeper understanding):                       ║
║   → Daniel Abadi's original PACELC blog post (2012)          ║
║     "Consistency Tradeoffs in Modern Distributed             ║
║      Database System Design"                                 ║
║     This is the paper that introduced PACELC.                ║
║     Short, accessible, directly relevant.                    ║
║                                                              ║
║   TOTAL: ~40 pages from DDIA + optional blog post.           ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Key Takeaways
```
╔═══════════════════════════════════════════════════════════════╗
║   5 THINGS TO REMEMBER IF YOU FORGET EVERYTHING ELSE          ║
╟───────────────────────────────────────────────────────────────╢
║                                                               ║
║   1. CAP's real choice is CP vs AP (not "pick 2 of 3").       ║
║      Partition tolerance is MANDATORY in distributed systems. ║
║      Partitions are facts of life, not design choices.        ║
║      The question is: during a partition, do you sacrifice    ║
║      consistency (serve stale data) or availability           ║
║      (return errors)?                                         ║
║                                                               ║
║   2. CAP only applies DURING partitions. PACELC extends it:   ║
║      "Else" (no partition) → Latency vs Consistency.          ║
║      The EL vs EC tradeoff is what you deal with DAILY.       ║
║      Sync replication = EC (slower, consistent).              ║
║      Async replication = EL (faster, eventually consistent).  ║
║                                                               ║
║   3. The CAP choice is PER-FEATURE, not per-system.           ║
║      Shopping cart: PA/EL (speed > consistency).              ║
║      Payment processing: PC/EC (correctness > speed).         ║
║      Different features in the SAME system can make           ║
║      different tradeoffs using different databases.           ║
║                                                               ║
║   4. The decision rule: compare damage from stale data vs     ║
║      damage from unavailability.                              ║
║      Stale data causes more damage → PC/EC.                   ║
║      Unavailability causes more damage → PA/EL.               ║
║      Financial data: stale = dangerous → PC/EC.               ║
║      Social feed: unavailable = revenue loss → PA/EL.         ║
║                                                               ║
║   5. In production, "partitions" are usually process pauses   ║
║      (GC, CPU saturation) not network failures. They happen   ║
║      weekly, not yearly. Design for the common case           ║
║      (PACELC's Else clause) not just the rare case            ║
║      (CAP's partition scenario).                              ║
╚═══════════════════════════════════════════════════════════════╝
```
> **Answer key (do not open until you attempt the scenario questions):**
> [`../answers/Week-03-Distributed-Systems-Theory/CAP%20Theorem%20Answers.md`](../answers/Week-03-Distributed-Systems-Theory/CAP%20Theorem%20Answers.md)

---

### Principal stretch

## Ops Sim: Northstar Financial Partition Tradeoff

**Drill note:** Answer from the incident timeline below. Make per-feature PACELC decisions; do not treat the whole platform as one CAP choice.

```
╔═════════════════════════════════════════════════════════════════╗
║   SCENARIO: Global Financial Trading Platform                   ║
╟─────────────────────────────────────────────────────────────────╢
║                                                                 ║
║   You're the on-call SRE for a financial trading platform       ║
║   that operates in two regions: US-East and EU-West.            ║
║                                                                 ║
║   STACK:                                                        ║
║   → PostgreSQL: Trade records, account balances                 ║
║     → US-East: Primary (read/write)                             ║
║     → EU-West: Async replica (read-only)                        ║
║     → Replication lag: normally 50-80ms (cross-Atlantic)        ║
║                                                                 ║
║   → Cassandra: Market data feed (price ticks, quotes)           ║
║     → 6 nodes: 3 in US-East, 3 in EU-West                       ║
║     → RF=3, NetworkTopologyStrategy (1 DC each gets 3 copies    ║
║       — actually RF=3 per DC, but let's say RF=3 total with     ║
║       data in both DCs for this scenario)                       ║
║     → Reads/Writes at LOCAL_QUORUM                              ║
║                                                                 ║
║   → Redis: Order book cache, session tokens                     ║
║     → Separate clusters in each region (not cross-region)       ║
║     → Each cluster is an independent 6-node Redis Cluster       ║
║                                                                 ║
║   → API Gateway: Routes users to the nearest region             ║
║     → US users → US-East                                        ║
║     → EU users → EU-West                                        ║
║                                                                 ║
║   ALERT TIMELINE:                                               ║
║                                                                 ║
║   14:00 — Undersea cable between US-East and EU-West            ║
║           experiences degradation.                              ║
║           Cross-region latency: 80ms → 320ms.                   ║
║           Packet loss: 0% → 12%.                                ║
║                                                                 ║
║   14:01 — PostgreSQL replication lag:                           ║
║           50ms → 4.2 seconds (and growing).                     ║
║           EU-West replica is falling behind.                    ║
║                                                                 ║
║   14:02 — EU traders report:                                    ║
║           "My trade executed but my balance hasn't updated."    ║
║           "I see my old balance, not the one after my trade."   ║
║           → EU reads going to EU replica which is 4.2s behind.  ║
║                                                                 ║
║   14:03 — A critical situation develops:                        ║
║           EU Trader Alice has $100,000 balance (per US primary) ║
║           EU replica shows $150,000 (4+ seconds stale).         ║
║           Alice places a trade for $120,000.                    ║
║           The trade service READS her balance from the EU       ║
║           replica ($150,000) → sufficient funds → APPROVED.     ║
║           Trade executes. But her ACTUAL balance is $100,000.   ║
║           She's now $20,000 in the red.                         ║
║                                                                 ║
║   14:04 — Cassandra market data:                                ║
║           US-East cluster: operating normally.                  ║
║           EU-West: price ticks are arriving 320ms late.         ║
║           EU traders see prices that are 320ms stale.           ║
║           In volatile markets, 320ms stale prices               ║
║           = trading on wrong information.                       ║
║                                                                 ║
║   14:05 — Risk management system alerts:                        ║
║           "3 trades in the last 2 minutes exceeded account      ║
║            balance limits. All originated from EU-West."        ║
║           Total exposure: $340,000 beyond balance limits.       ║
║                                                                 ║
║   14:06 — Cassandra in EU-West:                                 ║
║           LOCAL_QUORUM reads succeeding (local DC healthy).     ║
║           But cross-DC repair/consistency is delayed.           ║
║           Gossip protocol between DCs is slow (320ms RTT).      ║
║                                                                 ║
║   14:07 — Network monitoring:                                   ║
║           Packet loss increasing: 12% → 23%.                    ║
║           Cross-region latency: 320ms → 850ms.                  ║
║           The cable degradation is getting worse.               ║
║           PostgreSQL replication lag: 4.2s → 12.8s.             ║
║                                                                 ║
║   14:08 — EU Redis cluster: operating normally                  ║
║           (independent cluster, not cross-region).              ║
║           But the order book cache in EU is populated           ║
║           from market data in Cassandra, which is               ║
║           320ms+ stale → EU order book is stale too.            ║
║                                                                 ║
╚═════════════════════════════════════════════════════════════════╝

QUESTIONS:

Q1: Classify each component of this system using PACELC.
    For each, state:
    → What it does during normal operation (EL or EC)
    → What it does during this partition (PA or PC)
    → Whether this is the RIGHT choice for this component's
      data (should it be different?)

Q2: The balance check that approved Alice's $120,000 trade
    is the critical failure. It read $150,000 from the EU
    replica when the actual balance was $100,000.

    a) In PACELC terms, what went wrong?
    b) Give TWO different architectural fixes, each with
       different PACELC tradeoffs. For each, state the
       explicit tradeoff being made.

Q3: The system architect argues: "We should switch
    PostgreSQL to synchronous cross-region replication.
    That would have prevented Alice's trade."

    Is this a good idea? Argue BOTH sides using PACELC
    reasoning, then give your recommendation.

Q4: At 14:07, the cable degradation is getting worse.
    You need to decide: should EU-West continue operating
    independently, or should you SHUT DOWN EU-West trading
    and redirect all EU users to US-East (adding ~80-320ms
    latency but ensuring consistency)?

    Make the decision. Justify it using the per-feature
    CAP framework.

Q5: Give your mitigation plan for this incident.
    This is a financial platform — incorrect balances and
    trades beyond limits are REGULATORY issues, not just
    technical issues.
```

> **Answer key (open only after you have answered):**
> [`../answers/Week-03-Distributed-Systems-Theory/CAP Theorem Answers.md`](../answers/Week-03-Distributed-Systems-Theory/CAP Theorem Answers.md)


--- 



---
