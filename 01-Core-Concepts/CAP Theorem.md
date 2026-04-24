# Week 3, Topic 1: CAP Theorem + PACELC

---

## Step 1: Learning Objectives

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

## Step 2: Core Teaching

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
╭─────────────────────────────────────────────────────────────╮
│  MISCONCEPTION #1: "CAP means pick any 2 of 3"              │
│                                                             │
│  WRONG. You don't "pick" partition tolerance.               │
│  Partitions HAPPEN. You must handle them.                   │
│                                                             │
│  The real choice is: when a partition happens,              │
│  do you sacrifice Consistency or Availability?              │
│                                                             │
│  There's no "CA" distributed database.                      │
│  A single-node PostgreSQL is "CA" — but it's not            │
│  distributed, so CAP doesn't apply.                         │
│                                                             │
│  The moment you add a second node, you must deal            │
│  with partitions.                                           │
├─────────────────────────────────────────────────────────────┤
│  MISCONCEPTION #2: "Consistency and availability are binary"│
│                                                             │
│  WRONG. CAP's definitions are binary (for the proof),       │
│  but real systems exist on a SPECTRUM.                      │
│                                                             │
│  You don't have to choose "100% consistent always" or       │
│  "100% available always."                                   │
│                                                             │
│  Real systems make NUANCED choices:                         │
│  → Consistent for writes, eventually consistent for reads   │
│  → Consistent for financial data, available for social data │
│  → Consistent within a region, eventually consistent        │
│    across regions                                           │
│  → Consistent for the first 5 seconds, then serve stale     │
│                                                             │
│  Cassandra's tunable consistency (ONE, QUORUM, ALL) is      │
│  a perfect example: you choose PER QUERY where you          │
│  fall on the spectrum.                                      │
├─────────────────────────────────────────────────────────────┤
│  MISCONCEPTION #3: "CAP applies all the time"               │
│                                                             │
│  WRONG. CAP only applies DURING a partition.                │
│                                                             │
│  When the network is healthy (no partition):                │
│  → You CAN have consistency AND availability!               │
│  → This is normal operation for most systems                │
│  → There's no tradeoff to make                              │
│                                                             │
│  CAP says: "During a partition, you must sacrifice one."    │
│  It does NOT say: "You can never have both."                │
│                                                             │
│  This is why CAP alone is insufficient for system design.   │
│  It tells you nothing about the system's behavior during    │
│  NORMAL operation (no partition). And normal operation      │
│  is 99.9%+ of the time.                                     │
│                                                             │
│  THIS IS EXACTLY WHY PACELC EXISTS.                         │
╰─────────────────────────────────────────────────────────────╯
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
╭──────────────────┬──────────────────┬───────────────────────╮
│ SYSTEM           │ During Partition │ Else (Normal)         │
│                  │ (P → A or C?)    │ (E → L or C?)         │
├──────────────────┼──────────────────┼───────────────────────┤
│ PostgreSQL       │ PC               │ EC                    │ 
│ (sync replica)   │ Refuses writes   │ Waits for replica     │ 
│                  │ if replica is    │ ACK before            │
│                  │ unreachable      │ confirming commit     │
│                  │                  │ → Higher latency,     │
│                  │                  │   strong consistency  │
├──────────────────┼──────────────────┼───────────────────────┤
│ PostgreSQL       │ PC               │ EL                    │
│ (async replica)  │ Primary serves,  │ Write ACKed before    │
│                  │ replica becomes  │ replica has the data  │
│                  │ inconsistent.    │ → Lower latency,      │
│                  │ (Actually: PA    │   eventual consistency│
│                  │ at primary, PC   │                       │
│                  │ if reading from  │   (This is what most  │
│                  │ replica)         │    production PG uses)│
├──────────────────┼──────────────────┼───────────────────────┤
│ Cassandra        │ PA               │ EL                    │
│ (CL=ONE)         │ Serves requests  │ Returns after writing │
│                  │ from any live    │ to 1 node. Fast.      │
│                  │ node. Stale data │ Other nodes catch up  │
│                  │ possible.        │ asynchronously.       │
├──────────────────┼──────────────────┼───────────────────────┤
│ Cassandra        │ PC (effectively) │ EC                    │
│ (CL=QUORUM,RF=3)│ If partition     │ Waits for majority     │
│                  │ isolates 2+ nodes│ of replicas before    │
│                  │ → can't reach    │ returning. Slower     │
│                  │ quorum → error   │ but consistent.       │
├──────────────────┼──────────────────┼───────────────────────┤
│ DynamoDB         │ PA               │ EL                    │
│ (eventually      │ Always serves    │ Fast writes, async    │
│  consistent read)│ from any node    │ replication           │
├──────────────────┼──────────────────┼───────────────────────┤
│ DynamoDB         │ PC               │ EC                    │
│ (strongly        │ If partition →   │ Reads go to leader,   │
│  consistent read)│ may fail reads   │ waits for consistency │
├──────────────────┼──────────────────┼───────────────────────┤ 
│ MongoDB          │ PC               │ EC                    │
│ (default)        │ If primary is    │ Writes go to primary, │
│                  │ partitioned from │ wait for majority     │
│                  │ majority →       │ ACK (w:majority).     │
│                  │ primary steps    │ Reads from primary    │
│                  │ down, cluster    │ are consistent.       │
│                  │ becomes read-only│                       │
├──────────────────┼──────────────────┼───────────────────────┤
│ Redis            │ PA               │ EL                    │
│ (Cluster)        │ Serves from any  │ Async replication.    │
│                  │ reachable master │ ACK before replica    │
│                  │ Data may diverge │ has the data.         │
│                  │ across partition │ Fast, not consistent. │ 
├──────────────────┼──────────────────┼───────────────────────┤ 
│ ZooKeeper        │ PC               │ EC                    │
│                  │ Refuses writes   │ Waits for majority    │
│                  │ if can't reach   │ consensus (ZAB        │
│                  │ majority quorum  │ protocol) on every    │
│                  │                  │ write. Consistent     │
│                  │                  │ but slower.           │
├──────────────────┼──────────────────┼───────────────────────┤
│ etcd / Raft      │ PC               │ EC                    │
│                  │ Leader must have │ All writes go through │
│                  │ majority to      │ Raft consensus.       │
│                  │ serve writes     │ Linearizable.         │
╰──────────────────┴──────────────────┴───────────────────────╯

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

  ╭────────────────────────┬────────┬─────────────────────╮
  │ FEATURE                │ CHOICE │ REASONING           │
  ├────────────────────────┼────────┼─────────────────────┤
  │ Product catalog        │ PA/EL  │ Stale product       │
  │ (browse, search)       │        │ description for     │
  │                        │        │ 5 seconds = fine    │
  ├────────────────────────┼────────┼─────────────────────┤
  │ Shopping cart          │ PA/EL  │ Cart is per-user.   │
  │                        │        │ Speed > consistency │
  │                        │        │ across replicas.    │
  ├────────────────────────┼────────┼─────────────────────┤
  │ Inventory count        │ PC/EC  │ Overselling is      │
  │ (stock check at        │        │ worse than "out     │
  │  checkout)             │        │ of stock" error.    │
  ├────────────────────────┼────────┼─────────────────────┤
  │ Payment processing     │ PC/EC  │ Must be correct.    │
  │                        │        │ Double-charge is    │
  │                        │        │ a legal issue.      │
  ├────────────────────────┼────────┼─────────────────────┤
  │ Order confirmation     │ PC/EC  │ Order must exist    │
  │                        │        │ in ALL replicas     │
  │                        │        │ before confirming.  │
  ├────────────────────────┼────────┼─────────────────────┤
  │ Recommendations        │ PA/EL  │ Stale recs are      │ 
  │                        │        │ fine. Speed matters.│
  ├────────────────────────┼────────┼─────────────────────┤
  │ User session           │ PA/EL  │ If session is lost, │
  │                        │        │ user re-logs in.    │
  │                        │        │ Not catastrophic.   │
  ├────────────────────────┼────────┼─────────────────────┤
  │ Analytics / metrics    │ PA/EL  │ Approximate counts  │
  │                        │        │ are fine. Speed     │
  │                        │        │ and availability.   │
  ╰────────────────────────┴────────┴─────────────────────╯

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

  ╭───────────────────────────────────────────────╮
  │  PARTITION TYPE           │ FREQUENCY         │
  ├───────────────────────────┼───────────────────┤
  │  Process pause / GC       │  Weekly           │
  │  Single-node network blip │  Monthly          │
  │  DNS / service discovery  │  Monthly          │
  │  AZ-level network split   │  Yearly           │
  │  Region-level partition   │  Multi-year       │
  ╰───────────────────────────┴───────────────────╯

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

