# Mock Interview 04 — Design a Distributed Event Streaming Platform (Kafka)

> **Week 15 — Mock Interviews** | 45-minute timed session  
> **Prerequisites:** Week 6 (Message Queues and Kafka), Week 4 (Replication & Consensus), Week 13 (Design Kafka)  
> **Level target:** L5–L6 (Senior / Staff)  
> **Interviewer persona:** Principal Engineer, Platform Infrastructure team

---

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════╗
║   AFTER THIS MOCK INTERVIEW, YOU WILL BE ABLE TO:                ║
╟──────────────────────────────────────────────────────────────────╢
║                                                                  ║
║   1. Run a complete 45-minute interview for "design an           ║
║      internal Kafka-like event streaming platform" —             ║
║      including clarifying questions, capacity math, and          ║
║      a defensible high-level architecture                        ║
║                                                                  ║
║   2. Deep-dive on production Kafka mechanics: partitioning,      ║
║      consumer groups, ISR, exactly-once semantics, retention,    ║
║      and the rebalance protocol — at the level Week 6 taught     ║
║                                                                  ║
║   3. Size a 10M events/sec multi-tenant cluster: partition       ║
║      count, broker fleet, disk, replication factor, and          ║
║      per-tenant quotas without hand-waving                       ║
║                                                                  ║
║   4. Design replay capability for new consumers and              ║
║      disaster recovery without breaking ordering contracts       ║
║                                                                  ║
║   5. Diagnose the four canonical Kafka failure modes:            ║
║      rebalance storm, hot partition, ISR shrink, poison          ║
║      messages — with detection, mitigation, and prevention       ║
║                                                                  ║
║   6. Score your own answer on the 8-dimension rubric and         ║
║      identify the single highest-leverage improvement area       ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Kafka is a message queue with replay"          ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Kafka is a distributed commit log. Messages are NOT       ║
║   deleted on consume. Consumer position is an offset cursor,       ║
║   not message ownership. Partition assignment — not message        ║
║   redistribution — is how scale-out works. See Week 6 Part 1.      ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "10M events/sec = add more brokers"             ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Throughput scales via PARTITIONS (parallelism unit),      ║
║   not broker count alone. Each partition has a per-partition       ║
║   throughput ceiling (~10–50 MB/s). Broker count follows disk      ║
║   and replication layout — not the other way around.               ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Exactly-once is a broker feature"              ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Kafka EOS works WITHIN Kafka (idempotent producer +       ║
║   transactions + read_committed consumers). The moment you         ║
║   write to Postgres or call an external API, you need              ║
║   idempotent consumers. Week 6 Part 5 is explicit on this.         ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Multi-tenant = one topic per tenant"           ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG at 10M events/sec. Thousands of topics explode metadata,   ║
║   rebalance time, and controller load. Shared topics with          ║
║   tenant_id in the key + quotas is the production pattern.         ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Replay = reset offset to beginning"            ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG without planning. Replay re-processes history —            ║
║   downstream must be idempotent. Replay on a compacted topic       ║
║   behaves differently than on an event stream. Retention           ║
║   bounds how far back replay can go.                               ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Problem Statement (Give This to the Candidate)

```
PROMPT (read verbatim at minute 0):

  "You're a senior engineer on the platform team. Design an internal
   event streaming platform — think Kafka — that product teams across
   the company will use instead of building their own message buses.

   Scale:
     • 10 million events per second peak ingest (company-wide)
     • Multi-tenant: 200+ product teams, isolated quotas and ACLs
     • Average event size: 1 KB (JSON); p99 event size: 64 KB
     • Replay: new consumers must be able to read from any point
       within the retention window

   Non-functional:
     • Per-tenant ordering where required (per user_id or order_id)
     • 99.99% availability for produce path
     • Durability: no acknowledged writes lost on single broker failure
     • p99 produce latency < 10ms within a region
     • 7-day default retention; some tenants need 90-day archive

   Out of scope unless candidate asks:
     • Stream processing (Flink) — mention but don't design
     • Cross-region active-active — discuss as extension
     • Schema registry — in scope if candidate raises it

   You have 45 minutes. I'll redirect if we need to go deeper
   on a specific area."
```

---

## 45-Minute Timed Schedule

