# Roadmap Completion Tracker

Last updated: 2026-05-15

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
  Sharding.md
  Consensus Raft.md

Week-05-Database-Internals/
  Cassandra Architecture.md
  Database Scaling Patterns.md

Week-06-Architecture-Patterns/
  Message Queues and Kafka.md
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
[todo] Monitoring and Observability
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
