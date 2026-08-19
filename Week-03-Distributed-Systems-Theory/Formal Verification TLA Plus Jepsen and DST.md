# Formal Verification: TLA+, Jepsen & Deterministic Simulation Testing (DST)

## Learning Objectives

```
╔═════════════════════════════════════════════════════════════════════════════════════════════════╗
║ AFTER THIS TOPIC, YOU WILL BE ABLE TO:                                                          ║
╟─────────────────────────────────────────────────────────────────────────────────────────────────╢
║                                                                                                 ║
║ 1. Write TLA+ temporal logic specifications (Safety $\square P$ and Liveness $\diamond P$)      ║
║    to prove consensus state machine invariants.                                                 ║
║                                                                                                 ║
║ 2. Architecture Jepsen fault-injection test suites to verify linearizability and serializability║
║    under network partitions and split-brain scenarios.                                          ║
║                                                                                                 ║
║ 3. Design FoundationDB-style Deterministic Simulation Testing (DST) engines using virtual       ║
║    clocks, deterministic random seeds, and discrete-event simulation loops.                     ║
║                                                                                                 ║
║ 4. Diagnose subtle edge-case distributed race conditions that bypass traditional integration    ║
║    and chaos testing pipelines.                                                                 ║
║                                                                                                 ║
║ 5. Interpret TLC model checker state-space exploration logs and counterexample traces.          ║
╚═════════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═══════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "100% unit and integration test coverage guarantees correctness"             ║
╟───────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Unit tests test expected paths. Distributed consensus bugs (e.g., Raft split-brain)    ║
║ only trigger under exact interleavings of 5 concurrent RPC timeouts and network partitions.   ║
╠═══════════════════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #2: "Chaos Engineering in staging replaces formal verification"                  ║
╟───────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Chaos engineering tests real time. A bug that requires $10^{12}$ specific message      ║
║ orderings will never trigger in 24 hours of chaos testing, but will hit production in a month.║
╠═══════════════════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #3: "TLA+ is purely academic and too slow for real systems"                      ║
╟───────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. AWS, MongoDB, and FoundationDB use TLA+ to specify S3, DynamoDB, and Raft engines,     ║
║ catching critical data-loss bugs before writing a single line of production code.             ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

### 1. TLA+ Formal Specification Foundations

TLA+ (Temporal Logic of Actions) models distributed systems as mathematical state machines:

$$\text{Spec} \triangleq \text{Init} \land \square[\text{Next}]_{\text{vars}} \land \text{Liveness}$$

```tla
--------------------------- MODULE TwoPhaseCommit ---------------------------
EXTENDS Integers, Sequences

VARIABLES rmState, tmState, tmPrepared, msgs

RM == {"rm1", "rm2", "rm3"}

Init ==
    /\ rmState = [r \in RM |-> "working"]
    /\ tmState = "init"
    /\ tmPrepared = {}
    /\ msgs = {}

RMPrepare(r) ==
    /\ rmState[r] = "working"
    /\ rmState' = [rmState EXCEPT ![r] = "prepared"]
    /\ msgs' = msgs \cup {[type |-> "Prepared", rm |-> r]}
    /\ UNCHANGED <<tmState, tmPrepared>>

=============================================================================
```

---

### 2. Deterministic Simulation Testing (DST) Engine Architecture

DST (popularized by FoundationDB and TigerBeetle) runs an entire distributed cluster inside a single-threaded deterministic process:

```
DETERMINISTIC SIMULATION ENGINE (DST):

  ┌────────────────────────────────────────────────────────────┐
  │ Single-Threaded Simulator Process                          │
  │  ├── Virtual Clock (Discrete Event Queue)                  │
  │  ├── Pseudo-Random Generator (Fixed Seed = 0xDEADBEEF)     │
  │  ├── In-Memory Fault Injector (Drop/Delay Packets/Disks)   │
  │  └── Simulated Nodes A, B, C, D (Pure Deterministic Code)  │
  └────────────────────────────────────────────────────────────┘
