# Roadmap Completion Tracker

Last updated: 2026-07-06

This tracker exists to keep the curriculum complete without polluting topic
modules with process notes, self-review text, AI drafting artifacts, or meta
commentary.

Topic files should contain only topic-learning content:

```text
Allowed in modules:
  - concepts
  - mechanisms
  - diagrams
  - commands
  - examples
  - production patterns
  - failure modes
  - SRE diagnostics
  - scenario exercises
  - key takeaways
  - targeted reading

Not allowed in modules:
  - pre-flight compliance checks
  - self-critique blocks
  - AI process notes
  - draft/final commentary
  - quality-gate commentary
  - statements about what the author will or will not do
  - implementation notes about repo edits
```

---

## Current completed modules

```text
00-Curriculum/
  Handoff Doc.md
  Roadmap Completion Tracker.md

Week-01-Transport-Application-Protocols-DNS-CDN/
  TCP vs UDP.md
  HTTP-1.1-vs-HTTP-2-vs-HTTP-3.md
  REST vs GraphQL vs gRPC.md
  WebSockets.md
  DNS Resolution.md
  CDN Fundamentals.md

Week-02-Storage-Fundamentals/
  SQL Deep Dive.md
  NoSQL Taxonomy.md
  Caching Patterns.md

Week-03-Distributed-Systems-Theory/
  CAP Theorem.md
  Consistency Models.md
  Consistent Hashing.md

Week-04-Replication-Partitioning-Consensus/
  Replication Strategies.md
  Replication Strategies Worked Answers.md
  Sharding.md
  Sharding Worked Answers.md
  Consensus Raft.md

Week-05-Database-Internals/
  Cassandra Architecture.md
  Database Scaling Patterns.md
  The B-Tree, Slotted Pages, and MVCC Garbage Collection.md  [off-roadmap — consolidate or remove]

Week-06-Architecture-Patterns/
  Message Queues and Kafka.md

Week-08-Advanced-Patterns/
  Observability.md

Retention-Tests/
  Week-01.md
  Weeks-02-and-03.md
  Week-04.md
```

---

## Principal Engineer Audit (2026-07-06)

```text
OVERALL COMPLETION:     ~22 of ~80 planned modules (28%)
OVERALL QUALITY RATING: 7.5/10 as learning material (elite depth where present;
                        structurally inconsistent; large roadmap holes)

STRENGTHS (keep doing):
  - CDN Fundamentals is genuinely principal-grade: mechanisms, math, commands,
    failure modes, layered defenses, incident walkthrough
  - Week 2-4 core topics match CDN depth on average (2000-2800 lines each)
  - SRE scenarios are production-real, not interview trivia
  - Worked answers for Week 4 replication/sharding are excellent pedagogy

CRITICAL GAPS (fix first):
  [fixed 2026-07-06] HTTP module was buried inside TCP vs UDP.md with WRONG
    scenario answers (setup: request amplification; answers: QUIC firewall)
  [fixed 2026-07-06] Week 1 retention test was embedded in CDN Fundamentals.md
  [fixed 2026-07-06] Cassandra paste artifact; Kafka/Observability week mislabels
  [open] Weeks 7, 9-16 entirely missing (0 modules)
  [open] Week 6: 1 of 6 topics; Week 8: 1 of 6 topics
  [open] Week 5 worked answers referenced but not in repo
  [open] B-Tree module contradicts roadmap ("do not reintroduce")
  [open] "Wrong mental models" section in only 3 of 22 modules
  [open] No README / curriculum index / cross-module navigation
  [open] No labs, no runnable exercises (text-only limitation acknowledged)

TEMPLATE COMPLIANCE (12-section standard vs actual):
  Learning objectives:     ~95% of modules
  Wrong mental models:     ~15% of modules  ← biggest structural gap
  SRE diagnostic toolkit:  ~40% of modules
  Decision framework:      ~25% of modules
  Hands-on exercises:      ~70% of modules (commands, not runnable labs)
  Retention tests:         Weeks 1-4 only (partial)
```

---

## Immediate quality gates

```text
[done] Extract HTTP/1.1-2-3 from TCP vs UDP into standalone module
[done] Fix HTTP scenario answer mismatch (request amplification vs QUIC)
[done] Extract Week 1 retention test from CDN Fundamentals
[done] Add Wrong Mental Models to CDN Fundamentals
[done] Remove Cassandra paste artifact; fix week header mislabels
[todo] Add Wrong Mental Models to all Week 1-5 modules (CDN + HTTP done)
[todo] Remove or merge off-roadmap B-Tree module into SQL Deep Dive
[todo] Create Week 5 worked answers files (tracker claims they exist)
[todo] Add README curriculum index with completion percentages
[todo] Split Observability: extract SLOs/SLIs into separate Week 8 module
```

---

## 24-hour burn-down order

