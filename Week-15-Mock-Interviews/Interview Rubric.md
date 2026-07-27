# Interview Rubric — System Design Mastery

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS RUBRIC, YOU WILL BE ABLE TO:                      ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Score any system design interview answer on a             ║
║      consistent, principal-grade rubric — not vibes            ║
║                                                                ║
║   2. Distinguish between "sounds good" and "would              ║
║      survive production" in every scoring dimension            ║
║                                                                ║
║   3. Self-assess mock interviews and identify the              ║
║      single highest-leverage improvement area                  ║
║                                                                ║
║   4. Give structured feedback that accelerates                 ║
║      improvement (not generic praise or criticism)             ║
║                                                                ║
║   5. Calibrate your answers against FAANG L5/L6 and            ║
║      Principal SRE expectations                                ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "More boxes on the diagram = better"          ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. Interviewers score depth on 2-3 critical paths,         ║
║   not component count. A 4-box diagram with correct              ║
║   trade-offs beats a 20-box diagram with hand-waving.            ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "I need to know the 'right answer'"           ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. There is no single right answer. There are              ║
║   defensible trade-offs with explicit reasoning.                 ║
║   "It depends on X" without naming X is worse than               ║
║   picking one option and defending it.                           ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Failure modes are bonus points"              ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. At L6+ and Principal SRE level, failure modes           ║
║   are REQUIRED. A design without failure analysis is             ║
║   incomplete — not "good enough with extras."                    ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Numbers don't matter in interviews"          ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. Back-of-envelope math is how you justify                ║
║   sharding, caching, and replication. "We'll shard"              ║
║   without calculating data size and QPS is a red flag.           ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Communication is separate from design"       ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. If the interviewer cannot follow your reasoning,        ║
║   the design doesn't exist. Clarity IS a technical skill.        ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Rubric Overview

```
╔════════════════════════════════════════════════════════════════════╗
║   SCORING SCALE (1–4 per dimension)                                ║
╟────────────────────────────────────────────────────────────────────╢
║   1 = Unacceptable    — Fundamental gaps; would fail in prod       ║
║   2 = Below Bar       — Partial understanding; major holes         ║
║   3 = Meets Bar       — Solid L5/L6 answer; hireable with gaps     ║
║   4 = Exceeds Bar     — Principal-grade; production-ready depth    ║
╠════════════════════════════════════════════════════════════════════╣
║   TOTAL SCORE: Sum of 8 dimensions (max 32)                        ║
║                                                                    ║
║   8–14  : Not ready — revisit fundamentals (Weeks 1–6)             ║
║   15–19 : Developing — focus on weakest 2 dimensions               ║
║   20–24 : Interview-ready — polish edge cases and math             ║
║   25–28 : Strong — L6 bar; refine communication pacing             ║
║   29–32 : Principal-grade — teach this rubric to others            ║
╚════════════════════════════════════════════════════════════════════╝
```

### The Eight Dimensions

| # | Dimension | Weight | What It Measures |
|---|-----------|--------|------------------|
| 1 | Requirements & Scope | 12.5% | Clarification, constraints, MVP vs future |
| 2 | Capacity Estimation | 12.5% | QPS, storage, bandwidth, growth |
| 3 | API & Data Model | 12.5% | Interfaces, schemas, access patterns |
| 4 | High-Level Architecture | 12.5% | Component diagram, data flow, critical path |
| 5 | Deep Dive | 12.5% | One path explored to production depth |
| 6 | Trade-offs & Alternatives | 12.5% | Why X over Y; what you gave up |
| 7 | Failure Modes & Reliability | 12.5% | What breaks, detection, mitigation |
| 8 | Communication & Structure | 12.5% | Pacing, clarity, interviewer collaboration |

---

## Dimension 1: Requirements & Scope

### What Interviewers Listen For