```

---

### Staff

### 3. Real-Time Accurate Production Scenarios

#### Scenario 1: Silent Data Loss Bug in Distributed KV Store caught by DST
- **Incident:** Distributed KV engine passed all integration tests, but DST simulation with seed `0x89A12F` triggered key data corruption after 1,420,000 virtual simulated operations.
- **Root Cause:** Race condition between Raft snapshot compaction and background log truncation during leader stepping down.
- **Fix:** Fixed log entry index bounds before production release.

#### Scenario 2: Jepsen Finding Linearizability Violation in New Database Release
- **Incident:** Jepsen testing of a NoSQL database under partition injection revealed stale read values violating Read-Your-Writes consistency.
- **Root Cause:** Replica read paths failed to verify leader lease expiration prior to responding.
- **Fix:** Implemented Read-Index protocol requiring leader to verify quorum contact before responding to reads.

#### Scenario 3: TLA+ Model Checking Catching Lock Manager Deadlock
- **Incident:** TLA+ TLC model checker generated a 14-step counterexample trace showing distributed lock deadlock.
- **Fix:** Redesigned lock acquisition protocol to order lock keys strictly by hash value.

#

---

## Decision Framework

| Requirement / Scenario | Recommended Technology / Pattern | Key Trade-off / Bottleneck | Primary Telemetry Signal |
| :--- | :--- | :--- | :--- |
| Ultra-low latency microservice routing | eBPF Socket Layer Bypass (`sockmap`) | BPF map size bounds | Socket buffer drop count |
| Dynamic multi-cluster routing | Envoy xDS ADS Control Plane | xDS gRPC stream CPU overhead | CDS/EDS update latency |
| Pod network encapsulation | VXLAN / Geneve Overlay | 50-byte MTU header overhead | Interface packet drops |

---

## 🛑 SOCRATIC CHECK — STOP AND THINK

**Question 1:** Why does setting container interface MTU to 1500 bytes inside a VXLAN overlay network cause gRPC streaming calls to hang intermittently while short HTTP GET requests succeed?

**Question 2:** Why is iptables sequential packet evaluation ($O(N)$) fundamentally unsuited for large-scale Kubernetes clusters with 10,000+ services compared to Cilium eBPF socket maps?

> **Socratic check answer key:**
> See corresponding answer key in `answers/` directory.

---

## Production Failure Patterns

```
PATTERN 1: OVERLAY MTU MISMATCH FRAGMENTATION
  Symptom:   gRPC streaming calls hang or fail with connection timeouts; HTTP/1.1 calls succeed.
  Cause:     Container MTU set to 1500; VXLAN adds 50B header exceeding host 1500 MTU; IP fragments dropped with DF bit.
  Fix:       Set container interface MTU to 1450 bytes.

PATTERN 2: EBPF CONNTRACK MAP EXHAUSTION
  Symptom:   Kubernetes services reject incoming connections under load spikes.
  Cause:     High rate of short-lived TCP connections fills eBPF conntrack hash map.
  Fix:       Increase `bpf-ct-global-any-max` to 2,097,152 and tune TCP translation timeouts.
```

---

## SRE Diagnostic Toolkit

```bash
# 1. Trace kernel eBPF socket map lookup latency
bpftrace -e 'kprobe:bpf_sk_redirect_map { @[ustack] = count(); }'

# 2. Inspect Cilium eBPF conntrack map usage
cilium bpf ct list global

# 3. Check MTU configuration across pod interfaces
ip link show dev eth0
```


## Appendix B.1: Production Formal Verification Case Study 1

#### B.1.1 Verification & Simulation Setup
Formal verification guarantees distributed system invariants. Case study 1 details specification, model checking, and deterministic fault injection across distributed consensus engines.

```text
FORMAL VERIFICATION MATRIX B.1:
  - Verification Method: TLA+ / Jepsen / DST 1
  - Invariant Verified: Safety & Linearizability
  - Simulated Operations: 1000000 Events
  - Bugs Prevented Pre-Production: 2 Critical Race Conditions
```

#### B.1.2 Technical Remediation Workflow
1. Write TLA+ state machine specification defining Init state and Next transition actions.
2. Run TLC model checker to explore 100,000,000 distinct system state spaces.
3. Construct Jepsen Nemesis test suites injecting network partitions and clock drift.
4. Integrate Deterministic Simulation Testing (DST) into CI build pipelines.

#