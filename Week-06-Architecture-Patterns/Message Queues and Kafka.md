# Week 6, Topic 1 — Message Queues & Streaming (Kafka Deep Dive)

> The connective tissue under everything we just built. CQRS read models, sagas, outbox, CDC — all of them assume a streaming substrate. This module makes that substrate first-class.



Same density as the database scaling module. Same teaching contract: every section answers *what do I run, what do I look at, what's the bug nobody warned me about.*

---

## Learning Objectives

```
After this module, you will be able to:
  1. Choose queue vs log semantics for a workload and justify the tradeoff
  2. Explain Kafka partitions, consumer groups, ISR, and rebalance protocol
  3. Design idempotent producers, transactional outbox, and idempotent consumers
  4. Diagnose consumer lag, rebalance storms, and under-replicated partitions
  5. Compare Kafka vs SQS vs RabbitMQ for AWS-centric architectures
```

---

## Wrong Mental Models (Destroy These First)

```
MENTAL MODEL #1: "Kafka is a message queue"
  WRONG. Kafka is an append-only distributed log with replay. Queues delete
  messages on ack; logs retain by policy. Design consumers accordingly.

MENTAL MODEL #2: "More partitions always means more throughput"
  WRONG. Each partition is ordered and single-leader. Too many partitions
  increases rebalance cost, file handles, and end-to-end latency variance.

MENTAL MODEL #3: "Exactly-once Kafka means my app is exactly-once"
  WRONG. Kafka EOS covers producer+broker+consumer protocol boundaries.
  Your side effects (DB writes, API calls) still need idempotency keys.

MENTAL MODEL #4: "Consumer lag is always a consumer problem"
  WRONG. Lag rises from slow processing, skewed keys, broker disk IO,
  under-replicated partitions, or rebalance storms — diagnose before scaling.

MENTAL MODEL #5: "Delete the message after processing"
  WRONG. In a log, you commit offsets; retention is time/size policy.
  Treating Kafka like SQS causes replay bugs and wrong capacity planning.
```

---

## Part 0: Why This Module Exists

### Foundation

Every distributed system eventually grows a backbone of asynchronous events: orders flowing to fulfillment, clicks flowing to analytics, writes flowing to search indexes, audit logs flowing to compliance. The naive implementations of this — direct HTTP calls, database polling, "let's just use SQS" — work until they don't, and the failure modes are spectacular: lost messages during deploys, duplicate charges, fan-out storms, head-of-line blocking that takes down checkout because the recommendations service is slow.

Kafka (and its cousins: Pulsar, Kinesis, Redpanda, Warpstream) solved this at FAANG scale and the patterns leaked downward. Today, if you cannot reason about partitions, consumer groups, offset commits, exactly-once semantics, and the rebalance protocol, you cannot operate any modern event-driven system.

By the end of this module you will:

