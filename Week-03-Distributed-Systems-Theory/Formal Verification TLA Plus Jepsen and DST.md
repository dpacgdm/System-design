# Formal Verification, Jepsen Testing & Deterministic Simulation Testing (DST)

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════════════╗
║ AFTER THIS TOPIC, YOU WILL BE ABLE TO:                                   ║
╟──────────────────────────────────────────────────────────────────────────╢
║                                                                          ║
║ 1. Specify distributed system invariants using TLA+ mathematical logic   ║
║    and verify state spaces with the TLC Model Checker.                   ║
║                                                                          ║
║ 2. Distinguish Safety invariants (nothing bad happens) from Liveness     ║
║    invariants (something good eventually happens) in protocol specs.     ║
║                                                                          ║
║ 3. Design Jepsen black-box fault injection tests with Nemesis partitions ║
║    and validate execution logs with linearizability checkers (Knossos).  ║
║                                                                          ║
║ 4. Implement Deterministic Simulation Testing (DST) using virtual time,  ║
║    seeded PRNGs, and simulated I/O to catch subtle concurrency bugs.     ║
║                                                                          ║
║ 5. Analyze real-world DST architectures (FoundationDB, TigerBeetle,      ║
║    Turmoil) to build bug-free consensus and state machine engines.       ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "Unit tests and integration tests can prove correctness"       ║
╟─────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Concurrency bugs in distributed protocols (e.g., Raft leader election    ║
║ split-brain, stale read races) require specific thread interleavings and        ║
║ network message re-ordering that occur 1 in 10^9 executions. Traditional        ║
║ testing only explores a fraction of state space.                                ║
╠═════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #2: "TLA+ is just academic theory, not used in production"         ║
╟─────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. AWS (S3, DynamoDB, EBS), MongoDB, and Azure use TLA+ to formally         ║
║ verify core consensus and replication protocols before writing code. TLA+       ║
║ routinely uncovers catastrophic subtle bugs in designs that passed peer review. ║
╠═════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #3: "Jepsen testing is only for database creators"                 ║
╟─────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Any architecture combining local caching, leader election, outbox CDC    ║
║ queues, or distributed locks needs Jepsen-style fault injection. If you         ║
║ don't fault-inject your system with clock skew and partitions, production       ║
║ will do it for you.                                                             ║
╠═════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #4: "Chaos Engineering (Chaos Mesh/Litmus) is the same as DST"     ║
╟─────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Chaos engineering injects real-time random faults into non-deterministic ║
║ production/staging clusters. If a bug is caught, it cannot be reproduced        ║
║ deterministically. DST runs the entire system inside a single-threaded          ║
║ deterministic virtual time environment where every bug is 100% reproducible.    ║
╚═════════════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

### 1. TLA+ Formal Specification & Model Checking

**TLA+** (Temporal Logic of Actions), created by Leslie Lamport, is a formal specification language based on mathematical set theory and temporal logic.

#### The Core TLA+ Formula Structure

A system in TLA+ is modeled as a set of states and state transitions (Actions):

$$\text{Spec} \triangleq \text{Init} \land \Box[\text{Next}]_v \land \text{Fairness}$$

