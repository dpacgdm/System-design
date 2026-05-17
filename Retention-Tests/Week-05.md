# Retention Test — Week 05 Database Internals

This test is the skipped Week 5 gate. It covers Weeks 1-5 with emphasis on Cassandra Architecture and Database Scaling Patterns, plus a compound scenario that forces Week 4 consensus/replication reasoning together with Week 5 storage-internals reasoning.

---

## How to take this test

```text
Target mode: closed notes
Time box: 45-60 minutes
Goal: explain mechanisms, tradeoffs, and failure chains, not recite definitions
Passing bar: answers should be operationally useful during an incident or design review
Principal bar: answers include assumptions, invariants, safe mitigations, and what evidence would change the decision
```

For each answer, prefer this structure:

```text
1. Mechanism
2. Failure mode
3. Detection signal
4. Safe action
5. Tradeoff / caveat
```

---

## Part 1 — Rapid Fire Across Weeks 1-5

### 1. TCP vs UDP

A payment API uses TCP, while a metrics sidecar exports some telemetry over UDP. Explain why TCP is preferred for payment APIs and why UDP can be acceptable for telemetry. Include what each protocol does or does not guarantee.

### 2. HTTP versions

Explain the operational difference between HTTP/1.1, HTTP/2, and HTTP/3 from an SRE perspective. Include head-of-line blocking, multiplexing, TLS/QUIC, and what can go wrong during CDN or load-balancer migrations.

### 3. DNS resolution

A service migration changes an ALB DNS record with a 300-second TTL. Some users still hit the old region after the change. Explain why this happens, where caching occurs, and how you would safely plan a cutover.

### 4. CDN fundamentals

A product image is stale for 20 minutes after a deploy, but the origin has the correct file. Explain the caching layers that could be involved and how cache-control headers, surrogate keys, and invalidations affect recovery.

### 5. REST vs GraphQL vs gRPC

Compare REST, GraphQL, and gRPC for internal service-to-service APIs. Include schema evolution, observability, load balancing, client generation, and failure modes.

### 6. WebSockets

A chat service uses WebSockets. Explain why scaling it is different from stateless HTTP. Include sticky sessions, connection state, backpressure, load balancers, and reconnect storms.

### 7. SQL vs NoSQL

A team wants to move order storage from PostgreSQL to a NoSQL database because traffic increased. What questions must you ask before agreeing? Include transactions, query patterns, consistency, indexing, operational maturity, and migration risk.

### 8. Caching patterns

Explain cache-aside, write-through, write-behind, and read-through. For each, name one failure mode and one situation where it is appropriate.

### 9. CAP theorem

During a network partition, a distributed database must choose behavior. Explain CP vs AP using a concrete example, and explain why CAP is not a menu of three independent properties.

### 10. Consistency models

Explain strong consistency, eventual consistency, read-your-writes, monotonic reads, and causal consistency. Give one user-visible bug caused by violating each model.

### 11. Consistent hashing

Why does consistent hashing reduce key movement during cluster resize? Explain virtual nodes and the operational problem they solve.

### 12. Replication strategies

Compare leader-follower replication, multi-leader replication, and leaderless/quorum replication. Include write availability, conflict handling, read freshness, and failure recovery.

### 13. Sharding

A single PostgreSQL table grows to 20 TB. Explain the difference between vertical partitioning, horizontal sharding, range sharding, hash sharding, and directory-based sharding. What goes wrong during resharding?

### 14. Raft consensus

A Raft cluster has 5 nodes and loses 2. Can it still make progress? What if it loses 3? Explain quorum, leader election, committed entries, and why split-brain protection matters.

### 15. Cassandra write path

Trace a Cassandra write from client request to durable storage. Include coordinator, partitioner, replicas, commit log, memtable, SSTable, and consistency level.

### 16. Cassandra read path

Trace a Cassandra read. Include coordinator, bloom filter, partition index, memtable, SSTables, read repair, digest reads, and consistency level.

### 17. Cassandra compaction

What does compaction do? Explain why it is necessary and how it can hurt latency, disk, and repair behavior.

### 18. Tombstones

What are tombstones in Cassandra? Why do they exist, why are they dangerous at scale, and how do TTL-heavy workloads create tombstone pressure?

### 19. Database scaling patterns

