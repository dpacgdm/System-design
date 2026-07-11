# Week 6, Topic 3 — Outbox Pattern & Change Data Capture (CDC)

> You know how messages move (Kafka module). You know how read models diverge and reconverge (CQRS, Week 5). You know what happens when replication slots bloat (Database Scaling Patterns, Part 7). This module is the bridge: how to publish domain events *atomically* with your database writes, and how to choose between polling, WAL-based CDC, and managed alternatives without lying to yourself about delivery guarantees.

Same teaching contract as every module in this curriculum: every section answers *what do I design, what do I run, what breaks at 2 AM, and what question separates a passing answer from a principal one.*

**Prerequisites:** Message Queues and Kafka (Week 6, Topic 1), Event-Driven Architecture (Week 6, Topic 2), Database Scaling Patterns / CQRS / CDC Failure Modes (Week 5, Parts 7, 13, 14).

---

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                         ║
╟──────────────────────────────────────────────────────────────────╢
║                                                                  ║
║   1. Explain the dual-write problem and why the                  ║
║      transactional outbox is the standard fix — not              ║
║      "write to DB then publish to Kafka"                         ║
║                                                                  ║
║   2. Design an outbox table schema with correct indexes,         ║
║      partitioning, lifecycle management, and event               ║
║      payload shape for downstream consumers                      ║
║                                                                  ║
║   3. Implement and operate both polling publishers and           ║
║      Debezium CDC publishers — and articulate when each          ║
║      wins on latency, ops burden, and failure modes              ║
║                                                                  ║
║   4. Reason about at-least-once publishing as the baseline,      ║
║      idempotent consumers as the contract, and ordering          ║
║      per aggregate as a partition-key decision                   ║
║                                                                  ║
║   5. Manage schema evolution across outbox payloads,             ║
║      Debezium envelopes, and Schema Registry without             ║
║      halting the pipeline                                        ║
║                                                                  ║
║   6. Compare Debezium on MSK Connect vs polling vs AWS DMS       ║
║      for Postgres → Kafka pipelines with honest trade-offs       ║
║                                                                  ║
║   7. Diagnose CDC/outbox incidents: slot bloat, connector        ║
║      stalls, duplicate events, ordering violations, schema       ║
║      rejection cascades, and the Tuesday Afternoon Black         ║
║      Hole pattern from the Kafka module                          ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Outbox = CDC on the outbox table"                ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Outbox is a *pattern* (atomic write + async publish).       ║
║   CDC is one *transport* for step 2. Polling is another.             ║
║   "We use outbox" does not imply Debezium. Many teams poll.          ║
║   Conversely, Debezium on orders table directly is NOT outbox —      ║
║   it's row-level CDC without atomicity guarantees for events.        ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "CDC gives me exactly-once delivery"              ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. CDC delivers at-least-once from WAL to Kafka.               ║
║   Connector restarts, snapshot replays, and Kafka retries all        ║
║   produce duplicates. Exactly-once is a consumer-side                ║
║   property achieved via idempotency — never a broker promise.        ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Debezium on the business table is simpler"       ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Row-level CDC emits storage mutations, not domain           ║
║   events. One business action → N row changes. Two updates →         ║
║   two CDC events when you wanted one OrderShipped. Outbox            ║
║   publishes the event you *mean*. Direct CDC is for read-model       ║
║   replication (search, warehouse), not service choreography.         ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Polling is always too slow"                      ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Polling with FOR UPDATE SKIP LOCKED at 100–500ms            ║
║   intervals is fine for 95% of domain events. Sub-100ms              ║
║   publish latency is rarely a user-visible SLO. Debezium's           ║
║   operational tax (slots, connectors, schema coordination) is        ║
║   real. Don't pay it for vanity latency.                             ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Once published_at is set, we're done"            ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. published_at means "publisher *believes* Kafka has it."     ║
║   Crash between Kafka ack and UPDATE → duplicate publish.            ║
║   Crash before UPDATE after Kafka ack → row republished.             ║
║   Downstream MUST dedupe by event_id. published_at is                ║
║   publisher bookkeeping, not a consumer contract.                    ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "AWS DMS is drop-in Debezium"                     ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. DMS is a managed replication service with different         ║
║   semantics, latency profiles, and failure modes. It targets         ║
║   database-to-database and database-to-Kinesis/S3 paths.             ║
║   Debezium on MSK Connect gives you Kafka-native envelopes,          ║
║   SMTs (outbox event router), and Schema Registry integration.       ║
║   Pick based on team skills and pipeline shape — not logo.           ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #7: "Slot bloat only happens when CDC is broken"      ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Slot bloat happens when CDC is *slow*, not broken.          ║
║   Kafka ISR shrinkage → Debezium can't publish → slot stops          ║
║   advancing → pg_wal grows → primary disk fills. A healthy-          ║
║   looking connector with a stalled confirmed_flush_lsn is            ║
║   a ticking bomb. (Week 5, Part 7 — memorize the detection query.)   ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Part 1: Why This Module Exists — The Dual-Write Problem

Every event-driven system eventually faces the same question: *how do I update my database and notify the rest of the system atomically?*

```plaintext
THE NAIVE IMPLEMENTATION:
━━━━━━━━━━━━━━━━━━━━━━━━━

  def create_order(order):
      db.insert("orders", order)           # Step 1
      kafka.send("orders.events", {        # Step 2
          "type": "OrderCreated",
          "order_id": order.id,
          ...
      })

  Two independent systems. Two independent failure domains.
  No distributed transaction spanning Postgres and Kafka
  (and you don't want one — see Week 5, Part 12 on sagas).


THE FAILURE MATRIX:
━━━━━━━━━━━━━━━━━━━

  Step 1 (DB)    Step 2 (Kafka)    Result
  ───────────    ──────────────    ──────────────────────────────────
  ✓ success      ✓ success         Happy path. Rare in production.
  ✓ success      ✗ fail            Order exists. No event. Search
                                    empty. Fulfillment idle. Customer
                                    sees order in UI but nothing ships.
                                    THE MOST COMMON SILENT FAILURE.
  ✗ fail         ✓ success         Event published. No order. Phantom
                                    fulfillment. Inventory decremented
                                    for nothing. Harder to detect.
  ✗ fail         ✗ fail            Safe failure. User retries.
  ✓ success      ? crash           Unknown. On restart: maybe retried
                                    Kafka send → duplicate event. Or
                                    never sent → missing event.


WHY RETRIES DON'T FIX IT:
━━━━━━━━━━━━━━━━━━━━━━━

  "We'll retry Kafka if DB succeeded."
  Problem 1: How do you know DB succeeded after a crash?
             You need an out-of-band recovery scan.
  Problem 2: Retry without idempotency → duplicate events.
  Problem 3: Retry with timeout → user already got 500,
             order may or may not exist. Support ticket hell.

  "We'll use Kafka transactions (produce + consume in one txn)."
  That only works INSIDE Kafka pipelines. Your order INSERT
  is in Postgres. Kafka transactions don't span Postgres.


WHY CHANGE DATA CAPTURE ALONE DOESN'T FIX IT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  "We'll put Debezium on the orders table. Every INSERT
   becomes an event automatically."

  You get atomicity of *capture* (WAL is the source of truth),
  but not atomicity of *meaning*:

   - INSERT order row → CDC event (good)
   - UPDATE status='shipped' → CDC event (is this OrderShipped
     or a background cron fix?)
   - INSERT order + INSERT line_items + INSERT audit_log
     → THREE CDC events. Downstream must reassemble.
   - DELETE + re-INSERT (migration, data fix) → chaos.

  CDC on business tables is excellent for CQRS read models
  (Week 5, Part 13). It is a poor substitute for domain
  events to other services (Week 6 Kafka, Part 9).


THE OUTBOX INSIGHT:
━━━━━━━━━━━━━━━━━━

  Don't write to two systems. Write to ONE (Postgres) in ONE
  transaction: business data + outbox row. Let a separate
  process publish outbox rows to Kafka.

  Atomicity: Postgres ACID (free, battle-tested).
  Publish: async, at-least-once, idempotent downstream.

  This is the transactional outbox pattern. Microservices
  Papers (Chris Richardson), Enterprise Integration Patterns
  (Hohpe & Woolf), and every FAANG postmortem that mentions
  "missing events" converge here.
```

### Where Outbox Sits in the Architecture

```plaintext
                    ┌─────────────────────────────────────┐
                    │           checkout-svc              │
                    │  (application write path)           │
                    └──────────────┬──────────────────────┘
                                   │
                    BEGIN; INSERT orders; INSERT outbox; COMMIT;
                                   │
                                   ▼
                    ┌─────────────────────────────────────┐
                    │         PostgreSQL (orders DB)      │
                    │  ┌─────────┐  ┌──────────────────┐  │
                    │  │ orders  │  │ outbox           │  │
                    │  │ (truth) │  │ (pending events) │  │
                    │  └─────────┘  └────────┬─────────┘  │
                    └────────────────────────┼────────────┘
                                             │
                         ┌───────────────────┴───────────────────┐
                         │                                       │
                         ▼                                       ▼
              ┌─────────────────────┐               ┌─────────────────────┐
              │ POLLING PUBLISHER   │               │ CDC PUBLISHER       │
              │ (app-owned worker)  │               │ (Debezium / DMS)    │
              │ SELECT ... SKIP     │               │ WAL → logical slot  │
              │ LOCKED → Kafka      │               │ → Kafka             │
              └──────────┬──────────┘               └──────────┬──────────┘
                         │                                       │
                         └───────────────────┬───────────────────┘
                                             ▼
                              ┌──────────────────────────┐
                              │ Kafka: orders.events     │
                              └──────────┬───────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
             search-indexer      fulfillment-svc      analytics-loader
             (Elasticsearch)     (state machine)      (warehouse)
```