```
THE FIRST 5 MINUTES SET THE CEILING.

Strong candidates:
  → Ask 5–8 targeted clarifying questions
  → Propose explicit functional requirements (ranked)
  → Propose explicit non-functional requirements (with numbers)
  → Define MVP scope vs "nice to have"
  → State assumptions OUT LOUD and invite correction
  → Identify the hardest requirement (the design driver)

Weak candidates:
  → Jump to drawing boxes immediately
  → Assume requirements without stating them
  → Treat all features as equal priority
  → Ignore non-functional requirements until prompted
  → Design for 1 billion users when problem says 1 million
```

### Scoring Criteria

```
╔════════════════════════════════════════════════════════════════════╗
║   SCORE 1 — UNACCEPTABLE                                           ║
╟────────────────────────────────────────────────────────────────────╢
║   • No clarifying questions asked                                  ║
║   • Requirements invented without validation                       ║
║   • Scope undefined — designs everything or nothing                ║
║   • Misses obvious constraints (e.g., consistency for payments)    ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 2 — BELOW BAR                                              ║
╟────────────────────────────────────────────────────────────────────╢
║   • 1–2 generic questions ("How many users?")                      ║
║   • Functional requirements listed but not prioritized             ║
║   • Non-functional requirements vague ("needs to be fast")         ║
║   • Scope creep — designs features interviewer didn't ask for      ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 3 — MEETS BAR                                              ║
╟────────────────────────────────────────────────────────────────────╢
║   • 4–6 clarifying questions covering users, scale, latency        ║
║   • Functional requirements ranked (P0/P1/P2)                      ║
║   • At least 3 NFRs with targets (latency, availability, etc.)     ║
║   • Clear MVP boundary stated                                      ║
║   • Identifies 1 design driver ("feed read latency is P0")         ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 4 — EXCEEDS BAR                                            ║
╟────────────────────────────────────────────────────────────────────╢
║   • 6–10 precise questions that change the design                  ║
║   • Explicitly asks about read/write ratio, consistency model      ║
║   • NFRs quantified AND tied to user experience                    ║
║   • Proposes scope cuts with reasoning ("defer DMs to v2")         ║
║   • Names the constraint that eliminates naive solutions           ║
║   • Summarizes requirements back to interviewer for confirmation   ║
╚════════════════════════════════════════════════════════════════════╝
```

### Red Flags

- Designing Twitter DMs when asked for a news feed
- Assuming global scale when interviewer says "US only, 10M DAU"
- Ignoring mobile vs web differences when product is mobile-first
- Not asking about consistency requirements for financial systems

### Green Flags

- "Before I design, let me confirm the read/write ratio — is this read-heavy?"
- "I'll scope to home timeline generation; trending and search are out of scope unless you want them"
- "For payments, I'm assuming exactly-once delivery — correct me if that's wrong"

### Interviewer Probe Questions

```
If candidate skips requirements:
  "What are the top 3 things this system must do well?"
  "What's acceptable latency for [critical operation]?"
  "Are we optimizing for consistency or availability here?"
  "What can we defer to a v2?"

If candidate over-scopes:
  "If you had 25 minutes left, what would you cut?"
  "What's the minimum viable version you'd ship first?"
```

---

## Dimension 2: Capacity Estimation

### What Interviewers Listen For

```
BACK-OF-ENVELOPE MATH IS NOT OPTIONAL.

Strong candidates:
  → Start with DAU/MAU and derive QPS
  → Separate read QPS from write QPS
  → Calculate storage (raw + indexes + replicas)
  → Calculate bandwidth (egress is expensive)
  → Identify the bottleneck BEFORE designing around it
  → Sanity-check numbers ("1 PB/day seems high — let me recheck")

Weak candidates:
  → "We'll use a cache" without knowing miss rate impact
  → "We'll shard" without knowing shard count
  → Numbers off by 1000x without noticing
  → Skip estimation entirely
```

### The Estimation Template