Compare read replicas, partitioning, sharding, caching, materialized views, denormalization, and CQRS. Which solve read scale, which solve write scale, and which mostly shift complexity?

### 20. Connection pools and database saturation

Why can increasing application replicas make the database slower? Explain the relationship between pod count, pool size, active connections, locks, CPU, I/O, and queueing.

---

## Part 2 — Compound Scenario: Consensus + Storage Internals

### Scenario: The Inventory Ledger Split-Brain Scare

```text
Company: large e-commerce marketplace
Service: inventory-ledger-service
Database stack:
  - Cassandra cluster for high-volume inventory movement events
  - PostgreSQL for financial/order source-of-truth
  - Kafka for inventory.adjusted and order.created events
  - A small Raft-backed configuration store for write-routing and feature flags

Cassandra topology:
  - 9 nodes total
  - 3 AZs, 3 nodes per AZ
  - replication factor = 3 using NetworkTopologyStrategy
  - LOCAL_QUORUM for inventory decrement writes
  - LOCAL_QUORUM for reads used by checkout availability checks

Raft config store:
  - 5 nodes total
  - 3 nodes in AZ-a, 1 in AZ-b, 1 in AZ-c
  - stores flags such as:
      inventory_write_region = us-east-1
      enable_inventory_fast_path = true
      checkout_degrade_on_inventory_uncertain = true

Timeline:
  10:00 UTC: Normal traffic. Checkout success 99.98%.
  10:03 UTC: AZ-a starts packet loss between app subnets and data subnets.
  10:04 UTC: Raft leader is in AZ-a. Leadership becomes unstable.
  10:05 UTC: Two Raft followers in AZ-a are intermittently unreachable.
  10:06 UTC: Config reads from some app pods time out.
  10:07 UTC: Cassandra nodes in AZ-a remain up but show elevated read/write latency.
  10:08 UTC: Checkout begins timing out on inventory checks.
  10:09 UTC: Kafka inventory.adjusted lag begins rising.
  10:10 UTC: On-call sees Cassandra CPU normal, but p99 latency high and client timeouts rising.
  10:11 UTC: Product asks if checkout can ignore inventory for 10 minutes to save revenue.
```

### Questions

#### Q1. Raft quorum and topology

Can the 5-node Raft config store safely make progress during the AZ-a impairment? Explain using quorum math and the actual placement of nodes. What topology mistake made this worse?

#### Q2. Config-store failure mode

Some app pods cannot read the latest config. What should a production app do when a Raft-backed config store is unavailable? Compare fail-open, fail-closed, cached-last-known-good, and default config behavior for checkout inventory logic.

#### Q3. Cassandra consistency during AZ impairment

Given RF=3 and LOCAL_QUORUM, what happens to Cassandra reads/writes when one AZ is impaired but not fully down? Why can partial packet loss be worse than a clean node failure?

#### Q4. Latency with normal CPU

Cassandra CPU is normal, but p99 latency and client timeouts are high. Explain at least five possible causes that do not require high CPU. Include coordinator behavior, hinted handoff, compaction, tombstones, disk I/O, network, and thread pools.

#### Q5. Kafka lag interpretation

Kafka inventory.adjusted lag is rising. Is Kafka the root cause? Explain how Cassandra latency can create Kafka lag through producers, consumers, outbox/CDC, or downstream processors.

#### Q6. Checkout mitigation decision

Product asks to ignore inventory for 10 minutes. Give a Principal SRE answer. What business invariants matter? What is safe to degrade? What must not happen? Include oversell risk, customer trust, reconciliation, and compensation.

#### Q7. Safe immediate actions

List the first 10 actions you would take in the incident. Label each as diagnostic, mitigation, communication, or risk-control. Include at least one action for Raft, Cassandra, Kafka, checkout, and business stakeholders.

#### Q8. Post-incident architecture fixes

Name at least eight durable fixes. Include Raft node placement, app config caching, Cassandra client timeouts/retries, consistency-level review, tombstone/compaction monitoring, Kafka lag attribution, checkout degradation modes, and game-day testing.

---

## Part 3 — Answer Key / Principal SRE Reasoning

### A1. TCP vs UDP