Many production systems run **both** transports on the same database:
- **Outbox → Kafka** for domain events (service choreography).
- **Direct CDC → Kafka** for CQRS read-model sync (orders table → Elasticsearch).

Same Postgres. Different tables watched. Different event shapes. Different consumers.

---

## Part 2: What the Transactional Outbox Pattern IS

```plaintext
DEFINITION:
━━━━━━━━━━━

  The transactional outbox pattern ensures that domain events
  are persisted atomically with the state change that caused
  them, by writing both to the same database in the same
  transaction, then publishing to a message broker asynchronously.


THE TWO PHASES:
━━━━━━━━━━━━━━━

  PHASE 1 — ATOMIC WRITE (synchronous, in request path):
    Application transaction includes:
     1. Mutate business tables (orders, inventory, etc.)
     2. INSERT into outbox table (event payload + metadata)
    COMMIT or ROLLBACK together. User-facing latency includes
    only Phase 1. Typically +1–3ms for the extra INSERT.

  PHASE 2 — ASYNC PUBLISH (out of request path):
    Publisher reads unpublished outbox rows, sends to Kafka,
    marks rows published (or deletes them).
    Latency: polling 100ms–2s; CDC sub-second typical.
    Failures in Phase 2 do NOT roll back the business write.
    Downstream eventual consistency bounded by publish lag.


INVARIANTS (memorize):
━━━━━━━━━━━━━━━━━━━━

  I1. Every outbox row is written in the SAME transaction
      as the business mutation it describes.

  I2. Outbox rows are IMMUTABLE after insert. Never UPDATE
      the payload. Corrections = new outbox row (new event).

  I3. Publishing is AT-LEAST-ONCE. Duplicates are expected.
      Consumers dedupe by event_id (outbox.id).

  I4. Ordering is per-partition-key, not global. Default key
      = aggregate_id (e.g., order_id) → all events for one
      order land in one Kafka partition, in order.

  I5. The outbox table is NOT the system of record for
      events long-term. Kafka retention + consumer state are.
      Outbox is a durable queue with DB-grade durability
      until published. Purge aggressively after publish.


WHAT OUTBOX IS NOT:
━━━━━━━━━━━━━━━━━━

  ✗ Not event sourcing. The orders table is the source of
    truth, not the outbox. Outbox is a side-effect log.

  ✗ Not a replacement for sagas. Multi-service workflows
    still need choreography or orchestration (Week 6 EDA).

  ✗ Not exactly-once delivery. Never claim this in design
    docs. "Effectively-once via idempotent consumers."

  ✗ Not CDC. CDC tails WAL. Outbox is application-authored
    events. You can USE CDC to read the outbox table, but
    the pattern is about write-side atomicity, not transport.
```

### Outbox vs Direct CDC vs Dual-Write — Decision Summary

```plaintext
┌────────────────────┬──────────────┬──────────────┬───────────────┐
│                    │ Dual-write   │ Direct CDC   │ Outbox        │
│                    │ (DB + Kafka) │ (WAL→Kafka)  │ (txn+publish) │
├────────────────────┼──────────────┼──────────────┼───────────────┤
│ Atomicity          │ ✗            │ capture only │ ✓ (Phase 1)   │
│ Event semantics    │ ✓ (you pick) │ row changes  │ ✓ (you pick)  │
│ Ops complexity     │ low (lies)   │ medium       │ medium        │
│ Latency to Kafka   │ lowest       │ low          │ low–medium    │
│ Duplicate handling │ required     │ required     │ required      │
│ Best for           │ nothing      │ read models  │ domain events │
│                    │ production   │ (CQRS)       │ (choreography)│
└────────────────────┴──────────────┴──────────────┴───────────────┘
```

---

## Part 3: Transactional Outbox Table Design

The outbox table is not "just another table." Schema mistakes here become production incidents at scale: table bloat slowing checkout, missing indexes causing publisher pile-ups, wrong payload shape breaking every consumer on deploy.

```plaintext
THE CANONICAL SCHEMA (Postgres):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CREATE TABLE outbox (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      aggregate_type  TEXT NOT NULL,          -- 'order', 'payment', 'user'
      aggregate_id    TEXT NOT NULL,          -- business key for partitioning
      event_type      TEXT NOT NULL,          -- 'OrderCreated', 'OrderPaid'
      payload         JSONB NOT NULL,         -- or BYTEA for Avro bytes
      metadata        JSONB DEFAULT '{}',     -- trace_id, user_id, causation_id
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
      published_at    TIMESTAMPTZ,            -- NULL = pending publish
      publish_attempts INT NOT NULL DEFAULT 0,
      last_error      TEXT
  );

  -- Publisher hot path: find unpublished rows in order
  CREATE INDEX outbox_pending_created_idx
      ON outbox (created_at)
      WHERE published_at IS NULL;

  -- Operational queries: stuck rows, per-aggregate debug
  CREATE INDEX outbox_aggregate_idx
      ON outbox (aggregate_type, aggregate_id, created_at);

  -- Optional: partition key for time-based retention
  -- (see Partitioning section below)


FIELD-BY-FIELD RATIONALE:
━━━━━━━━━━━━━━━━━━━━━━━━

  id (UUID):
    THE deduplication key. Becomes event_id in Kafka headers
    and consumer dedup tables. Use UUIDv7 (time-ordered) if
    available — better B-tree locality than random UUIDv4.
    NEVER reuse ids. NEVER derive from business keys alone
    (two OrderUpdated events for same order need distinct ids).

  aggregate_type + aggregate_id:
    Drive Kafka message key: key = aggregate_id (or
    f"{aggregate_type}:{aggregate_id}"). Ensures all events
    for one aggregate land in one partition → ordering.
    Text not BIGINT: supports non-numeric keys (SKU, email).

  event_type:
    Consumer routing. fulfillment-svc subscribes to
    OrderCreated, OrderPaid — ignores UserRegistered.
    Also drives Schema Registry subject naming:
    orders.events-OrderCreated-value.

  payload (JSONB vs BYTEA):
    JSONB: debuggable in psql, flexible, larger on disk.
           Good for <10k events/sec, small payloads.
    BYTEA: pre-serialized Avro/Protobuf. Smaller, faster
           publish (no re-serialize). Schema enforced at
           write time in application code.
    Rule: pick one per org. JSONB in dev, Avro in prod is
    a migration you'll regret.

  metadata:
    Cross-cutting context NOT in domain payload:
     - trace_id, span_id (OpenTelemetry propagation)
     - causation_id (which event caused this one)
     - user_id (audit, not always in payload)
     - schema_version
    Debezium outbox event router SMT maps metadata → headers.

  published_at:
    NULL = pending. Non-NULL = publisher claims success.
    Soft-delete pattern: retain 7–30 days for debugging,
    then partition drop or DELETE batch.

  publish_attempts / last_error:
    Observability for stuck rows. Alert when
    publish_attempts > 10 or oldest unpublished > 5 min.


THE INSERT (application code):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  BEGIN;

  INSERT INTO orders (id, customer_id, total_cents, status)
  VALUES ($1, $2, $3, 'pending');

  INSERT INTO outbox (
      aggregate_type, aggregate_id, event_type, payload, metadata
  ) VALUES (
      'order',
      $1::text,
      'OrderCreated',
      jsonb_build_object(
          'order_id', $1,
          'customer_id', $2,
          'total_cents', $3,
          'line_items', $4::jsonb
      ),
      jsonb_build_object(
          'trace_id', $5,
          'schema_version', 1
      )
  );

  COMMIT;

  Notes:
   - One transaction. One round-trip to Postgres.
   - Multiple events in one transaction: multiple INSERTs
     into outbox. All publish or none. Ordering preserved
     by created_at within the transaction (same timestamp
     → use id as tiebreaker in publisher ORDER BY).
   - NEVER publish to Kafka in this transaction.


MULTI-EVENT TRANSACTIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━

  Scenario: OrderCreated + InventoryReserved in one txn.

  INSERT INTO outbox ... 'OrderCreated' ...;
  INSERT INTO outbox ... 'InventoryReserved' ...;

  Publisher publishes both. Consumers may see them in
  either order across partitions IF you use different
  aggregate_ids as keys. If both share order_id as key,
  same partition → strict order.

  Rule: events that must be ordered together share
  aggregate_id as Kafka key.
```

### Indexing Deep Dive

```plaintext
WHY PARTIAL INDEX ON published_at IS NULL:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Without partial index:
    Publisher query scans ALL rows including millions of
    published rows. Sequential scan or bloated index.

  With partial index:
    Index contains ONLY pending rows. Typically <10k rows
    even at high throughput (publish keeps pace).
    Index stays small, hot in shared_buffers.

  EXPLAIN ANALYZE on publisher query should show:
    Index Scan using outbox_pending_created_idx
    Rows Removed by Filter: 0


WHEN TO ADD publish_attempts TO INDEX:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  If you run a "retry dead letter" worker that queries:
    WHERE published_at IS NULL AND publish_attempts > 5

  CREATE INDEX outbox_stuck_idx
      ON outbox (publish_attempts, created_at)
      WHERE published_at IS NULL AND publish_attempts > 0;


VACUUM AND BLOAT:
━━━━━━━━━━━━━━━━━

  High churn (INSERT + UPDATE published_at) causes bloat.
  Mitigations:
   - Partition by day (drop old partitions — no UPDATE bloat
     on published rows if you DELETE partition instead).
   - autovacuum tuning on outbox: lower scale_factor.
   - Monitor: pg_stat_user_tables.n_dead_tup on outbox.
```

