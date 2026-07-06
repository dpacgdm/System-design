# Week 8, Topic 2 — Lamport Clocks, Vector Clocks, and Causality

> **Prerequisite:** Week 3 Topic 2 (Consistency Models) — especially causal consistency, the consistency spectrum, and the allergy-check SRE scenario. This module gives you the *mechanisms* behind the guarantees you already named.

> **Connects forward to:** Week 8 Topic 3 (CRDTs), Week 5 (multi-master conflict resolution), Week 6 (Kafka ordering and causal metadata in events).

Same teaching contract as Consistency Models and Observability: every section answers *what do I run, what breaks, what's the bug nobody warned me about, and what do I say in the interview.*

---

## Learning Objectives
```
After this topic, you will be able to:

1. Define PARTIAL ORDER, TOTAL ORDER, and the happens-before
   relation — and explain why wall-clock time cannot provide
   either in a distributed system

2. Implement Lamport timestamps from first principles: the
   three rules, the total-order tiebreaker, and the critical
   limitation (L(A) < L(B) does NOT imply A happened-before B)

3. Implement vector clocks: increment rules, domination comparison,
   concurrent detection, and when O(N) metadata is worth the cost

4. Distinguish VECTOR CLOCKS from VERSION VECTORS — the most
   common interview trap — and explain dotted version vectors

5. Explain how CAUSAL CONSISTENCY (Week 3) is implemented using
   clock metadata: MongoDB causal sessions, COPS-style tracking,
   and read-at-timestamp routing

6. Walk through Dynamo-style conflict detection: sibling creation,
   vector clock comparison, LWW failure modes, and merge semantics

7. Select the correct clock mechanism for a given product requirement
   using the decision framework (not "vector clocks because fancy")

8. Diagnose production bugs as clock/causality violations: phantom
   siblings, lost updates, effect-before-cause, and clock skew LWW

9. Trace an incident from symptom → root cause → fix, articulating
   which consistency guarantee was violated and why
```

---


## Wrong Mental Models (Destroy These First)

```
MENTAL MODEL #1: "Lamport timestamp A < B means A happened-before B"
  WRONG. Lamport gives TOTAL ORDER with false causality — concurrent events
  can get arbitrary order. Use vector clocks to detect concurrency.

MENTAL MODEL #2: "Vector clocks and version vectors are the same"
  WRONG. Version vectors track replicas (anti-entropy); vector clocks track
  per-process causality. Mixing them breaks merge semantics in CRDTs/Dynamo.

MENTAL MODEL #3: "Wall clock + NTP fixes ordering"
  WRONG. Skew and leap seconds make wall clocks unsafe for correctness.
  Logical clocks track causality; physical clocks are for human UX only.

MENTAL MODEL #4: "Causal consistency requires vector clocks everywhere"
  WRONG. Session tokens (MongoDB), hybrid logical clocks, and partition-
  scoped vectors trade metadata cost for the guarantee you actually need.

MENTAL MODEL #5: "Last-write-wins with timestamps resolves all conflicts"
  WRONG. Clock skew picks the wrong winner; siblings proliferate under
  concurrent writes. LWW is a product decision, not a correctness proof.
```

---

## Core Teaching

### 2.1 — The Problem Wall Clocks Cannot Solve

```
In Week 3, you learned that CAUSAL CONSISTENCY sits between
sequential consistency and read-your-writes on the spectrum.

You also learned it "can be implemented with vector clocks or
Lamport timestamps."

This module explains HOW — and more importantly, WHY each
mechanism succeeds or fails at specific jobs.

THE FUNDAMENTAL PROBLEM:

  Distributed systems have no shared "now."

  Node A's clock says 14:00:00.003
  Node B's clock says 13:59:59.847
  Node C's clock says 14:00:00.112

  Even with NTP/chrony keeping clocks within milliseconds,
  two events that are causally related can appear to happen
  in the wrong order when sorted by wall-clock timestamp.

  Leslie Lamport (1978): "The concept of time is fundamental
  to our way of thinking. It is derived from the more basic
  concept of the ORDERING of events."

  He didn't ask "what time did this happen?"
  He asked "did this event INFLUENCE that event?"
```

### 2.2 — Three Questions, Three Mechanisms

```
╔══════════════════════════════════════════════════════════════════╗
║   QUESTION                          │  MECHANISM                 ║
╠══════════════════════════════════════════════════════════════════╣
║  "Give me a TOTAL ORDER of all      │  Lamport timestamps        ║
║   events" (for leader election,     │  (+ process ID tiebreaker) ║
║   lock ordering, log sequencing)    │                            ║
╠══════════════════════════════════════════════════════════════════╣
║  "Did event A CAUSE event B?"       │  Vector clocks             ║
║  "Are A and B CONCURRENT?"          │  (true causality detection)║
╠══════════════════════════════════════════════════════════════════╣
║  "Which REPLICA updates conflict    │  Version vectors           ║
║   on this KEY?"                     │  (Dynamo, Riak, Cassandra) ║
╠══════════════════════════════════════════════════════════════════╣
║  "Ensure no observer sees effect    │  Causal consistency        ║
║   before cause"                     │  (implemented via clocks)  ║
╚══════════════════════════════════════════════════════════════════╝

THE TRAP:
  Using Lamport timestamps for conflict detection.
  Using wall-clock timestamps for anything important.
  Treating version vectors and vector clocks as the same thing.
  Assuming causal consistency comes "for free" from eventual
  consistency + replication.
```

### 2.3 — Connection to Week 3 Consistency Models

```
From Consistency Models.md — causal consistency definition:

  "Operations that are CAUSALLY RELATED are seen by all nodes
   in the same order. Operations that are NOT causally related
   can be seen in any order."

  Causal relationships arise from:
    1. Same client: op1 then op2 on one client
    2. Reads-from: B reads A's write, then B writes
    3. Transitive closure of the above

  THIS MODULE provides the DATA STRUCTURES that track those
  relationships across nodes without a central coordinator.

  Week 3 told you WHAT guarantee you need.
  Week 8 Topic 2 tells you HOW to implement it.
```

---

## 3. Partial Ordering and the Happens-Before Relation

### 3.1 — Events, Processes, and Messages

```
MODEL (Lamport 1978):

  A distributed system consists of PROCESSES (nodes/clients).
  Each process has a sequence of EVENTS:
    - Local computation events
    - Send events (message dispatched)
    - Receive events (message arrived)

  Events within ONE process are totally ordered by execution.
  Events on DIFFERENT processes have no inherent order unless
  connected by message passing.

VISUAL — three processes, six events:

  Process P1:  ──e1──send(m)──e2──receive(m')──e3──►
  Process P2:  ──e4──receive(m)──e5──send(m')──e6──►
  Process P3:  ──e7──────────────────────────────►

  Within P1: e1 → e2 → e3 (total order)
  Within P2: e4 → e5 → e6 (total order)

  Cross-process order is UNKNOWN unless linked by messages.
```

### 3.2 — The Happens-Before Relation (→)

```
DEFINITION — a → b means "event a happens before event b"

RULE 1 — Process order:
  If a and b are events in the same process, and a occurs
  before b in that process's sequence, then a → b.

RULE 2 — Send-receive:
  If event a is a SEND of message m, and event b is the
  RECEIVE of message m, then a → b.

RULE 3 — Transitivity:
  If a → b and b → c, then a → c.

  (→ is irreflexive, transitive, but NOT total)

CONCURRENT EVENTS:
  If neither a → b nor b → a, then a and b are CONCURRENT.
  They are incomparable in the partial order.
  Symbol: a ∥ b

EXAMPLE — social media thread (from Week 3):

  Alice posts "I got the job!"     → event A (on server S1)
  Bob reads Alice's post           → event R (receive of A's data)
  Bob replies "Congratulations!"   → event B (caused by R)
  Carol posts "Nice weather"       → event C (independent)

  Causal chain: A → R → B
  C is concurrent with A, R, and B.

  Partial order diagram:

       C (concurrent)
       │
       │    A ──→ R ──→ B
       │    (causal chain)
       ▼
  Valid global views: [C,A,R,B], [A,C,R,B], [A,R,B,C]
  INVALID: [B,A,...] — effect before cause
```

### 3.3 — Partial Order vs Total Order

```
PARTIAL ORDER:
  Some pairs of elements are ordered; some are not.
  Concurrent events are incomparable.
  The happens-before relation is a partial order.

TOTAL ORDER:
  EVERY pair of elements is comparable.
  For any a, b: either a ≤ b or b ≤ a (or both if equal).

WHY DISTRIBUTED SYSTEMS CARE:

  Leader election needs TOTAL ORDER:
    "Who had the highest term at this moment?"
    Two candidates must not both think they won.

  Conflict detection needs PARTIAL ORDER (or better):
    "Are these two writes concurrent?"
    If concurrent → conflict (siblings). If ordered → one wins.

  Causal consistency needs PARTIAL ORDER preserved:
    If a → b, all observers must see a before b.
    Concurrent events can appear in any order.

THE MISMATCH:
  Lamport timestamps impose a TOTAL ORDER on ALL events.
  That total order is a SUPERSET of happens-before:
    if a → b, then L(a) < L(b)  ✓ (sound)
    if L(a) < L(b), then a → b   ✗ (NOT guaranteed — the trap)
```

### 3.4 — Why Physical Clocks Fail

```
FAILURE MODE — clock skew and Last-Write-Wins:

  Client A (clock slow by 500ms):  write(X=1) at T=100
  Client B (clock fast by 500ms):  write(X=2) at T=50

  LWW picks X=1 as "winner" because T=100 > T=50.
  But B's write may have happened AFTER A's in real causality
  if B read A's value and incremented it.

  Even with synchronized clocks (Spanner TrueTime):
    - Cost: GPS + atomic clocks in every datacenter
    - Uncertainty window still exists (ε)
    - Overkill for 99% of applications

  LOGICAL CLOCKS track CAUSALITY, not wall time.
  They work without synchronized physical clocks.
  They are the engineering default for conflict detection
  and causal ordering below planetary scale.
```

### 3.5 — Hasse Diagram: Visualizing Partial Order

```
For events {A, B, C, D, E} with relations:
  A → B, A → C, B → D, C → D, (E concurrent with all)

Hasse diagram (cover edges — omit transitive shortcuts):

        A
       / \
      B   C
       \ /
        D

  E floats separately — no edges to/from A,B,C,D

Valid linear extensions (total orders respecting →):
  [A,B,C,D,E], [A,C,B,D,E], [E,A,B,C,D], [A,B,E,C,D], ...

Invalid linear extensions:
  [B,A,...] — B before A violates A → B
  [D,B,...] — D before B violates B → D

INTERVIEW SKILL:
  Given a diagram, list two valid and one invalid ordering.
  Connect to causal consistency: observers may pick different
  linear extensions for concurrent events (E's position varies)
  but must agree on edges (A before B, etc.).
```

### 3.6 — Four Types of "Ordering" (Disambiguation)

```
Engineers confuse these four — define precisely:

1. PHYSICAL TIME ORDER
   Wall clock timestamp order.
   Requires synchronized clocks. Breaks under skew.

2. LOGICAL TIME ORDER (Lamport)
   Total order extension of happens-before.
   Sound but not complete for causality reverse inference.

3. CAUSAL ORDER (happens-before, partial)
   The true dependency order. Concurrent events incomparable.

4. ARBITRARY TOTAL ORDER (consensus log)
   Raft log index, Kafka offset within partition.
   Imposed by protocol, not derived from event semantics.

MAPPING TO SYSTEMS:
  Postgres WAL LSN → type 4 within one database
  Lamport on gateway → type 2 (dangerous for conflicts)
  Vector clock compare → type 3 detection
  NTP timestamp on write → type 1 (fragile)
```

### 3.7 — Reads-From: The Subtle Causal Edge

```
The reads-from relation is how causality LEAKS across clients:

  Client A: write(X=42)  → event W
  Client B: read(X) returns 42  → event R (reads-from W)
  Client B: write(Y=99) based on X=42  → event W2

  W → R → W2  therefore W → W2

  Client B never spoke to Client A directly.
  The DATABASE carried A's value to B, creating causal link.

IMPLICATION FOR IMPLEMENTATION:
  Any read must return metadata (version vector, LSN, VC)
  that the client attaches to subsequent writes.
  Without this, the system loses reads-from edges and
  cannot enforce causal consistency.

  MongoDB session: operationTime captures this implicitly.
  Dynamo: client must send prior vv on conditional put.
  Postgres+Kafka: causal_lsn on event encodes reads-from point.
```