TCP is preferred for payment APIs because payment requests need reliable, ordered byte streams, retransmission, congestion control, and a clear connection lifecycle. UDP can be acceptable for lossy telemetry because individual metrics or traces may be sampled or dropped without violating business correctness. The principal distinction is not speed; it is consequence of loss. Lost payment authorization is a correctness incident. Lost low-value telemetry is an observability-quality issue.

### A2. HTTP versions

HTTP/1.1 commonly suffers from per-connection head-of-line blocking and uses multiple connections for concurrency. HTTP/2 multiplexes many streams over one TCP connection, improving connection reuse but still inheriting TCP-level head-of-line blocking when packet loss occurs. HTTP/3 runs over QUIC/UDP and avoids TCP-level HOL blocking across streams, but introduces different operational surfaces: UDP reachability, QUIC support in CDNs/LBs, TLS behavior, and firewall/NAT oddities. During migrations, the risk is not only protocol support; it is observability, retries, idle timeouts, ALPN negotiation, and edge/origin behavior mismatch.

### A3. DNS resolution

DNS caching occurs at recursive resolvers, OS caches, browser/client caches, application runtimes, and sometimes load balancers or service-discovery layers. A 300-second TTL is a request to caches, not a global instant switch. Safe cutovers lower TTL before migration, run both old and new targets concurrently, drain old regions, monitor both paths, and avoid assuming all clients obey TTL perfectly.

### A4. CDN fundamentals

The stale image can live in browser cache, CDN edge cache, regional shield cache, proxy cache, or application cache. Cache-control controls freshness; surrogate keys allow group invalidation; versioned filenames avoid many invalidation races. The safest production answer is usually content-addressed or versioned assets plus short control-plane TTLs, not manual global purge as the default hammer.

### A5. REST vs GraphQL vs gRPC

REST is simple, cache-friendly, and broadly observable, but can over/under-fetch. GraphQL gives clients flexible selection but can hide expensive fan-out and needs query-cost controls. gRPC gives strong contracts, streaming, and efficient internal calls, but needs stronger tooling for debugging, load balancing, retries, and proxy support. Principal SREs evaluate them by operational behavior: schema evolution, timeout semantics, client behavior, retry safety, load-balancer compatibility, telemetry, and blast radius.

### A6. WebSockets

WebSockets create long-lived stateful connections. Scaling requires thinking about connection distribution, sticky sessions, reconnect storms, per-connection memory, backpressure, idle timeouts, and deployment draining. Stateless HTTP scaling can add pods behind a load balancer; WebSocket scaling also requires preserving or externalizing connection/session state and protecting the system from synchronized reconnect floods.

### A7. SQL vs NoSQL

Before moving order storage, ask: what are the transaction boundaries, queries, indexes, consistency needs, audit requirements, migration plan, failure modes, and operational skills? Increased traffic alone does not justify NoSQL. Orders often require strong correctness, constraints, idempotency, and reconciliation. NoSQL may help at scale if access patterns are known and consistency tradeoffs are acceptable, but it can make ad hoc queries, cross-entity transactions, and audits harder.

### A8. Caching patterns

Cache-aside lets the app load from DB on miss and populate cache; failure mode is stampede or stale data. Write-through writes cache and DB synchronously; failure mode is write latency/coupling. Write-behind writes cache first and DB later; failure mode is data loss or ordering bugs. Read-through delegates miss loading to the cache layer; failure mode is hidden dependency behavior. The principal question is whether the cache is an optimization or part of correctness.

### A9. CAP theorem

During a partition, a distributed system must choose whether to preserve consistency by refusing some operations or preserve availability by accepting operations that may conflict. CP systems reject or block some requests to maintain a single safe view. AP systems accept requests and reconcile later. CAP does not mean choosing any two forever; partition tolerance is not optional in distributed systems, and normal-case behavior has many more dimensions than CAP captures.

### A10. Consistency models

Strong consistency makes reads observe the latest committed write. Eventual consistency allows replicas to converge later. Read-your-writes ensures a user sees their own update. Monotonic reads prevent a user from seeing time go backward across replicas. Causal consistency preserves cause-effect relationships. Violations create bugs like missing profile updates, disappearing cart items, old balances after payment, message replies appearing before original messages, or support screens showing stale order state.

### A11. Consistent hashing