### Partitioning Strategy

```plaintext
RANGE PARTITION BY created_at (recommended):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CREATE TABLE outbox (
      ...
  ) PARTITION BY RANGE (created_at);

  CREATE TABLE outbox_2026_07_06
      PARTITION OF outbox
      FOR VALUES FROM ('2026-07-06') TO ('2026-07-07');

  Daily cron creates tomorrow's partition.
  Retention job: DROP TABLE outbox_2026_06_29;
  (after confirming all rows published or aged out)


PUBLISHER WITH PARTITIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  Publisher must query parent table OR current + yesterday
  partitions (edge case: txn at 23:59:59, publish at 00:00:01).

  SELECT * FROM outbox
  WHERE published_at IS NULL
    AND created_at > now() - interval '2 days'
  ORDER BY created_at
  LIMIT 100
  FOR UPDATE SKIP LOCKED;

  Partition pruning: Postgres eliminates old partitions
  if created_at filter is explicit.


ALTERNATIVE: DELETE AFTER PUBLISH (no partitions):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  UPDATE ... published_at = now()  -- row stays, bloats
  vs
  DELETE FROM outbox WHERE id = ANY($1)  -- immediate reclaim
     after Kafka ack

  DELETE is simpler for small volumes (<1k events/sec).
  PARTITION + DROP is mandatory above ~5k events/sec sustained.
```

### Payload Design for Consumers

```plaintext
THIN VS FAT EVENTS (Week 6 EDA recap):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  THIN (notification):
    payload: { "order_id": "ord_123" }
    Consumer calls orders API or reads replica for details.
    Smaller outbox rows. Looser coupling. Extra latency.

  FAT (event-carried state transfer):
    payload: { full order + line items + customer snapshot }
    Consumer acts without callback. Larger rows. Schema
    coupling. PII in every Kafka copy.

  OUTBOX BIAS: lean toward FAT for critical path events
  (OrderCreated) — you've already paid the DB read to
  build the payload in the transaction. Avoid N+1 in
  consumer. But strip PII you don't need downstream.


VERSIONING IN PAYLOAD:
━━━━━━━━━━━━━━━━━━━━

  Option A: event_type version suffix
    OrderCreatedV1, OrderCreatedV2
    Explicit. Topic or subject per version. Consumer
    subscribes to both during migration.

  Option B: schema_version in metadata + backward-compatible
    JSON evolution (add fields with defaults).
    Simpler for JSONB. Dangerous without Schema Registry.

  Option C: Avro/Protobuf in BYTEA + Schema Registry
    Industry standard at scale. Week 6 Kafka Part 10.
```

---

## Part 4: Polling Publisher — Design & Operations

The polling publisher is a background worker (or fleet of workers) that reads unpublished outbox rows and publishes to Kafka. Boring, debuggable, and correct — if you implement the concurrency primitives properly.

```plaintext
THE CORE LOOP:
━━━━━━━━━━━━━━

  while True:
      rows = db.fetch("""
          SELECT id, aggregate_id, event_type, payload, metadata
          FROM outbox
          WHERE published_at IS NULL
          ORDER BY created_at, id
          LIMIT 100
          FOR UPDATE SKIP LOCKED
      """)

      if not rows:
          sleep(poll_interval_ms)  # 100–500 typical
          continue

      for row in rows:
          try:
              kafka.produce(
                  topic=topic_for(row.event_type),
                  key=row.aggregate_id.encode(),
                  value=serialize(row.payload),
                  headers=build_headers(row),
              )
              kafka.flush()  # or per-batch flush
              mark_published(row.id)
          except KafkaError as e:
              increment_attempts(row.id, str(e))
              # do NOT mark published; row stays locked until
              # txn end, then available for retry

      # Optional: kafka.producer.flush() once per batch


FOR UPDATE SKIP LOCKED — WHY IT MATTERS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Without SKIP LOCKED:
    Publisher A: SELECT ... FOR UPDATE  (locks rows 1–100)
    Publisher B: SELECT ... FOR UPDATE  (BLOCKS waiting for A)
    Publisher B is idle. No horizontal scale.

  With SKIP LOCKED:
    Publisher A: locks rows 1–100
    Publisher B: skips 1–100, locks 101–200
    Both publish in parallel. Linear scale to ~N publishers
    until DB or Kafka becomes bottleneck.

  Postgres 9.5+. MySQL 8+ (FOR UPDATE SKIP LOCKED).
  SQL Server: READPAST hint. Oracle: SKIP LOCKED.


TRANSACTION BOUNDARIES:
━━━━━━━━━━━━━━━━━━━━━━

  Pattern A — lock, publish, mark (risky):
    BEGIN; SELECT FOR UPDATE; COMMIT;  # release locks early
    kafka.produce(...);                 # crash here = duplicate
    UPDATE published_at;

  Pattern B — lock through mark (better):
    BEGIN;
      SELECT ... FOR UPDATE SKIP LOCKED;
      -- rows locked for this txn duration
    -- publish OUTSIDE txn is required (Kafka not XA)
    COMMIT;  # release locks BEFORE kafka if publish is slow

  The fundamental tension: you cannot hold row locks during
  Kafka produce (seconds) without blocking other publishers.

  Production pattern:
    1. SELECT ids FOR UPDATE SKIP LOCKED → commit (short lock)
    2. Re-select those ids WHERE published_at IS NULL
       (another publisher may have taken them — check)
    3. Publish to Kafka
    4. UPDATE published_at WHERE id IN (...) AND published_at IS NULL

  Step 4 is idempotent. Duplicate publish from race = OK
  if consumers dedupe.


BATCHING FOR THROUGHPUT:
━━━━━━━━━━━━━━━━━━━━━━━

  kafka.producer with:
    linger.ms = 20
    batch.size = 65536
    compression.type = lz4

  Publish 100 rows, single flush(). Latency +20ms,
  throughput 5–10×.

  Trade-off: crash after flush, before UPDATE → 100
  duplicates. Consumers handle it.


MULTI-PUBLISHER DEPLOYMENT:
━━━━━━━━━━━━━━━━━━━━━━━━━

  Kubernetes: Deployment with 3–8 replicas.
  No leader election needed (SKIP LOCKED handles it).
  HPA on: outbox_pending_count metric (custom Prometheus
  from periodic COUNT(*) WHERE published_at IS NULL).

  Anti-pattern: CronJob every minute. Tail latency up to
  60s. Use long-running Deployment.


POLL INTERVAL MATH:
━━━━━━━━━━━━━━━━━

  Events/sec = E. Batch size = B. Poll interval = P.
  Max publisher throughput ≈ B / P  (if Kafka keeps up).

  Example: B=100, P=0.2s → 500 events/sec max per publisher.
  3 publishers → 1500/sec. Size accordingly.

  p99 publish latency ≈ P + kafka_produce_time + jitter.
  P=100ms → ~150–300ms typical tail.
```

### Polling Publisher — Failure Modes

```plaintext
STUCK ROWS (publish_attempts climbing):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Causes:
   - Kafka cluster unhealthy (ISR, auth, ACL)
   - Schema Registry rejection
   - Payload serialization error (bad JSON → Avro)
   - Row too large (> max.message.bytes)

  Detection:
    SELECT id, event_type, publish_attempts, last_error, created_at
    FROM outbox
    WHERE published_at IS NULL
      AND publish_attempts > 5
    ORDER BY created_at;

  Response:
   - Fix root cause (Kafka, schema)
   - Manual replay after fix
   - DLQ pattern: move to outbox_dead_letter after N attempts


TABLE GROWTH (published rows not purged):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: orders DB disk climbing, checkout latency up.
  Cause: published_at set but rows never deleted/partition dropped.

  Fix: retention job. Alert on outbox table size > threshold.


THUNDERING HERD ON RECOVERY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Kafka was down 10 minutes. 50k unpublished rows.
  Kafka recovers. All publishers flush simultaneously.
  Mitigation: exponential backoff on empty/error; rate limit
  produce; scale publishers gradually.


DB LOAD FROM POLLING:
━━━━━━━━━━━━━━━━━━━━━

  Each poll = indexed SELECT. At 100ms interval, 10 QPS
  per publisher. Negligible for Postgres.

  At 10ms interval with 20 publishers: 2000 QPS of identical
  queries. Consider LISTEN/NOTIFY (see below) or CDC.


LISTEN/NOTIFY OPTIMIZATION (Postgres):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Trigger on outbox INSERT:
    PERFORM pg_notify('outbox_new', NEW.id::text);

  Publisher:
    LISTEN outbox_new;
    -- wake on notify, else poll every 1s fallback

  Cuts idle polling. Sub-ms wake latency. Still at-least-once.
  NOTIFY is not durable — always keep polling fallback.
```

### Polling vs Request Path Isolation

```plaintext
CRITICAL: publisher runs on SEPARATE connection pool
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Never share the checkout-svc connection pool with the
  outbox publisher. Publisher spikes (recovery) must not
  exhaust connections for user-facing writes.

  Typical split:
   - checkout-svc: pool max 50, reserved for HTTP handlers
   - outbox-publisher: pool max 10, own Deployment

  Same database. Different credentials optional (publisher
  needs SELECT+UPDATE on outbox only — principle of least
  privilege).
```

---

## Part 5: CDC Publisher — WAL, Debezium, and the Outbox Event Router

Change Data Capture reads the database write-ahead log (WAL) and streams row-level changes to Kafka. For outbox, you configure CDC to watch *only* the outbox table and transform inserts into clean domain events.

