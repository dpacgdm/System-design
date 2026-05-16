# Week 5, T2 — Message Queues & Streaming (Kafka Deep Dive)

> The connective tissue under everything we just built. CQRS read models, sagas, outbox, CDC — all of them assume a streaming substrate. This module makes that substrate first-class.



Same density as the database scaling module. Same teaching contract: every section answers *what do I run, what do I look at, what's the bug nobody warned me about.*

---

## Part 0: Why This Module Exists

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

## Part 2: Kafka's Storage Model (the foundation for everything)

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

## Part 3: Partitions — The Decision That Decides Your Future

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

## Part 4: Consumer Groups & The Rebalance Protocol

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

## Part 5: Producer Internals — Idempotence & Transactions

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

## Part 6: Replication & ISR (the durability story)

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

## Part 7: Delivery Semantics — The Four Levels

```plaintext
THE FOUR DELIVERY GUARANTEES (in increasing strength):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────────────────────────────┐
  │  AT-MOST-ONCE                                        │
  │                                                      │
  │  Producer: acks=0 OR no retries.                     │
  │  Consumer: commits BEFORE processing.                │
  │                                                      │
  │  May lose messages. Never duplicates.                │
  │                                                      │
  │  Use: high-volume metrics, logs, traces where some   │
  │  loss is acceptable in exchange for throughput.      │
  ├──────────────────────────────────────────────────────┤
  │  AT-LEAST-ONCE  (the default; the workhorse)         │
  │                                                      │
  │  Producer: acks=all, retries enabled.                │
  │  Consumer: commits AFTER processing.                 │
  │                                                      │
  │  Never loses. May duplicate.                         │
  │                                                      │
  │  Use: 95% of real systems, COMBINED WITH consumer    │
  │  idempotence to handle the duplicates.               │
  ├──────────────────────────────────────────────────────┤
  │  EFFECTIVELY-ONCE  (the practical exactly-once)      │
  │                                                      │
  │  Producer: idempotent (per-partition dedup).         │
  │  Broker:   acks=all, RF >= 3, min.ISR >= 2.          │
  │  Consumer: commits AFTER processing, AND processing  │
  │            is idempotent in the external system      │
  │            (dedup table, upsert by primary key,      │
  │            conditional writes).                      │
  │                                                      │
  │  No loss, no observable duplicates downstream.       │
  │  This is what "exactly-once" actually means in       │
  │  production.                                         │
  ├──────────────────────────────────────────────────────┤
  │  EXACTLY-ONCE  (within Kafka boundaries only)        │
  │                                                      │
  │  Kafka transactions, read_committed isolation.       │
  │  Atomic across multi-partition Kafka writes and      │
  │  consumer offset commits.                            │
  │                                                      │
  │  TRUE only Kafka→Kafka. Cross-system: see EFFECTIVELY.│
  └──────────────────────────────────────────────────────┘


THE PRINCIPAL'S RULE:
━━━━━━━━━━━━━━━━━━━

  Choose AT-LEAST-ONCE + idempotent consumer for nearly
  everything. Reach for transactions only inside Kafka
  Streams pipelines.

  "Exactly-once" in resumes is usually wrong. Effectively-
  once via idempotence is right and harder to brag about.
```

---

## Part 8: Idempotent Consumers — The Real Exactly-Once

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

## Part 9: The Transactional Outbox Pattern

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

## Part 10: Schema Management — The Forgotten Discipline

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

## Part 11: Operational Health — What to Watch

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

## Part 12: SRE Scenario — "The Lag That Wasn't"