---


## 4. Lamport Timestamps — Total Order from Logical Time

### 4.1 — The Algorithm (1978)

```
Each process P maintains a local counter L (initially 0).

RULE 1 — Local event:
  Before recording any local event, increment L:
    L := L + 1
  Attach timestamp L to the event.

RULE 2 — Send event:
  Before sending message m, increment L:
    L := L + 1
  Attach timestamp L to message m.

RULE 3 — Receive event:
  On receiving message m with timestamp Tm:
    L := max(L, Tm) + 1
  Attach timestamp L to the receive event.

That's the entire algorithm. No central coordinator.
```

### 4.2 — Worked Example

```
Three processes P1, P2, P3. Initial L=0 everywhere.

Step 1: P1 local event
  P1: L=1, event a (timestamp 1)

Step 2: P1 sends message m1 to P2
  P1: L=2, send m1 (timestamp 2)

Step 3: P2 receives m1
  P2: L = max(0, 2) + 1 = 3, receive event (timestamp 3)

Step 4: P2 local event
  P2: L=4, event b (timestamp 4)

Step 5: P3 local event (concurrent with everything above)
  P3: L=1, event c (timestamp 1)

Step 6: P2 sends m2 to P3
  P2: L=5, send m2 (timestamp 5)

Step 7: P3 receives m2
  P3: L = max(1, 5) + 1 = 6, receive (timestamp 6)

TIMELINE:

  P1:  a(1) ── send(2) ──────────────────────►
  P2:  ───────── recv(3) ── b(4) ── send(5) ──►
  P3:  c(1) ───────────────────── recv(6) ────►

CAUSALITY CHECK:
  a → send(2) → recv(3) → b → send(5) → recv(6)
  Lamport: 1 < 2 < 3 < 4 < 5 < 6  ✓

  c is concurrent with a..send(5).
  But L(c)=1 < L(recv on P2)=3.
  Lamport correctly orders c before recv(3) even though
  they may be concurrent — that's allowed (total order extension).

THE TRAP:
  L(c)=1 and L(a)=1 — same timestamp, concurrent.
  L(c)=1 < L(recv)=3 — but c ∥ recv (not causal).
  You CANNOT infer c → recv from timestamps alone.
```

### 4.3 — Achieving Total Order (Tiebreaker)

```
When L(a) = L(b), use process ID as tiebreaker:

  Compare (L(a), process_id_a) vs (L(b), process_id_b)
  lexicographically.

  This gives a TOTAL ORDER suitable for:
    - Total-order broadcast
    - Sequencing entries in a replicated log
    - Lock request ordering (older request wins)

USED IN:
  - Google Chubby (lock ordering)
  - Some Paxos/Raft implementations for log entry ordering
  - Batch job scheduling across nodes

NOT USED FOR:
  - Detecting concurrent writes (use vector clocks)
  - Causal consistency enforcement alone (insufficient)
```

### 4.4 — Lamport Implementation (Python)

```python
class LamportClock:
    """Per-process Lamport logical clock."""

    def __init__(self, process_id: str):
        self.process_id = process_id
        self.time = 0

    def local_event(self) -> tuple[int, str]:
        self.time += 1
        return (self.time, self.process_id)

    def send(self) -> tuple[int, str]:
        self.time += 1
        return (self.time, self.process_id)

    def receive(self, remote_ts: int) -> tuple[int, str]:
        self.time = max(self.time, remote_ts) + 1
        return (self.time, self.process_id)

    @staticmethod
    def compare(a: tuple[int, str], b: tuple[int, str]) -> int:
        """Returns -1 if a < b, 0 if equal, 1 if a > b."""
        if a[0] != b[0]:
            return -1 if a[0] < b[0] else 1
        if a[1] != b[1]:
            return -1 if a[1] < b[1] else 1
        return 0


# Example: three processes exchanging messages
p1 = LamportClock("P1")
p2 = LamportClock("P2")
p3 = LamportClock("P3")

a = p1.local_event()           # (1, P1)
m1 = p1.send()                 # (2, P1)
r1 = p2.receive(m1[0])         # (3, P2)
b = p2.local_event()           # (4, P2)
c = p3.local_event()           # (1, P3) — concurrent with a
m2 = p2.send()                 # (5, P2)
r2 = p3.receive(m2[0])         # (6, P3)

assert LamportClock.compare(a, r1) < 0   # causal: a before r1
assert LamportClock.compare(c, r1) < 0   # NOT causal — false signal!
# L(c)=1 < L(r1)=3 but c ∥ r1
```

### 4.5 — Lamport Clock Properties and Limits

```
PROPERTY 1 — Soundness (the good news):
  If a → b (happens-before), then L(a) < L(b).
  Causal order is preserved in the timestamp order.

PROPERTY 2 — Not complete (the bad news):
  If L(a) < L(b), we CANNOT conclude a → b.
  a and b may be concurrent.

PROPERTY 3 — Space efficient:
  O(1) per process — just one integer.

PROPERTY 4 — Total order extension:
  With process ID tiebreaker, every pair is comparable.
  Useful when you need ANY consistent order, not the
  causally correct one.

WHEN TO USE LAMPORT:
  ✓ Total-order multicast
  ✓ Distributed lock queues
  ✓ Timestamping events for logging/audit (rough ordering)
  ✓ Teaching and interview foundations

WHEN NOT TO USE LAMPORT:
  ✗ Conflict detection ("are these writes concurrent?")
  ✗ Causal consistency enforcement by itself
  ✗ Merge decisions in multi-master replication
```

### 4.6 — Extended Worked Example: Five Processes, Ten Events

```
Setup: P1, P2, P3, P4, P5. Trace a message chain AND concurrent branch.

  P1: local(a) L=1
  P1: send m1 to P2, L=2
  P3: local(c) L=1          ← concurrent with P1's early events
  P2: recv m1, L=3
  P2: local(b) L=4
  P2: send m2 to P4, L=5
  P4: recv m2, L=6
  P5: local(d) L=1          ← concurrent with most of the chain
  P4: send m3 to P1, L=7
  P1: recv m3, L=8

HAPPENS-BEFORE EDGES:
  a → send(m1) → recv(m2 path on P2) → b → send(m2) → recv on P4 → send(m3) → recv on P1
  c concurrent with a (unless message links them — here no)
  d concurrent with chain until proven otherwise

LAMPORT ORDER (may not match real-time):
  c(1), d(1), a(1) — tie on 1, use process ID for total order
  send_m1(2) < recv(3) < b(4) < send_m2(5) < recv_P4(6) < send_m3(7) < recv_P1(8)

INTERVIEW QUESTION from this trace:
  "Is c before recv on P2?"
  Lamport: L(c)=1 < L(recv)=3 → c appears first in total order.
  Causality: c ∥ recv — NO happens-before relationship.
  If you used Lamport for merge, c might incorrectly "win" over
  state derived from recv.

LESSON: Draw TWO diagrams — Lamport total order AND happens-before DAG.
  They are related but not identical.
```

### 4.7 — Lamport in Total-Order Multicast

```
USE CASE: Replicate state machine — all nodes must apply commands
in identical order.

PROTOCOL (simplified):
  1. Client sends command C to all nodes (or leader).
  2. Each node timestamps C with Lamport clock on receive.
  3. Buffer commands, deliver when no lower-timestamp command pending.
  4. Tie-break with process ID.

DELIVERY RULE:
  Deliver command with smallest (L, process_id) when:
    - It is the smallest among all undelivered commands in buffer
    - All commands with smaller timestamp already delivered

WHY NOT VECTOR CLOCK HERE:
  Total order required — any deterministic total order works.
  Lamport + tiebreaker is simpler than maintaining O(N) vectors.

SYSTEMS:
  - State machine replication (some variants)
  - Ordered log ingestion before Raft leader assignment
  - Sequencer service for global command ordering

COST:
  Delivery latency — must wait for messages that might get lower
  timestamp from slow network paths (buffering delay).
  Not the same as Raft — Lamport multicast alone doesn't handle
  failures; pair with consensus for durability.
```

### 4.8 — Common Lamport Misimplementation Bugs

```
BUG 1 — Forgetting to increment on receive:
  L := max(L, Tm)   # WRONG — missing +1
  Two receives of same message can get same timestamp.

BUG 2 — Not incrementing before send:
  Attach L to message without increment → duplicate timestamps
  on send and prior local event.

BUG 3 — Using Lamport across restarts without persistence:
  Process restarts L=0, causes timestamp regression relative to
  peers who remember higher values.
  Fix: persist L to disk or use (epoch, L) on restart with new epoch.

BUG 4 — Global Lamport from gateway only:
  Single gateway counter — works for total order through gateway
  but LOSES cross-client concurrency info at replicas.
  The v2.14.0 grocery cart bug pattern.

BUG 5 — Comparing Lamport across independent clock domains:
  Service A and Service B each have own Lamport — incomparable
  unless messages flow between them to sync.
```

---


## 5. Vector Clocks — Detecting True Causality

### 5.1 — The Problem Lamport Cannot Solve

```
Scenario — shopping cart conflict:

  Replica R1: Client A writes item "apple"  (no message between)
  Replica R2: Client B writes item "banana"   (no message between)

  These writes are CONCURRENT. Both should be preserved (merge)
  or flagged as conflict (siblings).

  Lamport timestamps:
    A's write: L = 5
    B's write: L = 3

  L(B) < L(A) → B appears "before" A.
  LWW would discard B's write. DATA LOSS.

  Vector clocks detect: A ∥ B (concurrent).
  Neither dominates the other → CONFLICT → keep both.
```

### 5.2 — Vector Clock Algorithm

```
Each process P_i maintains vector V of length N (N = num processes).
V[j] = number of events process P_j knows about at P_i.

INITIAL: V = [0, 0, ..., 0]

RULE 1 — Local event at P_i:
  V[i] := V[i] + 1

RULE 2 — Send from P_i:
  V[i] := V[i] + 1
  Attach V to message

RULE 3 — Receive at P_i with vector V_msg:
  V[j] := max(V[j], V_msg[j]) for all j
  V[i] := V[i] + 1

COMPARISON — domination:
  V1 dominates V2 (V1 > V2, V1 is "after" V2) iff:
    V1[k] >= V2[k] for all k, AND
    V1[k] > V2[k] for at least one k

  V1 and V2 are CONCURRENT (V1 ∥ V2) iff:
    Neither dominates the other.

  V1 equals V2 iff all components equal.
```

### 5.3 — Worked Example — Three Processes

```
N=3 processes: P0, P1, P2. Initial V=[0,0,0] everywhere.

Event a at P0 (local):
  P0: V=[1,0,0]

P0 sends to P1 with V=[1,0,0]:
  P0: V=[2,0,0]  (increment before send)

P1 receives:
  P1: V = [max(0,2), max(0,0), max(0,0)] = [2,0,0]
  P1: V=[3,0,0]  (increment at P1 after merge)

Event b at P1 (local):
  P1: V=[4,0,0]

Meanwhile at P2 (concurrent branch):
  Event c at P2:
  P2: V=[0,0,1]

P1 sends to P2 with V=[4,0,0]:
  P1: V=[5,0,0]

P2 receives:
  P2: V = [max(0,5), max(0,0), max(1,0)] = [5,0,1]
  P2: V=[5,0,2]

COMPARISON:
  V(a)=[1,0,0] dominated by V(b)=[4,0,0]? 
    4>=1, 0>=0, 0>=0, and 4>1 → YES. a → b. ✓

  V(c)=[0,0,1] vs V(b)=[4,0,0]:
    4>=0, 0>=0, 0>=1? NO (0 < 1).
    0>=4? NO.
    → CONCURRENT. c ∥ b. ✓

  This is the answer Lamport cannot give.
```

### 5.4 — Vector Clock Implementation (Python)