* **Init:** State predicate defining all valid starting configurations.
* **Next:** Action formula defining all allowed state transitions ($s \rightarrow s'$).
* **$\Box[\text{Next}]_v$:** "Always" (Box operator $\Box$) either a valid `Next` state transition occurs or the variables $v$ remain unchanged (stuttering step).

```
TLA+ STATE TRANSITION MODEL:

   [ Init State ] ───Action A───► [ State 1 ] ───Action B───► [ State 2 ]
        │                              │                           │
        ▼                              ▼                           ▼
 Check Invariant P             Check Invariant P           Check Invariant P
 (If P is FALSE -> TLC Model Checker generates Error Counterexample Trace!)
```

#### Safety vs. Liveness Invariants

| Invariant Type | Mathematical Operator | Meaning | Example Violation |
| :--- | :--- | :--- | :--- |
| **Safety** | $\Box P$ ("Always P") | **"Nothing bad happens."** The system never enters an invalid state. | Two nodes elect themselves Leader for the same Term in Raft. |
| **Liveness** | $\Diamond P$ ("Eventually P") | **"Something good eventually happens."** The system makes forward progress. | A cluster deadlocks indefinitely during leader election. |

#### TLC Model Checker Execution

The **TLC Model Checker** exhaustively explores all possible state transitions:
1. It maintains a Queue of unexplored states and a Hash Table of seen states.
2. For every state, it evaluates all possible next actions, message delays, and re-orderings.
3. If an invariant evaluates to `FALSE`, TLC outputs a step-by-step **Counterexample Trace** showing the exact sequence of events leading to the failure.

---

### 2. Jepsen Fault Injection & Linearizability Checking

Created by Kyle Kingsbury (aphyr), **Jepsen** is a framework for black-box verification of distributed databases under network partitions and system failures.

```
JEPSEN TEST ARCHITECTURE:

 ┌────────────────────────────────────────────────────────────────────────┐
 │                              Control Node                              │
 │  ┌───────────────────────┐                 ┌────────────────────────┐  │
 │  │ Client Generator      │                 │ Nemesis Fault Injector │  │
 │  │ (Sends Concurrent     │                 │ (Injects Partitions,   │  │
 │  │  Reads / Writes)      │                 │  SIGSTOP, Clock Skew)  │  │
 │  └───────────┬───────────┘                 └───────────┬────────────┘  │
 └──────────────┼─────────────────────────────────────────┼───────────────┘
                │ Concurrent Operations                   │ Fault Injection
                ▼                                         ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Target Distributed Cluster (DB Node 1, DB Node 2, DB Node 3, DB Node 4)│
 └────────────────────────────────────────────────────────────────────────┘
                │
                ▼ History Log (Recorded Operations)
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Linearizability Checker (Knossos / Porcupine Algorithm)                │
 └────────────────────────────────────────────────────────────────────────┘
```

#### Nemesis Fault Injection Modes

* **Asymmetric Partition:** Node A can send packets to Node B, but Node B cannot send to Node A.
* **Process Pause (`SIGSTOP` / `SIGCONT`):** Pauses a database node process mid-transaction (simulates JVM Garbage Collection stop-the-world pauses).
* **Clock Skew Drift:** Uses `ntpdate` / `chrony` manipulation to jump system clocks forward or backward by seconds (testing NTP drift vulnerabilities in Cassandra/CockroachDB).

#### History Verification (Knossos / Porcupine)

After executing operations during Nemesis fault injection, Jepsen generates a linear execution history log:

```
CLIENT 1:  |--- Write X=1 ---|
CLIENT 2:          |--- Read X -> 0 (STALE!) ---|
CLIENT 3:                  |--- Write X=2 ---|
```

The history log is passed to a **Linearizability Checker** (Knossos/Porcupine), which builds a Directed Acyclic Graph (DAG) of valid sequential state paths. If no valid sequential ordering exists that satisfies linearizability rules, Jepsen reports a **Linearizability Anomaly**.

---

### Staff

### 3. Deterministic Simulation Testing (DST)

While Jepsen tests real running clusters, non-deterministic OS scheduling, network stack timing, and hardware threads make reproducing caught bugs extremely difficult.

**Deterministic Simulation Testing (DST)** solves this by executing the entire distributed system (all nodes, network, and disk) inside a **single-threaded, deterministic virtual time runtime**.

```
DETERMINISTIC SIMULATION RUNTIME (FoundationDB / TigerBeetle / Turmoil):

┌──────────────────────────────────────────────────────────────────────────┐
│ Virtual Deterministic Runtime (Single OS Thread)                         │
│                                                                          │
│ ┌──────────────────────┐  ┌──────────────────────┐ ┌───────────────────┐ │
│ │ Virtual Node 1       │  │ Virtual Node 2       │ │ Virtual Node 3    │ │
│ └──────────┬───────────┘  └──────────┬───────────┘ └─────────┬─────────┘ │
│            │                        │                       │            │
│ ───────────┴────────────────────────┼───────────────────────┴─────────── │
│                                     ▼                                    │
│  Simulated Network / Disk Subsystem & Pseudo-Random Number Generator     │
│  - Virtual Time Clock (Advances instantly to next event)                 │
│  - Seeded PRNG (Seed = 0x8F3A219)                                        │
│  - Injected Disk Bit Flips & Simulated Packet Re-ordering                │
└──────────────────────────────────────────────────────────────────────────┘
```

#### Core Components of a DST Engine

1. **Virtual Time Clock:** Instead of real-world `system_time()`, time is an integer counter driven by the simulation event loop. If all nodes are waiting on a 10-second timeout, virtual time advances **instantly** to $T+10s$.
2. **Seeded Pseudo-Random Number Generator (PRNG):** All non-deterministic decisions (packet loss, disk corruption, message order, node crashes) are derived from a single integer **Seed** (e.g., `seed = 42`).
3. **Simulated Network & Disk I/O:** Socket calls (`send`, `recv`) and disk calls (`read`, `write`, `fsync`) are intercepted. The simulator randomly drops, delays, or corrupts buffers based on the PRNG sequence.

$$\text{Simulation Execution} = f(\text{Codebase}, \text{Seed})$$

**The Determinism Guarantee:** If a bug occurs on Seed `1094821` after 4 hours of simulation representing 3 years of cluster runtime, running the simulation with Seed `1094821` will reproduce the **exact same failure sequence down to the exact nanosecond every single time.**

---

### Principal Stretch

### 4. Real-World DST Architecture Case Studies

#### FoundationDB (Flow / C++)
FoundationDB built a custom C++ transpiler (`Flow`) that adds async/await primitives compiling into a single-threaded state machine. The FoundationDB simulation engine runs thousands of virtual cluster tests per second, injecting network partitioning, disk corruption, and machine kills. FoundationDB ran equivalent to **thousands of years** of simulation testing before shipping to production.

#### TigerBeetle DB (VOPR / Zig)
TigerBeetle (a high-throughput financial accounting database) uses a built-in DST engine called the **VOPR (Viewstamped Operation Replication Simulator)**. The VOPR simulates storage fault injection (bit rots, torn writes, misdirected reads) and network partitions, testing TigerBeetle's protocol invariants against millions of state transitions per second.

```
TIGERBEETLE STORAGE FAULT INJECTION MATRICES:
- Bit Rot: Invert random byte in block -> Verified by SHA-256 checksums
- Torn Write: Write only first 512 bytes of 4KB block -> Detected by WAL tail checks
- Misdirected Write: Drive writes block to Sector 100 instead of Sector 200 -> Verified by Block Header Tags
```

## Decision Framework

```
DISTRIBUTED TESTING METHODOLOGY CHOOSER:

  Designing novel consensus / state machine?        → TLA+ Formal Specification & TLC Model Checker
  Testing running database cluster under fault?     → Jepsen Fault Injection (Nemesis + Knossos DAG)
  Building mission-critical state engine (DB/Ledger) → Deterministic Simulation Testing (DST / Turmoil / VOPR)
```

---

## 🛑 SOCRATIC CHECK — STOP AND THINK

**Question 1:** You write a TLA+ specification for a custom 3-node leader election protocol. TLC runs for 2 hours and reports no violations of your Safety invariant (`\A n1, n2 \in Nodes : IsLeader(n1) /\ IsLeader(n2) => n1 = n2`). However, when deployed, the system deadlocks permanently during node restarts. What type of invariant failed to be specified or checked?

**Question 2:** An engineering team implements Deterministic Simulation Testing (DST) for their Go microservice. During simulation runs, they notice that identical random seeds produce *different* failure execution traces on different developer laptops. What unhandled source of non-determinism leaked into their simulation engine?

> **Socratic check answer key:**
> See [`../answers/Week-03-Distributed-Systems-Theory/Formal-Verification-Answers.md`](../answers/Week-03-Distributed-Systems-Theory/Formal-Verification-Answers.md).

---

## Production Failure Patterns

```
PATTERN 1: READ-ONLY LEADER STALE READ IN AN ASYMMETRIC PARTITION
  Symptom:   Linearizability violation; clients read old state after a new leader has committed updates.
  Cause:     Old leader is partitioned from majority for writes, but can still respond to client reads without re-confirming leadership quorum.
  Fix:       Implement Read Index or Lease Read checks (Raft leader must confirm majority heartbeats before serving reads).

PATTERN 2: NON-DETERMINISTIC LEAK IN SIMULATION ENGINES
  Symptom:   DST bug caught on Seed X cannot be reproduced when re-running Seed X on another machine.
  Cause:     Code uses real-world system clock (`time.Now()`), global unseeded RNG (`rand.Float64()`), or OS thread concurrency (`goroutines`).
  Fix:       Enforce abstraction wrappers for Time, Randomness, and Scheduling across the entire codebase.

PATTERN 3: UNHANDLED TORN WRITE IN CONSENSUS WAL
  Symptom:   Database crashes on startup post-power outage with "Corrupted Journal State" and fails to recover.
  Cause:     Disk controller wrote partial sector during crash; recovery parser assumes binary all-or-nothing write integrity.
  Fix:       Add checksum fields to WAL record headers; truncate partial trailing records on recovery.
```

---

## SRE Diagnostic Toolkit

```bash
# Running TLC Model Checker on TLA+ Specification
java -cp tla2tools.jar tlc2.TLC -config Protocol.cfg Protocol.tla

# Running Jepsen Test Suite against a Target DB Cluster
lein run test --tarball http://cluster-pkg/db.tar.gz --workload append --nemesis partition

# Running TigerBeetle VOPR Deterministic Simulator
zig build vopr -- --seed=0xDEADBEEF --repl-count=3

# Inspecting Non-Deterministic System Calls in Go Binaries
go tool objdump -s "time\.Now" my_binary
```