```
STEP 1: USERS
  DAU = ___
  Peak concurrent = DAU × ___% = ___
  
STEP 2: OPERATIONS PER USER PER DAY
  Reads:  ___/user/day  →  ___/sec peak (× 2–3 for peak factor)
  Writes: ___/user/day  →  ___/sec peak
  
STEP 3: DATA SIZE
  Per-record size = ___ bytes
  Records/day = ___
  Daily growth = ___ GB/day
  5-year storage = ___ TB (× replication factor)
  
STEP 4: BANDWIDTH
  Egress per request = ___ KB
  Peak egress = ___ Gbps
  
STEP 5: BOTTLENECK IDENTIFICATION
  "At ___ QPS with ___ ms latency, we need ___ connections"
  "Storage growth of ___ TB/year requires sharding by ___"
```

### Scoring Criteria

```
╔══════════════════════════════════════════════════════════════════╗
║   SCORE 1 — UNACCEPTABLE                                         ║
╟──────────────────────────────────────────────────────────────────╢
║   • No estimation attempted                                      ║
║   • Numbers clearly impossible (1 trillion QPS for 1M users)     ║
║   • Cannot explain how they arrived at any number                ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 2 — BELOW BAR                                            ║
╟──────────────────────────────────────────────────────────────────╢
║   • Estimates only users, not operations                         ║
║   • Missing storage OR bandwidth calculation                     ║
║   • Arithmetic errors that change the design conclusion          ║
║   • No peak factor applied                                       ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 3 — MEETS BAR                                            ║
╟──────────────────────────────────────────────────────────────────╢
║   • Read and write QPS calculated with stated assumptions        ║
║   • Storage estimate with growth projection                      ║
║   • Identifies primary bottleneck                                ║
║   • Numbers are within 2× of reasonable                          ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 4 — EXCEEDS BAR                                          ║
╟──────────────────────────────────────────────────────────────────╢
║   • Full template: QPS, storage, bandwidth, memory               ║
║   • Separates hot path from cold path traffic                    ║
║   • Derives infrastructure sizing (shards, cache size, nodes)    ║
║   • Sanity-checks and corrects mid-calculation                   ║
║   • Connects math directly to design decisions                   ║
╚══════════════════════════════════════════════════════════════════╝
```

### Common Estimation Anchors

```
TYPICAL ASSUMPTIONS (state explicitly, adjust per problem):

  Peak factor:     2–3× average (3× for consumer, 2× for B2B)
  Read/write:      100:1 for feeds, 1:1 for chat, 10:1 for search
  Tweet size:      ~300 bytes metadata + 280 chars
  Photo:           2–5 MB original, 200 KB served
  Video bitrate:   2–5 Mbps (1080p), 0.5 Mbps (480p)
  DB row overhead: 2–5× raw data (indexes, WAL, replication)
  Cache hit ratio: 80–95% for hot content, 50% for long tail
```

---

## Dimension 3: API & Data Model

### What Interviewers Listen For

```
THE DATA MODEL DRIVES THE ARCHITECTURE.

Strong candidates:
  → Define 3–5 core API endpoints with request/response shapes
  → Choose data model based on access patterns (not familiarity)
  → Identify primary keys and partition keys explicitly
  → Discuss denormalization with justification
  → Mention indexing strategy for hot queries
  → Consider schema evolution

Weak candidates:
  → Vague "REST API" without endpoints
  → One giant table with no access pattern analysis
  → SQL vs NoSQL choice based on preference, not workload
  → No discussion of how data is queried vs how it's written
```

### Scoring Criteria

```
╔════════════════════════════════════════════════════════════════════╗
║   SCORE 1 — UNACCEPTABLE                                           ║
╟────────────────────────────────────────────────────────────────────╢
║   • No API definition                                              ║
║   • Data model doesn't support stated requirements                 ║
║   • Cannot explain how a core query is served                      ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 2 — BELOW BAR                                              ║
╟────────────────────────────────────────────────────────────────────╢
║   • APIs listed but incomplete (missing critical operations)       ║
║   • Data model is generic (users, posts, likes) without schema     ║
║   • Access patterns not connected to storage choice                ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 3 — MEETS BAR                                              ║
╟────────────────────────────────────────────────────────────────────╢
║   • Core APIs defined with key fields                              ║
║   • Data model supports read AND write paths                       ║
║   • Partition/shard key identified for scale                       ║
║   • At least one index or denormalization decision explained       ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 4 — EXCEEDS BAR                                            ║
╟────────────────────────────────────────────────────────────────────╢
║   • APIs cover happy path + pagination + error cases               ║
║   • Multiple storage engines chosen per access pattern             ║
║   • CQRS or materialized views where appropriate                   ║
║   • Schema migration strategy mentioned                            ║
║   • ID generation strategy (UUID, snowflake, auto-inc)             ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Dimension 4: High-Level Architecture

### What Interviewers Listen For

```
THE DIAGRAM IS A COMMUNICATION TOOL, NOT THE PRODUCT.