```plaintext
HOW LOGICAL CDC WORKS (Postgres):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Application INSERTs into outbox (normal txn).
  2. Postgres writes to WAL (Write-Ahead Log) on commit.
  3. Logical replication slot bookmarks position in WAL.
  4. Debezium (pgoutput plugin) reads WAL from slot position.
  5. Debezium converts INSERT to change event envelope.
  6. Outbox Event Router SMT extracts payload → Kafka record.
  7. Debezium advances confirmed_flush_lsn on success.

  Application never calls Kafka. Latency = WAL flush +
  Debezium poll + Kafka produce. Typically 50–500ms.


THE REPLICATION SLOT (Week 5, Part 7 — required reading):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  A slot is a server-side bookmark: "do not recycle WAL
  until consumer has read past position X."

  If Debezium stalls (Kafka down, bug, network):
    confirmed_flush_lsn stops advancing
    → WAL accumulates on primary disk (pg_wal/)
    → disk fills → PRIMARY DOWN

  Detection query (run hourly, page on results):

  SELECT slot_name, active,
         pg_size_pretty(pg_wal_lsn_diff(
           pg_current_wal_lsn(), restart_lsn)) AS retained_wal
  FROM pg_replication_slots
  ORDER BY retained_wal DESC;

  Prevention:
   - max_slot_wal_keep_size = 100GB (Postgres 13+)
   - Alert: retained_wal > 10GB warn, > 50GB page
   - Alert: active = false for > 1 hour


DEBEZIUM CONNECTOR CONFIG (outbox table only):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "orders-db.primary.internal",
    "database.port": "5432",
    "database.user": "debezium",
    "database.password": "${secrets}",
    "database.dbname": "orders",
    "topic.prefix": "orders_db",
    "table.include.list": "public.outbox",
    "plugin.name": "pgoutput",
    "slot.name": "debezium_outbox_orders",
    "publication.name": "dbz_outbox_publication",
    "transforms": "outbox",
    "transforms.outbox.type": "io.debezium.transforms.outbox.EventRouter",
    "transforms.outbox.table.field.event.id": "id",
    "transforms.outbox.table.field.event.key": "aggregate_id",
    "transforms.outbox.table.field.event.type": "event_type",
    "transforms.outbox.table.field.event.payload": "payload",
    "transforms.outbox.route.by.field": "event_type",
    "transforms.outbox.route.topic.replacement": "orders.events",
    "transforms.outbox.table.expand.json.payload": "true",
    "key.converter": "org.apache.kafka.connect.json.JsonConverter",
    "value.converter": "org.apache.kafka.connect.json.JsonConverter",
    "errors.tolerance": "none",
    "errors.deadletterqueue.topic.name": "orders.outbox.dlq",
    "errors.deadletterqueue.context.headers.enable": "true"
  }


OUTBOX EVENT ROUTER SMT:
━━━━━━━━━━━━━━━━━━━━━━━

  Transforms Debezium's raw envelope:

    { "op": "c", "after": { "id": "...", "event_type": "OrderCreated",
        "payload": "{...}", ... } }

  Into Kafka message:

    topic: orders.events  (or routed per event_type)
    key:   aggregate_id
    value: payload (expanded JSON)
    headers: id, event_type, source metadata

  Skips UPDATE/DELETE on outbox if you only INSERT.
  If you soft-mark published_at via UPDATE, Debezium emits
  UPDATE events — configure router to ignore or don't UPDATE
  (use DELETE or partition drop instead).


MSK CONNECT DEPLOYMENT:
━━━━━━━━━━━━━━━━━━━━━━

  Debezium runs as Kafka Connect worker on MSK Connect.
  Worker connects to:
   - Postgres primary (logical replication)
   - MSK cluster (produce)
   - Schema Registry (optional, for Avro)

  Sizing: 1 MCU per connector typical for <5k events/sec.
  Scale workers before adding duplicate connectors on same
  slot (DON'T — one slot per connector).


WHY NOT CDC THE BUSINESS TABLES FOR DOMAIN EVENTS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  (Recap from Kafka Part 9 — exam favorite)

  orders table CDC on status change:
    before: { status: 'pending' }
    after:  { status: 'shipped' }

  Is that OrderShipped? OrderCancelled-then-fixed? Admin
  override? Consumer can't tell.

  outbox row:
    event_type: 'OrderShipped'
    payload: { order_id, shipped_at, carrier, tracking }

  You authored the meaning. CDC just transports it.
```

### WAL Mechanics — What Debezium Actually Reads

```plaintext
POSTGRES WAL STRUCTURE (simplified):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Every committed transaction appends records to WAL files
  in pg_wal/. Records include:
   - heap INSERT/UPDATE/DELETE for logical decoding
   - transaction commit LSN

  Logical decoding plugin (pgoutput) converts physical WAL
  to logical change stream filtered by publication.

  Publication for outbox only:
    CREATE PUBLICATION dbz_outbox_publication
      FOR TABLE public.outbox;


LSN (Log Sequence Number):
━━━━━━━━━━━━━━━━━━━━━━━━

  Monotonic pointer into WAL byte stream.
  Debezium tracks:
   - restart_lsn: slot position (what PG retains from)
   - confirmed_flush_lsn: what Debezium acked to PG

  Lag bytes = pg_current_wal_lsn() - confirmed_flush_lsn
  Lag time  = correlate LSN advancement with wall clock

  Dashboard both. Bytes grow before time lag shows in
  consumer-facing metrics.


SNAPSHOT ON FIRST START:
━━━━━━━━━━━━━━━━━━━━━━

  Debezium initial snapshot: reads entire outbox table,
  emits READ events for existing rows.

  Problem: republishes historical events to Kafka.
  Mitigation:
   - snapshot.mode = no_data (only new changes)
     Use when outbox is empty on first deploy.
   - snapshot.mode = initial + idempotent consumers
     Use when migrating from polling to CDC.
   - Truncate outbox before first CDC start (if safe).

  Week 5 Part 14 Failure 1: snapshot restart duplicates.
```

---

## Part 6: At-Least-Once Publishing — The Only Honest Guarantee

Every outbox pipeline delivers **at-least-once** from database to Kafka to consumer. Pretending otherwise is how phantom charges and duplicate shipments enter production.

```plaintext
WHERE DUPLICATES ENTER (complete map):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. POLLING PUBLISHER
     Crash after kafka.ack, before UPDATE published_at
     → row republished on restart.

     Two publishers race: both read same row before either
     marks published (if lock scope wrong).

  2. CDC / DEBEZIUM
     Connector restart before offset commit → events replayed.
     Snapshot restart → entire table re-emitted (op=READ).
     Kafka producer retries → duplicate records (mitigated
     by producer idempotence for same key+sequence).

  3. KAFKA BROKER
     Producer retries with idempotence=false → dupes.
     Unclean leader election (unclean.leader.election.enable
     = true) → rare duplicate or loss. Keep false.

  4. CONSUMER
     Process message, crash before offset commit → redelivery.
     Rebalance during processing → another consumer gets same
     batch (if auto-commit misconfigured).


AT-MOST-ONCE VS AT-LEAST-ONCE VS EFFECTIVELY-ONCE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  AT-MOST-ONCE:
    Publish then mark published. Crash between → lost event.
    Never acceptable for domain events.

  AT-LEAST-ONCE (publisher default):
    Mark published only after Kafka ack. Crash → retry →
    duplicate. Acceptable WITH idempotent consumers.

  EFFECTIVELY-ONCE (system goal):
    At-least-once transport + idempotent consumer effects
    = business outcome same as exactly-once.
    This is what you put in design docs.


PUBLISHER-SIDE HARDENING:
━━━━━━━━━━━━━━━━━━━━━━━━

  Kafka producer config:
    enable.idempotence=true
    acks=all
    retries=2147483647  (or high)
    max.in.flight.requests.per.connection=5
      (required with idempotence)

  Message key = outbox.id (UUID) OR aggregate_id?
    - key=outbox.id: max spread across partitions, NO
      ordering between events for same aggregate. Wrong
      for state machine consumers.
    - key=aggregate_id: ordering per aggregate. Duplicates
      same key → idempotent producer dedupes within
      producer session. STILL need consumer dedup across
      sessions/restarts.

  Recommendation:
    key = aggregate_id (ordering)
    headers: event_id = outbox.id (dedup)
    value: payload


THE published_at FIELD SEMANTICS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Polling: set published_at after producer callback confirms
           offset for partition.

  CDC: published_at may stay NULL forever (Debezium doesn't
        update outbox). Alternative:
         - DELETE row after CDC publish (trigger-based audit)
         - Separate published_at updated by lightweight
           "mark published" consumer (overkill)
         - Rely on Kafka retention + outbox partition DROP

  Many CDC deployments never set published_at. Retention =
  partition DROP on outbox by age. Pending = unpublished
  rows in recent partitions only.


MONITORING AT-LEAST-ONCE HEALTH:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Metric: outbox_publish_lag_seconds
    = now() - min(created_at) WHERE published_at IS NULL

  Metric: kafka_producer_record_error_rate (per publisher)

  Metric: debezium_millisecond_behind_source

  SLO example: 99% of events published within 5 seconds
  of created_at.
```

### End-to-End Delivery Diagram