```python
from typing import List

class VectorClock:
    def __init__(self, process_index: int, num_processes: int):
        self.index = process_index
        self.num = num_processes
        self.v = [0] * num_processes

    def local_event(self) -> List[int]:
        self.v[self.index] += 1
        return self.v.copy()

    def send(self) -> List[int]:
        self.v[self.index] += 1
        return self.v.copy()

    def receive(self, remote: List[int]) -> List[int]:
        for i in range(self.num):
            self.v[i] = max(self.v[i], remote[i])
        self.v[self.index] += 1
        return self.v.copy()

    @staticmethod
    def compare(a: List[int], b: List[int]) -> str:
        """Returns 'before', 'after', 'concurrent', or 'equal'."""
        a_le_b = all(x <= y for x, y in zip(a, b))
        b_le_a = all(y <= x for x, y in zip(a, b))
        if a == b:
            return "equal"
        if a_le_b and any(x < y for x, y in zip(a, b)):
            return "before"   # a → b
        if b_le_a and any(y < x for x, y in zip(a, b)):
            return "after"    # b → a
        return "concurrent"


# Shopping cart conflict detection
num = 3
r1 = VectorClock(0, num)  # replica R1
r2 = VectorClock(1, num)  # replica R2

# Client A writes at R1
va = r1.local_event()     # [1,0,0]

# Client B writes at R2 (concurrent — no message exchange)
vb = r2.local_event()     # [0,1,0]

assert VectorClock.compare(va, vb) == "concurrent"
# → siblings, merge both items, do NOT LWW
```

### 5.5 — Vector Clock Costs and Variants

```
COST:
  Space: O(N) per event, N = number of processes
  Comparison: O(N) per pair
  Grows with cluster size — problematic at 1000+ nodes

VARIANTS:

  COMPACT VECTOR CLOCKS:
    Track only processes that actually participated.
    Sparse representation. Used in some tracing systems.

  SUMMER/WINTER (bounded):
    Reset or compress periodically. Risk of false "concurrent"
    if reset too aggressively.

  CAUSAL DAG:
    Store explicit dependency graph instead of vector.
    Better for persistent storage of large histories.

  HYBRID LOGICAL CLOCKS (HLC):
    Combines physical clock + logical counter.
    Used in CockroachDB, MongoDB (hybrid logical time).
    Gives: if physical clocks synchronized, HLC approximates
    real time while preserving causality.
    Format: (physical_ms, logical_counter, process_id)

WHEN TO USE VECTOR CLOCKS:
  ✓ True concurrency detection
  ✓ Causal consistency tracking across messages
  ✓ Debugging distributed traces (who caused what)
  ✓ Small-to-medium cluster sizes (tens, low hundreds)

WHEN NOT TO USE:
  ✗ Million-node systems (metadata explodes)
  ✗ When you only need total order (use Lamport)
  ✗ When per-key versioning suffices (use version vectors)
```

### 5.6 — Extended Worked Example: Shopping Cart Across Three Replicas

```
Initial: all V=[0,0,0]

Step 1 — Client A writes apple at R1 (index 0):
  R1: local → V=[1,0,0]
  Stored: cart={apple}, vv via version vector {R1:1}

Step 2 — Client B writes banana at R2 (index 1), no message from R1:
  R2: local → V=[0,1,0]
  Stored: cart={banana}, vv {R2:1}

Step 3 — Anti-entropy sync: R1 and R2 exchange versions
  R1 sees {R2:1} and {R1:1} — CONCURRENT siblings
  R1 sees {R1:1} and {R2:1} — same

Step 4 — Client C at R1 reads, merges:
  merged = {apple, banana}, vv={R1:1,R2:1}

Step 5 — Client C writes cherry at R1 (descendant of merge):
  vv={R1:2,R2:1}
  This DOMINATES both prior versions → no conflict, normal write

VECTOR CLOCK at event level (if tracking messages):
  When R1 sends merged state to R2:
  R1 send: V=[2,0,0] → R2 receive: merge → V=[2,2,0]
  Causal chain preserved for sync message.

TWO LAYERS:
  Event vector clock — tracks message/event causality
  Version vector — tracks per-key replica write counts
  Both use domination comparison. Different increment rules.
```

### 5.7 — Vector Clock Comparison Algorithm (Formal)

```
function compare(V1, V2):
  if V1 == V2: return EQUAL
  if forall i: V1[i] <= V2[i] and exists j: V1[j] < V2[j]:
    return V1_BEFORE_V2    # V1 → V2 in causality
  if forall i: V2[i] <= V1[i] and exists j: V2[j] < V1[j]:
    return V2_BEFORE_V1
  return CONCURRENT

function merge(V1, V2):  # for causal context update
  return [max(V1[i], V2[i]) for i in range(N)]

function increment(V, process_i):
  V[i] += 1
  return V

CORRECTNESS PROPERTY:
  compare(V(a), V(b)) == V1_BEFORE_V2  iff  a → b
  (assuming no phantom events, reliable message delivery for
   sync paths, and consistent process indexing)

INTERVIEW: "What's the complexity of detecting if two events
  are concurrent across a cluster?"
  O(N) per comparison, N = process count.
  Space O(N) per stored event if you keep full VC per event.
  Production systems compress or scope N.
```

### 5.8 — Vector Clocks in Distributed Tracing

```
Modern tracing (Jaeger, Tempo, Honeycomb) often embed causal hints:

  Span A starts, Span B child of A — trace tree encodes causality
  within ONE request.

  Cross-request causality (async Kafka consumer):
    Trace context propagation (W3C traceparent) ≠ vector clock.
    traceparent links spans for observability.
    Vector clock links EVENTS for consistency.

  Advanced: carry both
    traceparent: for UI waterfall
    causal_vc: for read-your-writes across async boundary

  Debugging "effect before cause" in traces:
    1. Find span where stale read occurred
    2. Check if consumer span has parent's VC merged
    3. Compare required VC vs replica state at read time
    4. If missing merge on receive → fix consumer middleware
```

---


## 6. Version Vectors — Per-Key Replica Tracking

### 6.1 — Vector Clocks ≠ Version Vectors

```
╔══════════════════════════════════════════════════════════════════╗
║   VECTOR CLOCKS              │  VERSION VECTORS                  ║
╠══════════════════════════════════════════════════════════════════╣
║  Track EVENT causality       │  Track REPLICA update counts      ║
║  Increment on every event    │  Increment only on WRITE to key   ║
║  Per-process counter         │  Per-replica counter for ONE key  ║
║  "Did write A cause write B?"│  "Did these two writes conflict?" ║
║  Used in message ordering    │  Used in Dynamo-style storage     ║
╚══════════════════════════════════════════════════════════════════╝

THE CONFUSION:
  Both are vectors of integers.
  Both use domination comparison.
  But they answer different questions at different granularity.

VERSION VECTOR for key "user:123:cart":
  V = {R1: 3, R2: 1, R3: 0}
  Means: replica R1 has applied 3 writes, R2 has 1, R3 has 0.

  New write at R1: V = {R1: 4, R2: 1, R3: 0}

  Compare with stored V' = {R1: 2, R2: 1, R3: 0}:
    V dominates V' → this write is a DESCENDANT, not a conflict.
    Apply normally.

  Compare with V'' = {R1: 2, R2: 2, R3: 0}:
    Neither dominates → CONCURRENT updates → SIBLINGS.
```

### 6.2 — Dynamo Paper Mechanics (DeCandia et al., 2007)

```
Dynamo (Amazon's KV store, precursor to DynamoDB) stores:

  KEY → LIST OF VERSIONS (each with a version vector + value)

  On PUT:
    1. Client or coordinator generates new version vector
       by incrementing the writer's replica counter.
    2. Write goes to N nodes (preference list).
    3. Each node stores the version.

  On GET:
    1. Read from R nodes (R = read quorum).
    2. Collect all versions returned.
    3. Compare version vectors:
       - One dominates all others → return that value.
       - Multiple incomparable → return ALL (siblings).
    4. Client must MERGE siblings and write back.

SIBLING EXAMPLE:

  Key: cart/user-789

  Version A: vv={R1:1, R2:0}, value={apple}
  Version B: vv={R1:0, R2:1}, value={banana}

  GET returns BOTH. Application merge: {apple, banana}.
  PUT merged: vv={R1:1, R2:1}, value={apple, banana}
```

### 6.3 — Version Vector Implementation (Python)

```python
from typing import Dict, Optional, List, Tuple

VersionVector = Dict[str, int]

def increment_vv(vv: VersionVector, replica_id: str) -> VersionVector:
    new = dict(vv)
    new[replica_id] = new.get(replica_id, 0) + 1
    return new

def dominates(a: VersionVector, b: VersionVector) -> bool:
    """True if a is a descendant of b (b → a in version order)."""
    all_keys = set(a) | set(b)
    a_gte_b = all(a.get(k, 0) >= b.get(k, 0) for k in all_keys)
    a_gt_b = any(a.get(k, 0) > b.get(k, 0) for k in all_keys)
    return a_gte_b and a_gt_b

def concurrent(a: VersionVector, b: VersionVector) -> bool:
    return not dominates(a, b) and not dominates(b, a) and a != b

def merge_siblings(siblings: List[Tuple[VersionVector, object]]) -> Tuple[VersionVector, object]:
    """Merge concurrent versions — application-specific merge for values."""
    merged_vv: VersionVector = {}
    for vv, _ in siblings:
        for k, v in vv.items():
            merged_vv[k] = max(merged_vv.get(k, 0), v)
    # Value merge is domain-specific (set union for cart, etc.)
    merged_value = siblings[0][1]  # placeholder — real code merges values
    return merged_vv, merged_value


# Conflict detection
v1 = {"R1": 1, "R2": 0}
v2 = {"R1": 0, "R2": 1}
assert concurrent(v1, v2)

v3 = {"R1": 2, "R2": 1}  # descendant of both after merge+write
assert dominates(v3, v1)
assert dominates(v3, v2)
```

### 6.4 — Dotted Version Vectors

```
PROBLEM — version vector garbage:
  Old replica IDs accumulate forever.
  V = {R1:45, R2:12, R3:0, R4:0, ..., R47:0, ...}
  Vectors grow as cluster membership changes.

DOTTED VERSION VECTORS (Riak 2.0+):
  Track (replica_id, counter) pairs with DOTS:
    Each increment creates a new "dot" (id, count).
  Prune dots that are dominated by current state.
  Bounded size in practice.

  Used when:
    - Cluster membership changes frequently
    - Long-lived keys with many updates
    - You need accurate conflict detection without unbounded growth

  Trade-off:
    More complex implementation.
    Pruning too aggressively → false concurrent detection.
```

### 6.5 — Where Version Vectors Appear in Production

```
SYSTEM              │ VERSION VECTOR USAGE
────────────────────┼────────────────────────────────────────────
Riak                │ Dotted version vectors, explicit siblings
Voldemort           │ Vector clocks per key (similar model)
Cassandra           │ NOT full version vectors — uses timestamps
                    │ + last-write-wins (with known problems)
DynamoDB            │ No exposed version vectors — conditional
                    │ writes on _version attribute (optimistic locking)
CouchDB             │ Revision tree (_rev) — similar conflict model
Azure Cosmos DB     │ ETag + session tokens (different mechanism)

LESSON:
  "Dynamo-style" often means the CONCEPT (quorum, siblings,
  client-side merge) even when the implementation uses
  different metadata (ETags, HLC, session tokens).
```

### 6.6 — Version Vector Pruning and Garbage Collection

```
PROBLEM:
  Replica R47 decommissioned. Its slot in vv stays forever.
  vv = {R1:99, R2:44, ..., R47:3} — sparse, large, stale.

STRATEGIES:

  1. REPLICA EPOCH
     On topology change, bump epoch. vv keys include epoch:
     {R1:e5:99} invalidates pre-epoch vectors.
     Requires careful migration during rebalancing.

  2. DOMINATED PRUNING
     If vv_a dominates vv_b, drop vv_b from history.
     Safe for sibling lists after merge.

  3. DOTTED VERSION VECTORS
     Track individual dots (replica, counter) pairs.
     Remove dots subsumed by current state.
     Riak 2.0+ approach.

  4. SERVER-SIDE COMPACTION
     After merge PUT, delete sibling history older than merged vv.
     Background job for keys not read recently.

OPERATIONAL RULE:
  If p99 vv entry count > 10 for any key type → investigate
  topology churn or missing merge.
```