Strong candidates:
  → Draw 5–8 components maximum in first pass
  → Show data flow with numbered steps for critical path
  → Place load balancers, caches, and queues deliberately
  → Separate sync path from async path
  → Label each component with its responsibility (one line)
  → Explain the request lifecycle end-to-end

Weak candidates:
  → Kitchen-sink diagram with 20 unlabeled boxes
  → No clear entry point or data flow direction
  → Missing load balancer or cache without justification
  → All communication is sync HTTP with no async option
```

### Architecture Checklist

```
EVERY ARCHITECTURE SHOULD ADDRESS:

  [ ] Client → Edge (CDN, API gateway, rate limiting)
  [ ] Load balancing (L4 vs L7 choice stated)
  [ ] Application tier (stateless? how many?)
  [ ] Caching layer (what, where, TTL strategy)
  [ ] Primary storage (what, how sharded)
  [ ] Secondary storage (search, analytics, blob)
  [ ] Async processing (queue, stream, workers)
  [ ] External dependencies (3rd party APIs, payment rails)
```

### Scoring Criteria

```
╔══════════════════════════════════════════════════════════════════╗
║   SCORE 1 — UNACCEPTABLE                                         ║
╟──────────────────────────────────────────────────────────────────╢
║   • No coherent architecture — random components                 ║
║   • Critical path impossible (e.g., no storage for persistent    ║
║     data)                                                        ║
║   • Cannot walk through a single request                         ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 2 — BELOW BAR                                            ║
╟──────────────────────────────────────────────────────────────────╢
║   • Architecture exists but missing obvious components           ║
║   • No separation of concerns (monolith diagram)                 ║
║   • Data flow unclear or contradictory                           ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 3 — MEETS BAR                                            ║
╟──────────────────────────────────────────────────────────────────╢
║   • Clear component diagram with data flow                       ║
║   • Critical path walkable in 60 seconds                         ║
║   • Caching and async processing included where needed           ║
║   • Stateless app tier (or justified stateful)                   ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 4 — EXCEEDS BAR                                          ║
╟──────────────────────────────────────────────────────────────────╢
║   • Architecture directly driven by requirements and math        ║
║   • Multi-region or HA topology when NFRs require it             ║
║   • Sync/async split with clear boundaries                       ║
║   • Identifies what is on the critical latency path              ║
║   • Proactively simplifies ("we don't need X because Y")         ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Dimension 5: Deep Dive

### What Interviewers Listen For

```
THE DEEP DIVE IS WHERE HIRING DECISIONS ARE MADE.

Interviewers will say: "Let's dive deeper into [X]."
X is usually the hardest part of the problem.

Strong candidates:
  → Go 3–4 levels deep on ONE path
  → Discuss algorithms (fan-out on write vs read, consistent hash)
  → Discuss protocols (gRPC vs REST, WebSocket, long-polling)
  → Discuss storage internals (B-tree vs LSM, partition strategy)
  → Provide concrete configs (partition count, TTL, batch size)
  → Draw a second diagram for the deep dive component

Weak candidates:
  → Repeat the high-level diagram in more detail
  → "It uses a database" without schema or query discussion
  → Cannot go deeper when probed
  → Deep dive on the easy part (user registration) not the hard part
```

### Deep Dive Selection Guide

