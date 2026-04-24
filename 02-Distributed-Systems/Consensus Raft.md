# Week 4, Topic 3: Consensus (Raft)

---

## 1. Learning Objectives

```
After this topic, you will be able to:

1. Explain WHY consensus exists — the exact problems it solves 
   that replication and quorums alone cannot
2. Trace the complete Raft algorithm: leader election, log 
   replication, safety guarantees, and commitment rules
3. Walk through Raft term numbers, election timeouts, and 
   split-brain prevention at the message level
4. Explain the safety guarantee that makes Raft correct: 
   why a committed entry can NEVER be lost
5. Compare Raft to Paxos and understand why Raft was designed 
   as "understandable Paxos"
6. Map Raft to real systems (etcd, CockroachDB, TiKV, 
   Consul, MongoDB replica sets) with exact behavioral details
7. Diagnose consensus failures in production: election storms, 
   split-brain, log divergence, and membership change hazards
```

---

## 2. Core Teaching

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
╭────────────────────────────┬──────────────────────────────────╮
│  PRIOR REFERENCE            │  CONSENSUS CONNECTION           │
├────────────────────────────┼──────────────────────────────────┤
│ Week 3 T1: etcd, ZooKeeper │ Both use consensus internally    │
│ classified as PC/EC         │ (etcd=Raft, ZK=ZAB). That's     │
│                             │ WHY they're PC/EC — they        │
│                             │ sacrifice availability for      │
│                             │ agreement.                      │
├────────────────────────────┼──────────────────────────────────┤
│ Week 3 T2: linearizability  │ Consensus is HOW you implement  │
│ "single global timeline"    │ linearizability across multiple │
│                             │ nodes. Raft's replicated log =  │
│                             │ the global timeline.            │
├────────────────────────────┼──────────────────────────────────┤
│ Week 4 T1: split-brain      │ Consensus PREVENTS split-brain  │
│ "two nodes think they're    │ via term numbers and majority   │
│ leader"                     │ voting. This is the formal fix  │
│                             │ for the failover problem.       │
├────────────────────────────┼──────────────────────────────────┤
│ Week 4 T1: fencing tokens   │ Raft's TERM NUMBER is a         │
│ "epoch E+1 rejects writes   │ fencing token. A leader with    │
│ from epoch E"               │ term 5 rejects messages from    │
│                             │ a stale leader with term 4.     │
├────────────────────────────┼──────────────────────────────────┤
│ Week 2: Cassandra QUORUM    │ Quorum is NECESSARY but not     │
│ R+W>N                       │ SUFFICIENT for consensus.       │
│                             │ Consensus adds: leader election,│
│                             │ log ordering, commitment rules. │
│                             │ Quorum is just the voting math. │
╰────────────────────────────┴──────────────────────────────────╯
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

## 3. Production Patterns & Failure Modes

```
╭───────────────────────────────────────────────────────────────╮
│  FAILURE MODE 1: ELECTION STORMS                              │
│                                                               │
│  Cause: Election timeout too short relative to network        │
│  latency. Every time a leader sends a heartbeat, it arrives   │
│  AFTER the follower's election timeout. Follower starts       │
│  election. Leader sends another heartbeat. Too late. Another  │
│  election. Repeat.                                            │
│                                                               │
│  Symptoms:                                                    │
│  → etcd logs: "elected leader" / "lost leader" cycling        │
│  → Kubernetes: API server intermittently unavailable          │
│  → High CPU on etcd nodes from constant election RPCs         │
│  → raft.leader.changes metric spiking                         │
│                                                               │
│  Fix: Increase election timeout.                              │
│  etcd: --election-timeout=5000 (5 seconds, default=1000)      │
│  Rule of thumb: election_timeout > 10× network RTT            │
│  heartbeat_interval = election_timeout / 10                   │
│                                                               │
│  etcd defaults: heartbeat=100ms, election=1000ms              │
│  Cross-region: heartbeat=500ms, election=5000ms               │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│  FAILURE MODE 2: DISK LATENCY CAUSING LEADER LOSS             │
│                                                               │
│  Raft leaders must fsync WAL entries to disk before sending   │
│  AppendEntries. If disk is slow (noisy neighbor in cloud,     │
│  SSD garbage collection, EBS burst credits exhausted):        │
│  → Leader's fsync takes 200ms                                 │
│  → Heartbeat interval is 100ms                                │
│  → Leader misses heartbeat while fsyncing                     │
│  → Followers start election                                   │
│  → Leader steps down, new leader elected                      │
│  → Old leader recovers, tries to sync, disk is still slow     │
│  → If new leader is on SAME slow disk: election storm         │
│                                                               │
│  Fix: Dedicated SSD for Raft WAL. Monitor disk latency.       │
│  etcd: dedicated disk via --wal-dir=/ssd/etcd/wal             │
│  AWS: use io2 EBS volumes for etcd, not gp3                   │
│  Alert: etcd_disk_wal_fsync_duration_seconds p99 > 10ms       │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│  FAILURE MODE 3: LARGE RAFT SNAPSHOT TRANSFERS                │
│                                                               │
│  When a follower falls too far behind (log entries already    │
│  compacted on leader), leader must send a SNAPSHOT:           │
│  → Full state machine snapshot, not individual log entries    │
│  → For etcd with 8GB data: 8GB transfer                       │
│  → During transfer: network bandwidth consumed, leader        │
│    performance degraded, follower rebuilding                  │
│  → If transfer takes too long: election timeout fires,        │
│    another election during snapshot transfer                  │
│                                                               │
│  Fix: Monitor log compaction vs follower position.            │
│  etcd: --snapshot-count=10000 (compact after 10K entries)     │
│  Increase if followers frequently need snapshots.             │
│  etcd_debugging_snap_save_total_duration_seconds monitors.    │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│  FAILURE MODE 4: LEARNER / NON-VOTING MEMBER MISHAPS          │
│                                                               │
│  Adding a new node to a 3-node cluster:                       │
│  → New node needs full data sync (snapshot transfer)          │
│  → During sync: if it's a voting member, it can't vote        │
│    (it doesn't have the log yet)                              │
│  → 3-node cluster + 1 new = 4 nodes, majority = 3             │
│  → New node can't vote → only 3 effective voters              │
│  → If 1 existing node fails → only 2 voters < majority        │
│  → CLUSTER LOSES QUORUM during node addition!                 │
│                                                               │
│  Fix: Add new node as LEARNER (non-voting) first.             │
│  etcd: etcdctl member add <name> --learner                    │
│  Learner receives log entries but doesn't vote.               │
│  Once caught up: promote to voting member.                    │
│  etcdctl member promote <member-id>                           │
│                                                               │
│  This ensures the voting set never includes a node that       │
│  can't actually participate.                                  │
╰───────────────────────────────────────────────────────────────╯
```

---

## 4. Hands-On Exercise

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

## 5. SRE Scenario

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

## 6. Targeted Reading

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

## 7. Key Takeaways

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

# Scenario: Kubernetes Control Plane Meltdown — etcd Consensus Failure

---

## Q1: Cascade Chain Analysis

### The Trigger

```
TRIGGER: DaemonSet deployment creating 3,200 objects in 
rapid succession, spiking etcd writes from 600/sec to 
4,800/sec.

The write volume itself is not extraordinary — etcd can 
handle thousands of writes per second in ideal conditions. 
The trigger becomes catastrophic because the DISK cannot 
sustain 4,800 fsyncs/sec. The gp3 EBS volume has a 
baseline of 3,000 IOPS. The write spike exceeds disk 
capacity by 60%.

The trigger is the MISMATCH between write demand (4,800/sec) 
and disk capacity (3,000 IOPS), not the write volume alone.
```

### The Amplifiers