### 6.7 — Full Dynamo GET/PUT Pseudocode

```python
def dynamo_get(key, N, R):
    nodes = preference_list(key, N)
    responses = read_from(nodes, R)  # wait for R of N
    versions = [r.value for r in responses if r.ok]

    # Prune dominated versions
    pruned = []
    for v in versions:
        if not any(dominates(other.vv, v.vv) for other in versions if other != v):
            pruned.append(v)

    siblings = []
    for v in pruned:
        if not any(dominates(v.vv, other.vv) for other in pruned if other != v):
            siblings.append(v)

    if len(siblings) == 1:
        # read repair: push to lagging nodes
        repair_lagging(nodes, siblings[0])
        return siblings[0]
    return siblings  # client must merge


def dynamo_put(key, value, vv, W, N):
    nodes = preference_list(key, N)
    new_vv = increment_vv(vv, my_replica_id())
    version = Version(value=value, vv=new_vv)
    acks = write_to(nodes, version, W)
    return len(acks) >= W
```

### 6.8 — Version Vectors vs Vector Clocks — Interview Whiteboard

```
Draw two columns:

VECTOR CLOCK (event order):
  Process P0: e1(V=[1,0]) — e2(V=[2,0]) — send — ...
  Process P1: e3(V=[0,1]) concurrent
  Question: "Did e1 cause e3?" → compare V vectors → concurrent

VERSION VECTOR (key "cart:1"):
  Write at R0: vv={R0:1}
  Write at R1: vv={R1:1}  concurrent
  GET: siblings → merge vv={R0:1,R1:1}
  Next write: vv={R0:2,R1:1} dominates both prior

Same comparison function (domination).
Different increment semantics (every event vs per-key write).
Different scope (process vs replica for one key).

One sentence: "Vector clocks order events; version vectors
version keys."
```

---


## 7. Causal Consistency — The Consistency Model That Uses Clocks

### 7.1 — Recap from Week 3 (Consistency Models.md)

```
CAUSAL CONSISTENCY guarantees:

  If operation A could have INFLUENCED operation B,
  then every process that observes B must also observe A,
  and must observe A before B.

  Operations with NO causal link (concurrent) may appear
  in different orders to different observers.

ANOMALY PREVENTED:
  "Seeing an effect before its cause"
  → Reply before parent post
  → Notification before the resource exists
  → Allergy check seeing prescription without allergy update
    (Week 3 SRE scenario)

ANOMALY ALLOWED:
  Concurrent posts appear in different order per region.
  That's fine — no causal relationship to preserve.

COST (from Week 3):
  Much cheaper than linearizability.
  Only coordinate on causally related operations.
  Implemented with vector clocks, version metadata, or
  hybrid logical clocks — THIS module's subject matter.
```

### 7.2 — Implementing Causal Consistency with Vector Clocks

```
ARCHITECTURE — causal tracking middleware:

  Each client maintains a causal context C (vector clock or
  derived structure).

  On WRITE:
    1. Client sends C with the write request.
    2. Server merges C with its local state.
    3. Server assigns new version, updates C.
    4. Server returns updated C to client.
    5. Client stores C for subsequent operations.

  On READ:
    1. Client sends C with read request.
    2. Server returns value + version vector at least as
       fresh as C (may read from replica if caught up).
    3. Client merges returned metadata into C.

  On READ after WRITE (same client):
    C includes the write → server must return state that
    reflects that write → read-your-writes as side effect.

VISUAL — comment thread:

  Alice (C_A): write post P
    Server: store P with vv=[1,0,0], return C_A'=[1,0,0]

  Bob reads P (C_B receives P's metadata):
    C_B := [1,0,0]
    Bob writes reply R depending on P
    Server: store R with vv showing dependency on [1,0,0]

  Carol (C_C=[0,0,0], never saw P):
    Carol writes unrelated post U
    U is concurrent with P and R

  Any observer must see P before R.
  U can appear anywhere relative to P/R per observer.
```

### 7.3 — MongoDB Causal Consistency Sessions

```
MongoDB 3.6+ — causal consistency via session tokens:

  NOT full vector clocks exposed to application.
  Uses clusterTime and operationTime (Hybrid Logical Clock based).

  PATTERN:

  session = client.start_session(causal_consistency=True)

  with session.start_transaction():
      db.posts.insert_one({"text": "I got the job!"}, session=session)
      # session now tracks causal point

  with session.start_transaction():
      post = db.posts.find_one({"_id": post_id}, session=session)
      db.comments.insert_one({"text": "Congrats!", "post_id": post_id},
                             session=session)

  Reads within the session see all prior writes in that session
  AND all writes that causally preceded them cluster-wide.

  operationTime:
    Logical timestamp of last write the session observed.
  readConcern: "majority" + session ensures replica is caught up
    to at least operationTime before serving read.

  WHY NOT EXPOSE VECTOR CLOCKS:
    - Simpler API for developers
    - Server manages HLC internally
    - Trade-off: less control for custom merge logic

  WHEN IT FAILS:
    - Reading OUTSIDE the session from a stale secondary
    - Mixing session writes with non-session reads
    - Cross-shard operations without proper session propagation
```

### 7.4 — COPS and Eiger (Research Systems)

```
COPS (Bailis et al.):

  Key idea: per-key version history + dependency metadata.
  Writes tagged with dependencies on prior versions client saw.
  Server stores based on causal order within datacenter.
  Cross-datacenter: async replication with causal metadata.

  Read path:
    Client provides dependencies from prior reads.
    Server returns value consistent with those dependencies.

  Eiger (follow-on):
    Optimized COPS for wide-area.
    Causal consistency without linearizable coordination
    across datacenters.

  PRODUCTION REALITY:
    Research systems prove feasibility.
    Most production systems use simpler approximations:
      - Session tokens (MongoDB)
      - Read-your-writes routing (Postgres primary)
      - Causal LSN in events (Week 3 allergy-check fix)
```

### 7.5 — Causal Metadata in Event Streams (Week 6 Connection)

```
From Week 3 Action Item 6 — causal LSN linking:

  prescription_event = {
      "patient_id": 4521,
      "drug": "penicillin",
      "causal_lsn": wal_lsn,
  }

  allergy_check_consumer:
      required_lsn = event['causal_lsn']
      if replica.replay_lsn < required_lsn:
          route read to primary

  This is CAUSAL CONSISTENCY without vector clocks:
    WAL LSN is a single-dimensional logical clock for ONE
    database's total order.
    Works when all causal data lives in one Postgres primary.
    Breaks when causality spans multiple stores.

  VECTOR CLOCKS / VERSION VECTORS needed when:
    - Multiple independent replicas per key
    - Multi-master writes
    - Cross-service causality without single WAL
```

### 7.6 — Causal Consistency vs Related Guarantees

```
╔══════════════════════════════════════════════════════════════════╗
║  GUARANTEE           │ WHAT IT ADDS OVER EVENTUAL                ║
╠══════════════════════════════════════════════════════════════════╣
║  Eventual            │ Nothing — replicas converge eventually    ║
╠══════════════════════════════════════════════════════════════════╣
║  Causal              │ Causally related ops ordered everywhere   ║
╠══════════════════════════════════════════════════════════════════╣
║  Read-your-writes    │ Own writes visible to self                ║
╠══════════════════════════════════════════════════════════════════╣
║  Sequential          │ All ops in some order; per-client order   ║
╠══════════════════════════════════════════════════════════════════╣
║  Linearizable        │ Total order matching real time            ║
╚══════════════════════════════════════════════════════════════════╝

  Causal ⊃ read-your-writes (for same session with tracking)
  Causal ⊂ sequential (sequential is stronger)
  Causal allows concurrent reordering; sequential does not
    (for cross-client visibility of concurrent ops)
```

---

## 8. Dynamo-Style Conflict Detection and Resolution

### 8.1 — The Dynamo Design Space

```
Dynamo (2007) established the pattern for AP-system conflict handling:

  1. QUORUM reads/writes (N, R, W)
  2. VERSION VECTORS per key
  3. SIBLING values when concurrent writes detected
  4. CLIENT-SIDE merge (application knows semantics)
  5. Sloppy quorum + hinted handoff (availability)
  6. Merkle trees for anti-entropy (background sync)

  Conflict detection is the heart of this module:
    Without accurate concurrency detection, you either
    LOSE DATA (LWW) or STORE GARBAGE (unbounded siblings).
```

### 8.2 — Write Path with Version Vectors

```
PUT key=cart:789, value={items: [apple]}, vv={R1:1, R2:0}

Coordinator:
  1. Hash key → preference list [N1, N2, N3]
  2. Send write to all N nodes (parallel)
  3. Wait for W acknowledgments
  4. Return success to client

Each node stores:
  (key, value, version_vector, timestamp_metadata)

Concurrent PUT from another region:
  PUT key=cart:789, value={items: [banana]}, vv={R1:0, R2:1}

  Neither vv dominates the other → both versions persist
  as SIBLINGS on the nodes.
```

### 8.3 — Read Path and Sibling Detection

```
GET key=cart:789

Coordinator:
  1. Read from R nodes in preference list
  2. Collect responses:

     N1: {items:[apple]},  vv={R1:1, R2:0}
     N2: {items:[banana]}, vv={R1:0, R2:1}
     N3: {items:[apple]},  vv={R1:1, R2:0}

  3. Prune dominated versions:
     Neither vv dominates → SIBLINGS

  4. Return to client both siblings

  5. Client merge: {items: [apple, banana]}
     merged_vv = {R1:1, R2:1}

  6. Client PUT merged value back (read-repair + resolution)
```

### 8.4 — Last-Write-Wins (LWW) and Why It Fails

```
LWW — pick the write with the highest timestamp:

  Simple. Fast. WRONG for concurrent updates.

FAILURE 1 — Clock skew:
  Slow clock write appears "older" → discarded incorrectly.

FAILURE 2 — Hidden concurrency:
  Two users edit different fields of same document.
  LWW keeps one entire document → other edits vanish.

FAILURE 3 — Offline/mobile:
  Device sync with skewed clocks destroys causal chain.

FAILURE 4 — Delete resurrection:
  Tombstone LWW has garbage-collection edge cases.

WHEN LWW IS ACCEPTABLE:
  - Single writer per key
  - Immutable values
  - Metrics/counters with CRDT merge
  - Strong external coordination prevents concurrency
```

### 8.5 — Merge Semantics — Application Responsibility

```
Dynamo principle: STORAGE detects conflict. APPLICATION resolves.

MERGE STRATEGIES BY DATA TYPE:

  Shopping cart → set union on items
  Counter → CRDT (Week 8 Topic 3)
  JSON document → field-level version vectors
  Text editing → OT or CRDT
  Inventory quantity → CANNOT naive merge — needs linearizable
                       decrement or reservation pattern
```

### 8.6 — Read Repair and Anti-Entropy

```
READ REPAIR (on read path):
  Coordinator detects version mismatch across R nodes.
  Sends latest merged version to out-of-date nodes.

ANTI-ENTROPY (background):
  Merkle tree comparison between replicas.
  Syncs cold keys read repair misses.

  Both propagate RESOLVED versions.
  If client never merges siblings, garbage propagates forever.
  Operational smell: growing sibling_count metric.
```

### 8.7 — Conditional Writes and Optimistic Locking

```
DynamoDB / Postgres pattern:
  GET with version N → PUT IF version=N → retry on conflict

  Conflict DETECTION without vector clock siblings.
  Simpler storage.   Hot keys suffer retry storms.
```

### 8.8 — Sloppy Quorum and Hinted Handoff (Dynamo Context)

```
When N nodes in preference list are unavailable, Dynamo uses
SLOPPY QUORUM: write to ANY W available nodes, store HINT
"this belongs to node N3 when it returns."

  Normal: key K → preference list [N1, N2, N3]
  N3 down: write to N1, N4(hint for N3), N5(hint for N3)

  When N3 returns: N4/N5 hand off hinted writes.

INTERACTION WITH VERSION VECTORS:
  Hints carry full version metadata.
  When handoff completes, vv must merge correctly.
  Risk: hinted write concurrent with live write to N3
  → siblings on recovery → client merge required.

  Without vv: hinted handoff + LWW = silent loss of hinted
  write if LWW picks wrong winner on merge.

LESSON: availability mechanisms (sloppy quorum) INCREASE
concurrency surface area. Accurate conflict detection becomes
MORE important, not less.
```

