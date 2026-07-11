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

## Ops Sim: Northstar Auction Bid Event Hot Partition

> Open only after attempting the learner-side drill.

### Executive diagnosis

A celebrity auction correctly keys bids by auction_id, concentrating all notification events on one partition. A poison schema-v7 event blocks ordered processing at the head of that partition.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `kafka_consumergroup_lag{group="auction-notify"}: 18k -> 7.8M`
- `kafka_consumergroup_lag{partition="44"}: 7.1M`
- `auction_bid_accept_rate{auction="watch-8844"}: 22k/min`
- `notification_send_lag_seconds{p99}: 18 -> 720`
- `consumer_records_lag_max{client="notify-3"}: 7100000`
- `consumer_rebalance_total: +38/20m`
- Config clue: `producer.partition_key: auction_id`
- Config clue: `topic.partitions: 64`
- Red herring: a fleet average or generic health check that does not include the damaged slice.

### First 15 minutes: sequencing

1. Declare severity, name the invariant, and assign an incident commander.
2. Freeze deploys, config flips, schema changes, broad failovers, and bulk replay touching this path.
3. Stop the active amplifier before adding capacity: retry storms, unsafe repair, global fallback, bad routing, or telemetry blow-up.
4. Roll back or override the specific dangerous config while preserving source-of-truth writes.
5. Shed noncritical surfaces: dashboards, notifications, search, decorative metadata, analytics, or advisory enrichment as appropriate.
6. Verify with the sliced SLI and scarce-resource metric; do not declare recovery from a global average.
7. Start an affected-record ledger before any replay or customer-visible repair.

### Bad fixes

- `scale consumers and expect one partition to split`: adds idle consumers or cold-partition capacity; it cannot parallelize the single hot partition that preserves per-auction order.
- `increase partitions mid-auction`: changes ordering/key mapping under load and can corrupt assumptions for stateful consumers.
- `drop the poison event without audit`: can destroy replay evidence or resurrect/de-synchronize state before repair is safe.
- `change key to user_id and reorder bids`: parallelizes by sacrificing per-auction ordering, the core correctness invariant.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: bid ledger plus Kafka partition/offset audit.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- partition/key lag dashboards
- ordered poison-message quarantine
- celebrity auction lane strategy
- schema tests against all consumers

Acceptance criteria:
- The exact bad config from the drill is blocked or requires senior review.
- A staging drill reproduces the old failure and verifies safe rollback/replay.
- The dashboard contains the sliced SLI and the scarce-resource metric together.
- The alert fires before customer impact or before the scarce resource reaches exhaustion.

### Org and runbook

By T+10 include incident command, the owning service team, the relevant platform/data owner, product/business owner, and support. Add payments, security, finance, warehouse, seller-ops, or customer-success when money, trust, physical fulfillment, or enterprise promises are involved.

Pre-authorized: rollback bad config, pause unsafe repair, shed noncritical work, throttle retry/replay, quarantine unhealthy replicas/consumers/pods, and communicate degraded mode. Escalate: destructive state changes, durability downgrades, broad failover, consistency weakening, manual ledger/customer remediation outside policy, or accepting derived data as truth.

### Principal-depth checklist

- Root mechanism, trigger, and amplifier are distinct.
- Evidence uses real metric/config names from the drill.
- First action protects the invariant, not the prettiest graph.
- Bad fixes are rejected with concrete failure modes.
- Capacity math precedes scale/failover/replay.
- Repair has source of truth, idempotency, throttle, and audit.
- Durable fixes include alerts, tests, config guardrails, and ownership.

---