```
AMPLIFIER 1: EBS gp3 IOPS Ceiling [14:00:30]

  etcd calls fsync() after EVERY Raft log entry to 
  guarantee durability. This is non-negotiable — Raft's 
  correctness depends on durable log entries before 
  acknowledging commits.

  At 4,800 writes/sec, each requiring an fsync:
  → 4,800 IOPS demanded
  → 3,000 IOPS available (gp3 baseline)
  → 1,800 IOPS deficit per second
  → Disk queue builds: each fsync waits longer
  → fsync latency: 4ms → 210ms (52x slower)

  The IOPS ceiling is a HARD WALL. Unlike CPU (which 
  degrades gracefully under load), disk IOPS has a 
  binary threshold: below the limit, fsyncs are fast. 
  Above the limit, a queue forms and latency spikes 
  non-linearly.

  ╔══════════════════════════════════════════════════════════════╗
  ║   IOPS DEMAND vs CAPACITY                                    ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   4800 ┤■■■■■■■■■■■■■■■■■■■■■■■■│■■■■■■■■■■■                 ║
  ║        │                         │ QUEUED                    ║
  ║   3000 ┤─────────────────────────┤ (1800 excess)             ║
  ║        │         SERVED          │                           ║
  ║        │         (3000)          │                           ║
  ║      0 ┤                         │                           ║
  ║        ╰─────────────────────────┴───────────────            ║
  ║                                                              ║
  ║   Every IOPS above 3000 queues. Queue grows                  ║
  ║   linearly. Latency grows with queue depth.                  ║
  ║   At 1800 excess/sec, after 10 seconds:                      ║
  ║   18,000 queued IOPs. Each waits for 18,000/3000             ║
  ║   = 6 seconds. System is functionally frozen.                ║
  ╚══════════════════════════════════════════════════════════════╝


AMPLIFIER 2: Raft Heartbeat / fsync Coupling [14:00:45]

  THIS IS THE CRITICAL RAFT MECHANISM.

  In Raft, the leader must send heartbeat RPCs to all 
  followers at the heartbeat interval (100ms). If a 
  follower doesn't receive a heartbeat within the 
  election timeout (1000ms), it starts an election.

  The leader's main loop:
  1. Receive client write request
  2. Append to local Raft log
  3. fsync the log entry to disk (DURABILITY)
  4. Send AppendEntries RPC to followers (REPLICATION)
  5. Wait for majority ACK
  6. Apply to state machine, respond to client
  7. Send periodic heartbeats (piggyback on AppendEntries 
     or empty AppendEntries when idle)

  THE PROBLEM: Steps 2-3 (fsync) and step 7 (heartbeat) 
  compete for the SAME goroutine / event loop in etcd.

  When fsync takes 210ms:
  → The leader is BLOCKED on disk I/O for 210ms
  → During that 210ms, it cannot send heartbeats
  → Heartbeat interval is 100ms
  → After 2 missed heartbeats (200ms), followers 
    suspect the leader is dead
  → After 1000ms (election timeout), they start election

  The leader is NOT dead. It's not crashed. It's not 
  partitioned. It's waiting for a DISK OPERATION. But 
  to the followers, silence for >1000ms is 
  indistinguishable from death.

  ╔══════════════════════════════════════════════════════════════╗
  ║   LEADER TIMELINE:                                           ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   T=0ms:    Start fsync for log entry                        ║
  ║   T=100ms:  Heartbeat DUE — but blocked on fsync             ║
  ║   T=200ms:  2nd heartbeat DUE — still blocked                ║
  ║   T=210ms:  fsync completes. Send heartbeat.                 ║
  ║                                                              ║
  ║   FOLLOWER TIMELINE:                                         ║
  ║   T=0ms:    Last heartbeat received                          ║
  ║   T=100ms:  No heartbeat. Timer ticking.                     ║
  ║   T=200ms:  No heartbeat. Suspicious.                        ║
  ║   T=1000ms: Election timeout! Start election.                ║
  ║                                                              ║
  ║   The leader's 210ms fsync doesn't directly                  ║
  ║   cause election (1000ms timeout > 210ms).                   ║
  ║   BUT: fsync latency is p99=210ms, meaning                   ║
  ║   some fsyncs take longer. And fsyncs are                    ║
  ║   SEQUENTIAL — the next fsync starts only after              ║
  ║   the previous completes. Multiple slow fsyncs               ║
  ║   compound: 210ms + 210ms + 210ms = 630ms of                 ║
  ║   consecutive blocking. Add disk queue depth                 ║
  ║   growth, and some fsync chains exceed 1000ms.               ║
  ║                                                              ║
  ║   MORE CRITICALLY: during the election storm,                ║
  ║   the new leader must ALSO fsync its term change             ║
  ║   and new log entries. Same disk, same limit.                ║
  ║   The new leader immediately hits the same wall.             ║
  ╚══════════════════════════════════════════════════════════════╝


AMPLIFIER 3: Election Storm Self-Sustaining Loop [14:01:30]

  This is why the storm doesn't resolve:

  1. Leader elected (e.g., node-2, term 848)
  2. Leader receives pending writes (DaemonSet + backlog)
  3. Leader fsyncs → hits IOPS ceiling → heartbeats stall
  4. Followers timeout → new election
  5. New leader elected (e.g., node-4, term 849)
  6. GOTO step 2

  EVERY NODE IN THE CLUSTER has the same gp3 disk.
  Whichever node wins the election immediately faces 
  the same IOPS constraint. Leadership is a hot potato 
  — no node can hold it under this write load.

  ADDITIONAL AMPLIFICATION: Each election itself 
  generates Raft log entries:
  → RequestVote RPCs
  → Term change records
  → New leader announcement
  → Log compaction/snapshot attempts
  → These ALL require fsync, adding to the disk load

  Each election cycle ADDS to the IOPS demand, making 
  the next election MORE likely. This is a positive 
  feedback loop:

  ╔══════════════════════════════════════════════════════════════╗
  ║   Election storm ──► more Raft log entries                   ║
  ║        ▲               │                                     ║
  ║        │               ▼                                     ║
  ║        │          more fsyncs needed                         ║
  ║        │               │                                     ║
  ║        │               ▼                                     ║
  ║        │          disk more overloaded                       ║
  ║        │               │                                     ║
  ║        │               ▼                                     ║
  ║        │          fsync latency increases                    ║
  ║        │               │                                     ║
  ║        │               ▼                                     ║
  ║        ╰────────── heartbeats missed                         ║
  ║                        │                                     ║
  ║                        ▼                                     ║
  ║                   new election ──► loop continues            ║
  ╚══════════════════════════════════════════════════════════════╝


AMPLIFIER 4: DaemonSet Controller Retry Storm [14:03:30]

  The DaemonSet controller runs in kube-controller-manager. 
  When it fails to create objects (etcd timeout), it 
  RETRIES with exponential backoff. But 3,200 objects 
  are queued, and the controller keeps retrying them.

  Each retry generates write requests to kube-apiserver 
  → kube-apiserver sends them to etcd → etcd queues 
  them → more disk pressure → longer fsyncs → more 
  election instability.

  The DaemonSet controller is ADDING FUEL to the fire. 
  The original 3,200 writes are done, but the RETRIES 
  keep the write pressure high.


AMPLIFIER 5: WAL Disk Space Exhaustion [14:04:30]

  etcd's WAL (Write-Ahead Log) accumulates entries:
  → Normal writes (DaemonSet objects)
  → Election records (term changes, votes)
  → Raft proposal entries (even failed ones)
  
  Under normal operation, etcd compacts WAL entries 
  after snapshotting. But during the election storm:
  → No stable leader → no successful compaction
  → WAL entries accumulate without cleanup
  → Node-3's 20GB partition fills up
  → Node-3 crashes: "no space left on device"
  → 5 nodes → 4 nodes. Quorum threshold: 3.
  → ONE more node failure → quorum lost → total outage
```

### The Complete Cascade Chain

```
  DaemonSet deployment: 3,200 objects (TRIGGER)
       │
       ▼
  etcd writes: 600 → 4,800/sec
       │
       ▼
  gp3 IOPS ceiling: 3,000 IOPS < 4,800 demand
       │                                (AMPLIFIER 1)
       ▼
  fsync latency: 4ms → 210ms+
       │
       ▼
  ╔═══════════════════════════════════════════════╗
  ║ RAFT MECHANISM: Leader blocked on fsync       ║
  ║ → cannot send heartbeats → followers timeout  ║
  ║ → election triggered                          ║
  ╚═══════════════════════════════════════════════╝
       │                                (AMPLIFIER 2)
       ▼
  New leader → same disk → same IOPS limit → same problem
       │                                (AMPLIFIER 3)
       ▼
  ELECTION STORM (self-sustaining loop)
       │
       ├──► No commits → API server timeouts
       │    → kubectl fails
       │    → No new scheduling
       │
       ├──► Lease renewals fail → nodes marked NotReady
       │    → Pod eviction timers start (5 min)
       │
       ├──► DaemonSet controller retries add more writes
       │                                (AMPLIFIER 4)
       │
       ╰──► WAL grows without compaction → disk full
            → node-3 crashes           (AMPLIFIER 5)
            → 5 nodes → 4 nodes
            → ONE MORE FAILURE = QUORUM LOST
```

---

## Q2: Mitigation Plan — First 10 Minutes

### Situation at 14:05:30