## Step 3: Production Patterns & Failure Modes

```
╭──────────────────────────────────────────────────────────────╮
│  PRODUCTION PATTERN #1: SPLIT-BRAIN                          │
│                                                              │
│  Scenario: MongoDB replica set. Primary is in AZ-1.          │
│  Network partition between AZ-1 and AZ-2.                    │
│                                                              │
│  AZ-1: Primary (can't reach secondaries in AZ-2)             │
│  AZ-2: Secondaries (can't reach primary in AZ-1)             │
│                                                              │
│  What happens:                                               │
│  → Secondaries in AZ-2 hold an election                      │
│  → They elect a NEW primary (among themselves)               │
│  → Now there are TWO primaries!                              │
│  → Both accepting writes → data DIVERGES                     │
│                                                              │
│  This is SPLIT-BRAIN — the worst failure in CP systems.      │
│                                                              │
│  MongoDB's defense: Majority requirement for election.       │
│  → 3-node replica set: majority = 2                          │
│  → AZ-1 has 1 node (primary) → can't form majority → steps   │ 
│    down to secondary → STOPS accepting writes                │
│  → AZ-2 has 2 nodes → CAN form majority → elects new primary │
│  → Only ONE primary exists at any time                       │
│                                                              │
│  BUT: what if the partition is 2-1 the other way?            │
│  → AZ-1: 2 nodes (primary + secondary)                       │
│  → AZ-2: 1 node (secondary)                                  │
│  → AZ-1 has majority → primary continues                     │
│  → AZ-2 can't form majority → read-only (or unavailable)     │
│  → Clean. No split-brain.                                    │
│                                                              │
│  KEY PRINCIPLE: Always have an ODD number of voting          │
│  members. 3, 5, 7 — never 2, 4, 6. Even numbers              │
│  can split exactly in half with no majority.                 │
├──────────────────────────────────────────────────────────────┤
│  PRODUCTION PATTERN #2: STALE READS AFTER FAILOVER           │
│                                                              │
│  Scenario: PostgreSQL with async replication.                │
│  Primary crashes. Replica is promoted to primary.            │
│                                                              │
│  Problem: The replica was BEHIND the old primary.            │
│  Some committed transactions on the old primary hadn't       │
│  been replicated yet.                                        │
│                                                              │
│  → Old primary: WAL position 1000 (crashed)                  │
│  → Replica: WAL position 980 (20 entries behind)             │
│  → Replica promoted → new primary at position 980            │
│  → Those 20 transactions are LOST.                           │
│                                                              │
│  This is the EL (Else Latency) cost of async replication.    │
│  You got faster writes (EL) but lost data on failover.       │
│                                                              │
│  Fix:                                                        │
│  → Synchronous replication (EC): primary waits for           │
│    replica ACK before committing. No data loss on failover.  │
│    Cost: ~2ms extra latency per write (within same DC).      │
│  → Semi-synchronous: wait for at least ONE replica.          │
│    Tolerate loss only if primary AND that one replica        │
│    fail simultaneously (extremely unlikely).                 │
│                                                              │
│  PRODUCTION DECISION:                                        │
│  → Financial data: synchronous (EC). 2ms is acceptable.      │
│  → User activity data: async (EL). Losing 20 events          │
│    on failover is acceptable.                                │
├──────────────────────────────────────────────────────────────┤
│  PRODUCTION PATTERN #3: CHOOSING WRONG CAP FOR THE FEATURE   │
│                                                              │
│  Scenario: Team uses Cassandra (PA/EL) for an inventory      │
│  management system. Two warehouses.                          │
│                                                              │
│  What breaks:                                                │
│  → Warehouse A: reads stock = 1 (from local Cassandra node)  │
│  → Warehouse B: reads stock = 1 (from its local node)        │
│  → Both "sell" the last item simultaneously                  │
│  → Stock is now -1 (oversold)                                │
│                                                              │
│  The team chose AP (Cassandra) for a feature that            │
│  requires CP (inventory). Stale reads caused overselling.    │
│                                                              │
│  Fix: Use PostgreSQL (PC/EC) for inventory.                  │
│  Cassandra is fine for product descriptions, reviews,        │
│  and analytics — but NOT for inventory counts.               │
│                                                              │
│  THIS IS THE MOST COMMON CAP MISTAKE IN PRODUCTION:          │
│  Using one database for everything instead of choosing       │
│  the right consistency model PER FEATURE.                    │
╰──────────────────────────────────────────────────────────────╯
```

---

## Step 4: Hands-On Exercises

