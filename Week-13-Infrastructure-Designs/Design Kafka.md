# Design Kafka
> Week 13 — Infrastructure System Design | Interview Framing
> **Different angle from Week 6:** Week 6 teaches Kafka internals (partitions, ISR, rebalance). This module teaches you to *design* a distributed log / event streaming platform in a system design interview.

---

## Learning Objectives
```
╔════════════════════════════════════════════════════════════════════════╗
║ AFTER THIS MODULE, YOU WILL BE ABLE TO:                                ║
╟────────────────────────────────────────────────────────────────────────╢
║ 1. Lead a 45-min interview for 'design a message queue / event bus'    ║
║ 2. Choose log vs queue model before naming Kafka                       ║
║ 3. Size topics, partitions, retention, and disk throughput             ║
║ 4. Design partition keys without hot partitions                        ║
║ 5. Explain consumer groups, offset management, rebalance cost          ║
║ 6. Compare at-least-once, exactly-once, and idempotent consumers       ║
║ 7. Contrast Kafka vs SQS vs RabbitMQ vs Kinesis with decision matrix   ║
║ 8. Diagnose lag, rebalance storms, and ISR shrink in production        ║
╚════════════════════════════════════════════════════════════════════════╝
```
---

## Wrong Mental Models (Destroy These First)
```
╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL: "Kafka = message queue with persistence"                                                                         ║
╟────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Kafka is a distributed commit log. Messages are NOT deleted on consume. Consumer position is a cursor, not ownership.   ║
╚════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝



╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL: "More partitions = always better"                                                                      ║
╟──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Each partition = one leader broker thread + file handles + rebalance cost. Over-partitioning kills brokers.   ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝



╔═════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL: "Exactly-once is free"                                                                            ║
╟─────────────────────────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. EOS requires idempotent producer + transactions + cooperative consumers — latency and complexity cost.   ║
╚═════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝



╔═════════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL: "Kafka replaces your database"                                                    ║
╟─────────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Log is immutable history; compacted topics ≠ OLTP. CQRS read models still need stores.   ║
╚═════════════════════════════════════════════════════════════════════════════════════════════════╝



╔═══════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL: "One consumer group per service is enough"                          ║
╟───────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Different SLAs need different groups, offset policies, and retry topics.   ║
╚═══════════════════════════════════════════════════════════════════════════════════╝
```
---

## Core Teaching


```
THE SYSTEM DESIGN INTERVIEW OPENING (45 MINUTES TOTAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Minutes 0-5:   CLARIFY requirements (functional + non-functional)
  Minutes 5-10:  ESTIMATE scale (QPS, storage, bandwidth)
  Minutes 10-15: HIGH-LEVEL design (boxes and arrows — get buy-in)
  Minutes 15-35: DEEP DIVE (2-3 areas interviewer picks)
  Minutes 35-42: BOTTLENECKS, failure modes, tradeoffs
  Minutes 42-45: SUMMARY and extensions

  RULE: Never jump to micro-optimizations before the interviewer
  agrees on the high-level shape. A beautiful consistent-hashing
  explanation that solves the wrong problem scores zero.
```

### 3.1 — Canonical Prompts

```
INTERVIEW PROMPTS (all map to same core design):
  → "Design a message queue for a social network's activity feed"
  → "Design an event streaming platform for payment events"
  → "Design Kafka" (meta — they want the log architecture)
  → "Design a system to collect 1B clicks/day for analytics"

CLARIFY FIRST:
  □ Ordering requirements (global? per-user? none?)
  □ Retention (hours? forever? compacted?)
  □ Delivery guarantee (fire-and-forget? at-least-once? exactly-once?)
  □ Fan-out (many independent consumers?)
  □ Replay (new consumers read history?)
  □ Message size (1 KB vs 10 MB — affects broker config)
  □ Throughput and peak QPS
```

### 3.2 — Queue vs Log Decision (State This Early)

```
  Week 6 taught internals. In interview, START HERE:

  Need ONE worker per message, delete after ack?
    → Queue (SQS, RabbitMQ)

  Need MANY consumers reading same events independently?
    → Log (Kafka, Pulsar, Kinesis)

  Need replay / event sourcing / audit trail?
    → Log

  Need strict per-entity ordering?
    → Log with partition key = entity_id

  If interviewer says "design Kafka" — you've already chosen Log.
  Justify: "Multiple services consume payment events independently;
  audit requires 7-year retention; replay for new fraud model."
```

### 3.3 — Capacity Estimation

```
EXAMPLE: 1 billion events/day, avg 2 KB

  Ingest: 1B / 86400 ≈ 12K events/sec (peak 3× ≈ 36K/sec)
  Ingress bandwidth: 36K × 2 KB = 72 MB/s
  Retention 7 days: 1B × 7 × 2 KB = 14 TB raw
  Replication RF=3: 42 TB cluster storage
  Add 20% index overhead → ~50 TB

  Partition count:
    Target: ~10 MB/s per partition max (rule of thumb)
    72 MB/s peak / 10 = 8 partitions minimum
    × 10 headroom = 80-100 partitions for this topic
    Say 96 partitions (clean power of 2)

  Broker count:
    50 TB / 12 TB per broker disk = 5 brokers minimum
    × 2 for headroom = 10 brokers
```

### 3.4 — High-Level Architecture

```
                    PRODUCERS
        ┌──────────┬──────────┬──────────┐
        ▼          ▼          ▼          ▼
   ┌─────────────────────────────────────────┐
   │           KAFKA CLUSTER (brokers)        │
   │  Topic: payments (96 partitions)         │
   │  RF=3, min.insync.replicas=2             │
   │                                          │
   │  P0  P1  P2 ... P95                      │
   │  each partition = ordered immutable log  │
   └─────────────────────────────────────────┘
        │          │          │
        ▼          ▼          ▼
   Consumer     Consumer    Consumer
   Group A      Group B     Group C
   (fraud)      (analytics) (audit archive)

  ZooKeeper / KRaft: cluster metadata, controller election
  (Interview: "Modern Kafka uses KRaft — Raft-based metadata, Week 4")

  Schema Registry: Avro/Protobuf schema evolution
```
### 3.5 — Partition & Key Design

```
PARTITION KEY = colocation + ordering unit

  All messages with same key → same partition → strict order

  GOOD keys: user_id, order_id, device_id (high cardinality)

  BAD keys: country_code (hot partition — all US → one partition)
            null key (round-robin — loses ordering)

  HOT PARTITION FIX:
    → Salt: key = hash(user_id + random_bucket)
    → Downstream reorder if needed (Flink keyed state)
    → Separate topic for hot entities
### 3.6 — Producer Design

```
PRODUCER CONFIG (name in interview):

  acks=all (wait for ISR ack) — durability
  enable.idempotence=true — dedupe within session
  compression.type=lz4 or zstd — bandwidth
  batch.size + linger.ms — throughput vs latency tradeoff

  PRODUCE FLOW:
    1. Serialize (Avro + schema ID)
    2. Partition(key) → partition_id
    3. Send to partition leader broker
    4. Leader appends to log segment, replicates to ISR
    5. Ack to producer

  FAILURE: producer retry + idempotence → no duplicate sequence numbers
### 3.7 — Consumer Groups & Offsets

```
CONSUMER GROUP = horizontal scale unit for ONE processing pipeline

  Partitions ÷ consumers in group = max parallelism
  96 partitions, 24 consumers → each handles 4 partitions
  96 partitions, 100 consumers → 4 idle (wasted)

  OFFSET = position in partition log
  Stored in __consumer_offsets topic (compact)

  Commit strategies:
    Auto-commit: easy, may lose or duplicate on crash
    Sync commit after DB write: at-least-once
    Transactional read-process-write: exactly-once

  REBALANCE (Week 6 — interview cost):
    Consumer join/leave → partition reassignment
    STOPS THE WORLD during rebalance (classic consumer)
    Cooperative sticky: incremental — mention as improvement
### 3.8 — Replication & ISR

```
PARTITION LEADER + FOLLOWERS (Week 4 parallel):

  RF=3: 1 leader + 2 followers per partition
  ISR = in-sync replicas (lag < replica.lag.time.max.ms)

  acks=all + min.insync.replicas=2:
    → Write committed when 2 of 3 ISR members ack
    → Leader failure: new leader from ISR only
    → Unclean leader election OFF → no data loss (prefer unavailability)

  CONNECTION TO WEEK 4:
    ISR overlap resembles quorum — majority of replicas
    have the latest committed offset before ack
### 3.9 — Retention & Compaction

```
DELETE RETENTION: time (7d) or size (500 GB/topic)
  → Old segments deleted

LOG COMPACTION (changelog topics):
  → Keep latest value per key forever
  → Use for: config changes, KTables, CDC state
  → NOT for infinite event history

  Interview: "Payments events → time retention + archive to S3
             User profile changelog → compacted topic"
### 3.10 — Delivery Semantics

```
┌──────────────┬─────────────────────────────────────────────┐
│ Guarantee    │ How                                         │
├──────────────┼─────────────────────────────────────────────┤
│ At-most-once │ Commit offset BEFORE process (may lose)     │
│ At-least-once│ Process then commit (may duplicate)         │
│ Exactly-once │ Kafka transactions + idempotent producer  │
│              │ + read_committed consumers                  │
└──────────────┴─────────────────────────────────────────────┘

  Interview default: at-least-once + idempotent consumer
  (dedupe by event_id in DB unique constraint)

  EOS when: financial ledger, no duplicate tolerance
  Cost: 20-30% latency, operational complexity
### 3.11 — KRaft vs ZooKeeper