```
PROBLEM TYPE          →  EXPECTED DEEP DIVE
─────────────────────────────────────────────────────
Social feed           →  Fan-out on write vs read, ranking
Payment system        →  Idempotency, double-entry ledger, sagas
Distributed KV        →  Consistent hashing, replication, quorum
Kafka / streaming     →  Partitioning, consumer groups, ordering
Uber / ride matching  →  Geospatial indexing, dispatch algorithm
Search                →  Inverted index, ranking, crawling
Video (YouTube)       →  Transcoding pipeline, CDN, adaptive bitrate
Chat (WhatsApp)       →  Message ordering, delivery guarantees
```

### Scoring Criteria

```
╔════════════════════════════════════════════════════════════════════╗
║   SCORE 1 — UNACCEPTABLE                                           ║
╟────────────────────────────────────────────────────────────────────╢
║   • Cannot elaborate beyond high-level                             ║
║   • Deep dive contains factual errors                              ║
║   • Avoids the hard part when interviewer redirects                ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 2 — BELOW BAR                                              ║
╟────────────────────────────────────────────────────────────────────╢
║   • Surface-level detail (names a technology, no mechanics)        ║
║   • One level deep only                                            ║
║   • Algorithm chosen without complexity analysis                   ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 3 — MEETS BAR                                              ║
╟────────────────────────────────────────────────────────────────────╢
║   • 2–3 levels deep on the probed component                        ║
║   • Correct algorithm/approach for the problem                     ║
║   • Discusses at least one implementation detail                   ║
║   • Aware of scaling limits of chosen approach                     ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 4 — EXCEEDS BAR                                            ║
╟────────────────────────────────────────────────────────────────────╢
║   • Production-grade depth (configs, failure behavior, ops)        ║
║   • Compares 2+ approaches with complexity/ops trade-offs          ║
║   • Discusses edge cases (hot keys, split brain, poison msgs)      ║
║   • References real system behavior (Kafka rebalance, etc.)        ║
║   • Quantifies deep dive decisions with math                       ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Dimension 6: Trade-offs & Alternatives

### What Interviewers Listen For

```
"I'D USE KAFKA" IS NOT A TRADE-OFF.

Strong candidates:
  → For every major decision: "I chose X because Y; the cost is Z"
  → Proactively mention alternatives they rejected
  → Use CAP/PACELC framework when relevant (not as buzzword)
  → Acknowledge what their design does NOT do well
  → Discuss operational cost, not just technical elegance

Weak candidates:
  → Single solution presented as obvious
  → "We'll use microservices" without justification
  → Cannot name a downside of their own design
  → Flip-flop without reasoning when challenged
```

### Trade-off Framework

```
FOR EACH MAJOR DECISION, STATE:

  DECISION:     What you chose
  BECAUSE:      The requirement that drove it
  ALTERNATIVE:  What you rejected
  COST:         What you gave up
  WHEN TO FLIP: Condition that would change your mind

EXAMPLE (feed fan-out):

  DECISION:     Fan-out on write for normal users
  BECAUSE:      Read latency is P0; 95% of users have < 1000 friends
  ALTERNATIVE:  Fan-out on read (simpler writes)
  COST:         Write amplification; celebrity problem needs hybrid
  WHEN TO FLIP: If > 50% of users have 10K+ followers
```

### Scoring Criteria

```
╔══════════════════════════════════════════════════════════════════╗
║   SCORE 1 — UNACCEPTABLE                                         ║
╟──────────────────────────────────────────────────────────────────╢
║   • No alternatives considered                                   ║
║   • Decisions appear random or technology-driven                 ║
║   • Cannot defend choices when challenged                        ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 2 — BELOW BAR                                            ║
╟──────────────────────────────────────────────────────────────────╢
║   • Mentions one alternative but weak comparison                 ║
║   • Trade-offs are generic ("SQL is more consistent")            ║
║   • Defensive when challenged rather than reasoning              ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 3 — MEETS BAR                                            ║
╟──────────────────────────────────────────────────────────────────╢
║   • 2–3 major decisions with stated trade-offs                   ║
║   • Alternatives named with reasonable comparison                ║
║   • Acknowledges at least one weakness in own design             ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 4 — EXCEEDS BAR                                          ║
╟──────────────────────────────────────────────────────────────────╢
║   • Every major decision has explicit cost/benefit               ║
║   • Operational trade-offs included (complexity, staffing)       ║
║   • "When I'd flip" conditions stated                            ║
║   • Engages with interviewer pushback constructively             ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Dimension 7: Failure Modes & Reliability