### 8.9 — Dynamo vs DynamoDB — What Amazon Kept and Dropped

```
DYNAMO (2007 paper, internal):
  ✓ Version vectors / siblings
  ✓ Client-side merge
  ✓ Sloppy quorum + hinted handoff
  ✓ Merkle tree anti-entropy
  ✓ Configurable R/W/N

DYNAMODB (managed service):
  ✗ No exposed siblings — conditional writes + LWW internally
  ✓ Optimistic locking via attribute _version (2013+)
  ✓ Strongly consistent read (optional, per-call)
  ✓ Partitions with leader per partition (hidden)
  ✗ Application rarely sees vector clocks

  DynamoDB is NOT "Dynamo you rent" — it's inspired by the
  paper but optimized for operational simplicity.
  Interview: know BOTH — paper for AP conflict model,
  DynamoDB for what AWS actually ships.

  For true Dynamo semantics in AWS ecosystem:
  Consider Cassandra (self-managed) or DocumentDB patterns,
  or implement vv in application layer on top of DynamoDB items.
```

### 8.10 — Conflict Resolution Decision Tree

```
                    [Write to replicated key]
                              │
                              ▼
                    ┌─────────────────────┐
                    │ Single writer       │
                    │ guaranteed?         │
                    └─────────┬───────────┘
                         YES  │  NO
                    ┌─────────┴───────────┐
                    ▼                     ▼
              [Optimistic lock      [Concurrent write
               or simple PUT]        possible]
                    │                     │
                    │                     ▼
                    │           ┌─────────────────────┐
                    │           │ Can merge with math │
                    │           │ (CRDT)?             │
                    │           └─────────┬───────────┘
                    │                YES  │  NO
                    │           ┌─────────┴───────────┐
                    │           ▼                     ▼
                    │      [Use CRDT]          [Version vector
                    │                           + app merge]
                    │                                 │
                    │                                 ▼
                    │                    ┌─────────────────────┐
                    │                    │ Human must resolve? │
                    │                    └─────────┬───────────┘
                    │                         YES  │  NO
                    │                    ┌─────────┴───────────┐
                    │                    ▼                     ▼
                    │              [Escalation queue]    [Auto merge fn]
                    ▼
              [Done]
```

---


## Decision Framework
### 9.1 — Master Comparison Table

```
╔═══════════════════╦═══════════════╦═══════════════╦═══════════════════╗
║                   ║ LAMPORT       ║ VECTOR CLOCK  ║ VERSION VECTOR    ║
╠═══════════════════╬═══════════════╬═══════════════╬═══════════════════╣
║ Size per event    ║ O(1) int      ║ O(N) ints     ║ O(R) ints         ║
╠═══════════════════╬═══════════════╬═══════════════╬═══════════════════╣
║ Detect a→b?       ║ Sound only    ║ Complete      ║ Per-key descendant║
╠═══════════════════╬═══════════════╬═══════════════╬═══════════════════╣
║ Detect concurrent?║ NO            ║ YES           ║ YES (siblings)    ║
╠═══════════════════╬═══════════════╬═══════════════╬═══════════════════╣
║ Total order?      ║ YES (+ tie)   ║ NO (partial)  ║ NO (partial)      ║
╠═══════════════════╬═══════════════╬═══════════════╬═══════════════════╣
║ Primary use       ║ Log sequence  ║ Causal track  ║ Multi-master KV   ║
╠═══════════════════╬═══════════════╬═══════════════╬═══════════════════╣
║ Typical systems   ║ Chubby, logs  ║ COPS, research║ Riak, Voldemort   ║
╚═══════════════════╩═══════════════╩═══════════════╩═══════════════════╝
```

### 9.2 — Decision Framework

```
Q1: Concurrent writes to SAME KEY need BOTH preserved?
    YES → Version vectors + merge OR CRDT
    NO  → Q2

Q2: Single leader/primary for this key?
    YES → Optimistic locking or safe LWW
    NO  → Q3

Q3: Observers must never see effect before cause?
    YES → Causal consistency (LSN / HLC / vector clocks)
    NO  → Q4

Q4: Only need total order for sequencing?
    YES → Lamport (+ process ID tiebreaker)
    NO  → Eventual may suffice

Q5: Cluster size?
    < 100 nodes → Vector clocks feasible
    > 1000 nodes → HLC, dotted version vectors, per-shard clocks
    Planetary → TrueTime + Paxos
```

### 9.3 — Hybrid Logical Clocks (HLC)

```
HLC = (physical_time, logical_counter, process_id)

  Preserves causality. Approximates wall time when clocks sync.
  MongoDB, CockroachDB use internally.

  NOT a drop-in for Dynamo sibling detection.
  Cannot detect concurrency like vector clocks.
```

### 9.4 — Extended Comparison: Conflict Detection Mechanisms

```
╔════════════════════╦════════════╦════════════╦════════════╦════════════╗
║ MECHANISM          ║ DETECT ∥   ║ METADATA   ║ COORD FREE ║ AP/CP TILT ║
╠════════════════════╬════════════╬════════════╬════════════╬════════════╣
║ Lamport LWW        ║ NO         ║ O(1)       ║ YES        ║ AP (lossy) ║
╠════════════════════╬════════════╬════════════╬════════════╬════════════╣
║ Version vector     ║ YES        ║ O(R)       ║ YES        ║ AP         ║
╠════════════════════╬════════════╬════════════╬════════════╬════════════╣
║ Vector clock       ║ YES        ║ O(N)       ║ YES        ║ AP         ║
╠════════════════════╬════════════╬════════════╬════════════╬════════════╣
║ Optimistic lock    ║ YES (retry)║ O(1) ver   ║ PARTIAL    ║ CP on hot  ║
╠════════════════════╬════════════╬════════════╬════════════╬════════════╣
║ Raft log index     ║ NO (total) ║ O(1)       ║ NO (leader)║ CP         ║
╠════════════════════╬════════════╬════════════╬════════════╬════════════╣
║ HLC session        ║ NO         ║ O(1)       ║ PARTIAL    ║ Tunable    ║
╠════════════════════╬════════════╬════════════╬════════════╬════════════╣
║ CRDT               ║ N/A (merge)║ varies     ║ YES        ║ AP         ║
╚════════════════════╩════════════╩════════════╩════════════╩════════════╝
```

### 9.5 — Consistency Model vs Clock Requirement Matrix

```
╔══════════════════════════╦═════════════════════════════════════════════╗
║ PRODUCT REQUIREMENT      ║ MINIMUM CLOCK / MECHANISM                   ║
╠══════════════════════════╬═════════════════════════════════════════════╣
║ Leader election          ║ Consensus log index OR Lamport total order  ║
╠══════════════════════════╬═════════════════════════════════════════════╣
║ Unique username          ║ Linearizable (Raft), not clocks alone       ║
╠══════════════════════════╬═════════════════════════════════════════════╣
║ Shopping cart merge      ║ Version vector OR CRDT OR-Set                 ║
╠══════════════════════════╬═════════════════════════════════════════════╣
║ Comment after post       ║ Causal (session, LSN, or VC)                ║
╠══════════════════════════╬═════════════════════════════════════════════╣
║ Profile read-after-write ║ Primary routing OR opTime (no full VC)      ║
╠══════════════════════════╬═════════════════════════════════════════════╣
║ Cross-region timeline    ║ Causal OR accept eventual reorder of ∥ ops  ║
╠══════════════════════════╬═════════════════════════════════════════════╣
║ Inventory decrement      ║ Linearizable OR LWT — NOT vv merge          ║
╠══════════════════════════╬═════════════════════════════════════════════╣
║ Audit log ordering       ║ Lamport OR physical time if NTP trusted     ║
╚══════════════════════════╩═════════════════════════════════════════════╝
```

### 9.6 — Hybrid Logical Clocks (HLC) — Production Middle Ground

```
HLC = (physical_time, logical_counter, process_id)

  On event:
    l' = max(l, physical_time, received_physical_time)
    if l' == l: logical_counter++
    else: logical_counter = 0
    timestamp = (l', logical_counter, process_id)

PROPERTIES:
  Preserves causality like Lamport/vector.
  Approximates wall time when clocks are reasonable.
  Used internally by MongoDB, CockroachDB.

  CockroachDB HLC excerpt (conceptual):
    - Each node has HLC
    - On txn commit: HLC assigned to write timestamp
    - If local HLC < previous: bump logical part
    - "Clock jump" protection prevents time travel

WHEN HLC BEATS PURE VECTOR:
  - Large clusters (avoid O(N) vectors)
  - SQL databases needing timestamp-indexed reads
  - When you want causality + approximate recency sorting

WHEN HLC FAILS:
  - Large clock skew without bound → ordering surprises
  - Still cannot detect concurrency like vector clocks
  - Not a drop-in for Dynamo sibling detection
```

### 9.7 — Scenario Walkthrough: Pick the Mechanism

```
SCENARIO A — Global config flag, one writer (admin UI):
  → Optimistic locking with version column. No vector needed.

SCENARIO B — Instagram like count (approximate):
  → CRDT counter or atomic increment with eventual sync.
  → LWW loses counts — never LWW.

SCENARIO C — Geo-distributed user profile (name, bio):
  → Per-field version vectors OR last-writer-wins per field
    with server HLC if single-field edits dominate.
  → Full document LWW loses concurrent field edits.

SCENARIO D — Chat thread messages:
  → Causal consistency within thread (parent message id + causal session).
  → Total order NOT required across unrelated threads.

SCENARIO E — Distributed job scheduler claiming tasks:
  → Linearizable compare-and-set (etcd, DynamoDB LWT).
  → Lamport total order alternative if single sequencer acceptable.

SCENARIO F — Merge conflict audit for legal docs:
  → NO automatic merge. Version vectors detect conflict,
    escalate to human. Storage returns siblings explicitly.
```

---


## Production Patterns

### 10.1 — MongoDB Causal Session (JavaScript)

```javascript
const session = client.startSession({ causalConsistency: true });
await session.withTransaction(async () => {
  const post = await posts.insertOne(
    { author: 'alice', text: 'I got the job!' }, { session }
  );
  await comments.insertOne(
    { postId: post.insertedId, text: 'Congrats!' }, { session }
  );
});
await session.endSession();
// ANTI-PATTERN: insert with session, read WITHOUT from secondary
```

### 10.2 — WAL LSN Causal Read (Python + Kafka)

```python
def publish_prescription(conn, event):
    with conn.transaction():
        lsn = conn.execute(
            "INSERT INTO prescriptions (...) RETURNING pg_current_wal_lsn()"
        ).fetchone()[0]
        event["causal_lsn"] = str(lsn)
        kafka_producer.send("prescriptions", event)

def check_allergy(replica, primary, event):
    required = event["causal_lsn"]
    replay = replica.execute("SELECT pg_last_wal_replay_lsn()").fetchone()[0]
    conn = primary if replay < required else replica
    return conn.execute(
        "SELECT 1 FROM allergies WHERE patient_id=%s AND drug=%s",
        (event["patient_id"], event["drug"])
    ).fetchone() is not None
```

### 10.3 — Propagating Causal Context

```
HTTP: X-Causal-Context: base64(json(vector_clock))
Kafka headers: causality-vc on produce/consume
OpenTelemetry baggage: carry VC — NOT the same as trace_id

Traces show request flow. Vector clocks show event causality.
Use both — different jobs.
```

### 10.4 — Observability Metrics

```
sibling_count_histogram     — merge logic health
causal_stale_read_total     — replica lag vs causal window
vector_clock_size_bytes     — metadata bloat alert
lww_overwrite_total         — "my edit vanished" precursor
merge_retry_count           — hot key / optimistic lock pressure
```

### 10.5 — Pattern: Read-Your-Writes Without Full Vector Tracking