```
╭──────────────────────────────────────────────────────────────╮
│  EXERCISE 1: Observe a Partition in Redis Cluster            │
│                                                              │
│  # Start a 3-node Redis Cluster with Docker Compose          │
│  # (use a redis-cluster docker image or create manually)     │
│                                                              │
│  # Write a key:                                              │
│  redis-cli -c -p 7000 SET mykey "hello"                      │
│  # Note which node owns it (redis-cli shows the redirect)    │
│                                                              │
│  # Read from another node:                                   │
│  redis-cli -c -p 7001 GET mykey                              │
│  # Returns "hello" — cluster redirects to the right node     │
│                                                              │
│  # NOW: simulate a partition by pausing a container:         │
│  docker pause redis-node-1                                   │
│                                                              │
│  # Try to read the key that was on node 1:                   │
│  redis-cli -c -p 7001 GET mykey                              │
│  # What happens?                                             │
│  # → If the key was on node 1: CLUSTERDOWN or redirect       │
│  #   to node 1's replica (if it has one and failover happens)│
│  # → If the key was on another node: works fine              │
│                                                              │
│  # Try to write a key that routes to node 1:                 │
│  redis-cli -c -p 7001 SET newkey "world"                     │
│  # If newkey routes to node 1's slots: error                 │
│  # If it routes to node 2 or 3's slots: success              │
│                                                              │
│  # OBSERVE: Redis Cluster is PA for reads (returns what      │
│  # it has) but PC for writes to the downed node's slots      │
│  # (refuses writes it can't guarantee).                      │
│  # After failover: replica takes over, writes resume.        │
│                                                              │
│  # Unpause:                                                  │
│  docker unpause redis-node-1                                 │
│  # Node 1 rejoins. If a failover happened, node 1 becomes    │
│  # a replica of the new master for those slots.              │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 2: Observe Consistency Differences                 │
│                                                              │
│  # Using PostgreSQL with 1 primary + 1 async replica:        │
│  # (docker-compose with pg primary and standby)              │
│                                                              │
│  # Terminal 1 (write to primary):                            │
│  psql -h primary -c "INSERT INTO test VALUES (1, 'hello');"  │
│                                                              │
│  # Terminal 2 (IMMEDIATELY read from replica):               │
│  psql -h replica -c "SELECT * FROM test WHERE id = 1;"       │
│                                                              │
│  # If you're fast enough: row might not be there yet!        │
│  # This is EL — async replication means the replica is       │
│  # briefly behind.                                           │
│                                                              │
│  # Now switch to SYNCHRONOUS replication:                    │
│  psql -h primary -c "ALTER SYSTEM SET                        │
│    synchronous_standby_names = 'replica1';"                  │
│  psql -h primary -c "SELECT pg_reload_conf();"               │
│                                                              │
│  # Repeat the test:                                          │
│  # Terminal 1: INSERT                                        │
│  # Terminal 2: SELECT (immediately)                          │
│  # Row IS there. Every time. This is EC.                     │
│                                                              │
│  # But: measure the write latency difference.                │
│  # Async: INSERT takes ~1ms                                  │
│  # Sync: INSERT takes ~3ms (waiting for replica ACK)         │
│  # That's the PACELC tradeoff in action: EC costs latency.   │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 3: Cassandra Tunable Consistency                   │
│                                                              │
│  # If you have a Cassandra cluster (or use ccm for local):   │
│                                                              │
│  # Write at CL=ONE:                                          │
│  cqlsh -e "CONSISTENCY ONE;                                  │
│    INSERT INTO test.data (id, value) VALUES (1, 'hello');"   │
│  # Returns immediately — wrote to 1 node only                │
│                                                              │
│  # Read at CL=ONE from a DIFFERENT node:                     │
│  # (might return nothing if the write hasn't propagated)     │
│                                                              │
│  # Write at CL=QUORUM:                                       │
│  cqlsh -e "CONSISTENCY QUORUM;                               │
│    INSERT INTO test.data (id, value) VALUES (2, 'world');"   │
│  # Takes slightly longer — waited for 2 of 3 nodes           │
│                                                              │
│  # Read at CL=QUORUM:                                        │
│  # Guaranteed to see the write (R + W > N → overlap)         │
│                                                              │
│  # OBSERVE: Same database, same data, different              │
│  # consistency guarantees based on CL setting.               │
│  # This is PACELC in action: you choose the tradeoff         │
│  # PER QUERY, not per database.                              │
╰──────────────────────────────────────────────────────────────╯
```

---

## Step 5: SRE Scenario

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

---

## Step 6: Targeted Reading

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

## Step 7: Key Takeaways

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

# Incident Deep-Dive: Cross-Region Partition on a Financial Trading Platform

---

## Question 1: PACELC Classification of Every Component

### PACELC Refresher

```
PACELC: "If there's a Partition (P), choose Availability (A) 
or Consistency (C). Else (E), choose Latency (L) or 
Consistency (C)."

Every distributed system makes these choices — 
explicitly or accidentally.
```

### PostgreSQL (Trade Records, Account Balances)

```
CURRENT BEHAVIOR:
  
  Normal operation (E):
    → EL (Else Latency)
    → Async replication: US primary commits immediately 
      without waiting for EU replica to acknowledge
    → EU reads go to local replica (fast, ~1ms)
    → Trade-off: EU reads may be 50-80ms stale, but 
      reads are FAST

  During partition (P):
    → PA (Partition Availability)
    → EU replica continues serving reads despite 
      growing lag (4.2s → 12.8s)
    → Writes still go to US primary (succeeds for US users)
    → EU users can READ (stale data) but writes are 
      routed to US primary (slow/failing due to cable)
    → System chose AVAILABILITY over CONSISTENCY:
      it serves stale balances rather than refusing reads

IS THIS THE RIGHT CHOICE?

  FOR TRADE RECORDS: PA/EL is WRONG.

  Account balances are FINANCIAL DATA. A stale read 
  directly caused Alice to overdraw by $20,000. Three 
  trades exceeded balance limits, creating $340,000 in 
  uncontrolled exposure. In financial systems, a wrong 
  answer is WORSE than no answer.

  SHOULD BE: PC/EC
    → During partition: REFUSE reads from stale replica 
      for balance-critical operations (trade approval)
    → Normal operation: accept slightly higher latency 
      to ensure reads reflect committed state
    → The cost of a rejected trade (user frustration, 
      lost trading opportunity) is VASTLY less than the 
      cost of an unauthorized overdraft (regulatory fine, 
      financial loss, legal liability)

  FOR READ-ONLY QUERIES (trade history, statements):
    → PA/EL is ACCEPTABLE
    → Showing a trade history that's 4 seconds behind 
      is annoying but not dangerous
    → No financial decision depends on this read
```

### Cassandra (Market Data Feed)