```
╔══════════════════════════════════════════════════════════════════════╗
║   MINUTE  0–5  │ Requirements clarification                          ║
║   MINUTE  5–12 │ Capacity estimation (10M events/sec)                ║
║   MINUTE 12–18 │ API & data model (topics, keys, schemas)            ║
║   MINUTE 18–28 │ High-level architecture                             ║
║   MINUTE 28–40 │ Deep dive (interviewer picks 2–3 areas)             ║
║   MINUTE 40–45 │ Failure modes, wrap-up, candidate questions         ║
╠══════════════════════════════════════════════════════════════════════╣
║   INTERVIEWER CHECKPOINTS:                                           ║
║   • Minute 5:  candidate must have stated ordering + durability      ║
║   • Minute 12: candidate must have computed ingress bandwidth        ║
║   • Minute 28: architecture diagram must show broker cluster +       ║
║                consumer groups + metadata layer (KRaft/ZK)           ║
║   • Minute 40: candidate must name ≥3 failure modes unprompted       ║
╠══════════════════════════════════════════════════════════════════════╣
║   IF BEHIND AT MINUTE 20: skip detailed API; draw architecture.      ║
║   IF AHEAD AT MINUTE 35: inject constraint (see script minute 32).   ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Interviewer Script

### Minute 0–5: Opening & Requirements

```
INTERVIEWER (minute 0):
  "Thanks for joining. Today you'll design an internal event streaming
   platform at Kafka scale — 10M events/sec, multi-tenant, with replay.
   You drive the first 5 minutes: clarifying questions, requirements,
   scope. I'll jump in if we need to redirect."

  [Wait. Let candidate ask questions. Do NOT answer unless they ask
   directly. Nod, take notes.]

GOOD CANDIDATE QUESTIONS (score 3–4 on Requirements):
  → "What ordering guarantees do tenants need — global, per-key, or none?"
  → "What's the delivery guarantee — at-least-once acceptable, or EOS?"
  → "Is 10M/sec one topic or aggregate across all tenants?"
  → "What's the retention default and max? Archive to cold storage?"
  → "Multi-tenant isolation: noisy neighbor protection — quotas?"
  → "Message size limits? Binary payloads or schema-enforced?"
  → "Read QPS / fan-out — how many independent consumer groups?"
  → "Is this greenfield or migration from existing queues?"

INTERVIEWER PROBES (if candidate is silent after 2 min):
  "What would you prioritize — throughput, ordering, or durability?"
  "Can one tenant's traffic affect another tenant's latency?"

INTERVIEWER (minute 5 — transition):
  "Good. Let's lock scope: aggregate 10M/sec, per-key ordering by default,
   at-least-once with idempotent consumers, 7-day retention with tiered
   archive for longer. Multi-tenant quotas required. Does that match
   what you heard?"