```
STATE:
  → etcd: 4 of 5 nodes functional (node-3 crashed, disk full)
  → etcd: election storm ongoing (leaders cycling every 10-20s)
  → Quorum: 3 of 5 required. Currently have 4. NO MARGIN.
  → 127 nodes marked NotReady (lease expiry, NOT actually down)
  → Pod eviction: 3.5 minutes until evictions begin
  → DaemonSet controller: still retrying writes
  → kubectl: mostly unusable (etcd timeouts)
  → Running pods: HEALTHY (kubelet is autonomous)

PRIORITY HIERARCHY:
  1. PREVENT POD EVICTIONS (3.5 min countdown — ticking)
  2. STOP THE ELECTION STORM (root cause of all control 
     plane failures)
  3. PREVENT FURTHER NODE LOSS (one more = quorum lost)
  4. RESTORE ETCD STABILITY
  5. RECOVER NODE-3 AND FULL CLUSTER HEALTH
```

### Minute 0-2: Prevent Pod Evictions + Stop the Write Storm

```
ACTION 1: STOP THE DAEMONSET CONTROLLER [0:00 — 30 seconds]

  The DaemonSet controller is continuously retrying 
  3,200 object creations, feeding the write storm. 
  This is the fuel keeping the election storm alive.
  STOP IT.

  # The DaemonSet controller runs inside kube-controller-manager.
  # We can't easily stop ONE controller, but we can 
  # pause the DaemonSet itself:

  # Option A: Scale the DaemonSet to target zero nodes
  # (if kubectl works intermittently):
  kubectl patch daemonset monitoring-agent -n monitoring \
    -p '{"spec":{"template":{"spec":{"nodeSelector":{"non-existent-label":"true"}}}}}'
  
  # This makes the DaemonSet target zero nodes 
  # (no node has label "non-existent-label").
  # The controller stops trying to create new pods.
  # Existing partially-created objects stop retrying.

  # Option B: If kubectl is completely unresponsive,
  # go DIRECTLY to etcd (nuclear option, use with caution):
  # We can't do this easily during election storm.
  # Try Option A first — kubectl may succeed during 
  # brief windows of leader stability.

  # Option C: If all else fails, stop kube-controller-manager:
  # On the control plane node(s):
  # This is DRASTIC — it stops ALL controllers, not just 
  # DaemonSet. But it also stops the NODE CONTROLLER 
  # from evicting pods on "NotReady" nodes.
  
  # If on kubeadm-managed cluster:
  mv /etc/kubernetes/manifests/kube-controller-manager.yaml \
     /etc/kubernetes/kube-controller-manager.yaml.disabled
  
  # kubelet watches /etc/kubernetes/manifests/. Removing 
  # the manifest stops the controller-manager pod.
  # This IMMEDIATELY stops:
  # → DaemonSet retries (no more write storm fuel)
  # → Node controller evictions (pods are safe)
  # → ALL other controllers (deployments, replicasets, etc.)
  
  # This is acceptable as an emergency measure because:
  # → Running pods are unaffected (kubelet is autonomous)
  # → No new pods can be scheduled anyway (etcd is down)
  # → The eviction threat is neutralized

  WHAT THIS FIXES: 
  → Stops write pressure from DaemonSet retries
  → Stops pod eviction timers (if using Option C)
  
  WHAT THIS DOESN'T FIX: 
  → etcd election storm (existing backlog still queued)
  → Node-3 is still crashed
  → 127 nodes still marked NotReady

  VERIFY: 
  # If controller-manager stopped:
  docker ps | grep controller-manager  # should show no container
  # or: crictl ps | grep controller-manager

  # Write rate to etcd should drop. We'll verify 
  # after Action 2 when etcd stabilizes enough 
  # to query metrics.


ACTION 2: STOP THE ELECTION STORM — REDUCE WRITE LOAD [0:30 — 2 minutes]

  The election storm persists because EVERY leader 
  hits the same IOPS ceiling. Two approaches:

  APPROACH A: INCREASE DISK IOPS (fix the bottleneck)
  
  # gp3 volumes support provisioned IOPS up to 16,000.
  # Increase IOPS on ALL surviving etcd node volumes:
  
  for vol_id in vol-etcd1 vol-etcd2 vol-etcd4 vol-etcd5; do
    aws ec2 modify-volume \
      --volume-id $vol_id \
      --iops 16000 \
      --throughput 1000
  done
  
  # gp3 IOPS changes take effect IMMEDIATELY for 
  # increases (no detach/reattach needed).
  # EBS elastic volumes: the change propagates within 
  # seconds to minutes.
  
  # VERIFY BEFORE: Check that the volumes are gp3 
  # (not gp2, which doesn't support provisioned IOPS):
  aws ec2 describe-volumes \
    --volume-ids vol-etcd1 \
    --query 'Volumes[0].VolumeType'
  # Expected: "gp3"

  EFFECT: IOPS ceiling rises from 3,000 to 16,000.
  Even at 4,800 writes/sec, there's massive headroom.
  fsync latency drops from 210ms back to ~4ms.
  Leader can send heartbeats again.
  Election storm stops.

  APPROACH B: IF IOPS INCREASE IS NOT IMMEDIATE

  # Some EBS modifications take minutes to apply.
  # If the election storm continues after IOPS change:
  
  # Temporarily increase election timeout to tolerate 
  # slow fsyncs:
  
  # etcd flag: --election-timeout 5000 (5 seconds)
  # This requires restarting etcd — which is risky 
  # during instability. But if the IOPS fix isn't 
  # taking effect yet, this buys time.
  
  # On each etcd node, edit the etcd manifest or 
  # systemd unit:
  # --election-timeout=5000
  # --heartbeat-interval=500
  
  # Restart etcd:
  systemctl restart etcd
  # or if running as static pod:
  # Edit /etc/kubernetes/manifests/etcd.yaml and 
  # kubelet will restart it automatically.

  # WARNING: Restart one node at a time. With 4 nodes 
  # (quorum=3), losing one during restart is survivable.
  # Losing two = quorum lost.

  # RESTART ORDER: 
  # 1. Node-5 (AZ-c) — least critical
  # 2. Node-4 (AZ-b) — wait for node-5 to rejoin
  # 3. Node-2 (AZ-a) — wait for node-4 to rejoin
  # 4. Node-1 (AZ-a) — last
  # NEVER restart two simultaneously.

  VERIFY:
  etcdctl endpoint status --cluster \
    --endpoints=https://etcd1:2379,https://etcd2:2379,https://etcd4:2379,https://etcd5:2379
  # Look for:
  # → Single stable leader (same ID across checks)
  # → Raft term not incrementing rapidly
  # → No "leader changed" errors
  
  etcdctl endpoint health --cluster
  # All endpoints: healthy
  
  # Check election storm stopped:
  # Prometheus: rate(etcd_server_leader_changes_seen_total[1m])
  # Should be 0 (no leader changes in the last minute)
```

### Minute 2-5: Verify Stability + Prevent Evictions

```
ACTION 3: VERIFY ETCD IS STABLE [2:00 — 2 minutes]

  # Before doing ANYTHING else, confirm etcd has 
  # stabilized. One change at a time.

  # Check 1: Leader is stable
  for i in $(seq 1 5); do
    etcdctl endpoint status \
      --endpoints=https://etcd1:2379 \
      -w table 2>/dev/null | grep -i leader
    sleep 5
  done
  # Same leader ID across all 5 checks = stable

  # Check 2: Write latency is normal
  etcdctl put /health-check/test "$(date)" \
    --endpoints=https://etcd1:2379
  # Should complete in < 50ms

  # Check 3: Disk metrics
  # On the leader node:
  iostat -x 1 5 | grep <etcd-disk-device>
  # await (average I/O wait) should be < 10ms
  # %util should be < 50%

  # Check 4: Raft metrics
  curl -s https://etcd-leader:2379/metrics | grep -E \
    'etcd_disk_wal_fsync_duration_seconds|etcd_server_leader_changes'
  # wal_fsync p99 should be < 10ms
  # leader_changes should be 0 in the last minute

  IF ETCD IS NOT STABLE: Do NOT proceed. Go back to 
  Action 2. Try Approach B (election timeout increase).

  IF ETCD IS STABLE: Proceed to Action 4.


ACTION 4: RESTORE CONTROLLER-MANAGER WITH EVICTION PROTECTION [4:00 — 1 minute]

  Before re-enabling the controller-manager, increase 
  the pod eviction tolerance so the 127 "NotReady" 
  nodes don't trigger immediate mass eviction:

  # Option A: Increase tolerations on the API server 
  # (controls how long to wait before evicting pods 
  # from NotReady nodes):
  
  # Edit kube-controller-manager manifest:
  # --pod-eviction-timeout=30m (default is 5m)
  # This gives 30 minutes before eviction starts.
  
  # On the control plane node:
  vi /etc/kubernetes/kube-controller-manager.yaml.disabled
  # Add to command args:
  # --pod-eviction-timeout=30m
  
  # Restore the manifest:
  mv /etc/kubernetes/kube-controller-manager.yaml.disabled \
     /etc/kubernetes/manifests/kube-controller-manager.yaml
  
  # kubelet detects the manifest and starts 
  # kube-controller-manager.

  # Option B: If we DIDN'T stop controller-manager 
  # (used Option A for DaemonSet), increase the 
  # toleration now:
  kubectl patch deployment kube-controller-manager \
    -n kube-system --type=json \
    -p='[{"op":"add","path":"/spec/template/spec/containers/0/command/-","value":"--pod-eviction-timeout=30m"}]'

  EFFECT: 
  → Controller-manager restarts with 30-minute eviction 
    timeout
  → 127 "NotReady" nodes get 30 minutes before eviction
  → This gives us time to renew their leases

  VERIFY:
  kubectl get pods -n kube-system | grep controller-manager
  # Running, not CrashLoopBackOff
  
  kubectl get nodes | grep NotReady | wc -l
  # Should show 127 NotReady but NO evictions starting


ACTION 5: FORCE NODE LEASE RENEWAL [4:30 — 1 minute]

  The 127 "NotReady" nodes are actually healthy — their 
  kubelets are running, pods are fine. They were marked 
  NotReady because etcd couldn't accept lease renewals 
  during the election storm.

  Now that etcd is stable, kubelets will AUTOMATICALLY 
  renew their leases on the next heartbeat cycle 
  (default: every 10 seconds).

  # Watch nodes recover:
  watch -n 5 'kubectl get nodes | grep -c NotReady'
  
  # Within 10-40 seconds, nodes should start 
  # transitioning from NotReady → Ready as their 
  # kubelets successfully renew leases.

  # If nodes DON'T recover within 60 seconds:
  # Check that kubelets can reach the API server:
  # On a "NotReady" node:
  journalctl -u kubelet --since "5 minutes ago" | tail -50
  # Look for successful heartbeat messages

  VERIFY: 
  kubectl get nodes | grep -c NotReady
  # Should decrease rapidly: 127 → 80 → 40 → 10 → 0
  # over ~60 seconds
```