```plaintext
  [checkout-svc]
       │ txn commit (order + outbox row)
       ▼
  [Postgres outbox] ─────────────────────────────────────┐
       │                                                    │
       │ polling or CDC                                     │
       ▼                                                    │
  [Publisher] ──at-least-once──► [Kafka orders.events]     │
       │                              │                     │
       │ duplicate possible           │ duplicate possible  │
       ▼                              ▼                     │
  [fulfillment-svc]              [search-indexer]          │
       │ idempotent dedup              │ idempotent dedup   │
       ▼                              ▼                     │
  [fulfillment DB]               [Elasticsearch]            │
                                                            │
  If publisher stalls ◄───────────────────────────────────┘
  outbox rows accumulate (visible lag metric)
  If CDC stalls: slot bloat threatens PRIMARY (Week 5 P7)
```

---

## Part 7: Idempotent Consumers — The Contract Downstream

The outbox guarantees atomic write. Kafka guarantees durable log. **Consumers** guarantee correct business outcome under duplicate delivery.

```plaintext
THE GOLDEN RULE:
━━━━━━━━━━━━━━━

  event_id (outbox.id) is the idempotency key.
  Consumer must process each event_id at most once FOR EFFECT.


PATTERN 1 — DEDUP TABLE (most explicit):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  BEGIN;
    INSERT INTO processed_events (event_id, processed_at)
    VALUES ($1, now())
    ON CONFLICT (event_id) DO NOTHING;

    GET DIAGNOSTICS rows = ROW_COUNT;
    IF rows = 0 THEN
      ROLLBACK;  -- already processed, skip
      COMMIT offset anyway;
      RETURN;
    END IF;

    -- apply business logic
    UPDATE orders SET status = 'shipped' WHERE id = $2;
  COMMIT;

  consumer.commitSync();  -- AFTER db commit

  processed_events retention: partition by week, drop > 90 days.
  Size: ~16 bytes × event_id per processed event.
  At 10M events/day = 160MB/day. Plan retention.


PATTERN 2 — UPSERT BY NATURAL KEY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Message: OrderCreated { order_id, ... }
  INSERT INTO orders (...) ON CONFLICT (order_id) DO UPDATE
    SET ... WHERE orders.updated_at < EXCLUDED.updated_at;

  Works when event maps 1:1 to row and payload is complete.
  Duplicate OrderCreated → same final row. Safe.

  FAILS for: OrderShipped then OrderCancelled — need
  state machine with version or event sequence.


PATTERN 3 — VERSION / SEQUENCE (state machines):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  payload: { order_id, sequence: 5, status: 'shipped' }
  UPDATE orders SET status='shipped', last_sequence=5
    WHERE order_id=$1 AND last_sequence < 5;

  Duplicate sequence 5 → 0 rows updated. Safe.

  Outbox: include monotonic sequence per aggregate in
  application when emitting multiple event types.


PATTERN 4 — LSN / OFFSET TRACKING (CDC consumers):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Week 5 Part 14 Failure 5:
    Store last_applied_lsn per aggregate_id.
    Debezium envelope includes source.lsn.
    If incoming.lsn <= stored → skip (stale/duplicate).

  Required when re-keying CDC stream or consuming
  direct table CDC (not just outbox).


TRANSACTIONAL CONSUMER (Week 6 Kafka Part 8):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Order of operations:
    1. BEGIN db txn
    2. Dedup check + business write
    3. COMMIT db txn
    4. commit Kafka offset

  Never commit offset before db commit.
  Never db commit without dedup in same txn.


DEBEZIUM HEADER event_id:
━━━━━━━━━━━━━━━━━━━━━━━━

  Outbox Event Router sets header `id` from outbox.id.
  Consumer reads:
    event_id = headers['id'] or payload.meta.event_id

  Standardize across services. Put in consumer SDK.


IDEMPOTENCY AND SIDE EFFECTS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Idempotent DB write ≠ idempotent email send.
  Pattern: outbox on consumer side too (transactional
  outbox for emails) OR idempotency key on provider
  (Stripe Idempotency-Key, SendGrid custom arg).

  Exam trap: "consumer is idempotent" — ask about
  third-party API calls.
```

### Consumer Dedup — Schema

```sql
-- Shared pattern across fulfillment, search indexer, etc.

CREATE TABLE processed_events (
    event_id        UUID PRIMARY KEY,
    event_type      TEXT NOT NULL,
    aggregate_id    TEXT,
    kafka_topic     TEXT,
    kafka_partition INT,
    kafka_offset    BIGINT,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (processed_at);

CREATE INDEX processed_events_aggregate_idx
    ON processed_events (aggregate_id, processed_at);

-- Weekly partition creation + 90-day drop via cron
```

---

## Part 8: Ordering Guarantees

Ordering is not a broker feature you enable. It is a consequence of partition key choice, consumer concurrency, and failure handling.

```plaintext
KAFKA ORDERING RULE (Week 6 Kafka Part 2):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Order guaranteed WITHIN a partition.
  NO order across partitions.
  NO global order across topic.


OUTBOX DEFAULT:
━━━━━━━━━━━━━━

  Kafka message key = aggregate_id (e.g., order_id).
  hash(key) % num_partitions → fixed partition per order.
  All OrderCreated, OrderPaid, OrderShipped for order 123
  → same partition → consumer processes in offset order.


WHEN ORDERING BREAKS:
━━━━━━━━━━━━━━━━━━━

  1. NULL key or random key
     → round-robin partitions → events for same order
       processed out of order.

  2. Key change mid-lifecycle
     order_id as key, then re-key to customer_id for
     "customer timeline" → ordering lost.

  3. Multiple consumers on same partition
     Impossible in one group — one consumer per partition.
     But: async processing inside consumer (thread pool)
     → submit OrderPaid before OrderCreated finishes.
     Fix: single-threaded per partition OR per-key
     in-memory queue.

  4. Retry to different partition
     Shouldn't happen with fixed key. If producer omits
     key on retry → disaster.

  5. CDC re-key SMT
     Week 5 Part 14 Failure 5: re-key by user_id breaks
     per-order ordering.


OUT-OF-ORDER HANDLING (defensive):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Even with correct keys, duplicates + retries can cause
  apparent out-of-order (duplicate old event after new).

  Defense: sequence numbers in payload + conditional apply
    IF event.sequence > entity.last_sequence THEN apply

  Or: tolerate out-of-order for idempotent state merges
    (set status=shipped is commutative if already shipped)


MULTI-EVENT SINGLE TRANSACTION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Two outbox INSERTs same txn, same created_at:
    OrderCreated (seq implicit: id order)
    InventoryReserved

  Publisher ORDER BY created_at, id → deterministic publish
  order. Same partition if same aggregate_id key → consumer
  sees correct order.


PARTITION COUNT VS ORDERING SCOPE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  More partitions = more parallelism, same per-key order.
  Hot key still lands on one partition (hot partition
  problem — Week 6 Kafka Part 3).

  Don't increase partitions to "fix" ordering — fix the key.


CROSS-AGGREGATE ORDERING:
━━━━━━━━━━━━━━━━━━━━━━━

  "Payment must be processed before shipment globally."
  Kafka cannot guarantee this across keys.

  Solutions:
   - Single partition topic (throughput ceiling — bad)
   - Saga orchestrator sequences steps
   - Idempotent state machine tolerates reorder if
     invalid transitions rejected (PaymentReceived before
     OrderCreated → park in pending table)
```

### Ordering Decision Table

```plaintext
┌─────────────────────────────┬────────────────────────────────┐
│ Requirement                 │ Design choice                  │
├─────────────────────────────┼────────────────────────────────┤
│ Per-order event sequence    │ key = order_id                 │
│ Per-customer timeline       │ key = customer_id; accept      │
│                             │ cross-order interleaving       │
│ Global total order          │ not on Kafka; use DB or        │
│                             │ single partition (rare)        │
│ Cross-service causal order  │ saga + correlation_id in       │
│                             │ metadata; not broker order     │
└─────────────────────────────┴────────────────────────────────┘
```

---

## Part 9: Schema Evolution — Outbox Payloads, Debezium, and Schema Registry

Schema breaks don't announce themselves. They arrive as a connector in FAILED state, a consumer in CrashLoopBackOff, and a replication slot eating your primary disk.

```plaintext
THREE LAYERS OF SCHEMA:
━━━━━━━━━━━━━━━━━━━━━━

  1. OUTBOX TABLE DDL (Postgres)
     Adding column to outbox: trivial (nullable).
     Changing payload JSONB shape: application concern.

  2. KAFKA MESSAGE SCHEMA (Avro/Protobuf/JSON Schema)
     Schema Registry enforces compatibility on produce.

  3. CONSUMER DESERIALIZATION CODE
     Generated classes or dynamic readers. Deploy order
     matters: consumer first (backward) or producer first
     (forward).


DEBEZIUM + SCHEMA REGISTRY:
━━━━━━━━━━━━━━━━━━━━━━━━━

  Outbox payload as JSONB expanded by Event Router:
    Often JSON without Registry (simple path).

  Outbox payload as BYTEA (Avro serialized in app):
    Converter: io.confluent.connect.avro.AvroConverter
    schema.registry.url = https://sr.internal:8081
    Debezium publishes Avro values; Registry stores schema.

  Envelope schema (Debezium default) vs payload-only
  (Event Router): Router strips envelope — consumers see
  domain schema only. Preferred for service consumers.


COMPATIBILITY MODES (Week 6 Kafka Part 10):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  BACKWARD (default for consumers-deploy-first):
    New schema can read old data.
    Safe: add field with default. Remove optional field.

  FORWARD (producers-deploy-first):
    Old schema can read new data.
    Safe: add optional field only.

  FULL / FULL_TRANSITIVE:
    Both directions. Use for critical topics.

  Week 5 Part 14 Failure 2:
    DBA drops column → BACKWARD-compatible Registry change.
    Consumer with FORWARD mode REJECTS → halt → slot bloat.


THE EXPAND → MIGRATE → CONTRACT PATTERN:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 1 EXPAND:
    Add new_field to Avro with default null.
    Deploy producers writing both old and new fields.

  Phase 2 MIGRATE:
    Deploy consumers reading new_field, fallback old.

  Phase 3 CONTRACT:
    Stop writing old_field. Deploy producers.
    Remove old_field from schema (BACKWARD compat OK
    if field had default).

  Same as database migrations. Run over multiple deploys.
  NEVER rename field in Avro — add new, deprecate old.


OUTBOX-SPECIFIC: event_type VERSIONING:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Instead of mutating OrderCreated schema in place:
    OrderCreatedV1 → topic orders.events.v1
    OrderCreatedV2 → topic orders.events.v2
    Or single topic, event_type header distinguishes.

  Consumer subscribes to both during migration window.


SCHEMA DRIFT WITHOUT REGISTRY CHANGE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Producer changes cents → dollars in JSON payload.
  No schema change detected. Consumers charge 100× wrong.

  Defense:
   - Contract tests in CI (Pact, schema fixtures)
   - payload schema_version in metadata; consumer rejects
     unknown major version to DLQ
   - Code review on payload struct changes


PRE-DEPLOY GATE (Week 5 Part 14):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CI step: schema diff against Registry
  Fail PR if incompatible for topic orders.events.

  For JSONB outbox: JSON Schema check in application
  before INSERT.
```