```

### Minute 5–12: Capacity Estimation

```
INTERVIEWER (minute 5):
  "Walk me through the numbers. How big is this system?"

  [Let candidate work on whiteboard. Do NOT interrupt arithmetic
   unless they're stuck for 60+ seconds.]

INTERVIEWER PROBES (if stuck):
  "Start with bandwidth — 10M events × 1 KB."
  "How many partitions do you need given per-partition throughput?"
  "How much disk for 7-day retention with RF=3?"

INTERVIEWER (minute 12 — if candidate missed multi-tenant):
  "200 teams sharing one cluster — how does that change partition count?"
```

### Minute 12–18: API & Data Model

```
INTERVIEWER (minute 12):
  "What does a product team see? APIs, topic model, schemas."

  [Expect: produce/consume APIs, topic naming, partition key contract,
   schema registry mention, admin APIs for quotas.]

INTERVIEWER PROBE:
  "Tenant A wants strict order per order_id. Tenant B wants maximum
   throughput with no ordering. Same cluster — how do topics differ?"

INTERVIEWER (minute 18 — transition):
  "Draw the architecture. Producers through brokers to consumers."
```

### Minute 18–28: High-Level Architecture

```
INTERVIEWER (minute 18):
  "High-level boxes. Don't optimize yet — I want the data flow."

  [Expect: producer → broker cluster → consumer groups; KRaft/ZK;
   schema registry; optional tiered storage / S3 archive.]

INTERVIEWER PROBES:
  "Where does offset state live?"
  "How does a new consumer group replay from 3 days ago?"
  "Where do tenant quotas get enforced?"

INTERVIEWER (minute 28 — transition):
  "Let's go deep. Pick one: partitioning strategy, consumer groups
   and rebalance, or exactly-once semantics."
   [Actually YOU pick based on candidate weakness — see Deep Dive section.]
```

### Minute 28–40: Deep Dive (Interviewer-Directed)

```
INTERVIEWER (minute 28 — choose path):

  PATH A — Partitioning & Hot Partitions:
    "One tenant sends 30% of all traffic keyed by country_code='US'.
     What happens? How do you fix it without breaking their ordering?"

  PATH B — Consumer Groups & Rebalance:
    "A team deploys 50 consumers rolling one pod at a time. Lag spikes
     30 seconds every deploy. Why? Fix it."

  PATH C — ISR & Durability:
    "A broker disk slows down. Walk me through ISR shrink and what
     happens to producers with acks=all, min.insync.replicas=2."

  PATH D — Exactly-Once:
    "Fraud team needs exactly-once from Kafka to their Postgres ledger.
     Can Kafka deliver that end-to-end? Design it."

INTERVIEWER (minute 32 — constraint injection):
  "New requirement: one tenant needs to replay 90 days of events for
   a new ML model. Retention is 7 days on hot storage. What changes?"

INTERVIEWER (minute 37 — second deep dive):
  "Quickly — retention policy: time vs size vs compaction. When do
   you use each?"
```

### Minute 40–45: Failure Modes & Close

```
INTERVIEWER (minute 40):
  "What breaks first in production? Name three failure modes and
   how you'd detect them."

  [Do NOT prompt with "rebalance" or "hot partition" unless silent
   for 30 seconds.]

INTERVIEWER (minute 43):
  "30-second summary: key design decisions and one thing you'd
   ship in v1 vs defer to v2."

INTERVIEWER (minute 45):
  "That's time. Any questions for me?"
```

---

## Candidate Expectations

### Requirements Phase (Score 3+)

```
STRONG CANDIDATE STATES:

  FUNCTIONAL (ranked):
    P0: Durable append-only log; produce and consume APIs
    P0: Per-key ordering within a topic partition
    P0: Independent consumer groups (fan-out)
    P0: Replay by offset or timestamp within retention
    P1: Multi-tenant quotas and ACLs
    P1: Schema evolution (Avro/Protobuf + registry)
    P2: Tiered storage / long-term archive

  NON-FUNCTIONAL (quantified):
    → 10M events/sec peak ingest (~10 GB/s raw)
    → p99 produce latency < 10ms (regional)
    → 99.99% produce availability
    → Durability: RPO=0 for acked writes (RF=3, acks=all, min.insync=2)
    → 7-day hot retention; 90-day cold archive optional

  DESIGN DRIVER (must identify):
    "Partition count and key design determine both throughput ceiling
     and ordering contract — that's the constraint that eliminates
     naive single-topic designs."
```

### Capacity Phase (Score 3+)

```
CANDIDATE MUST DERIVE (order of magnitude OK):

  Ingress:
    10M events/sec × 1 KB = 10 GB/s raw ingress
    With compression (lz4/zstd ~3×): ~3.3 GB/s on disk

  Partitions (Week 6 heuristic):
    Per-partition sustained: ~10 MB/s (conservative)
    10 GB/s / 10 MB/s = 1,000 partitions minimum
    × 3 headroom for skew and growth = ~3,000 partitions
    Round to 4,096 (power of 2) for important shared topics
    OR: per-tenant topics with 64–256 partitions each (fewer tenants
    at high volume — hybrid model)

  Storage (7-day retention, RF=3):
    Daily: 10M × 86400 × 1 KB = 864 TB/day raw
    × 7 days = 6 PB raw
    × RF=3 replication = ~18 PB cluster (before compression)
    With 3× compression: ~6 PB replicated
    → Tiered storage to S3 mandatory; not all on NVMe

  Brokers:
    ~6 PB / 24 TB usable per broker = ~250 brokers (order of magnitude)
    Production: 150–300 brokers across 3 AZs with rack awareness

  SANITY CHECK (score 4):
    Candidate notices 864 TB/day is enormous and proposes:
      → Compression at producer
      → Tiered storage (hot NVMe + cold S3)
      → Not every tenant at peak simultaneously
```

### Architecture Phase (Score 3+)

```
MINIMUM VIABLE DIAGRAM:

  ┌─────────────┐     ┌──────────────────────────────────────┐
  │ Producers   │────►│ Broker Cluster (KRaft controllers)    │
  │ (SDK/API)   │     │  Topics → Partitions → Segments       │
  └─────────────┘     │  RF=3, rack-aware, min.insync.replicas=2│
        │             └───────────┬──────────────────────────┘
        │                         │
        │             ┌───────────▼───────────┐
        │             │ Schema Registry       │
        │             └───────────────────────┘
        │                         │
  ┌─────▼─────┐         ┌─────────▼─────────┐
  │ Admin /   │         │ Consumer Group A   │
  │ Quota Svc │         │ Consumer Group B   │
  └───────────┘         │ Consumer Group C   │
                        └───────────────────┘
                                  │
                        ┌─────────▼─────────┐
                        │ Tiered Storage    │
                        │ (S3 / object store)│
                        └───────────────────┘

  LABELS REQUIRED:
    → Leader/follower per partition (Week 4 / Week 6)
    → __consumer_offsets for offset storage
    → Quota enforcement at broker (produce/fetch byte rate)
```

---

## Capacity Estimation — Worked Solution

```
STEP 1: INGRESS BANDWIDTH
━━━━━━━━━━━━━━━━━━━━━━━━━

  Peak events:     10,000,000 / sec
  Avg event size:  1 KB
  Raw bandwidth:   10 GB/s

  Compression (zstd ~3× at batch):  ~3.3 GB/s written to disk
  Peak factor already in 10M (assume given as peak)

STEP 2: PARTITION COUNT
━━━━━━━━━━━━━━━━━━━━━━

  Per-partition throughput (Week 6): 5–10 MB/s sustained typical

  Minimum partitions = 10 GB/s ÷ 10 MB/s = 1,000

  Adjustments:
    + 50% for key skew (hot partitions)     → 1,500
    + 100% headroom for growth              → 3,000
    Round to 4,096 (operations-friendly)

  Consumer parallelism ceiling = 4,096 consumers per group (max)

  Multi-tenant layout:
    Option A: Shared topics, key = tenant_id || entity_id
    Option B: Dedicated high-volume topics per tenant (top 20 tenants)
    Hybrid (production): B for whales, A for long tail

STEP 3: STORAGE
━━━━━━━━━━━━━━━

  Uncompressed daily volume:
    10M × 86,400 sec × 1 KB = 864 TB/day

  7-day hot retention (compressed ~3×):
    864 × 7 / 3 ≈ 2 PB hot

  Replicated (RF=3):
    2 PB × 3 = 6 PB on cluster (mix of NVMe hot + S3 tiered)

  90-day archive (cold, compressed, RF=1 in S3):
    864 × 90 / 3 ≈ 26 PB S3 (with lifecycle to Glacier for old)

STEP 4: EGRESS (CONSUMER FAN-OUT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Assume 5 independent consumer groups reading full stream:
    Egress ≈ 5 × 3.3 GB/s = 16.5 GB/s cluster read

  This exceeds ingress — broker network sizing must account for
  fan-out. Separate offline analytics cluster is common (Week 13).

STEP 5: METADATA & OPS
━━━━━━━━━━━━━━━━━━━━━━

  4,096 partitions × 200 tenants (shared model) → still ~4K partitions
  KRaft controllers: 3–5 nodes (Week 4 Raft)
  Rebalance time at 4K partitions: minutes without cooperative protocol
  → CooperativeStickyAssignor + static membership mandatory
```

---

## API & Data Model

### Producer / Consumer APIs

```
PRODUCE (HTTP/gRPC wrapper or native Kafka protocol):

  POST /v1/topics/{topic}/records
  {
    "key": "tenant-42|order-991823",     // partition key
    "value": { ... },                     // schema-validated
    "headers": {
      "tenant_id": "42",
      "trace_id": "abc-123",
      "content-type": "application/vnd.company.order.v2+json"
    },
    "timestamp": 1712345678900              // optional
  }

  Response: { "partition": 17, "offset": 9283746291, "timestamp": ... }

CONSUME (via consumer group — SDK, not REST for high throughput):

  subscribe(["payments.events.v1"])
  poll(timeout)
  → records[] with (topic, partition, offset, key, value, headers)
  commit(offsets)  // manual commit after processing

ADMIN:

  POST   /v1/tenants/{id}/topics          // create with quota
  GET    /v1/tenants/{id}/quotas
  POST   /v1/consumer-groups/{g}/offsets/reset  // replay (guarded)
  GET    /v1/topics/{t}/partitions/{p}/lag
```

### Topic Naming & Schema

```
CONVENTION: {domain}.{entity}.{event}.{version}

  Examples:
    commerce.order.created.v1
    commerce.order.created.v1.dlt     // dead-letter
    platform.audit.raw.v1

TOPIC CONFIG (per tenant tier):

  retention.ms:           604800000 (7d) default
  retention.bytes:        -1 (size-unlimited within time)
  cleanup.policy:         delete | compact
  min.insync.replicas:    2
  compression.type:       zstd
  message.timestamp.type: CreateTime

PARTITION KEY CONTRACT (document per topic):

  commerce.order.* → key = order_id
    "Ordering guaranteed per order_id, not globally."

  analytics.clicks.* → key = null (sticky partitioner)
    "No ordering. Maximum throughput."

SCHEMA REGISTRY:

  Subject: commerce.order.created.v1-value
  Compatibility: BACKWARD (new consumers read old data)
  Wire format: magic byte + schema ID + Avro payload
```

### Internal Metadata Model

```
Tenant:
  tenant_id, name, tier (free/pro/enterprise)
  produce_quota_bytes_sec, consume_quota_bytes_sec
  max_partitions, allowed_topics[]

TopicMetadata:
  topic_name, tenant_id, partition_count, replication_factor
  cleanup_policy, retention_ms, key_schema, value_schema

ConsumerGroupState (in __consumer_offsets + ops DB):
  group_id, tenant_id, topic, partition, committed_offset
  member_id, generation_id, assignment[]
```

---

## High-Level Architecture

```
                    MULTI-TENANT EVENT STREAMING PLATFORM
                    ════════════════════════════════════

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                                PRODUCER LAYER                               │
  │                                                                             │
  │    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                        │
  │    │  Java SDK   │  │   Go SDK    │  │    REST     │  (low-volume tenants)  │
  │    │ (idempotent │  └─────────────┘  │   Gateway   │                        │
  │    │  producer)  │                   └─────────────┘                        │
  │    └──────┬──────┘                                                          │
  └───────────┼───────────────────────────────────────────────────────────────┘
              │ mTLS + SASL (tenant ACL, all producer SDKs)
              ▼
  ┌───────────────────────────────────────────────────────┐
  │            BROKER TIER (3 AZs, rack-aware)            │
  │                                                       │
  │  KRaft Controllers (3–5) — metadata, leader election  │
  │                                                       │
  │  Brokers (150–300):                                   │
  │    Topic: shared.events (4096 partitions, RF=3)       │
  │    Topic: tenant-whale-42 (512 partitions, RF=3)      │
  │    Local: NVMe segments (hot)                         │
  │    Remote: Tiered Storage → S3 (cold segments)        │
  │                                                       │
  │  Per-broker enforcement:                              │
  │    quota.produce / quota.consume (tenant principal)   │
  │    max.message.bytes, ACL authorization               │
  └───────────────────────────┬───────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
  ┌───────────────┐  ┌───────────────┐  ┌───────────────────┐
  │ Schema        │  │ Consumer      │  │ Archive Service   │
  │ Registry      │  │ Groups (N)    │  │ (S3/Glacier 90d)  │
  │ (Avro/Proto)  │  │ independent   │  │ replay bootstrap  │
  └───────────────┘  │ offset cursors│  └───────────────────┘
                     └───────────────┘

PRODUCE PATH (numbered):
  1. Producer serializes via schema registry
  2. Partition = hash(key) % num_partitions
  3. Batch → partition leader broker
  4. Leader appends segment; replicate to ISR followers
  5. acks=all: wait min.insync.replicas acks
  6. Return (partition, offset) to producer

CONSUME PATH:
  1. Consumer joins group → coordinator assigns partitions
  2. Fetch from leaders at committed offset
  3. Process batch
  4. commit offset to __consumer_offsets (after process)
  5. Repeat

REPLAY PATH:
  1. New consumer group registers
  2. auto.offset.reset=earliest OR admin resets to timestamp
  3. Consumer reads from offset 0 (or T-3days) — within retention
  4. For beyond retention: restore from S3 archive → temp topic
```

---

## Deep Dive — Interviewer Reference

### 1. Partitioning Strategy

```
PARTITION KEY DESIGN (Week 6 Part 3):

  hash(key) % num_partitions → partition assignment

  Multi-tenant shared topic:
    key = tenant_id + "|" + entity_id
    → spreads tenants; ordering per entity within tenant

  HOT PARTITION SCENARIO:
    Tenant keys by country_code → all "US" → one partition

  FIXES (trade-offs stated):
    A) Composite key: country + hash(entity_id) % 16
       → spreads load; LOSES strict per-country ordering
    B) Dedicated topic for hot tenant with 512 partitions
    C) Rate limit at producer; broker quota per tenant
    D) Salt in key for known hot entities (bot accounts)

  PARTITION COUNT IS IMMUTABLE DOWNWARD:
    Cannot reduce. Adding partitions changes hash mapping.
    Over-provision day 1: 256–4096 for shared topics.

  INTERVIEW SCORE 4:
    Candidate mentions per-partition lag monitoring, not topic average.