```
  Legacy: ZooKeeper for broker metadata (external CP system)
  Modern (Kafka 3.3+): KRaft — built-in Raft controller (Week 4)

  Interview: "I'd design with KRaft — one less dependency,
  Raft quorum for metadata matches Week 4 consensus module."

---

## Concrete Examples
### Activity Feed Fan-Out
```
Producer: post_created → topic social.events, key=author_id. Groups: feed-builder, notifications, search-indexer, analytics.
```
### Payment Event Bus
```
Topic payments, key=account_id, 7y retention, audit consumer to Glacier, fraud ML consumer with replay.
```
### CDC from OLTP
```
Debezium → topic db.users, compacted, search service builds Elasticsearch index.
```
### Metrics Pipeline
```
High QPS low value: separate topic, short retention, Flink aggregation downstream.
```
### Dead Letter Queue Pattern
```
Main topic → consumer → fail after 3 retries → topic payments.DLT, manual replay tool.
```

---

## Production Patterns
#### Topic naming: domain.entity.action.version
```
Production implementation notes for Topic naming: domain.entity.action.version.
```
#### Schema evolution: backward compatible Avro only
```
Production implementation notes for Schema evolution: backward compatible Avro only.
```
#### MSK on AWS: IAM auth, multi-AZ brokers, tiered storage
```
Production implementation notes for MSK on AWS: IAM auth, multi-AZ brokers, tiered storage.
```
#### MirrorMaker 2 for cross-region DR
```
Production implementation notes for MirrorMaker 2 for cross-region DR.
```
#### Quota per tenant: produce/consume byte rate limits
```
Production implementation notes for Quota per tenant: produce/consume byte rate limits.
```
#### Separate clusters: online vs offline analytics
```
Production implementation notes for Separate clusters: online vs offline analytics.
```
#### Broker rack awareness: RF spread across AZs
```
Production implementation notes for Broker rack awareness: RF spread across AZs.
```
#### Monitoring: ConsumerLag, UnderReplicatedPartitions
```
Production implementation notes for Monitoring: ConsumerLag, UnderReplicatedPartitions.
```

---

## Failure Modes
### Consumer lag explosion
```
Slow consumer; scale consumers ≤ partitions; optimize processing; don't block poll loop
```
### Rebalance storm
```
Rolling deploy too fast; session.timeout too low; use cooperative rebalance
```
### Hot partition
```
Bad key; salt keys; add partitions only helps if key space expands
```
### ISR shrink to 1
```
Follower disk slow; network partition; min.insync.replicas blocks producers
```
### Disk full
```
Retention too long; no tiered storage; missed monitoring on log.dir
```
### Zombie consumer
```
Static membership; max.poll.interval exceeded; duplicate processing
```
### Poison message
```
DLT + skip; don't infinite retry blocking partition
```
### Unclean election data loss
```
unclean.leader.election.enable=true — never in prod
```

---

## SRE Diagnostic Toolkit
```
kafka-consumer-groups.sh --bootstrap-server ... --describe --group mygroup
  → LAG per partition — THE metric

kafka-topics.sh --describe --topic payments
  → Leader, ISR, Under-replicated partitions

Broker JMX:
  kafka.server:type=FetcherLagMetrics,name=ConsumerLag,...
  kafka.log:type=LogFlushStats,name=LogFlushRateAndTimeMs

Confluent / AWS MSK:
  CloudWatch BrokerCount, CpuUser, KafkaDataLogsDiskUsed

kcat / kafkacat:
  kcat -C -b broker -t payments -p 0 -o beginning -c 5
  → Inspect first 5 messages partition 0
```

---

## Decision Framework
```
┌──────────────────┬─────────┬──────────┬─────────┬──────────┐
│ Need             │ Kafka   │ SQS      │ RabbitMQ│ Kinesis  │
├──────────────────┼─────────┼──────────┼─────────┼──────────┤
│ Multi-subscriber │ Yes     │ No*      │ Pub/sub │ Yes      │
│ Replay           │ Yes     │ No       │ No      │ 24h-365d │
│ Ordering/key     │ Yes     │ FIFO*    │ Limited │ Yes      │
│ Ops burden       │ High    │ Zero     │ Medium  │ Low(AWS) │
│ Throughput       │ Massive │ High     │ Medium  │ High     │
└──────────────────┴─────────┴──────────┴─────────┴──────────┘
  * SQS FIFO: 300 msg/s per queue without batching
```

---

## Incident Scenario
```
P1: Payment processing stopped — consumer lag 45 million

Architecture: Kafka 12 brokers, topic payments 120 partitions RF=3
Consumer group payment-processor, 60 consumers, at-least-once

Timeline:
  14:00 — Deploy payment-processor v2.2.0
  14:03 — Lag starts climbing all partitions
  14:08 — Lag 12M, DB connection pool exhausted
  14:12 — Alerts: processing rate 500/sec vs ingest 8000/sec
  14:15 — Rollback deploy — lag still climbing
  14:20 — Discover v2.2.0 changed max.poll.records 500→5000
          but processing still 1 record at a time — poll timeout

Questions:
  1. Why didn't rollback fix lag immediately?
  2. Root cause chain?
  3. Immediate mitigation?
  4. Design changes to prevent recurrence?
```

---

## Expert Analysis
### Question 1
```
Expert worked answer for incident Q1.
```
### Question 2
```
Expert worked answer for incident Q2.
```
### Question 3
```
Expert worked answer for incident Q3.
```
### Question 4
```
Expert worked answer for incident Q4.
```

### Full Expert Narrative

```
Q1 Rollback: Lag is BACKLOG not production rate. Consumers still
   process 500/sec; 45M / 500 = 25 hours to drain. Rollback stops
   NEW bugs but doesn't erase accumulated lag.

Q2 Root cause: max.poll.records=5000 → process loop exceeds
   max.poll.interval.ms (5 min default) → consumer kicked from group
   → rebalance storm → each rebalance pauses all 60 consumers
   → effective throughput collapses

Q3 Mitigation:
   1. Scale consumers to 120 (match partitions) on OLD version
   2. Increase max.poll.interval.ms temporarily (tactical)
   3. Pause non-critical producers if overload continues
   4. Fix code: batch DB writes before poll