### What Interviewers Listen For

```
PRODUCTION ENGINEERS ASK: "WHAT BREAKS FIRST?"

Strong candidates:
  → Name 3–5 specific failure modes unprompted
  → For each: detection method + mitigation + blast radius
  → Discuss graceful degradation ("if X fails, Y still works")
  → Mention monitoring, alerting, and SLOs
  → Discuss data loss scenarios and recovery
  → Include security failure modes (abuse, injection, auth bypass)

Weak candidates:
  → "We'll replicate for HA" without specifics
  → No failure modes mentioned until interviewer asks
  → "It won't fail" or "we'll add retries" as complete answer
  → No mention of monitoring or incident response
```

### Failure Mode Template

```
FAILURE:          [Specific thing that breaks]
SYMPTOM:          [What users/operators see]
DETECTION:        [Metric, alert, or probe]
BLAST RADIUS:     [What else is affected]
MITIGATION:       [Immediate + long-term fix]
PREVENTION:       [Design change to reduce likelihood]
```

### Scoring Criteria

```
╔══════════════════════════════════════════════════════════════════╗
║   SCORE 1 — UNACCEPTABLE                                         ║
╟──────────────────────────────────────────────────────────────────╢
║   • No failure analysis                                          ║
║   • Single point of failure in design without acknowledgment     ║
║   • "We'll handle it later" for critical failures                ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 2 — BELOW BAR                                            ║
╟──────────────────────────────────────────────────────────────────╢
║   • 1–2 generic failures ("database goes down")                  ║
║   • Mitigation is "restart" or "failover" without detail         ║
║   • No detection strategy                                        ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 3 — MEETS BAR                                            ║
╟──────────────────────────────────────────────────────────────────╢
║   • 3+ failure modes with mitigations                            ║
║   • At least one graceful degradation path                       ║
║   • Monitoring or alerting mentioned                             ║
║   • Discusses replication or redundancy for critical components  ║
╠══════════════════════════════════════════════════════════════════╣
║   SCORE 4 — EXCEEDS BAR                                          ║
╟──────────────────────────────────────────────────────────────────╢
║   • Failure modes are specific to THIS design (not generic)      ║
║   • Cascade analysis (failure A triggers failure B)              ║
║   • SLO/SLI targets stated with error budget reasoning           ║
║   • Disaster recovery and data durability addressed              ║
║   • Chaos/failure injection or game day mentioned                ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Dimension 8: Communication & Structure

### What Interviewers Listen For

```
YOU ARE DESIGNING WITH THE INTERVIEWER, NOT PRESENTING AT THEM.

Strong candidates:
  → Narrate thinking process out loud
  → Check in every 5–10 minutes ("Does this direction make sense?")
  → Structured progression: requirements → math → API → architecture → deep dive
  → Uses board/diagram effectively (labels, arrows, numbers)
  → Manages time ("I'll spend 5 more minutes on this, then move on")
  → Adapts when interviewer redirects

Weak candidates:
  → Silent for 5+ minutes while drawing
  → Monologue without pausing for input
  → Disorganized — jumps between topics randomly
  → Argues with interviewer instead of collaborating
  → Runs out of time with no deep dive attempted
