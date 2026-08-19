# System Design & Distributed Systems Engineering — Master Knowledge Base

> **Audience Gate:** Recommended for engineers with ~3+ years of backend, distributed systems, or SRE experience. Designed as an operational reference, architectural blueprint, and deep theoretical curriculum.

---

## 📚 Core Navigation & Meta Curriculum

- [Learning Path & Study Rules](00-Curriculum/LEARNING_PATH.md) — Spaced retention mix, tier gates (Foundation → Staff → Principal), and study protocol.
- [Module Contract V2](00-Curriculum/MODULE_CONTRACT_V2.md) — Technical depth standards and teaching structure required across all modules.
- [Quality Rubric](00-Curriculum/QUALITY_RUBRIC.md) — Grading criteria for incident diagnosis, tradeoff analysis, and capacity math.
- [Roadmap Completion Tracker](00-Curriculum/Roadmap%20Completion%20Tracker.md) — Progress tracking across all 16 weeks.

---

## 🗺️ 16-Week Curriculum Map

### **Foundations (Weeks 01 – 04)**

#### [Week 01: Transport, Application Protocols, DNS & CDN](Week-01-Transport-Application-Protocols-DNS-CDN/)
- [TCP vs UDP](Week-01-Transport-Application-Protocols-DNS-CDN/TCP%20vs%20UDP.md) — Sequence numbers, flow control, TIME_WAIT exhaustion, sysctl tuning.
- [HTTP/1.1 vs HTTP/2 vs HTTP/3](Week-01-Transport-Application-Protocols-DNS-CDN/HTTP-1.1-vs-HTTP-2-vs-HTTP-3.md) — Multiplexing, HOL blocking, QUIC transport, connection migration.
- [DNS Resolution](Week-01-Transport-Application-Protocols-DNS-CDN/DNS%20Resolution.md) — Recursion, TTL caching, Anycast routing, GEO-DNS, EDNS client subnet.
- [CDN Fundamentals](Week-01-Transport-Application-Protocols-DNS-CDN/CDN%20Fundamentals.md) — Edge caching, origin shield, cache invalidation, cache stampede mitigation.
- [REST vs GraphQL vs gRPC](Week-01-Transport-Application-Protocols-DNS-CDN/REST%20vs%20GraphQL%20vs%20gRPC.md) — Protocol buffers, schema governance, N+1 query problem, HTTP/2 streaming.
- [WebSockets](Week-01-Transport-Application-Protocols-DNS-CDN/WebSockets.md) — Upgrade handshake, stateful connection scaling, ping/pong frames, edge proxies.
- [Cloud-Native Networking: Envoy, eBPF & Overlay Networks](Week-01-Transport-Application-Protocols-DNS-CDN/Cloud-Native%20Networking%20Envoy%20eBPF%20and%20Overlay%20Networks.md) — xDS control plane, mTLS CPU tax, Cilium eBPF kernel bypass, VXLAN MTU overhead.

#### [Week 02: Storage Fundamentals](Week-02-Storage-Fundamentals/)
- [SQL Deep Dive](Week-02-Storage-Fundamentals/SQL%20Deep%20Dive.md) — B-Trees vs LSM-Trees, MVCC, isolation levels (Read Committed to Serializable), EXPLAIN ANALYZE.
- [Hardware Bounds: NVMe, PCIe, NUMA & Cache Contention](Week-02-Storage-Fundamentals/Hardware%20Bounds%20NVMe%20PCIe%20NUMA%20and%20Cache%20Contention.md) — Flash IOPS saturation, PCIe 4.0/5.0 lane math, NUMA bus contention, L1-L3 cache bouncing.

#### [Week 03: Distributed Systems Theory](Week-03-Distributed-Systems-Theory/)
- [CAP Theorem & PACELC](Week-03-Distributed-Systems-Theory/CAP%20Theorem.md) — Proof mechanics, linearizability, PACELC latency/consistency tradeoffs under health vs partition.
- [Consistency Models](Week-03-Distributed-Systems-Theory/Consistency%20Models.md) — Strict, Linearizable, Sequential, Causal, Eventual consistency bounds.
- [Consistent Hashing](Week-03-Distributed-Systems-Theory/Consistent%20Hashing.md) — Ring topology, virtual nodes, bounded loads, partition rebalancing algorithms.
- [Formal Verification: TLA+, Jepsen & DST](Week-03-Distributed-Systems-Theory/Formal%20Verification%20TLA%20Plus%20Jepsen%20and%20DST.md) — TLA+ safety/liveness specifications, Jepsen fault injection, Deterministic Simulation Testing (DST).