### Schema Evolution Playbook — Worked Example

```plaintext
SCENARIO: Add `gift_message` to OrderCreated

  Step 1: Update Avro schema (add gift_message: ["null","string"] default null)
          Register v2. Compatibility: BACKWARD ✓

  Step 2: Deploy fulfillment-svc consumer (reads gift_message, ignores if null)

  Step 3: Deploy checkout-svc producer (writes gift_message when present)

  Step 4: No contract phase needed (additive only)

  Rollback: revert producer; consumer still handles null.


SCENARIO: Rename total_cents → total_amount_cents

  NEVER rename in Avro.

  Step 1: Add total_amount_cents alongside total_cents (both written)
  Step 2: Consumers read total_amount_cents, fallback total_cents
  Step 3: Stop writing total_cents
  Step 4: Remove total_cents from schema (default null for old messages)
```

---

## Part 10: Debezium vs Polling vs AWS DMS on MSK

This is the principal-level trade-off section. Interviewers ask it. Production teams regret skipping it.

```plaintext
COMPARISON MATRIX:
━━━━━━━━━━━━━━━━

┌──────────────────┬─────────────┬─────────────┬─────────────────┐
│ Dimension        │ Polling     │ Debezium    │ AWS DMS         │
│                  │ publisher   │ MSK Connect │ (→ Kafka/KS)    │
├──────────────────┼─────────────┼─────────────┼─────────────────┤
│ Publish latency  │ 100ms–2s    │ 50–500ms    │ 1–30s typical   │
│ DB read load     │ indexed     │ WAL stream  │ WAL/binlog read │
│                  │ SELECTs     │ (low CPU)   │ (varies)        │
│ Ops ownership    │ your app    │ Connect +   │ AWS managed     │
│                  │ team        │ connector   │ task            │
│ Slot bloat risk  │ none        │ YES (P7)    │ YES (similar)   │
│ Event shape      │ native      │ SMT router  │ table mapping   │
│ Schema Registry  │ app-side    │ Connect     │ limited/native  │
│                  │             │ converters  │                 │
│ Multi-table      │ one worker  │ one conn per│ per-task        │
│                  │ any table   │ DB typical  │                 │
│ Local dev        │ trivial     │ Docker +    │ AWS only        │
│                  │             │ Kafka stack │                 │
│ Cost at scale    │ compute for │ MSK Connect │ DMS instance +  │
│                  │ publishers  │ MCUs + MSK  │ data transfer   │
│ Exactly-once     │ no          │ no          │ no              │
│ claim            │             │             │                 │
└──────────────────┴─────────────┴─────────────┴─────────────────┘


WHEN TO CHOOSE POLLING:
━━━━━━━━━━━━━━━━━━━━━

  ✓ < 2k events/sec on outbox
  ✓ Team lacks Kafka Connect operational experience
  ✓ Strict control over publish logic (routing, enrichment)
  ✓ Latency SLO > 500ms acceptable
  ✓ Want to avoid replication slots on primary entirely
  ✓ Startup / MVP proving domain model

  Shopify, Stripe-scale systems have run polling outbox
  for years. It is not "junior engineering."


WHEN TO CHOOSE DEBEZIUM ON MSK CONNECT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ✓ > 2k events/sec sustained on outbox
  ✓ Sub-200ms publish latency SLO
  ✓ Already running MSK + Connect for other connectors
  ✓ Standardized on Outbox Event Router SMT
  ✓ Team can own slot monitoring (Week 5 dashboards)
  ✓ Multiple services share outbox publish infrastructure

  Operational checklist before adopting:
   □ max_slot_wal_keep_size set on Postgres
   □ Slot registry with owner + alert
   □ DLQ topic configured on connector
   □ Runbook for snapshot restart duplicates
   □ confirmed_flush_lsn on dashboard next to consumer lag


WHEN TO CHOOSE AWS DMS:
━━━━━━━━━━━━━━━━━━━

  ✓ Organization mandate: managed AWS only, no self-run Connect
  ✓ Pipeline: Postgres → Kafka via DMS → MSK (supported path)
    OR Postgres → S3 → analytics (more common DMS sweet spot)
  ✓ Team familiar with DMS from database migration projects
  ✓ Need homogeneous multi-source replication (Oracle + PG)
    with one tool

  Caveats for outbox → Kafka:
   - Transformation logic less flexible than Debezium SMTs
   - Latency higher than Debezium for low-lag domain events
   - Error visibility differs; DLQ patterns vary
   - Test event shape carefully — may get full row envelope
     not Event Router clean payload

  DMS shines for: lift-and-shift DB replication, warehouse
  ingest, not sub-100ms choreography.


HYBRID (common at scale):
━━━━━━━━━━━━━━━━━━━━━━━

  Polling for low-volume admin/domain events.
  Debezium on outbox for orders/payments high-volume tables.
  Direct Debezium CDC (no outbox) on orders table →
  Elasticsearch for CQRS search (Week 5 Part 13).

  Three connectors, three operational surfaces. Document
  which path each consumer uses.


MSK CONNECT SIZING (Debezium):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1 MCU = 1 GB RAM, 1 vCPU equivalent on Connect worker.

  Rule of thumb:
   < 5k events/sec, avg 2KB payload → 2 MCU worker
   5k–20k events/sec → 4–8 MCU, monitor cpuUtilization
   > 20k events/sec → partition outbox table by domain,
   multiple connectors with separate slots (careful with
   primary load — each slot retains WAL independently)


COST SANITY (order of magnitude, us-east-1):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Polling: 3× t3.small K8s pods ≈ $50/mo + existing PG
  Debezium MSK Connect: 4 MCU ≈ $200/mo + MSK cluster
  DMS: dms.c5.large ≈ $250/mo + data transfer

  None of this matters vs one hour of checkout outage.
  Pick ops fit over $150/mo savings.
```

### Migration Paths

```plaintext
POLLING → DEBEZIUM (zero-downtime sketch):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Deploy Debezium with snapshot.mode=no_data
     (only new INSERTs after connector start).

  2. Run polling publisher in parallel (dual publish).
     Consumers dedupe by event_id — duplicates OK briefly.

  3. Verify Debezium lag < polling lag for 24h.

  4. Disable polling publisher.

  5. Monitor slot health for 1 week.

  Rollback: re-enable polling. Dedup handles overlap.


DEBEZIUM → POLLING (incident rollback):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Connector FAILED, slot approaching cap, checkout at risk.

  1. Pause Debezium connector (stops WAL read, slot frozen
     — still retains WAL unless you drop slot).

  2. Start polling publisher against unpublished rows
     (published_at IS NULL).

  3. If slot bloat emergency: drop slot after polling
     catches up OR after max_slot_wal_keep_size invalidates.

  4. Fix connector offline. Re-snapshot if slot was dropped.
```

---

## Failure Modes

Outbox and CDC failures cascade: publisher stall → outbox growth → lag → slot bloat → primary disk → **entire platform down**, not just async consumers.