Q4 Design:
   → Separate retry topic (don't block main partition)
   → Lag alert on derivative (dLag/dt) not absolute
   → Load test consumer with production message sizes pre-deploy
   → Circuit breaker on DB when pool exhausted
```

---

## Key Takeaways
```
╔════════════════════════════════════════════════════════════════════════╗
║ REMEMBER:                                                              ║
╟────────────────────────────────────────────────────────────────────────╢
║ 1. Interview: clarify queue vs log before Kafka specifics.             ║
║ 2. Partitions = unit of order AND parallelism — size deliberately.     ║
║ 3. Consumer lag is debt — rollback doesn't erase backlog.              ║
║ 4. at-least-once + idempotent consumer is the pragmatic default.       ║
║ 5. Week 6 internals support design; this module is the 45-min story.   ║
╚════════════════════════════════════════════════════════════════════════╝
```
---

## Targeted Reading
```
REQUIRED:
  1. Kafka documentation: Design Overview + Replication
  2. Week 6: Message Queues and Kafka.md (internals reference)
  3. DDIA Chapter 11 (Stream Processing)
  4. Confluent: Log compaction, exactly-once semantics blogs

OPTIONAL:
  5. Jay Kreps: "The Log" essay
  6. AWS MSK best practices guide
```

## Appendix: Interview Comparison with Week 6


```
Week 6 Module                    │ Week 13 Design Module
─────────────────────────────────┼──────────────────────────────
How ISR works                    │ When to choose Kafka vs SQS
Rebalance protocol steps         │ How many partitions to size
Offset commit internals          │ 45-minute interview script
Transactional producer API       │ Incident: lag + rebalance storm
Outbox pattern integration       │ Capacity estimation for broker fleet
```

### Interview Drill 1: Extending the Design

```
Drill 1: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 2: Extending the Design

```
Drill 2: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 3: Extending the Design

```
Drill 3: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 4: Extending the Design

```
Drill 4: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 5: Extending the Design

```
Drill 5: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 6: Extending the Design

```
Drill 6: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 7: Extending the Design

```
Drill 7: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 8: Extending the Design

```
Drill 8: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 9: Extending the Design

```
Drill 9: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 10: Extending the Design

```
Drill 10: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 11: Extending the Design

```
Drill 11: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 12: Extending the Design

```
Drill 12: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 13: Extending the Design

```
Drill 13: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 14: Extending the Design

```
Drill 14: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 15: Extending the Design

```
Drill 15: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 16: Extending the Design

```
Drill 16: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 17: Extending the Design

```
Drill 17: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 18: Extending the Design

```
Drill 18: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 19: Extending the Design

```
Drill 19: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

### Interview Drill 20: Extending the Design

```
Drill 20: Interviewer asks extension question.

  Sample extensions:
    → Add schema registry and backward compatibility rules
    → Cross-region replication with MirrorMaker 2
    → Tiered storage to S3 for 7-year retention
    → Stream processing with Flink (windows, joins)
    → Security: mTLS, ACLs, SASL SCRAM

  Structure your answer:
    1. Restate requirement
    2. Component added (box on diagram)
    3. Tradeoff (latency, cost, ops)
    4. Failure mode introduced
    5. Metric to monitor

  Connection to Week 6: reference ISR/rebalance when discussing
  broker failures; reference outbox when discussing DB+Kafka consistency.
```

---

# Appendix: Design Kafka — Interview Deep-Dive

> **Append to:** `Design Kafka.md` (Week 13 — Infrastructure System Design)
> **Purpose:** Hands-on drills, timed whiteboard script, incident forensics, and mock dialogue.
> **Angle:** Interview design framing — not Week 6 internals rehash.

---

## Part A: 45-Minute Interview Whiteboard Walkthrough

This is a **timed script** for the canonical prompt: *"Design an event streaming platform for payment events at scale."* Each phase has unique talking points an interviewer expects. Practice with a timer.

```
INTERVIEW CLOCK (45 MINUTES)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 1 │ 0:00 – 5:00  │ Requirements & scope lock
  Phase 2 │ 5:00 – 10:00 │ Back-of-envelope capacity
  Phase 3 │ 10:00 – 15:00│ High-level architecture (whiteboard)
  Phase 4 │ 15:00 – 25:00│ Deep dive A: partitions & keys
  Phase 5 │ 25:00 – 35:00│ Deep dive B: consumers & delivery
  Phase 6 │ 35:00 – 42:00│ Failure modes & ops
  Phase 7 │ 42:00 – 45:00│ Summary & extensions

  RULE: Spend Phase 1 even if you "know" Kafka. Interviewers
  score candidates who design the RIGHT system, not the loudest one.
```

### Phase 1 (0:00 – 5:00): Requirements & Scope Lock

```
WHAT TO SAY (verbatim structure):

  "Before I draw boxes, let me clarify functional and non-functional
   requirements so we design the right abstraction — queue or log."

FUNCTIONAL (write on board):
  □ Event types: payment.initiated, payment.captured, payment.refunded
  □ Producers: checkout API, refund service, chargeback webhook
  □ Consumers: ledger writer, fraud scorer, analytics, audit archiver
  □ Ordering: per account_id (not global)
  □ Retention: 7 years for audit; 30 days hot in Kafka
  □ Replay: new fraud model must reprocess last 90 days

NON-FUNCTIONAL:
  □ Peak ingest: ~10K events/sec (Black Friday 3× headroom)
  □ Avg message: 2 KB Avro
  □ Durability: no committed payment lost on single broker failure
  □ Latency: fraud decision p99 < 500ms (stream path)
  □ Multi-AZ, RF=3 acceptable cost

DECISION OUT LOUD:
  "Multiple independent consumers, replay, audit trail → distributed
   commit log, not a work queue. I'll design around Kafka semantics
   but the pattern applies to Pulsar/Kinesis."

INTERVIEWER PUSHBACK YOU SHOULD INVITE:
  → "Why not SQS?" → "SQS has no independent fan-out groups or replay
     beyond 14 days; three consumers can't each read the same payment
     at their own pace without duplicate queues."
  → "Why not RabbitMQ?" → "Pub/sub exists but no durable replay;
     competing consumers delete messages — wrong for audit + analytics."
```

**Whiteboard sketch (Phase 1 only — labels, no internals):**

```
  [Checkout] [Refunds] [Webhooks]
         \      |      /
          PRODUCERS (Avro + schema registry)
                    │
                    ▼
            ┌───────────────┐
            │  EVENT LOG    │  ← you haven't said "Kafka" yet
            │  (payments)   │
            └───────────────┘
               │   │   │
         ledger fraud analytics audit
```

### Phase 2 (5:00 – 10:00): Back-of-Envelope Capacity

```
WRITE ON BOARD — show arithmetic:

  Daily volume: 800M payments/day (example after clarify)
  Average: 800M / 86400 ≈ 9,260 events/sec
  Peak (3×): ≈ 28K events/sec

  Ingress bandwidth (peak):
    28,000 × 2 KB = 56 MB/s write to cluster

  Hot retention (30 days):
    800M × 30 × 2 KB = 48 TB raw
  RF=3: 144 TB
  +20% segment/index overhead ≈ 173 TB

  PARTITION SIZING (interview-critical):
    Rule of thumb: target ≤ 10 MB/s per partition leader
    56 MB/s / 10 = 6 partitions minimum
    × 10 growth headroom = 60 partitions
    Round to 64 (power of 2, clean ops)

  BROKER COUNT:
    173 TB / 16 TB usable per broker ≈ 11 brokers
    × 1.5 headroom for rebalancing skew → 16–18 brokers

  CONSUMER PARALLELISM (payment-processor group):
    Target 50ms processing per event → 20 events/sec per thread
    28K / 20 = 1,400 parallel pipelines needed
    BUT max parallelism = partition count = 64
    → 64 consumers × 437 events/sec each at peak — TOO SLOW

  RED FLAG — SAY IT:
    "64 partitions cannot sustain 28K/sec if processing is 50ms each.
     I need either faster processing (batch DB writes), more partitions
     (256+), or async handoff to a worker pool per partition."

  REVISED:
    Batch 100 events → 5ms amortized DB write → 200 events/sec/consumer
    28K / 200 = 140 consumers needed → need ≥ 140 partitions
    Design: 192 partitions, RF=3, 24 brokers
```

### Phase 3 (10:00 – 15:00): High-Level Architecture

```
DRAW THIS (unique to payment domain):

                    ┌─────────────────┐
                    │ Schema Registry │
                    │ (Avro, BACKWARD)│
                    └────────┬────────┘
                             │
    ┌──────────┐    ┌────────▼────────────────────────────┐
    │ Checkout │───►│ Topic: payments.events.v1           │
    │ Service  │    │ 192 partitions, RF=3                │
    └──────────┘    │ key=account_id                      │
    ┌──────────┐    │ retention.ms=30d + tiered → S3 7y   │
    │ Refunds  │───►│ min.insync.replicas=2, acks=all     │
    └──────────┘    └────────┬────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
  │ Group:      │    │ Group:      │    │ Group:      │
  │ ledger-     │    │ fraud-      │    │ analytics-  │
  │ writer      │    │ scorer      │    │ flink       │
  │ (EOS txn)   │    │ (at-least-  │    │ (at-least-  │
  │             │    │  once)      │    │  once)      │
  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘
         │                  │                  │
         ▼                  ▼                  ▼
     PostgreSQL         Redis + ML         Data warehouse
     (ledger)           features           (Snowflake)

  METADATA LAYER (one sentence):
    "KRaft controllers — three dedicated nodes, Week 4 Raft quorum
     for broker metadata; no ZooKeeper dependency."

  CROSS-CUTTING (bullets on board):
    • mTLS + ACLs per service principal
    • CloudWatch/Prometheus: ConsumerLag, UnderReplicatedPartitions
    • payments.DLT topic for poison messages
    • MirrorMaker 2 passive DR region (lag < 5 min RPO)
```

### Phase 4 (15:00 – 25:00): Deep Dive A — Partitions & Keys

```
INTERVIEWER: "How do you pick the partition key?"

YOUR ANSWER STRUCTURE:

  1. Ordering requirement → colocate by account_id
  2. Cardinality check → 400M accounts → good spread
  3. Hot key risk → enterprise B2B accounts with 10K txn/min
  4. Mitigation → salted sub-key for known hot accounts

KEY DESIGN:

  Default: partition = murmur2(account_id)

  Hot account detection:
    Producer-side: if account_id in HOT_ACCOUNT_SET:
      key = account_id + ":" + (txn_id % 32)  // 32-way split
    Downstream ledger: idempotent by payment_id anyway

ASCII — HOT PARTITION WITHOUT SALT:

  Partition 7: ████████████████████  (enterprise client X)
  Partition 3: ██
  Partition 9: █
  Partition 1: ██
  ... other partitions nearly idle

  Consumer on P7: LAG 2.4M while others at 0

WITH SALT (32 buckets for hot account):

  Partition 7:  ███
  Partition 12: ███
  Partition 44: ███
  ... load spreads; ordering per account relaxed for that account only
  Ledger still serializes by payment_id in DB

PARTITION COUNT CHANGE POLICY:
  "Increase 192 → 384 offline with Kafka partition reassignment;
   keys hash to new partition — ordering preserved per key.
   Never decrease partitions in production."

PRODUCER CONFIG (name configs — interview points):
  acks=all
  enable.idempotence=true
  compression.type=zstd
  linger.ms=5, batch.size=65536
```

### Phase 5 (25:00 – 35:00): Deep Dive B — Consumers & Delivery

```
INTERVIEWER: "Exactly-once for the ledger?"

DRAW SEMANTICS TABLE:

  ┌──────────────┬─────────────────────────────────────────────┐
  │ Path         │ Guarantee & mechanism                       │
  ├──────────────┼─────────────────────────────────────────────┤
  │ Ledger       │ EOS: read_committed + txn producer +       │
  │              │ DB upsert idempotent on payment_id          │
  │ Fraud        │ At-least-once + dedupe store (Redis SET)    │
  │ Analytics    │ At-least-once; duplicates OK in rollup      │
  │ Audit S3     │ At-least-once; S3 keys idempotent by offset│
  └──────────────┴─────────────────────────────────────────────┘

CONSUMER GROUP MATH ON BOARD:

  Topic: 192 partitions
  Group ledger-writer: 48 consumers → 4 partitions each
  Group fraud-scorer: 96 consumers → 2 partitions each

  "Different groups — no competition. Fraud can scale independently
   from ledger without touching ledger offsets."

OFFSET COMMIT PATTERN (ledger — at-least-once minimum):

  WRONG:
    poll() → process → write DB → crash before commit → duplicate

  RIGHT:
    poll() → write DB + store offset in same DB txn → commit
    OR: process → commit sync → accept at-least-once + idempotent UPSERT

  EOS (when interviewer pushes):
    consume → transform → produce to downstream / write DB
    all in one kafka transaction + read_committed isolation

REBALANCE COST (mention, don't lecture — Week 6 reference):
  "Rolling deploy of 48 consumers triggers cooperative sticky rebalance;
   I use static group.instance.id to reduce churn; max.poll.interval
   sized for worst-case batch (see incident appendix)."

POLL LOOP DISCIPLINE:
  process time < max.poll.interval.ms / 2
  records per poll matched to processing throughput
```

### Phase 6 (35:00 – 42:00): Failure Modes & Operations

```
INTERVIEWER: "Broker dies in us-east-1a?"

FAILURE WALKTHROUGH:

  1. Leader for P42 was broker-7 (AZ-a)
  2. Controller detects failure (~10s)
  3. New leader elected from ISR (brokers in AZ-b, AZ-c)
  4. Producers metadata refresh → send to new leader
  5. Unclean election disabled → if ISR=1, prefer unavailability

  "min.insync.replicas=2 means if ISR shrinks to 1, producers with
   acks=all block — correct tradeoff for payments."

ISR SHRINK SCENARIO:

  Follower lag > replica.lag.time.max.ms (default 30s)
  → Follower dropped from ISR
  → If only leader in ISR → writes block for acks=all

  Mitigation: disk IO tuning, separate log dirs NVMe, network placement

CONSUMER LAG INCIDENT PREVIEW:
  "Lag is debt. Rollback stops new bugs, not backlog.
   Alert on d(lag)/dt, not absolute lag at 3am."

MONITORING CHECKLIST (write quickly):
  □ ConsumerLag per group/partition
  □ UnderReplicatedPartitions
  □ OfflinePartitionsCount
  □ BytesInPerSec vs consumer process rate
  □ RequestHandlerAvgIdlePercent (broker saturation)
  □ Rebalance rate (consumer group coordinator metrics)
```

### Phase 7 (42:00 – 45:00): Summary & Extensions

```
60-SECOND CLOSE:

  "We chose a distributed log because payment events fan out to ledger,
   fraud, analytics, and audit with independent replay. 192 partitions
   keyed by account_id with hot-account salting, RF=3, acks=all,
   tiered storage for 7-year compliance. Ledger uses EOS; others
   at-least-once with idempotency. Consumer groups sized to partition
   count; lag derivative alerts; DLT for poison pills."

EXTENSIONS IF TIME (pick one):
  → Schema evolution: BACKWARD only, new optional fields
  → Cross-region: MirrorMaker 2, active-passive failover
  → Stream processing: Flink keyed by account_id for windowed fraud
  → Cost: tiered storage S3 for cold retention (90% disk savings)
```

---

## Part B: Hands-On Exercises

These exercises use **kcat** (formerly kafkacat) and Kafka CLI tools. Run against a local Docker Compose cluster or MSK development cluster.

```
PREREQUISITES
━━━━━━━━━━━━━

  # Docker Compose (Confluent platform quickstart):
  docker compose -f docker-compose-kafka.yml up -d

  # Environment variables (adjust for your cluster):
  export BOOTSTRAP=localhost:9092
  export TOPIC=payments.exercise.v1
```

### Exercise 1: Create Topic and Inspect Metadata

```
GOAL: Create a topic with explicit partition count and RF;
      verify leader/ISR assignment.

  kafka-topics.sh --bootstrap-server $BOOTSTRAP \
    --create \
    --topic $TOPIC \
    --partitions 12 \
    --replication-factor 1 \
    --config retention.ms=604800000 \
    --config min.insync.replicas=1

  kafka-topics.sh --bootstrap-server $BOOTSTRAP \
    --describe --topic $TOPIC

  EXPECTED OUTPUT (annotated):
    Topic: payments.exercise.v1  PartitionCount: 12
    Partition: 0  Leader: 1  Replicas: 1  Isr: 1
    ...

  INTERVIEW TAKEAWAY:
    Partition count is FIXED at create time (increase only via admin).
    Leader handles all reads/writes for that partition.
```

### Exercise 2: Produce Messages with Keys Using kcat

```
GOAL: Observe partition assignment by key.

  # Produce 20 messages with keys account-100 through account-109
  for i in $(seq 1 20); do
    acct="account-$((100 + i % 10))"
    echo "$acct|payment-$i|amount=$((RANDOM % 500))" | \
      kcat -P -b $BOOTSTRAP -t $TOPIC -K'|'
  done

  # kcat partition query — which partition got account-100?
  kcat -C -b $BOOTSTRAP -t $TOPIC -f 'Part:%p Key:%k Val:%s\n' -e -q

  INTERVIEW TAKEAWAY:
    Same key → same partition → ordering guarantee for that key.
    Different keys → spread across partitions (modulo hash collisions).
```

### Exercise 3: Consume from Specific Partition and Offset

```
GOAL: Understand offset as cursor, not deletion.

  # Read partition 0 from beginning, max 5 messages
  kcat -C -b $BOOTSTRAP -t $TOPIC -p 0 -o beginning -c 5

  # Read partition 0 from offset 10
  kcat -C -b $BOOTSTRAP -t $TOPIC -p 0 -o 10 -c 3

  # Read only new messages (end offset)
  kcat -C -b $BOOTSTRAP -t $TOPIC -p 0 -o end

  INTERVIEW TAKEAWAY:
    Messages remain in log after consume. Multiple consumer groups
    each maintain independent offsets.
```

### Exercise 4: Consumer Groups and Lag Inspection

```
GOAL: Run a slow consumer and observe lag growth.

  # Terminal 1 — start consumer group
  kcat -C -b $BOOTSTRAP -t $TOPIC -G exercise-group -o beginning

  # Terminal 2 — produce burst
  for i in $(seq 1 1000); do
    echo "burst-$i" | kcat -P -b $BOOTSTRAP -t $TOPIC
  done

  # Terminal 3 — describe group lag
  kafka-consumer-groups.sh --bootstrap-server $BOOTSTRAP \
    --describe --group exercise-group

  OUTPUT COLUMNS TO KNOW:
    TOPIC  PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID

  INTERVIEW TAKEAWAY:
    LAG = LOG-END-OFFSET - CURRENT-OFFSET per partition.
    Sum of LAG across partitions = total backlog "debt."
```

### Exercise 5: Reset Offsets (Replay Simulation)

```
GOAL: Demonstrate replay — unique to log model.

  # Stop consumer first, then reset to beginning
  kafka-consumer-groups.sh --bootstrap-server $BOOTSTRAP \
    --group exercise-group \
    --topic $TOPIC \
    --reset-offsets --to-earliest \
    --execute

  # Verify
  kafka-consumer-groups.sh --bootstrap-server $BOOTSTRAP \
    --describe --group exercise-group

  INTERVIEW TAKEAWAY:
    Replay enables new fraud model training on historical payments.
    SQS/RabbitMQ cannot do this — key differentiator in interviews.
```

### Exercise 6: Increase Partitions Live

```
GOAL: Practice partition expansion (interview ops question).

  kafka-topics.sh --bootstrap-server $BOOTSTRAP \
    --alter --topic $TOPIC --partitions 24

  kafka-topics.sh --bootstrap-server $BOOTSTRAP \
    --describe --topic $TOPIC | head -20

  WARNING TO STATE IN INTERVIEW:
    Existing keys may move to new partitions on PRODUCE only.
    Old messages stay on original partition — ordering per key
    preserved for new messages after expansion.
```

### Exercise 7: Inspect Under-Replicated Partitions

```
GOAL: Simulate awareness of replication health.

  kafka-topics.sh --bootstrap-server $BOOTSTRAP \
    --describe --under-replicated-partitions

  kafka-topics.sh --bootstrap-server $BOOTSTRAP \
    --describe --unavailable-partitions

  # Broker API versions (sanity check connectivity)
  kafka-broker-api-versions.sh --bootstrap-server $BOOTSTRAP

  INTERVIEW TAKEAWAY:
    Under-replicated ≠ offline. ISR lagging but partition still
    serves reads/writes from leader. Persistent URP → risk on failure.
```

### Exercise 8: Producer Idempotence Smoke Test

```
GOAL: Configure idempotent producer (conceptual — use kafka-console-producer).

  kafka-console-producer.sh --bootstrap-server $BOOTSTRAP \
    --topic $TOPIC \
    --producer-property enable.idempotence=true \
    --producer-property acks=all \
    --producer-property retries=2147483647

  # Type messages; kill producer mid-send; restart
  # With idempotence, no duplicate sequence numbers within PID epoch

  INTERVIEW TAKEAWAY:
    Idempotent producer dedupes broker-side within producer session.
    NOT the same as EOS across consume-process-write — needs transactions.
```

### Exercise 9: Configuring Retention vs Compaction

```
GOAL: Create compacted changelog topic (CDC pattern).

  kafka-topics.sh --bootstrap-server $BOOTSTRAP \
    --create \
    --topic account-state.changelog.v1 \
    --partitions 6 \
    --replication-factor 1 \
    --config cleanup.policy=compact \
    --config min.cleanable.dirty.ratio=0.01

  INTERVIEW TAKEAWAY:
    payments.events → delete retention (time/size)
    account-state → compaction (latest value per key forever)
    Wrong policy = disk fill or lost history.
```

### Exercise 10: Measure End-to-End Latency

```
GOAL: Produce with timestamp, consume and compute lag.

  # Produce with payload timestamp
  TS=$(date +%s%3N)
  echo "{\"ts\":$TS,\"event\":\"ping\"}" | \
    kcat -P -b $BOOTSTRAP -t $TOPIC

  # Consume and compare
  kcat -C -b $BOOTSTRAP -t $TOPIC -o -1 -c 1 -f '%s\n' | \
    python3 -c "
import sys, json, time
m = json.loads(sys.stdin.read())
print('E2E ms:', int(time.time()*1000) - m['ts'])
"

  INTERVIEW TAKEAWAY:
    Kafka latency = producer batching + replication + consumer poll interval.
    linger.ms=5 adds up to 5ms intentionally for throughput.
```

---

## Part C: Partition Sizing & Consumer Math — 15 Practice Problems

Each problem has **unique numbers**. Work them on paper before reading solutions.

---

### Problem 1

```
INGEST: 4,200 events/sec sustained, peak 2.5×
MESSAGE SIZE: 1.5 KB average
TARGET: ≤ 8 MB/s per partition leader
PROCESSING: 30ms per event per consumer thread (single-threaded)

Find: (a) minimum partitions for ingest (b) consumers needed at peak
      if 1 partition = 1 consumer thread (c) bottleneck?
```

**Solution 1:**

```
(a) Peak ingest = 4200 × 2.5 = 10,500 events/sec
    Bandwidth = 10,500 × 1.5 KB = 15.75 MB/s
    Partitions = ceil(15.75 / 8) = 2 → with 10× headroom = 20 partitions

(b) Processing rate per consumer = 1/0.030 = 33.3 events/sec
    At peak: 10,500 / 33.3 = 315 consumers needed

(c) BOTTLENECK: Consumer processing. 20 partitions max 20 parallel
   consumers → 20 × 33.3 = 666 events/sec << 10,500 peak.
   FIX: Increase partitions to ≥ 315 (round 384) OR batch processing
   (100 events in 30ms → 3,333/sec per consumer → 4 consumers at peak)
```

---

### Problem 2

```
TOPIC: order-events, 88 partitions
CONSUMER GROUP: fulfillment, 22 running consumers
INGEST: 6,600 events/sec uniform

Find: (a) partitions per consumer (b) events/sec per consumer
      (c) idle consumers? (d) max parallel consumers useful?
```

**Solution 2:**

```
(a) 88 / 22 = 4 partitions per consumer
(b) 6,600 / 22 = 300 events/sec per consumer
(c) None idle — 22 consumers active
(d) Max useful = 88 (one per partition). Adding consumer 89 → idle
```

---

### Problem 3

```
PEAK: 52 MB/s ingress
PARTITION CAP: 12 MB/s
GROWTH: 4× in 18 months

Find: partitions today and at growth horizon.
```

**Solution 3:**

```
Today: ceil(52 / 12) = 5 → ×10 headroom = 50 partitions
At 4×: 208 MB/s → ceil(208/12) = 18 → ×10 = 180 partitions
Design now with 192 partitions to avoid early rebalancing pain.
```

---

### Problem 4

```
CONSUMER: batch size 250 records, batch processing time 400ms
PARTITIONS: 64
PEAK INGEST: 16,000 events/sec

Find: minimum consumers in group to keep lag stable at peak.
```

**Solution 4:**

```
Throughput per consumer = 250 / 0.4 = 625 events/sec
Consumers needed = ceil(16,000 / 625) = 26 consumers
26 < 64 partitions → 26 active, each handles ~2.5 partitions on average
Stable lag if processing uniform; skewed keys may still hot-spot.
```

---

### Problem 5

```
LAG DEBT: 18,000,000 messages
PROCESS RATE after fix: 2,400 msg/sec aggregate group
INGEST RATE: 900 msg/sec

Find: time to drain lag; steady-state headroom.
```

**Solution 5:**

```
Net drain = 2,400 - 900 = 1,500 msg/sec
Time = 18,000,000 / 1,500 = 12,000 sec = 3 hours 20 minutes
Steady-state headroom = 2400/900 = 2.67× ingest — healthy
```

---

### Problem 6

```
RF=3, 15 brokers, topic needs 120 partitions
RACK AWARENESS: 3 AZs

Find: replicas per broker approximate; any broker limit concern?
```

**Solution 6:**

```
Total replica slots = 120 × 3 = 360
Per broker ≈ 360 / 15 = 24 partition replicas each
Leader count ≈ 120/15 = 8 leaders per broker (if balanced)
Interview: ensure replica.count ≤ brokers for rack spread;
  15 brokers × 3 AZ = 5 brokers/AZ — RF=3 can place one replica per AZ.
```

---

### Problem 7

```
MESSAGE: 800 bytes
TARGET RETENTION: 14 days
DAILY VOLUME: 2.1 billion events
RF=3

Find: raw storage TB; with 25% overhead.
```

**Solution 7:**

```
Daily raw = 2.1B × 800 B = 1.68 TB/day
14-day = 23.52 TB
RF=3 → 70.56 TB
Overhead 25% → 88.2 TB cluster storage for this topic
```

---

### Problem 8

```
HOT KEY: 1 account generates 4,000 events/sec
TOTAL INGEST: 25,000 events/sec
PARTITIONS: 100

Find: hot partition share; salt buckets needed to bring hot partition
      below 500 events/sec if rest is uniform.
```

**Solution 8:**

```
Without salt: hot partition = 4,000/sec (16% of total alone)
Remaining 21,000 / 99 partitions ≈ 212/sec each — OK
Hot partition 4,000 >> 500 target
Salt buckets = ceil(4000/500) = 8 minimum (use 16 for headroom)
After 16-way salt: 4000/16 = 250/sec per salted sub-stream
```

---

### Problem 9

```
CONSUMER GROUP A: 40 consumers, 160 partitions → LAG stable
DEPLOY: rolling restart, 2 min per instance, 40 instances

Find: worst-case rebalance events if no static membership;
      interview mitigation in one line.
```

**Solution 9:**

```
Naive rolling: each restart triggers rebalance → 40 rebalances × ~30s stop
  ≈ 20 minutes degraded throughput during deploy window
Mitigation: cooperative-sticky assignor + static group.instance.id
  → incremental rebalance, single partition handoff at a time
```

---

### Problem 10

```
FIFO REQUIREMENT per user_id
USERS: 50M DAU, peak 80K events/sec
MAX ACCEPTABLE IN-PARTITION RATE: 300/sec (downstream DB limit)

Find: minimum partitions assuming perfect key distribution.
```

**Solution 10:**

```
Partitions ≥ 80,000 / 300 = 267 → round to 288
Interview: real distribution not uniform — add 50% → 432 partitions
```

---

### Problem 11

```
COMPACTED TOPIC: 500M keys, avg value 2 KB, compaction ratio 0.3

Find: approximate compacted size (order of magnitude).
```

**Solution 11:**

```
If every key updated once: 500M × 2 KB = 1 TB
Compaction retains latest only; ratio 0.3 → ~300 GB post-compaction
Interview: compaction is async — disk temporarily higher during clean
```

---

### Problem 12

```
MIRRORMAKER: source 200 partitions, target cluster

Find: partition mapping strategy; ordering guarantee across DC.
```

**Solution 12:**

```
Default MM2: preserve partition index (P47 → P47) for ordering
Consumer in DR reads same key → same partition index → order preserved
Interview: topic rename prefix (source.payments → dr.payments)
```

---

### Problem 13

```
max.poll.records=2000, processing=150ms per record (bug!)
max.poll.interval.ms=300000 (5 min)

Find: max records processable before rebalance kick; is 2000 safe?
```

**Solution 13:**

```
Budget = 300,000 ms / 150 ms = 2,000 records exactly — AT LIMIT
Any GC pause → exceeds max.poll.interval → consumer expelled
2000 max.poll.records is UNSAFE; should be ≤ 500 with 150ms processing
  or reduce processing to 25ms via batch DB writes
```

---

### Problem 14

```
TIERED STORAGE: hot 7 days local, 90 days total retention
Local disk budget: 8 TB per broker, 20 brokers
RF=3, single topic dominates

Find: max daily ingest volume for this topic on this cluster.
```

**Solution 14:**

```
Usable cluster hot storage = 20 × 8 / 3 RF ≈ 53.3 TB (rough)
7-day hot = 53.3 / 7 ≈ 7.6 TB/day max ingest for one RF=3 topic
Interview: tiered storage offloads older segments to S3 — extends retention
  without local disk linear growth
```

---

### Problem 15

```
THREE consumer groups on same topic (120 partitions):
  G1: 30 consumers
  G2: 120 consumers
  G3: 8 consumers

INGEST: 12,000 events/sec

Find: per-consumer load each group; which group limits fan-out scale?
```

**Solution 15:**

```
G1: 120/30 = 4 parts each → 12,000/30 = 400 events/sec per consumer
G2: 1 part each → 12,000/120 = 100 events/sec per consumer
G3: 120/8 = 15 parts each → 12,000/8 = 1,500 events/sec per consumer ← HOT

G3 bottleneck: each consumer handles 15 partitions — likely highest lag
  under load; scale G3 to 120 consumers or optimize G3 processing first
Interview: groups are independent — G2 scaling doesn't help G3
```

---

## Part D: Kafka vs SQS vs RabbitMQ — Scenario Comparisons

Deep comparison for **interview decisions** — not API trivia.

### Scenario 1: Payment Fan-Out to Five Downstream Systems

```
REQUIREMENTS:
  • checkout publishes payment.captured once
  • ledger, fraud, email, analytics, data lake each consume independently
  • audit requires replay of last 90 days when new system onboarded
  • 12K events/sec peak

┌─────────────┬──────────────────────────────────────────────────────────┐
│ System      │ Verdict & reasoning                                      │
├─────────────┼──────────────────────────────────────────────────────────┤
│ Kafka       │ ✓ BEST — one publish, five consumer groups, replay by     │
│             │   offset reset; ordering per account via partition key    │
├─────────────┼──────────────────────────────────────────────────────────┤
│ SQS         │ ✗ Five queues + fan-out (SNS→SQS) = 5× publish ops or    │
│             │   SNS filter complexity; no replay beyond retention;      │
│             │   FIFO queue = 300 msg/s per queue without batching       │
├─────────────┼──────────────────────────────────────────────────────────┤
│ RabbitMQ    │ △ Topic exchange + 5 queues works but no long replay;     │
│             │   competing consumers per queue OK; memory-bound backlog  │
│             │   at 12K/sec requires careful cluster sizing              │
└─────────────┴──────────────────────────────────────────────────────────┘

INTERVIEW SOUND BITE:
  "Fan-out + replay + retention pushes us to a log. I'd still use SQS
   for individual async tasks inside a service (send email job)."
```

### Scenario 2: Image Thumbnail Generation (Embarrassingly Parallel)

```
REQUIREMENTS:
  • Upload triggers one thumbnail job
  • Any worker can process; order irrelevant
  • At-least-once OK; idempotent by image_id
  • 500 jobs/sec peak, 200 KB payload references S3 key

┌─────────────┬──────────────────────────────────────────────────────────┐
│ System      │ Verdict                                                  │
├─────────────┼──────────────────────────────────────────────────────────┤
│ SQS         │ ✓ BEST — zero ops, auto-scale Lambda/ECS, delete on ack  │
├─────────────┼──────────────────────────────────────────────────────────┤
│ RabbitMQ    │ ✓ GOOD — classic work queue, prefetch tuning, DLQ        │
├─────────────┼──────────────────────────────────────────────────────────┤
│ Kafka       │ △ OVERKILL — no multi-subscriber need; retention disk    │
│             │   cost for deleted-work pattern; ops burden unjustified   │
└─────────────┴──────────────────────────────────────────────────────────┘
```

### Scenario 3: Order Pipeline with Strict Per-Order Ordering

```
REQUIREMENTS:
  • Events for order_id must process in sequence
  • Single consumer pipeline per order
  • 3K orders/sec peak, 1 KB messages
  • 24-hour retention sufficient

┌─────────────┬──────────────────────────────────────────────────────────┐
│ SQS FIFO    │ △ POSSIBLE — 300 msg/s per queue; need sharding 10       │
│             │   FIFO queues by hash(order_id) — ops complexity          │
├─────────────┼──────────────────────────────────────────────────────────┤
│ RabbitMQ    │ △ Single queue = ordering but one consumer bottleneck     │
│             │   Consistent-hash exchange → multiple ordered streams     │
├─────────────┼──────────────────────────────────────────────────────────┤
│ Kafka       │ ✓ BEST — key=order_id, partitions scale parallelism       │
│             │   while preserving per-order sequence                     │
└─────────────┴──────────────────────────────────────────────────────────┘
```

### Scenario 4: Startup with 50 Events/Sec and Three Engineers

```
REQUIREMENTS:
  • Event bus for microservices MVP
  • No dedicated infra team
  • Budget-sensitive

VERDICT: SQS + SNS (or RabbitMQ managed CloudAMQP)
  Kafka MSK minimum ≈ $400+/month + on-call expertise
  Interview: "I'd start SQS; migrate to Kafka when replay + throughput
  + multi-team fan-out justify ops tax — typically >5K events/sec or
  regulatory replay requirement."
```

### Scenario 5: Cross-Region Active-Active Writes

```
REQUIREMENTS:
  • Producers in US and EU write same logical stream
  • Consumers in both regions need full history
  • Conflict-free merge not required (events immutable)

┌─────────────┬──────────────────────────────────────────────────────────┐
│ Kafka       │ ✓ MirrorMaker 2 bidirectional; cluster linking (Confluent)│
│             │   Interview: active-active Kafka is HARD — prefer active-  │
│             │   passive + regional topics unless strong CRDT story      │
├─────────────┼──────────────────────────────────────────────────────────┤
│ SQS         │ ✗ Regional queues; no unified log; dual publish burden    │
├─────────────┼──────────────────────────────────────────────────────────┤
│ RabbitMQ    │ ✗ Federation/Shovel fragile at scale; not a global log    │
└─────────────┴──────────────────────────────────────────────────────────┘
```

### Scenario 6: Request-Reply RPC Pattern

```
REQUIREMENTS:
  • Service A calls Service B async, waits for reply correlation_id
  • 200ms SLA

VERDICT: RabbitMQ (direct reply-to) or gRPC — NOT Kafka
  Kafka request-reply anti-pattern: high latency, wrong tool
  Interview: "Kafka for event notification; RPC layer separate."
```

### Scenario 7: Log Compaction for Account Profile Changelog

```
REQUIREMENTS:
  • Latest state per account_id must be recoverable
  • Infinite retention of latest snapshot per key

VERDICT: Kafka compacted topic ONLY among these three
  SQS/RabbitMQ delete on ack — cannot rebuild state from history
```

### Scenario 8: Burst Traffic 100× for 10 Minutes (Flash Sale)

```
REQUIREMENTS:
  • 50/sec normal, 5K/sec burst
  • Consumers must not lose messages
  • Cost-minimize idle capacity

┌─────────────┬──────────────────────────────────────────────────────────┐
│ SQS         │ ✓ Elastic buffer; consumers scale on ApproximateNumberOf   │
│             │   MessagesVisible; pay per request                          │
├─────────────┼──────────────────────────────────────────────────────────┤
│ Kafka       │ ✓ Log absorbs burst if disk sized; consumers catch up lag  │
│             │   Interview: size for burst retention OR throttle producers │
├─────────────┼──────────────────────────────────────────────────────────┤
│ RabbitMQ    │ △ Memory alarms under unbounded burst if consumers slow   │
└─────────────┴──────────────────────────────────────────────────────────┘
```

---

## Part E: Mock Interview Dialogue Snippets

### Snippet 1: Opening — Don't Jump to Kafka

```
INTERVIEWER:
  "Design a message queue for our payment platform."

CANDIDATE (GOOD):
  "Happy to — I'd like to clarify whether we need a work queue
   (one consumer per message, delete on process) or an event log
   (multiple independent readers, replay). Payments usually have
   both patterns: async jobs vs audit/event stream. Which use case
   are we focusing on?"

INTERVIEWER:
  "Multiple services need the same payment events. Audit wants 7-year history."

CANDIDATE:
  "That's a log model. I'll design a distributed commit log — Kafka-class
   semantics — with tiered storage for cost. If you'd rather I use a
   specific product name, I can map to MSK or Confluent Cloud."
```

### Snippet 2: Partition Key Pushback

```
INTERVIEWER:
  "Why partition by account_id and not payment_id?"

CANDIDATE:
  "Ordering requirement drives the key. If downstream ledger must see
   all events for an account in publish order — refund after capture —
   they must share a partition. payment_id gives finer spread but
   breaks account-level ordering. I'd confirm with product: if ordering
   is only per payment_id, that's the better key for even load."
```

### Snippet 3: Exactly-Once Skepticism

```
INTERVIEWER:
  "Can we get exactly-once end to end?"

CANDIDATE:
  "Kafka EOS covers consume-transform-produce within the broker transaction.
   The moment we write to PostgreSQL, true exactly-once needs either
   transactional DB integration or idempotent writes keyed by payment_id.
   I'd propose exactly-once for the ledger path only — 20-30% latency cost —
   and at-least-once with idempotent dedupe for analytics. Pragmatic split."
```

### Snippet 4: Scaling Consumers

```
INTERVIEWER:
  "We added 200 consumers but lag isn't improving. Why?"

CANDIDATE:
  "Consumer count ceiling equals partition count for a single group.
   If the topic has 48 partitions, consumers 49-200 sit idle. I'd check
   kafka-consumer-groups describe — if LAG concentrates on few partitions,
   it's a hot key problem, not consumer count. If LAG uniform, processing
   per record is the bottleneck — batch or optimize DB, don't add consumers."
```

### Snippet 5: Why Not Delete After Consume

```
INTERVIEWER:
  "Isn't it wasteful to keep messages after consumption?"

CANDIDATE:
  "In a queue model, yes — storage is temporary. In a log, retention serves
   replay, audit, and new consumer onboarding. We control cost with
   retention.ms and tiered storage to S3. The waste is a deliberate
   tradeoff for multi-subscriber independence."
```

### Snippet 6: Failure — Broker Down

```
INTERVIEWER:
  "A broker just died. Walk me through what happens."

CANDIDATE:
  "Controller detects failure, elects new partition leaders from ISR only
   if unclean election disabled. Producers refresh metadata, retry in-flight
   batches. In-flight acks=all batches may fail if min ISR not met — producers
   block or error. Consumers may see rebalance if broker hosted group coordinator.
   I'd watch UnderReplicatedPartitions and producer error rate metrics first."
```

### Snippet 7: Schema Evolution

```
INTERVIEWER:
  "How do you evolve payment event schemas?"

CANDIDATE:
  "Avro in Schema Registry with BACKWARD compatibility default — new consumers
   read old data, old consumers ignore new optional fields. Never remove fields
   in v1 topic; create payments.events.v2 for breaking changes with dual-write
   migration window. Producers embed schema ID in wire format — no JSON soup."
```

### Snippet 8: Interviewer Trap — "Kafka Replaces Database"

```
INTERVIEWER:
  "Can we skip PostgreSQL and just use Kafka?"

CANDIDATE:
  "Kafka is not a queryable system of record for OLTP. Compacted topics hold
   latest key state but no ad hoc joins or indexes. I'd keep PostgreSQL as
   ledger of record; Kafka as immutable event history and integration bus.
   CQRS: writes to DB, events to Kafka via outbox — Week 6 pattern."
```

### Snippet 9: Cost Challenge

```
INTERVIEWER:
  "Finance says Kafka is too expensive."

CANDIDATE:
  "Break down: broker compute vs disk vs cross-AZ transfer. Tiered storage
   cuts hot disk 70-90%. Separate analytics cluster prevents OLTP traffic
   interference. Compare TCO to operating five SNS-SQS fan-out pipes plus
   Kinesis for replay — often Kafka wins above 5K events/sec sustained."
```

### Snippet 10: Closing Summary

```
CANDIDATE:
  "To summarize: distributed log keyed by account_id, 192 partitions sized
   for peak ingress and consumer parallelism, RF=3 acks=all for durability,
   independent consumer groups per downstream, at-least-once default with
   EOS on ledger, tiered retention for compliance, lag derivative alerts,
   and DLT for poison messages. Happy to deep dive any box."
```

---

## Part F: Payment Consumer Lag Incident — Expert Analysis (Q1–Q4)

Reference scenario from `Design Kafka.md` Section 9:

```
P1: Payment processing stopped — consumer lag 45 million

Architecture: Kafka 12 brokers, topic payments 120 partitions RF=3
Consumer group payment-processor, 60 consumers, at-least-once

Timeline:
  14:00 — Deploy payment-processor v2.2.0
  14:03 — Lag starts climbing all partitions
  14:08 — Lag 12M, DB connection pool exhausted
  14:12 — Alerts: processing rate 500/sec vs ingest 8000/sec
  14:15 — Rollback deploy — lag still climbing
  14:20 — Discover v2.2.0 changed max.poll.records 500→5000
          but processing still 1 record at a time — poll timeout
```

---

## Question 1: Why Didn't Rollback Fix Lag Immediately?

### The Misconception Interviewers Are Testing

```
╔══════════════════════════════════════════════════════════════════════════╗
║  ROLLBACK FIXES THE BUG — NOT THE BACKLOG                                ║
╟──────────────────────────────────────────────────────────────────────────╢
║  Candidates conflate "stop getting worse" with "return to normal."       ║
║  Lag is INVENTORY of unprocessed messages, not a live error state.       ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### Expert Analysis — Full Chain

When the rollback completed at 14:15, the payment-processor fleet was running v2.1.0 again — the last known good application code. That **did** stop the primary failure mode: consumers were no longer requesting 5,000 records per poll while still processing serially at ~150ms per record, which caused `max.poll.interval.ms` violations and repeated expulsion from the consumer group.

However, three separate mechanisms kept **lag climbing** or made it **appear** to climb after rollback:

**Mechanism 1 — Lag is cumulative debt**

```
At 14:12 measured rates:
  Ingest:     8,000 events/sec (checkout traffic continued)
  Processing:   500 events/sec (effective, during rebalance storm)

  Net accumulation: 7,500 events/sec

  From 14:03 to 14:15 (12 minutes):
    Approximate debt added ≈ 12 × 60 × 7,500 = 5.4 million messages
    (Reported lag 12M at 14:08 — prior accumulation + continued ingest)

  After rollback at 14:15, assume processing restored to 6,000/sec:
    Net drain = 6,000 - 8,000 = still negative 2,000/sec IF ingest unchanged

  Lag STILL CLIMBS until processing rate exceeds ingest rate.
  Rollback alone doesn't flip the inequality if rebalance storm persists.
```

**Mechanism 2 — Rebalance storm inertia**

```
Timeline of consumer group instability:

  14:00  Deploy starts — rolling restart 60 pods over ~8 minutes
  14:03  First pods on v2.2.0 begin exceeding max.poll.interval
  14:04  Consumer coordinator triggers rebalance (Classic or Eager)
  14:05  All 60 consumers stop processing during partition revocation
  14:06  Partitions reassigned; new pods fetch 5000 records, choke again
  14:08  Cycle repeats — effective throughput ~500/sec (mostly idle in rebalance)

  14:15  Rollback complete — but coordinator state is "unstable group"
  14:16  Remaining v2.2.0 pods (if any) or mixed metadata still triggers rebalance
  14:18  session.timeout.ms (default 45s) + rebalance timeout cycles continue

  Even on v2.1.0, the GROUP needs 2-3 clean poll cycles (minutes) to stabilize.
  During stabilization, processing rate stays depressed → lag grows.
```

**Mechanism 3 — Downstream DB connection pool exhaustion (secondary amplifier)**

```
  14:08 Alert: DB connection pool exhausted (100 connections)

  v2.2.0 consumers held connections longer per bloated poll batch:
    5000 records × 1 connection each (bug: no batch commit) = stall

  Rollback stops NEW long-held batches, but:
    • Existing transactions may still drain slowly
    • Pool health lag — waiting threads timeout over 30-60s
    • Processing rate on v2.1.0 still throttled until pool recovers

  This explains "rollback but lag still climbing" even after code fix:
    Application code fixed ≠ infrastructure immediately healthy
```

### Quantitative Drain Estimate (Post-Rollback)

```
Given:
  Lag at peak report: 45,000,000 messages (worst case from title)
  Optimistic post-rollback sustained processing: 6,000/sec
  Ingest sustained: 8,000/sec

  Scenario A — processing < ingest:
    Lag never drains; incident continues until ingest throttled

  Scenario B — processing 6,000, ingest paused to 0 (manual circuit):
    Time to drain 45M / 6000 = 7,500 sec ≈ 2 hours 5 minutes

  Scenario C — processing 10,000 (after scale-out to 120 consumers), ingest 8,000:
    Net 2,000/sec drain → 45M / 2000 = 22,500 sec ≈ 6.25 hours

INTERVIEW ANSWER (concise):
  "Rollback stopped the rebalance trigger from v2.2.0's max.poll.records
   misconfiguration, but 45M lag is inventory. At net positive ingest minus
   process, lag still grows. Even at net negative, drain takes hours. Plus
   DB pool recovery and rebalance stabilization add minutes of continued pain."
```

### ASCII — Lag vs Error Rate

```
  Error rate (misconfig):     ████░░░░░░  drops on rollback ✓
  Rebalance frequency:        ███████░░░  decays over ~5 min after rollback
  DB pool availability:       ██████░░░░  recovers ~1-2 min after rollback
  Consumer LAG (inventory):   ██████████  KEEP CLIMBING until process > ingest
                              then only falls linearly — hours at scale
```

### What the On-Call Should Have Expected

```
REALISTIC EXPECTATIONS POST-ROLLBACK:

  T+0 min   Rollback complete — code path healthy
  T+2 min   Rebalance storm subsiding — processing 3-4K/sec
  T+5 min   DB pool recovered — processing 6K/sec
  T+5+ min  IF scaled to 120 consumers AND batch writes: 10K/sec
  T+hours   Lag visibly decreasing on dashboards

  Communicate to stakeholders:
    "Rollback applied; processing restored; lag peak expected; ETA drain
     4-6 hours unless we scale consumers or throttle producers."
```

---

## Question 2: Root Cause Chain — Full Forensic Trace

### Layer 0 — Precipitating Change

```
CHANGE REQUEST (v2.2.0):
  "Increase consumer throughput by raising max.poll.records from 500 to 5000"

INTENT: Fewer poll loops → higher throughput

MISSING ANALYSIS:
  Processing loop still: for (record : batch) { syncDbWrite(record); }
  No batch insert, no async handoff, no max.poll.interval adjustment
```

### Layer 1 — Primary Technical Failure

```
CONFIG CHANGE:
  max.poll.records: 500 → 5000  (10× records per poll())

PROCESSING TIME MATH:
  Per-record processing: ~150ms (DB write + fraud check)
  Batch time: 5000 × 150ms = 750,000ms = 12.5 MINUTES per poll

KAFKA CONFIG:
  max.poll.interval.ms default: 300,000ms (5 minutes)

  12.5 min > 5 min → CONSUMER HEARTBEAT FAILURE

  Broker coordinator marks consumer DEAD → triggers REBALANCE
```

### Layer 2 — Rebalance Storm Dynamics

```
CLASSIC (EAGER) REBALANCE — worst case:

  Step 1: All consumers revoke ALL partitions (stop processing)
  Step 2: Coordinator runs assignment (Range or RoundRobin)
  Step 3: Consumers re-acquire partitions, fetch offsets

  During Step 1-3 (~5-30 seconds per rebalance):
    Processing rate = ZERO for entire group

  v2.2.0 AMPLIFICATION LOOP:

    ┌─────────────────────────────────────────────────────────┐
    │  Consumer A fetches 5000 records                        │
    │       ↓                                                 │
    │  Processing exceeds 5 min                               │
    │       ↓                                                 │
    │  Coordinator evicts Consumer A → REBALANCE ALL 60       │
    │       ↓                                                 │
    │  Partitions reassigned; Consumer B now has A's partitions│
    │       ↓                                                 │
    │  Consumer B fetches 5000, also times out → repeat       │
    └─────────────────────────────────────────────────────────┘

  Effective group throughput collapses to ~500/sec (measured at 14:12)
  while ingest continues at 8000/sec
```

### Layer 3 — Database Connection Pool Exhaustion

```
CONNECTION PATTERN IN v2.2.0:

  for (record : pollBatch) {          // 5000 iterations
      Connection conn = pool.get();   // blocks if pool empty
      conn.execute(insert);
      conn.close();
  }

  60 consumers × attempted parallel batches → 60 × N connections
  Pool size: 100

  Symptom at 14:08:
    • HikariCP timeout waiting for connection
    • Processing slows further → worsens max.poll.interval breach
    • Positive feedback loop

  PostgreSQL side:
    • pg_stat_activity shows idle in transaction
    • checkout API latency rises (shared DB) — potential blast radius
```

### Layer 4 — Monitoring and Alert Gap

```
WHY P1 DECLARED LATE (hypothesis for interview):

  Alert configured: ConsumerLag > 1,000,000 (absolute threshold)
  Lag crossed 1M only after ~14:07 — 7 minutes after deploy

  MISSING:
    • Alert on d(lag)/dt (derivative) — would fire at 14:04
    • Alert on consumer group rebalance rate
    • Alert on max.poll.interval violations (consumer logs)
    • Canary deploy on 5% consumers with lag SLO gate

  Deploy pipeline:
    No consumer lag check in automated rollback criteria
```

### Layer 5 — Architectural Coupling

```
DESIGN AMPLIFIERS (not root cause, but made incident worse):

  1. Single consumer group on critical path — no isolation between
     fast metadata updates and slow ledger writes

  2. No retry topic — poison or slow records block partition head

  3. 60 consumers on 120 partitions — only 2 partitions each;
     rebalance affects large fraction of keyspace per consumer death

  4. Synchronous DB write in poll thread — violates poll loop discipline
```

### Root Cause Statement (Interview Gold)

```
PRIMARY ROOT CAUSE:
  v2.2.0 increased max.poll.records to 5000 without reducing per-record
  processing time or increasing max.poll.interval.ms, causing consumers
  to exceed the 5-minute poll interval, triggering continuous rebalance
  storms and effective throughput collapse.

CONTRIBUTING FACTORS:
  • Serial per-record DB writes in poll loop (no batching)
  • DB connection pool undersized for misconfigured batch size
  • No lag derivative alerting; no canary consumer deploy
  • Rollback expected to clear lag immediately — operational misconception

NOT ROOT CAUSE (common wrong answers):
  ✗ "Kafka broker failure" — brokers healthy; ingest 8000/sec proves it
  ✗ "Need more partitions" — uniform lag across all partitions
  ✗ "ISR shrink" — would block producers, not consumers specifically
  ✗ "Hot partition" — lag climbed ALL partitions uniformly
```

### Five-Whys Summary

```
WHY lag 45M?        → Processing 500/sec << ingest 8000/sec for 30+ min
WHY processing 500? → Continuous consumer rebalance stops processing
WHY rebalance?      → Consumers exceeded max.poll.interval.ms
WHY exceeded?       → 5000 records × 150ms = 12.5 min per poll batch
WHY deployed?       → Config change without load test or interval math
```

---

## Question 3: Immediate Mitigation — Priority-Ordered Actions

### T+0 to T+5 Minutes — Stop the Bleeding

```
ACTION 1 (P0): HALT ROLLING DEPLOY / CONFIRM ROLLBACK COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Verify all 60 pods running v2.1.0:
    kubectl rollout status deployment/payment-processor
    kubectl get pods -l app=payment-processor -o jsonpath='{..image}'

  If ANY v2.2.0 remains → force rollback again

  WHY FIRST: Continuing mixed versions extends rebalance chaos
```

```
ACTION 2 (P0): SCALE CONSUMERS TO PARTITION COUNT (120)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  kubectl scale deployment/payment-processor --replicas=120

  Effect:
    • 1 partition per consumer → minimizes rebalance blast radius
    • Maximizes parallel processing immediately
    • Each consumer processes smaller partition share

  Caveat: DB pool must handle 120 connections — may need temporary
    pool bump OR staggered scale (60 → 90 → 120 over 3 min)

  Expected processing gain: 6K → 10K/sec if v2.1.0 baseline per consumer
```

```
ACTION 3 (P1): TEMPORARY max.poll.interval.ms INCREASE (TACTICAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Consumer property override (ConfigMap / env):
    KAFKA_MAX_POLL_INTERVAL_MS=900000   # 15 minutes — TEMPORARY

  Rationale: Buys time if any pod still misconfigured; prevents eviction
  during stabilization

  MUST REVERT after incident — masks future poll loop bugs

  kafka-consumer-groups.sh --bootstrap-server $BS \
    --describe --group payment-processor --members --verbose
  Verify all members stable, no constant rejoin
```

### T+5 to T+15 Minutes — Restore Throughput

```
ACTION 4 (P1): THROTTLE NON-CRITICAL PRODUCERS (IF NEEDED)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  If processing still < ingest after scale-out:

  Option A — Rate limit analytics producer (lowest business impact):
    nginx/envoy rate limit on analytics-ingest endpoint

  Option B — Kafka quotas (broker-side):
    kafka-configs.sh --bootstrap-server $BS \
      --alter --entity-type clients --entity-name analytics-producer \
      --add-config producer_byte_rate=1048576

  Goal: Net processing rate POSITIVE for lag drain
  DO NOT throttle checkout producer unless regulatory hold approved
```

```
ACTION 5 (P1): DB CONNECTION POOL EMERGENCY EXPANSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Temporary HikariCP maximumPoolSize: 100 → 200
  PostgreSQL max_connections audit — ensure headroom

  Enable pgbouncer transaction pooling if not already:
    Reduces connection hold time per record

  Kill idle in transaction > 60s:
    SELECT pg_terminate_backend(pid) FROM pg_stat_activity
    WHERE state = 'idle in transaction' AND query_start < now() - interval '60s';
```

```
ACTION 6 (P2): PAUSE SECONDARY CONSUMER GROUPS (OPTIONAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  fraud-scorer and analytics groups compete for broker I/O and disk
  Pause if broker metrics show saturation:
    kafka-consumer-groups.sh --bootstrap-server $BS \
      --group fraud-scorer --execute --action pause-all-partitions
  (Requires kafka 3.x+ pause API or stop those deployments)

  Frees broker fetch bandwidth for payment-processor catch-up
  Tradeoff: fraud delayed — communicate to risk team
```

### T+15 to T+60 Minutes — Verify and Communicate

```
ACTION 7: VALIDATE LAG DERIVATIVE NEGATIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Every 2 minutes:
    kafka-consumer-groups.sh --bootstrap-server $BS \
      --describe --group payment-processor \
      | awk '{sum+=$6} END {print "Total LAG:", sum}'

  Success criteria:
    • Total LAG decreasing for 3 consecutive samples
    • No consumer member churn in --members output
    • Processing rate metric > ingest rate on dashboard

  Stakeholder comms template:
    "Root cause: consumer config regression causing rebalance storm.
     Rollback complete. Scaled to 120 consumers. Lag peaked at 45M;
     draining at ~2K/sec net — ETA 6 hours to normal levels.
     Payments processing live; no data loss (offsets committed pre-crash
     may duplicate — idempotent writes verified)."
```

```
ACTION 8: ENABLE IDEMPOTENCY AUDIT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  During chaos, at-least-once consumers may duplicate process:
    SELECT payment_id, count(*) FROM ledger GROUP BY payment_id HAVING count(*) > 1;

  If duplicates found → quarantine for manual review
  Idempotent UPSERT should make this zero — verify constraint held
```

### Mitigation Decision Tree (ASCII)

```
                    Lag climbing post-deploy?
                              │
                              ▼
                    ┌─────────────────┐
                    │ Rollback app    │ ← ALWAYS first if deploy correlated
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
     Rebalance churn?                Uniform lag all partitions?
     (members flapping)                      │
              │                              ▼
              ▼                    Scale consumers → partition count
     Fix max.poll.records/interval          │
     Scale to partition count               ▼
              │                    Still process < ingest?
              └──────────────┬──────────────┘
                             ▼
                    Throttle non-critical producers
                    Expand DB pool / batch writes
                             │
                             ▼
                    Lag derivative negative? → Monitor drain ETA
```

### What NOT to Do (Interview Points)

```
✗ Delete consumer group offsets — causes reprocess entire retention
✗ Reduce partitions — impossible without migration
✗ Restart all brokers — adds leader election chaos
✗ Increase max.poll.records further — opposite of fix
✗ Assume rollback instant fix — stakeholders misled
```

---

## Question 4: Long-Term Design Changes — Prevent Recurrence

### Pillar 1 — Poll Loop Contract Enforcement

```
PROBLEM: Application team treated max.poll.records as "throughput knob"
         without honoring max.poll.interval.ms constraint

DESIGN FIX — HARD CONTRACT IN CODE:

```java
// Consumer poll loop — enforced framework wrapper
public void pollLoop() {
    long pollStart = System.currentTimeMillis();
    ConsumerRecords<K, V> records = consumer.poll(Duration.ofMillis(1000));
    long budgetMs = maxPollIntervalMs / 2;  // 50% safety margin

    List<V> batch = collectRecords(records, maxPollRecords);
    processBatchWithDeadline(batch, budgetMs - elapsed(pollStart));
    consumer.commitSync();
}
```

```
CI LOAD TEST GATE:
  • Synthetic topic, production message size distribution
  • Deploy candidate must sustain process_rate > 2× peak ingest
    for 15 minutes with zero rebalance events
  • Fail pipeline if consumer coordinator logs rebalance

CONFIG GUARDRAIL (lint rule):
  assert maxPollRecords * p99ProcessTimeMs < maxPollIntervalMs * 0.5
  For this incident: 5000 × 150 = 750000 < 150000 → BUILD FAIL
```

### Pillar 2 — Lag Observability — Derivative Alerts

```
ABSOLUTE LAG ALERT (bad):
  ConsumerLag > 1M → fires at 14:07 (7 min late)

DERIVATIVE ALERT (good):
  rate(ConsumerLag[5m]) > 5000/sec → fires at 14:04 (3 min)

PROMETHEUS EXAMPLE:

  # Lag increasing rapidly
  - alert: PaymentProcessorLagDerivative
    expr: deriv(kafka_consumer_group_lag{group="payment-processor"}[5m]) > 0
          and kafka_consumer_group_lag{group="payment-processor"} > 100000
    for: 2m
    labels:
      severity: P1

  # Rebalance storm proxy
  - alert: ConsumerGroupChurn
    expr: rate(kafka_consumer_group_members{group="payment-processor"}[1m]) > 0.1
    for: 3m
```

```
DASHBOARD ADDITIONS:
  • Process rate vs ingest rate (same chart, two lines)
  • Rebalance count per hour
  • max.poll.interval time budget utilization (% of interval used per poll)
  • DB pool wait time p99
```

### Pillar 3 — Deploy Safety — Canary Consumer Group

```
PATTERN: Blue/Green consumer groups (not just blue/green pods)

  payment-processor-canary (5 consumers, 5 canary partitions)
  payment-processor-main     (115 consumers, 115 partitions)

  Static assignment or cooperative assignor with tagged consumers

  Deploy flow:
    1. Deploy v2.2.0 to canary only
    2. Monitor canary lag derivative for 15 min
    3. Auto-promote or auto-rollback based on SLO

  Partition assignment via:
    group.instance.id prefix or separate consumer group reading
    shadow topic (advanced)

  Interview simplification:
    "Canary 5% of consumers with automated lag gate before full rollout"
```

### Pillar 4 — Retry Topic Isolation

```
PROBLEM: Slow or poison record blocks partition head-of-line

DESIGN:

  payments.main     → happy path consumer (fast batch insert)
  payments.retry.1  → failed records, exponential backoff consumer
  payments.DLT      → manual triage after 5 retries

```python
def process(record):
    try:
        db.batch_upsert(record)
    except TransientError:
        producer.send("payments.retry.1", record)
    except PermanentError:
        producer.send("payments.DLT", record)
    # Always commit offset on main topic after handoff
```

```
BENEFIT: Main partition never blocked by single bad record
         Retry consumers scale independently
```

### Pillar 5 — Database Write Batching

```
ROOT AMPLIFIER FIX:

  BEFORE: 5000 × single-row INSERT = 5000 round trips
  AFTER:  batch INSERT 500 rows × 10 batches = 10 round trips

  Expected per-batch time: 50ms → 5000 records in ~500ms total

  Enables safe max.poll.records=5000 IF batching implemented:
    5000 records / 500ms << 300000ms interval ✓

  Use COPY or multi-row INSERT with idempotent ON CONFLICT DO NOTHING
```

### Pillar 6 — Connection Pool Architecture

```
FIX: Decouple poll thread from DB connection hold time

  poll thread → in-memory queue (bounded) → worker pool (DB writers)

  Poll thread never holds DB connection > 1ms
  Workers sized independently: 40 workers, 100 pool connections

  Backpressure: if queue full, pause poll (reduce max.poll.records dynamically)
```

### Pillar 7 — Capacity Headroom Policy

```
ORG POLICY (document in design review):

  Consumer group max size = partition count
  Steady-state processing capacity ≥ 2× peak ingest
  Partition count reviewed quarterly with growth forecast

  For this architecture:
    Peak ingest 8000/sec → target process capacity 16000/sec
    At 100 records/batch, 50ms batch time → 2000 batch/sec per consumer
    Need 8 consumers minimum at peak → 120 partitions gives 15× headroom ✓
    Incident occurred because REBALANCE zeroed effective capacity, not
    because partition count was wrong
```

### Pillar 8 — Runbook and Game Day

```
QUARTERLY GAME DAY SCENARIO:
  "Inject max.poll.records misconfiguration in staging;
   on-call must diagnose via lag derivative, scale, drain"

RUNBOOK SECTION: "Lag climbing post-deploy"
  1. Correlate deploy timestamp
  2. kafka-consumer-groups describe — uniform vs skewed lag
  3. Check consumer logs for max.poll.interval exceeded
  4. Rollback + scale to partitions + verify DB pool
  5. Communicate drain ETA formula: lag / (process - ingest)

POST-INCIDENT REVIEW OUTPUT:
  • Config change requires load test artifact in ticket
  • Automated lint for poll interval math
  • Canary consumer group in deploy pipeline by Q2
```

### Summary Table — Design Controls

```
┌────────────────────────┬─────────────────────────────────────────────────┐
│ Control                │ Prevents                                        │
├────────────────────────┼─────────────────────────────────────────────────┤
│ Poll loop deadline     │ max.poll.interval violations                    │
│ CI load test gate      │ Deploying untested consumer configs             │
│ Lag derivative alerts  │ 7-minute detection delay                        │
│ Canary consumer group  │ Full-fleet rebalance storms                     │
│ Retry/DLT topics       │ Head-of-line blocking poison pills               │
│ DB batch writes        │ Connection pool exhaustion                      │
│ 2× ingest headroom     │ Lag debt accumulation during transient slowdown │
│ Game day runbooks      │ Operational misconception about rollback        │
└────────────────────────┴─────────────────────────────────────────────────┘
```

---

## Part G: Quick Reference — Production Commands

```
# Consumer lag (THE metric)
kafka-consumer-groups.sh --bootstrap-server $BS \
  --describe --group payment-processor

# Consumer member stability
kafka-consumer-groups.sh --bootstrap-server $BS \
  --describe --group payment-processor --members --verbose

# Topic health
kafka-topics.sh --bootstrap-server $BS \
  --describe --topic payments --under-replicated-partitions

# Broker log dirs disk usage
kafka-log-dirs.sh --bootstrap-server $BS \
  --describe --topic-list payments

# Reset offsets (staging only — never prod without approval)
kafka-consumer-groups.sh --bootstrap-server $BS \
  --group payment-processor --topic payments \
  --reset-offsets --to-datetime 2026-07-06T00:00:00.000 \
  --execute

# kcat consume with metadata
kcat -C -b $BS -t payments -G debug-group -o end -f \
  'Part:%p Off:%o Key:%k TS:%T Val:%s\n'

# Producer perf test (partition sizing validation)
kafka-producer-perf-test.sh --topic payments \
  --num-records 1000000 --record-size 2048 \
  --throughput 10000 --producer-props bootstrap.servers=$BS
```

---

## Part H: Appendix Cross-Reference

```
Design Kafka.md Section          │ This Appendix Part
─────────────────────────────────┼────────────────────────────
Section 3: Interview Walkthrough │ Part A: Timed 45-min script
Section 7: SRE Toolkit           │ Part B: Hands-on exercises
Section 8: Decision Framework    │ Part D: Scenario comparisons
Section 9-10: Incident           │ Part F: Q1-Q4 expert analysis
Section 6: Failure modes         │ Part E: Mock dialogue
                                 │ Part C: 15 math problems
Week 6: Message Queues and Kafka │ Referenced, not duplicated
                                 │ (ISR steps, rebalance protocol)
```

---

*End of appendix — approximately 1,400 lines of interview-focused Kafka design content.*