#### [Week 04: Replication, Partitioning & Consensus](Week-04-Replication-Partitioning-Consensus/)
- [Replication Strategies](Week-04-Replication-Partitioning-Consensus/Replication%20Strategies.md) — Single-leader, multi-leader, leaderless (Dynamo-style), replication lag, split-brain.
- [Sharding](Week-04-Replication-Partitioning-Consensus/Sharding.md) — Key-based, range-based, directory-based sharding, hot key mitigation, resharding strategies.
- [Consensus Raft](Week-04-Replication-Partitioning-Consensus/Consensus%20Raft.md) — Leader election, log replication, joint consensus configuration changes, safety invariants.

---

### **Architecture Patterns & Internals (Weeks 05 – 08c)**

#### [Week 05: Database Internals](Week-05-Database-Internals/)
- [Cassandra Architecture](Week-05-Database-Internals/Cassandra%20Architecture.md) — Memtables, SSTables, Bloom filters, compaction strategies, hint handoff.
- [Database Scaling Patterns](Week-05-Database-Internals/Database%20Scaling%20Patterns.md) — Read replicas, connection pooling (PgBouncer), CQRS, materialized views.

#### [Week 06: Architecture Patterns](Week-06-Architecture-Patterns/)
- [Event-Driven Architecture](Week-06-Architecture-Patterns/Event-Driven%20Architecture.md) — Event notification, event-carried state transfer, event sourcing.
- [Message Queues and Kafka](Week-06-Architecture-Patterns/Message%20Queues%20and%20Kafka.md) — Partition logs, consumer groups, offset management, exactly-once semantics.
- [Microservices Patterns](Week-06-Architecture-Patterns/Microservices%20Patterns.md) — Service boundary decomposition, API gateway, BFF pattern.
- [Outbox Pattern and CDC](Week-06-Architecture-Patterns/Outbox%20Pattern%20and%20CDC.md) — Transactional outbox, Debezium CDC, WAL tailing.
- [Saga Pattern](Week-06-Architecture-Patterns/Saga%20Pattern.md) — Orchestration vs Choreography, compensation state machines, forward recovery.
- [Resilience: Circuit Breakers, Bulkheads, Timeouts, Retries](Week-06-Architecture-Patterns/Circuit%20Breakers%20Bulkheads%20Timeouts%20Retries%20and%20Backpressure.md) — Cascading failure mitigation, exponential backoff, jitter, load shedding.

#### [Week 07: Specialized Components](Week-07-Specialized-Components/)
- [Load Balancing Deep Dive](Week-07-Specialized-Components/Load%20Balancing%20Deep%20Dive.md) — L4 vs L7 balancing, Maglev, ECMP, health checks, connection draining.
- [Rate Limiting Algorithms](Week-07-Specialized-Components/Rate%20Limiting%20Algorithms.md) — Token bucket, leaky bucket, sliding window counter, distributed Redis limiters.
- [Search Systems and Inverted Indexes](Week-07-Specialized-Components/Search%20Systems%20and%20Inverted%20Indexes.md) — Lucene index structure, TF-IDF / BM25, postings list compression, Elias-Fano & WAND pruning.
- [Vector Databases](Week-07-Specialized-Components/Vector%20Databases%20HNSW%20IVF-PQ%20and%20Semantic%20Search.md) — HNSW graphs, IVF-PQ product quantization, SIMD AVX-512 distance math, semantic search architectures.
- [Unique ID Generation](Week-07-Specialized-Components/Unique%20ID%20Generation.md) — Snowflake IDs, UUID v4/v7, ticket servers, monotonic clock dependencies.
- [Feature Flags and Progressive Delivery](Week-07-Specialized-Components/Feature%20Flags%20and%20Progressive%20Delivery.md) — Context evaluation, dark launches, canary rollouts, kill switches.

#### [Week 08: Advanced Patterns](Week-08-Advanced-Patterns/)
- [Clocks, Time and Ordering](Week-08-Advanced-Patterns/Clocks%20Time%20and%20Ordering.md) — Physical vs Logical time, NTP drift, TrueTime (Google Spanner), bounded uncertainty.
- [Lamport Clocks, Vector Clocks & Causality](Week-08-Advanced-Patterns/Lamport%20Clocks%20Vector%20Clocks%20and%20Causality.md) — Causal ordering, partial order graphs, vector clock size bloat.
- [CRDTs and Conflict Resolution](Week-08-Advanced-Patterns/CRDTs%20and%20Conflict%20Resolution.md) — State-based (CvRDT) vs Operation-based (CmRDT), LWW-Element-Set, PN-Counters.
- [Geospatial Systems](Week-08-Advanced-Patterns/Geospatial%20Systems.md) — Geohash, S2 geometry, Quadtrees, spatial indexing, k-NN queries.
- [Observability](Week-08-Advanced-Patterns/Observability.md) — Metrics (Prometheus), Distributed Tracing (OpenTelemetry), Structured Logging, trace context propagation.
- [eBPF Observability & Continuous Profiling](Week-08-Advanced-Patterns/eBPF%20Observability%20Off-CPU%20Profiling%20and%20Flame%20Graphs.md) — Off-CPU latency profiling, kernel tracepoints, continuous flame graphs, Parca/Pyroscope architecture.
- [SLOs, SLIs, Error Budgets & Alerting](Week-08-Advanced-Patterns/SLOs%20SLIs%20Error%20Budgets%20and%20Alerting.md) — Multi-window multi-burn-rate alerts, SLA math, error budget policy.