```
When a single PostgreSQL primary owns all causal state,
full vector clocks are overkill. Week 3 Approach 1 applies:

  User writes profile → primary ACK
  Set-Cookie: last_write_ts=<commit_time>; Max-Age=5
  Load balancer: if cookie fresh → route to primary
  After 5s → resume replica reads

  Guarantees: read-your-writes for that user
  Does NOT guarantee: cross-client causal ordering
  Cost: near zero metadata

  Upgrade path to causal consistency:
    Attach WAL LSN instead of wall timestamp in cookie.
    Replica serves read only if replay_lsn >= cookie_lsn.
    Primary fallback otherwise.
    Now ANY client reading after a write sees causal state
    for data in that database.
```

### 10.6 — Pattern: Riak-Style Sibling Handling

```python
# Conceptual Riak get/put with dotted version vectors
def get_key(bucket, key):
    resp = riak_client.get(bucket, key)
    if resp.siblings:
        # Application MUST merge — storage cannot guess semantics
        merged = merge_siblings(resp.siblings)
        # put merged to collapse siblings (read repair)
        put_key(bucket, key, merged.value, merged.vtag)
        return merged.value
    return resp.data

def put_key(bucket, key, value, vtag=None):
    obj = riak_client.new(bucket, key, data=value)
    if vtag:
        obj.vtag = vtag  # optimistic: fail if changed
    obj.store()
```

### 10.7 — Pattern: Cassandra Lightweight Transactions vs LWW

```
Cassandra default (non-LWT):
  LWW on client-supplied or server timestamp.
  Concurrent writes → one wins silently. DATA LOSS RISK.

  INSERT INTO cart (user_id, items, writetime)
  VALUES (?, ?, ?)  -- highest writetime wins entire row

Cassandra LWT (Paxos — linearizable per partition key):
  UPDATE cart SET items = items + ['apple']
  WHERE user_id = ? IF EXISTS;

  IF NOT EXISTS path for create-if-absent.
  Cost: 4x round trips (Paxos prepare/promise/propose/commit)
  Use for: inventory, leader election, uniqueness
  Not for: high-write shopping carts at scale

  Middle ground for carts:
    Per-item rows (one C* row per SKU) — reduces conflict blast radius
    OR application-level version vectors in blob column
    OR offload to DynamoDB-style store for cart specifically
```

### 10.8 — Hands-On Exercise 1: Lamport Clock Message Simulation

```
GOAL: Verify Lamport soundness and false-positive ordering.

Setup — three terminal processes exchanging JSON messages over stdin/out
or a shared file queue.

Process P1:
  1. Local event → print timestamp
  2. Send {ts, msg:"hello"} to P2
  3. Wait for reply
  4. Local event → print timestamp

Process P2:
  1. Receive → merge timestamp
  2. Local event
  3. Send reply

Process P3 (concurrent):
  1. Local event BEFORE any message arrives
  2. Compare: is P3's event "before" P2's receive in Lamport order?
  3. Answer: MAYBE — even if concurrent in reality

VERIFY:
  All causally related pairs have increasing timestamps.
  Find at least one pair where L(a) < L(b) but a ∦ b (concurrent).
  That pair is your interview talking point.
```

### 10.9 — Hands-On Exercise 2: Detect Siblings with Version Vectors

```python
#!/usr/bin/env python3
"""Run: py -3 vv_lab.py — prints sibling detection scenarios."""

def dominates(a: dict, b: dict) -> bool:
    keys = set(a) | set(b)
    return (all(a.get(k, 0) >= b.get(k, 0) for k in keys)
            and any(a.get(k, 0) > b.get(k, 0) for k in keys))

def relation(a: dict, b: dict) -> str:
    if a == b:
        return "equal"
    if dominates(a, b):
        return "a descends b"
    if dominates(b, a):
        return "b descends a"
    return "CONCURRENT (siblings)"

scenarios = [
    ({"R1": 1, "R2": 0}, {"R1": 0, "R2": 1}, "two-region concurrent cart"),
    ({"R1": 2, "R2": 1}, {"R1": 1, "R2": 1}, "merged after sibling resolution"),
    ({"R1": 3, "R2": 2}, {"R1": 3, "R2": 2}, "identical replicas"),
    ({"R1": 5}, {"R1": 3, "R2": 1}, "one replica ahead — descendant"),
]

for a, b, label in scenarios:
    print(f"{label:40} → {relation(a, b)}")
```

### 10.10 — Hands-On Exercise 3: MongoDB Causal Session Failure

```
1. Start 3-node replica set (Docker compose or Atlas free tier).
2. Open two mongo shells with causal session A and B.
3. Session A: insert post, note operationTime via db.adminCommand({getParameter:1})
4. Session B (no prior ops): read posts from SECONDARY with
   readPreference secondary — may miss A's write (expected).
5. Session A: insert comment referencing post — succeeds in session.
6. Session B: read comments from secondary — CAN see comment BEFORE post
   if causality not enforced → BUG REPRODUCTION
7. Fix: session B uses same causal session OR readConcern majority + afterClusterTime

Document: screenshot operationTime vs secondary lag.
This connects Week 3 anomaly to Week 8 mechanism.
```

---

## Failure Modes

```
╔════════════════════════════════════════════════════════════════════╗
║   FAILURE MODE #1: LAMPORT FOR CONFLICT DETECTION                  ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║   System: Multi-region cart service. Engineer uses Lamport         ║
║   timestamps attached at API gateway for "versioning."             ║
║                                                                    ║
║   Region US: add apple  (L=42)                                     ║
║   Region EU: add banana (L=41) — concurrent, but L(EU) < L(US)     ║
║                                                                    ║
║   Merge policy: "keep higher Lamport timestamp."                   ║
║   Result: banana write discarded. User in EU sees item vanish.     ║
║                                                                    ║
║   Root cause: Lamport does NOT detect concurrency.                 ║
║   L(EU) < L(US) does not mean EU write causally precedes US.       ║
║                                                                    ║
║   Fix: Version vectors per cart key. Concurrent → union merge.     ║
║   Or: CRDT OR-Set for cart items (Week 8 Topic 3).                 ║
╠════════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #2: UNBOUNDED SIBLING EXPLOSION                     ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║   System: Riak/Voldemort-style KV. Mobile clients sync offline.    ║
║   Client never merges siblings — always reads, never PUT merge.    ║
║                                                                    ║
║   Each offline edit creates new sibling.                           ║
║   Key cart:user-123 accumulates 847 siblings over 6 months.        ║
║   GET latency: 12 seconds. Object size: 4 MB.                      ║
║   Merge function runs O(n) on siblings — timeouts cascade.         ║
║                                                                    ║
║   Root cause: Missing client merge + no sibling count alert.       ║
║                                                                    ║
║   Fix:                                                             ║
║   - Alert sibling_count > 2 for any key                            ║
║   - Server-side forced merge on read (if semantics allow)          ║
║   - Dotted version vectors to cap metadata                         ║
║   - CRDT for offline-first data types                              ║
╠════════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #3: VECTOR CLOCK SIZE EXPLOSION                     ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║   System: Microservices (200 services) pass full vector clock      ║
║   in every HTTP header. Each service = one vector index.           ║
║                                                                    ║
║   Header size: 200 × 8 bytes = 1.6 KB per request minimum.         ║
║   Load balancer rejects requests (header limit 8 KB with JWT).     ║
║   CPU spent merging vectors dominates business logic.              ║
║                                                                    ║
║   Root cause: Vector clock indexed by SERVICE not by logical       ║
║   replication group. N grows with architecture, not replicas.      ║
║                                                                    ║
║   Fix:                                                             ║
║   - Causal metadata only on writes that need it (safety path)      ║
║   - HLC or WAL LSN for single-database causality                   ║
║   - Per-shard vector clocks (size = shard replica count)           ║
║   - Causal broadcast trees (reduce fan-out metadata)               ║
╠════════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #4: EFFECT BEFORE CAUSE (CAUSAL VIOLATION)          ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║   System: Social app. Notification service reads from Redis        ║
║   replica. Post service writes to Postgres primary.                ║
║                                                                    ║
║   Flow:                                                            ║
║   1. Post created in Postgres (post_id=991)                        ║
║   2. CDC event → notification worker                               ║
║   3. Worker writes "Alice posted!" to Redis primary                ║
║   4. Bob's feed read from Redis REPLICA (stale — no post metadata) ║
║   5. Bob sees notification, taps through                           ║
║   6. Post API read from Postgres replica — post exists             ║
║   BUT alternate ordering: notification visible while post 404      ║
║   on CDN edge cache that hasn't invalidated.                       ║
║                                                                    ║
║   Root cause: No causal link between notification write and        ║
║   post visibility. Different stores, no shared clock domain.       ║
║                                                                    ║
║   Fix:                                                             ║
║   - Notification includes post snapshot OR post_id + version       ║
║   - Client fetches post with If-None-Match / version check         ║
║   - Single causal store for user-visible timeline                  ║
║   - Or: delay notification until post read-repair completes        ║
╠════════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #5: LWW + NTP STEP                                  ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║   System: Cassandra inventory. writetime from client system clock. ║
║                                                                    ║
║   Tuesday 02:00: chrony steps clock BACK 500ms on warehouse node.  ║
║   Writes during step window get LOWER writetime than prior writes. ║
║   LWW discards "newer" business writes as "older."                 ║
║   Inventory count wrong by 12 units. Discovered at audit.          ║
║                                                                    ║
║   Root cause: Trusting physical time for ordering.                 ║
║                                                                    ║
║   Fix:                                                             ║
║   - Server-side HLC or microsecond server timestamp only           ║
║   - LWT for inventory mutations                                    ║
║   - Never client-supplied writetime for authoritative data         ║
╠════════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #6: LOST CAUSAL CONTEXT ACROSS SERVICE BOUNDARY     ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║   System: Order service → Payment service → Inventory service      ║
║   Order service attaches vector clock in internal API call.        ║
║   Payment service processes, calls Inventory via DIFFERENT         ║
║   message bus (Kafka) — drops vector clock header.                 ║
║                                                                    ║
║   Inventory decrements stock based on stale read — oversell.       ║
║                                                                    ║
║   Root cause: Causal context not propagated on ALL edges.          ║
║   One broken link breaks the chain.                                ║
║                                                                    ║
║   Fix:                                                             ║
║   - Causal metadata in Kafka headers (mandate via schema/lint)     ║
║   - Or: inventory mutation keyed by order_id with idempotency      ║
║   - Or: saga with linearizable inventory partition (Raft)          ║
╠════════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #7: FALSE MERGE (SEMANTIC CONFLICT)                 ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║   System: Dynamo-style document store. Two siblings:               ║
║   v1: {status: "shipped", qty: 5}                                  ║
║   v2: {status: "cancelled", qty: 5}                                ║
║                                                                    ║
║   Naive merge: field-wise max timestamp / union                    ║
║   Result: {status: ["shipped","cancelled"], qty: 5}  OR worse      ║
║   LWW picks "shipped" — order ships after cancel.                  ║
║                                                                    ║
║   Root cause: Version vectors detect SYNTACTIC conflict.           ║
║   Application merge must enforce BUSINESS INVARIANTS.              ║
║                                                                    ║
║   Fix:                                                             ║
║   - Domain-specific merge (cancel wins over ship)                  ║
║   - OR escalate to human / manual resolution queue                 ║
║   - OR use strong consistency for state machine transitions        ║
╚════════════════════════════════════════════════════════════════════╝
```

### 11.1 — Debugging Checklist

```
SYMPTOM: "User's edit disappeared"
  → Check LWW overwrite metrics
  → Compare writetime / version vector of lost vs surviving write
  → Were writes concurrent? (version vectors should show siblings)
  → If no siblings returned: detection mechanism failed

SYMPTOM: "Reply appeared before original post"
  → Causal consistency violation
  → Trace read path: session token? primary? replica lag?
  → Is causal metadata propagated on the write that triggered reply?

SYMPTOM: "Cart has duplicate/weird items after offline sync"
  → Sibling merge semantics wrong (union vs quantity add)
  → Check sibling count on key
  → Verify client merge on every GET with siblings

SYMPTOM: "Latency spike on reads for hot key"
  → Sibling explosion on that key
  → GET returning hundreds of versions
  → Emergency: force merge, add sibling cap, block writes until resolved

SYMPTOM: "Cross-region ordering surprises"
  → Expected under eventual/causal — concurrent ops reorder
  → If NOT expected: verify requirement isn't linearizability
  → Upgrade model or route conflicting ops through single leader
```