```
CURRENT BEHAVIOR:

  Normal operation (E):
    → EL (Else Latency)
    → LOCAL_QUORUM reads: only need quorum within 
      the LOCAL datacenter
    → Fast reads (~3-5ms) from local nodes
    → Cross-DC consistency happens asynchronously

  During partition (P):
    → PA (Partition Availability)
    → LOCAL_QUORUM means each DC operates independently
    → EU-West continues serving market data from its 
      local nodes
    → But that data is 320ms+ stale (cross-DC replication 
      delayed by cable degradation)
    → System chose AVAILABILITY: serve stale prices 
      rather than refusing market data queries

IS THIS THE RIGHT CHOICE?

  PARTIALLY RIGHT, PARTIALLY WRONG.

  For DISPLAYING prices to traders (informational):
    → PA/EL is ACCEPTABLE with a warning
    → Traders can see prices are delayed and adjust 
      their behavior
    → Every trading platform has a "prices may be delayed" 
      disclaimer
    → 320ms staleness should be SURFACED to the user, 
      not hidden

  For EXECUTING TRADES based on these prices:
    → PA/EL is DANGEROUS
    → A trader sees a stale price and submits a market 
      order expecting that price
    → By the time the order reaches the matching engine, 
      the real price may have moved significantly
    → In volatile markets, 320ms of price staleness can 
      mean thousands of dollars per trade
    → Trade execution should use REAL-TIME prices from 
      the authoritative source, not stale cached data

  SHOULD BE: Mixed
    → Display: PA/EL (show stale prices with "delayed" flag)
    → Execution: PC/EC (trade orders must use prices from 
      the authoritative market data source, even if slower)
```

### Redis (Order Book Cache, Sessions)

```
CURRENT BEHAVIOR:

  Normal operation (E):
    → EL (Else Latency)
    → Independent clusters per region
    → Local reads, ~0.3ms latency
    → No cross-region consistency needed for sessions

  During partition (P):
    → PA (Partition Availability)
    → Each Redis cluster is independent and unaffected 
      by the cross-region partition
    → Sessions work fine (local only)
    → BUT: order book cache is populated from Cassandra 
      market data, which is stale → order book is stale

IS THIS THE RIGHT CHOICE?

  For SESSIONS: PA/EL is CORRECT.
    → Sessions are inherently per-region
    → No cross-region dependency
    → Availability is the right choice

  For ORDER BOOK CACHE: The Redis cluster itself is fine.
    → The problem isn't Redis — it's the DATA FLOWING 
      INTO Redis from stale Cassandra data
    → Redis is faithfully caching what it's told to cache
    → The staleness is upstream (Cassandra), not in Redis
    → CORRECT CHOICE: Redis should cache what it receives, 
      but the APPLICATION should mark order book data with 
      a staleness indicator based on the source timestamp
```

### API Gateway (Regional Routing)

```
CURRENT BEHAVIOR:

  Normal operation (E):
    → EL (Else Latency)
    → Routes users to nearest region
    → Minimizes latency

  During partition (P):
    → PA (Partition Availability)
    → Continues routing EU users to EU-West
    → EU-West is "available" but serving stale/dangerous data
    → Does NOT failover EU users to US-East

IS THIS THE RIGHT CHOICE?

  WRONG for trade-critical operations.

  The API gateway should be AWARE of partition conditions 
  and make per-feature routing decisions:

  → Browsing, market data display: route to EU-West (PA/EL)
    → Stale but fast — acceptable with staleness indicator
  
  → Trade execution, balance checks: route to US-East (PC/EC)
    → Slower (320ms+ latency) but CORRECT data
    → A trade that takes 400ms is better than a trade 
      that causes a $20,000 overdraft
```

### PACELC Summary Table

```
╭──────────────┬──────────┬──────────┬──────────────────────────╮
│ COMPONENT    │ CURRENT  │ SHOULD BE│ WHY                      │
├──────────────┼──────────┼──────────┼──────────────────────────┤
│ PostgreSQL   │ PA/EL    │ PC/EC    │ Stale balance reads      │
│ (balances)   │          │ for      │ cause overdrafts.        │
│              │          │ balance  │ Wrong answer > no answer │
│              │          │ checks   │ is NEVER true for money. │
├──────────────┼──────────┼──────────┼──────────────────────────┤
│ PostgreSQL   │ PA/EL    │ PA/EL    │ Stale trade history is   │
│ (history)    │          │ (OK)     │ annoying, not dangerous. │
├──────────────┼──────────┼──────────┼──────────────────────────┤
│ Cassandra    │ PA/EL    │ PA/EL    │ Stale price DISPLAY is   │
│ (display)    │          │ + stale  │ OK with warning flag.    │
│              │          │ warning  │                          │
├──────────────┼──────────┼──────────┼──────────────────────────┤
│ Cassandra    │ PA/EL    │ PC/EC    │ Trade execution on stale │
│ (execution)  │          │ for trade│ prices = financial risk. │
│              │          │ execution│                          │
├──────────────┼──────────┼──────────┼──────────────────────────┤
│ Redis        │ PA/EL    │ PA/EL    │ Sessions are local.      │
│ (sessions)   │          │ (OK)     │ No cross-region need.    │
├──────────────┼──────────┼──────────┼──────────────────────────┤
│ Redis        │ PA/EL    │ PA/EL    │ Cache is correct; the    │
│ (order book) │          │ + stale  │ staleness is upstream.   │
│              │          │ indicator│ Surface it, don't hide.  │
├──────────────┼──────────┼──────────┼──────────────────────────┤
│ API Gateway  │ PA/EL    │ Per-     │ Route reads to local     │
│              │          │ feature  │ (PA/EL). Route writes    │
│              │          │ routing  │ and balance checks to    │
│              │          │          │ primary region (PC/EC).  │
╰──────────────┴──────────┴──────────┴──────────────────────────╯

THE CORE LESSON:
  Not every piece of data in a system deserves the same 
  PACELC treatment. The system architect must classify 
  data BY CONSEQUENCE OF STALENESS:

  "What happens if this read is 5 seconds stale?"
    → Trade history: User sees old data. Annoying. → PA/EL
    → Market prices: Trader sees old price. Risky. → PA/EL with warning
    → Account balance for trade approval: Overdraft. → PC/EC
    → Balance for display: User confused. → PA/EL with warning
```

---

## Question 2: Alice's $120,000 Trade — What Went Wrong

### a) In PACELC Terms

```
The system was configured as PA/EL for account balances.

During the partition:
  → The system chose AVAILABILITY: it continued serving 
    reads from the EU replica even though the replica 
    was 4.2 seconds behind the primary
  → Specifically: the TRADE APPROVAL service read 
    Alice's balance from the EU replica
  → The EU replica showed $150,000 (stale)
  → The US primary had $100,000 (current)
  → The trade was approved based on stale data

The system made the WRONG PA choice for this data:

  It should have been PC: during a partition, REFUSE 
  to read balance data from the stale replica for 
  trade approval purposes. Either:
    a) Read from the US primary (slower but correct), or
    b) Reject the trade entirely ("balance check 
       unavailable, please retry")

  Alice would have been annoyed if her trade was delayed 
  or rejected. But she wouldn't be $20,000 in the red.

  THE FUNDAMENTAL ERROR:
  The system treated account-balance-for-trade-approval 
  the same as account-balance-for-display. These are 
  DIFFERENT operations with DIFFERENT consistency 
  requirements, but they read from the same table 
  with the same replication configuration.
```