1. Choose between a **queue** (SQS, RabbitMQ) and a **log** (Kafka) based on the access pattern, not the brand name.
2. Design a partition key that doesn't create hot partitions or break ordering.
3. Reason about the four delivery guarantees (at-most-once, at-least-once, effectively-once, exactly-once) and what each costs.
4. Avoid the four operational landmines: rebalance storms, consumer lag explosions, poison messages, and ISR collapse.
5. Implement the transactional outbox pattern correctly (it's harder than it looks).
6. Walk an interviewer from "we have a monolith with cron jobs" to "we have a streaming platform" without hand-waving.


**Prerequisite mental model.** A queue is a *line*: messages enter, consumers take them, they're gone. A log is a *tape*: messages are appended, consumers read at their own pace, the tape persists. Everything else is consequence.

---

## Part 1: Queues vs Logs — The Distinction That Decides Everything

```plaintext
THE QUEUE MODEL (SQS, RabbitMQ classic, ActiveMQ):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Producer ─► [ msg1, msg2, msg3, msg4 ] ─► Consumer
                                              │
                                              ▼
                                          ack → message DELETED

  Properties:
   - Message lifetime = "until consumed."
   - Consumer pulls, processes, acks. Broker deletes.
   - Multiple consumers compete; each message goes to ONE.
   - Order: usually not guaranteed (SQS standard); FIFO
     queues exist but have throughput limits.
   - Replay: impossible. Once acked, gone forever.
   - Storage: small (the backlog). Brokers optimize for
     low-latency hand-off, not retention.

  Best for:
   - Work distribution (process this job exactly once).
   - Decoupling producer/consumer rate.
   - Tasks where "did it get done?" matters more than
     "what was the exact sequence?"


THE LOG MODEL (Kafka, Pulsar, Kinesis, Redpanda):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Producer ─► [ m1 m2 m3 m4 m5 m6 m7 m8 m9 ... ] (immutable log)
                ▲              ▲           ▲
                │              │           │
              consumer-A    consumer-B   consumer-C
              offset=2      offset=5     offset=8
              (analytics)   (search)     (audit)

  Properties:
   - Message lifetime = retention policy (hours to forever).
   - Consumers read at their own pace. Position = offset.
   - Multiple INDEPENDENT consumer groups read the SAME
     messages. No competition between groups.
   - Order: guaranteed within a partition.
   - Replay: trivial. Reset offset, re-read.
   - Storage: large (all retained messages). Brokers
     optimize for sequential disk I/O.

  Best for:
   - Event-sourcing (the log IS the source of truth).
   - Multi-consumer fan-out (one event, N independent reactions).
   - Replay for new use cases ("compute this metric over
     the last 30 days of events").
   - Stream processing.
```

```plaintext
THE DECISION TABLE:
━━━━━━━━━━━━━━━━━━

  Need                                       Pick
  ─────────────────────────────────────────  ────────────
  "Process this job, only one worker"        Queue (SQS)
  "Send this email, retry until delivered"   Queue
  "Notify all interested services"           Log (Kafka)
  "Stream of clicks, analytics + ML + audit" Log
  "I want to replay last week's events"      Log
  "I want strict ordering per user"          Log (per-key)
  "I want millions of independent consumers" Pub/sub broker
                                             (Pulsar, NATS)
  "I want 100ms end-to-end, no replay"       Queue or
                                             pub/sub
  "I want the message gone after consumed"   Queue


THE SUBTLE ONE — KAFKA IS NOT A QUEUE.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  People say "Kafka queue" all the time. It is wrong and
  it leads to design errors.

  - Kafka does not delete messages on consume.
  - Kafka does not push to consumers; consumers pull.
  - Kafka does not redistribute messages on consumer death;
    it reassigns PARTITIONS.

  If your mental model is "queue with replay," you'll hit
  these pain points:
   - Trying to ack individual messages → there is no such
     thing. There is only "advance offset to N."
   - Trying to scale consumers beyond partition count →
     the extras sit idle.
   - Trying to delete a "processed" message → impossible
     except by retention or compaction.
```

---

## Part 2 (continued): Kafka's Storage Model (the foundation for everything)

You cannot reason about Kafka's failure modes without understanding what is on disk. Most operational disasters trace back to misunderstanding *where data lives* and *who owns its lifecycle*.

```plaintext
THE PHYSICAL LAYOUT:
━━━━━━━━━━━━━━━━━━

  Cluster
    └── Topic (logical name, e.g. "orders")
           └── Partition 0  ─► /var/kafka/orders-0/
           └── Partition 1  ─► /var/kafka/orders-1/
           └── Partition 2  ─► /var/kafka/orders-2/
                              │
                              ├── 00000000000000000000.log    (segment)
                              ├── 00000000000000000000.index
                              ├── 00000000000000000000.timeindex
                              ├── 00000000000532814821.log    (segment)
                              ├── 00000000000532814821.index
                              └── 00000000000532814821.timeindex


  THE PARTITION IS THE UNIT OF EVERYTHING:
   - Replication: a partition has N replicas across brokers.
   - Ordering: ordered within partition, not across partitions.
   - Parallelism: max parallel consumers in a group =
     partition count.
   - Throughput: per-partition limit ~10-50 MB/s sustained.


  THE SEGMENT IS THE UNIT OF DELETION:
   - A partition is a sequence of segment files.
   - Active segment receives appends. Closed segments are
     immutable.
   - Retention policy deletes WHOLE SEGMENTS, not individual
     messages. This is why "delete one message" doesn't
     exist in the API — wrong granularity.
   - segment.bytes (default 1GB), segment.ms (default 7d).
     Closes a segment when either threshold hit.


  THE OFFSET IS THE UNIT OF READING:
   - Monotonically increasing per-partition integer.
   - Assigned by leader on write.
   - Consumers track position by offset.
   - Offsets are NOT comparable across partitions.


THE WRITE PATH (memorize this):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Producer
     │
     │  send(topic, key, value)
     ▼
  Producer client
     │
     │  1. Serialize key and value (Avro/Protobuf/JSON).
     │  2. Compute partition: hash(key) % num_partitions
     │     OR sticky/round-robin if key is null.
     │  3. Append to in-memory batch for that partition.
     │  4. When batch full OR linger.ms elapses, send.
     ▼
  Broker (partition leader)
     │
     │  5. Append to active segment file (mmap).
     │  6. fsync depends on flush.messages / flush.ms
     │     (DEFAULT: NOT per-message — relies on replicas
     │      and OS page cache).
     │  7. Replicate to followers in ISR (in-sync replicas).
     │  8. ACK to producer based on acks setting.
     ▼
  Followers in ISR
     │
     │  9. Pull from leader, append, fsync per their config.


  THE FOUR "acks" SETTINGS (memorize):

   acks=0     fire-and-forget. Producer doesn't wait. Loses
              data on broker failure. Throughput champion.
              Use for: high-volume metrics where loss is OK.

   acks=1     leader writes locally and acks. If leader
              fails before replicating, message lost.
              DEFAULT in some clients, dangerous default.

   acks=all   leader waits for all in-sync replicas. RPO=0
              if min.insync.replicas > 1. The right answer
              for important data.
              ALSO REQUIRES: min.insync.replicas >= 2 to
              actually be safe (see Part 7).
```

```plaintext
THE READ PATH:
━━━━━━━━━━━━━

  Consumer
     │
     │  poll()
     ▼
  Consumer client
     │
     │  1. Send Fetch request to partition leader for
     │     each assigned partition with current offset.
     ▼
  Broker
     │
     │  2. Look up segment file containing offset (binary
     │     search on .index file).
     │  3. mmap segment, sendfile() to socket.
     │     ZERO-COPY: data goes from page cache → NIC
     │     without copying through user space.
     │     This is why Kafka is fast on commodity disk.
     ▼
  Consumer client
     │
     │  4. Deserialize.
     │  5. Hand to application.
     │  6. Application processes.
     │  7. commit() — sends offset back to broker.


  THE ZERO-COPY MAGIC:
   Kafka's reputation for throughput comes from sendfile().
   On a typical broker with cold reads:
     - read() to user space:        ~6 GB/s on NVMe
     - sendfile() (zero-copy):     ~25 GB/s (NIC-bound)
   Logs are sequential. Sequential reads from page cache
   saturate NIC before CPU.

   This is broken by:
    - SSL/TLS encryption (must encrypt in user space)
    - Compression that decompresses on broker
    - Schema validation on broker
   Trade-off acknowledged: many production deployments
   accept the speed loss for security. Plan capacity
   accordingly: TLS-enabled Kafka does ~40-60% of
   plaintext throughput.
```

---

## Part 3 (extended): Partitions — The Decision That Decides Your Future

### Staff

Partition count and partition key are the two most consequential choices in any Kafka deployment. Both are easy to get wrong and hard to undo.

```plaintext
PARTITION COUNT — THE TENSIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  More partitions:
   ✓ Higher parallelism (one consumer per partition max).
   ✓ Smoother key distribution.
   ✗ More open file handles per broker.
   ✗ More leader elections during failover (slower).
   ✗ More producer batches in flight (more memory).
   ✗ End-to-end latency rises (more metadata, smaller batches).
   ✗ Rebalance time grows linearly with partition count.

  Fewer partitions:
   ✓ Faster failover, smaller metadata.
   ✓ Larger batches, better compression.
   ✗ Hard ceiling on consumer parallelism.
   ✗ Harder to add more later WITHOUT breaking key→partition
     mapping (because hash(key) % N changes).


  THE SIZING HEURISTIC (Confluent's, validated by ops):

    target_partitions = max(
      throughput_in / per_partition_throughput_in,
      throughput_out / per_partition_throughput_out,
      num_consumers_at_peak
    )

   per_partition_throughput is empirical: 5-10 MB/s for
   typical hardware, 25-50 MB/s for fast NVMe + 10GbE.

  Worked example:
   - Topic peak: 200 MB/s in, 600 MB/s out (3 consumer groups).
   - Per-partition throughput: 10 MB/s.
   - Peak consumers: 24.
   → max(20, 60, 24) = 60 partitions.

   Round to 64 (power of 2, easier to reason about).


  THE GROWTH PROBLEM:
   You cannot reduce partition count. You can only add.
   Adding partitions changes hash(key) % N for existing
   keys → ordering broken for those keys mid-stream.

   Defenses:
    - Over-provision partitions on day 1 (50-200 typical
      for important topics).
    - Use sticky partitioning (Kafka 2.4+) for keyless
      messages — within a batch, all go to one partition.
    - For keyed: choose partition count carefully ONCE.


PARTITION KEY — THE ORDERING CONTRACT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Kafka guarantees order within a partition, not across.
  hash(key) determines partition. Therefore:

   Same key → same partition → ordered.
   Different keys → possibly different partitions → NO order.

  Implication: your key choice IS your ordering boundary.


  GOOD KEYS (high cardinality, stable, captures "what
  must be ordered relative to itself"):

   user_id              user actions ordered per user.
   conversation_id      messages ordered per conversation.
   order_id             order state changes ordered per order.
   account_id           ledger entries ordered per account.

  BAD KEYS (low cardinality or wrong scope):

   country              "us" key takes 60% of writes.
   event_type           "click" key swamps one partition.
   timestamp            essentially random; loses any
                        meaningful ordering grouping.
   null/none            round-robin: zero ordering. Fine
                        for stateless metrics, NOT for
                        anything stateful.


  THE HOT PARTITION BUG:
   Topic: user_actions, key=user_id, 64 partitions.
   One whale user (a bot, an internal test account, a
   celebrity) sends 10× the volume of normal users.
   That user's partition is at 100% throughput; other
   63 are at 5%.
   Symptom: consumer lag piles up on ONE partition;
   monitoring averages mask it.

   Defenses:
    - Per-partition lag monitoring (NOT just topic-avg).
    - Composite key: user_id || bucket where bucket =
      hash(message_id) % K. Spreads hot user across K
      partitions. Loses strict per-user ordering;
      acceptable for many use cases (idempotent ops).
    - Rate-limit at the producer for known-hot keys.


  THE NULL KEY GOTCHA:
   send(topic, null, value) — what happens?
   - Kafka < 2.4: round-robin partitioner. Spreads evenly,
     small batches, suboptimal compression.
   - Kafka >= 2.4: sticky partitioner. Sticks to one
     partition until batch fills, then switches. Better
     batching, same eventual distribution.
   - You will NEVER get ordering. If you need ordering,
     you need a key.


  ORDERING IS A CONTRACT. STATE IT EXPLICITLY.
   In every topic's docs, write:
     "This topic is keyed by ${key}. Ordering is
      guaranteed per ${key}, not globally."
   Consumers must design around the documented contract.
```

---

## Part 4 (extended): Consumer Groups & The Rebalance Protocol

The most operationally significant Kafka concept after partitions. Misunderstanding rebalance is responsible for the majority of "Kafka is unreliable" complaints.

```plaintext
THE CONSUMER GROUP MODEL:
━━━━━━━━━━━━━━━━━━━━━━━

  Topic: orders, 12 partitions
  Consumer group: "order-processor", 4 consumers

   Partitions:  P0 P1 P2 P3 P4 P5 P6 P7 P8 P9 P10 P11
                 │  │  │   │  │  │   │  │  │   │   │   │
                 └──┴──┘   └──┴──┘   └──┴──┘   └───┴───┘
                Consumer1  Consumer2 Consumer3 Consumer4

  Each partition is owned by EXACTLY ONE consumer in the
  group at a time. Each consumer can own MANY partitions.

  Properties:
   - Add a 5th consumer → coordinator reassigns; one
     consumer per partition still, plus an idle consumer
     OR redistributed (depends on assignment strategy).
   - Lose a consumer → its partitions reassigned to others.
   - Consumers > partitions → extras sit idle.

  THIS IS WHY PARTITION COUNT IS THE PARALLELISM CEILING.


THE OFFSET COMMIT MODEL:
━━━━━━━━━━━━━━━━━━━━━━━

  Consumer reads message at offset N.
  Consumer processes message.
  Consumer commits offset N+1 (the NEXT to read).

  Stored in: __consumer_offsets internal topic.
  Keyed by: (group_id, topic, partition).
  Value: offset, metadata, timestamp.

  TWO COMMIT MODES:

   AUTO COMMIT (enable.auto.commit=true, default in some clients):
    Background thread commits every auto.commit.interval.ms
    (default 5s).
    DANGEROUS: commits offset for messages that may not have
    been processed yet. On consumer crash → message loss.

   MANUAL COMMIT (enable.auto.commit=false):
    App explicitly calls commitSync() or commitAsync() after
    processing. The right answer for at-least-once delivery.

  THE "WHEN TO COMMIT" QUESTION:

    Pattern A: commit BEFORE processing.
     poll() → commit → process
     If process fails → message LOST. At-most-once.

    Pattern B: commit AFTER processing.
     poll() → process → commit
     If commit fails after process → message reprocessed
     on restart. At-least-once.

    99% of the time you want Pattern B.


THE REBALANCE PROTOCOL — THE SOURCE OF MOST PAIN:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  When the coordinator detects group membership change
  (consumer joined, left, or stopped heartbeating), it
  triggers a REBALANCE. Until rebalance completes, the
  ENTIRE GROUP STOPS PROCESSING.

  Stop-the-world events:
   1. Consumer joins or leaves.
   2. Consumer fails to heartbeat within session.timeout.ms.
   3. Consumer's poll() takes longer than max.poll.interval.ms.
   4. Topic partition count changes.
   5. Consumer subscribes to new topics.

  Rebalance phases (eager protocol, default <2.4):
    Phase 1: All consumers REVOKE their partitions. Stop.
    Phase 2: Coordinator assigns new partitions.
    Phase 3: Consumers receive assignments, fetch from
             last-committed offset, resume.

  DURING THE REBALANCE: nobody processes anything.

  Rebalance time scales with:
   - Partition count (more to assign).
   - Consumer count (more to coordinate).
   - State to restore (Kafka Streams).

  Real production rebalances on big groups: 30s to
  several minutes. Lag spikes during this window.


COOPERATIVE REBALANCING (Kafka 2.4+, opt-in; default in some
clients 3.0+):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CooperativeStickyAssignor:
   - Only partitions that NEED to move are revoked.
   - Other consumers keep processing during rebalance.
   - Two-phase: revoke only what's moving, then assign.

  10× shorter rebalance impact for large groups.
  Use this. The default eager protocol is a footgun.

  Set: partition.assignment.strategy =
        org.apache.kafka.clients.consumer.CooperativeStickyAssignor


THE FOUR REBALANCE PATHOLOGIES (memorize):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. SLOW POLL LOOP TIMEOUT
     Symptom: consumers churn in/out of group, lag never
     drains.
     Cause: a message takes longer than max.poll.interval.ms
     (default 5 min) to process. Coordinator thinks consumer
     is dead, kicks it. New consumer joins, takes the same
     slow message, gets kicked. Loop.
     Fix:
      - Reduce max.poll.records so each poll cycle has less
        work.
      - Increase max.poll.interval.ms if processing is
        legitimately long.
      - Move slow work off the poll thread (background
        executor + manual offset management). Hard but
        sometimes necessary.

  2. ROLLING DEPLOY STORM
     Symptom: every deploy of consumer service triggers
     30s of group lag.
     Cause: each pod restart triggers a rebalance. With
     20 pods rolling one at a time, that's 20 rebalances.
     Fix:
      - Cooperative rebalancing (above).
      - Static membership: set group.instance.id per pod.
        Coordinator treats restart-within-session-timeout as
        same member, no rebalance. Kafka 2.3+.
      - Tune session.timeout.ms (default 45s in newer
        clients, was 10s in old) to be longer than your
        pod restart time.

  3. CASCADING FAILURE
     Symptom: one consumer OOMs, another consumer takes
     over its partitions, that consumer OOMs too, third
     takes over, etc.
     Cause: a "poison" partition with messages too large
     or too slow. Each consumer dies in turn.
     Fix:
      - Bound message size at producer side
        (max.message.bytes).
      - Implement DLQ (Part 8).
      - Per-consumer memory limits and circuit breakers.

  4. ZOMBIE CONSUMER
     Symptom: consumer pod is OOMKilled but its TCP
     connection lingered; coordinator hasn't realized.
     Lag grows on partitions assigned to dead pod.
     Fix:
      - session.timeout.ms tuned reasonably (30-60s).
      - heartbeat.interval.ms = session.timeout.ms / 3.
      - Kubernetes preStop hook that calls
        consumer.close() before SIGKILL.
```

---

## Part 5 (extended): Producer Internals — Idempotence & Transactions

### Principal stretch

```plaintext
THE NAIVE PRODUCER PROBLEM:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  send(msg) → broker writes → ack lost on network →
              producer retries → broker writes AGAIN →
              ack received → producer thinks all is well.

  Result: duplicate message. At-least-once delivery,
  the default since forever.


IDEMPOTENT PRODUCER (Kafka 0.11+, default in 3.0+):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  enable.idempotence = true

  Mechanism:
   - Producer gets a Producer ID (PID) from broker.
   - Each message tagged with (PID, sequence_number).
   - Broker tracks last sequence per (PID, partition).
   - Duplicate seq → broker silently de-duplicates.

  Guarantees:
   - Exactly-once delivery to a SINGLE PARTITION.
   - Ordering preserved per partition even with retries.
   - Implicit: max.in.flight.requests.per.connection ≤ 5
     (Kafka enforces).

  Limitations:
   - Per producer SESSION. Producer restart → new PID →
     duplicates possible across restart boundary.
   - Per partition. A logically-single message that maps
     to multiple partitions cannot be made atomic by
     idempotence alone.

  In Kafka 3.0+: idempotence is the DEFAULT.
  In earlier: explicitly enable. Always.


KAFKA TRANSACTIONS (the harder, rarer thing):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  transactional.id = "my-app-instance-1"

  Provides:
   - Atomic write across multiple partitions.
   - Atomic read-process-write (Kafka → Kafka pipelines).
   - Survives producer restart (transactional.id persists).

  API:
    producer.initTransactions()
    producer.beginTransaction()
    producer.send(record1)   // partition A
    producer.send(record2)   // partition B
    producer.sendOffsetsToTransaction(offsets, "consumer-group")
    producer.commitTransaction()    // OR abortTransaction()

  Reader side:
    isolation.level = read_committed
    Consumer skips messages in aborted transactions.

  Costs:
   - Extra coordination round-trips → ~2-3× latency.
   - Producer state on broker (transactional coordinator).
   - Consumer must handle "read_committed" semantics.

  Use for:
   - Kafka-to-Kafka stream processing where exactly-once
     across stages matters.
   - NOT for "exactly-once to external system" — see below.


THE "EXACTLY-ONCE TO EXTERNAL SYSTEM" MYTH:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Kafka's exactly-once semantics work WITHIN Kafka.
  As soon as you write to Postgres / S3 / external API:

    consumer reads → writes to PG → commits offset

  If process dies between PG write and offset commit:
   - PG write succeeded.
   - Offset not committed.
   - On restart: re-process → DUPLICATE PG WRITE.

  No amount of Kafka transactions fixes this. The fix is
  IDEMPOTENT CONSUMER (Part 8): the consumer's effect on
  the external system must be naturally repeat-safe.

  This is the truth nobody tells you in marketing material.
  Kafka transactions are powerful WITHIN Kafka. Across
  the boundary, you build idempotence.
```

---

## Part 6 (extended): Replication & ISR (the durability story)

```plaintext
THE REPLICATION MODEL:
━━━━━━━━━━━━━━━━━━━━━

  Topic created with replication.factor = 3.
  Each partition has:
   - 1 LEADER (handles all reads and writes).
   - N-1 FOLLOWERS (pull from leader, replicate).

  The set of replicas currently caught up with the leader =
  ISR (In-Sync Replicas).

   ISR membership requires:
    - Replica is alive (recent heartbeat to controller).
    - Replica's log is within replica.lag.time.max.ms of
      leader (default 30s).

   A follower that lags too long → REMOVED from ISR.
   Caught up again → re-added.


THE PRODUCER'S DURABILITY GUARANTEE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  acks=all + min.insync.replicas=2:
   - Write succeeds only if leader + at least 1 follower
     in ISR have written.
   - If ISR shrinks to just leader → writes REJECTED with
     NotEnoughReplicasException.

  This is the key invariant for safety:
   replication.factor = 3, min.insync.replicas = 2
   → tolerate 1 broker failure with no data loss, no
     unavailability.


THE TWO HALVES OF DURABILITY (memorize):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   Producer side:    acks=all
   Topic side:       min.insync.replicas >= 2
   Topic side:       replication.factor >= 3

  Forget any of these and your "durable" topic isn't.

  Worst case in the wild:
   - replication.factor = 3 (looks safe!)
   - acks = 1 (default in old clients)
   - min.insync.replicas = 1 (default!)
   → silent data loss on leader failover.


UNCLEAN LEADER ELECTION — THE SHARP CORNER:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Scenario: ISR = {leader, follower-A}. Leader dies.
  Follower-A becomes new leader. Good.

  Scenario: ISR = {leader}. Leader dies. ISR empty.
  unclean.leader.election.enable controls behavior:

   false (DEFAULT, Kafka 1.0+):
    Partition becomes UNAVAILABLE. Wait for any ISR
    member to come back. Data preserved.

   true:
    A non-ISR replica is elected leader. It's behind by
    some unknown amount of data. THAT DATA IS LOST.

  Set false unless you genuinely prefer availability over
  durability. For analytics streams: maybe true. For
  payments: NEVER.


ISR SHRINKAGE — THE SILENT KILLER (parallels Part 6.2 of
last module):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptoms:
   - Production "feels fine."
   - Producer throughput unchanged.
   - But: every partition's ISR has silently shrunk to
     just the leader.

  Cause:
   - Network blip caused followers to lag past
     replica.lag.time.max.ms.
   - Followers re-sync but slowly.
   - In the meantime, ISR = {leader} on every partition.

  If broker hosting leader dies during this window:
   - With unclean.leader.election=false → partition offline.
   - With min.insync.replicas=2 + acks=all → producer was
     ALREADY being rejected (loud failure, the safe one).

  THE ALERT YOU MUST HAVE:
   metric: kafka.server:type=ReplicaManager,name=UnderMinIsrPartitionCount
   alert: > 0 for > 2 minutes → page.
   This is the equivalent of pg_stat_replication's sync_state
   alert. Same shape, same cost of forgetting.
```

---

## Part 7 (extended): Delivery Semantics — The Four Levels

```plaintext
THE FOUR DELIVERY GUARANTEES (in increasing strength):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌───────────────────────────────────────────────────────┐
  │  AT-MOST-ONCE                                         │
  │                                                       │
  │  Producer: acks=0 OR no retries.                      │
  │  Consumer: commits BEFORE processing.                 │
  │                                                       │
  │  May lose messages. Never duplicates.                 │
  │                                                       │
  │  Use: high-volume metrics, logs, traces where some    │
  │  loss is acceptable in exchange for throughput.       │
  ├───────────────────────────────────────────────────────┤
  │  AT-LEAST-ONCE  (the default; the workhorse)          │
  │                                                       │
  │  Producer: acks=all, retries enabled.                 │
  │  Consumer: commits AFTER processing.                  │
  │                                                       │
  │  Never loses. May duplicate.                          │
  │                                                       │
  │  Use: 95% of real systems, COMBINED WITH consumer     │
  │  idempotence to handle the duplicates.                │
  ├───────────────────────────────────────────────────────┤
  │  EFFECTIVELY-ONCE  (the practical exactly-once)       │
  │                                                       │
  │  Producer: idempotent (per-partition dedup).          │
  │  Broker:   acks=all, RF >= 3, min.ISR >= 2.           │
  │  Consumer: commits AFTER processing, AND processing   │
  │            is idempotent in the external system       │
  │            (dedup table, upsert by primary key,       │
  │            conditional writes).                       │
  │                                                       │
  │  No loss, no observable duplicates downstream.        │
  │  This is what "exactly-once" actually means in        │
  │  production.                                          │
  ├───────────────────────────────────────────────────────┤
  │  EXACTLY-ONCE  (within Kafka boundaries only)         │
  │                                                       │
  │  Kafka transactions, read_committed isolation.        │
  │  Atomic across multi-partition Kafka writes and       │
  │  consumer offset commits.                             │
  │                                                       │
  │  TRUE only Kafka→Kafka. Cross-system: see EFFECTIVELY.│
  └───────────────────────────────────────────────────────┘


THE PRINCIPAL'S RULE:
━━━━━━━━━━━━━━━━━━━

  Choose AT-LEAST-ONCE + idempotent consumer for nearly
  everything. Reach for transactions only inside Kafka
  Streams pipelines.

  "Exactly-once" in resumes is usually wrong. Effectively-
  once via idempotence is right and harder to brag about.
```

---

## Part 8 (extended): Idempotent Consumers — The Real Exactly-Once

```plaintext
THE FUNDAMENTAL TECHNIQUE:
━━━━━━━━━━━━━━━━━━━━━━━━

  Every message has a unique ID (or composite of
  topic+partition+offset).
  Consumer's effect must be repeat-safe — applying the
  message twice has the same outcome as applying it once.


THE FOUR IDEMPOTENCE PATTERNS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. UPSERT BY NATURAL KEY
     Message: {order_id: 123, status: "shipped"}
     Action: INSERT INTO orders ... ON CONFLICT (order_id)
             DO UPDATE SET status = EXCLUDED.status
     Repeat-safe trivially.

  2. CONDITIONAL WRITE (compare-and-set)
     Message: {order_id: 123, version: 5, status: "shipped"}
     Action: UPDATE orders SET status='shipped', version=5
             WHERE order_id=123 AND version=4
     If version != 4 (already applied) → no-op.
     Pattern matches event-sourcing; requires version on
     entities.

  3. DEDUP TABLE
     Action: INSERT INTO processed_events (event_id)
             VALUES ($id) ON CONFLICT DO NOTHING.
     If insert had effect → process. Else skip.
     Wrap both in a transaction.
     Watch table growth; partition by week, drop old.

  4. KEY-LEVEL OFFSET TRACKING
     Per-key: store last-applied offset.
     On message: if offset <= last_applied → skip.
                 Else apply, update last_applied.
     For CDC consumers especially (Part 14 of last module).


THE TRANSACTIONAL CONSUMER (the right pattern):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  BEGIN;                                    -- Postgres txn
    -- Either dedup check or upsert
    INSERT INTO processed_events (event_id) 
      VALUES ($id) ON CONFLICT DO NOTHING;
    -- If 0 rows affected, skip; else continue.
    
    -- Apply the effect
    INSERT INTO orders (...) VALUES (...);
    UPDATE inventory ...;
  COMMIT;
  
  -- Only after PG commit succeeds:
  consumer.commitSync();   -- Kafka offset commit

  Failure modes handled:
   - Crash before PG commit: nothing applied, offset
     not committed → reprocess on restart.
   - Crash between PG commit and Kafka commit: PG has
     event_id, will skip on reprocess; offset advances.
   - Crash at any other point: same shape.

  This is "effectively-once" delivery. The real thing.
```

---

## Part 9 (extended): The Transactional Outbox Pattern

The single most important pattern in event-driven architecture, and the one most teams botch.

```plaintext
THE PROBLEM:
━━━━━━━━━━━

  Service handles createOrder():
    1. INSERT INTO orders (...)         -- Postgres
    2. producer.send("order-created")    -- Kafka

  What can go wrong:
   - PG succeeds, Kafka fails → order exists, no event.
     Downstream services never learn. Search shows no
     order. Fulfillment never ships.
   - Kafka succeeds, PG fails → event published, no
     order. Fulfillment ships nothing. Customer confused.
   - Process crashes between → unknown state.

  This is the "dual-write problem." There is no way to
  make two independent systems' writes atomic without a
  distributed transaction. Distributed transactions cost
  too much (Part 12 of last module).


THE OUTBOX PATTERN:
━━━━━━━━━━━━━━━━━

  Convert dual-write to single-write + asynchronous publish.

  Step 1: At application write time, write business data
          AND outbox row in the SAME Postgres transaction.

    BEGIN;
      INSERT INTO orders (...) VALUES (...);
      INSERT INTO outbox 
        (id, aggregate_type, aggregate_id, event_type, payload, created_at)
        VALUES (gen_random_uuid(), 'order', $1, 'OrderCreated', $2, now());
    COMMIT;

  Both succeed atomically. Postgres ACID handles it.

  Step 2: A separate "outbox publisher" reads outbox rows
          and publishes to Kafka.

  Two implementations — choose carefully.


  IMPLEMENTATION A — POLLING PUBLISHER:
   ┌────────────────────────────────────────────────┐
   │ Loop:                                          │
   │   1. SELECT * FROM outbox                      │
   │      WHERE published_at IS NULL                │
   │      ORDER BY created_at LIMIT 100             │
   │      FOR UPDATE SKIP LOCKED;                   │
   │   2. For each row, send to Kafka with          │
   │      key=aggregate_id, value=payload.          │
   │   3. UPDATE outbox SET published_at=now()      │
   │      WHERE id IN (...);                        │
   │   4. Sleep briefly, repeat.                    │
   └────────────────────────────────────────────────┘

   ✓ Simple, debuggable, you control everything.
   ✓ FOR UPDATE SKIP LOCKED enables multi-publisher
     scaling without conflicts.
   ✗ Polling latency (100ms-1s tail).
   ✗ Outbox table grows unless you DELETE or partition.


  IMPLEMENTATION B — CDC PUBLISHER (Debezium):
   Debezium tails Postgres WAL, captures INSERTs to
   outbox table, publishes to Kafka.

   ✓ Sub-second latency.
   ✓ No polling load on the database.
   ✗ Operational burden (Debezium = another service).
   ✗ Replication slot bloat risk (last module, Part 7).
   ✗ Schema changes require coordination.


  THE PUBLISHER MUST BE IDEMPOTENT.
   Multi-instance publisher OR retry-on-crash means same
   outbox row may be published twice. Fix:
    - Send to Kafka with key = outbox.id.
    - Producer idempotence ON.
    - Consumer dedup by event_id (which equals outbox.id).
   Result: at-most-once visible to downstream despite
   at-least-once internal publishing.


THE COMMON MISTAKE — SKIPPING OUTBOX BY USING CDC:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  "We have Debezium on the orders table directly. Why
   bother with an outbox?"

  Because the SHAPE of the events is wrong:
   - Debezium emits ROW-LEVEL CHANGES: before/after row state.
   - Your domain emits BUSINESS EVENTS: OrderShipped,
     PaymentRefunded, AddressVerified.
   - Two updates to one row = two CDC events, but maybe
     only ONE business event.
   - Sometimes one business event = changes to multiple
     rows (header + line items) — CDC gives you N events,
     downstream must reassemble.

  The outbox lets you publish the EVENT YOU MEAN, not the
  row change you incidentally caused. This decoupling is
  worth the operational cost.

  Use direct CDC for: data replication to read stores
  (search index, warehouse).
  Use outbox for: domain events to other services.
  Many systems use BOTH on the same database.


OUTBOX TABLE LIFECYCLE:
━━━━━━━━━━━━━━━━━━━━━

  Without management, outbox grows forever.

  Strategies:
   - DELETE rows after publish (immediate, but trades
     debuggability for size).
   - Soft-delete (published_at IS NOT NULL), purge after
     N days. Useful for replay and debugging.
   - Partition outbox table by created_at (Part 10 of
     last module). DROP old partitions.

  Recommendation: partition by day. Retain 7-30 days.
  Anything older, drop. If you need the event later,
  it's in Kafka.
```

---

## Part 10 (extended): Schema Management — The Forgotten Discipline

```plaintext
THE PROBLEM:
━━━━━━━━━━━

  Producer team adds a field to OrderCreated event.
  Consumer team's deserializer breaks on unknown field.
  Or:
  Producer renames a field. Consumer reads garbage.
  Or:
  Producer changes a field's type. Consumer crashes.

  Multiply by 50 producers and 200 consumers.


SCHEMAS AS A CONTRACT:
━━━━━━━━━━━━━━━━━━━━

  Three serialization formats dominate:

   AVRO (Confluent ecosystem default):
    - Compact binary.
    - Schema is required to read AND write.
    - Schema Registry stores schemas; messages reference
      schema by ID (4 bytes).
    - Strong evolution rules.

   PROTOBUF:
    - Compact binary.
    - Schema baked into generated code.
    - Forward/backward compat via field numbers.

   JSON SCHEMA / plain JSON:
    - Human-readable, larger payload.
    - Schema validation optional.
    - Easiest to debug, weakest typing.

  Pick one per organization. Mixing is a permanent tax.


THE SCHEMA REGISTRY:
━━━━━━━━━━━━━━━━━━

  Central service storing schema versions per topic.
  Producers/consumers fetch schemas by ID.

  Compatibility rules (per topic):
   BACKWARD: new schema can read old data.
              (Drop optional field, add field with default.)
   FORWARD:  old schema can read new data.
              (Add field, can't drop.)
   FULL:     both. (Most restrictive — only optional changes.)
   NONE:     no checks. Don't.

  THE RULE: BACKWARD is the right default for most topics.
  Consumers usually deploy first, producers second; new
  consumer must read old data already in the topic.

  When in doubt: FULL_TRANSITIVE — applies the rule
  against ALL prior versions, not just the previous.
  Catches "we evolved through 5 versions, the chain is
  broken" bugs.


COMPATIBLE CHANGES (BACKWARD):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ✓ Add a new field WITH A DEFAULT.
  ✓ Remove a field that has a default.
  ✓ Add an enum value (with care).

INCOMPATIBLE CHANGES:
  ✗ Rename a field.
  ✗ Change a field's type.
  ✗ Add a required field.
  ✗ Remove a required field.

  How to "rename" safely:
   1. Add new_field with default. Deploy producers.
   2. Update consumers to read new_field, fall back to
      old_field. Deploy consumers.
   3. Stop writing old_field. Deploy producers.
   4. Stop reading old_field. Deploy consumers.
   5. Eventually drop old_field. Multi-deploy migration.

  This is the expand → migrate → contract pattern.
  Same shape as schema migrations in databases.


THE GAP NOBODY FIXES:
━━━━━━━━━━━━━━━━━━━━

  Schema Registry validates SCHEMA evolution. It does NOT
  validate SEMANTIC evolution.

  - Old: amount in USD cents.
  - New: amount in USD cents (no schema change), but
    producer started sending whole dollars.
  - Schema Registry: happy.
  - Downstream: wrong values.

  Defenses:
   - Field-level documentation in schema (Avro doc).
   - Contract tests: producer team owns example payloads
     in a registry; consumer team's CI validates against
     them.
   - Versioned event types: OrderCreatedV1, V2 instead of
     mutating OrderCreated. Trades schema sprawl for
     unambiguous semantics. Worth it for important events.
```

---

## Failure Modes

```
PATTERN 1: CONSUMER LAG SPIKE / REBALANCE STORM
  Cause: too many consumers vs partitions, long poll interval, GC pause
  Fix: consumers ≤ partitions; static membership; cooperative rebalance

PATTERN 2: UNDER-REPLICATED / MIN-ISR BREACH
  Cause: broker disk, network partition, slow follower
  Fix: restore broker; unclean.leader.election=false; alert UnderMinIsrPartitionCount

PATTERN 3: HOT PARTITION
  Cause: skewed key (user_id hash collision, default partition)
  Fix: salt keys; custom partitioner; split topic

PATTERN 4: DUPLICATE / LOST MESSAGES
  Cause: at-least-once without idempotent consumer; acks=1 under failure
  Fix: idempotency keys; acks=all; min.insync.replicas=2

PATTERN 5: LOG DIR FULL
  Cause: consumer offline + retention misconfig
  Fix: disk alerts; tiered storage; consumer lag pages
```

---

## Decision Framework

```
QUEUE vs LOG:
  Task queue, delete-on-ack, single consumer group    → SQS / RabbitMQ
  Event log, replay, multiple consumer groups         → Kafka / Kinesis

PARTITION COUNT:
  Target ~10–50 MB/s per partition write throughput
  Consumer parallelism ≤ partition count
  Key skew → hot partition before adding partitions

DELIVERY SEMANTICS:
  At-most-once     → fire-and-forget producer, no retries
  At-least-once    → idempotent consumer required (default honest choice)
  Exactly-once     → transactional producer + idempotent consumer + EOS protocol
```

---

---

## SRE Diagnostic Toolkit
```plaintext
THE FOUR METRICS THAT MATTER:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. CONSUMER LAG (per group, per partition)
     metric: kafka.consumer.lag (per consumer group)
     OR: query Kafka admin API for committed vs end offset.
     
     Per-partition lag, NOT just aggregate. A topic-avg
     of 1000 messages can hide one partition at 1M and
     63 at 0. (See: hot partition.)
     
     Alarms:
      - Lag > X messages → warn (X depends on throughput).
      - Lag growing for > 10 minutes → page.
      - Lag flat (consumer dead but not removed) → page.

  2. UNDER-REPLICATED PARTITIONS
     metric: kafka.server:type=ReplicaManager,
              name=UnderReplicatedPartitions
     
     Should be 0. > 0 means at least one follower has
     fallen out of ISR.
     
     Alarms:
      - > 0 for > 2 min → page.
      - UnderMinIsrPartitionCount > 0 → page IMMEDIATELY.
        This is the equivalent of "primary about to lose
        durability guarantee."

  3. PRODUCER ERROR RATE
     metric: kafka.producer:type=producer-metrics,
              name=record-error-rate
     
     Spikes mean: throttling, broker failures, schema
     rejection, ISR shortfall.

  4. END-TO-END LATENCY
     produce_time → consume_time per message.
     
     Implement via timestamp header:
      - Producer adds `produced_at` to record.
      - Consumer subtracts on receipt.
      - Histogram per topic.
     
     This catches problems no broker metric will:
     bottlenecks in the consumer's processing thread,
     network issues, JVM GC pauses. End-to-end is the
     SLO that maps to user experience.


THE INSPECTION COMMANDS (memorize):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Show all topics and basic info
  kafka-topics --bootstrap-server $BS --list
  kafka-topics --bootstrap-server $BS --describe --topic orders

  # Consumer group state
  kafka-consumer-groups --bootstrap-server $BS \
    --describe --group order-processor

   GROUP            TOPIC   PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
   order-processor  orders  0          145728          145731          3
   order-processor  orders  1          145812          151203          5391  ◄
   order-processor  orders  2          146001          146002          1

  # ◄ Partition 1 is way behind. Maybe a slow consumer
  # owning partition 1, or a hot key on partition 1.

  # Reset offsets (DANGEROUS — usually for replay)
  kafka-consumer-groups --bootstrap-server $BS \
    --group order-processor --topic orders \
    --reset-offsets --to-datetime 2026-05-01T00:00:00.000 \
    --execute

  # Inspect actual messages
  kafka-console-consumer --bootstrap-server $BS \
    --topic orders --from-beginning --max-messages 5 \
    --property print.key=true --property print.timestamp=true


CAPACITY HEADROOM RULE:
━━━━━━━━━━━━━━━━━━━━━━

  Always run brokers at < 60% of:
   - Disk capacity (room for log retention spikes,
     replication catch-up).
   - Network bandwidth (room for failover-induced
     re-replication).
   - CPU (room for compaction storms).

  60% sounds wasteful. It's actually the right number.
  Kafka needs headroom to RECOVER from failures, not
  just to run normally.
```

---

## Ops Sim: Northstar Auction Bid Event Hot Partition

**Time box:** 50 minutes  
**Severity:** P1  
**Service / domain:** Kafka producers, partitioning, consumer groups, bid notifications  
**Northstar system:** Northstar Commerce

### Operating rules for this drill

1. Answer from memory of the Message Queues and Kafka teaching section; do not re-read mid-drill.
2. Write decisions in order: T+0, T+5, T+15, T+30, T+60, and follow-up.
3. Tie every claim to a metric, log line, trace, query output, or config key from this packet.
4. Name the correctness invariant before proposing scale, failover, replay, or data repair.
5. Do not open the answer key until your response is written.

---

### Incident brief

```text
WHAT USERS SEE:
  - Outbid notifications arrive 8-12 minutes late for one celebrity auction.
  - Bid confirmation is accepted, but watchlist state is stale.
  - Other auctions continue normally.
  - Duplicate bid submits are suppressed by the bid ledger.

WHAT ON-CALL SEES:
  - Partition 44 owns nearly all group lag.
  - Extra consumers are idle or assigned cold partitions.
  - A schema-v7 event is retried inline at the same offset.
  - Producer key is auction_id to preserve per-auction order.

BUSINESS CONSTRAINT:
  Do not lose or reorder accepted bids; notifications may lag or be quarantined.
```

### Failure physics to reason about

A celebrity auction correctly keys bids by auction_id, concentrating all notification events on one partition. A poison schema-v7 event blocks ordered processing at the head of that partition.

Break it into these forces before answering:
- trigger: the release/config/data shape that started the failure
- amplifier: retry, cache, routing, projection, or observability behavior that widened it
- scarce resource: the metric that reaches a limit first
- invariant: what must remain conservative even while users see degraded experience
- repair boundary: the source of truth and operation id used after mitigation

### What changed in the last release window

- The suspicious production lever is `producer.partition_key: auction_id`; tie it to the first bad minute before changing capacity.
- The dashboard that stayed calm does not expose `kafka_consumergroup_lag{group="auction-notify"}` for the damaged slice.
- The runbook move closest to "scale consumers and expect one partition to split" needs an explicit no-go decision on the bridge.
- The repair path is allowed only after the source-of-truth query and operation key are written down.

### Telemetry pack

```text
METRICS:
  - kafka_consumergroup_lag{group="auction-notify"}: 18k -> 7.8M
  - kafka_consumergroup_lag{partition="44"}: 7.1M
  - auction_bid_accept_rate{auction="watch-8844"}: 22k/min
  - notification_send_lag_seconds{p99}: 18 -> 720
  - consumer_records_lag_max{client="notify-3"}: 7100000
  - consumer_rebalance_total: +38/20m
  - dlq_records_total: 0
  - poison_event_retry_total: +1.9M

LOG LINES:
  - auction-notify: parse error schema_version=7 missing reserve_price_cents offset=918271 p=44
  - consumer: retrying same offset p=44 attempt=8842
  - bid-api: accepted bid id=bid-77c auction_id=watch-8844
  - ops: scaled deployment replicas=8->32 no lag improvement
  - producer: key=auction_id partition=44

TRACE / QUERY / INSPECTION NOTES:
  - Consumer group describe shows p44 assigned to one pod.
  - Bid ledger sequence is correct; notification projection is behind.
  - Schema registry allowed a shape the worker treats as required.
  - The disk and broker path for p44 are healthy.
```

### Config pack: wrong line included

```yaml
producer.partition_key: auction_id
topic.partitions: 64
retry.poison_strategy: inline_forever
dlq.enabled: false
notification.ordering_required_per_auction: true
```

### Timeline and decision points

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | Auction notification lag pages; one partition dominates. | Prove hot key plus poison. |
| T+5 | Team scales consumers to 32. | Explain one partition cannot split. |
| T+15 | Poison schema-v7 event is identified. | Choose ordered quarantine. |
| T+30 | One auction notification stream is behind. | Define communication and replay. |
| T+60 | Lag drains after worker patch. | Audit skipped/replayed offsets. |
| T+24h | Live-ops plans next celebrity auction. | Design hot-key lane. |

### Levers available on the bridge

- Roll back or disable the specific dangerous config from the packet.
- Shed decorative, derived, notification, or analytics work before weakening source-of-truth correctness.
- Throttle retry/replay using the narrowest downstream capacity limit.
- Keep an affected-record ledger before customer-visible repair.
- Verify recovery with the sliced SLI plus the scarce-resource metric, not a fleet average.

### Bad-fix gallery

For each proposal, name the concrete failure mode it creates.

- scale consumers and expect one partition to split
- increase partitions mid-auction
- drop the poison event without audit
- change key to user_id and reorder bids

### Questions

**Q01.** What exact layer owns the failure and why is the most obvious graph a red herring?

**Q02.** Which config line is wrong, and what failure physics does it create?

**Q03.** Select three metrics and two log/inspection clues that prove your diagnosis.

**Q04.** What is the safe T+0 to T+5 announcement and freeze/rollback decision?

**Q05.** What do you stop first: trigger, amplifier, or repair job? Explain sequencing.

**Q06.** What invariant must remain true if every dashboard is stale?

**Q07.** Which bad fix is most tempting in this incident, and why does it make recovery worse?

**Q08.** What numeric capacity or blast-radius check is required before scale/failover/replay?

**Q09.** What is the source-of-truth query or ledger for the affected set?

**Q10.** Which derived systems may lag, and which external side effects require idempotency?

**Q11.** Write the durable config/architecture change and its acceptance test.

**Q12.** Who joins by T+10, and what is pre-authorized versus escalated?

### Self-score after reading the answer key

| Error type | Count | Notes |
|------------|-------|-------|
| Wrong layer/root cause | | |
| Evidence gap | | |
| Unsafe first action | | |
| Capacity/blast-radius miss | | |
| Correctness invariant miss | | |
| Repair/replay mistake | | |
| Org/runbook gap | | |

**Pass bar:** correct mechanism, safe sequencing, explicit rejection of the bad fix, one numeric capacity check, and a repair plan grounded in source of truth.

**Answer key:** [answers/Week-06-Architecture-Patterns/Message Queues and Kafka Answers.md](../answers/Week-06-Architecture-Patterns/Message%20Queues%20and%20Kafka%20Answers.md)