#### [Week 08b: Trust, Cost & Multi-Tenancy](Week-08b-Trust-Cost-Multi-Tenancy/)
- [AuthN, AuthZ, OAuth, mTLS & Secrets](Week-08b-Trust-Cost-Multi-Tenancy/AuthN%20AuthZ%20OAuth%20mTLS%20and%20Secrets.md) — JWT validation, RBAC/ABAC (SpiceDB/OPA), OAuth2 PKCE, secrets rotation.
- [Cost, Capacity & FinOps](Week-08b-Trust-Cost-Multi-Tenancy/Cost%20Capacity%20and%20FinOps.md) — Unit economics, egress cost optimization, reserved instance sizing, storage tiering.
- [Multi-Tenancy Isolation & Noisy Neighbor](Week-08b-Trust-Cost-Multi-Tenancy/Multi-Tenancy%20Isolation%20and%20Noisy%20Neighbor.md) — Pool vs Silo architecture, fair queuing, tenant quota enforcement.

#### [Week 08c: Operations Hardening](Week-08c-Operations-Hardening/)
- [Migration and Cutover](Week-08c-Operations-Hardening/Migration%20and%20Cutover.md) — Dual-writing, shadow traffic, backfill pipelines, rollback safety checks.
- [Testing Distributed Systems](Week-08c-Operations-Hardening/Testing%20Distributed%20Systems.md) — Chaos engineering, fault injection, shadow testing, synthetic monitoring.
- [Abuse, Bots & Fraud Defense](Week-08c-Operations-Hardening/Abuse%20Bots%20and%20Fraud%20Defense.md) — CAPTCHA challenges, IP reputation scoring, device fingerprinting, velocity tracking.
- [Client Offline & Edge Resilience](Week-08c-Operations-Hardening/Client%20Offline%20and%20Edge%20Resilience.md) — Offline-first local storage, optimistic UI updates, background sync queue.

---

### **System Design Case Studies (Weeks 09 – 14)**

- [Week 09: Twitter Feed & WhatsApp](Week-09-Feed-and-Chat-Designs/) — Fan-out on write vs read, timeline caching, WebSocket gateway, end-to-end encryption.
- [Week 10: YouTube & Uber](Week-10-Media-and-Mobility-Designs/) — Chunked video transcoding, CDN origin shield, Quadtree location indexing, driver matching.
- [Week 11: Payment System & E-Commerce](Week-11-Commerce-and-Payments-Designs/) — Double-entry accounting ledger, Stripe-grade idempotency keys, PCI SAQ A scope, checkout saga.
- [Week 12: Search Engine & Web Crawler](Week-12-Search-and-Crawling-Designs/) — Distributed crawler frontier, robots.txt parser, PageRank calculation, inverted index sharding.
- [Week 13: Distributed KV Store, Kafka & Config Store](Week-13-Infrastructure-Designs/) — Dynamo-style LSM KV store, partition log broker, etcd linearizable config watch.
- [Week 14: Collaborative Docs, LLM Serving & Feature Store](Week-14-Collaboration-and-AI-Designs/) — OT/CRDT real-time text edit, vLLM PagedAttention GPU inference, offline/online ML feature store.

---

### **Evaluation, Mocks & Final Mastery (Weeks 15 – 16)**

- [Week 15: Mock Interviews](Week-15-Mock-Interviews/) — Timed interview prompts, scoring rubric, and feedback checklists.
- [Week 16: Final Mastery & Checklists](Week-16-Final-Mastery/) — Architecture review checklist, production readiness checklist, and capstone incident scenario.

---

## 🎯 How to Use This Knowledge Base

1. **For Incident Response & On-Call:** Jump directly to the relevant **Wrong Mental Models** and **Production Failure Patterns** sections in each topic file.
2. **For System Design Preparation:** Review the functional/non-functional requirements, capacity math, state diagrams, and DB schema designs in Weeks 09 through 14.
3. **For Architectural Design Reviews:** Consult the checklists in [Week 16](Week-16-Final-Mastery/Production%20Readiness%20Checklist.md) alongside the resilience and hardware bounds modules.