```

### Time Management Template (45-minute interview)

```
╔════════════════════════════════════════════════════════════════════╗
║   MINUTE  0–5  │ Requirements clarification                        ║
║   MINUTE  5–10 │ Capacity estimation                               ║
║   MINUTE 10–15 │ API & data model                                  ║
║   MINUTE 15–25 │ High-level architecture                           ║
║   MINUTE 25–40 │ Deep dive (interviewer-directed)                  ║
║   MINUTE 40–45 │ Failure modes, wrap-up, questions                 ║
╠════════════════════════════════════════════════════════════════════╣
║   If behind at minute 20: skip to architecture, do abbreviated     ║
║   math. A complete architecture beats perfect estimation.          ║
║   If ahead at minute 30: proactively start failure modes.          ║
╚════════════════════════════════════════════════════════════════════╝
```

### Scoring Criteria

```
╔════════════════════════════════════════════════════════════════════╗
║   SCORE 1 — UNACCEPTABLE                                           ║
╟────────────────────────────────────────────────────────────────────╢
║   • Interviewer cannot follow reasoning                            ║
║   • Hostile or dismissive communication                            ║
║   • No structure — random topic jumping                            ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 2 — BELOW BAR                                              ║
╟────────────────────────────────────────────────────────────────────╢
║   • Long silent periods                                            ║
║   • Some structure but poor time management                        ║
║   • Doesn't respond to interviewer hints                           ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 3 — MEETS BAR                                              ║
╟────────────────────────────────────────────────────────────────────╢
║   • Clear narration throughout                                     ║
║   • Logical progression through rubric dimensions                  ║
║   • Responds to probes and redirects                               ║
║   • Reaches deep dive within time                                  ║
╠════════════════════════════════════════════════════════════════════╣
║   SCORE 4 — EXCEEDS BAR                                            ║
╟────────────────────────────────────────────────────────────────────╢
║   • Collaborative — treats interview as design review              ║
║   • Proactive time management with explicit checkpoints            ║
║   • Diagrams enhance (not replace) verbal explanation              ║
║   • Summarizes decisions at transitions                            ║
║   • Asks insightful questions back to interviewer                  ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Level Calibration Guide

### L4 (Entry Senior)

```
EXPECTED SCORE RANGE: 16–22

Bar:
  → Solid architecture for well-known problems
  → Correct but not deep on trade-offs
  → Failure modes when prompted, not proactive
  → Estimation within order of magnitude

Differentiator:
  → Can implement what they design
  → Clear communication
```

### L5 (Senior)

```
EXPECTED SCORE RANGE: 20–26

Bar:
  → Proactive requirements and estimation
  → Deep dive on one path with correct algorithm
  → 2–3 trade-offs articulated
  → 3+ failure modes unprompted

Differentiator:
  → Production experience shows (configs, ops, real failures)
  → Adapts design when interviewer adds constraints
```

### L6 (Staff)

```
EXPECTED SCORE RANGE: 24–29

Bar:
  → Requirements drive every decision
  → Math connected to infrastructure sizing
  → Deep dive with production-grade detail
  → Cascade failure analysis
  → Operational cost in trade-offs

Differentiator:
  → Teaches the interviewer something
  → Identifies non-obvious constraints
  → Multi-system interaction awareness
```

### Principal / L7

```
EXPECTED SCORE RANGE: 27–32

Bar:
  → All L6 criteria plus:
  → Organizational trade-offs (team structure, migration path)
  → Explicit "what I'd ship in v1 vs v2" with migration plan
  → Security and compliance woven in, not bolted on
  → Cost modeling (infra $, not just capacity)
  → References real postmortems and industry incidents

Differentiator:
  → Framework thinking — answer applies to problem class
  → Challenges the problem statement itself when appropriate
```

---

## Scoring Worksheet