```plaintext
THE PAGE (14:22 UTC, Tuesday afternoon):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Datadog: [P2] kafka.consumer.lag for group=search-indexer
            on topic=orders averaging 280k (threshold 50k)
            for 18 minutes.

  Slack #incidents:

    14:04  oncall-data:  "search-indexer lag spike, looking."
    14:08  oncall-data:  "added 4 more pods, lag still climbing."
    14:11  oncall-data:  "added 4 more — 12 total now. lag
                          at 280k and not draining."
    14:16  oncall-data:  "broker CPU normal, network normal,
                          producer rate is normal too."
    14:20  oncall-data:  "wait — only one of our 12 pods is
                          actually consuming. the other 11
                          show 0 lag."
    14:22  PagerDuty:    [P2] paged.

  THE STAGE:
   - Topic: orders, 8 partitions, 3 replicas.
   - Consumer group: search-indexer, normally 4 pods.
   - Each pod uses 1 consumer thread.
   - Producer throughput: 12k msg/s normal, 14k now (mild
     uptick).
   - Lag budget: < 50k messages (~5s).
   - Time budget: search staleness budget is 5 minutes.

  YOU JOIN THE BRIDGE. What do you do?


MINUTE 0 — WHAT THE TEAM ALREADY KNOWS, DECODED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  "Only one pod is consuming."
  → The team has 12 pods, but the topic has 8 partitions.
    Even if perfectly assigned, only 8 pods CAN consume;
    4 must be idle.
  → But "only ONE consuming" means assignment is broken.
    The other 11 (including 7 that should be active) are
    not assigned partitions.

  Hypothesis A: rebalance is failing.
  Hypothesis B: assignment strategy is broken.
  Hypothesis C: a single consumer is "static" and is
                holding all 8 partitions.


MINUTE 1 — THE INSPECTION:
━━━━━━━━━━━━━━━━━━━━━━━━

  $ kafka-consumer-groups --describe --group search-indexer

   GROUP           TOPIC   PARTITION  CURRENT-OFFSET   LAG   CONSUMER-ID
   search-indexer  orders  0          ...              35k   pod-3-abc
   search-indexer  orders  1          ...              36k   pod-3-abc
   search-indexer  orders  2          ...              35k   pod-3-abc
   search-indexer  orders  3          ...              35k   pod-3-abc
   search-indexer  orders  4          ...              35k   pod-3-abc
   search-indexer  orders  5          ...              35k   pod-3-abc
   search-indexer  orders  6          ...              35k   pod-3-abc
   search-indexer  orders  7          ...              35k   pod-3-abc

  ALL 8 partitions assigned to pod-3-abc.
  280k total lag. The other 11 pods show as members but
  own zero partitions.

  This is Hypothesis C. One consumer holds everything.


MINUTE 3 — WHY:
━━━━━━━━━━━━━━

  Check assignment strategy:

  $ kubectl exec pod-3-abc -- cat /app/config/kafka.yaml | grep assignor
   partition.assignment.strategy: org.apache.kafka.clients.consumer.RangeAssignor

  RangeAssignor with single-topic subscription assigns
  contiguous ranges. With 8 partitions and 12 consumers,
  RangeAssignor's behavior depends on member ordering —
  but should still spread across consumers.

  Look closer at consumer config:

  $ kubectl exec pod-3-abc -- env | grep -i kafka
   KAFKA_GROUP_INSTANCE_ID=search-indexer-static

  Stop. Check the others:

  $ kubectl exec pod-7-xyz -- env | grep -i kafka
   KAFKA_GROUP_INSTANCE_ID=search-indexer-static    ◄ SAME

  All 12 pods have the SAME group.instance.id.

  This is the bug. Static membership requires UNIQUE
  group.instance.id per consumer instance. With duplicates:
   - Coordinator treats all 12 as the SAME static member.
   - First to register "wins," gets all partitions.
   - Others rejected, sit idle, retry, fail again.


MINUTE 5 — THE FIX:
━━━━━━━━━━━━━━━━━

  Root cause: Helm chart hardcoded group.instance.id
  instead of templating per-pod.

  Hot fix:
   1. UNSET KAFKA_GROUP_INSTANCE_ID across the deployment.
      Static membership disabled → cooperative rebalance
      across all 12 pods → 8 will own 1 partition each,
      4 will be idle.
      Trade-off: deploy-time rebalance storms come back
      until proper fix.
   2. OR: redeploy with templated group.instance.id:
      KAFKA_GROUP_INSTANCE_ID=search-indexer-${POD_NAME}

  We pick option 2 — proper fix, redeploy.

  At 14:31: rolling restart in progress.
  At 14:33: 8 pods owning 1 partition each, 4 idle. Lag
            draining at 8× previous rate.
  At 14:39: lag below 50k threshold. Page resolved.
  At 14:52: lag at zero, search caught up.


THE POSTMORTEM PRELOADS:
━━━━━━━━━━━━━━━━━━━━━━

  1. STATIC MEMBERSHIP IS A FOOTGUN.
     Set carelessly, it silently collapses parallelism.
     The error mode is not "loud failure"; it's "one
     consumer doing all the work." Easy to miss.
     Action: lint rule on Helm charts that group.instance.id
     must include {{ .PodName }} or equivalent template var.

  2. MONITORING WAS LAG-AVERAGE, NOT PER-PARTITION.
     Aggregate lag was reported. Per-partition would have
     shown immediately that all 8 partitions had the same
     consumer-id.
     Action: per-partition lag dashboard with consumer-id
     overlay.

  3. THE TEAM SCALED PODS BEFORE DIAGNOSING.
     Adding 8 pods to fix lag is an instinctive but wrong
     reflex when assignment is broken. Pods 5-12 sat idle.
     Action: runbook entry: "Before scaling consumers, run
     kafka-consumer-groups --describe and verify partitions
     are spread across consumer-ids."

  4. THE HELM CHART WAS REVIEWED BUT NOT TESTED AT SCALE.
     Single-pod dev environment never triggered the bug.
     Action: pre-prod soak test with pod count > partition
     count. Verify all consumers are active.

  5. PROPER VS WORKAROUND DECISION WAS FAST.
     Given a 5-minute deploy capability, "redeploy with
     fix" beat "remove static membership entirely." Don't
     trade durability features (static membership reduces
     deploy-time rebalance storms) for incident speed
     when proper fix is comparable.


  THE LESSON:
   Kafka's most operationally annoying failure modes are
   not crashes. They're silent collapses of parallelism
   or durability that look like normal operation until
   you check the right metric. Build the dashboards that
   show those things by default, not on incident demand.
```

---

## Part 13: The Four In-Depth Questions