### Minute 5-10: Recover Node-3 + Clean Up

```
ACTION 6: RECOVER ETCD NODE-3 [5:00 — 3 minutes]

  Node-3 crashed with "no space left on device" on 
  its WAL partition (20GB full).

  # SSH to node-3:
  ssh etcd-node-3

  # Check disk usage:
  df -h /var/lib/etcd
  # 100% used

  # Clean up old WAL and snapshot files:
  # etcd stores WAL in /var/lib/etcd/member/wal/
  # and snapshots in /var/lib/etcd/member/snap/

  # Option A: If we can free space, restart etcd:
  # Remove old snapshot files (keep the latest):
  ls -lt /var/lib/etcd/member/snap/
  # Keep the most recent .snap file, remove older ones
  
  # But WAL files can't be safely manually deleted — 
  # etcd manages them internally.
  
  # SAFEST APPROACH: Expand the EBS volume.
  # From outside the node:
  aws ec2 modify-volume \
    --volume-id vol-etcd3 \
    --size 50 \
    --iops 16000 \
    --volume-type gp3
  
  # On node-3, resize the filesystem:
  # (For ext4):
  resize2fs /dev/xvdf
  # (For xfs):
  xfs_growfs /var/lib/etcd
  
  # Verify:
  df -h /var/lib/etcd
  # Should show ~50GB with plenty of free space

  # ALSO: Increase IOPS to 16,000 (same as other nodes)
  # Already done in the modify-volume command above.

  # Restart etcd on node-3:
  systemctl start etcd
  
  # etcd will rejoin the cluster, replicate any missed 
  # log entries from the leader, and become a healthy 
  # follower.

  VERIFY:
  etcdctl member list \
    --endpoints=https://etcd1:2379
  # All 5 members listed
  
  etcdctl endpoint health --cluster \
    --endpoints=https://etcd1:2379,https://etcd2:2379,https://etcd3:2379,https://etcd4:2379,https://etcd5:2379
  # All 5: healthy

  # Quorum: back to 5 nodes, majority = 3.
  # Can survive 2 node failures again.


ACTION 7: COMPACT ETCD AND DEFRAGMENT [7:00 — 2 minutes]

  The election storm generated thousands of unnecessary 
  log entries (term changes, failed proposals). etcd's 
  data size may have bloated. Compact and defragment.

  # Get current revision:
  rev=$(etcdctl endpoint status \
    --endpoints=https://etcd1:2379 -w json | \
    python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Status']['header']['revision'])")
  
  # Compact all revisions up to current:
  etcdctl compact $rev \
    --endpoints=https://etcd1:2379
  
  # Defragment each node (one at a time!):
  for endpoint in etcd1 etcd2 etcd3 etcd4 etcd5; do
    etcdctl defrag --endpoints=https://${endpoint}:2379
    echo "Defragged ${endpoint}. Waiting 10s..."
    sleep 10
    etcdctl endpoint health --endpoints=https://${endpoint}:2379
  done
  
  # Defrag one at a time because defrag blocks the 
  # node briefly. Running on all simultaneously could 
  # drop below quorum.

  VERIFY:
  etcdctl endpoint status --cluster -w table
  # DB SIZE should have decreased
  # All endpoints: healthy, same leader


ACTION 8: SAFELY RE-ENABLE DAEMONSET [8:00 — 2 minutes]

  Now that etcd is stable with 16,000 IOPS headroom, 
  re-enable the DaemonSet — but with rate limiting 
  (see Q3 for full strategy):

  # Remove the impossible node selector:
  kubectl patch daemonset monitoring-agent -n monitoring \
    --type=json \
    -p='[{"op":"remove","path":"/spec/template/spec/nodeSelector/non-existent-label"}]'

  # BUT: Add maxUnavailable to control rollout rate:
  kubectl patch daemonset monitoring-agent -n monitoring \
    --type=merge \
    -p='{"spec":{"updateStrategy":{"type":"RollingUpdate","rollingUpdate":{"maxUnavailable":"5%"}}}}'

  # This limits the DaemonSet to creating/updating 
  # pods on 5% of nodes at a time (40 nodes out of 800).
  # Instead of 3,200 objects in 15 seconds, objects 
  # are created in waves of ~160 (4 objects × 40 nodes).

  VERIFY:
  kubectl get daemonset monitoring-agent -n monitoring
  # DESIRED: 800, CURRENT: increasing gradually
  # Watch etcd write rate: should stay well below 
  # 3,000/sec during the rollout
  
  # Monitor etcd health continuously during rollout:
  watch -n 5 "etcdctl endpoint status --cluster -w table"
```

### Mitigation Timeline Summary

```
╭─────────┬──────────────────────────────────┬──────────────────╮
│  TIME   │ ACTION                           │ FIXES            │
├─────────┼──────────────────────────────────┼──────────────────┤
│  0:00   │ Stop DaemonSet controller        │ Write storm fuel │
│         │ (patch DaemonSet or stop         │ + pod eviction   │
│         │  controller-manager)             │ timers           │
├─────────┼──────────────────────────────────┼──────────────────┤
│  0:30   │ Increase EBS IOPS to 16,000      │ Root cause:      │
│         │ on all etcd volumes              │ IOPS bottleneck  │
│         │ (+election timeout if needed)    │ → election storm │
├─────────┼──────────────────────────────────┼──────────────────┤
│  2:00   │ Verify etcd stability            │ Confirms storm   │
│         │ (leader stable, fsync normal)    │ has stopped      │
├─────────┼──────────────────────────────────┼──────────────────┤
│  4:00   │ Restore controller-manager       │ Pod eviction     │
│         │ with 30m eviction timeout        │ protection       │
├─────────┼──────────────────────────────────┼──────────────────┤
│  4:30   │ Wait for node lease renewal      │ 127 NotReady     │
│         │ (automatic via kubelet)          │ → Ready          │
├─────────┼──────────────────────────────────┼──────────────────┤
│  5:00   │ Recover node-3 (expand disk,     │ 5th etcd node    │
│         │ increase IOPS, restart etcd)     │ restored         │
├─────────┼──────────────────────────────────┼──────────────────┤
│  7:00   │ Compact + defragment etcd        │ Clean up bloat   │
│         │ (one node at a time)             │ from storm       │
├─────────┼──────────────────────────────────┼──────────────────┤
│  8:00   │ Re-enable DaemonSet with rate    │ Complete the     │
│         │ limiting (5% maxUnavailable)     │ original deploy  │
╰─────────┴──────────────────────────────────┴──────────────────╯

ORDER DEPENDENCIES:
  Action 1 MUST be first: stop the fuel (writes) and 
    protect against evictions simultaneously.
  Action 2 MUST be second: fix the root cause (disk IOPS).
  Action 3 MUST precede 4: verify etcd is stable before 
    re-enabling controller-manager (which will issue writes).
  Action 4 MUST precede 5: protect evictions before nodes 
    start renewing leases (the transition from NotReady 
    → Ready generates writes to etcd).
  Action 6 MUST follow stability: adding a node during 
    instability could worsen things (Raft bootstrapping 
    requires writes).
  Action 7 MUST follow 6: defrag with all 5 nodes healthy 
    (can tolerate one node being briefly unresponsive).
  Action 8 MUST be last: only re-introduce the write load 
    after ALL other issues are resolved and verified.
```