```plaintext
FAILURE MODE 1 — KAFKA ISR SHRINKAGE STALLS DEBEZIUM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  (Kafka module: Tuesday Afternoon Black Hole, 13:57 UTC)

  Chain:
   click.stream overload → broker request queue saturated
   → orders.events followers lag > 30s → ISR shrink
   → Debezium produce acks=all FAILS
   → confirmed_flush_lsn frozen
   → pg_wal grows on orders primary
   → 6 hours to disk full

  Symptoms:
   - Debezium connector RUNNING (green lie)
   - millisecond_behind_source climbing
   - retained_wal on slot climbing
   - outbox rows with published_at NULL (if polling backup)
   - Checkout still works (DB fine) — async drift only
     until disk fills

  Fix order:
   1. Restore Kafka ISR health (stop poison producer load)
   2. Verify Debezium advancing flush LSN
   3. If disk critical: evaluate slot drop vs primary survival


FAILURE MODE 2 — SLOT BLOAT (Week 5 Part 7)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Causes beyond Kafka:
   - Connector paused for maintenance, slot not dropped
   - Debezium OOM loop — active=false, WAL pinned
   - Network partition between Connect and Postgres
   - Test connector left in prod after hackathon

  Detection:
    SELECT slot_name, active,
           pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS bytes
    FROM pg_replication_slots;

  Prevention:
    max_slot_wal_keep_size = 100GB
    Slot owner registry
    Daily cron: drop slots matching ^test_

  Recovery:
    Fix consumer → slot advances naturally
    OR pg_drop_replication_slot → re-snapshot (hours)


FAILURE MODE 3 — SNAPSHOT RESTART DUPLICATES (Week 5 P14-F1)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Connector crash mid-initial snapshot.
  Restart → full re-snapshot → every outbox row re-emitted.

  Consumer impact: duplicate OrderCreated flood.
  If consumer not idempotent: duplicate shipments.

  Defense: idempotent consumers + snapshot.mode tuning +
  monitor op=r (READ) rate spike on topic.


FAILURE MODE 4 — SCHEMA REJECTION CASCADE (Week 5 P14-F2)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Incompatible schema → connector or consumer halts
  → lag → slot bloat → secondary primary risk.

  Defense: Registry compatibility FULL_TRANSITIVE in CI.
  DLQ for deserialization errors (consumer side).


FAILURE MODE 5 — ORDERING VIOLATION (Week 5 P14-F5)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Re-key SMT or wrong partition key → OrderShipped before
  OrderCreated in consumer → invalid state.

  Defense: sequence numbers + LSN compare in consumer.


FAILURE MODE 6 — OUTBOX TABLE BLOAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  published_at rows never purged. Index bloat. Autovacuum
  can't keep up. Checkout INSERT outbox slows.

  Symptom: p99 checkout latency up, disk up, sequential
  scans in EXPLAIN on publisher query.

  Fix: partition DROP, emergency DELETE published rows
  older than 7 days.


FAILURE MODE 7 — POLLING PUBLISHER STAMPEDE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  100k backlog, 20 publishers, each batch 500, no jitter.
  Kafka briefly unavailable then recovers — all publishers
  fire at once → second Kafka incident.

  Fix: randomized backoff, rate limiter on produce.


FAILURE MODE 8 — DUAL PUBLISH DURING MIGRATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Polling AND Debezium both active without dedup plan.
  Consumers see 2× events. Finance reconciliation breaks.

  Fix: feature flag single publisher; dedup by event_id always.


THE CDC HEALTH DASHBOARD (Week 5 Part 14 — build this):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Per pipeline panel:
   - Connector status (running/paused/failed)
   - Slot active boolean
   - retained_wal (GB) with 10/50 GB thresholds
   - confirmed_flush_lsn lag (bytes and seconds)
   - outbox_pending_count (polling path)
   - outbox_oldest_pending_age_seconds
   - Kafka consumer group lag (downstream)
   - DLQ topic size + oldest message age
   - Schema Registry incompatible register attempts
   - Reconciliation: sample order_id count PG vs ES
```

### Failure Mode Interaction Diagram

```plaintext
                    ┌─────────────────┐
                    │ Kafka unhealthy │
                    │  (ISR shrink)   │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     Debezium stall    Polling backlog   Consumer lag
              │              │              │
              ▼              │              ▼
     Slot WAL retain        │         Read models stale
              │              │              │
              ▼              ▼              │
     PRIMARY disk ◄── outbox bloat ────────┘
              │
              ▼
     CHECKOUT DOWN (when disk full)

  The async path kills the sync path. This is why slot
  monitoring is a checkout-svc concern, not "data team."
```

---

## Decision Framework

```plaintext
DECISION FLOWCHART (outbox publish transport):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Start: Need transactional outbox?
    │
    ├─ No → fix your dual-write (you don't)
    │
    └─ Yes → Events/sec on outbox?
              │
              ├─ < 500/sec, latency SLO > 1s
              │     → POLLING (start here always)
              │
              ├─ 500–5k/sec, latency SLO < 500ms
              │     → DEBEZIUM if team owns Connect
              │     → else POLLING + scale publishers
              │
              └─ > 5k/sec or strict MSK-only AWS mandate
                    → DEBEZIUM on MSK Connect
                    → evaluate DMS if no Connect ops


DIRECT CDC ON BUSINESS TABLE?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Read model sync (ES, Redis, warehouse)? → Direct CDC ✓
  Cross-service domain choreography?       → Outbox ✓
  Both? → Both connectors, different tables, document owners


RUNBOOK: OUTBOX LAG PAGE
━━━━━━━━━━━━━━━━━━━━━━━━

  Alert: outbox_oldest_pending_age > 300s

  1. kubectl get pods -l app=outbox-publisher (or check Connect)
  2. Is Kafka healthy? UnderReplicatedPartitions == 0?
  3. kafka-producer error rate on publisher?
  4. COUNT(*) FROM outbox WHERE published_at IS NULL
  5. Sample last_error on stuck rows
  6. If Debezium: check slot retained_wal + connector status
  7. Scale publishers OR fix Kafka OR fix schema
  8. Comms: downstream staleness, NOT checkout down (yet)


RUNBOOK: SLOT BLOAT PAGE
━━━━━━━━━━━━━━━━━━━━━━

  Alert: retained_wal > 50GB on debezium_outbox_orders

  1. Is slot active? SELECT active FROM pg_replication_slots
  2. Connector RUNNING? MSK Connect console
  3. Kafka produce errors on connector?
  4. If connector dead: restart Connect worker
  5. If Kafka sick: fix ISR first (Kafka module runbook)
  6. If disk > 85%: EMERGENCY — enable polling fallback,
     consider pg_drop_replication_slot (re-snapshot after)
  7. Post-incident: verify max_slot_wal_keep_size set


SLO TEMPLATE:
━━━━━━━━━━━━━

  Outbox publish latency p99 < 2s (polling) or < 500ms (CDC)
  Outbox pending count < 1000 steady state
  Slot retained_wal < 10GB steady state
  Zero events lost (pending count recovers after incident)
  Duplicate rate at consumer: 0% effect (idempotency metric)
```

---

## SRE Diagnostic Toolkit

```bash
# Outbox pending count and oldest age
psql -c "
  SELECT COUNT(*) AS pending,
         EXTRACT(EPOCH FROM (now() - MIN(created_at))) AS oldest_age_sec
  FROM outbox WHERE published_at IS NULL;
"

# Stuck rows with errors
psql -c "
  SELECT id, event_type, publish_attempts, last_error, created_at
  FROM outbox
  WHERE published_at IS NULL AND publish_attempts > 0
  ORDER BY created_at LIMIT 20;
"

# Replication slot health (Week 5 Part 7)
psql -c "
  SELECT slot_name, active, active_pid,
         pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained,
         pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS pending
  FROM pg_replication_slots
  ORDER BY pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) DESC;
"

# Debezium JMX / Connect REST
curl -s http://connect:8083/connectors/orders-outbox-connector/status | jq

# Kafka consumer lag for downstream
kafka-consumer-groups --bootstrap-server $BS \
  --describe --group fulfillment-svc

# Check for duplicate event_id in consumer dedup table (sanity)
psql -c "SELECT event_id, COUNT(*) FROM processed_events GROUP BY 1 HAVING COUNT(*) > 1;"

# MSK Connect worker metrics (CloudWatch)
# AWS/KafkaConnect CPUUtilization, ErroredTaskCount
```

---

## Hands-On Exercises

```plaintext
EXERCISE 1 — Outbox table + polling publisher
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Setup: local Postgres + Redpanda/Kafka.
  1. Create outbox schema with partial index.
  2. Write a script that INSERTs order + outbox in one txn.
  3. Implement polling publisher with FOR UPDATE SKIP LOCKED.
  4. Kill publisher mid-batch (after produce, before UPDATE).
  5. Restart. Prove duplicate in Kafka. Implement dedup
     consumer. Prove single effect.


EXERCISE 2 — Measure publish latency
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Load test: 1000 events/sec INSERT via pgbench custom script.
  Compare p99 created_at → Kafka timestamp for:
   - poll_interval 100ms vs 1000ms
   - batch size 10 vs 100


EXERCISE 3 — Debezium outbox router (Docker)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Use debezium/example-postgres + kafka compose.
  Configure Outbox Event Router SMT.
  INSERT outbox row. Verify Kafka message shape (key, headers).
  Pause Kafka. Watch pg_wal size grow. Resume. Observe recovery.


EXERCISE 4 — Schema break drill
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Register Avro schema v1. Produce events.
  Deploy consumer. Register incompatible v2 (remove required field).
  Observe failure mode. Fix with BACKWARD-compatible v2.


EXERCISE 5 — Slot bloat simulation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Start Debezium. Stop Kafka brokers. Wait (monitored).
  Plot retained_wal. Document at what threshold you'd drop slot.
  Restart Kafka. Measure catch-up time.
```

---

## Targeted Reading

```plaintext
ESSENTIAL:
  - Chris Richardson: Microservices Patterns, Chapter on Transactional Outbox
  - Debezium documentation: Outbox Event Router SMT
  - Week 5 Database Scaling Patterns: Part 7 (slots), Part 13 (CQRS), Part 14 (CDC failures)
  - Week 6 Message Queues and Kafka: Part 8 (idempotent consumers), Part 9 (outbox), Part 12 scenario

DEEP DIVES:
  - Gunnar Morling: "Reliable Microservices Data Exchange With the Outbox Pattern"
  - Confluent: "Using Debezium to Stream Change Events to Apache Kafka"
  - AWS: DMS continuous replication docs + MSK Connect Debezium guide
  - PostgreSQL docs: Logical Replication, pgoutput plugin

POSTMORTEMS / TALKS:
  - Search "replication slot wal disk full" — read 2 real incident writeups
  - Uber / LinkedIn engineering blogs on outbox at scale (pattern variations)
```