```plaintext
QUESTION 1 — THE SCALING DECISION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Your "orders" topic has 8 partitions. Peak traffic is
  120 MB/s in, 360 MB/s out across 3 consumer groups.
  You're hitting per-partition throughput ceilings during
  peak. The on-call engineer proposes: "Bump partitions
  to 32." Walk through:

   (a) What breaks immediately if you do this naively?
       Specifically: identify two existing consumers in
       this fictional system that depend on per-key
       ordering, and explain what they will see.
   (b) The "expand-and-migrate" alternative: design a new
       topic orders_v2 with 64 partitions and a path to
       cut consumers over.
   (c) For each consumer group, decide whether replay from
       offset 0 is feasible during cutover. What determines
       feasibility?
   (d) Identify the one business condition under which
       you'd take the naive in-place repartition anyway,
       and what monitoring you'd add to detect the damage.

  The principal answer notices that hash(key) % N changes
  for every existing key when N changes. Per-key ordering
  is broken for in-flight events for the duration of the
  cutover. Worse, downstream stateful consumers (Kafka
  Streams, KTables) silently corrupt: they'll see a
  state machine for one user receiving events on TWO
  different partitions during the transition.


QUESTION 2 — THE OUTBOX VS CDC DECISION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Your team is building a new "user" service. The lead
  engineer proposes putting Debezium directly on the
  users table to publish UserCreated, UserUpdated, and
  UserDeleted events to Kafka. "Why build an outbox when
  CDC does this for free?"

   (a) Sketch a specific business event, OTHER than the
       three CRUD events listed, that the user service
       will need to publish in the next 12 months. Show
       how CDC fails to express it cleanly.
   (b) Identify a transformation the team WILL need to
       apply between database state and event payload —
       e.g., field redaction for PII, computed fields,
       composite events. Compare CDC's options for this
       (single-message transforms, downstream stream
       processing) against outbox.
   (c) Suppose the team accepts your argument and adopts
       outbox. They want to use Debezium on the OUTBOX
       table to publish (still using CDC under the hood,
       just on a different table). Argue for or against
       this hybrid.
   (d) Now suppose the user service must publish events
       AND continue to support a legacy system that reads
       a "user_audit" table directly via SQL. How does
       this change your design, and why is this case
       common in real migrations?

  The principal answer recognizes (c) is actually the
  recommended Debezium pattern (outbox event router SMT).
  And (d) reveals the deep truth: outbox tables are a
  feature, not a hack. They become the canonical event
  log inside the database, queryable by both Kafka
  consumers AND legacy SQL clients.


QUESTION 3 — THE EXACTLY-ONCE CLAIM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  A vendor sells you a stream processor that claims
  "exactly-once delivery to S3." Your application reads
  Kafka events and writes parquet files to S3. Decompose
  this claim:

   (a) Identify each boundary at which "exactly-once" is
       being claimed and what would have to be true for
       the claim to hold.
   (b) S3 PUT is idempotent if the key is the same — but
       only if the CONTENT is also the same. Construct a
       failure scenario where two different runs produce
       different content for the same key, and explain
       why this breaks the claim.
   (c) The vendor's docs mention a "commit protocol" for
       atomically promoting written parquet files to
       "visible." Explain why this is necessary, and
       what state the system can be in if the commit
       protocol itself fails halfway.
   (d) Compare the vendor's approach against the simplest
       alternative: at-least-once + a downstream
       deduplication job that runs hourly. Under what
       conditions is the vendor's approach worth its
       complexity? Under what conditions is the
       deduplication job sufficient?

  The principal answer notices most "exactly-once to S3"
  systems use a write-ahead log (the parquet files in a
  staging prefix) and an atomic commit (rename or
  manifest-write). Failures during the commit produce a
  knowable, recoverable state. But "exactly-once" is
  still a story about the SYSTEM'S OWN VIEW; downstream
  consumers reading S3 may see partial writes if they
  don't follow the commit protocol. Compare to Iceberg/
  Delta/Hudi commit semantics for context.


QUESTION 4 — THE CAPACITY DECISION (PRINCIPAL'S DAY JOB)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Your Kafka cluster: 6 brokers, r6i.4xlarge, 2 TB EBS
  gp3 each, RF=3. Average broker disk: 50%. Average
  network: 35%. Average CPU: 25%. The product team plans
  to launch a feature that 5×s click-stream traffic in 6
  weeks. The CFO will fund exactly ONE:

   (i)   Add 6 more brokers (12 total). $90K/year
         additional infra.
   (ii)  Upgrade brokers to r6i.8xlarge with 4 TB disks.
         $80K/year additional.
   (iii) Move click-stream to a separate dedicated cluster
         on cheaper hardware ($55K/year), keep current
         cluster for OLTP-adjacent topics.
   (iv)  Adopt tiered storage (Kafka 3.6+) so old segments
         go to S3 ($30K/year + 2 eng-months migration).

  Required:
   (a) For each option, identify what failure mode it
       prevents AND which it does NOT.
   (b) State assumptions about traffic shape for a 5×
       claim — is it 5× peak, 5× average, 5× worst minute?
       How does the choice change with each interpretation?
   (c) Identify which option produces compounding returns
       vs one-time relief.
   (d) Choose, defend, and name your hedge: if you're
       wrong about (b), what's the smallest reversible
       follow-up?

  The easy answer picks (i). The principal answer notices
  click-stream is a high-volume, loss-tolerant, low-
  retention workload that doesn't need OLTP's durability
  characteristics. Option (iii) buys ISOLATION, not just
  capacity — a runaway click-stream producer can no
  longer DOS the orders cluster. The truly principal
  answer pairs (iii) + (iv): split the workload, then
  tier the click-stream cluster's storage. Total: $85K
  + 2 eng-months. Cleaner architecture for years.
```

Read week-4-topic-3-consensus-raft.mdRead document contentRead more sectionsRead scenario introGot it. The reference scenario has a much higher density: minute-by-minute timeline with specific infrastructure (instance types, IOPS numbers, AZ layouts), 5 questions (not 4) with concrete commands and math, and answers that include exact configuration values, PromQL expressions, and topology calculations. Let me redo the Kafka module's scenario + questions at that bar.

---

# Week 5, T2 — REVISED Parts 12-14

## Part 12: SRE Scenario — "The Tuesday Afternoon Black Hole"

### The System