---

## Q3: DaemonSet Deployment Strategy That Prevents etcd Overload

```
THE PROBLEM:
  3,200 objects (4 per node × 800 nodes) created in 
  ~15 seconds = 213 objects/sec. Each object creation 
  is a write to etcd. Combined with existing 600/sec 
  baseline = 4,800/sec total. Exceeds 3,000 IOPS limit.

THE GOAL:
  Deploy to all 800 nodes without exceeding etcd's 
  write capacity. Budget: 3,000 IOPS baseline - 600 
  existing = 2,400 IOPS available for the deployment.
  
  4 objects per node × rate = write TPS
  At 2,400 available IOPS: max 600 nodes/sec 
  (4 objects × 600 = 2,400). But we want headroom.
  
  TARGET: Keep deployment writes under 1,200/sec 
  (50% of available IOPS — leave headroom for variance).
  
  1,200/sec ÷ 4 objects/node = 300 nodes/sec max rate.
  But we should be much more conservative — batch in 
  waves with pauses.
```

### Strategy 1: DaemonSet maxUnavailable with RollingUpdate

```
The DaemonSet spec supports maxUnavailable in its 
updateStrategy, which controls how many pods are 
created/updated simultaneously:

apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: monitoring-agent
  namespace: monitoring
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 25
      # Only create/update 25 pods at a time.
      # 25 pods × 4 objects = 100 objects per wave.
      # At ~2 seconds per wave: ~50 objects/sec added 
      # to etcd writes.
      # 800 nodes ÷ 25 per wave = 32 waves
      # At ~5 seconds per wave (including scheduling): 
      # ~160 seconds total = ~2.7 minutes.

EFFECT ON ETCD:
  → Baseline: 600 writes/sec
  → Deployment adds: ~50-100 writes/sec per wave
  → Total: ~700 writes/sec
  → Well under 3,000 IOPS ceiling (77% headroom)
  → fsync latency stays at 4ms
  → No heartbeat disruption
  → No election storm

TRADEOFF:
  → Deployment takes ~3 minutes instead of ~15 seconds
  → Perfectly acceptable for a monitoring DaemonSet
```

### Strategy 2: Staged Rollout with Canary

```
EVEN SAFER: Deploy to a subset first, verify, then expand.

PHASE 1: Label 10 nodes as canary
  kubectl label nodes node-{1..10} monitoring-canary=true

PHASE 2: Deploy DaemonSet with nodeSelector targeting 
only canary nodes:
  
  apiVersion: apps/v1
  kind: DaemonSet
  metadata:
    name: monitoring-agent
  spec:
    selector:
      matchLabels:
        app: monitoring-agent
    template:
      spec:
        nodeSelector:
          monitoring-canary: "true"
        containers:
        - name: agent
          image: monitoring-agent:v1.0
    updateStrategy:
      type: RollingUpdate
      rollingUpdate:
        maxUnavailable: 5

  # 10 nodes × 4 objects = 40 objects. Trivial.
  # Verify: pods running, etcd stable.

PHASE 3: Expand to 100 nodes
  kubectl label nodes node-{1..100} monitoring-rollout=phase2
  # Update DaemonSet nodeSelector to match both labels
  # 90 new nodes × 4 objects = 360 objects. 
  # With maxUnavailable=25: ~4 waves, ~20 seconds.
  # Verify.

PHASE 4: Expand to all 800 nodes
  # Remove nodeSelector (target all nodes)
  # With maxUnavailable=25: 28 waves, ~3 minutes.
  # Monitor etcd write rate throughout.

ETCD WRITE RATE DURING STAGED ROLLOUT:
  Phase 1: 600 + 40 = 640/sec (instant)
  Phase 2: 600 + ~50/sec = 650/sec (over 20s)
  Phase 3: 600 + ~100/sec = 700/sec (over 3 min)
  NEVER exceeds 800/sec. 73% headroom at all times.
```

### Strategy 3: Server-Side Rate Limiting (API Priority and Fairness)

```
Kubernetes 1.29+ supports API Priority and Fairness 
(APF) which rate-limits API server requests by category.

Configure a FlowSchema that limits DaemonSet controller 
writes:

apiVersion: flowcontrol.apiserver.k8s.io/v1beta3
kind: FlowSchema
metadata:
  name: daemonset-rate-limit
spec:
  priorityLevelConfiguration:
    name: daemonset-workloads
  matchingPrecedence: 500
  rules:
  - subjects:
    - kind: ServiceAccount
      serviceAccount:
        name: daemon-set-controller
        namespace: kube-system
    resourceRules:
    - verbs: ["create", "update", "patch"]
      apiGroups: ["*"]
      resources: ["*"]
      namespaces: ["*"]

---
apiVersion: flowcontrol.apiserver.k8s.io/v1beta3
kind: PriorityLevelConfiguration
metadata:
  name: daemonset-workloads
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 10
    # Low share — DaemonSet controller gets limited 
    # concurrency compared to user-facing workloads.
    lendablePercent: 0
    limitResponse:
      type: Queue
      queuing:
        queues: 16
        handSize: 4
        queueLengthLimit: 50

EFFECT:
  → DaemonSet controller's API requests are queued and 
    rate-limited by the API server itself
  → Even if the controller tries to create 3,200 objects 
    at once, the API server throttles them
  → Other API operations (kubectl, kubelet heartbeats) 
    get higher priority and aren't affected
  → etcd write rate stays within bounds regardless of 
    controller behavior

THIS IS DEFENSE IN DEPTH: Even if someone deploys a 
DaemonSet without maxUnavailable limits, the API server 
rate-limits the controller's writes.
```

### Summary: Deployment Strategy

```
RECOMMENDED APPROACH: Strategy 1 + Strategy 3

  1. Always set maxUnavailable on DaemonSets:
     → maxUnavailable: 25 (or 3-5% of cluster size)
     → This is the PRIMARY control on write rate.

  2. Configure API Priority and Fairness:
     → Rate-limit DaemonSet controller at the API server
     → This is the SAFETY NET if someone forgets 
       maxUnavailable.

  3. For critical deployments: use Strategy 2 (staged 
     rollout with canary).

  WRITE RATE BUDGET:
  ╔══════════════════════════════════════════════════════════════╗
  ║  Available IOPS             │ 3,000                          ║
  ║  Baseline writes            │ 600/sec                        ║
  ║  Available for deployment   │ 2,400/sec                      ║
  ║  Target (50% headroom)      │ 1,200/sec                      ║
  ║  With maxUnavailable=25     │ ~100/sec                       ║
  ║  HEADROOM                   │ 92%                            ║
  ╚══════════════════════════════════════════════════════════════╝
```

---

## Q4: etcd Topology Evaluation and Redesign

### Current Topology Analysis

```
CURRENT: 3 nodes in AZ-a, 1 in AZ-b, 1 in AZ-c

  AZ-a: node-1, node-2, node-3  (3 nodes)
  AZ-b: node-4                  (1 node)
  AZ-c: node-5                  (1 node)

  Quorum for 5 nodes: majority = 3

SCENARIO: AZ-a FAILS (entire AZ unavailable)

  → Nodes 1, 2, 3 are all DOWN simultaneously.
  → Remaining: node-4 (AZ-b) + node-5 (AZ-c) = 2 nodes.
  → Quorum requires 3.
  → 2 < 3 → QUORUM LOST.
  → etcd is COMPLETELY UNAVAILABLE.
  → Kubernetes control plane is DEAD.
  → No new pods, no scheduling, no kubectl, no lease 
    renewals, eventual pod evictions.

  This topology CANNOT survive an AZ failure.

  ╔══════════════════════════════════════════════════════════════╗
  ║   AZ-a failure:                                              ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   AZ-a (DEAD):  ╳ node-1  ╳ node-2  ╳ node-3                 ║
  ║   AZ-b (ALIVE): ✓ node-4                                     ║
  ║   AZ-c (ALIVE): ✓ node-5                                     ║
  ║                                                              ║
  ║   Alive: 2.  Quorum: 3.  2 < 3 → NO QUORUM.                  ║
  ║                                                              ║
  ║   Probability of AZ failure: LOW but non-zero.               ║
  ║   AWS has had AZ-level outages multiple times.               ║
  ║   Losing the entire control plane on a single                ║
  ║   AZ failure is unacceptable for an 800-node                 ║
  ║   production cluster.                                        ║
  ╚══════════════════════════════════════════════════════════════╝

ADDITIONAL PROBLEM WITH CURRENT TOPOLOGY:

  Even WITHOUT an AZ failure, the 3-in-AZ-a topology 
  creates a performance bias:
  
  → If the leader is in AZ-a (likely — 3 of 5 nodes): 
    it can get quorum from the 2 other AZ-a nodes with 
    <1ms latency. Fast commits. Good.
  
  → If the leader is in AZ-b or AZ-c: it must reach 
    2 nodes in AZ-a for quorum. Cross-AZ RTT is 0.8ms. 
    Slightly slower but acceptable.
  
  → The BIAS: AZ-a nodes will almost always win elections 
    (they can reach 2 peers locally faster than cross-AZ 
    candidates). Leadership is effectively pinned to AZ-a.
    This concentrates the leader's disk I/O in AZ-a. 
    If AZ-a has an EBS degradation (not full outage), 
    the leader is affected with no fast failover to 
    another AZ.
```