Consistent hashing maps keys and nodes onto a ring so adding/removing a node remaps only a fraction of keys, not almost all keys as modulo hashing would. Virtual nodes smooth distribution and allow weighted capacity. Operationally, this reduces cache churn, shard movement, and hot-node imbalance during scaling.

### A12. Replication strategies

Leader-follower centralizes writes and simplifies ordering but makes failover and replica lag important. Multi-leader improves write locality/availability but introduces conflict resolution. Leaderless/quorum systems allow flexible read/write quorums and high availability but require reasoning about stale reads, read repair, hinted handoff, and conflict/timestamp semantics. Principal reasoning starts with invariants: what must never be stale, duplicated, or lost?

### A13. Sharding

Vertical partitioning splits columns or domains; horizontal sharding splits rows. Range sharding is intuitive but can hotspot. Hash sharding distributes load but hurts range queries. Directory-based sharding gives control but adds a routing dependency. Resharding risks dual writes, inconsistent routing, backfill bugs, hot shards, rebalancing traffic, and operational uncertainty around cutover.

### A14. Raft consensus

A 5-node Raft cluster needs a majority of 3 to elect a leader and commit new entries. Losing 2 nodes leaves 3, so it can progress. Losing 3 leaves 2, so it cannot safely progress. Quorum prevents split brain because two independent majorities cannot exist at the same time in the same term.

### A15. Cassandra write path

The client sends a write to a coordinator. The partitioner maps the partition key to token ranges and replicas. The coordinator sends mutations to replicas required by the chosen consistency level. Each replica appends to the commit log for durability and updates the memtable. Later, memtables flush to immutable SSTables. The write succeeds when enough replicas acknowledge for the consistency level.

### A16. Cassandra read path

The coordinator sends reads to replicas according to the consistency level. Replicas check memtables and SSTables, using bloom filters and indexes to avoid unnecessary disk reads. Digest reads compare data without returning full rows. If replicas disagree, read repair or reconciliation may occur. Tombstones and many SSTables can make reads expensive even if CPU looks normal.

### A17. Cassandra compaction

Compaction merges SSTables, removes obsolete versions and expired tombstones, and improves future read efficiency. It is necessary because Cassandra writes immutable SSTables. But compaction consumes disk I/O, CPU, and temporary disk space; falling behind can increase read amplification, latency, and operational risk.

### A18. Tombstones

Tombstones mark deleted data so replicas can learn about deletions during repair and eventual consistency. They are dangerous because reads must scan and reconcile them until they are safely purged. TTL-heavy workloads create many tombstones, causing read latency spikes, GC pressure, compaction pressure, and sometimes query failure due to tombstone thresholds.

### A19. Database scaling patterns

Read replicas scale reads but not primary writes and introduce lag. Partitioning can improve manageability and some query paths. Sharding scales writes and storage but adds routing and transaction complexity. Caching reduces repeated reads but introduces staleness. Materialized views optimize derived reads but need refresh correctness. Denormalization improves query locality but duplicates data. CQRS separates write and read models but adds eventing and consistency complexity.

### A20. Connection pools and database saturation

Increasing app replicas multiplies possible DB connections. If each pod has a pool of 50 and there are 100 pods, the DB may face 5000 potential sessions. More connections can increase lock contention, memory pressure, context switching, I/O queues, and slow-query pileups. A smaller pool can protect the DB by limiting concurrency to what it can actually process.

---

## Part 4 — Compound Scenario Answer Key

### Q1. Raft quorum and topology

A 5-node Raft cluster needs 3 reachable voters for quorum. The topology is poor because 3 of 5 nodes are in AZ-a. If AZ-a is impaired, the cluster may lose the majority even though two other AZs are healthy. The safer placement is 2-2-1 across AZs or a design that avoids one AZ holding a voting majority. The topology mistake is concentrating quorum power in a single failure domain.

### Q2. Config-store failure mode

For checkout inventory logic, fail-open is dangerous because it may allow overselling. Fail-closed protects inventory correctness but can hurt revenue and availability. Default config is risky if defaults are stale or unsafe. Cached-last-known-good is usually the best baseline if configs are signed/versioned, have TTLs, and include safe expiration behavior. For uncertain inventory, a safe design may degrade by limiting high-risk SKUs, disabling fast path, or requiring stronger confirmation rather than ignoring inventory entirely.