### 11.2 — SRE Toolkit Commands

```bash
# Riak — list buckets with sibling stats (conceptual)
riak-admin stats | grep siblings

# Cassandra — compare writetimes on conflicting rows
cqlsh -e "SELECT writetime(items) FROM cart WHERE user_id='u1';"

# MongoDB — check replication lag vs operationTime
mongosh --eval '
  rs.printSecondaryReplicationInfo();
  db.adminCommand({hello:1}).operationTime;
'

# Postgres — causal LSN check (from Week 3 toolkit)
psql -h replica -c "
  SELECT pg_last_wal_replay_lsn() AS replay,
         pg_last_wal_receive_lsn() AS received;"

# Application — log vector clock comparison result on every merge
# Structured log:
# {"event":"vv_compare","key":"cart:1","result":"concurrent",
#  "vv_a":{"R1":1,"R2":0},"vv_b":{"R1":0,"R2":1}}
```

---

## SRE Diagnostic Toolkit

```
CLOCK/CAUSALITY BUGS LOOK LIKE DATA BUGS. The tell is "effect before cause",
lost concurrent updates, or values that flip based on which replica answered.

WHAT TO INSTRUMENT
  Sibling / conflict rate (leaderless stores):
    Cassandra/Dynamo: count of concurrent versions merged per key.
    A spike after a deploy = someone changed the conflict-resolution path.
  LWW overwrite rate:
    how often a write is discarded because another had a higher timestamp.
    High + cross-region = clock-skew-driven data loss (see incident).
  Clock skew between nodes:
    NTP/chrony offset per host; alert if |offset| > 100ms.
    node_timex_offset_seconds (node_exporter) or chronyc tracking.
  Causal-order violations (app-level SLI):
    emit a counter when a read observes an effect whose cause it has NOT seen
    (e.g., a reply whose parent message is missing).

COMMANDS / QUERIES
  Clock discipline:
    chronyc tracking ; chronyc sources -v
    timedatectl status            # NTP synchronized: yes/no
  Postgres logical position (for causal/read-your-writes routing):
    SELECT pg_current_wal_lsn();                 -- on primary after write
    SELECT pg_last_wal_replay_lsn();             -- on replica before read
  Application merge logging (structured):
    {"event":"vv_merge","key":"cart:42","result":"concurrent",
     "vv_a":{"R1":2,"R2":0},"vv_b":{"R1":0,"R2":1}}
    -> grep result="concurrent" to quantify true concurrency vs false conflicts.

DIAGNOSTIC DECISION TREE
  Value goes backward / update lost?
    Concurrent writers? -> conflict, need vector clocks + merge (NOT LWW).
    Single writer, replica lag? -> Week 3/4 replication problem, not clocks.
  "Reply before message", "comment before post"?
    -> causal metadata missing on the read path; add causal token / version vector.
  LWW picking the wrong winner across regions?
    -> wall-clock skew; switch to logical clocks / HLC, fix NTP.

LOG / SIGNATURE PATTERNS
  child span starts before parent (traces)   -> host clock skew, not app bug
  "merged N siblings" growing                -> conflict storm; check write path
  cross-region write always loses            -> gateway timestamp skew (LWW trap)
```

---

## Incident Scenario
### 12.1 — Production Scenario: "The Vanishing Bananas"

```
╔══════════════════════════════════════════════════════════════════╗
║   INCIDENT BRIEF — GROCERY CART PLATFORM                         ║
║   Severity: SEV-2 (revenue impact, no data breach)               ║
║   Duration: 11 days (slow burn before escalation)                ║
╚══════════════════════════════════════════════════════════════════╝

ARCHITECTURE:

  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
  │  US-East    │     │  US-West    │     │  EU-West    │
  │  API + KV   │     │  API + KV   │     │  API + KV   │
  │  replica R1 │     │  replica R2 │     │  replica R3 │
  └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                    Dynamo-style quorum (N=3, W=2, R=2)
                    Version vectors per cart key
                    Client-side merge: set union on SKU

TIMELINE:

  Day 1 — Deploy v2.14.0
    "Optimization: use Lamport timestamp from API gateway
     instead of full version vector — reduces payload 40%."

  Day 2-4 — Support tickets trickle in
    "Items missing from cart" — 12 tickets/day (baseline: 2)
    All from users who shopped across mobile + web same session.
    EU support notes pattern: "bananas vanish, apples stay."

  Day 5 — Engineer investigates
    Logs show concurrent writes US + EU for cart:user-8842:
      US write: {banana}, gateway_ts=1847291000001
      EU write: {apple},  gateway_ts=1847291000000
    Merge code: if new_ts > stored_ts: replace else discard
    banana ts > apple ts → US write wins entire cart snapshot
    EU user's apple merge intended union — got overwrite

  Day 6 — False lead
    Team checks NTP drift — all regions within 2ms. "Not clocks."
    Correct: NTP is fine. Wrong mechanism was chosen.

  Day 8 — Sibling metric introduced retroactively from logs
    Estimated 340,000 carts experienced at least one wrong LWW merge
    Revenue impact: $890K abandoned carts (SEV-2 math)

  Day 9 — Rollback to v2.13.0 (full version vectors)
    Client merge restored. No new bad merges.
    Existing corrupted carts: batch job compares vv history,
    attempts union merge from audit log siblings.

  Day 11 — Post-incident review scheduled

YOUR ROLE: Staff engineer, first responder Day 5 onward.
```

### 12.2 — Scenario Analysis (Principal-Grade)

```
ROOT CAUSE (one sentence):
  Deploy v2.14.0 replaced version-vector sibling detection with
  Lamport gateway timestamps, causing concurrent cross-region cart
  writes to be serialized incorrectly via LWW semantics.

CONSISTENCY MODEL VIOLATED:
  Not causal consistency — concurrent writes are allowed to conflict.
  Violated invariant: CONFLICT PRESERVATION — concurrent updates
  must become siblings, not silent overwrites.

WHY LAMPORT FAILED HERE:
  US banana write and EU apple write were CONCURRENT.
  Gateway assigned Lamport-like monotonic ts per region but
  US ts > EU ts → false total order → LWW discarded EU state.

CORRECT MECHANISM:
  Version vectors {R1:1,R2:0} vs {R1:0,R2:1} → concurrent
  → siblings → client union merge → {apple, banana}
  vv merged → {R1:1,R2:1}

IMMEDIATE MITIGATION (Day 5):
  1. Rollback v2.14.0 (feature flag if rollback slow)
  2. Disable cross-region concurrent cart writes → route to
     nearest leader (availability hit, correctness win)
  3. Alert: any cart PUT that replaces without vv dominance check

REPAIR (Day 9-11):
  Replay audit log of cart writes with vv reconstruction.
  For keys with overlapping concurrent window: force union merge.
  Email affected users + credit.

PREVENT (permanent):
  1. CI test: concurrent PUT simulation MUST produce siblings
  2. Code review rule: no Lamport/LWW for multi-writer keys
  3. Metric: lww_overwrite_without_dominance_total → page
  4. Design doc required for any change to cart conflict path
```

### 12.3 — Scenario Timeline Diagram

```
REAL TIME (concurrent window ~200ms) ─────────────────────────►

  EU user:  ──write(apple)──►  R3 vv={R1:0,R2:0,R3:1}
  US user:  ──write(banana)─► R1 vv={R1:1,R2:0,R3:0}

  CORRECT (v2.13.0):
    GET → siblings [apple, banana] → merge → both items

  BROKEN (v2.14.0):
    US ts=1001 > EU ts=1000 → cart={banana} ONLY
    EU user refreshes → apples gone → support ticket

  CAUSALITY NOTE:
    These writes are NOT causally related — no happens-before.
    Causal consistency allows them in either order BUT both
    must eventually be visible. LWW violates "both visible."
```

### 12.4 — Five In-Depth Questions

---

#### Q1: Lamport vs Vector — When Does the Difference Matter?

**Question:** Your teammate says: "We already attach Lamport timestamps to every event in our event bus. That gives us causal ordering. We don't need vector clocks." What is wrong with this claim, and when would the teammate be partially right?

**Answer:**

The claim conflates **soundness** with **completeness**.

Lamport guarantees: if event A happens-before event B, then L(A) < L(B). That is **causal soundness** — the order respects all known dependencies.

Lamport does NOT guarantee: if L(A) < L(B), then A happens-before B. Two **concurrent** events can receive timestamps where L(A) < L(B) arbitrarily. Any system that interprets L(A) < L(B) as "A before B" for merge or visibility decisions will **silently discard** concurrent work. That is exactly the grocery cart incident.

The teammate is **partially right** when:

1. **Total order is sufficient** — lock ordering, log sequencing, "pick any deterministic order" without preserving concurrent branches. Example: Chubby lock queue.

2. **Single writer per key** — no concurrency means no siblings to detect. Lamport timestamps audit ordering without harm.

3. **Downstream only needs "roughly increasing" timestamps** — metrics, log correlation, not conflict detection.

4. **Causal consistency via a single total-order log** — if ALL events pass through one Kafka partition or one Raft log, the log's offset IS the order. Lamport on top adds little. Causality is enforced by the log, not the timestamp.

The teammate is **wrong** when:

1. **Multi-master or multi-region writes** to the same key without coordination.

2. **Conflict detection** — need to know "concurrent" vs "descendant."

3. **Client-side merge** (Dynamo model) — must receive siblings, not one LWW winner.

4. **Causal consistency across independent replicas** without central sequencer — need vector clocks, HLC with proper session tracking, or equivalent dependency metadata.

**Interview one-liner:** "Lamport tells you what definitely happened first. Vector clocks also tell you when two things definitely did NOT ordered — they were concurrent."

---

#### Q2: Design Causal Allergy Check (Week 3 Callback)

**Question:** Redesign the Week 3 prescription-allergy safety check using explicit causal metadata. Compare WAL LSN approach vs vector clock approach. When does each apply?

**Answer:**

**Week 3 problem recap:** Prescription event processed before allergy update visible → causal violation → patient safety risk.

**Approach A — WAL LSN (single Postgres domain):**

```python
# On prescription commit
event = {"patient_id": 4521, "drug": "penicillin",
         "causal_lsn": str(wal_lsn_at_commit)}

# Allergy check consumer
def safe_read(conn_replica, conn_primary, required_lsn):
    replay = get_replay_lsn(conn_replica)
    if replay < required_lsn:
        return query(conn_primary)
    return query(conn_replica)
```

- **Applies when:** All causal state (allergies, prescriptions) lives in ONE PostgreSQL cluster. Causality is total order of WAL.

- **Pros:** O(1) metadata, simple, fast, proven in Week 3 action items.

- **Cons:** Breaks if allergies move to Redis cache (different store), or multi-region active-active Postgres.

**Approach B — Vector clock (multi-store / multi-region):**

```python
# Allergy update at replica R1
vc_allergy = {"R1": 5, "R2": 3}

# Prescription service reads allergy, gets vc_allergy
# Prescription write includes dependency: depends_on=vc_allergy
event = {"patient_id": 4521, "drug": "penicillin",
         "depends_on_vv": vc_allergy}

# Allergy check: read must return state whose vv DOMINATES depends_on_vv
```

- **Applies when:** Allergies in Redis, prescriptions in Postgres, or geo-distributed writers.

- **Pros:** Works across service boundaries if context propagated.

- **Cons:** Metadata size, merge complexity, all services must participate.

**Minimum correct model (Week 3):** Causal consistency — read reflects all writes that causally precede the triggering event. LSN achieves this for single DB. Vector clock achieves this across stores.

**Production recommendation:** Start with LSN (cheapest). If allergies cached in Redis, either (1) read-through primary Postgres for safety path only, or (2) attach vv to Redis writes and enforce dominance on safety read.

---

#### Q3: Dynamo Siblings — Who Should Merge?

**Question:** Dynamo paper pushes conflict resolution to the client. Critics say this is "irresponsible" — storage should merge. Argue both sides and give your production recommendation for a collaborative document editor vs a shopping cart.