### Correct Topology: 2-2-1 Distribution

```
REDESIGNED: 2 nodes in AZ-a, 2 in AZ-b, 1 in AZ-c

  AZ-a: node-1, node-2  (2 nodes)
  AZ-b: node-3, node-4  (2 nodes)
  AZ-c: node-5          (1 node)

  Quorum: 3 of 5.

SCENARIO ANALYSIS:

  AZ-a fails:
  → Remaining: node-3, node-4 (AZ-b) + node-5 (AZ-c)
  → Alive: 3. Quorum: 3. ✓ QUORUM MAINTAINED.
  → etcd continues operating. Control plane survives.

  AZ-b fails:
  → Remaining: node-1, node-2 (AZ-a) + node-5 (AZ-c)
  → Alive: 3. Quorum: 3. ✓ QUORUM MAINTAINED.
  → etcd continues operating.

  AZ-c fails:
  → Remaining: node-1, node-2 (AZ-a) + node-3, node-4 (AZ-b)
  → Alive: 4. Quorum: 3. ✓ QUORUM MAINTAINED.
  → etcd continues operating (with extra margin).

  ╔══════════════════════════════════════════════════════════════╗
  ║   FAILURE TOLERANCE COMPARISON:                              ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Topology      │ AZ-a  │ AZ-b  │ AZ-c  │                    ║
  ║                 │ fails │ fails │ fails │                    ║
  ║   ─────────────┼───────┼───────┼───────┤                     ║
  ║   3-1-1        │  ✗    │  ✓   │  ✓    │                      ║
  ║   (current)    │       │       │       │                     ║
  ║   ─────────────┼───────┼───────┼───────┤                     ║
  ║   2-2-1        │  ✓    │  ✓   │  ✓    │                      ║
  ║   (proposed)   │       │       │       │                     ║
  ║   ─────────────┴───────┴───────┴───────╯                     ║
  ║                                                              ║
  ║   3-1-1: Survives ANY SINGLE AZ failure                      ║
  ║          EXCEPT the AZ with 3 nodes.                         ║
  ║   2-2-1: Survives ANY SINGLE AZ failure.                     ║
  ║          Period.                                             ║
  ║                                                              ║
  ║   The only topology that CANNOT survive a                    ║
  ║   single AZ failure with 5 nodes is one where                ║
  ║   ≥3 nodes are in the same AZ (majority in                   ║
  ║   one failure domain).                                       ║
  ╚══════════════════════════════════════════════════════════════╝

RAFT MAJORITY MATH:

  For a 5-node Raft cluster, quorum = ⌊5/2⌋ + 1 = 3.
  
  RULE: No single AZ may contain ≥ quorum nodes.
  If one AZ has ≥3 nodes: losing that AZ loses quorum.
  
  With 5 nodes across 3 AZs, valid distributions:
  → 2-2-1: max per AZ = 2 < 3 ✓
  → 3-1-1: max per AZ = 3 = quorum ✗ (AZ-a is SPOF)
  → 1-1-3: same problem in AZ-c ✗
  
  2-2-1 is the ONLY distribution across 3 AZs that 
  survives any single AZ failure with a 5-node cluster.

WHY NOT 2-2-1-0-0 (use only 2 AZs)?
  → 2-3 or 3-2: losing the 3-node AZ = quorum lost.
  → At least 3 AZs needed for single-AZ fault tolerance 
    with 5 nodes.

WHY NOT 7 NODES (3-2-2)?
  → 7 nodes: quorum = 4.
  → 3-2-2: Losing AZ-a (3 nodes) leaves 4. Quorum met. ✓
  → More resilient but more expensive and higher commit 
    latency (more nodes to replicate to).
  → 5 nodes with 2-2-1 is the sweet spot for most 
    clusters.

ADDITIONAL BENEFIT OF 2-2-1:

  Leader election is more balanced:
  → AZ-a and AZ-b each have 2 nodes (equal weight)
  → AZ-c has 1 node (can still win elections)
  → Leadership naturally rotates across AZs
  → No single AZ concentrates disk I/O
```

### Migration Plan from 3-1-1 to 2-2-1

```
CURRENT: AZ-a (1,2,3), AZ-b (4), AZ-c (5)
TARGET:  AZ-a (1,2), AZ-b (4,NEW-6), AZ-c (5)
         (Remove node-3 from AZ-a, add node-6 to AZ-b)

STEPS:

  1. Add node-6 in AZ-b:
     etcdctl member add node-6 \
       --peer-urls=https://node-6:2380
     # Start etcd on node-6. It syncs from leader.
     # Cluster: 6 nodes. Quorum: 4.

  2. Verify node-6 is healthy and caught up:
     etcdctl endpoint health --cluster
     etcdctl endpoint status --cluster -w table
     # node-6 should show healthy, raft index close to leader

  3. Remove node-3 from AZ-a:
     etcdctl member remove <node-3-id>
     # Cluster: 5 nodes. Quorum: 3.
     # Distribution: AZ-a(1,2), AZ-b(4,6), AZ-c(5) = 2-2-1

  4. Shut down etcd on node-3.

  5. Verify final topology:
     etcdctl member list
     # 5 members across 3 AZs: 2-2-1

  ORDER MATTERS: Add before remove. 
  → Adding first: 6 nodes, quorum 4. Safe.
  → If we removed first: 4 nodes, quorum 3. 
    Only 1 node failure away from quorum loss during 
    the transition.
```

---

## Q5: Monitoring and Alerting — Catching the Cascade at Each Stage

### Stage 1: etcd Disk Performance Degradation

```
METRIC: etcd_disk_wal_fsync_duration_seconds 
        (histogram, p99 bucket)

  - alert: EtcdWalFsyncSlow
    expr: |
      histogram_quantile(0.99, 
        rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])
      ) > 0.01
    for: 1m
    labels:
      severity: warning
    annotations:
      summary: "etcd WAL fsync p99 > 10ms on {{ $labels.instance }}"
      description: |
        Normal: < 5ms. Current: {{ $value }}s.
        Disk is becoming a bottleneck. If this reaches 
        100ms, heartbeat disruption and election storms 
        become likely.

  WHAT IT DETECTS: Disk I/O degradation BEFORE it 
  reaches the election-triggering threshold. At 10ms, 
  there's still 90ms of headroom before heartbeats 
  are affected (100ms interval).

  AUTOMATED RESPONSE:
    → WARN at > 10ms: Page on-call. Check EBS IOPS 
      utilization. Consider provisioned IOPS increase.
    → CRITICAL at > 50ms: 
      AUTO-ACTION: Increase EBS IOPS to 16,000 on all 
      etcd volumes via AWS API call.
      
      # Automated runbook:
      aws ec2 modify-volume --volume-id $VOL_ID --iops 16000
      
      This buys immediate headroom without human 
      intervention.

  ╔══════════════════════════════════════════════════════════════╗
  ║   In the incident: this would have fired at                  ║
  ║   14:00:30 (fsync went from 4ms to 210ms).                   ║
  ║   The automated IOPS increase would have                     ║
  ║   resolved the problem before any election.                  ║
  ║   CASCADE PREVENTED AT STAGE 1.                              ║
  ╚══════════════════════════════════════════════════════════════╝


COMPLEMENTARY METRIC: EBS IOPS utilization

  - alert: EtcdDiskIopsHigh
    expr: |
      rate(node_disk_reads_completed_total{device="<etcd-disk>"}[1m])
      + rate(node_disk_writes_completed_total{device="<etcd-disk>"}[1m])
      > 2400
    for: 30s
    labels:
      severity: warning
    annotations:
      summary: "etcd disk IOPS > 80% of gp3 baseline (3000)"
      description: |
        Current IOPS: {{ $value }}. Baseline: 3000.
        20% headroom remaining. If write rate continues 
        to increase, IOPS ceiling will be hit.

  AUTOMATED RESPONSE:
    → At 80% IOPS: Alert SRE + prepare IOPS increase.
    → At 95% IOPS: AUTO-INCREASE IOPS to 16,000.
```