```plaintext
PRODUCTION KAFKA CLUSTER ("orders-platform"):

  ┌────────────────────────────────────────────────────────────┐
  │  CLUSTER TOPOLOGY                                          │
  ├────────────────────────────────────────────────────────────┤
  │  Brokers:        12 × i3en.2xlarge                         │
  │                  (8 vCPU, 64 GB RAM, 2× 2.5TB NVMe local)  │
  │  Distribution:   AZ-a: 4 brokers (b1-b4)                   │
  │                  AZ-b: 4 brokers (b5-b8)                   │
  │                  AZ-c: 4 brokers (b9-b12)                  │
  │  Kafka version:  3.6.1 (KRaft mode, no ZooKeeper)          │
  │  Controllers:    3 dedicated (c1 in AZ-a, c2 AZ-b,         │
  │                  c3 AZ-c). Quorum=2.                       │
  │                                                            │
  │  Networking:     25 Gbps ENA, intra-AZ <0.5ms,             │
  │                  cross-AZ ~1.2ms                           │
  └────────────────────────────────────────────────────────────┘

  CRITICAL TOPICS (3 of 47 total):
  
  ┌──────────────────────┬───────┬─────┬─────────────┬──────────┐
  │ Topic                │ Parts │ RF  │ min.ISR     │ Retention│
  ├──────────────────────┼───────┼─────┼─────────────┼──────────┤
  │ orders.events        │ 64    │ 3   │ 2           │ 7 days   │
  │ orders.outbox        │ 32    │ 3   │ 2           │ 3 days   │
  │ payments.events      │ 32    │ 3   │ 2           │ 30 days  │
  │ click.stream         │ 128   │ 2   │ 1           │ 24 hours │
  │ ... 43 others        │       │     │             │          │
  └──────────────────────┴───────┴─────┴─────────────┴──────────┘

  PRODUCERS (relevant ones):
   - checkout-svc:        ~8k msg/s baseline → orders.events
                          acks=all, idempotence=true, linger=20ms
   - payments-svc:        ~3k msg/s baseline → payments.events
                          acks=all, idempotence=true, linger=5ms
                          (low latency requirement)
   - clickstream-edge:    ~140k msg/s baseline → click.stream
                          acks=1, idempotence=false, linger=100ms
                          (volume over durability)
   - orders-outbox-pub:   Debezium CDC on orders DB outbox table
                          → orders.outbox

  CONSUMERS:
   - search-indexer:      group of 16 pods consuming orders.events
                          → Elasticsearch
   - fulfillment-svc:     group of 8 pods consuming orders.events
                          → state machine in Postgres
   - fraud-detector:      group of 12 pods consuming payments.events
                          → Redis features + ML scoring
   - analytics-loader:    group of 32 pods consuming click.stream
                          → S3 in 5-min batches

  BUSINESS CONTEXT:
   - Tuesday 13:45 UTC. Mid-afternoon US peak.
   - Checkout SLO: p99 < 250ms end-to-end, ≥ 99.95% success.
   - Payments SLO: p99 < 400ms, ≥ 99.99% success.
   - Quarterly compliance audit happening THIS WEEK; data
     loss on payments.events is a reportable event.
```

### The Timeline