### b) Two Architectural Fixes with Different PACELC Tradeoffs

### Fix 1: Route Balance Checks for Trade Approval to Primary (PC/EC)

```
DESIGN:
  → Trade approval service ALWAYS reads balance from 
    US-East primary, regardless of which region the 
    trader is in
  → All other balance reads (display, history) can 
    use the local replica

  Code:
  async def approve_trade(user_id, trade_amount):
      # CRITICAL: read from PRIMARY, not replica
      balance = await primary_db.fetch_one(
          "SELECT balance FROM accounts WHERE user_id = $1 "
          "FOR UPDATE",  # Lock the row during approval
          user_id
      )
      
      if balance < trade_amount:
          raise InsufficientFunds()
      
      # Execute trade against primary
      await primary_db.execute(
          "UPDATE accounts SET balance = balance - $1 "
          "WHERE user_id = $2",
          trade_amount, user_id
      )

PACELC CLASSIFICATION: PC/EC
  
  During partition (P → C):
    → EU trade approval MUST reach US primary
    → If the cable is degraded (320ms-850ms latency), 
      the trade takes 320-850ms longer
    → If the cable is completely down, the trade FAILS 
      ("unable to verify balance")
    → Consistency is GUARANTEED: balance check is always 
      against the source of truth

  Else (E → C):
    → Even in normal operation, EU trade approvals take 
      ~80ms extra (cross-Atlantic round trip to primary)
    → Every single trade has this latency cost
    → Balance is always consistent

EXPLICIT TRADEOFF:
  SACRIFICE: Latency. Every EU trade takes 80ms+ longer 
  (normal) to 850ms+ longer (degraded cable). Some trades 
  fail entirely during severe partitions.
  
  GAIN: Correctness. No trade can ever be approved based 
  on stale balance data. Alice's overdraft becomes impossible.

  For a FINANCIAL PLATFORM: 80ms extra latency is invisible 
  to a human trader. $20,000 overdraft is catastrophic.
  This is the correct tradeoff.
```

### Fix 2: EU-West Maintains Independent Balance Authority with Conservative Limits (PA/EC)

```
DESIGN:
  → Each region maintains an ALLOCATED TRADING LIMIT 
    for each account
  → US-East primary sets: "Alice can trade up to $80,000 
    through EU-West" (a conservative fraction of her 
    actual $100,000 balance)
  → EU-West has a LOCAL balance ledger that tracks trades 
    against this allocation
  → EU-West can approve trades LOCALLY without contacting 
    US-East, as long as the allocated limit isn't exceeded
  → Periodically (every few seconds), regions reconcile 
    allocations

  Code:
  # EU-West local trade approval:
  async def approve_trade_local(user_id, trade_amount):
      # Read from LOCAL allocation table (EU Redis or EU PostgreSQL)
      allocation = await local_db.fetch_one(
          "SELECT remaining_allocation FROM regional_allocations "
          "WHERE user_id = $1 FOR UPDATE",
          user_id
      )
      
      if allocation.remaining < trade_amount:
          # Local allocation exhausted — cannot approve locally
          # Option: try primary (slower) or reject
          raise InsufficientLocalAllocation()
      
      # Approve locally — deduct from allocation
      await local_db.execute(
          "UPDATE regional_allocations "
          "SET remaining_allocation = remaining_allocation - $1 "
          "WHERE user_id = $2",
          trade_amount, user_id
      )
      
      # Async: notify primary of the trade for reconciliation
      await event_bus.publish("trade_executed", {
          "user_id": user_id, 
          "amount": trade_amount,
          "region": "eu-west"
      })

PACELC CLASSIFICATION: PA/EC

  During partition (P → A):
    → EU-West continues approving trades LOCALLY
    → No need to contact US primary
    → System remains AVAILABLE during partition
    → BUT: limited to the pre-allocated amount
    → Alice with $100K balance and $80K EU allocation 
      can trade up to $80K in EU without contacting US
    → Her $120K trade would be REJECTED (exceeds $80K 
      allocation), even though EU is "available"
    → Overdraft PREVENTED by the conservative allocation

  Else (E → C):
    → Normal operation: allocations are refreshed every 
      few seconds via cross-region sync
    → Allocations reflect near-real-time balance
    → Slightly more complex than direct primary reads
    → Consistency maintained through allocation accounting

EXPLICIT TRADEOFF:
  SACRIFICE: Maximum trading capacity per region. Alice can 
  only trade $80K in EU even though she has $100K. The other 
  $20K is "reserved" for US-East trades or as safety margin.
  
  GAIN: Availability. EU trades continue even during a 
  complete partition. No cross-region call required for 
  trades within the allocation.

  ADDITIONAL COMPLEXITY: Allocation management, reconciliation 
  logic, handling allocation exhaustion, rebalancing allocations 
  as traders move between regions.
```

### Comparison

```
╭────────────────────┬──────────────────┬──────────────────────╮
│                    │ FIX 1: Read from │ FIX 2: Regional      │
│                    │ Primary (PC/EC)  │ Allocation (PA/EC)   │
├────────────────────┼──────────────────┼──────────────────────┤
│ During partition   │ Trades SLOW or   │ Trades FAST but      │
│                    │ FAIL if primary  │ LIMITED to allocation│
│                    │ unreachable      │                      │
├────────────────────┼──────────────────┼──────────────────────┤
│ Normal operation   │ +80ms latency on │ No extra latency     │
│                    │ every EU trade   │ for normal trades    │
├────────────────────┼──────────────────┼──────────────────────┤
│ Overdraft risk     │ ZERO             │ ZERO (within alloc)  │
├────────────────────┼──────────────────┼──────────────────────┤
│ Complexity         │ LOW              │ HIGH (reconciliation,│
│                    │ (route to primary│ allocation mgmt,     │
│                    │  for approvals)  │ rebalancing)         │
├────────────────────┼──────────────────┼──────────────────────┤
│ Complete partition │ EU trading STOPS │ EU trading continues │
│ (cable cut)        │                  │ (within allocation)  │
├────────────────────┼──────────────────┼──────────────────────┤
│ Best for           │ Most platforms   │ High-frequency       │
│                    │ (simple, safe)   │ trading requiring    │
│                    │                  │ local latency        │
╰────────────────────┴──────────────────┴──────────────────────╯
```

---

## Question 3: Synchronous Cross-Region Replication — Good Idea?