### Stage 2: Raft Leader Instability

```
METRIC: etcd_server_leader_changes_seen_total

  - alert: EtcdLeaderChanges
    expr: |
      increase(etcd_server_leader_changes_seen_total[10m]) > 2
    for: 0s
    labels:
      severity: critical
      automation: etcd_election_storm
    annotations:
      summary: "etcd leader changed {{ $value }} times in 10 minutes"
      description: |
        Normal: 0 changes in steady state. >2 in 10 minutes 
        indicates election instability. If this continues, 
        Raft commits will stall and the control plane will 
        become unavailable.

  WHAT IT DETECTS: Election storm in its EARLY stage. 
  In the incident, there were 6 leader changes in 90 
  seconds. This alert fires after the 3rd change.

  AUTOMATED RESPONSE:
    → Page on-call IMMEDIATELY (severity: critical).
    → AUTO-ACTION 1: Increase EBS IOPS on all etcd 
      volumes to 16,000 (most common root cause).
    → AUTO-ACTION 2: Temporarily increase election timeout:
      
      # On each etcd node (via etcd API, no restart):
      # etcd doesn't support runtime election timeout 
      # changes — this requires restart. So:
      
      # Instead: reduce write pressure by pausing 
      # non-critical controllers:
      kubectl patch deployment metrics-server -n kube-system \
        -p '{"spec":{"replicas":0}}'
      # Pause any custom controllers that write frequently.
      
    → AUTO-ACTION 3: Check for bulk write operations 
      (DaemonSet deployments, large CRD updates) and 
      throttle them.

  ╔══════════════════════════════════════════════════════════════╗
  ║   In the incident: this fires at ~14:01:15                   ║
  ║   (3rd leader change). Auto IOPS increase                    ║
  ║   resolves within 1-2 minutes. Election                      ║
  ║   storm stops at 14:03. Nodes never marked                   ║
  ║   NotReady. No evictions. No WAL exhaustion.                 ║
  ║   CASCADE PREVENTED AT STAGE 2.                              ║
  ╚══════════════════════════════════════════════════════════════╝
```

### Stage 3: etcd Commit Latency

```
METRIC: etcd_disk_backend_commit_duration_seconds 
        (histogram, p99)

  - alert: EtcdCommitLatencyHigh  
    expr: |
      histogram_quantile(0.99,
        rate(etcd_disk_backend_commit_duration_seconds_bucket[5m])
      ) > 0.1
    for: 30s
    labels:
      severity: critical
    annotations:
      summary: "etcd backend commit p99 > 100ms"
      description: |
        Normal: < 25ms. Current: {{ $value }}s.
        Raft commits are slow. API server requests will 
        start timing out. Kubernetes operations will fail.

  WHAT IT DETECTS: The moment etcd commits become slow 
  enough to affect API server operations. This fires 
  BEFORE API server timeouts (5 seconds) but AFTER the 
  disk bottleneck is established.

  AUTOMATED RESPONSE:
    → Same as Stage 2 (IOPS increase + write throttling).
    → Additional: enable etcd request rate limiting:
      
      # etcd supports --max-request-bytes and 
      # --quota-backend-bytes. But more useful:
      # API server side — enable API Priority and Fairness 
      # to throttle bulk operations automatically.
```

### Stage 4: API Server etcd Health

```
METRIC: apiserver_request_duration_seconds 
        (for etcd-related operations)
AND:    etcd_request_duration_seconds (from API server)

  - alert: ApiserverEtcdRequestSlow
    expr: |
      histogram_quantile(0.99,
        rate(etcd_request_duration_seconds_bucket{type="write"}[5m])
      ) > 1.0
    for: 30s
    labels:
      severity: critical
    annotations:
      summary: "API server etcd write requests p99 > 1 second"
      description: |
        API server is experiencing etcd timeouts. kubectl 
        commands and controller operations will fail. 
        Scheduling is likely impaired.

  WHAT IT DETECTS: The API server's view of etcd health.
  If etcd is in an election storm, API server requests 
  to etcd will timeout. This is the USER-FACING impact.

  AUTOMATED RESPONSE:
    → All previous automated responses plus:
    → Preemptively increase pod-eviction-timeout:
      
      # Prevent the eviction cascade that would start 
      # 5 minutes after nodes go NotReady:
      # This must be done BEFORE nodes go NotReady.
      
      # Automated script patches the controller-manager 
      # to extend eviction timeout from 5m to 30m.
```

### Stage 5: etcd WAL/DB Size Growth

```
METRIC: etcd_mvcc_db_total_size_in_bytes 
AND:    node_filesystem_avail_bytes{mountpoint="/var/lib/etcd"}

  - alert: EtcdDbSizeLarge
    expr: |
      etcd_mvcc_db_total_size_in_bytes > 6e9
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "etcd database size > 6GB (default quota: 8GB)"
      description: |
        etcd database approaching quota limit. If it 
        reaches 8GB, etcd will reject all writes (alarm).
        Compact and defragment.

  - alert: EtcdDiskSpaceLow
    expr: |
      node_filesystem_avail_bytes{mountpoint="/var/lib/etcd"}
      / node_filesystem_size_bytes{mountpoint="/var/lib/etcd"}
      < 0.2
    for: 1m
    labels:
      severity: critical
      automation: etcd_disk_expand
    annotations:
      summary: "etcd disk < 20% free on {{ $labels.instance }}"
      description: |
        WAL and/or snapshot files consuming disk space.
        If disk fills completely, etcd crashes.

  WHAT IT DETECTS: The WAL exhaustion that crashed 
  node-3 at 14:04:30. With 20GB partition and rapid 
  WAL growth during election storm, disk filled in 
  ~4 minutes.

  AUTOMATED RESPONSE:
    → At < 20% free: 
      AUTO-ACTION: Expand EBS volume by 2x.
      
      aws ec2 modify-volume --volume-id $VOL_ID --size 50
      # Then on the node:
      resize2fs /dev/<device>
      
    → At < 10% free:
      AUTO-ACTION: Trigger emergency etcd compaction:
      
      rev=$(etcdctl endpoint status -w json | \
        python3 -c "...")
      etcdctl compact $rev
      
      This frees space from old revisions.

  ╔══════════════════════════════════════════════════════════════╗
  ║   In the incident: this fires at ~14:04:00                   ║
  ║   (30 seconds before node-3 crashes).                        ║
  ║   Auto volume expansion prevents the crash.                  ║
  ║   etcd retains 5 nodes and full quorum.                      ║
  ║   CASCADE PREVENTED AT STAGE 5.                              ║
  ╚══════════════════════════════════════════════════════════════╝
```

### Stage 6: Node Lease Expiry (Kubernetes Level)

```
METRIC: kube_node_status_condition{condition="Ready",status="true"}

  - alert: MassNodeNotReady
    expr: |
      count(kube_node_status_condition{condition="Ready",status="true"} == 0) > 10
    for: 1m
    labels:
      severity: critical
      automation: eviction_protection
    annotations:
      summary: "{{ $value }} nodes NotReady simultaneously"
      description: |
        More than 10 nodes are NotReady at the same time.
        This is likely a control plane issue (etcd/API server), 
        not individual node failures. Nodes may be healthy 
        but unable to renew leases.

  WHAT IT DETECTS: Mass NotReady events that indicate a 
  control plane problem rather than actual node failures.
  10+ nodes going NotReady simultaneously is almost 
  NEVER individual node failures — it's always a 
  control plane issue.

  AUTOMATED RESPONSE:
    → IMMEDIATELY increase pod-eviction-timeout to 60m:
      
      # Patch kube-controller-manager to prevent 
      # mass pod eviction:
      kubectl patch ... --pod-eviction-timeout=60m
      
    → Page on-call with CRITICAL alert.
    → Automated investigation:
      → Check etcd health
      → Check API server health  
      → Check network connectivity between control plane 
        and worker nodes

  ╔══════════════════════════════════════════════════════════════╗
  ║   In the incident: this fires at ~14:03:00                   ║
  ║   (127 nodes NotReady). Automated eviction                   ║
  ║   timeout extension prevents pod evictions.                  ║
  ║   SRE has 60 minutes instead of 5 to fix                     ║
  ║   the underlying etcd problem.                               ║
  ║   EVICTION CASCADE PREVENTED AT STAGE 6.                     ║
  ╚══════════════════════════════════════════════════════════════╝
```