**Answer:**

**Dynamo/client-merge argument:**

- **Semantic knowledge lives in application.** Storage sees bytes. Only the app knows cart = union, inventory = NOT mergeable, text = character-level merge.

- **Availability.** Server-side strong merge requires coordination or CRDT structure chosen at write time. Client merge keeps AP properties.

- **Flexibility.** Different clients (mobile vs web) can upgrade merge logic independently.

**Critics/server-merge argument:**

- **Many clients are buggy.** Mobile app v1.0 never merges → sibling explosion (Failure Mode #2).

- **Security.** Malicious client can ignore siblings, overwrite history.

- **Operational burden.** 847 siblings on one key is a storage incident, not "client bug."

**Shopping cart recommendation:**

- **Server-side default merge on read** with union semantics (idempotent, commutative).
- Client CAN override but never required.
- Alert sibling_count > 1 after merge.
- Version vectors remain authoritative for detection.

**Collaborative document editor recommendation:**

- **Do NOT use naive Dynamo siblings** for rich text — union merge destroys documents.
- Use **CRDT** (RGA, Yjs, Automerge) — Week 8 Topic 3 — where merge is mathematically defined.
- If stuck on Dynamo-style KV: store CRDT state blob per key, not plain text siblings.
- Server may run merge for compaction but merge function = CRDT merge, not LWW.

---

#### Q4: Partial Order in the Interview — Whiteboard Problem

**Question:** Whiteboard: Processes P1, P2, P3. P1 sends m1 to P2. P2 receives m1, sends m2 to P3. P3 sends m3 to P1 concurrently with P2's send. Draw happens-before, assign Lamport timestamps, assign vector clocks (N=3), identify concurrent pairs.

**Answer:**

```
Events:
  e1: P1 local (before send m1)
  e2: P1 send m1
  e3: P2 recv m1
  e4: P2 send m2
  e5: P3 recv m2  (after e4)
  e6: P3 send m3   (concurrent with e4 if no ordering with e4)
  e7: P1 recv m3

Happens-before chains:
  e1 → e2 → e3 → e4 → e5
  e6 → e7
  e4 ∥ e6 (if m3 send doesn't depend on m2 — problem says concurrent)

Lamport (sample assignment):
  e1=1, e2=2, e3=3, e4=4, e5=5, e6=1 (concurrent branch at P3), e7=6
  Note L(e6)=1 < L(e4)=4 but e6 ∦ e4 — classic trap.

Vector clocks:
  After e3 at P2: [2,1,0]
  After e4 at P2: [2,2,0]
  After e5 at P3: [2,2,1]
  e6 at P3 (concurrent, before e5): [0,0,1] or similar independent branch
  Compare e4 [2,2,0] vs e6 [0,0,1]: CONCURRENT

Concurrent pairs: (e4, e6), and any cross-branch incomparable events.

Follow-up: "Which consistency model allows e6 before e4 for one observer?"
  → Eventual and causal (both allow concurrent reordering).
  Sequential and linearizable would require picking one order globally.
```

---

#### Q5: Capacity Planning — Vector Clock Metadata at Scale

**Question:** 500 microservices, each request fans out to 8 downstream calls. PM asks to "add vector clocks for full causal tracing." Estimate metadata size, identify breaking point, propose alternative.

**Answer:**

**Naive design:** One vector index per microservice → N=500.

- Vector size: 500 × 8 bytes (int64) = 4 KB per event minimum.
- Fan-out chain: each hop merges vector — CPU O(N) per request.
- 8 hops: 8 × merge(500) = 4000 comparisons per end-to-end request at p99.
- HTTP/2 header limit, gRPC metadata limits — **broken before production.**

**Breaking point:** N > ~50 for inline per-request metadata in HTTP. Depends on header budget; 4 KB kills latency on mobile networks.

**Alternatives (production-grade):**

1. **Causal only on critical path** — allergy check, payment, inventory. Not on analytics.

2. **HLC (3×8 bytes = 24 bytes)** — Mongo/Cockroach model. Causality without O(N).

3. **Per-shard clocks** — cart service 3 replicas → vv size 3, not 500.

4. **External causal store** — write dependency graph to Redis/DB keyed by trace_id; services lookup, don't carry full VC in headers.

5. **Kafka partition ordering** — causality scoped to partition; cross-partition use saga + idempotency.

6. **Dotted version vectors** — bound size for long-lived keys.

**Recommendation to PM:** "Full causal tracing across 500 services" is a research project, not a sprint. Phase 1: HLC + WAL LSN on financial/safety paths. Phase 2: vv per storage shard for multi-master keys. Phase 3: evaluate Causal tracing product (Honeycomb/Baggage) for debug, not inline VC.

---

### 12.5 — Key Takeaways

```
╔══════════════════════════════════════════════════════════════════╗
║   1. PARTIAL ORDER is the native order of distributed systems.   ║
║      Total order is always an artificial extension.              ║
╠══════════════════════════════════════════════════════════════════╣
║   2. LAMPORT: O(1), total order extension, sound for →,          ║
║      NOT complete — never use for conflict detection.            ║
╠══════════════════════════════════════════════════════════════════╣
║   3. VECTOR CLOCKS: complete concurrency detection, O(N),        ║
║      for event causality and debugging.                          ║
╠══════════════════════════════════════════════════════════════════╣
║   4. VERSION VECTORS: per-key replica tracking, Dynamo siblings, ║
║      client merge — NOT the same as vector clocks.               ║
╠══════════════════════════════════════════════════════════════════╣
║   5. CAUSAL CONSISTENCY (Week 3) = preserve →, allow ∥.          ║
║      Implemented via VC, HLC sessions, or WAL LSN.               ║
╠══════════════════════════════════════════════════════════════════╣
║   6. LWW is a footgun for concurrent writes. Accept only with    ║
║      single-writer proof or CRDT math backing you.               ║
╠══════════════════════════════════════════════════════════════════╣
║   7. Detect conflict in storage; resolve conflict in application ║
║      — but server-side safe defaults prevent client bugs.        ║
╠══════════════════════════════════════════════════════════════════╣
║   8. Propagate causal metadata on EVERY edge or accept breaks.   ║
╠══════════════════════════════════════════════════════════════════╣
║   9. Metric sibling_count and lww_overwrite BEFORE tickets.      ║
╠══════════════════════════════════════════════════════════════════╣
║   10. Minimum mechanism: pick weakest clock that satisfies the   ║
║       consistency model — LSN before VC, VC before TrueTime.     ║
╚══════════════════════════════════════════════════════════════════╝
```

### 12.6 — Targeted Reading

```
PRIMARY (read these):

  1. Leslie Lamport — "Time, Clocks, and the Ordering of Events
     in a Distributed System" (1978)
     → The original. 17 pages. Defines →, Lamport clocks.
     → https://lamport.azurewebsites.net/pubs/time-clocks.pdf

  2. DeCandia et al. — "Dynamo: Amazon's Highly Available Key-value
     Store" (SOSP 2007)
     → Version vectors, siblings, quorum, client merge.
     → Required for Dynamo-style interview questions.

  3. Week 3 — Consistency Models.md (causal consistency section)
     → The guarantee this module implements.

SECONDARY (skim / reference):

  4. Fidge / Mattern — vector clock original papers (1988)
     → Historical; modern treatments in textbooks suffice.

  5. Bailis et al. — "COPS" and "Eiger" (NSDI)
     → Causal consistency at geo-scale. Research → production gap.

  6. Kulkarni et al. — "Logical Physical Clocks" (HLC paper)
     → CockroachDB/MongoDB internals.

  7. Riak documentation — dotted version vectors
     → Practical bounded metadata.

  8. MongoDB manual — "Causal Consistency"
     → operationTime, afterClusterTime, session API.

CROSS-MODULE:

  Week 5 — Multi-Master Conflict Resolution (Database Scaling)
  Week 6 — Kafka ordering, event metadata propagation
  Week 8 Topic 3 — CRDTs (alternative to sibling merge)
  Week 4 — Raft log as total order source
```

### 12.7 — Cross-Module Concept Map

```
╔══════════════════════════════════════════════════════════════════╗
║   PRIOR MODULE              │  CONNECTION                        ║
╠══════════════════════════════════════════════════════════════════╣
║  Week 3: Consistency Models │  Causal consistency DEFINITION;    ║
║                             │  allergy-check scenario; LSN fix   ║
╠══════════════════════════════════════════════════════════════════╣
║  Week 4: Raft               │  Log index = total order; not for  ║
║                             │  cross-key concurrency detection   ║
╠══════════════════════════════════════════════════════════════════╣
║  Week 5: DB Scaling       │  Multi-master vv; read-your-writes   ║
║                             │  routing patterns                  ║
╠══════════════════════════════════════════════════════════════════╣
║  Week 6: Kafka              │  Partition order; causal headers   ║
║                             │  on events; outbox LSN             ║
╠══════════════════════════════════════════════════════════════════╣
║  Week 8 T3: CRDTs           │  Alternative when merge = math     ║
║                             │  not application logic             ║
╚══════════════════════════════════════════════════════════════════╝
```

### 12.8 — Interview Rapid Fire

```
Q: What's the difference between Lamport and vector clocks?
A: Lamport gives O(1) total order extension, sound for causality
   but can't detect concurrency. Vector clocks detect concurrent
   events, O(N) space.

Q: What's the difference between vector clocks and version vectors?
A: Vector clocks track event causality per process. Version vectors
   track per-replica write counts per KEY for conflict detection.

Q: When is LWW safe?
A: Single writer per key, immutable values, or when lost concurrent
   writes are acceptable (metrics). Never for read-modify-write carts.

Q: How does MongoDB do causal consistency without exposing VC?
A: Hybrid Logical Clocks + session operationTime + readConcern
   majority ensures reads reflect session's causal past.

Q: Dynamo returned two values on GET. What happened?
A: Concurrent writes — siblings. Client must merge and PUT back.

Q: If a → b, what do we know about L(a) and L(b)? L(a) < L(b).
   If L(a) < L(b), what do we know about a and b? NOTHING — may
   be concurrent. The interview trap.
```

---

*End of Week 8, Topic 2 — Lamport Clocks, Vector Clocks, and Causality*

*Next: Week 8, Topic 3 — CRDTs and Conflict Resolution*

---

## Appendix A: Glossary

```
happens-before (→)     Partial order relation between events
concurrent (∥)         Neither event happens-before the other
partial order          Some pairs ordered, some incomparable
total order            All pairs comparable
Lamport timestamp      Single integer logical clock per process
vector clock           Integer vector per process for event causality
version vector         Per-replica counters per KEY for conflict detect
sibling                Concurrent versions of same key (Dynamo term)
domination             V1 dominates V2 if V1 strictly descends V2
LWW                    Last-Write-Wins — timestamp picks single winner
HLC                    Hybrid Logical Clock — (physical, logical, id)
causal consistency     Preserve →, allow ∥ reordering
read-your-writes       Client sees own prior writes
sloppy quorum          Write to alternate nodes when preference list down
hinted handoff         Deferred delivery of writes to recovering node
read repair            Fix lagging replicas on read path
anti-entropy           Background replica sync (Merkle trees)
```

## Appendix B: Quick Reference Card

```
NEED                          USE
────────────────────────────────────────────────────
Total order of events         Lamport + process ID
Detect concurrent writes      Version vector or vector clock
Causal consistency (1 DB)     WAL LSN / read primary
Causal consistency (multi)    HLC session or vector clock
Dynamo-style AP conflicts     Version vector + client merge
Safe inventory / balance      Raft / LWT — NOT vv merge
Interview trap answer         L(a)<L(b) does NOT imply a→b
```




---

## Key Takeaways

```
1. Lamport timestamps give total order, NOT causality.
2. Vector clocks detect concurrency; version vectors track replica divergence.
3. LWW with wall clocks fails under skew — siblings need explicit merge.
4. Causal consistency uses session tokens or vector metadata, not NTP alone.
5. Pick the weakest clock mechanism that satisfies the product invariant.
```

---

## Targeted Reading

- Lamport "Time, Clocks, and the Ordering of Events" (1978)
- Dynamo paper — vector clocks and sibling merges
- DDIA Ch 8–9