### Q3. Cassandra consistency during AZ impairment

With RF=3 and LOCAL_QUORUM, the coordinator needs acknowledgements from a quorum of local replicas. If replicas are spread across AZs, a clean AZ failure may be easier to reason about than partial packet loss, because clients and coordinators can quickly mark nodes down. Partial impairment causes timeouts, retries, slow coordinators, speculative execution, and ambiguous outcomes. The result can be high p99 latency despite nodes technically being up.

### Q4. Latency with normal CPU

Normal CPU does not mean healthy Cassandra. p99 latency can rise from network packet loss, slow replica responses, coordinator waiting for consistency-level acknowledgements, compaction I/O, tombstone-heavy reads, too many SSTables/read amplification, disk queueing, thread-pool saturation, GC pauses, repair/streaming pressure, hinted handoff accumulation, or client retries amplifying load. CPU is one signal, not the system’s truth serum.

### Q5. Kafka lag interpretation

Kafka lag is likely a symptom, not the root cause. Cassandra latency can slow consumers that write to Cassandra, slow producers that wait for database transactions before publishing, stall outbox/CDC publication, or create retry storms that reduce consumer throughput. The diagnostic question is whether Kafka brokers are unhealthy or whether consumers/producers are blocked by downstream Cassandra or Postgres dependencies.

### Q6. Checkout mitigation decision

Ignoring inventory protects short-term revenue but risks oversell, canceled orders, customer distrust, support load, and reconciliation cost. A Principal SRE would not approve a blanket ignore-inventory mode unless the business explicitly accepts those risks. Safer degradation options include allowing checkout only for high-confidence inventory, disabling low-stock SKUs, queueing orders as pending inventory confirmation, limiting quantity per user, or routing to a fallback reservation path. The invariant is: do not promise goods you cannot plausibly fulfill without an explicit business decision and compensation plan.

### Q7. Safe immediate actions

```text
1. Diagnostic: declare incident and establish customer/business impact.
2. Diagnostic: check Raft quorum, current leader, and reachable voters.
3. Diagnostic: inspect Cassandra p99 by coordinator/replica/AZ, timeouts, dropped messages, pending compactions, tombstones, and thread pools.
4. Diagnostic: check Kafka broker health and lag by consumer group to separate broker issue from downstream slowdown.
5. Mitigation: disable risky fast path if config can be read safely or use cached safe config if designed.
6. Mitigation: reduce checkout concurrency or protect DB/Cassandra from retry amplification.
7. Mitigation: route traffic away from impaired AZ only if data-path dependencies support it.
8. Risk-control: freeze deploys and config changes for inventory/checkout until stable.
9. Communication: tell product the safe degradation menu and risks of ignoring inventory.
10. Communication: publish incident updates with current impact, mitigation, and next checkpoint.
```

### Q8. Post-incident architecture fixes

```text
1. Rebalance Raft voters across AZs; avoid majority in one AZ.
2. Add client-side cached-last-known-good config with TTL and safe expiry.
3. Define fail-open/fail-closed behavior per feature flag and business invariant.
4. Tune Cassandra client timeouts, retry policy, speculative execution, and circuit breakers.
5. Review LOCAL_QUORUM behavior under partial AZ impairment with game days.
6. Add dashboards for Cassandra coordinator latency, replica latency, dropped messages, compaction pending, tombstones, and thread pools.
7. Add Kafka lag attribution dashboards: broker health vs consumer dependency latency.
8. Add checkout degradation modes: high-confidence inventory only, pending confirmation, low-stock disablement.
9. Add retry budgets to prevent app retries from amplifying partial outages.
10. Add runbooks for Raft config-store instability and Cassandra partial-AZ impairment.
11. Add WAL/outbox/CDC lag monitoring if events depend on database publication.
12. Run chaos tests for partial packet loss, not only clean node/AZ failure.
```

---

## Final Scoring Guidance

```text
Strong answer:
  - Explains mechanisms correctly
  - Connects symptoms to layers
  - Avoids unsafe blanket mitigations
  - Names signals and commands to inspect

Principal answer:
  - Protects business invariants
  - Separates root cause from symptoms
  - Identifies topology and control-plane design flaws
  - Uses reversible mitigations first
  - States what evidence would change the decision
  - Produces durable architecture fixes
```