### Stage 7: Pod Eviction — Last Line of Defense

```
METRIC: kube_pod_status_reason{reason="Evicted"}
AND:    kube_controller_manager_taint_eviction_total

  - alert: MassPodEviction
    expr: |
      increase(kube_pod_status_reason{reason="Evicted"}[5m]) > 50
    for: 0s
    labels:
      severity: critical
      automation: eviction_halt
    annotations:
      summary: "{{ $value }} pods evicted in last 5 minutes"
      description: |
        Mass pod eviction in progress. This is the FINAL 
        stage of the cascade — healthy pods being killed 
        because their nodes were marked NotReady due to 
        control plane failure, NOT actual node failure.
        Immediate action required to stop the bleeding.

  WHAT IT DETECTS: If ALL previous stages failed to 
  prevent the cascade, this catches actual pod evictions 
  in progress. At this point, real user impact is 
  occurring — workloads are being terminated.

  AUTOMATED RESPONSE:
    → AUTO-ACTION 1: Stop kube-controller-manager 
      immediately (the nuclear option):
      
      # On all control plane nodes:
      mv /etc/kubernetes/manifests/kube-controller-manager.yaml \
         /etc/kubernetes/kube-controller-manager.yaml.disabled
      
      # This stops ALL evictions instantly. Yes, it stops 
      # all controllers. But at this point, the control 
      # plane is already broken — stopping it prevents 
      # further damage while SRE investigates.
      
    → AUTO-ACTION 2: Cordon all NotReady nodes to 
      prevent scheduler from adding MORE pods to them 
      if/when they recover mid-eviction:
      
      kubectl get nodes --field-selector spec.unschedulable!=true \
        -o name | xargs -I {} kubectl cordon {}
      # (This may fail if API server is unhealthy — 
      # that's fine, controller-manager stop is the 
      # primary defense.)

    → Page: INCIDENT COMMANDER. This is a P1.

  ╔══════════════════════════════════════════════════════════════╗
  ║   In the incident: this is the scenario we                   ║
  ║   NEVER want to reach. If Stages 1-6 all                     ║
  ║   failed and pods are being evicted, this                    ║
  ║   is the last automated defense before                       ║
  ║   widespread workload outage.                                ║
  ║                                                              ║
  ║   GOAL: This alert should NEVER fire. If it                  ║
  ║   does, the post-mortem must explain why all                 ║
  ║   6 prior stages failed to contain the                       ║
  ║   cascade.                                                   ║
  ╚══════════════════════════════════════════════════════════════╝
```

### Monitoring Dashboard: Complete Cascade View

```
DASHBOARD: "etcd Health & Cascade Risk"

╔═══════════════════════════════════════════════════════════════╗
║  PANEL 1: Disk Layer                                          ║
║  ╭──────────────────────────╮  ╭────────────────────────────╮ ║
║  │ WAL fsync p99            │  │ Disk IOPS (used/limit)     │ ║
║  │ [line graph, 1h]         │  │ [line graph + threshold]   │ ║
║  │ WARN: >10ms (yellow)     │  │ WARN: >80% (yellow)        │ ║
║  │ CRIT: >50ms (red)        │  │ CRIT: >95% (red)           │ ║
╚═══════════════════════════════════════════════════════════════╝
│                                                              │
│ PANEL 2: Raft Layer                                          │
│ ╔═══════════════════════════════════════════════════════════════╗
│ ║  │ Leader changes/10m       │  │ Raft term (current)        │ ║
│ ║  │ [counter graph]          │  │[counter, should be         │ ║
│ ║  │ CRIT: >2                 │  │  stable/slow-growing]      │ ║
│ ╚═══════════════════════════════════════════════════════════════╝
│                                                              │
│ PANEL 3: Commit Layer                                        │
│ ╔═══════════════════════════════════════════════════════════════╗
│ ║  │ Backend commit p99       │  │ Applied index delta        │ ║
│ ║  │[line graph]              │  │ (leader vs followers)      │ ║
│ ║  │ CRIT: >100ms             │  │ [per-node, gap = lag]      │ ║
│ ╚═══════════════════════════════════════════════════════════════╝
│                                                              │
│ PANEL 4: Capacity Layer                                      │
│ ╔═══════════════════════════════════════════════════════════════╗
│ ║  │ DB size / quota          │  │ WAL disk free %            │ ║
│ ║  │ [gauge, 8GB quota]       │  │ [per-node gauge]           │ ║
│ ║  │ WARN: >75%               │  │ CRIT: <20%                 │ ║
│ ╚═══════════════════════════════════════════════════════════════╝
│                                                              │
│ PANEL 5: Kubernetes Impact                                   │
│ ╔═══════════════════════════════════════════════════════════════╗
│ ║  │ Nodes NotReady           │  │ Pod evictions/5m           │ ║
│ ║  │ [counter]                │  │ [counter]                  │ ║
│ ║  │ CRIT: >10                │  │ CRIT: >50                  │ ║
│ ╚═══════════════════════════════════════════════════════════════╝
│                                                              │
│ PANEL 6: Write Rate                                          │
│ ╔═══════════════════════════════════════════════════════════════╗
│ ║  │ etcd writes/sec (total + by source: DaemonSet,           │ ║
│ ║  │ kubelet leases, user kubectl, controller-manager)        │ ║
│ ║  │ [stacked area graph showing write composition]           │ ║
│ ║  │ WARN: total > 60% of IOPS limit                          │ ║
│ ║  │ CRIT: total > 80% of IOPS limit                          │ ║
│ ║  │                                                          │ ║
│ ║  │ THIS PANEL WOULD HAVE SHOWN the DaemonSet                │ ║
│ ║  │ deployment as a sudden spike in the "controller-         │ ║
│ ║  │ manager" write source, instantly identifying the         │ ║
│ ║  │ trigger during the incident.                             │ ║
│ ╚═══════════════════════════════════════════════════════════════╝
╰──────────────────────────────────────────────────────────────╯
```

### Cascade Prevention Summary

```
  ╭────────┬─────────────────────┬──────────────────────────╮
  │ STAGE  │ ALERT               │ AUTOMATED RESPONSE       │
  ├────────┼─────────────────────┼──────────────────────────┤
  │   1    │ WAL fsync p99 >10ms │ WARN: page SRE           │
  │        │ IOPS > 80%          │ CRIT(50ms): auto IOPS↑   │
  │        │                     │ ◄── PREVENTS EVERYTHING  │
  ├────────┼─────────────────────┼──────────────────────────┤
  │   2    │ Leader changes >2   │ Auto IOPS↑ + pause       │
  │        │ in 10 min           │ non-critical controllers │
  │        │                     │ ◄── STOPS ELECTION STORM │
  ├────────┼─────────────────────┼──────────────────────────┤
  │   3    │ Commit p99 >100ms   │ Same as Stage 2 +        │
  │        │                     │ API rate limiting        │
  ├────────┼─────────────────────┼──────────────────────────┤
  │   4    │ API server etcd     │ All above + preemptive   │
  │        │ write p99 > 1s      │ eviction timeout increase│
  ├────────┼─────────────────────┼──────────────────────────┤
  │   5    │ DB >6GB or          │ Auto volume expand +     │
  │        │ disk <20% free      │ emergency compaction     │
  ├────────┼─────────────────────┼──────────────────────────┤
  │   6    │ >10 nodes NotReady  │ Auto eviction timeout    │
  │        │ simultaneously      │ → 60m + page on-call     │
  ├────────┼─────────────────────┼──────────────────────────┤
  │   7    │ >50 pods evicted    │ STOP controller-manager  │
  │        │ in 5 min            │ (nuclear) + P1 declared  │
  │        │                     │ ◄── LAST DEFENSE LINE    │
  ╰────────┴─────────────────────┴──────────────────────────╯

  DESIGN PRINCIPLE: Each stage's automation is designed 
  to make the NEXT stage's alert unnecessary. If Stage 1 
  fires and auto-increases IOPS, Stage 2 should never 
  fire. If Stage 2 fires (Stage 1 automation failed or 
  insufficient), its response should prevent Stage 3.

  In the incident timeline, Stage 1 alone at 14:00:30 
  would have resolved everything. The remaining 6 stages 
  exist because automation CAN fail: EBS API could be 
  slow, IOPS increase might not take effect immediately, 
  or the root cause might not be IOPS at all (e.g., 
  disk hardware failure where IOPS increase doesn't help).

  DEFENSE IN DEPTH: 7 independent detection points.
  Each catches a different failure mode. Each has an 
  automated response. The cascade must defeat ALL 7 
  to reach pod eviction.
```

