# Distributed Systems & System Design Mastery

A structured, production-grade curriculum for distributed systems and system design.
Depth target: principal engineer / staff SRE — not surface-level interview prep.

**Status (2026-07-06):** ~28% of planned modules complete. Weeks 1–5 are largely
written; Weeks 6–8 are partial; Weeks 7 and 9–16 are not started.

---

## How to Use This Repo

1. Read modules in week order — topics chain intentionally (TCP HOL → HTTP/2 → HTTP/3 → CDN).
2. Each module: learn the full teaching section before opening retention tests.
3. Worked answer files are for self-check after attempting scenarios yourself.
4. Process notes live in `00-Curriculum/` only — topic files are learning content.

### Topic File Standard (12 sections)

| # | Section | Purpose |
|---|---------|---------|
| 1 | Learning objectives | What you can do after |
| 2 | Wrong mental models | Destroy misconceptions first |
| 3 | Core teaching | Mechanisms, diagrams, math |
| 4 | Concrete examples | Real systems, real configs |
| 5 | Production patterns | How teams actually ship this |
| 6 | Failure modes | What breaks in prod |
| 7 | SRE diagnostic toolkit | Commands, metrics, log patterns |
| 8 | Decision framework | When to use X vs Y |
| 9 | Incident scenario | Multi-symptom, no hand-holding |
| 10 | Expert analysis | Full worked response |
| 11 | Key takeaways | 5 bullets max |
| 12 | Targeted reading | Specific pages, not "read DDIA" |

**Gold standard reference:** `Week-01-.../CDN Fundamentals.md`

---

## Curriculum Map

### Week 1: Transport, Protocols, DNS, CDN — **Complete**

| Module | Lines | Status |
|--------|------:|--------|
| [TCP vs UDP](Week-01-Transport-Application-Protocols-DNS-CDN/TCP%20vs%20UDP.md) | ~880 | ✓ |
| [HTTP/1.1 vs HTTP/2 vs HTTP/3](Week-01-Transport-Application-Protocols-DNS-CDN/HTTP-1.1-vs-HTTP-2-vs-HTTP-3.md) | ~970 | ✓ |
| [REST vs GraphQL vs gRPC](Week-01-Transport-Application-Protocols-DNS-CDN/REST%20vs%20GraphQL%20vs%20gRPC.md) | ~2140 | ✓ |
| [WebSockets](Week-01-Transport-Application-Protocols-DNS-CDN/WebSockets.md) | ~2220 | ✓ |
| [DNS Resolution](Week-01-Transport-Application-Protocols-DNS-CDN/DNS%20Resolution.md) | ~2330 | ✓ |
| [CDN Fundamentals](Week-01-Transport-Application-Protocols-DNS-CDN/CDN%20Fundamentals.md) | ~2270 | ✓ |
| [Retention Test](Retention-Tests/Week-01.md) | ~775 | ✓ |

### Week 2: Storage Fundamentals — **Complete**

| Module | Status |
|--------|--------|
| [SQL Deep Dive](Week-02-Storage-Fundamentals/SQL%20Deep%20Dive.md) (+ Appendix A: Postgres storage internals) | ✓ |
| [NoSQL Taxonomy](Week-02-Storage-Fundamentals/NoSQL%20Taxonomy.md) | ✓ |
| [Caching Patterns](Week-02-Storage-Fundamentals/Caching%20Patterns.md) | ✓ |
| [Retention Test](Retention-Tests/Weeks-02-and-03.md) | ✓ (combined w/ W3) |

### Week 3: Distributed Systems Theory — **Complete**

| Module | Status |
|--------|--------|
| [CAP Theorem](Week-03-Distributed-Systems-Theory/CAP%20Theorem.md) | ✓ |
| [Consistency Models](Week-03-Distributed-Systems-Theory/Consistency%20Models.md) | ✓ |
| [Consistent Hashing](Week-03-Distributed-Systems-Theory/Consistent%20Hashing.md) | ✓ |

### Week 4: Replication, Partitioning, Consensus — **Complete**

| Module | Status |
|--------|--------|
| [Replication Strategies](Week-04-Replication-Partitioning-Consensus/Replication%20Strategies.md) | ✓ |
| [Replication Worked Answers](Week-04-Replication-Partitioning-Consensus/Replication%20Strategies%20Worked%20Answers.md) | ✓ |
| [Sharding](Week-04-Replication-Partitioning-Consensus/Sharding.md) | ✓ |
| [Sharding Worked Answers](Week-04-Replication-Partitioning-Consensus/Sharding%20Worked%20Answers.md) | ✓ |
| [Consensus (Raft)](Week-04-Replication-Partitioning-Consensus/Consensus%20Raft.md) | ✓ |
| [Retention Test](Retention-Tests/Week-04.md) | ✓ |

### Week 5: Database Internals — **Partial**

| Module | Status |
|--------|--------|
| [Cassandra Architecture](Week-05-Database-Internals/Cassandra%20Architecture.md) | ✓ |
| [Database Scaling Patterns](Week-05-Database-Internals/Database%20Scaling%20Patterns.md) | ✓ |
| B-Tree / MVCC deep dive | ➜ merged into Week 2 SQL Deep Dive Appendix A |
| Worked answers | ✗ missing |
| Retention test | ✗ missing |

### Week 6: Architecture Patterns — **~17%**

| Module | Status |
|--------|--------|
| [Message Queues and Kafka](Week-06-Architecture-Patterns/Message%20Queues%20and%20Kafka.md) | ✓ |
| Event-Driven Architecture | ✗ |
| Microservices / Saga / Circuit Breaker | ✗ |
| Outbox / CDC | ✗ |

### Week 7: Specialized Components — **0%**

All modules missing.

### Week 8: Advanced Patterns — **~17%**

| Module | Status |
|--------|--------|
| [Observability](Week-08-Advanced-Patterns/Observability.md) | ✓ (includes SLOs) |
| Clocks / Lamport / Vector / CRDTs / Geospatial | ✗ |

### Weeks 9–16: System Designs, Mocks, Mastery — **0%**

---

## Meta / Process

- [Handoff Doc](00-Curriculum/Handoff%20Doc.md) — learner profile, scores, growth areas
- [Roadmap Completion Tracker](00-Curriculum/Roadmap%20Completion%20Tracker.md) — gaps, audit, burn-down

---

## Reading Spine

Primary: *Designing Data-Intensive Applications* (Kleppmann) — specific chapter pages
are cited per module, not generically.