```

### 2. Consumer Groups & Rebalance Protocol

```
CONSUMER GROUP MODEL (Week 6 Part 4):

  Partitions ÷ consumers in group = max parallelism
  4096 partitions, 200 consumers → ~20 partitions each
  4096 partitions, 5000 consumers → 4096 idle

  OFFSET COMMIT:
    Pattern B (correct): poll → process → commit
    Stored in __consumer_offsets (compacted topic)

  EAGER REBALANCE (legacy):
    All consumers REVOKE → stop processing → reassign → resume
    Stop-the-world. Duration scales with partition count.

  COOPERATIVE REBALANCE (Kafka 2.4+):
    CooperativeStickyAssignor — only moving partitions revoked
    10× less impact. MANDATORY at this scale.

  STATIC MEMBERSHIP (group.instance.id):
    Pod restart within session.timeout → same identity
    No rebalance on rolling deploy. Critical for K8s.

  REBALANCE STORM SCENARIO (interview favorite):
    Symptom: 30s lag spike every deploy
    Cause: 200 pods rolling → 200 rebalances × stop-the-world
    Fix:
      1. CooperativeStickyAssignor
      2. group.instance.id per pod
      3. session.timeout.ms > pod restart time
      4. Reduce max.poll.records if poll loop timeout triggers rebalance

  SLOW POLL LOOP:
    Processing > max.poll.interval.ms → consumer kicked → rebalance
    → another consumer gets slow message → kicked → loop
    Fix: reduce batch size; async processing + manual commits