```
╔═══════════════════════════════════════════════════════════════════╗
║   MOCK INTERVIEW SCORING SHEET                                    ║
╠═══════════════════════════════════════════════════════════════════╣
║   Candidate: _______________  Date: ___________                   ║
║   Problem:   _______________  Level:  ___________                 ║
║   Interviewer: _____________  Duration: _________                 ║
╠═══════════════════════════════════════════════════════════════════╣
║   Dimension                    │ Score (1-4) │ Notes              ║
║   ─────────────────────────────┼─────────────┼──────────────────  ║
║   1. Requirements & Scope        │             │                  ║
║   2. Capacity Estimation         │             │                  ║
║   3. API & Data Model            │             │                  ║
║   4. High-Level Architecture     │             │                  ║
║   5. Deep Dive                   │             │                  ║
║   6. Trade-offs & Alternatives   │             │                  ║
║   7. Failure Modes & Reliability │             │                  ║
║   8. Communication & Structure   │             │                  ║
║   ─────────────────────────────┼─────────────┼──────────────────  ║
║   TOTAL                          │    /32      │                  ║
╠═══════════════════════════════════════════════════════════════════╣
║   TOP STRENGTH: ___________________________________________       ║
║   TOP GAP:      ___________________________________________       ║
║   NEXT FOCUS:   ___________________________________________       ║
║   HIRE SIGNAL:  [ ] Strong Yes  [ ] Yes  [ ] Lean  [ ] No         ║
╚═══════════════════════════════════════════════════════════════════╝
```

---

## Interviewer Behavior Guide

### Do

```
✓ Let candidate drive for first 5 minutes
✓ Redirect to the hard part if they avoid it
✓ Add a constraint mid-interview ("now assume multi-region")
✓ Ask "what breaks first?" if they skip failure modes
✓ Take notes on specific quotes for feedback
✓ Leave 3–5 minutes for candidate questions
```

### Don't

```
✗ Lead the candidate to your preferred answer
✗ Interrupt during estimation (let them finish math)
✗ Penalize technology choices if well-defended
✗ Expect the same depth on every component
✗ Compare candidate to your company's internal design
✗ Rush the deep dive — that's the signal
```

### Constraint Injection Timing

```
MINUTE 15: "What if we need 99.99% availability?"
MINUTE 25: "A celebrity with 50M followers posts — what happens?"
MINUTE 30: "The cache layer fails completely — walk me through it"
MINUTE 35: "How would you migrate from the current monolith to this?"
```

---

## Self-Assessment Protocol

After each mock interview, answer these five questions:

```
1. Which dimension scored lowest? That is next week's focus.
2. Did I reach the deep dive before minute 30?
3. Did I state at least 3 failure modes without prompting?
4. Can I redo the estimation from memory in 3 minutes?
5. Would I trust this design in production for 1 year?
```

---

## Key Takeaways

```
1. Eight dimensions, 1–4 scale, max 32. Score consistently.
2. Requirements and estimation in the first 10 minutes set the ceiling.
3. Deep dive on the HARD part — that's where hiring decisions happen.
4. Trade-offs require naming what you gave up, not just what you chose.
5. Failure modes are required at L5+, not bonus material.
```

---

## Targeted Reading

```
→ "System Design Interview" (Alex Xu), Vol 1 & 2 — scoring calibration
→ DDIA Chapter 1 (reliability), Chapter 5 (replication), Chapter 6 (partitioning)
→ Google SRE Book, Ch 4 (SLOs) — for failure mode dimension
→ "Staff Engineer" (Will Larson), Ch 3 — for L6+ communication expectations
→ This curriculum: Week 9–14 system design modules for problem-specific depth
```

---

## Timed Interview OS (mandatory)

All Week-15 mocks must be run using [`../00-Curriculum/TIMED_INTERVIEW_OS.md`](../00-Curriculum/TIMED_INTERVIEW_OS.md).

### Communication scorecard hard gate

Score Communication (dimension 8) using the Pressure Communication drills scorecard:

| Dimension | Min for Staff pass |
|-----------|-------------------:|
| Structure | 3 |
| Brevity | 3 |
| Numbers | 3 |
| Interrupt recovery | 3 |
| Assumption checks | 3 |

**Rule:** Even if technical dimensions sum to Meets Bar, the mock is **Staff fail** if any communication dimension is below 3.

### Interviewer interrupt script (use ≥2 times per mock)

1. At minute 12: “Stop — why this data store?”  
2. At minute 25: “What fails first at 10x?”  
3. Anytime ramble >90s: “Headline only — then continue.”
