# Week 4, Topic 3: Consensus (Raft)

---

## Learning Objectives
```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Explain WHY consensus exists — the exact problems it      ║
║      solves that replication and quorums alone cannot          ║
║                                                                ║
║   2. Trace the complete Raft algorithm: leader election, log   ║
║      replication, safety guarantees, and commitment rules      ║
║                                                                ║
║   3. Walk through Raft term numbers, election timeouts, and    ║
║      split-brain prevention at the message level               ║
║                                                                ║
║   4. Explain the safety guarantee that makes Raft correct:     ║
║      why a committed entry can NEVER be lost                   ║
║                                                                ║
║   5. Compare Raft to Paxos and understand why Raft was         ║
║      designed as "understandable Paxos"                        ║
║                                                                ║
║   6. Map Raft to real systems (etcd, CockroachDB, TiKV,        ║
║      Consul, MongoDB replica sets) with exact behavioral       ║
║      details                                                   ║
║                                                                ║
║   7. Diagnose consensus failures in production: election       ║
║      storms, split-brain, log divergence, and membership       ║
║      change hazards                                            ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═══════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Raft is only for etcd — we don't need it"             ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. Raft (or Paxos variants) underpins CockroachDB, TiKV,            ║
║   Consul, MongoDB elections, and Kubernetes control plane. Any            ║
║   system needing agreed leader election and replicated state              ║
║   uses consensus — often invisibly.                                       ║
╠═══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Having a leader means we have consensus"              ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. Manual leader assignment without election protocol =             ║
║   split-brain when network partitions occur. Consensus ensures            ║
║   exactly one leader per term with quorum-backed decisions.               ║
╠═══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Raft guarantees zero downtime during election"        ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. Leader election takes 150ms–2s (election timeout + vote          ║
║   round). During election, writes are rejected. Design for                ║
║   brief unavailability windows — don't assume seamless failover.          ║
╠═══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Paxos and Raft solve different problems"              ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. Both solve agreement on a sequence of values in the              ║
║   presence of failures. Raft is Paxos decomposed for                      ║
║   understandability — same safety guarantees, different                   ║
║   presentation.                                                           ║
╠═══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Split-brain can't happen with Raft"                   ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. Raft prevents split-brain only with proper quorum (majority      ║
║   of full membership) and fencing. Misconfigured even-numbered            ║
║   clusters, network partitions without fencing, and ignoring              ║
║   term numbers all cause dual-leader scenarios.                           ║
╠═══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Quorum = any N/2+1 nodes responding"                  ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. Quorum is majority of the CURRENT membership, which              ║
║   changes during joint-consensus membership changes. Adding/removing      ║
║   nodes without joint consensus can permanently lose quorum or            ║
║   violate safety — the #1 production Raft misconfiguration.               ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### 2.1 — Why Consensus? What Replication Can't Do

We've covered three replication topologies (Topic 1). Each has a fundamental gap:

```
╔════════════════════════════════════════════════════════════════╗
║   THE GAP IN REPLICATION                                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   LEADER-FOLLOWER (async):                                     ║
║   → Leader dies. Promote a follower. But WHICH follower?       ║
║   → Who DECIDES the new leader?                                ║
║   → What if two followers both think they're the new leader?   ║
║   → What if the old leader comes back and still thinks it's    ║
║     the leader? (SPLIT-BRAIN — Topic 1 failure mode 2)         ║
║                                                                ║
║   LEADERLESS (quorum):                                         ║
║   → R+W>N guarantees overlap. But NOT linearizability.         ║
║   → Concurrent writes to the same key: who wins?               ║
║   → Cassandra says "last writer wins" (LWW) — but clocks       ║
║     are unreliable. This is CONFLICT RESOLUTION, not           ║
║     CONFLICT PREVENTION.                                       ║
║                                                                ║
║   MULTI-LEADER:                                                ║
║   → Conflicts are INEVITABLE. You resolve them after the fact. ║
║   → You can never guarantee "exactly one leader decided X."    ║
║                                                                ║
║   THE MISSING PRIMITIVE:                                       ║
║   None of these topologies can make a group of nodes           ║
║   AGREE on a single value — reliably, in the presence of       ║
║   failures, without split-brain.                               ║
║                                                                ║
║   This is the CONSENSUS problem:                               ║
║   "Get N nodes to agree on a value such that:                  ║
║    1. All nodes that decide, decide the SAME value             ║
║    2. The value was proposed by SOME node (not fabricated)     ║
║    3. Every non-failed node eventually decides"                ║
║                                                                ║
║   Consensus is the foundation for:                             ║
║   → Leader election (who is the leader? — all agree)           ║
║   → Atomic broadcast (total order of operations — all agree)   ║
║   → Distributed locks (who holds the lock? — all agree)        ║
║   → Configuration management (what's the cluster state?)       ║
║   → Linearizable reads and writes                              ║
╚════════════════════════════════════════════════════════════════╝
```

**Where you've already seen consensus (connecting prior weeks):**

```
╔═════════════════════════════════════════════════════════════════╗
║   PRIOR REFERENCE            │  CONSENSUS CONNECTION            ║
╠═════════════════════════════════════════════════════════════════╣
║  Week 3 T1: etcd, ZooKeeper │ Both use consensus internally     ║
║  classified as PC/EC         │ (etcd=Raft, ZK=ZAB). That's      ║
║                              │ WHY they're PC/EC — they         ║
║                              │ sacrifice availability for       ║
║                              │ agreement.                       ║
╠═════════════════════════════════════════════════════════════════╣
║  Week 3 T2: linearizability  │ Consensus is HOW you implement   ║
║  "single global timeline"    │ linearizability across multiple  ║
║                              │ nodes. Raft's replicated log =   ║
║                              │ the global timeline.             ║
╠═════════════════════════════════════════════════════════════════╣
║  Week 4 T1: split-brain      │ Consensus PREVENTS split-brain   ║
║  "two nodes think they're    │ via term numbers and majority    ║
║  leader"                     │ voting. This is the formal fix   ║
║                              │ for the failover problem.        ║
╠═════════════════════════════════════════════════════════════════╣
║  Week 4 T1: fencing tokens   │ Raft's TERM NUMBER is a          ║
║  "epoch E+1 rejects writes   │ fencing token. A leader with     ║
║  from epoch E"               │ term 5 rejects messages from     ║
║                              │ a stale leader with term 4.      ║
╠═════════════════════════════════════════════════════════════════╣
║  Week 2: Cassandra QUORUM    │ Quorum is NECESSARY but not      ║
║  R+W>N                       │ SUFFICIENT for consensus.        ║
║                              │ Consensus adds: leader election, ║
║                              │ log ordering, commitment rules.  ║
║                              │ Quorum is just the voting math.  ║
╚═════════════════════════════════════════════════════════════════╝
```

---

### 2.2 — The FLP Impossibility Result (Why This Is Hard)

Before Raft, you need to understand why consensus is *fundamentally* difficult:

```
╔══════════════════════════════════════════════════════════════╗
║   FLP IMPOSSIBILITY (Fischer, Lynch, Paterson, 1985)         ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   In an ASYNCHRONOUS system (no bound on message delivery    ║
║   time), it is IMPOSSIBLE to guarantee consensus if even     ║
║   ONE node can fail.                                         ║
║                                                              ║
║   Why? Because you can't distinguish between:                ║
║   → A node that CRASHED (will never respond)                 ║
║   → A node that is SLOW (will respond eventually)            ║
║                                                              ║
║   If you wait forever for the slow node → you might wait     ║
║   forever (no liveness — violates "eventually decides").     ║
║   If you proceed without it → it might come back with a      ║
║   different decision (no safety — violates "all agree").     ║
║                                                              ║
║   HOW RAFT (and Paxos) GET AROUND FLP:                       ║
║   They use TIMEOUTS to assume a node is dead.                ║
║   This makes the system PARTIALLY SYNCHRONOUS —              ║
║   "I'll wait X milliseconds; if no response, I assume        ║
║   you're dead and proceed."                                  ║
║                                                              ║
║   This means: consensus algorithms can get STUCK             ║
║   (no progress) but they can NEVER be WRONG.                 ║
║   Safety is always guaranteed. Liveness is guaranteed        ║
║   only when the network is "well-behaved enough."            ║
║                                                              ║
║   In practice: Raft makes progress almost all the time.      ║
║   The pathological case (constant leader crashes during      ║
║   election) is theoretically possible but practically rare.  ║
╚══════════════════════════════════════════════════════════════╝
```

---

### 2.3 — Raft Overview: The Three Sub-Problems

Raft (Ongaro & Ousterhout, 2014) decomposes consensus into three independent sub-problems:

```
╔══════════════════════════════════════════════════════════════╗
║   RAFT = THREE SUB-PROBLEMS                                  ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. LEADER ELECTION                                         ║
║      → Choose exactly ONE leader from the cluster            ║
║      → All nodes agree on who the leader is                  ║
║      → If the leader fails, elect a new one                  ║
║                                                              ║
║   2. LOG REPLICATION                                         ║
║      → Leader accepts client requests                        ║
║      → Leader appends to its log                             ║
║      → Leader replicates log entries to followers            ║
║      → When a MAJORITY have the entry, it's "committed"      ║
║                                                              ║
║   3. SAFETY                                                  ║
║      → A committed entry is NEVER lost or overwritten        ║
║      → All nodes that apply an entry apply the SAME entry    ║
║        at the SAME log position                              ║
║      → This is the correctness guarantee                     ║
║                                                              ║
║   The key insight of Raft: the leader handles EVERYTHING.    ║
║   Clients talk to the leader. The leader orders operations.  ║
║   Followers just replicate what the leader tells them.       ║
║   This is MUCH simpler than Paxos (where any node can        ║
║   propose).                                                  ║
╚══════════════════════════════════════════════════════════════╝
```

**Raft node states:**

```
  Every node is in exactly ONE of three states:

╔═══════════════════════════════════════════════════════════════════════╗
║   FOLLOWER  │────timeout────▶│ CANDIDATE  │─────votes─────▶│   LEADER ║
║             │                │            │                │          ║
║  Passive.   │                │ Requesting │                │ Handles  ║
║  Responds   │◀───discovers───│ votes from │◀───discovers───│ ALL      ║
║  to leader  │   new leader   │ all nodes  │   higher term  │ client   ║
║  and        │                │            │                │ requests ║
║  candidates │◀───────────────│            │───╮ election   │          ║
║             │ loses election │            │◀──╯ timeout    │          ║
╚═══════════════════════════════════════════════════════════════════════╝

  STARTUP: All nodes begin as FOLLOWERS.
  No heartbeat from leader within election timeout →
  become CANDIDATE → start election.
```

---

### 2.4 — Raft Concept: Terms

Terms are Raft's logical clock — the equivalent of the "epoch" or "fencing token" from Topic 1:

```
╔═══════════════════════════════════════════════════════════════╗
║   TERMS                                                       ║
╟───────────────────────────────────────────────────────────────╢
║                                                               ║
║   Time is divided into TERMS of arbitrary length.             ║
║   Each term has at most ONE leader.                           ║
║                                                               ║
║   ╭──────╮ ╭──────────────────╮ ╭────╮ ╭────────────────────╮ ║
║   │Term 1│ │     Term 2       │ │T 3 │ │      Term 4        │ ║
║   │      │ │                  │ │    │ │                    │ ║
║   │elect.│ │ election │ normal│ │elec│ │ election │ normal  │ ║
║   │      │ │          │ oper. │ │tion│ │          │ oper.   │ ║
║   │leader│ │ leader B │ B     │ │no  │ │ leader D │ D       │ ║
║   │  A   │ │ elected  │ leads │ │win │ │ elected  │ leads   │ ║
╚═══════════════════════════════════════════════════════════════╝
│                                                               │
│  Term 3: election held but no candidate got majority.         │
│  This happens (split vote). Term ends, new term begins.       │
│                                                               │
│  RULES:                                                       │
│  → Every RPC message includes the sender's current term.      │
│  → If a node receives a message with a HIGHER term:           │
│    → It immediately updates its term to the higher one.       │
│    → If it was a leader or candidate, it STEPS DOWN           │
│      to follower.                                             │
│  → If a node receives a message with a LOWER term:            │
│    → It REJECTS the message.                                  │
│    → "You're from term 4? I'm in term 6. Ignored."            │
│                                                               │
│  THIS IS THE SPLIT-BRAIN PREVENTION MECHANISM.                │
│  An old leader that was network-partitioned comes back.       │
│  It sends messages with term 4. Everyone else is in term 6.   │
│  All messages rejected. Old leader sees term 6 in a           │
│  response, updates to term 6, steps down to follower.         │
│  Split-brain impossible.                                      │
│                                                               │
│  Compare to Topic 1 fencing tokens:                           │
│  → Term IS the fencing token.                                 │
│  → "Storage rejects writes with epoch ≤ E" =                  │
│    "Followers reject AppendEntries from a lower term."        │
╰───────────────────────────────────────────────────────────────╯
```

---

### 2.5 — Sub-Problem 1: Leader Election (Full Detail)

```
╔══════════════════════════════════════════════════════════════╗
║   LEADER ELECTION — STEP BY STEP                             ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   Cluster: 5 nodes (A, B, C, D, E). Term = 4. Leader = A.    ║
║   Node A crashes.                                            ║
║                                                              ║
║   STEP 1: ELECTION TIMEOUT                                   ║
║   ─────────────────────                                      ║
║   Each follower has a randomized election timeout            ║
║   (e.g., 150-300ms). Node C's timeout fires first.           ║
║                                                              ║
║   WHY RANDOMIZED: If all timeouts were the same,             ║
║   all nodes would become candidates simultaneously,          ║
║   split the vote, no one gets majority, repeat forever.      ║
║   Randomization makes it likely ONE node times out first.    ║
║                                                              ║
║   STEP 2: BECOME CANDIDATE                                   ║
║   ────────────────────────                                   ║
║   Node C:                                                    ║
║   → Increments its term: 4 → 5                               ║
║   → Transitions to CANDIDATE state                           ║
║   → Votes for ITSELF (1 vote so far)                         ║
║   → Sends RequestVote RPC to all other nodes (B, D, E)       ║
║                                                              ║
║   RequestVote RPC contains:                                  ║
║   {                                                          ║
║     term: 5,                                                 ║
║     candidateId: C,                                          ║
║     lastLogIndex: 47,    // C's last log entry index         ║
║     lastLogTerm: 4       // term of C's last log entry       ║
║   }                                                          ║
║                                                              ║
║   STEP 3: VOTING                                             ║
║   ──────────────                                             ║
║   Each node receives the RequestVote and decides:            ║
║                                                              ║
║   VOTE GRANTED if ALL of:                                    ║
║   ✓ Candidate's term ≥ voter's current term                  ║
║   ✓ Voter hasn't already voted in this term                  ║
║   ✓ Candidate's log is AT LEAST AS UP-TO-DATE as voter's     ║
║     (this is the ELECTION RESTRICTION — critical for safety) ║
║                                                              ║
║   "At least as up-to-date" means:                            ║
║   → Compare last log entry's TERM first (higher term wins)   ║
║   → If terms equal, compare log LENGTH (longer wins)         ║
║                                                              ║
║   Example:                                                   ║
║   Node B: lastLogIndex=47, lastLogTerm=4 → C is equally      ║
║           up-to-date → GRANTS vote                           ║
║   Node D: lastLogIndex=48, lastLogTerm=4 → D has MORE        ║
║           entries → DENIES vote (C's log is behind)          ║
║   Node E: lastLogIndex=45, lastLogTerm=4 → C has MORE        ║
║           entries → GRANTS vote                              ║
║                                                              ║
║   STEP 4: WIN OR LOSE                                        ║
║   ────────────────────                                       ║
║   C has: 1 (self) + B (granted) + E (granted) = 3 votes      ║
║   Majority of 5 = 3 → C WINS. C becomes leader of term 5.    ║
║                                                              ║
║   C immediately sends heartbeat AppendEntries to all nodes.  ║
║   All nodes update: "leader of term 5 = C."                  ║
║   Node D sees term 5 ≥ its term 4, accepts C as leader       ║
║   (even though D denied C's vote — D didn't get enough       ║
║   votes to win itself).                                      ║
║                                                              ║
║   Node A eventually recovers. It's still in term 4.          ║
║   It receives an AppendEntries from C with term 5.           ║
║   A updates to term 5, becomes follower. No split-brain.     ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

**The election visualized in time:**

```
  Time ──────────────────────────────────────────────────▶

  Node A: ████ LEADER (term 4) ████ CRASH ─────────── recovers → FOLLOWER (term 5)

  Node B: ──── follower ─── timeout ── receives RequestVote(C,5) ── grants ── follower(C)

  Node C: ──── follower ─── timeout ── CANDIDATE(5) ── wins ── LEADER (term 5) ████████
                             ▲ first!       │
                                            │──▶ RequestVote to B,D,E
                                            │◀── votes: B=yes, D=no, E=yes
                                            │    3/5 = majority ✓

  Node D: ──── follower ─── timeout ── receives RequestVote(C,5) ── denies ── follower(C)
                             (hasn't                                 (accepts heartbeat
                              fired yet)                              from C at term 5)

  Node E: ──── follower ─── timeout ── receives RequestVote(C,5) ── grants ── follower(C)
```

**What happens when elections fail (split vote):**

```
  5-node cluster. A crashes. B and D timeout simultaneously.

  B becomes candidate (term 5), votes for self.
  D becomes candidate (term 5), votes for self.

  C receives both RequestVotes. Votes for whichever arrives first (say B).
  E receives both RequestVotes. Votes for whichever arrives first (say D).

  B: 2 votes (self + C). Not majority.
  D: 2 votes (self + E). Not majority.

  Neither wins. Election timeout fires again.
  RANDOMIZED timeouts → one will fire first next time.

  New term 6. Process repeats. Eventually someone wins.

  In practice: split votes are rare (randomization works well).
  Typical election completes in one round, ~150-300ms.

  BUT: if timeouts are misconfigured (too tight, not enough
  randomization), you can get ELECTION STORMS — rapid
  repeated failed elections. The cluster has no leader,
  so no writes are processed. This is a liveness failure.
```

---

### 2.6 — Sub-Problem 2: Log Replication

Once a leader is elected, it handles all client requests by replicating log entries:

```
╔════════════════════════════════════════════════════════════════╗
║   LOG REPLICATION — THE CORE MECHANISM                         ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   Every node maintains a LOG — an ordered sequence of entries: ║
║                                                                ║
║   Log index:  1    2    3    4    5    6    7                  ║
║   ╭─────┬─────┬─────┬─────┬─────┬─────┬─────╮                  ║
║   │ t=1 │ t=1 │ t=1 │ t=2 │ t=3 │ t=3 │ t=3 │                  ║
║   │x←1  │y←2  │x←3  │y←7  │x←5  │y←1  │z←9  │                  ║
╚════════════════════════════════════════════════════════════════╝
│   Each entry has: [term, command]                             │
│                                                               │
│  The log is THE linearizable history.                         │
│  Entry at index 5 happens BEFORE entry at index 6.            │
│  All nodes that commit entry 5 commit the SAME command        │
│  at index 5. This is the "single global timeline" from        │
│  Week 3 Topic 2.                                              │
╰───────────────────────────────────────────────────────────────╯
```

**The replication protocol step by step:**

```
  Client sends: SET x = 42

  STEP 1: Leader appends to its own log

  Leader (C):
  Log: [..., index=7 term=5 cmd="SET x=42"]
                                    ▲ new entry

  STEP 2: Leader sends AppendEntries RPC to all followers

  AppendEntries RPC:
  {
    term: 5,                    // leader's current term
    leaderId: C,
    prevLogIndex: 6,            // index of entry BEFORE new one
    prevLogTerm: 3,             // term of entry at index 6
    entries: [{term:5, cmd:"SET x=42"}],  // new entries
    leaderCommit: 6             // leader's current commit index
  }

  STEP 3: Follower receives AppendEntries

  Follower checks:
  ✓ term ≥ my current term? (yes → accept)
  ✓ Do I have an entry at prevLogIndex=6 with prevLogTerm=3?
    → YES: my log is consistent with leader's up to index 6.
           Append the new entry at index 7. Reply success.
    → NO:  my log DIVERGES from leader's. Reply failure.
           Leader will back up and retry with earlier entries
           until it finds the point where logs agree.

  STEP 4: Leader counts acknowledgments

  5-node cluster. Leader + 4 followers.
  Leader has the entry (counts as 1).
  Needs 2 more followers to ACK → total 3 = majority.

  B: ACK ✓  (2 so far: C + B)
  E: ACK ✓  (3 so far: C + B + E) → MAJORITY!
  D: ACK ✓  (4 — extra, doesn't change anything)
  A: still down

  STEP 5: Leader COMMITS

  Leader advances its commitIndex to 7.
  Entry at index 7 is now COMMITTED.
  Leader applies "SET x = 42" to its state machine.
  Leader responds to client: "OK, x = 42."

  STEP 6: Followers learn about commit

  The NEXT AppendEntries (or heartbeat) from the leader
  includes leaderCommit = 7. Followers see this, advance
  their own commitIndex, and apply the entry to their
  own state machines.

  Note: followers learn about commits AFTER the leader.
  This is why reading from a follower may return stale data.
  This is exactly the replication lag from Topic 1 —
  but now with a FORMAL guarantee: committed entries
  will NEVER be rolled back.
```

**The log replication visualized:**

```
  5-node cluster, leader = C, term = 5

  Client ──── "SET x=42" ────▶ Leader C
                                │
              ╭─────────────────┼─────────────────╮
              ▼                 ▼                  ▼
           Node B            Node D             Node E

  Leader C's log:  [1:t1][2:t1][3:t2][4:t3][5:t3][6:t3][7:t5←NEW]
  Node B's log:    [1:t1][2:t1][3:t2][4:t3][5:t3][6:t3][7:t5←NEW] ✓ ACK
  Node D's log:    [1:t1][2:t1][3:t2][4:t3][5:t3][6:t3][7:t5←NEW] ✓ ACK
  Node E's log:    [1:t1][2:t1][3:t2][4:t3][5:t3][6:t3][7:t5←NEW] ✓ ACK
  Node A:          [crashed — log frozen at index 6]

  Commit index: 7 (C + B + D + E = 4 nodes have it, majority = 3 ✓)

  When A recovers, leader C sends it the missing entry at index 7.
  A appends it, catches up. No data loss, no inconsistency.
```

---

### 2.7 — Sub-Problem 3: Safety (The Election Restriction)

This is the most subtle and most important part of Raft. It's what prevents committed entries from ever being lost.

```
╔═══════════════════════════════════════════════════════════════╗
║   THE SAFETY GUARANTEE                                        ║
╟───────────────────────────────────────────────────────────────╢
║                                                               ║
║   "If a log entry is committed at a given index in a given    ║
║    term, no other entry will ever be committed at that index  ║
║    in any future term."                                       ║
║                                                               ║
║   In plain English: once committed, NEVER rolled back.        ║
║                                                               ║
║   HOW THIS IS ENFORCED:                                       ║
║                                                               ║
║   THE ELECTION RESTRICTION:                                   ║
║   A candidate can only win an election if its log is at       ║
║   least as up-to-date as the logs of a MAJORITY of nodes.     ║
║                                                               ║
║   Why this works:                                             ║
║   → An entry is committed when a MAJORITY has it.             ║
║   → A candidate needs votes from a MAJORITY.                  ║
║   → Any two majorities OVERLAP in at least one node.          ║
║   → That overlapping node has the committed entry.            ║
║   → That node will NOT vote for a candidate whose log         ║
║     is BEHIND (doesn't have the committed entry).             ║
║   → Therefore: no candidate without the committed entry       ║
║     can win.                                                  ║
║   → Therefore: the new leader ALWAYS has all committed        ║
║     entries.                                                  ║
║   → Therefore: committed entries are never lost.              ║
║                                                               ║
║   THIS IS THE KEY INSIGHT OF RAFT.                            ║
║                                                               ║
║   ╭─────────────────────────────────────────────────────────╮ ║
║   │  5 nodes: A B C D E                                     │ ║
║   │  Entry X committed: on A, B, C (majority = 3)           │ ║
║   │                                                         │ ║
║   │  Leader A crashes. Election.                            │ ║
║   │  Any candidate needs 3 votes (majority of 5).           │ ║
║   │  Remaining voters: B, C, D, E (4 nodes)                 │ ║
║   │                                                         │ ║
║   │  Can D win? D needs 3 votes: self + 2 others.           │ ║
║   │  D asks B: B has entry X. D doesn't. B DENIES vote.     │ ║
║   │  D asks C: C has entry X. D doesn't. C DENIES vote.     │ ║
║   │  D asks E: E doesn't have entry X. E GRANTS vote.       │ ║
║   │  D has: self + E = 2 votes. NOT majority. D LOSES.      │ ║
║   │                                                         │ ║
║   │  Can B win? B has entry X. B asks C, D, E.              │ ║
║   │  C: B's log ≥ C's → GRANTS.                             │ ║
║   │  D: B's log ≥ D's → GRANTS.                             │ ║
║   │  E: B's log ≥ E's → GRANTS.                             │ ║
║   │  B has: self + C + D + E = 4. MAJORITY. B WINS.         │ ║
║   │                                                         │ ║
║   │  B becomes leader. B HAS entry X. Entry X is safe.      │ ║
╚═══════════════════════════════════════════════════════════════╝
│                                                               │
│  The math is beautiful:                                       │
│  {nodes with committed entry} ∩ {nodes that vote for winner}  │
│  must be non-empty (two majorities always overlap).           │
│  The overlapping node enforces the election restriction.      │
╰───────────────────────────────────────────────────────────────╯
```

**Uncommitted entries CAN be lost:**

```
  IMPORTANT DISTINCTION:

  COMMITTED (majority has it):    NEVER lost. Guaranteed.
  UNCOMMITTED (only leader has it): CAN be lost.

  Scenario:
  → Leader C appends entry at index 8 to its own log.
  → Before replicating to anyone: C crashes.
  → New leader elected (doesn't have index 8).
  → Entry at index 8 is PERMANENTLY LOST.
  → Client never received "OK" (leader crashed before responding).
  → Client retries. New leader processes the retry.
  → No inconsistency — client didn't think it succeeded.

  THIS IS WHY the client only considers a write successful
  after the leader responds "committed." If the leader
  crashes before responding, the client doesn't know whether
  it committed or not → must retry (idempotent writes needed).

  THIS IS ALSO the async replication durability gap from
  Topic 1 — but now formalized. In Raft, "committed" means
  "majority durable." In async replication, "committed"
  means "leader wrote it locally" — which is weaker.
```

---

### 2.8 — Log Divergence and Repair

When leaders change, followers may have log entries that disagree with the new leader. Raft resolves this:

```
  After several leader changes, logs can look like this:

  Log index: 1  2  3  4  5  6  7  8  9  10 11 12

  Leader S1 │1 │1 │1 │4 │4 │5 │5 │6 │6 │6 │        (current leader, term 8)
  (term 8)  ╰──┴──┴──┴──┴──┴──┴──┴──┴──┴──╯

  Follower  │1 │1 │1 │4 │4 │5 │5 │6 │6 │              (missing 10)
  S2        ╰──┴──┴──┴──┴──┴──┴──┴──┴──╯

  Follower  │1 │1 │1 │4 │                              (way behind)
  S3        ╰──┴──┴──┴──╯

  Follower  │1 │1 │1 │4 │4 │5 │5 │6 │6 │6 │6 │        (has EXTRA entry)
  S4        ╰──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──╯

  Follower  │1 │1 │1 │2 │2 │2 │3 │3 │3 │3 │3 │        (diverged at index 4!)
  S5        ╰──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──╯

  S4 has an extra entry at index 11 (from a previous leader that
  didn't commit it). S5 has completely different entries from index
  4 onward (from an even older leader).

  HOW RAFT REPAIRS THIS:

  Leader S1 sends AppendEntries to S5:
  → prevLogIndex=10, prevLogTerm=6
  → S5 doesn't have an entry at index 10 with term 6. REJECT.

  Leader backs up: prevLogIndex=9, prevLogTerm=6
  → S5 doesn't have matching entry at 9. REJECT.

  ...backs up to prevLogIndex=3, prevLogTerm=1
  → S5 has entry at index 3 with term 1. MATCH!

  Leader sends entries 4-10 to S5.
  S5 OVERWRITES its entries 4-11 with the leader's entries 4-10.
  S5's old entries (the ones from terms 2 and 3) are DELETED.

  This is safe because those entries were NEVER COMMITTED.
  (If they had been committed, S1 would have them too —
  election restriction guarantees this.)

  AFTER REPAIR, all followers match the leader's log.
```

---

### 2.9 — Linearizable Reads in Raft

Raft's log provides a total order for writes. But what about reads?

```
╔════════════════════════════════════════════════════════════════╗
║   THE STALE READ PROBLEM                                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   Scenario:                                                    ║
║   → Leader C processes "SET x = 42" (committed, index 7).      ║
║   → Network partition: C is cut off from B, D, E.              ║
║   → B, D, E elect new leader D (term 6). C doesn't know yet.   ║
║   → D processes "SET x = 99" (committed on B, D, E, index 8).  ║
║   → Client reads x from C. C is still the "old leader."        ║
║   → C returns x = 42. But x is actually 99.                    ║
║   → STALE READ. Violates linearizability.                      ║
║                                                                ║
║   THE PROBLEM: A leader might not know it's been deposed.      ║
║   It can serve stale reads from its local state.               ║
║                                                                ║
║   THREE SOLUTIONS:                                             ║
║                                                                ║
║   1. LEADER LEASE (time-based)                                 ║
║      → Leader holds a "lease" for T seconds.                   ║
║      → Followers promise not to start an election for T secs   ║
║        after last heartbeat.                                   ║
║      → Leader can serve reads within the lease window          ║
║        without checking followers.                             ║
║      → REQUIRES: bounded clock skew. If clocks drift,          ║
║        two nodes might both think they have the lease.         ║
║      → etcd uses this approach.                                ║
║                                                                ║
║   2. READINDEX (majority check on every read)                  ║
║      → Before serving a read, leader sends a heartbeat         ║
║        to all followers.                                       ║
║      → If majority respond: leader confirms it's still leader. ║
║      → Then serves the read.                                   ║
║      → Safe but adds latency to every read (one RTT).          ║
║      → etcd supports this via ReadIndex API.                   ║
║                                                                ║
║   3. LOG READ (treat reads as writes)                          ║
║      → Append a no-op entry to the log for the read.           ║
║      → When it's committed (majority), serve the read.         ║
║      → Guarantees linearizability but very expensive.          ║
║      → Every read has the cost of a write.                     ║
║                                                                ║
║   PRODUCTION PATTERN:                                          ║
║   → Writes: always go through log (committed by majority)      ║
║   → Reads requiring linearizability: use ReadIndex or lease    ║
║   → Reads tolerating staleness: read from any follower         ║
║     (this is the read-from-replica pattern from Topic 1)       ║
║                                                                ║
║   This maps to the per-feature consistency decision from       ║
║   Week 3: balance-for-trade reads from leader (linearizable),  ║
║   balance-for-display reads from follower (eventually          ║
║   consistent).                                                 ║
╚════════════════════════════════════════════════════════════════╝
```

---

### 2.10 — Membership Changes (Adding/Removing Nodes)

The most operationally dangerous part of consensus:

```
╔═════════════════════════════════════════════════════════════════╗
║   THE JOINT CONSENSUS PROBLEM                                   ║
╟─────────────────────────────────────────────────────────────────╢
║                                                                 ║
║   Scenario: cluster is {A, B, C}. Add node D.                   ║
║   New config: {A, B, C, D}.                                     ║
║                                                                 ║
║   If some nodes switch to new config before others:             ║
║                                                                 ║
║   Old config {A, B, C}: majority = 2                            ║
║   New config {A, B, C, D}: majority = 3                         ║
║                                                                 ║
║   Time T1: A and B have switched to new config.                 ║
║            C and D still use old config.                        ║
║                                                                 ║
║   A + B think majority of NEW config = 3. They need one more.   ║
║   C thinks majority of OLD config = 2. C + one other = done.    ║
║                                                                 ║
║   C and D could elect a leader under old config (2/3 majority)  ║
║   A and B and D could elect a different leader under new config ║
║   (3/4 majority)                                                ║
║                                                                 ║
║   TWO LEADERS. SPLIT-BRAIN.                                     ║
║                                                                 ║
║   RAFT'S SOLUTION: SINGLE-NODE MEMBERSHIP CHANGES               ║
║   (simplified from original joint consensus approach)           ║
║                                                                 ║
║   Only add or remove ONE node at a time.                        ║
║   With single-node changes, old and new majorities              ║
║   ALWAYS overlap:                                               ║
║                                                                 ║
║   {A, B, C} → {A, B, C, D}                                      ║
║   Old majority: 2 of 3                                          ║
║   New majority: 3 of 4                                          ║
║   Any group of 2 from old AND any group of 3 from new           ║
║   MUST share at least one node (pigeonhole principle).          ║
║   Therefore: two leaders impossible.                            ║
║                                                                 ║
║   To go from 3 nodes to 5:                                      ║
║   {A,B,C} → {A,B,C,D} → {A,B,C,D,E}                             ║
║   Two membership changes, each committed through the log.       ║
║   Never two changes pending simultaneously.                     ║
║                                                                 ║
║   PRODUCTION REALITY:                                           ║
║   etcd: etcdctl member add / member remove (one at a time)      ║
║   Consul: autopilot manages membership automatically            ║
║   CockroachDB: nodes join via gossip, Raft groups adjust        ║
║                                                                 ║
║   THE DANGER: Adding/removing nodes during instability.         ║
║   If a node is added while the cluster is already struggling    ║
║   with elections, the membership change can make the election   ║
║   math worse. RULE: only change membership on a STABLE          ║
║   cluster with a healthy leader.                                ║
╚═════════════════════════════════════════════════════════════════╝
```

---

### 2.11 — Raft vs Paxos

```
╔═════════════════════════════════════════════════════════════════════╗
║  Notoriously difficult to understand and implement.                 ║
╟─────────────────────────────────────────────────────────────────────╢
║                                                                     ║
║  Key differences from Raft:                                         ║
║                                                                     ║
║  ╭───────────────────┬────────────────────┬───────────────────────╮ ║
║  │                   │ RAFT               │ PAXOS                 │ ║
║  ├───────────────────┼────────────────────┼───────────────────────┤ ║
║  │ Leader            │ Strong leader.     │ Any node can          │ ║
║  │                   │ ALL ops go         │ propose. No fixed     │ ║
║  │                   │ through leader.    │ leader required.      │ ║
║  ├───────────────────┼────────────────────┼───────────────────────┤ ║
║  │ Log               │ Entries committed  │ Single values         │ ║
║  │                   │ in order. No       │ agreed per slot.      │ ║
║  │                   │ gaps allowed.      │ Gaps possible.        │ ║
║  ├───────────────────┼────────────────────┼───────────────────────┤ ║
║  │ Understandability │ Designed to be     │ "Paxos Made Simple"   │ ║
║  │                   │ understandable.    │ is still 14 pages     │ ║
║  │                   │ User study         │ of dense proof.       │ ║
║  │                   │ proved this.       │                       │ ║
║  ├───────────────────┼────────────────────┼───────────────────────┤ ║
║  │ Implementation    │ Specification      │ Huge gap between      │ ║
║  │                   │ maps closely to    │ spec and working      │ ║
║  │                   │ implementation.    │ implementation.       │ ║
║  ├───────────────────┼────────────────────┼───────────────────────┤ ║
║  │ Phases per op     │ 1 phase (leader    │ 2 phases (prepare     │ ║
║  │                   │ append + commit)   │ + accept) per         │ ║
║  │                   │ in steady state    │ proposal              │ ║
║  ├───────────────────┼────────────────────┼───────────────────────┤ ║
║  │ Used by           │ etcd, TiKV,        │ Chubby (Google),      │ ║
║  │                   │ CockroachDB,       │ Spanner (Multi-       │ ║
║  │                   │ Consul, RethinkDB  │ Paxos), Cassandra     │ ║
║  │                   │                    │ LWT                   │ ║
╚═════════════════════════════════════════════════════════════════════╝
│                                                                    │
│ Multi-Paxos: optimization of Paxos that elects a stable            │
│ leader and amortizes the prepare phase. In steady state,           │
│ Multi-Paxos behaves very similarly to Raft.                        │
│                                                                    │
│ For interviews: "Raft and Multi-Paxos are equivalent in            │
│ power and similar in steady-state performance. Raft is             │
│ easier to understand and implement. Most modern systems            │
│ choose Raft."                                                      │
│                                                                    │
│ ZooKeeper's ZAB (ZooKeeper Atomic Broadcast) is a third            │
│ variant: similar to Raft (strong leader, ordered log) but          │
│ predates Raft and has slightly different recovery mechanics.       │
╰────────────────────────────────────────────────────────────────────╯
```

---

### 2.12 — Raft in Real Systems

```
╭──────────────────┬───────────────────────────────────────────────────────╮
│ TiKV (TiDB)      │ Same Multi-Raft approach as CockroachDB.              │
│                  │ Each Region (~96MB) is a Raft group.                  │
│                  │ PD (Placement Driver) manages Raft groups.            │
│                  │                                                       │
│ Consul           │ Raft for service catalog and KV store.                │
│                  │ 3 or 5 server nodes.                                  │
│                  │ consul operator raft list-peers.                      │
│                  │                                                       │
│ MongoDB          │ Replica sets use a Raft-LIKE protocol.                │
│ (replica sets)   │ Not pure Raft: uses an election priority              │
│                  │ system, pull-based replication (oplog tailing),       │
│                  │ and allows reads from secondaries.                    │
│                  │ rs.status(): shows election state per member.         │
│                  │                                                       │
│ Kafka (KRaft)    │ Kafka 3.3+: replaced ZooKeeper with Raft              │
│                  │ for metadata management (KRaft mode).                 │
│                  │ Controller quorum uses Raft for topic/                │
│                  │ partition metadata consensus.                         │
│                  │ NOT used for message replication (that uses           │
│                  │ ISR-based replication, different mechanism).          │
├──────────────────┴───────────────────────────────────────────────────────┤
│                                                                          │
│                         KEY PATTERN: MULTI-RAFT                          │
│                                                                          │
│  ╔══════════════════════════════════════════════════════════════════════════╗
│  ║   │                                                                    │ ║
│  ║   │       Node 1               Node 2               Node 3             │ ║
│  ║   │   ╭────────────╮       ╭────────────╮       ╭────────────╮         │ ║
│  ║   │   │ Range A    │       │ Range A    │       │ Range A    │  Raft   │ ║
│  ║   │   │ (LEADER)   │       │ (follower) │       │ (follower) │ group A │ ║
│  ║   │   ├────────────┤       ├────────────┤       ├────────────┤         │ ║
│  ║   │   │ Range B    │       │ Range B    │       │ Range B    │  Raft   │ ║
│  ║   │   │ (follower) │       │ (LEADER)   │       │ (follower) │ group B │ ║
│  ║   │   ├────────────┤       ├────────────┤       ├────────────┤         │ ║
│  ║   │   │ Range C    │       │ Range C    │       │ Range C    │  Raft   │ ║
│  ║   │   │ (follower) │       │ (follower) │       │ (LEADER)   │ group C │ ║
│  ╚══════════════════════════════════════════════════════════════════════════╝
│  │                                                                    │  │
│  │   Each range is an INDEPENDENT Raft group.                         │  │
│  │   Leadership is distributed across nodes.                          │  │
│  │   Node 1 is leader for Range A, follower for B and C.              │  │
│  │   Node 2 is leader for Range B, follower for A and C.              │  │
│  │   This DISTRIBUTES write load across nodes!                        │  │
│  │                                                                    │  │
│  │   This solves the "replication doesn't scale writes"               │  │
│  │   problem from Topic 1 — combined with Topic 2's                   │  │
│  │   partitioning, each partition gets its own Raft group,            │  │
│  │   and different partitions have different leaders.                 │  │
│  │                                                                    │  │
│  ╰────────────────────────────────────────────────────────────────────╯  │
│                                                                          │
╰──────────────────────────────────────────────────────────────────────────╯
```

---

## Production Patterns

```
╔═══════════════════════════════════════════════════════════════╗
║   FAILURE MODE 1: ELECTION STORMS                             ║
║                                                               ║
║   Cause: Election timeout too short relative to network       ║
║   latency. Every time a leader sends a heartbeat, it arrives  ║
║   AFTER the follower's election timeout. Follower starts      ║
║   election. Leader sends another heartbeat. Too late. Another ║
║   election. Repeat.                                           ║
║                                                               ║
║   Symptoms:                                                   ║
║   → etcd logs: "elected leader" / "lost leader" cycling       ║
║   → Kubernetes: API server intermittently unavailable         ║
║   → High CPU on etcd nodes from constant election RPCs        ║
║   → raft.leader.changes metric spiking                        ║
║                                                               ║
║   Fix: Increase election timeout.                             ║
║   etcd: --election-timeout=5000 (5 seconds, default=1000)     ║
║   Rule of thumb: election_timeout > 10× network RTT           ║
║   heartbeat_interval = election_timeout / 10                  ║
║                                                               ║
║   etcd defaults: heartbeat=100ms, election=1000ms             ║
║   Cross-region: heartbeat=500ms, election=5000ms              ║
║                                                               ║
╠═══════════════════════════════════════════════════════════════╣
║   FAILURE MODE 2: DISK LATENCY CAUSING LEADER LOSS            ║
║                                                               ║
║   Raft leaders must fsync WAL entries to disk before sending  ║
║   AppendEntries. If disk is slow (noisy neighbor in cloud,    ║
║   SSD garbage collection, EBS burst credits exhausted):       ║
║   → Leader's fsync takes 200ms                                ║
║   → Heartbeat interval is 100ms                               ║
║   → Leader misses heartbeat while fsyncing                    ║
║   → Followers start election                                  ║
║   → Leader steps down, new leader elected                     ║
║   → Old leader recovers, tries to sync, disk is still slow    ║
║   → If new leader is on SAME slow disk: election storm        ║
║                                                               ║
║   Fix: Dedicated SSD for Raft WAL. Monitor disk latency.      ║
║   etcd: dedicated disk via --wal-dir=/ssd/etcd/wal            ║
║   AWS: use io2 EBS volumes for etcd, not gp3                  ║
║   Alert: etcd_disk_wal_fsync_duration_seconds p99 > 10ms      ║
║                                                               ║
╠═══════════════════════════════════════════════════════════════╣
║   FAILURE MODE 3: LARGE RAFT SNAPSHOT TRANSFERS               ║
║                                                               ║
║   When a follower falls too far behind (log entries already   ║
║   compacted on leader), leader must send a SNAPSHOT:          ║
║   → Full state machine snapshot, not individual log entries   ║
║   → For etcd with 8GB data: 8GB transfer                      ║
║   → During transfer: network bandwidth consumed, leader       ║
║     performance degraded, follower rebuilding                 ║
║   → If transfer takes too long: election timeout fires,       ║
║     another election during snapshot transfer                 ║
║                                                               ║
║   Fix: Monitor log compaction vs follower position.           ║
║   etcd: --snapshot-count=10000 (compact after 10K entries)    ║
║   Increase if followers frequently need snapshots.            ║
║   etcd_debugging_snap_save_total_duration_seconds monitors.   ║
║                                                               ║
╠═══════════════════════════════════════════════════════════════╣
║   FAILURE MODE 4: LEARNER / NON-VOTING MEMBER MISHAPS         ║
║                                                               ║
║   Adding a new node to a 3-node cluster:                      ║
║   → New node needs full data sync (snapshot transfer)         ║
║   → During sync: if it's a voting member, it can't vote       ║
║     (it doesn't have the log yet)                             ║
║   → 3-node cluster + 1 new = 4 nodes, majority = 3            ║
║   → New node can't vote → only 3 effective voters             ║
║   → If 1 existing node fails → only 2 voters < majority       ║
║   → CLUSTER LOSES QUORUM during node addition!                ║
║                                                               ║
║   Fix: Add new node as LEARNER (non-voting) first.            ║
║   etcd: etcdctl member add <name> --learner                   ║
║   Learner receives log entries but doesn't vote.              ║
║   Once caught up: promote to voting member.                   ║
║   etcdctl member promote <member-id>                          ║
║                                                               ║
║   This ensures the voting set never includes a node that      ║
║   can't actually participate.                                 ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## SRE Diagnostic Toolkit

```
METRICS:
  etcd_server_has_leader, etcd_disk_wal_fsync_duration_seconds
  raft_term, proposal_failed_total

COMMANDS:
  etcdctl endpoint status -w table
  etcdctl member list
  etcdctl check perf

INCIDENT SIGNATURES:
  Frequent leader elections + disk latency → fsync/storage bottleneck
  proposal failures + quorum loss         → partition or slow follower
```

---

## Decision Framework

```
WHEN CONSENSUS (RAFT/PAXOS) IS THE RIGHT TOOL

  USE IT FOR (small, strongly-consistent, low-write-rate state):
    - cluster membership / leader election
    - configuration and feature-flag source of truth (etcd, Consul)
    - distributed locks / leases / fencing tokens
    - service discovery registries
    - metadata for a larger system (shard maps, schema versions)

  DO NOT USE IT FOR (high-throughput data plane):
    - user data at web scale             -> leaderless quorum (Dynamo/Cassandra)
    - event streams                      -> Kafka (ISR replication, not Raft per msg)
    - anything writing >~10k ops/s to the SAME group -> the leader is a bottleneck;
      every write is a full round-trip to a quorum + fsync.

CLUSTER SIZING

  ┌────────┬───────────────────┬─────────────────────────────────────────────┐
  │ Nodes  │ Tolerates failures│ Notes                                       │
  ├────────┼───────────────────┼─────────────────────────────────────────────┤
  │ 3      │ 1                 │ spread across 3 AZs; common default         │
  │ 5      │ 2                 │ survives 1 AZ + 1 node; more quorum latency │
  │ 7      │ 3                 │ rarely worth it; write latency grows        │
  │ even   │ — (avoid)         │ no availability gain, worse quorum          │
  └────────┴───────────────────┴─────────────────────────────────────────────┘
  Quorum = floor(N/2)+1. Bigger clusters = more durable but SLOWER writes
  (must wait for a majority to fsync).

OPERATIONAL RULES (where clusters actually die)
  - Disk fsync latency IS your write latency. Put the Raft log on fast, local
    NVMe; a slow EBS volume causes election storms and proposal timeouts.
  - Never rolling-restart all followers at once, and never let clients hammer
    the leader on boot -> thundering herd + repeated elections (see incident).
  - Keep the keyspace SMALL. etcd is metadata, not a database; watch DB size
    and compact/defrag on schedule.
  - Set client backoff + jitter on watches and leases so a leader change does
    not trigger a reconnect stampede.

ALTERNATIVES
  Need HA config but not linearizability? A replicated cache + versioned S3
  object may be simpler than running Raft. Consensus is powerful and expensive
  — reach for it only when you truly need agreement, not just replication.
```

---

## Hands-On Exercises
```
╭───────────────────────────────────────────────────────────────╮
│  EXERCISE: Observe Raft in Action with etcd                   │
│                                                               │
│  # Start a 3-node etcd cluster locally:                       │
│                                                               │
│  # Terminal 1:                                                │
│  etcd --name node1 \                                          │
│    --initial-advertise-peer-urls http://localhost:2380 \      │
│    --listen-peer-urls http://localhost:2380 \                 │
│    --listen-client-urls http://localhost:2379 \               │
│    --advertise-client-urls http://localhost:2379 \            │
│    --initial-cluster \                                        │
│      node1=http://localhost:2380,\                            │
│      node2=http://localhost:2480,\                            │
│      node3=http://localhost:2580                              │
│                                                               │
│  # Terminal 2 & 3: similar for node2 (ports 2480/2479)        │
│  # and node3 (ports 2580/2579)                                │
│                                                               │
│  # Check cluster health:                                      │
│  etcdctl --endpoints=localhost:2379,localhost:2479,localhost:2579 \
│    endpoint status --write-out=table                          │
│  # Shows: which node is leader, raft term, raft index         │
│                                                               │
│  # Write a key:                                               │
│  etcdctl --endpoints=localhost:2379 put mykey "hello"         │
│                                                               │
│  # Read from leader:                                          │
│  etcdctl --endpoints=localhost:2379 get mykey                 │
│                                                               │
│  # Read from a follower (serializable = may be stale):        │
│  etcdctl --endpoints=localhost:2479 get mykey \               │
│    --consistency=s                                            │
│                                                               │
│  # Now KILL the leader (Ctrl+C on its terminal)               │
│                                                               │
│  # Watch election happen:                                     │
│  etcdctl --endpoints=localhost:2479,localhost:2579 \          │
│    endpoint status --write-out=table                          │
│  # New leader elected! Note the new raft term (incremented).  │
│                                                               │
│  # Write to new leader:                                       │
│  etcdctl --endpoints=localhost:2479 put mykey "world"         │
│                                                               │
│  # Bring old leader back:                                     │
│  # Restart it. Watch it rejoin as follower.                   │
│  # Check: old leader now has "world" (it synced up).          │
│                                                               │
│  # Monitor Raft metrics:                                      │
│  curl -s http://localhost:2379/metrics | grep raft            │
│  # Key metrics:                                               │
│  # etcd_server_leader_changes_seen_total                      │
│  # etcd_server_proposals_committed_total                      │
│  # etcd_server_proposals_failed_total                         │
│  # etcd_disk_wal_fsync_duration_seconds                       │
│  # etcd_network_peer_round_trip_time_seconds                  │
╰───────────────────────────────────────────────────────────────╯
```

---

## Incident Scenario

### Scenario: Kubernetes Control Plane Meltdown — etcd Consensus Failure

```
SETUP:
━━━━━━
You run a large Kubernetes cluster (800 nodes, 12,000 pods).
The control plane has:
  → 5-node etcd cluster (3 in AZ-a, 1 in AZ-b, 1 in AZ-c)
  → etcd stores all cluster state: deployments, services,
    configmaps, secrets, leases
  → etcd data size: 4.2GB
  → Normal write throughput: ~600 writes/sec
  → etcd disk: gp3 EBS volumes (3000 baseline IOPS)
  → Election timeout: 1000ms (default)
  → Heartbeat interval: 100ms (default)
  → 3 Kubernetes API servers (kube-apiserver) behind an NLB

NORMAL STATE:
  → etcd leader: node-1 (AZ-a)
  → Raft term: 847
  → Leader disk fsync p99: 4ms
  → Network RTT between AZs: 0.8ms (same region)
  → API server response time p99: 45ms

THE INCIDENT:
━━━━━━━━━━━━
14:00:00 — Platform team begins deploying a new monitoring
           DaemonSet across all 800 nodes. Each node gets a
           pod spec + configmap + service account + RBAC
           binding = 4 objects per node = 3,200 new objects
           written to etcd in rapid succession.

14:00:15 — etcd write throughput spikes from 600/sec to
           4,800/sec. Normal Raft commit latency (10ms)
           climbs to 85ms.

14:00:30 — etcd node-1 (leader, AZ-a) EBS volume hits IOPS
           ceiling. gp3 baseline is 3000 IOPS, but etcd is
           attempting 4,800 fsyncs/sec. Disk queue depth
           grows. fsync p99 jumps from 4ms to 210ms.

14:00:45 — Leader node-1 misses heartbeat window (100ms
           interval, but fsync takes 210ms — leader can't
           send heartbeats while blocked on fsync).
           Followers in AZ-a (nodes 2, 3) start election.

14:01:00 — Node-2 wins election (term 848). Becomes leader.
           But node-2 is on the SAME gp3 volume type. Same
           IOPS limit. Within 15 seconds, node-2 also hits
           the fsync ceiling.

14:01:15 — Node-2 loses leadership. Node-4 (AZ-b) wins
           (term 849). Cross-AZ RTT is 0.8ms (fine), but
           node-4 is ALSO on gp3. Same problem.

14:01:30 — etcd enters ELECTION STORM. Leaders elected and
           deposed every 10-20 seconds. raft.leader.changes
           metric: 6 changes in 90 seconds.

14:01:45 — During election storms, Raft log replication
           stalls. No commits happening. kube-apiserver
           requests to etcd start timing out (5s timeout).

14:02:00 — kube-apiserver marks etcd as unhealthy. Returns
           "etcdserver: leader changed" errors to clients.
           kubectl commands fail. No new pods can be
           scheduled. Running pods are UNAFFECTED (kubelet
           operates independently) but no NEW operations work.
           lease objects in etcd can't be renewed (etcd not
           accepting writes). After 40 seconds of missed
           renewals, kube-controller-manager starts marking
           nodes as NotReady.

14:03:00 — 127 nodes marked NotReady (their leases expired).
           kube-controller-manager begins pod eviction timers
           for pods on "NotReady" nodes (default: 5 minutes).

14:03:30 — The DaemonSet controller is still retrying its
           3,200 object creation. Each API server retry adds
           MORE writes to etcd's queue. Backlog growing.

14:04:00 — Operators notice: "kubectl get nodes" shows 127
           NotReady. Panic. They attempt to cordon nodes and
           investigate — but kubectl commands timeout because
           etcd is still in election storm.

14:04:30 — etcd node-3 (AZ-a) runs out of WAL disk space.
           The rapid term changes and election RPCs generated
           thousands of WAL entries. Combined with the 3,200
           DaemonSet objects (some partially replicated), the
           WAL directory on node-3 has grown to fill its 20GB
           partition. Node-3 crashes with "no space left on
           device."

14:05:00 — 5-node cluster → 4 functioning nodes. Majority = 3.
           Still have quorum (nodes 1, 2, 4, 5). But the
           election storm continues on the remaining 4 nodes.
           If ONE more node fails → quorum lost → etcd is
           completely down → Kubernetes control plane is dead.

14:05:30 — ALERTS EVERYWHERE. etcd cluster unstable. 127
           nodes NotReady. Pod eviction timers counting down
           (3.5 minutes remaining). DaemonSet controller
           still retrying. kubectl unusable.
```

**Questions:**

**Q1:** Trace the cascade chain. What is the trigger, what are the amplifiers, and identify the specific Raft mechanism that turns a disk I/O bottleneck into a cluster-wide control plane outage. Why does the election storm sustain itself instead of resolving?

**Q2:** At 14:05:30, you're the on-call SRE. The pod eviction timers hit zero in 3.5 minutes. If you don't act, Kubernetes will start killing pods on 127 "NotReady" nodes that are actually healthy. Write your mitigation plan for the first 10 minutes. For each action, state what you're doing, the exact command, what it fixes, and what you must VERIFY before executing it.

**Q3:** The DaemonSet deployment created 3,200 objects in rapid succession. This was the trigger. Design a deployment strategy that would have prevented the etcd overload while still deploying the DaemonSet to all 800 nodes. Be specific about rate limiting, batching, and how Kubernetes mechanisms support this.

**Q4:** The etcd cluster has 3 nodes in AZ-a and 1 each in AZ-b and AZ-c. Evaluate this topology. What happens during an AZ-a failure? Design the correct etcd topology for a 5-node cluster across 3 AZs, and explain why your topology is better using Raft majority math.

**Q5:** After the incident is resolved, design the monitoring and alerting that would catch this cascade at each stage before it reached the election storm. For each alert, specify: the exact metric, the threshold, what it detects, and what automated response should trigger.

---

## Targeted Reading
```
DDIA Chapter 9: Consistency and Consensus (pp 321-375)
  → pp 348-352: Atomic Broadcast and Consensus
    (the equivalence of consensus and total order broadcast)
  → pp 352-359: Epoch Numbering and Quorums
    (maps directly to Raft terms and majority voting)
  → pp 359-363: Limitations of Consensus
    (performance costs, when NOT to use consensus)
  → pp 363-375: Membership and Coordination Services
    (ZooKeeper, etcd — how consensus is used in practice)

Raft paper (Ongaro & Ousterhout, 2014):
  → "In Search of an Understandable Consensus Algorithm"
  → https://raft.github.io/raft.pdf
  → Sections 5.1-5.4 are the core algorithm (~10 pages)
  → Section 6: Cluster membership changes
  → The Raft visualization: https://raft.github.io/
    (interactive — watch elections and log replication)
```

---

## Key Takeaways
```
1. Consensus solves what replication can't: getting N nodes to
   AGREE on a value (leader identity, operation order, lock
   ownership) such that agreement is never violated, even
   during failures. This is the foundation of linearizability.

2. Raft decomposes consensus into three sub-problems: leader
   election (randomized timeouts + majority vote), log
   replication (leader appends, majority commits), and safety
   (election restriction ensures committed entries survive
   leader changes — two majorities always overlap).

3. Terms are Raft's fencing tokens. Every message carries a
   term number. Higher term wins. Stale leaders step down
   immediately on seeing a higher term. This prevents
   split-brain by construction.

4. Committed ≠ replicated. An entry is committed only when a
   MAJORITY has it. Uncommitted entries CAN be lost on leader
   failure. Clients must treat "no response" as ambiguous
   and retry with idempotent operations.

5. Consensus is EXPENSIVE: every write requires majority
   fsync + network RTT. Use it for METADATA and COORDINATION
   (leader election, config, locks, small state) — NOT for
   high-throughput data. Multi-Raft (one Raft group per
   partition) is how CockroachDB and TiKV scale consensus
   horizontally.
```

---

Your turn on the scenario whenever you're ready.

> **Answer key (do not open until you attempt the scenario questions):**
> [`../answers/Week-04-Replication-Partitioning-Consensus/Consensus%20Raft%20Answers.md`](../answers/Week-04-Replication-Partitioning-Consensus/Consensus%20Raft%20Answers.md)