```plaintext
13:45:00  STEADY STATE
          - Aggregate ingress: 158 MB/s.
          - All ISRs healthy (UnderReplicatedPartitions=0).
          - Consumer lag <5s on every group.
          - Disk usage: brokers 38-42% on /var/kafka.

13:47:12  CHANGE EVENT (the trigger, not yet visible)
          - Platform team merges a PR to clickstream-edge.
            Intended: bump linger.ms 100→200 to improve batch
            compression ratio.
          - ACTUAL DIFF: also flipped acks=1 → acks=all and
            removed compression.type=lz4 (was supposed to
            change to zstd; the line got deleted in rebase).
          - Deploy completes 13:48:30 across all edge pods.

13:48:45  FIRST SYMPTOM
          - clickstream-edge p99 produce latency: 12ms → 380ms.
          - Producer queue depth climbing on edge pods.
          - Datadog: kafka.producer.record-error-rate ticks
            from 0 to ~50/sec (NotEnoughReplicasException).
          - Why: click.stream has min.ISR=1, RF=2. acks=all
            means leader + 1 follower must ack. Network blips
            occasionally drop a follower briefly. Previously
            acks=1 hid this. Now every blip = error.

13:51:00  AMPLIFICATION BEGINS
          - clickstream-edge has retries=Integer.MAX_VALUE,
            delivery.timeout.ms=120000.
          - Failed sends retry. Buffered records pile up in
            producer memory. Each edge pod's send buffer
            (32MB) fills. Pods enter backpressure.
          - Producers begin BLOCKING on send() (max.block.ms
            default 60s). Edge service threadpools fill.
          - Edge service starts dropping inbound HTTP from
            CDN. Click events are now being LOST upstream
            of Kafka entirely. (Loss-tolerant — accepted.)

13:52:30  THE PIVOT (this is where it gets bad)
          - Frustrated edge engineers, seeing producer errors
            and not understanding the acks change, push a
            "fix": revert linger.ms but ALSO bump
            max.in.flight.requests.per.connection 5 → 50
            "to reduce queueing."
          - This silently DISABLES idempotence guarantees
            (Kafka enforces ≤5 with idempotence=false; with
            idempotence=true, the limit is 5 — and they
            never had idempotence on click.stream).
          - More importantly: 50 in-flight requests per
            connection × 200 edge pods × ~6 brokers/topic-leader
            = massive concurrent load on broker request
            handlers.
          - Deploy completes 13:54:00.

13:54:30  BROKER REQUEST QUEUE SATURATION
          - kafka.network.RequestQueueSize on b1, b5, b9
            (leaders for hot click.stream partitions): 0 → 500
            (the queue ceiling, queued.max.requests=500).
          - Brokers begin throttling: produce requests get
            queued behind a wall of pending requests.
          - kafka.server.RequestHandlerAvgIdlePercent drops
            from 0.65 to 0.02. Request handlers pinned.
          - CRITICAL CONSEQUENCE: produce/fetch requests for
            OTHER topics on the same brokers also queue.
            orders.events leader on b1 starts seeing fetch
            latency spike from followers in AZ-b and AZ-c.

13:55:15  ISR SHRINKAGE BEGINS — THE SILENT KILLER
          - Followers for orders.events partitions hosted on
            b1 fall behind: their fetch requests sit in b1's
            saturated request queue.
          - replica.lag.time.max.ms = 30000 (default).
          - Followers exceed 30s lag → REMOVED FROM ISR.
          - UnderReplicatedPartitions on b1: 0 → 18.
          - UnderMinIsrPartitionCount on b1: 0 → 6.
            (Topics with min.ISR=2 and only leader in ISR.)
          - For those 6 partitions, producer writes with
            acks=all are now REJECTED with
            NotEnoughReplicasException.

13:55:45  CHECKOUT BREAKS
          - checkout-svc has acks=all + idempotence + retries.
          - Sends to orders.events for the 6 affected
            partitions return NotEnoughReplicasException.
          - Producer retries (exponential backoff). Idempotent
            so safe.
          - But: checkout-svc has delivery.timeout.ms=30000.
            After 30s of failed retries, send() throws.
          - At 13:56:15, checkout starts returning 5xx to
            ~9% of orders (the fraction whose order_id hashes
            to one of the 6 dead partitions).
          - SLO burn: 99.95% target, 91% actual on impacted
            partitions. Error budget for the month gone in
            ~12 minutes if not stopped.

13:56:30  PAYMENTS DEGRADATION
          - payments.events has 32 partitions across the
            same 12 brokers. Some payment partition leaders
            are also on b1, b5, b9.
          - Same NotEnoughReplicasException pattern.
          - But payments-svc has linger.ms=5 and stricter
            timeout.ms=5000 for SLO reasons.
          - Failures surface faster. ~3% of payment
            authorizations failing.
          - PagerDuty: P1 fires for payments error rate.
            (Not for orders yet — orders alert threshold
            is 1%.)

13:57:00  THE OUTBOX BACKS UP
          - Debezium CDC connector on orders DB outbox table
            is configured to publish to orders.outbox with
            acks=all.
          - Same NotEnoughReplicasException pattern. Debezium
            retries, but its internal queue limit is finite.
          - Debezium's confirmed_flush_lsn on the Postgres
            replication slot stops advancing.
          - Postgres pg_wal volume begins filling on the
            orders DB primary. (Connection back to last
            module: Part 7. Slot bloat.)
          - At current rate, pg_wal would fill in ~6 hours.
            Not the immediate problem, but logging it.

13:58:30  CONSUMER REBALANCE STORM
          - search-indexer consumer group: one of 16 pods is
            running on a node with cross-AZ saturation (AZ-c
            uplink utilization at 78%, normal 22%).
          - That pod's poll() blocks on slow fetch from b9
            (AZ-c broker). Exceeds max.poll.interval.ms
            (default 5min).
          - Coordinator considers it dead → triggers
            rebalance.
          - Group is using RangeAssignor (legacy), NOT
            CooperativeStickyAssignor. ALL 16 consumers
            stop. Full revoke. Reassignment.
          - Rebalance takes 47 seconds (large group + many
            partitions + state).
          - During those 47s, search index is not updating.
          - When rebalance completes, the same problem
            repeats. New rebalance at 14:01:30.
          - search-indexer enters a rebalance loop.

13:59:00  PAGER STORM
          - PagerDuty fires (in this order):
            1. payments error rate > 1% (P1)
            2. orders error rate > 1% (P1)
            3. search-indexer rebalance loop (P2)
            4. UnderMinIsrPartitionCount > 0 sustained (P1)
          - Three on-call SREs paged across two teams.
          - Slack #incidents: chaos. Multiple hypotheses:
            "did we deploy?", "is it Kafka?", "is it
            Postgres?", "AWS issue?".

14:00:00  YOU JOIN THE BRIDGE
          - Status:
            • payments error rate: 3.4%, climbing
            • orders error rate: 9.1%, climbing
            • UnderMinIsrPartitionCount cluster-wide: 14
            • Compliance audit team has been notified by
              the payments error alert (automated)
            • clickstream-edge dropping ~30% of inbound at
              the LB
            • search index 90s stale and growing
            • Postgres pg_wal: 12% (climbing slowly)
            • All 12 brokers reporting healthy
              (no broker has crashed)
            • Controller quorum stable
          - You have NO immediate evidence of what changed.
            The symptoms started 13:48 — 12 minutes ago.
            git log shows three deploys today (clickstream,
            checkout, an unrelated dashboard).
          
          What do you do, in what order, and why?
```

### The Walkthrough