```

### 3. ISR (In-Sync Replicas)

```
REPLICATION MODEL (Week 6 Part 6):

  RF=3: 1 leader + 2 followers per partition
  ISR = replicas caught up within replica.lag.time.max.ms (30s)

  acks=all + min.insync.replicas=2:
    Write committed when leader + 1 follower ack
    Leader fails → new leader elected from ISR only
    unclean.leader.election.enable=false → no data loss
      (may block produce if ISR shrinks to 1)

  ISR SHRINK SCENARIO:
    Follower disk IO slow → falls out of ISR
    ISR = {leader} only (1 member)
    min.insync.replicas=2 → produce requests FAIL
    Symptom: "Kafka is down" but brokers are up
    Detection: UnderReplicatedPartitions, IsrShrinksPerSec
    Mitigation:
      → Replace/fix slow broker
      → Temporarily lower min.insync.replicas (EMERGENCY ONLY)
      → rack-aware assignment so ISR spans AZs

  CONNECTION TO WEEK 4:
    ISR overlap resembles quorum — committed offset on majority
```

### 4. Exactly-Once Semantics

```
WITHIN KAFKA (Week 6 Part 5):

  Idempotent producer (enable.idempotence=true):
    PID + sequence number per partition → broker dedupes
    Exactly-once to SINGLE partition per producer session

  Transactions (transactional.id):
    Atomic write across partitions
    sendOffsetsToTransaction — atomic consume-process-produce
    Consumer: isolation.level=read_committed

  Cost: 2–3× latency, operational complexity