### The Architect's Proposal

```
"Switch PostgreSQL to synchronous replication between 
US-East (primary) and EU-West (replica). Every write 
must be acknowledged by BOTH regions before committing."

This would mean: no write completes until the EU replica 
has confirmed it received and applied the WAL.

Would this have prevented Alice's trade?
YES — the EU replica would never be behind the primary, 
so Alice's balance read would have been $100,000 (correct).
```

### Arguing FOR Synchronous Replication

```
CASE FOR:

1. CONSISTENCY GUARANTEE:
   → EU replica is ALWAYS in sync with US primary
   → No stale reads, ever
   → Alice's overdraft is structurally impossible
   → All 3 trades that exceeded balance limits would 
     have been correctly rejected

2. SIMPLICITY:
   → No need for per-feature routing (Q2 Fix 1)
   → No need for allocation management (Q2 Fix 2)
   → No need to classify data by consistency requirements
   → The replica IS the primary in terms of data freshness
   → Application code doesn't change

3. REGULATORY COMPLIANCE:
   → Financial regulators require accurate balance reporting
   → Synchronous replication provides the strongest 
     guarantee that all reads reflect committed state
   → Simplifies audit trail: "our replica is always consistent"

PACELC: PC/EC
  → During partition: writes BLOCK until the replica 
    confirms (or timeout → write fails)
  → Else: every write pays the cross-Atlantic RTT 
    (80ms) for consistency
```

### Arguing AGAINST Synchronous Replication

```
CASE AGAINST:

1. LATENCY ON EVERY WRITE — ALWAYS:
   → Normal cross-Atlantic RTT: 80ms
   → EVERY write to the US primary now takes +80ms 
     minimum (waiting for EU replica ACK)
   → Trade execution: 2ms → 82ms (41x slower)
   → High-frequency trading: 82ms per trade is 
     UNACCEPTABLE for US traders
   → The EU consistency guarantee penalizes ALL traders, 
     including US traders who don't need it

2. AVAILABILITY CLIFF DURING PARTITION:
   → When the cable degrades (320ms-850ms latency):
     → Every US write takes +320ms to +850ms
     → US traders are now penalized by EU infrastructure
     → If the cable drops completely: ALL WRITES STOP
     → The US primary CANNOT commit any trade because 
       it's waiting for EU ACK that will never come
     → Timeout eventually releases the write, but until 
       then, the ENTIRE PLATFORM is frozen
     → A cable problem between continents shuts down 
       US domestic trading — that's absurd

   → In this specific incident:
     → 14:00: writes go from 2ms to 322ms (+320ms RTT)
     → 14:07: writes go from 2ms to 852ms (+850ms RTT)
     → At 23% packet loss: 23% of write ACKs are lost
     → Lost ACKs trigger timeouts (5-30 seconds)
     → 23% of ALL writes across the entire platform 
       take 5-30 seconds or fail entirely
     → US trading grinds to a halt

3. SINGLE POINT OF FAILURE:
   → Synchronous replication makes the EU replica a 
     CRITICAL dependency for US writes
   → EU datacenter power outage → US writes stop
   → EU network issue → US writes degraded
   → This VIOLATES the principle of regional independence
   → The whole point of multi-region is that one region's 
     failure shouldn't cripple another

4. THIS INCIDENT SPECIFICALLY:
   → At 14:07, cable degradation worsening
   → Synchronous replication would mean:
     → US trades: 2ms → 852ms (425x slower)
     → 23% of US writes timeout entirely
     → US traders can't trade because of EU cable problem
     → You've traded Alice's $20K overdraft for 
       PLATFORM-WIDE TRADING HALT
     → The cure is worse than the disease
```

### My Recommendation

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   RECOMMENDATION: DO NOT use synchronous cross-region        ║
║   replication for the entire database.                       ║
║                                                              ║
║   INSTEAD: Use FIX 1 from Q2 (route balance checks           ║
║   to primary) for trade-critical operations ONLY.            ║
║                                                              ║
║   REASONING:                                                 ║
║                                                              ║
║   Synchronous replication is a BLUNT INSTRUMENT.             ║
║   It forces EVERY write across the entire database           ║
║   to pay the cross-region latency tax, including             ║
║   writes that don't need cross-region consistency            ║
║   (analytics events, session updates, audit logs).           ║
║                                                              ║
║   The problem isn't "all EU reads are stale."                ║
║   The problem is "BALANCE CHECKS for trade approval          ║
║   are stale." That's ONE specific read path.                 ║
║                                                              ║
║   Fix the ONE path that needs consistency (route             ║
║   balance checks to primary). Leave everything               ║
║   else async for performance.                                ║
║                                                              ║
║   This is the per-feature PACELC approach:                   ║
║   → Trade approval balance check: PC/EC (read primary)       ║
║   → Everything else: PA/EL (read local replica)              ║
║                                                              ║
║   Cost of Fix 1: +80ms on EU trade approvals                 ║
║   Cost of sync repl: +80ms on ALL writes, platform           ║
║   halt during partition, EU failure affects US               ║
║                                                              ║
║   The targeted fix is STRICTLY BETTER than the               ║
║   blunt instrument for this use case.                        ║
║                                                              ║
║   EXCEPTION: If regulatory requirements MANDATE              ║
║   synchronous replication (some financial regulators         ║
║   require it), then use synchronous replication to           ║
║   a SECOND replica within the SAME REGION, not               ║
║   cross-region. This gives durability without the            ║
║   cross-Atlantic latency penalty.                            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 4: Should EU-West Continue Operating?

### The Decision Framework: Per-Feature CAP Analysis

```
At 14:07:
  → Cross-region latency: 850ms (and worsening)
  → Packet loss: 23% (and worsening)
  → PostgreSQL replication lag: 12.8 seconds
  → 3 trades already exceeded balance limits
  → Total unauthorized exposure: $340,000
  → Cable degradation is getting WORSE, not better

The question: continue EU-West operations or redirect 
EU users to US-East?

This is NOT an all-or-nothing decision. Apply the 
per-feature CAP framework:
```

### Decision: SPLIT EU-West Operations by Feature

