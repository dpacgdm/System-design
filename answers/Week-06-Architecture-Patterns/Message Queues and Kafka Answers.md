# Answer Key — Message Queues and Kafka

> Open only after attempting the learner file questions.

## Expert Analysis
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


## Incident Scenario — The Tuesday Afternoon Black Hole

## Incident Scenario

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

## Expert Analysis
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