ACROSS BOUNDARY (the interview trap):

  consumer → write Postgres → commit offset

  Crash between PG write and offset commit → duplicate on restart

  CORRECT DESIGN:
    at-least-once + idempotent consumer
    PG: UNIQUE(event_id) + INSERT ... ON CONFLICT DO NOTHING
    OR: transactional outbox (Week 6) for PG + Kafka atomicity

  EOS fraud ledger answer:
    "Kafka transactions for Kafka-to-Kafka pipeline stages.
     For Postgres: idempotent upsert on event_id.
     I would NOT claim Kafka alone delivers end-to-end EOS."
```

### 5. Retention & Replay

```
RETENTION POLICIES:

  delete (time/size):
    log.retention.ms = 7 days
    Segments deleted whole — not individual messages
    Bounds replay window

  compact (changelog):
    Keep latest value per key
    For: config, CDC state, KTables
    NOT for infinite event history

  TIERED STORAGE:
    Hot: NVMe on broker (recent segments)
    Cold: S3 (older segments, still fetchable)
    Enables 90-day replay without 90-day NVMe

  REPLAY MECHANICS:
    New consumer group + auto.offset.reset=earliest
    OR: offsetsForTimes(timestamp) → seek
    OR: Admin reset offsets (audit logged, tenant-scoped)

  REPLAY SAFETY:
    Downstream MUST be idempotent
    Rate-limit replay consumers (don't DDoS own DB)
    Separate replay consumer group quota
```

---

## Failure Modes

### 1. Rebalance Storm

```
FAILURE:       Rolling deploy triggers cascading rebalance
SYMPTOM:       Consumer lag spikes 30–120s every deploy; effective
               throughput drops 50–80%
DETECTION:     Rebalance rate metric; JoinGroup latency;
               correlated with deploy timestamps
BLAST RADIUS:  All partitions in consumer group pause
MITIGATION:    CooperativeStickyAssignor; static membership;
               stagger deploys; increase session.timeout.ms
PREVENTION:    Load test consumer with production batch sizes;
               preStop hook calls consumer.close()
```

### 2. Hot Partition

```
FAILURE:       Skewed partition key concentrates 30%+ traffic on one partition
SYMPTOM:       Single partition lag while others idle; produce latency p99
               spike for one key space
DETECTION:     Per-partition lag dashboard; per-partition byte rate
BLAST RADIUS:  One tenant or entity type; ordering preserved but delayed
MITIGATION:    Salt key; dedicated topic; producer rate limit
PREVENTION:    Partition key review in topic onboarding; load tests
               with realistic key distribution
```

### 3. ISR Shrink

```
FAILURE:       Followers fall out of ISR (disk, network, GC pause)
SYMPTOM:       produce latency → timeouts; NotEnoughReplicasException
DETECTION:     UnderReplicatedPartitions; min.isr violations;
               IsrShrinksPerSec broker metric
BLAST RADIUS:  All topics with affected partitions; write path blocked
               if min.insync.replicas=2 and ISR=1
MITIGATION:    Fix/replace broker; reassign partitions; emergency
               min.insync.replicas=1 (data loss risk — document)
PREVENTION:    Disk latency alerts; rack-aware RF=3; unclean election off
```

### 4. Poison Message

```
FAILURE:       One message causes infinite processing failure
SYMPTOM:       Single partition lag grows forever; consumer repeatedly
               crashes or times out on same offset
DETECTION:     Lag on one partition only; DLT topic growth zero;
               error logs with same offset
BLAST RADIUS:  One partition stalled; ordering blocked for that key
MITIGATION:    Skip to DLQ after N retries; quarantine offset;
               manual fix and seek
PREVENTION:    max.message.bytes at producer; schema validation;
               DLQ topic per main topic (payments.events.v1.dlt);
               NEVER infinite retry on main consumer loop
```

---

## Rubric Scoring — Problem-Specific Criteria

```
Score each dimension 1–4. See Interview Rubric.md for general criteria.

DIMENSION 1 — REQUIREMENTS (Kafka-specific green flags):
  ✓ Asks ordering scope (per-key vs global)
  ✓ Clarifies 10M/sec aggregate vs single topic
  ✓ Identifies multi-tenant noisy neighbor as design driver
  ✗ Designs one topic per tenant for all 200 teams

DIMENSION 2 — CAPACITY (Kafka-specific):
  ✓ Derives 10 GB/s ingress and partition count from per-partition limit
  ✓ Calculates 7-day storage with RF=3; notices PB scale
  ✓ Proposes tiered storage / compression
  ✗ "We'll add brokers" without partition math

DIMENSION 3 — API & DATA MODEL:
  ✓ Topic naming, partition key contract, schema registry
  ✓ DLQ topic pattern mentioned
  ✗ REST-only consume at 10M/sec

DIMENSION 4 — ARCHITECTURE:
  ✓ KRaft/ZK, ISR, consumer groups, tiered storage
  ✓ Quota enforcement point identified
  ✗ Single broker diagram

DIMENSION 5 — DEEP DIVE:
  ✓ Rebalance cooperative + static membership
  ✓ ISR + min.insync.replicas interaction
  ✓ EOS within vs across Kafka boundary
  ✗ "Kafka guarantees exactly-once to database"

DIMENSION 6 — TRADE-OFFS:
  ✓ Shared vs dedicated topics for whales
  ✓ at-least-once + idempotent vs Kafka transactions cost
  ✓ delete vs compact retention

DIMENSION 7 — FAILURE MODES:
  ✓ All four canonical modes with detection
  ✓ Per-partition lag (not topic average)

DIMENSION 8 — COMMUNICATION:
  ✓ States ordering contract explicitly
  ✓ Time management; summarizes at minute 43

SCORING WORKSHEET:

  Dimension                          │ Score (1-4) │ Notes
  ───────────────────────────────────┼─────────────┼──────
  1. Requirements & Scope            │             │
  2. Capacity Estimation             │             │
  3. API & Data Model                │             │
  4. High-Level Architecture         │             │
  5. Deep Dive                       │             │
  6. Trade-offs & Alternatives       │             │
  7. Failure Modes & Reliability     │             │
  8. Communication & Structure       │             │
  ───────────────────────────────────┼─────────────┼──────
  TOTAL                              │    /32      │

  25–28: Strong L6 bar for infra/platform roles
  20–24: Interview-ready; drill deep dive timing
  15–19: Revisit Week 6 partitions, ISR, rebalance
```

---

## Expert Answer — Full 45-Minute Narrative

```
MINUTE 0–5 — REQUIREMENTS

  "Before I draw anything, I want to confirm scope.

   Functional P0: append-only durable log, produce/consume APIs,
   per-key ordering, independent consumer groups for fan-out, replay
   within retention, multi-tenant ACLs and quotas.

   Non-functional: 10M events/sec peak (~10 GB/s), p99 produce < 10ms,
   99.99% availability, no data loss on single broker failure,
   7-day default retention with optional 90-day archive.

   I'll assume at-least-once delivery with idempotent consumers as
   the default; exactly-once within Kafka via transactions where
   teams explicitly need it.

   Design driver: partition count and key design — they set the
   throughput ceiling AND the ordering contract. Does that match?"

MINUTE 5–12 — CAPACITY

  "10M events/sec × 1 KB = 10 GB/s ingress. With zstd compression
   at batch level, ~3.3 GB/s on disk.

   Partitions: ~10 MB/s per partition sustained → 1,000 minimum,
   ×3 for skew and growth → 4,096 partitions on shared high-volume topics.

   Storage: 864 TB/day raw. Seven days compressed hot ≈ 2 PB,
   ×RF=3 ≈ 6 PB cluster — tiered storage to S3 is mandatory, not optional.

   Five consumer groups reading full stream → ~16 GB/s egress.
   I'd consider a separate offline cluster for analytics fan-out."

MINUTE 12–18 — API & DATA MODEL

  "Topic naming: domain.entity.event.version. Partition key documented
   per topic — order_id for commerce, null for click analytics.

   Schema registry with backward-compatible Avro. Admin API for tenant
   quotas. DLQ topic suffix .dlt for poison messages.

   Offsets in __consumer_offsets; replay via new consumer group or
   timestamp seek — guarded admin API for reset."

MINUTE 18–28 — ARCHITECTURE

  [Draw diagram from Architecture section]

  "KRaft for metadata — no ZooKeeper dependency. Brokers rack-aware
   across 3 AZs. RF=3, min.insync.replicas=2, acks=all.

   Producers use idempotent producer by default. Quotas enforced at
   broker per tenant principal. Tiered storage: NVMe hot, S3 cold.

   New consumer group for replay; beyond 7 days, bootstrap from
   S3 archive into temporary replay topic."

MINUTE 28–40 — DEEP DIVE

  "Deploy rebalance storm: eager protocol stops the world on every pod
   restart. Fix: CooperativeStickyAssignor, group.instance.id for
   static membership, session.timeout tuned to K8s preStop.

   Hot partition: bad key like country_code. Fix with composite key
   or dedicated topic for whale tenant. Monitor per-partition lag.

   ISR shrink: slow follower → ISR={leader} → min.isr=2 blocks writes.
   Fix broker disk; never enable unclean leader election in prod.

   Exactly-once to Postgres: Kafka transactions don't cross the boundary.
   Idempotent consumer with UNIQUE(event_id). Outbox pattern if they
   need atomic DB write + publish.

   90-day replay: tiered storage + S3 archive; replay service loads
   into temp topic with rate limits."

MINUTE 40–45 — FAILURE MODES & CLOSE

  "Four things break first: rebalance storm on deploy, hot partition
   from bad keys, ISR shrink blocking producers, poison message stalling
   one partition. Detection: per-partition lag, IsrShrinks, rebalance
   rate, DLT growth.

   V1: shared cluster, quotas, tiered storage, cooperative rebalance,
   schema registry, DLQ pattern. V2: cross-region MirrorMaker, Flink
   platform, self-serve topic provisioning UI."
```

---

## Debrief Guide

```
FOR THE INTERVIEWER (post-session, 10 minutes):

  1. Score the 8 dimensions on the worksheet — specific quotes as evidence
  2. Identify the single lowest dimension → assign Week 6 re-read if Deep Dive < 3
  3. Ask candidate: "What would you do differently with 5 more minutes?"
  4. Share one thing they did better than the expert narrative
  5. Assign focus: rebalance protocol if deploy scenario failed;
     ISR if durability hand-waved; idempotent consumer if EOS wrong

FOR THE CANDIDATE (self-debrief):

  □ Did I ask about ordering and delivery guarantees before drawing?
  □ Did I compute 10 GB/s and derive partition count?
  □ Did I mention cooperative rebalance AND static membership?
  □ Did I distinguish EOS within Kafka vs external systems?
  □ Did I name per-partition lag monitoring?
  □ Did I reach deep dive before minute 30?

COMMON FAILURES AT L5 BAR:

  → Treating Kafka as a queue (message deleted on consume)
  → No partition count math — just "horizontal scale"
  → Missing tiered storage at PB scale
  → Claiming exactly-once to Postgres via Kafka transactions alone
  → Topic-per-tenant for 200 teams (metadata explosion)

STRETCH QUESTIONS FOR REPEAT PRACTICE:

  → Design cross-region active-active with conflict resolution
  → Add Flink stream processing with EOS across stages
  → Migrate 50 teams from RabbitMQ with zero downtime
  → Tenant noisy neighbor bypasses quota — incident response
```

---

## Key Takeaways

```
1. Kafka is a log, not a queue — partitions are the unit of order,
   parallelism, and replication. Size them once, carefully.

2. 10M events/sec → ~10 GB/s → ~4,096 partitions and PB-scale storage.
   Compression and tiered storage are not optional extras.

3. Multi-tenant at scale = shared topics + quotas + ACLs, not
   one topic per tenant.

4. Rebalance storm is the #1 operational surprise — cooperative
   sticky assignor and static membership are production requirements.

5. Exactly-once stops at the Kafka boundary — idempotent consumers
   and outbox pattern handle external systems (Week 6 Part 5).

6. Replay requires retention + idempotent downstream + rate limits.
   Archive to S3 extends replay beyond hot window.

7. Monitor per-partition lag, not topic averages — hot partitions
   hide in aggregates.
```

---

## Targeted Reading

```
REQUIRED (before retry):
  → Week 6: Message Queues and Kafka.md — Parts 3–6 (partitions,
    consumer groups, EOS, ISR)
  → Week 13: Design Kafka.md — capacity and interview framing
  → Interview Rubric.md — 8 dimensions and time template

OPTIONAL (deepen):
  → DDIA Chapter 11 (Stream Processing)
  → Confluent: Tiered Storage, Cooperative Rebalance blogs
  → Jay Kreps: "The Log" essay
  → Kafka documentation: Replication, Configuration (min.insync.replicas)
```