```
╭─────────────────────┬──────────────┬────────────────────────╮
│ FEATURE             │ DECISION     │ REASONING              │
├─────────────────────┼──────────────┼────────────────────────┤
│ TRADE EXECUTION     │ SHUT DOWN    │ Every trade risks      │
│                     │ in EU-West.  │ overdraft. 12.8s stale │
│                     │ Route to     │ balance = no meaningful│
│                     │ US-East.     │ balance check. $340K   │
│                     │              │ exposure already.      │
│                     │              │ REGULATORY RISK.       │
│                     │              │ Latency via US: 850ms. │
│                     │              │ Unpleasant but SAFE.   │
├─────────────────────┼──────────────┼────────────────────────┤
│ MARKET DATA         │ KEEP in      │ LOCAL_QUORUM reads     │
│ DISPLAY             │ EU-West.     │ from local Cassandra   │
│                     │ Add "DELAYED"│ work fine. Data is     │
│                     │ banner.      │ 320ms+ stale but       │
│                     │              │ traders can see prices.│
│                     │              │ Surfacing staleness    │
│                     │              │ lets traders decide.   │
├─────────────────────┼──────────────┼────────────────────────┤
│ PORTFOLIO VIEW /    │ KEEP in      │ Stale by 12.8s.        │
│ BALANCE DISPLAY     │ EU-West.     │ Add "BALANCE AS OF     │
│                     │ Add staleness│ [timestamp]" indicator.│
│                     │ indicator.   │ Not used for decisions.│
├─────────────────────┼──────────────┼────────────────────────┤
│ ORDER BOOK          │ KEEP in      │ Cached from Cassandra. │
│ (READ-ONLY VIEW)    │ EU-West.     │ Stale but usable for   │
│                     │ Add "DELAYED"│ market awareness.      │
│                     │ banner.      │                        │
├─────────────────────┼──────────────┼────────────────────────┤
│ ACCOUNT MANAGEMENT  │ Route to     │ Password changes,      │
│ (WRITES)            │ US-East.     │ withdrawals, transfers │
│                     │              │ must hit primary.      │
│                     │              │ 850ms latency is fine  │
│                     │              │ for infrequent ops.    │
├─────────────────────┼──────────────┼────────────────────────┤
│ SESSIONS / AUTH     │ KEEP in      │ EU Redis is independent│
│                     │ EU-West.     │ and healthy. No reason │
│                     │              │ to disrupt sessions.   │
╰─────────────────────┴──────────────┴────────────────────────╯
```

### Justification

```
WHY NOT SHUT DOWN EU-WEST ENTIRELY?

  → Redirecting ALL EU users to US-East means:
    → 850ms latency on EVERY API call (browsing, 
      viewing portfolio, checking prices)
    → At 23% packet loss, many requests will timeout
    → US-East must absorb ALL EU traffic (capacity risk)
    → Users who are just WATCHING the market (not trading) 
      get a terrible experience for no safety benefit

  → The risk is specifically in TRADE EXECUTION using 
    stale balance data. That's the only feature that 
    needs to be shut down in EU.

WHY NOT KEEP EU-WEST TRADING ALIVE?

  → Replication lag is 12.8 seconds and GROWING
  → 23% packet loss means even routing to primary for 
    balance checks is unreliable
  → At this degradation level, the cable may drop entirely
  → $340,000 in unauthorized exposure already exists
  → Every minute of continued EU trading adds risk
  → The REGULATORY COST of further overdrafts dwarfs 
    the BUSINESS COST of EU trading being unavailable

THE DECISION IS CLEAR:
  Shut down the feature that's DANGEROUS (trade execution).
  Keep the features that are SAFE (read-only views with 
  staleness indicators).

  This is the per-feature CAP approach in action:
  → Trade execution: choose CONSISTENCY (route to US primary)
  → Everything else: choose AVAILABILITY (serve from EU local)
```

### Implementation

```python
# Feature-level routing in the API Gateway:

async def route_request(request):
    partition_detected = cable_health.degraded()  # True at 14:07
    
    if partition_detected:
        if request.path.startswith('/api/trades/execute'):
            # TRADE EXECUTION → US-East primary
            return route_to_region('us-east', request)
        
        if request.path.startswith('/api/account/withdraw'):
            # FINANCIAL WRITES → US-East primary
            return route_to_region('us-east', request)
        
        if request.path.startswith('/api/trades/approve'):
            # TRADE APPROVAL → US-East primary
            return route_to_region('us-east', request)
        
        # All other requests → local EU-West (with staleness headers)
        response = await route_to_region('eu-west', request)
        response.headers['X-Data-Staleness'] = f'{replication_lag_ms}ms'
        response.headers['X-Partition-Mode'] = 'degraded'
        return response
    
    # Normal operation — route to nearest region
    return route_to_nearest(request)
```

---

## Question 5: Mitigation Plan

### Priority Framework

```
This is a FINANCIAL PLATFORM.
  → Incorrect balances = REGULATORY violation
  → Trades beyond limits = FINANCIAL liability
  → $340,000 in unauthorized exposure = IMMEDIATE RISK
  → Every minute adds more exposure

PRIORITY: Stop financial risk FIRST, fix infrastructure SECOND.
```

### Step 1: HALT EU-West Trade Execution (Second 0-60)

```bash
# IMMEDIATE: Stop all trade execution in EU-West.
# This prevents any further trades based on stale balances.

# Option A: Feature flag (fastest if available)
kubectl set env deployment/api-gateway -n eu-west \
  EU_TRADE_EXECUTION=disabled \
  TRADE_ROUTE_OVERRIDE=us-east

# Option B: API Gateway rule to redirect trade endpoints
# Add routing rule: /api/trades/* → us-east-alb
kubectl apply -f - <<EOF
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: trade-execution-failover
  namespace: eu-west
spec:
  hosts:
    - api.trading.example.com
  http:
    - match:
        - uri:
            prefix: /api/trades/execute
        - uri:
            prefix: /api/trades/approve
      route:
        - destination:
            host: us-east-alb.trading.internal
    - route:
        - destination:
            host: eu-west-api.trading.internal
EOF

# EU traders will now experience 850ms+ latency on trades
# but ALL trades will be checked against the primary DB.

# VERIFY:
# → No new "exceeded balance limits" alerts
# → EU trade execution latency: ~1-2 seconds 
#   (850ms network + processing)
# → EU trades succeeding (slowly) or failing gracefully 
#   if timeout exceeded
# → US-East trade execution: unaffected
```

**VERIFY before proceeding:**
```
→ Risk management alerts: no new balance limit violations
→ EU trade flow: executing against US-East primary
→ US-East: absorbing EU trade load without pool exhaustion
```

### Step 2: Notify Risk Management and Compliance (Second 0-120, Parallel)

```
IMMEDIATE NOTIFICATION (parallel with Step 1):

  TO: Risk Management, Compliance, Trading Floor Manager

  SUBJECT: P1 INCIDENT — Cross-region partition, unauthorized 
  trade exposure

  BODY:
  - 3 trades in EU-West exceeded account balance limits
  - Total unauthorized exposure: $340,000
  - Root cause: stale balance reads from EU replica 
    during cross-Atlantic cable degradation
  - Replication lag: 12.8 seconds (and growing)
  - EU trade execution has been halted/redirected to US-East
  - Affected accounts identified:
    [Alice: $20K overdraft, accounts 2 and 3: details]
  
  REQUIRED ACTIONS:
  - Risk team: review all EU trades from 14:00-14:07 
    for potential balance violations
  - Compliance: assess regulatory notification requirements
  - Trading desk: may need to unwind affected positions
```