---

## Ops Sim: Northstar Checkout Outbox Gap

**Time box:** 45 minutes
**Severity:** P1
**Service / domain:** Postgres orders, transactional outbox, Debezium, Kafka order events
**Northstar system:** Northstar Commerce

### Rules

1. Answer from memory of the Outbox Pattern and CDC teaching section; do not re-read mid-drill.
2. Write decisions in order (T+0 -> T+60).
3. Name evidence (metric, log line, trace, or config key) for every claim.
4. Do not open `answers/` until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  - Some paid orders do not appear in fulfillment queues.
  - Search and emails lag behind the OLTP order table.
  - Support tickets mention retries, stale state, or inconsistent checkout behavior.

WHAT ON-CALL SEES:
  - A code path writes orders and publishes Kafka outside the transaction.
  - Debezium restarted with an old offset.
  - A well-meaning mitigation is already making one dependency hotter.

BUSINESS CONSTRAINT:
  Preserve checkout correctness and money/inventory invariants. Degrade freshness, dashboards,
  recommendations, or noncritical notifications before risking duplicate effects.
```

### 2. Telemetry pack

```text
METRICS:
  orders_paid_total: +340k/hour
  outbox_rows_pending: 0 -> 118k
  debezium_source_lag_seconds: 5 -> 1900
  pg_replication_slot_retained_bytes: 2GB -> 146GB
  kafka_duplicate_key_rate: 0.02% -> 4.8%
  email_duplicate_sends: +12k
  fulfillment_missing_orders: 8400
  wal_disk_free_percent: 38 -> 9

LOG LINES:
  orders: inserted order without outbox row path=legacy-mobile
  debezium: restarting connector from old lsn
  publisher: sent event without idempotency key
  postgres: replication slot retained WAL

TRACES / LAG / EXPLAIN:
  critical request -> suspect dependency -> queue/retry/lag -> user-visible symptom
  compare hot slice vs fleet average before deciding to scale or fail over
```

### 3. Config pack

```yaml
require_outbox_row_in_same_txn: false
event_key: order_id
snapshot_mode: always
idempotent_producer: false
manual_republish_dedup: false
```

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | Page fires: Some paid orders do not appear in fulfillment queues. | |
| T+5 | Someone proposes: manual publish without dedup. | |
| T+15 | Evidence confirms: A legacy path skipped the transactional outbox, and CDC/replay controls converted missing events into duplicates and WAL risk. | |
| T+30 | Product asks to preserve the launch/revenue path despite risk. | |
| T+60 | New traffic is stable; old ambiguous records still need repair. | |

### 5. Questions

**Q1 - Layer & root cause:** Which layer owns the primary symptom? What is the exact mechanism?

**Q2 - Trigger vs amplifier:** What started the incident, and what made it worse after T+0?

**Q3 - Evidence:** Pick three metrics, two log lines, and one config key that prove your diagnosis.

**Q4 - Red herring:** Which fleet average, healthy check, or scary downstream metric could mislead the room?

**Q5 - First 5 minutes:** What do you announce, freeze, disable, or rate-limit immediately?

**Q6 - First 15 minutes:** Write the ordered mitigation sequence. Include rollback and verification after each step.

**Q7 - Bad fix gallery:** Reject these proposals and name the failure mode:
- manual publish without dedup
- drop replication slot without recovery plan
- trust Kafka over OLTP
- restart connector with snapshot always

**Q8 - Capacity / blast radius:** Estimate scarce resources before scaling or failover:
- queue depth or lag derivative
- connection/thread/pool headroom
- disk/WAL/compaction/ingest time-to-fill where relevant
- affected orders, users, tenants, or events requiring reconciliation

**Q9 - Correctness invariant:** What must remain true even while experience degrades?

**Q10 - Data repair:** Which source of truth defines the affected set? How do you replay without duplicate side effects?

**Q11 - Durable fix:** Propose architecture/config changes and acceptance criteria for:
- enforce outbox row in same transaction
- idempotent event keys
- slot lag pages
- throttled backfill/replay runbook

**Q12 - Alerting:** Which symptom alert should have paged earlier? Which noisy alert should be demoted?

**Q13 - Org / runbook:** Who joins by T+10, what is pre-authorized, and what needs senior approval?

### 6. Self-score (after answer key)

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Knowledge gap | | |
| Misread / wrong layer | | |
| Sequencing error | | |
| Capacity miss | | |
| Consistency/invariant miss | | |
| Org/runbook miss | | |

**Answer key:** [../answers/Week-06-Architecture-Patterns/Outbox Pattern and CDC Answers.md](../answers/Week-06-Architecture-Patterns/Outbox%20Pattern%20and%20CDC%20Answers.md)

---
## Key Takeaways

```
╔════════════════════════════════════════════════════════════════╗
║   MEMORIZE THESE FOR INTERVIEWS AND 2 AM PAGES:                ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Outbox = atomic DB write + async publish. Not CDC.        ║
║      CDC on outbox table is a transport choice.                ║
║                                                                ║
║   2. Dual-write (DB then Kafka) is always wrong in prod.       ║
║                                                                ║
║   3. At-least-once everywhere. Idempotent consumers are        ║
║      the contract. event_id = outbox.id.                       ║
║                                                                ║
║   4. key = aggregate_id for ordering. Dedup by event_id.       ║
║                                                                ║
║   5. Polling is valid at scale. Debezium buys latency          ║
║      with slot operational tax.                                ║
║                                                                ║
║   6. Slot bloat connects async failure to primary disk.        ║
║      Monitor retained_wal. Set max_slot_wal_keep_size.         ║
║                                                                ║
║   7. Direct CDC on business tables = CQRS. Outbox =            ║
║      domain events. Many systems need both.                    ║
║                                                                ║
║   8. Schema evolution: expand → migrate → contract.            ║
║      Registry in CI. Incompatible change = slot bloat          ║
║      cascade.                                                  ║
╚════════════════════════════════════════════════════════════════╝
```

---

# 🔥 SRE SCENARIO — Outbox Pattern & CDC

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1 → P2 (cascading)
Service: orders-platform (checkout + async fulfillment)
Time: Tuesday 13:45–14:45 UTC

ARCHITECTURE:
  Users → checkout-svc → PostgreSQL orders DB (primary)
  Outbox table: public.outbox (~2k inserts/sec peak)
  Publish path: Debezium on MSK Connect → orders.outbox topic
  Slot: debezium_outbox_orders on primary
  Consumers: fulfillment-svc (8 pods), search-indexer (16 pods)

  Business context: same day as Kafka "Tuesday Afternoon Black Hole"
  (Message Queues and Kafka, Part 12). click.stream incident
  saturated shared MSK brokers. This scenario is the OUTBOX/CDC
  chapter of that cascade.

INCIDENT TIMELINE (abbreviated — see Kafka module for broker detail):

  13:55:15  ISR shrinkage on orders.events AND orders.outbox
            partitions (brokers b1, b5, b9 request queue saturated).

  13:56:30  checkout-svc 5xx on ~9% of orders (acks=all, min ISR).

  13:57:00  Debezium connector orders-outbox-pub: produce failures
            NotEnoughReplicasException on orders.outbox topic.
            confirmed_flush_lsn STOPS on slot debezium_outbox_orders.

  13:58:00  pg_wal on orders primary: 42GB → 48GB (climbing ~2GB/10min).
            outbox pending: published_at NULL rows NOT growing
            (Debezium path doesn't set published_at — rows stay).
            Downstream: fulfillment lag 0 → 45k messages in 12 min.

  14:02:00  DBA page: "orders DB disk 78%, growth anomaly pg_wal".
            On-call data engineer focused on Kafka ISR — slot not
            yet on their dashboard.

  14:08:00  Disk 83%. retained_wal 38GB on debezium_outbox_orders.
            Slot active=true but flush frozen. Connector status RUNNING.

  14:12:00  First customer report: "order confirmed but tracking
            never appeared" (fulfillment consumer lag).

  14:15:00  YOU join bridge. Kafka ISR recovering from click.stream
            fix. Debezium still failing intermittently on
            orders.outbox produce. WAL 52GB.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** Draw the failure chain from click.stream misconfiguration to a customer not receiving tracking info. Which components are symptom vs root cause? Where does outbox pattern succeed vs fail in this cascade?

**Question 2:** It is 14:15 UTC. Disk at 83%, projected full at 15:30 UTC. Kafka ISR mostly recovered. Debezium connector flapping. Give exact actions in priority order for the next 30 minutes — include when you would drop the replication slot, when you would start a polling publisher fallback, and what you tell customer support.

**Question 3:** After stabilization at 15:00 UTC, how do you prove no duplicate fulfillments were created? What queries and metrics? How does event_id dedup interact with fulfillment-svc's state machine?

**Question 4:** Design the monitoring that would have paged at 13:58 (slot growth) instead of 14:08 (disk). Give specific PromQL/CloudWatch/SQL thresholds and who owns the alert (checkout team vs data platform).

**Question 5:** Long-term: would you keep Debezium on outbox, switch to polling, or run hybrid? Factor in Tuesday's cascade, team size (4 backend, 1 data engineer), and 2k events/sec peak.

---

> **Answer key (do not open until you attempt the Ops Sim / questions):**
> [`../answers/Week-06-Architecture-Patterns/Outbox Pattern and CDC Answers.md`](../answers/Week-06-Architecture-Patterns/Outbox%20Pattern%20and%20CDC%20Answers.md)