```plaintext
MINUTE 0 (14:00) — TRIAGE BEFORE INTERVENTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  The temptation is to start "fixing." Resist it for 60
  seconds. The principal's first move is to ESTABLISH
  GROUND TRUTH on what's broken vs what's a symptom.

  Run, in parallel, three queries:

  (1) Which partitions are actually under-replicated?
      
      kafka-topics --bootstrap-server $BS \
        --describe --under-replicated-partitions
      
      Hypothetical output: 14 partitions across 3 topics,
      ALL with leader on b1, b5, or b9.

  (2) What's the leader-to-broker distribution look like?
      
      kafka-topics --bootstrap-server $BS --describe \
        --topic orders.events,payments.events,click.stream \
        | awk '{print $6}' | sort | uniq -c
      
      Reveals: leadership is balanced. So this isn't a
      "one broker hosts everything" problem.

  (3) Which brokers have saturated request queues?
      
      For each broker, fetch JMX:
        kafka.network:type=RequestChannel,name=RequestQueueSize
        kafka.server:type=KafkaRequestHandlerPool,
          name=RequestHandlerAvgIdlePercent
      
      Hypothetical: b1, b5, b9 show RequestQueueSize ~480-500
      (saturated). Other 9 brokers normal.

  THE PATTERN: 3 brokers saturated, ISR shrinkage on
  partitions whose LEADERS are on those 3 brokers, and
  they happen to be one broker per AZ. That last detail
  is the clue: this is not a hardware/AZ issue (it would
  affect one AZ). This is a workload pattern that
  concentrates on specific brokers across all AZs.

  Hypothesis: a producer's behavior changed in a way that
  hammers specific partition leaders. The "specific
  brokers across AZs" pattern is the signature of a
  topic whose leadership happens to land on b1/b5/b9.
  
  Which topic? Check broker request rates:
    kafka.network:type=RequestMetrics,
      name=RequestsPerSec,request=Produce
  
  Hypothetical: b1, b5, b9 are seeing 14k produce
  requests/sec (others ~3k). Click.stream's 128
  partitions are evenly spread, but each PARTITION on
  b1/b5/b9 is receiving 50× normal request count
  per second.
  
  → Click.stream producer is sending FAR more requests
    than before. Same payload volume? Probably not — but
    the request count surge is real.


MINUTE 3 (14:03) — IDENTIFY THE CHANGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Three deploys today. Diff each:
   - dashboard: HTML/CSS only. Eliminated.
   - checkout: minor refactor in cart code, no Kafka
     producer config change. Eliminated.
   - clickstream-edge: TWO config changes since 13:47.
     • acks=1 → acks=all (13:47)
     • max.in.flight.requests.per.connection 5 → 50 (13:54)

  THIS IS IT. Two compounding changes:
   - acks=all means every produce waits for follower ack
     → naturally slower → more in-flight to amortize
   - max.in.flight=50 means each producer can have 50
     concurrent unacked requests per connection
   - 200 edge pods × 50 in-flight × ~3 leaders for hot
     click.stream partitions = 30,000 concurrent produce
     requests in flight

  This saturates broker request handlers, which causes
  the OTHER topics on those brokers to suffer.

  AND: click.stream has min.ISR=1, RF=2, so acks=all is
  almost meaningless for click.stream's own durability —
  it just adds latency. The change accomplished nothing
  except harming the cluster.


MINUTE 5 (14:05) — DECIDE THE INTERVENTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Three options, in order of impact and reversibility:

  A. ROLLBACK clickstream-edge to pre-13:47 config.
     → Reverts acks change AND in-flight change.
     → Clickstream produce load returns to baseline shape.
     → Broker request queues drain.
     → ISRs recover within replica.lag.time.max.ms (30s).
     → Affected SLOs (orders, payments) recover seconds
       after ISR recovery (producer retries succeed).
     → Cost: ~3 minutes for kubectl rollout.
     → Risk: low. We're going back to the known-good state.

  B. THROTTLE clickstream at the broker level via quotas.
     kafka-configs --bootstrap-server $BS --alter \
       --add-config 'producer_byte_rate=50000000' \
       --entity-type clients --entity-name clickstream-edge
     → Limits to 50 MB/s aggregate.
     → But click.stream legit traffic was 140 MB/s. We'd
       be DROPPING customer click data.
     → Faster than rollback (~30 sec) but worse outcome.
     → Risk: moderate.

  C. STOP clickstream-edge entirely.
     → Removes the load completely.
     → Loses ~24h of click data (not regulatory; analytics
       re-derivable from logs).
     → Drastic but instantaneous.

  PRINCIPAL'S CALL: A. Rollback.

  REASONING:
   - Customer-impacting failures are on orders/payments,
     not clickstream. Stop the COLLATERAL damage.
   - Rollback is reversible.
   - 3 minutes is acceptable; we're not at "imminent
     quorum loss" (cf. last module's 13-minute disk fill).
   - We have 14 under-replicated partitions, not 14
     under-MIN-ISR. Half are still durable. We don't have
     to break glass.

  PARALLEL: prepare B and C as fallback if A doesn't
  drain queues within 90 seconds of completion.


MINUTE 6 (14:06) — EXECUTE
━━━━━━━━━━━━━━━━━━━━━━━━━

  SRE-1: kubectl rollout undo deployment/clickstream-edge
         -n edge --to-revision=N-1
         (Where N-1 is the revision before the 13:47 deploy.)
  
  SRE-2: in parallel, prepare quota fallback command;
         do NOT execute yet.
  
  SRE-3: monitor four metrics on a single pane:
         - UnderMinIsrPartitionCount (cluster aggregate)
         - kafka.network RequestQueueSize on b1/b5/b9
         - checkout error rate
         - payments error rate

  Comms (you): post to #incidents and to internal status:
   "Identified config change in clickstream-edge causing
    broker saturation. Rolling back. Expected recovery
    8-10 minutes from now (T+14:14 to T+14:16). No data
    loss expected on orders or payments. Will update in
    3 minutes."


MINUTE 7-12 (14:07-14:12) — RECOVERY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  T+14:09  Rollout completes. Edge pods on old config.
           Click.stream produce request rate to b1/b5/b9
           drops from 14k to 3k req/sec each.
  
  T+14:09  Broker request queues begin draining:
           RequestQueueSize on b1: 487 → 312 → 145 → 38.
  
  T+14:10  Followers catch up. ISRs recover. UnderMinIsr
           drops from 14 to 6 to 0.
  
  T+14:10  checkout-svc producers' retries succeed.
           Error rate: 9.1% → 4.2% → 0.8% → 0.1%.
  
  T+14:11  payments-svc errors clear: 3.4% → 0.0%.
  
  T+14:11  Debezium drains backlog to orders.outbox.
           Postgres slot pending size starts decreasing.
  
  T+14:12  search-indexer rebalance loop: still in
           progress. The slow-poll consumer never recovered;
           rebalances are now succeeding without storms,
           but lag built up to ~9 minutes.
           Side action: redeploy search-indexer to pick
           up CooperativeStickyAssignor (fix this in
           postmortem follow-up).

  Click.stream durability for the 13:48-14:09 window:
   - Edge pods dropped ~30% of inbound during the
     backpressure window. That data is GONE.
   - Click data is loss-tolerant; no escalation.
   - But: an entry in the postmortem log about the data
     loss volume for product analytics team awareness.


THE POSTMORTEM PRELOADS:
━━━━━━━━━━━━━━━━━━━━━━

  1. CONFIG CHANGES TO PRODUCERS NEED CLUSTER-IMPACT REVIEW.
     The clickstream-edge change was treated as an
     application change. It was a CLUSTER-WIDE change.
     A producer's acks/in-flight settings affect every
     broker leader they hit, which affects every other
     producer/consumer of those brokers.
     Action: producer config changes require Kafka SRE
     review (similar to "schema changes require DBA
     review"). Build it into the PR template via CODEOWNERS
     on producer config files.
  
  2. ACKS=ALL ON A min.ISR=1, RF=2 TOPIC IS NONSENSE.
     It adds latency without adding durability. The PR
     reviewer didn't understand the relationship between
     acks and min.ISR.
     Action: lint rule that rejects acks=all on topics
     with min.insync.replicas=1. The combinations only
     make sense in specific shapes.
  
  3. WE HAD NO PER-BROKER REQUEST QUEUE ALERT.
     RequestQueueSize on b1/b5/b9 was at 480+ for ~4
     minutes before the under-min-ISR alarm fired. We had
     UnderReplicated alerts but those are LAGGING — by
     the time they fire, customer impact is already
     happening.
     Action: alert on RequestQueueSize > 100 sustained
     for 1 minute. This is a LEADING indicator.
  
  4. RANGEASSIGNOR ON LARGE GROUPS IS A LANDMINE.
     search-indexer entered a 47-second stop-the-world
     rebalance because of one slow poll. Cooperative
     would have rebalanced one partition at a time and
     kept the other 15 consumers running.
     Action: org-wide migration to CooperativeStickyAssignor.
     Add a static analysis check to consumer config.
  
  5. THE OUTBOX → SLOT-BLOAT CONNECTION WASN'T MONITORED.
     Debezium failing to publish caused Postgres slot
     bloat that wasn't paged on. We got lucky that the
     incident resolved before pg_wal filled.
     Action: alert on confirmed_flush_lsn lag for ANY
     replication slot, regardless of cause. (Last
     module's lesson, applied here.)
  
  6. THE COMPLIANCE AUDIT TIMING WAS FORTUNATE.
     We didn't lose payments data — payments-svc had
     idempotent retries with sufficient timeout headroom
     to ride through the 6-minute degradation. If the
     producer's delivery.timeout.ms had been smaller than
     the recovery window, we'd have lost payment events
     and had a reportable incident during audit week.
     Action: payments producer's delivery.timeout.ms
     must be ≥ 10 minutes (longer than typical broker
     incident). Document the SLO budget math.

  THE LESSON:
   This wasn't a Kafka failure. It was a configuration
   change that exploited the way Kafka's request handler
   threads, broker leadership distribution, and ISR
   maintenance interact. The cluster did exactly what it
   was designed to do; the shape of the load was wrong.
   Operability of distributed systems is mostly about
   understanding which CHANGES are safe and which ones
   have cluster-wide blast radius.
```