```text
Priority 0: Keep roadmap integrity
  - Do not reintroduce B-Tree/Page-Based Storage as a separate Week 5 module.
  - Do not put Kafka, Observability, or other future-week content inside Week 5.
  - Keep process notes inside 00-Curriculum, not topic modules.

Priority 1: Fix known completed-week gaps
  - [done] HTTP-1.1-vs-HTTP-2-vs-HTTP-3.md extracted from TCP vs UDP.md
  - [todo] Add Wrong Mental Models section to remaining Week 1-5 modules
  - [todo] Retrofit Week 5 worked answers (files missing from repo)

Priority 2: Complete Week 6
  - Event-Driven Architecture
  - Microservices Patterns
  - Saga Pattern
  - Circuit Breakers, Bulkheads, Timeouts, Retries, and Backpressure
  - Outbox Pattern and CDC
  - Retention Questions Week 6

Priority 3: Complete Week 7
  - Load Balancing Deep Dive
  - Rate Limiting Algorithms
  - Search Systems and Inverted Indexes
  - Unique ID Generation
  - Feature Flags and Progressive Delivery
  - Retention Questions Week 7

Priority 4: Complete Week 8
  - Clocks, Time, and Ordering
  - Lamport Clocks, Vector Clocks, and Causality
  - CRDTs and Conflict Resolution
  - Geospatial Systems
  - SLOs, SLIs, Error Budgets, and Alerting
  - Retention Questions Week 8

Priority 5: Complete Weeks 9-16 system designs, mock interviews, and final mastery artifacts.
```

---

## Known repo gaps

```text
Week-01-Transport-Application-Protocols-DNS-CDN/
  [present] TCP vs UDP.md
  [present] HTTP-1.1-vs-HTTP-2-vs-HTTP-3.md
  [todo] Wrong mental models on DNS, REST/gRPC, WebSockets, TCP

Week-05-Database-Internals/
  [missing] Cassandra Architecture Worked Answers.md
  [missing] Database Scaling Patterns Worked Answers.md
  [off-roadmap] The B-Tree, Slotted Pages, and MVCC Garbage Collection.md

Retention-Tests/
  [missing] Week-05.md
  [missing] Week-06.md, Week-07.md, Week-08.md

Week-07-Specialized-Components/
  [missing] entire week directory

Weeks 9-16:
  [missing] all system design, mock interview, and mastery modules
```

---

## Remaining roadmap

### Week 6: Architecture Patterns

```text
[done] Message Queues and Kafka
[todo] Event-Driven Architecture
[todo] Microservices Patterns
[todo] Saga Pattern
[todo] Circuit Breakers, Bulkheads, Timeouts, Retries, and Backpressure
[todo] Outbox Pattern and CDC
[todo] Retention Questions Week 6
```

### Week 7: Specialized Components

```text
[todo] Load Balancing Deep Dive
[todo] Rate Limiting Algorithms
[todo] Search Systems and Inverted Indexes
[todo] Unique ID Generation
[todo] Feature Flags and Progressive Delivery
[todo] Retention Questions Week 7
```

### Week 8: Advanced Distributed Patterns and Observability

```text
[todo] Clocks, Time, and Ordering
[todo] Lamport Clocks, Vector Clocks, and Causality
[todo] CRDTs and Conflict Resolution
[todo] Geospatial Systems
[done] Monitoring and Observability
[todo] SLOs, SLIs, Error Budgets, and Alerting
[todo] Retention Questions Week 8
```

### Week 9: Feed and Chat System Designs

```text
[todo] Design WhatsApp
[todo] Design Twitter Feed
[todo] Compound Scenario: Social Platform Meltdown
```

### Week 10: Media and Mobility System Designs

```text
[todo] Design YouTube
[todo] Design Uber
[todo] Compound Scenario: Global Video Outage
```

### Week 11: Commerce and Payments System Designs

```text
[todo] Design Payment System
[todo] Design E-Commerce Platform
[todo] Compound Scenario: Payment Data Loss
```

### Week 12: Search and Crawling System Designs

```text
[todo] Design Google Search
[todo] Design Web Crawler
[todo] Compound Scenario: Search Index Corruption
```

### Week 13: Infrastructure System Designs

```text
[todo] Design Distributed Key-Value Store
[todo] Design Kafka
[todo] Design Configuration Store
[todo] Compound Scenario: Consensus and Data Loss
```

### Week 14: Collaboration and AI System Designs

```text
[todo] Design Google Docs
[todo] Design LLM Serving Platform
[todo] Design Feature Store
[todo] Compound Scenario: Realtime Collaboration Outage
```

### Week 15: Mock Interviews

```text
[todo] Interview Rubric
[todo] Mock Interview 01: Social Feed
[todo] Mock Interview 02: Payment System
[todo] Mock Interview 03: Distributed KV Store
[todo] Mock Interview 04: Kafka
[todo] Mock Interview 05: Uber
[todo] Feedback Patterns
```

### Week 16: Final Mastery

```text
[todo] Final Retention Test: All Topics
[todo] Principal SRE System Design Checklist
[todo] Architecture Review Checklist
[todo] Incident Review Checklist
[todo] Production Readiness Checklist
[todo] Final Capstone Scenario
```

---

## Topic file standard

Each future topic should follow this content structure:

```text
1. Learning objectives
2. Wrong mental models
3. Core teaching
4. Concrete examples
5. Production patterns
6. Failure modes
7. SRE diagnostic toolkit
8. Decision framework
9. Incident scenario
10. Expert answer or analysis
11. Key takeaways
12. Targeted reading
```

ASCII diagrams should be clean and topic-focused:

```text
+---------+      +---------+      +---------+
| Source  | ---> | System  | ---> | Sink    |
+---------+      +---------+      +---------+
```

Diagrams should not be decorative. Each one should teach a single mechanism.

---

## Completion rule

A module is complete only when it is topic-only, technically accurate, diagrammed
cleanly, and deep enough to be useful during both system-design interviews and
production incident reviews.