```sql
-- Identify ALL potentially affected trades:
SELECT t.trade_id, t.user_id, t.amount, t.executed_at,
       t.region, a.current_balance,
       (a.current_balance - t.amount) AS post_trade_balance
FROM trades t
JOIN accounts a ON t.user_id = a.user_id
WHERE t.region = 'eu-west'
  AND t.executed_at >= '2024-01-15 14:00:00'
  AND t.amount > a.current_balance
ORDER BY (t.amount - a.current_balance) DESC;

-- This finds all EU trades where the trade amount 
-- exceeded the ACTUAL balance at time of execution
```

### Step 3: Add Staleness Indicators to EU-West Read Paths (Minute 2-5)

```python
# EU users can still browse, view prices, check portfolios.
# But all read-only endpoints should surface staleness.

# Middleware for EU-West API servers:
class StalenessIndicatorMiddleware:
    async def process_response(self, request, response):
        if CABLE_DEGRADED:
            # Calculate replication lag
            lag = await get_replication_lag()  # 12.8 seconds
            
            response.headers['X-Data-Staleness-Seconds'] = str(lag)
            response.headers['X-Partition-Mode'] = 'degraded'
            
            # Inject banner into HTML responses:
            if 'text/html' in response.content_type:
                banner = (
                    '<div class="staleness-warning">'
                    f'⚠️ Data may be up to {int(lag)} seconds delayed '
                    'due to network issues. Trade execution is routed '
                    'to the primary datacenter for accuracy.'
                    '</div>'
                )
                response.body = banner + response.body
        
        return response
```

```bash
kubectl set env deployment/api-service -n eu-west \
  SHOW_STALENESS_BANNER=true \
  STALENESS_BANNER_THRESHOLD_SEC=2

# VERIFY:
# → EU users see staleness banner on all pages
# → No new customer complaints about "wrong balance" 
#   (they understand the delay)
```

### Step 4: Monitor Cable Recovery and Prepare Failback (Minute 5+)

```bash
# Monitor the cross-region link:
watch -n 10 "ping -c 5 eu-west-gateway.internal | tail -1; \
  echo 'PG Replication Lag:'; \
  psql -h us-east-primary -c \"SELECT now() - pg_last_xact_replay_timestamp() AS lag FROM eu_west_replica;\""

# Decision tree:
#
# IF cable improves (latency < 200ms, packet loss < 2%):
#   → Wait for replication lag to drop below 100ms
#   → Re-enable EU trade execution against local replica
#   → Remove staleness banners
#   → Monitor for 30 minutes before declaring recovery
#
# IF cable continues degrading (latency > 1s, loss > 30%):
#   → Prepare for full EU → US-East failover
#   → Pre-scale US-East to absorb all EU traffic
#   → Redirect ALL EU API traffic to US-East
#   → Keep EU CDN and static content local
#   → Communicate to traders: "EU experiencing connectivity 
#     issues, trades routed via US — expect increased latency"
#
# IF cable drops completely:
#   → PostgreSQL replication breaks (replica needs manual 
#     rejoin when cable restores)
#   → EU-West is fully isolated
#   → All EU traffic must go through US-East
#   → EU Cassandra may have data divergence — will need 
#     repair when connectivity restores
```

### Step 5: Post-Incident — Prevent Recurrence (After Resolution)

```
ARCHITECTURAL CHANGES:

1. IMPLEMENT PER-FEATURE ROUTING (from Q4 decision):
   → Trade execution: ALWAYS read balance from primary
   → Read-only views: use local replica with staleness 
     indicator
   → This should be the PERMANENT architecture, not 
     just an incident response

2. AUTOMATED PARTITION DETECTION + TRADE PROTECTION:
   → Monitor replication lag continuously
   → If lag > 1 second: automatically route trade 
     approvals to primary
   → If lag > 5 seconds: automatically enable staleness 
     banners
   → If lag > 10 seconds: automatically halt EU trade 
     execution
   → These thresholds should be configurable and tested

3. PRE-TRADE BALANCE CHECK WITH LAG AWARENESS:
   → Before approving any trade, check the replica lag
   → If lag > threshold: reject the trade with message 
     "Balance verification temporarily unavailable"
   → This is a CIRCUIT BREAKER for stale balance reads

4. REGULATORY REVIEW:
   → Review all trades from the incident window
   → Unwind positions that exceeded balance limits
   → File necessary regulatory notifications
   → Implement reconciliation procedures for 
     split-brain scenarios
```

### Complete Mitigation Timeline

```
╭──────────┬─────────────────────────────────────────────────────╮
│ TIME     │ ACTION                                              │
├──────────┼─────────────────────────────────────────────────────┤
│ 0-60s    │ HALT EU trade execution                             │
│          │ Route trade endpoints to US-East primary            │
│          │ VERIFY: no new balance violations                   │
├──────────┼─────────────────────────────────────────────────────┤
│ 0-120s   │ NOTIFY risk management + compliance (parallel)      │
│ (parallel)│ Identify all affected trades and accounts          │
│          │ Begin regulatory assessment                         │
├──────────┼─────────────────────────────────────────────────────┤
│ 2-5min   │ Add staleness banners to EU read-only endpoints     │
│          │ VERIFY: EU users see delay warnings                 │
│          │ VERIFY: EU read-only features functional            │
├──────────┼─────────────────────────────────────────────────────┤
│ 5min+    │ Monitor cable health                                │
│          │ Prepare for escalation (full EU→US failover)        │
│          │ OR prepare for recovery (lag declining)             │
├──────────┼─────────────────────────────────────────────────────┤
│ Recovery │ Wait for replication lag < 100ms                    │
│          │ Re-enable EU trade execution                        │
│          │ Remove staleness banners                            │
│          │ Monitor 30 minutes                                  │
├──────────┼─────────────────────────────────────────────────────┤
│ Post-    │ Review all affected trades with risk team           │
│ incident │ Implement per-feature routing permanently           │
│          │ Implement lag-aware circuit breaker for trades      │
│          │ Implement automated partition detection             │
│          │ File regulatory notifications if required           │
│          │ Load test EU→US failover path                       │
╰──────────┴─────────────────────────────────────────────────────╯

GUIDING PRINCIPLE:
  On a financial platform, the hierarchy is:
  
  1. FINANCIAL INTEGRITY (no unauthorized exposure)
  2. REGULATORY COMPLIANCE (report and remediate)
  3. AVAILABILITY (keep as much working as safely possible)
  4. LATENCY (accept slower trades over wrong trades)
  
  We sacrifice latency and partial availability to 
  protect financial integrity. That's the correct 
  tradeoff for this domain.
```