---

## Part 13: The Five In-Depth Questions

### Q1: Cascade Chain Analysis

**Trace the cascade chain from the trigger to customer-impacting failure. Identify the trigger, each amplifier, and the specific Kafka mechanism that turns a per-producer config change into ISR shrinkage on unrelated topics. Why doesn't the cluster self-heal — what is the positive feedback loop, and where would it have stopped on its own (if anywhere)?**

Required in your answer:

- (a) State the trigger AS A MISMATCH (the way the reference module states "4,800 writes/sec vs 3,000 IOPS"). What were the exact numbers and units?
- (b) Identify each amplifier with a numeric or mechanism-level explanation. There are at least five.
- (c) Name the specific resource that became saturated and explain why saturation propagated to OTHER topics on the same brokers (not just click.stream).
- (d) Identify the natural ceiling that would have limited the damage if no human intervened. (Hint: it isn't a happy ceiling.)


A passing answer identifies the request handler thread pool. A principal answer additionally notices that broker leadership for click.stream's hot partitions happened to land on b1/b5/b9 (one per AZ), making the saturation pattern look like a bizarre AZ-correlated failure rather than a workload-pattern failure — and explains how to disambiguate via JMX request rates per broker.

---

### Q2: Mitigation Plan with Verification Gates

**At T+14:00, you join the bridge. Write your mitigation plan for the next 12 minutes. For each action, specify:**

- **What you are doing**
- **The exact command (or sequence)**
- **What it fixes — explicitly, what failure mode does it remove?**
- **What you must VERIFY before executing**
- **What you must VERIFY after executing, before moving to the next step**
- **The fallback if it doesn't work within a stated time budget**


Constraints to address explicitly:

- (a) You cannot afford > 90 seconds of additional payments error rate without a compliance reportable.
- (b) You have three deploys today. The faulty one is not obvious until you investigate.
- (c) Two SREs are available besides you. State who does what, in parallel.
- (d) State the ONE diagnostic action you must run BEFORE any intervention, and explain why deferring it would be worse than the 60 seconds it costs.


A passing answer rolls back the producer. A principal answer:

- Spends the first 60 seconds on diagnosis (not action), and justifies that with the reasoning that intervening on the wrong layer would extend the incident.
- Names the specific JMX metrics to disambiguate "broker problem" vs "producer problem" vs "AZ problem."
- Stages the rollback so it's reversible if symptoms don't improve in 90 seconds.
- Identifies that search-indexer rebalance is a SECONDARY fire that should NOT distract from the primary.


---

### Q3: Preventive Design — The Producer Config Governance Problem

**The trigger was a producer configuration change that shipped through normal code review. Design the controls that would have caught it. You may propose up to four mechanisms, each at a different layer of the system. For each:**

- (a) State the exact failure mode it prevents
- (b) State the false-positive rate you'd expect (legitimate changes blocked) and why that's acceptable
- (c) State the false-negative rate you'd expect (bad changes still slip through) and the next layer of defense
- (d) State the implementation cost in eng-weeks


Specifically, you must address:

- (i) How do you prevent `acks=all` on a topic where it adds no durability (`min.ISR=1`)? This is a SEMANTIC validation — you can't lint it from the producer's config alone, you need topic state.
- (ii) How do you prevent the `max.in.flight=50` change from a producer that has `idempotence=false`? (Trick question — Kafka doesn't enforce a limit there. The danger is operational, not correctness.)
- (iii) How do you make the "blast radius" of a producer config change visible to the reviewer at PR time?


A passing answer proposes CI lints. A principal answer notices that some validations require runtime state (topic config), proposes a pre-merge bot that queries the cluster, and acknowledges the bot itself is a new operational dependency that needs to fail open or closed (which? defend it).

---

### Q4: Topology and Quota Design — The Click.Stream Isolation Question

**The product team's roadmap projects click.stream volume growing from 140 MB/s today to 800 MB/s in 9 months. Three solutions are on the table. The CFO will fund exactly ONE. Defend your choice with numeric reasoning.**

**Option I**: Add 12 more brokers to the existing cluster (24 total). $145K/year incremental. Lift click.stream to 256 partitions, rebalance.

**Option II**: Deploy a separate dedicated Kafka cluster for click.stream on cheaper hardware (i3.xlarge, 6 brokers). $58K/year. clickstream-edge points there. Other producers/consumers stay on the main cluster.

**Option III**: Implement broker-level quotas on the existing cluster — `producer_byte_rate=200000000` for clickstream-edge — and adopt KIP-405 tiered storage for click.stream so old segments offload to S3. $35K/year + 3 eng-months migration.

**Option IV**: Migrate click.stream off Kafka entirely to Kinesis Data Streams (managed service). $190K/year at projected volume + 4 eng-months migration.

Required:

- (a) For each option, identify what failure mode from the incident it would have PREVENTED, and what failure mode it would NOT have prevented. Be specific — "isolation" is too vague.
- (b) The 800 MB/s projection: is that peak, average, or 99th percentile? How does each interpretation change the answer? Identify the assumption you'd validate before committing.
- (c) State which option produces COMPOUNDING returns (helps next year too) vs ONE-TIME relief.
- (d) State your choice. Then state your hedge: if your projection is wrong by 2× either direction, what's the smallest reversible follow-up?


The principal-grade insight: Option II is the right answer not because of cost but because of FAILURE DOMAIN ISOLATION. The Tuesday incident proved that a click.stream producer config bug could break payments — that's a tier mismatch (loss-tolerant traffic taking down regulated traffic). No amount of capacity in option I prevents the next config bug from doing the same. Option II severs the blast radius. The hedge: keep clickstream on the main cluster's Kafka client API for 30 days post-migration so reverting is a DNS change.

---

### Q5: Layered Monitoring Design — Catching It at Each Stage

**Design the alerts that would have caught this incident at each stage of the cascade BEFORE customer impact at 13:55:45. For each alert, specify:**

- The exact metric (with full Prometheus/JMX path)
- The threshold and time window
- The severity (warn/page) and routing (which team)
- What stage of the cascade it catches
- The automated response (if any) that should fire
- The expected false-positive rate and how you'd tune it down without losing detection


You must design alerts at the following stages:

- **Stage 1: Producer config drift** (catch the change BEFORE it causes broker stress)
- **Stage 2: Broker request queue saturation** (the leading indicator)
- **Stage 3: Request handler thread starvation** (the moment broker capacity is exhausted)
- **Stage 4: ISR shrinkage** (the moment durability degrades)
- **Stage 5: Under-min-ISR** (the moment producer writes start failing)
- **Stage 6: Producer error rate** (the customer-impact stage — already too late, but still required)


Required for full credit:

- (a) For Stages 1-3, alerts must be LEADING — they fire before any customer impact.
- (b) For at least two stages, propose an automated remediation that's safe to run without a human (and justify why it's safe).
- (c) Identify which stage's alert would have given the longest lead time, and compute that lead time from the timeline (e.g., "Stage 2 fires at 13:54:45, customer impact is at 13:55:45 — 60 seconds of lead time").
- (d) Identify the alert that you'd page the on-call SRE on, and the alerts that should only Slack — and defend the boundary.


A passing answer lists metrics. A principal answer:

- Notices that Stage 1 (config drift) requires a different MECHANISM than the others (it's not a runtime metric, it's a code/deploy-time check).
- Computes lead times from the actual timeline and shows that Stage 2 (RequestQueueSize) would have fired at ~13:54:45 — a full minute before the first ISR shrinkage and 90 seconds before customer impact.
- Acknowledges that automated remediation on Stage 2 (e.g., auto-throttling the saturating producer via quota) is risky because the saturating producer might be a legitimate priority traffic spike — proposes a SAFE auto-action (alert only) with a SUGGESTED command for the human to run.


#### Worked Example: Stage 2 Alert

```yaml
- alert: KafkaBrokerRequestQueueSaturated
  expr: |
    avg_over_time(
      kafka_network_requestchannel_requestqueuesize{job="kafka"}[1m]
    ) > 100
  for: 1m
  labels:
    severity: page
    team: kafka-platform
    automation: kafka_broker_overload_v1
  annotations:
    summary: |
      Broker {{ $labels.instance }} request queue avg > 100 
      for 1 minute (max=500)
    description: |
      Request queue saturation indicates the broker cannot 
      keep up with incoming RPCs. Within 60-90 seconds, this 
      will cause:
      → Follower fetch requests to time out → ISR shrinkage
      → Produce requests to time out → producer errors
      
      Investigate which producer/topic is generating the 
      load:
        kafka.network:type=RequestMetrics,
          name=RequestsPerSec,request=Produce
      grouped by clientId.
      
      Consider quota: 
        kafka-configs --alter --add-config \
          'producer_byte_rate=X' \
          --entity-type clients --entity-name <client-id>
    runbook: https://wiki/kafka/runbooks/queue-saturation

  expected_lead_time_to_customer_impact: 60-90 seconds
  expected_false_positive_rate: ~2/month
    (legitimate traffic spikes, monthly batch job)
  tuning: |
    If FP rate exceeds 4/month, raise threshold to 150 OR 
    add label match to exclude scheduled batch windows.
```
