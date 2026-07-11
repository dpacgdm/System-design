# Week 6, Topic 2 — Event-Driven Architecture

> You know how messages move (Kafka module). You know how read models diverge and reconverge (CQRS, Week 5). You know what consistency you can promise (Week 3). This module connects those pieces into a coherent architecture: how systems *react* to each other without becoming a distributed ball of mud.

Same teaching contract as every module in this curriculum: every section answers *what do I design, what do I run, what breaks at 2 AM, and what question separates a passing answer from a principal one.*

**Prerequisites:** Message Queues and Kafka (Week 6, Topic 1), Consistency Models (Week 3), Database Scaling Patterns / CQRS (Week 5).

---

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Distinguish event notification from event-carried         ║
║      state transfer — and choose the right shape for a         ║
║      given coupling budget                                     ║
║                                                                ║
║   2. Design choreography and orchestration flows for           ║
║      multi-step business processes (orders, payments,          ║
║      fulfillment) with explicit failure and compensation       ║
║      semantics                                                 ║
║                                                                ║
║   3. Reason about delivery guarantees, ordering,               ║
║      idempotency, and schema evolution as a single             ║
║      design contract — not independent checkboxes              ║
║                                                                ║
║   4. Map AWS event primitives (EventBridge, SQS, SNS,          ║
║      Kinesis, MSK) to architectural roles and avoid            ║
║      the "everything goes through EventBridge" trap            ║
║                                                                ║
║   5. Diagnose production EDA incidents: duplicate              ║
║      charges, phantom orders, stuck sagas, DLQ floods,         ║
║      schema breakages, and backpressure cascades               ║
║                                                                ║
║   6. Articulate why "exactly-once" is an illusion at           ║
║      the system level and what "effectively-once"              ║
║      actually requires in code                                 ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Events decouple everything"                    ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Events decouple *timing* and *availability*, not          ║
║   *semantics*. If Service B must react correctly to Service A's    ║
║   event, they still share a contract. Break the contract and       ║
║   you break the system — you just find out asynchronously.         ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Exactly-once delivery solves duplicates"       ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Broker "exactly-once" (Kafka transactions, Kinesis        ║
║   Enhanced Fan-Out with checkpoints) covers a narrow slice:        ║
║   write-to-log + read-from-log within one pipeline. Your           ║
║   payment charge, inventory decrement, and email send each         ║
║   happen in different systems. Duplicates are inevitable.          ║
║   Idempotent consumers are not optional — they are the design.     ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Choreography is always better than             ║
║   orchestration"                                                   ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Choreography scales team autonomy; orchestration          ║
║   scales *visibility* and *compensation*. A 7-step order flow      ║
║   with money movement needs a coordinator (or a saga log you       ║
║   can query). Pure choreography across 6 services is a             ║
║   distributed debugger's nightmare.                                ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Fat events are always better"                  ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Event-carried state transfer (ECST) reduces chattiness    ║
║   but couples consumers to producer schemas, bloats the log,       ║
║   and leaks PII into every subscriber. Thin events + API/DB        ║
║   lookup trade latency for autonomy. The choice is a coupling      ║
║   budget decision, not a purity contest.                           ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "EventBridge is our enterprise service bus"     ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. EventBridge is a routing and integration layer —          ║
║   excellent for cross-account fan-out, SaaS webhooks, and          ║
║   operational events. It is NOT a high-throughput order            ║
║   backbone (default 10,000 events/sec/account, soft limits).       ║
║   Putting your checkout critical path through EventBridge          ║
║   without capacity planning is how Black Friday becomes a          ║
║   postmortem.                                                      ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Ordering doesn't matter if we're               ║
║   eventually consistent"                                           ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Eventual consistency has a *convergence* guarantee,       ║
║   not an "any order is fine" guarantee. OrderCreated before        ║
║   OrderPaid is a state machine. OrderPaid before OrderCreated      ║
║   is a bug that eventual consistency will never fix — it           ║
║   will faithfully converge to the wrong state.                     ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

### What Event-Driven Architecture Actually Is

```
EVENT-DRIVEN ARCHITECTURE (EDA):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  A style where components communicate by publishing and
  subscribing to EVENTS — immutable records of something
  that already happened in the past tense.

  "OrderPlaced" not "PlaceOrder"
  "PaymentCaptured" not "CapturePayment"

  The past-tense naming is not pedantry. It encodes a
  semantic commitment: the event describes a fact. The
  producer has already committed its local truth. Consumers
  react; they do not instruct.


THE THREE LAYERS (don't conflate them):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ╔════════════════════════════════════════════════════════════════╗
  ║  LAYER 1: TRANSPORT                                            ║
  ║  How bits move: Kafka, SQS, SNS, Kinesis, EventBridge, HTTP    ║
  ║  → Covered in depth: Message Queues and Kafka (Week 6 T1)      ║
  ╠════════════════════════════════════════════════════════════════╣
  ║  LAYER 2: EVENT PATTERN                                        ║
  ║  What the message means: notification vs state transfer,       ║
  ║  event sourcing vs event streaming, command vs event           ║
  ║  → THIS MODULE                                                 ║
  ╠════════════════════════════════════════════════════════════════╣
  ║  LAYER 3: CONSISTENCY & COORDINATION                           ║
  ║  How the system stays correct: sagas, outbox, idempotency,     ║
  ║  read models, compensation                                     ║
  ║  → Week 3 (consistency), Week 5 (CQRS), Week 6 T3-T5 (saga,    ║
  ║    outbox — upcoming modules)                                  ║
  ╚════════════════════════════════════════════════════════════════╝


WHY TEAMS ADOPT EDA:
━━━━━━━━━━━━━━━━━━

  ✓ Temporal decoupling — producer doesn't wait for consumers
  ✓ Load leveling — spikes absorbed by the log/queue
  ✓ Multi-subscriber fan-out — one event, N independent reactions
  ✓ Extensibility — add a consumer without changing the producer
  ✓ Audit trail — the log is a replayable history

  ✗ Distributed debugging — causality is implicit
  ✗ Contract governance — schema drift breaks silent consumers
  ✗ End-to-end latency — async means delay
  ✗ Testing complexity — integration tests need the bus
  ✗ Operational surface — DLQs, lag, poison messages, rebalance
```

### Event Notification vs Event-Carried State Transfer

```
THE FUNDAMENTAL FORK:
━━━━━━━━━━━━━━━━━━━━

  Every event design answers one question:

  "How much does the consumer need to know WITHOUT calling back?"


EVENT NOTIFICATION (thin event):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Carries: identity + type + minimal metadata
  Consumer must: fetch full state elsewhere

  Example:
  {
    "eventType": "OrderPlaced",
    "eventId": "evt_8f3a2b1c",
    "orderId": "ord_9912",
    "timestamp": "2026-07-06T14:22:01Z",
    "schemaVersion": 2
  }

  Fulfillment service receives this → calls Order API:
    GET /orders/ord_9912 → full order payload

  ╔═══════════════╗     thin event      ╔═══════════════╗
  ║ Order Service ║ ──────────────────► ║  Fulfillment  ║
  ║  (producer)   ║                     ║  (consumer)   ║
  ╚═══════════════╝                     ╚═══════╤═══════╝
        ▲                                       │
        │         GET /orders/{id}              │
        └───────────────────────────────────────┘

  PROS:
   - Small messages → cheap log, fast fan-out
   - Producer schema can evolve; consumer always gets latest
     via API (if API is versioned)
   - PII stays in the source system (access-controlled)
   - Single source of truth remains the Order DB

  CONS:
   - Extra round-trip → higher latency, coupling to API
     availability at consume time
   - Thundering herd on hot entities (10K consumers all
     fetch the same order)
   - API downtime = consumer cannot progress even though
     the event was delivered
   - Ordering + staleness: event says "placed" but API
     returns "cancelled" if consumer is slow


EVENT-CARRIED STATE TRANSFER (ECST, fat event):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Carries: everything the consumer needs to act
  Consumer: never calls back (in the happy path)

  Example:
  {
    "eventType": "OrderPlaced",
    "eventId": "evt_8f3a2b1c",
    "schemaVersion": 2,
    "order": {
      "orderId": "ord_9912",
      "customerId": "cus_441",
      "lines": [
        {"sku": "WIDGET-7", "qty": 2, "unitPrice": 29.99}
      ],
      "shippingAddress": { ... },
      "paymentMethod": "card",
      "totalCents": 5998
    }
  }

  Fulfillment service receives this → picks, packs, ships.
  No callback to Order service required.

  ╔═══════════════╗     fat event       ╔═══════════════╗
  ║ Order Service ║ ──────────────────► ║  Fulfillment  ║
  ║  (producer)   ║   (complete state)  ║  (consumer)   ║
  ╚═══════════════╝                     ╚═══════════════╝

  PROS:
   - Consumer fully autonomous — works during Order API outage
   - Lower end-to-end latency (no callback)
   - Natural fit for CQRS read models (Week 5): the event
     IS the write to the projection
   - Replayable: consumer can rebuild state from the log alone

  CONS:
   - Large messages → log cost, bandwidth, serialization CPU
   - Schema coupling: producer field rename breaks 6 consumers
   - PII in the log → compliance surface expands to every
     subscriber, every retention policy, every replay
   - Stale embedded state: if order is amended after publish,
     consumers have divergent snapshots unless you version


THE HYBRID (what production usually does):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  "Medium events" — enough to act, with a version + checksum,
  and a callback path for edge cases.

  {
    "eventType": "OrderPlaced",
    "orderId": "ord_9912",
    "customerId": "cus_441",
    "lines": [ ... ],           // act on this
    "stateVersion": 4,          // optimistic concurrency
    "snapshotHash": "a3f9...",  // detect drift
    "detailUrl": "/orders/ord_9912"  // fallback fetch
  }

  Consumer:
   1. Try to process from embedded state
   2. If stateVersion mismatch or business rule needs more
      → fetch detailUrl
   3. If fetch fails → retry with backoff (event is durable)


DECISION HEURISTIC:
━━━━━━━━━━━━━━━━━━

  ┌────────────────────────────┬─────────────────────────────────┐
  │ Favor NOTIFICATION (thin)  │ Favor ECST (fat)                │
  ├────────────────────────────┼─────────────────────────────────┤
  │ Payload > 64 KB            │ Payload small, stable shape     │
  │ PII / regulated data       │ Public catalog data             │
  │ Many consumers, diverse    │ Consumer builds read model      │
  │   needs (each wants diff)  │   (CQRS projection)             │
  │ Source is system of record │ Autonomy > coupling (warehouse  │
  │   and API is stable        │   fulfillment during outage)    │
  │ Low fan-out (1-2 subs)     │ High fan-out, same shape needed │
  └────────────────────────────┴─────────────────────────────────┘
```

### Choreography vs Orchestration

```
MULTI-STEP BUSINESS PROCESSES IN EDA:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Order → Payment → Inventory → Fulfillment → Notification

  Two coordination styles. Both are valid. Both have failure modes.


CHOREOGRAPHY (no central conductor):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Each service listens for events it cares about and publishes
  events when its work is done. The workflow emerges from
  local rules.

  ╔═══════════╗  OrderPlaced   ╔═══════════╗  PaymentAuth  ╔═══════════╗
  ║   Order   ║ ─────────────► ║ Inventory ║ ─────────────► ║  Payment  ║
  ║  Service  ║                ║  Service  ║                ║  Service  ║
  ╚═══════════╝                ╚═══════════╝                ╚═════╤═════╝
       ▲                              ▲                            │
       │                              │         PaymentCaptured      │
       │         OrderCancelled       │         InventoryReserved    │
       └──────────────────────────────┴────────────────────────────┘
                                          │
                                          ▼
                                   ╔═══════════╗
                                   ║Fulfillment║
                                   ║  Service  ║
                                   ╚═══════════╝

  Each box knows ONLY:
   - What events trigger me
   - What events I emit when done
   - What events trigger compensation

  PROS:
   - Team autonomy — no shared orchestration codebase
   - No single point of failure (no orchestrator to kill)
   - Add a step by adding a subscriber (open/closed)

  CONS:
   - Implicit workflow — you cannot "grep the saga"
   - Cyclic dependencies if designed carelessly
   - Debugging: "why is order 9912 stuck?" requires tracing
     across 5 services' logs
   - Compensation scattered — each service knows its undo,
     nobody sees the whole rollback
   - Version skew: Service C expects PaymentCaptured v3
     but Service B still emits v2


ORCHESTRATION (central coordinator):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  A workflow engine (or dedicated orchestrator service) tells
  each participant what to do and tracks state.

  ╔═══════════════════════════════════════════════════════════════╗
  ║                    ORDER SAGA ORCHESTRATOR                    ║
  ║  state: { orderId, step: "awaiting_payment", attempts: 1 }    ║
  ╚═══════════════════════════════════════════════════════════════╝
       │ reserve          │ charge           │ ship
       ▼                  ▼                  ▼
  ╔═══════════╗     ╔═══════════╗     ╔═══════════╗
  ║ Inventory ║     ║  Payment  ║     ║Fulfillment║
  ╚═══════════╝     ║  Service  ║     ╚═══════════╝
                    ╚═══════════╝

  Orchestrator:
   1. Receives StartOrderSaga command
   2. Calls Inventory.reserve() → on success, calls Payment.charge()
   3. On PaymentCaptured → calls Fulfillment.createShipment()
   4. On any failure → runs compensation chain in reverse

  AWS implementations:
   - Step Functions (visual state machine, built-in retry/catch)
   - Temporal / Cadence (code-as-workflow, durable execution)
   - Custom saga table + SQS command queues per service

  PROS:
   - Explicit state machine — one place to answer "where is
     order 9912?"
   - Centralized timeout and retry policy
   - Compensation logic in one module (the saga definition)
   - Easier compliance audit: export the state machine

  CONS:
   - Orchestrator is a coupling point and SPoF (mitigate with HA)
   - Temptation to put business logic in the orchestrator
     (keep it thin — route and track, don't compute)
   - Scaling the orchestrator itself under burst traffic
   - Team bottleneck if every new step requires orchestrator PR


CHOREOGRAPHY-ORCHESTRATION SPECTRUM:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Pure choreography ◄────────────────────────────► Pure orchestration

  Event reactions     Saga log + commands        Step Functions
  (microservices      (orchestrated choreography) (central SM)
   listening)              ▲
                           │
                    SWEET SPOT for most e-commerce:
                    Choreography for non-critical paths
                    (analytics, email, recommendations)
                    Orchestration for money + inventory
                    (payment, reserve, ship)


  RULE OF THUMB:
   - ≤ 3 steps, no compensation → choreography is fine
   - Money movement or inventory → orchestration or formal saga
   - > 5 services involved → you need a queryable saga state
     store regardless of style
```

### The Consistency Contract (Connecting Week 3)

```
EDA INHERITS CONSISTENCY MODELS — IT DOES NOT ESCAPE THEM:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Week 3 taught: linearizability, causal, read-your-writes,
  eventual. In EDA, the DEFAULT is eventual consistency
  between services. That is not a bug — it is the trade you
  made for decoupling.

  THE KEY QUESTION PER BOUNDARY:
  "What is the worst anomaly if Service B acts on stale
   information from an event?"

  ╔═══════════════════════════════════════════════════════════════╗
  ║  BOUNDARY                    │ MINIMUM CONSISTENCY NEED       ║
  ╠═══════════════════════════════════════════════════════════════╣
  ║  Order → Analytics           │ Eventual (hours stale OK)      ║
  ║  Order → Search index (CQRS) │ Eventual (seconds stale OK)    ║
  ║  Order → Inventory reserve   │ Causal / read-your-writes      ║
  ║  Payment → Ledger            │ Linearizable per account       ║
  ║  Order status → Customer UI  │ Read-your-writes (sticky)      ║
  ╚═══════════════════════════════════════════════════════════════╝

  ENFORCEMENT MECHANISMS IN EDA:

  1. PARTITION KEY ORDERING (per-entity sequence)
     All events for order_id=9912 land in order → consumer
     processes in sequence → no PaymentCaptured before
     OrderPlaced within that partition.

  2. VERSION / SEQUENCE NUMBER (optimistic concurrency)
     Event carries stateVersion: 4. Consumer writes only if
     current version < 4. Stale event rejected idempotently.

  3. CAUSAL METADATA (trace_id, parent_event_id)
     Consumer drops events whose parent hasn't been processed.

  4. READ-YOUR-WRITES VIA ROUTING
     After POST /orders, API returns orderId. UI polls
     GET /orders/{id} on the writer (or uses WebSocket fed
     by the same service that wrote). Do NOT expect the
     search-index read model to show the order instantly.

  5. SAGA COMPENSATION (logical consistency)
     When Payment fails after Inventory reserved, emit
     InventoryReleased — the system converges to "no sale"
     rather than "reserved forever."
```

### Idempotency — The Real Exactly-Once

```
WHY DUPLICATES HAPPEN (inevitable, not exceptional):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  - Producer retries (network timeout, broker nack)
  - Consumer processes, crashes before ack → redelivery
  - At-least-once broker guarantee (SQS, Kafka default)
  - Rebalance replay (consumer reassigned, reprocesses batch)
  - Operator replays DLQ during incident recovery
  - CDC duplicate events during connector restart

  "Exactly-once" at the broker layer (Kafka transactions,
  Kinesis checkpoint + idempotent producer) shrinks the
  window. It does NOT cover:
   - Your charge() HTTP call to Stripe
   - Your INSERT into Postgres
   - Your email send via SES

  EFFECTIVELY-ONCE = AT-LEAST-ONCE DELIVERY + IDEMPOTENT HANDLER


THE IDEMPOTENCY KEY PATTERN:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Every event carries a unique, stable eventId (or dedupe key).
  Consumer maintains a processed_events table (or Redis SET
  with TTL):

  CREATE TABLE processed_events (
    event_id     TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ DEFAULT now(),
    result_hash  TEXT  -- optional: return cached result
  );

  Handler:
    BEGIN;
    INSERT INTO processed_events (event_id) VALUES ($1)
      ON CONFLICT DO NOTHING
      RETURNING event_id;
    -- if 0 rows inserted → already processed → COMMIT and return
  -- do the actual work
    COMMIT;

  PROPERTIES:
   - eventId must be assigned by PRODUCER, stable across retries
   - Use UUIDv7 or ULID (time-sortable) for operability
   - TTL cleanup: keep 7-30 days, or forever if storage is cheap
   - For external APIs: pass idempotency-key header (Stripe,
     PayPal, AWS APIs all support this)


IDEMPOTENCY VS DEDUPLICATION VS TRANSACTIONAL OUTBOX:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────┬────────────────────────────────────────┐
  │ Pattern            │ What it prevents                       │
  ├────────────────────┼────────────────────────────────────────┤
  │ Idempotent consumer│ Duplicate processing side effects      │
  │ Broker dedup       │ Duplicate messages in the log          │
  │   (SQS FIFO 5min,  │   (limited window)                     │
  │    Kafka idempotent│                                        │
  │    producer)       │                                        │
  │ Outbox pattern     │ "DB committed but event never sent"    │
  │   (Week 6 T5)      │   and its inverse                      │
  └────────────────────┴────────────────────────────────────────┘

  You need all three layers for money paths. One alone is insufficient.
```

### Ordering Guarantees

```
ORDERING IS ALWAYS SCOPED — NEVER GLOBAL:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  "Kafka guarantees order" → within a partition.
  "SQS FIFO guarantees order" → within a message group.
  "Kinesis guarantees order" → within a shard.

  Cross-partition / cross-shard / cross-group: NO ORDER.


MAPPING ENTITY → ORDERING KEY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────┬────────────────────┬─────────────────────┐
  │ Business need    │ Ordering key       │ AWS mapping         │
  ├──────────────────┼────────────────────┼─────────────────────┤
  │ Per-order events │ order_id           │ Kafka key / Kinesis │
  │                  │                    │ partition key /     │
  │                  │                    │ SQS FIFO GroupId    │
  ├──────────────────┼────────────────────┼─────────────────────┤
  │ Per-customer     │ customer_id        │ Same                │
  │ ledger entries   │                    │                     │
  ├──────────────────┼────────────────────┼─────────────────────┤
  │ Per-device IoT   │ device_id          │ Kinesis shard key   │
  ├──────────────────┼────────────────────┼─────────────────────┤
  │ Global metrics   │ none (accept       │ Round-robin, no     │
  │                  │ disorder)          │ ordering            │
  └──────────────────┴────────────────────┴─────────────────────┘


ORDERING FAILURE MODES:
━━━━━━━━━━━━━━━━━━━━━━

  1. WRONG KEY
     Key=user_id but you need per-order order → two orders
     for same user interleave → InventoryReleased might
     process before InventoryReserved.

  2. HOT KEY
     All events key=tenant_id for your largest customer →
     one partition/shard at 100%, others idle. Ordering
     is "preserved" into a throughput wall.

  3. REPARTITIONING
     You increase Kafka partitions from 16 → 32 → hash(key)%N
     changes → ordering broken for in-flight keys. Never
     repartition without a migration plan.

  4. PARALLEL CONSUMER THREADS
     One consumer, 8 threads, same partition → you destroyed
     ordering yourself. Fix: one thread per partition, or
     per-key serial executor within the consumer.

  5. CROSS-TOPIC ORDERING
     OrderPlaced on topic-A, PaymentCaptured on topic-B →
     NO broker guarantee on relative order. Fix: same topic
     with keyed events, or saga orchestrator, or causal
     parent_event_id checking.


SQS FIFO NUANCE:
━━━━━━━━━━━━━━━

  - MessageGroupId = ordering scope (e.g., order_id)
  - Different groups process in parallel
  - Same group: strict FIFO, 300 TPS per group (soft),
    3000 TPS per queue with batching
  - ContentBasedDeduplication OR explicit DeduplicationId
    (5-minute dedup window)
  - FIFO throughput ceiling is real — don't put your entire
    Black Friday stream through one MessageGroupId
```

### Schema Evolution and Event Versioning

```
EVENTS ARE A PUBLIC API — VERSION THEM:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Schema drift is the #1 silent killer of EDA systems.
  A producer adds a field, renames a field, changes a type,
  and three consumers in other teams break on the next deploy.


COMPATIBILITY MODES (Avro / Protobuf / JSON Schema):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  BACKWARD compatible (new schema reads old data):
   - Consumers upgraded FIRST, then producers
   - Safe: add optional fields with defaults
   - Unsafe: remove required fields, change types

  FORWARD compatible (old schema reads new data):
   - Producers upgraded FIRST, then consumers
   - Safe: add fields old consumers ignore
   - Unsafe: remove fields old consumers still read

  FULL compatible: both directions — the gold standard
   - Only add optional fields with defaults
   - Never remove or rename (deprecate, stop emitting)

  AWS Glue Schema Registry / Confluent Schema Registry:
   - Enforces compatibility mode on registration
   - Rejects breaking schemas at CI time
   - MSK integrates with Glue; self-hosted Kafka with Confluent


EVENT VERSIONING STRATEGIES:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  STRATEGY 1: schemaVersion in payload (most common)
  {
    "schemaVersion": 3,
    "eventType": "OrderPlaced",
    ...
  }
  Consumer switch(version) { case 3: ... case 2: ... default: DLQ }

  STRATEGY 2: topic-per-version (heavy, explicit)
  orders.placed.v1, orders.placed.v2
  Run dual consumers during migration; retire v1 when lag = 0.

  STRATEGY 3: eventType versioning
  OrderPlacedV1, OrderPlacedV2 — ugly but grep-friendly.

  STRATEGY 4: upcasting (event sourcing)
  Store v1 events forever; on read, upcast v1→v2→v3 in memory.
  Projections always see latest shape.


THE RENAME TRAP:
━━━━━━━━━━━━━━━

  NEVER rename a field in-place. Old events in the log still
  have the old name forever (retention = years).

  Correct:
   - Add newField, emit both during transition
   - Consumers read newField ?? oldField
   - Stop emitting oldField after N weeks
   - (Optional) compaction job for ancient events — expensive


UPCOMING TOPIC LINK:
  Outbox + CDC (Week 6, Topic 5) — schema changes in the
  outbox table propagate through Debezium. A column type
  change can stall the replication slot. Coordinate with
  the Kafka module's Part 10 (Schema Management).
```

### Dead Letter Queues

```
DLQ = THE SAFETY VALVE THAT BECOMES A GARBAGE DUMP:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  When a consumer fails N times, the message moves to a
  Dead Letter Queue instead of blocking the queue forever.

  ╔═══════════════╗   fail × N   ╔═══════════════╗
  ║  Main Queue   ║ ───────────► ║     DLQ       ║
  ║  (SQS / sub)  ║              ║  (inspection) ║
  ╚═══════════════╝              ╚═══════════════╝

  AWS defaults:
   - SQS redrive policy: maxReceiveCount (typically 3-5)
   - Lambda: async invoke DLQ or on-failure destination
   - Kinesis: iterator age grows; failed records need
     custom DLQ pattern (write to SQS on poison)
   - MSK/Kafka: no native DLQ → you build it (produce to
     orders.dlq topic on handler failure)


DLQ OPERATIONAL RULES:
━━━━━━━━━━━━━━━━━━━━━

  1. ALERT on DLQ depth > 0 (not > 1000)
     A single message in DLQ is a bug. Page on first arrival.

  2. NEVER auto-replay without understanding root cause
     Replaying poison messages → infinite loop → DLQ fills
     again in 60 seconds.

  3. CLASSIFY before replay
     - Transient (downstream timeout) → safe to replay
     - Schema mismatch → fix consumer, then replay
     - Bad data (null orderId) → quarantine, fix producer
     - Duplicate of already-processed → discard

  4. DLQ MESSAGE MUST CARRY CONTEXT
     Original payload + error + stack + receive count +
     first failure timestamp + consumer version

  5. REPLAY TOOLING IS PRODUCTION INFRASTRUCTURE
     aws sqs start-message-move-task (SQS DLQ redrive)
     Custom script: read DLQ → validate → publish to main
     with new eventId + parent_event_id = original


DLQ ANTI-PATTERN: SILENT DLQ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Team sets maxReceiveCount=5, DLQ exists, nobody monitors it.
  Six months later: 400K messages, compliance audit finds
  missing fulfillment records. This is a P1 data-loss incident
  disguised as a configuration success.
```

### Backpressure

```
BACKPRESSURE = HOW A SLOW CONSUMER PROTECTS (OR DESTROYS) THE SYSTEM:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  In synchronous systems, TCP backpressure is automatic.
  In EDA, the log/queue ABSORBS pressure until it doesn't.

  ╔═══════════════╗                ╔═══════════════╗
  ║   Producers   ║ ── spike ────► ║  Log / Queue  ║
  ║  (unchanged)  ║                ║  (grows)      ║
  ╚═══════════════╝                ╚═══════╤═══════╝
                                           │
                                     lag ↑ │
                                           ▼
                                   ╔═══════════════╗
                                   ║ Slow Consumer ║
                                   ║ (can't keep   ║
                                   ║  up)          ║
                                   ╚═══════════════╝


BACKPRESSURE SIGNALS BY SERVICE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Kafka/MSK:     consumer lag (records behind head)
  Kinesis:       GetRecords.IteratorAgeMilliseconds
  SQS:           ApproximateAgeOfOldestMessage
  EventBridge:   FailedInvocations, ThrottledRules
  Lambda:        ConcurrentExecutions pegged, throttles


PROPAGATION MODES (what happens when consumer is slow):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. BUFFER (default)
     Queue grows. Lag increases. Eventually: disk full
     (Kafka), retention expires (data loss), or SQS
     14-day retention. Producers unaffected until
     broker limits hit.

  2. THROTTLE
     Broker rejects or slows producers. Kafka quotas,
     Kinesis ProvisionedThroughputExceeded, EventBridge
     throttling. Producers see errors — must retry or drop.

  3. SHED LOAD
     Producer explicitly drops (sample analytics events),
     routes to lower-priority queue, or rejects user requests
     ("try again later"). Honest backpressure to the user.

  4. SCALE OUT
     Add consumers — works until partition/shard count
     ceiling (Kafka: consumers ≤ partitions). Beyond that,
     only add partitions (with ordering caveats) or
     optimize handler.


DESIGN FOR BACKPRESSURE:
━━━━━━━━━━━━━━━━━━━━━━

  - Separate critical (orders) from analytics (clicks) topics
    — Week 6 Kafka module's isolation lesson
  - Set retention consciously: 7-day click stream vs
    infinite order events
  - Autoscale consumers on lag (MSK on ECS/EKS, Kinesis
    Enhanced Fan-Out + auto-scaling)
  - Circuit breakers on downstream calls inside handlers
    (upcoming Week 6 T4 module)
  - max.poll.interval.ms / visibility timeout must exceed
    p99 handler time — or messages reappear mid-process
```

### The Exactly-Once Illusion

```
WHAT VENDORS MEAN BY "EXACTLY-ONCE":
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────┬────────────────────────────────────────┐
  │ System             │ What "exactly-once" actually covers    │
  ├────────────────────┼────────────────────────────────────────┤
  │ Kafka transactions │ Atomic: write to multiple partitions   │
  │                    │ + consume offset commit. Within one    │
  │                    │ transactional producer session.        │
  ├────────────────────┼────────────────────────────────────────┤
  │ Kafka idempotent   │ Broker deduplicates producer retries   │
  │ producer           │ (single partition, PID+sequence).      │
  ├────────────────────┼────────────────────────────────────────┤
  │ Kinesis            │ Checkpoint + at-least-once + your      │
  │                    │ idempotent handler = effectively-once  │
  ├────────────────────┼────────────────────────────────────────┤
  │ SQS FIFO           │ Exactly-once processing (AWS claim)    │
  │                    │ within 5-min dedup window, one consumer│
  │                    │ per group at a time.                   │
  ├────────────────────┼────────────────────────────────────────┤
  │ Lambda + SQS       │ Deletes on success; retry on fail.     │
  │                    │ Concurrent retries can duplicate.      │
  └────────────────────┴────────────────────────────────────────┘

  NONE of these cover:
   - Charge card + write DB as one atomic operation
   - Send email exactly once across SES retry
   - Update 3 microservices in one transaction

  THE END-TO-END IMPOSSIBILITY (classic result):
   Exactly-once delivery between independent systems
   requires a shared transaction coordinator or idempotent
   design. There is no middleware fairy dust.


WHAT TO SAY IN AN INTERVIEW:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  "We use at-least-once delivery with idempotent consumers.
   For the payment boundary, we use Stripe idempotency keys
   backed by a processed_events table with the eventId.
   We accept that the log may contain duplicates; we
   guarantee that side effects happen at most once.
   We monitor for DLQ depth and consumer lag as leading
   indicators. We do NOT claim end-to-end exactly-once."
```

### AWS Event Primitives — Architectural Roles

```
THE AWS EVENT LANDSCAPE (what each thing is FOR):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ╔════════════════════════════════════════════════════════════════╗
  ║  SNS — FAN-OUT NOTIFICATION                                    ║
  ║  Push to many subscribers (SQS, Lambda, HTTP, email).          ║
  ║  No persistence (retry to subs, then drop).                    ║
  ║  No ordering (FIFO topic exists, 300 TPS/group limit).         ║
  ║  USE: "tell everyone something happened"                       ║
  ╠════════════════════════════════════════════════════════════════╣
  ║  SQS — WORK QUEUE                                              ║
  ║  Pull, ack, delete. Standard (unordered, unlimited TPS)        ║
  ║  or FIFO (ordered per group, 3K TPS). DLQ built-in.            ║
  ║  USE: "exactly one worker processes this job"                  ║
  ╠════════════════════════════════════════════════════════════════╣
  ║  EVENTBRIDGE — EVENT ROUTING BUS                               ║
  ║  Schema registry, content-based rules, cross-account.          ║
  ║  Archive + replay (retention). SaaS integrations.              ║
  ║  USE: "route events to targets based on pattern"               ║
  ╠════════════════════════════════════════════════════════════════╣
  ║  KINESIS DATA STREAMS — MANAGED SHARDED LOG                    ║
  ║  Ordered per shard, retention 1-365 days, replay.              ║
  ║  Enhanced Fan-Out for dedicated throughput per consumer.       ║
  ║  USE: "high-volume stream, multiple consumers, AWS-native"     ║
  ╠════════════════════════════════════════════════════════════════╣
  ║  MSK — MANAGED KAFKA                                           ║
  ║  Full Kafka API, partitions, consumer groups, transactions.    ║
  ║  USE: "Kafka ecosystem, Connect, Streams, cross-cloud"         ║
  ╚════════════════════════════════════════════════════════════════╝


REFERENCE ARCHITECTURE (e-commerce, AWS-native):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ╔═══════════════╗
  ║ Checkout API  ║
  ╚═══════════════╝
          │ write
          ▼
  ╔═══════════════╗                                ╔═══════════════╗
  ║   Postgres    ║   outbox CDC  ──────────────►  ║  MSK / Kafka  ║
  ║  (orders DB)  ║               (Debezium)       ║ orders.events ║
  ╚═══════════════╝                                ╚═══════════════╝
                                                           │
         ┌─────────────────────────────────────────────────┼─────────────────────────┐
         ▼                                                 ▼                         ▼
 ╔═══════════════╗                                 ╔═══════════════╗         ╔═══════════════╗
 ║   Inventory   ║                                 ║  OpenSearch   ║         ║  EventBridge  ║
 ║   consumer    ║                                 ║  (CQRS read)  ║         ║ (ops events)  ║
 ╚═══════════════╝                                 ╚═══════════════╝         ╚═══════════════╝
                                                                                     │
                                                                     ┌───────────────┼───────────────┐
                                                                     ▼               ▼               ▼
                                                                  Lambda      Step Functions        SQS
                                                                 (alert)          (saga)         (email)

  CRITICAL PATH: Postgres → outbox → MSK → consumers
  OPERATIONAL: EventBridge for CloudWatch, deployment, audit
  ASYNC WORK: SQS for email, image processing, retries
  FAN-OUT: SNS → multiple SQS queues (isolate failure domains)


EVENTBRIDGE RULE EXAMPLE:
━━━━━━━━━━━━━━━━━━━━━━━━

  {
    "source": ["com.shop.orders"],
    "detail-type": ["OrderPlaced"],
    "detail": {
      "totalCents": [{ ">": 100000 }]
    }
  }
  → Target: fraud-detection Lambda

  EventBridge transforms, input paths, dead-letter config
  per target. Archive all events for 90 days (compliance).
```

### Connecting to CQRS (Week 5)

```
CQRS + EDA = THE READ MODEL PIPELINE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Week 5's CQRS pattern: write to Postgres (command side),
  project to OpenSearch/Redis/ClickHouse (query side).

  The projection update IS an event consumer.

  ╔═══════════════╗  command  ╔═══════════════╗
  ║   API / UI    ║ ────────► ║   Postgres    ║
  ╚═══════════════╝           ║ (write model) ║
                              ╚═══════╤═══════╝
                                      │ CDC / outbox
                                      ▼
                              ╔═══════════════╗
                              ║  orders.events║
                              ║  (Kafka/MSK)  ║
                              ╚═══════╤═══════╝
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
             ╔════════════╗   ╔════════════╗   ╔════════════╗
             ║ OpenSearch ║   ║   Redis    ║   ║ ClickHouse ║
             ║  indexer   ║   ║  cache     ║   ║ analytics  ║
             ╚════════════╝   ╚════════════╝   ╚════════════╝

  EACH PROJECTOR MUST BE:
   - Idempotent (replay-safe)
   - Ordered per entity (partition key = order_id)
   - Version-aware (reject stale projections)
   - Monitored for lag (search stale 30s = user-visible)

  WHEN CDC BREAKS (Week 5, Part 14):
   - All read models drift simultaneously
   - Postgres replication slot bloat
   - Fix upstream FIRST, then rebuild projections from
     offset or snapshot + replay
```

---

## Concrete Examples

### Example 1: Order Placed — Thin vs Fat on AWS

```
SCENARIO: Customer places a $59.98 order for 2× WIDGET-7.
Checkout writes to Postgres, publishes event.


THIN EVENT (notification) + SQS consumer:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Producer (checkout-svc, after DB commit):
    aws sqs send-message \
      --queue-url https://sqs.us-east-1.amazonaws.com/123456789012/fulfillment-queue \
      --message-body '{
        "eventType": "OrderPlaced",
        "eventId": "01JYP2X8K4M5N6P7Q8R9S0T1V2",
        "orderId": "ord_9912",
        "schemaVersion": 2,
        "timestamp": "2026-07-06T14:22:01Z"
      }' \
      --message-attributes '{"eventType":{"DataType":"String","StringValue":"OrderPlaced"}}'

  Consumer (fulfillment-worker):
    1. Receive message (visibility timeout: 300s)
    2. Check processed_events for eventId
    3. GET https://internal-api/orders/ord_9912
    4. Create pick list, write to fulfillment DB
    5. INSERT processed_events, DELETE sqs message

  Failure: internal-api returns 503
    → message returns to queue after visibility timeout
    → consumer retries (idempotent via eventId)
    → after 5 failures → DLQ fulfillment-queue-dlq


FAT EVENT (ECST) on MSK:
━━━━━━━━━━━━━━━━━━━━━━

  Producer (Debezium CDC from outbox table):
    Topic: orders.events
    Key: ord_9912
    Value: {
      "eventType": "OrderPlaced",
      "eventId": "01JYP2X8K4M5N6P7Q8R9S0T1V2",
      "schemaVersion": 2,
      "order": {
        "orderId": "ord_9912",
        "customerId": "cus_441",
        "lines": [{"sku": "WIDGET-7", "qty": 2, "unitPrice": 29.99}],
        "shippingAddress": {"line1": "123 Main St", "zip": "10001"},
        "totalCents": 5998,
        "stateVersion": 1
      }
    }

  Consumer (fulfillment-worker, Kafka consumer group):
    1. poll(), deserialize with Glue Schema Registry
    2. idempotency check on eventId
    3. process embedded order (no API call)
    4. commit offset

  Trade-off visible: fulfillment runs when Order API is down.
  But: schema change in order.lines breaks consumer unless
  schemaVersion handled.
```

### Example 2: Choreographed Payment Flow (SNS → SQS)

```
ARCHITECTURE:
━━━━━━━━━━━

  OrderSvc publishes OrderPlaced → SNS topic orders-placed
    → SQS queue inventory-svc (subscription)
    → SQS queue payment-svc (subscription)
    → SQS queue analytics-svc (subscription)

  Each queue is isolated — analytics slowdown doesn't block
  payment (unlike one shared queue).

  ╔═══════════╗  OrderPlaced  ╔═══════════╗
  ║ Order Svc ║ ─────────────►║    SNS    ║
  ╚═══════════╝               ╚═════╤═════╝
                                    │ fan-out
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             ╔═══════════╗   ╔═══════════╗   ╔═══════════╗
             ║ SQS: inv  ║   ║ SQS: pay  ║   ║ SQS: ana  ║
             ╚═════╤═════╝   ╚═════╤═════╝   ╚═════╤═════╝
                   │               │               │
                   ▼               ▼               ▼
             Inventory Svc    Payment Svc     Analytics Svc

  InventorySvc:
    - Reserve stock
    - Publish InventoryReserved → SNS topic inventory-events
    - On insufficient stock: publish InventoryRejected
      → OrderSvc listens, marks order CANCELLED

  PaymentSvc:
    - Listens to orders-placed (NOT inventory-reserved)
      — INTENTIONAL RISK for demo; production often
        sequences payment after reserve via orchestrator
    - Charges card with Stripe idempotency-key=eventId
    - Publishes PaymentCaptured or PaymentFailed

  CHOREOGRAPHY BUG IN THIS EXAMPLE:
    Payment and Inventory run in PARALLEL.
    Payment might capture before reserve fails → need
    compensation (refund on InventoryRejected).

  This is WHY money paths gravitate toward orchestration.
```

### Example 3: Orchestrated Saga with Step Functions

```
STEP FUNCTIONS STATE MACHINE (simplified):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Start → ReserveInventory → ChargePayment → CreateShipment → Success
              │                    │
              ▼                    ▼
         ReleaseInventory    RefundPayment
         (compensation)       (compensation)

  ReserveInventory state:
    Type: Task
    Resource: arn:aws:lambda:us-east-1:123:function:reserve-inventory
    Retry:
      - ErrorEquals: [States.Timeout, Lambda.ServiceException]
        IntervalSeconds: 2
        MaxAttempts: 3
        BackoffRate: 2
    Catch:
      - ErrorEquals: [InsufficientStock]
        Next: FailOrder
      - ErrorEquals: [States.ALL]
        Next: ReleaseInventory

  ChargePayment state:
    Type: Task
    Resource: arn:aws:lambda:us-east-1:123:function:charge-payment
    Parameters:
      orderId.$: $.orderId
      idempotencyKey.$: $.eventId
    Catch:
      - ErrorEquals: [States.ALL]
        Next: ReleaseInventory

  Execution input:
    {
      "orderId": "ord_9912",
      "eventId": "01JYP2X8K4M5N6P7Q8R9S0T1V2",
      "lines": [...]
    }

  OBSERVABILITY WIN:
    aws stepfunctions describe-execution \
      --execution-arn arn:aws:states:...:execution:OrderSaga:ord_9912
    → exact state, history, failure point

  vs choreography: grep 5 CloudWatch log groups and pray.
```

### Example 4: Kinesis Click Stream with Backpressure

```
CLICK ANALYTICS PIPELINE:
━━━━━━━━━━━━━━━━━━━━━━━

  Edge → Kinesis Data Streams (stream: clicks, 32 shards)
    → Lambda consumer (aggregates per minute)
    → S3 (data lake)
    → Athena

  Shard capacity: 1 MB/s or 1000 records/s per shard (write)
  32 shards = 32 MB/s write ceiling

  BACKPRESSURE SCENARIO:
    Marketing campaign 10× traffic → 45 MB/s
    → ProvisionedThroughputExceeded on PutRecord
    → Edge must SHED: sample 70% of clicks, log dropped count
    → OR: emergency shard split (requires capacity planning)

  MONITORING:
    aws cloudwatch get-metric-statistics \
      --namespace AWS/Kinesis \
      --metric-name WriteProvisionedThroughputExceeded \
      --dimensions Name=StreamName,Value=clicks \
      --start-time 2026-07-06T14:00:00Z \
      --end-time 2026-07-06T15:00:00Z \
      --period 60 \
      --statistics Sum

  IteratorAgeMilliseconds > 60000 → consumer can't keep up
    → scale Lambda concurrency OR add shards (ordering impact!)
```

### Example 5: EventBridge for Cross-Account Audit

```
SECURITY / COMPLIANCE FAN-OUT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Account A (production orders):
    EventBridge bus: default
    Rule: source=com.shop.orders → target: event bus in Account B

  Account B (security):
    Archive: all events, 90-day retention
    Rule: detail-type=PaymentCaptured → Lambda → SIEM

  Cross-account policy on bus B:
    {
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"AWS": "arn:aws:iam::ACCOUNT_A:root"},
        "Action": "events:PutEvents",
        "Resource": "arn:aws:events:us-east-1:ACCOUNT_B:event-bus/audit-bus"
      }]
    }

  WHY NOT MSK for this:
    - Low volume (thousands/day not millions/sec)
    - Need schema discovery + archive + replay
    - Cross-account is first-class in EventBridge
    - Compliance team owns Account B independently
```

---

### Staff

## Production Patterns

### Pattern 1: Transactional Outbox (Preview)

```
PROBLEM: Dual-write
━━━━━━━━━━━━━━━━

  BEGIN;
    INSERT INTO orders ...;
    kafka.publish(OrderPlaced);  -- if this fails, order exists, no event
  COMMIT;
  -- if COMMIT fails after publish, event exists, no order

  THE FIX (detailed in Week 6, Topic 5):
  BEGIN;
    INSERT INTO orders ...;
    INSERT INTO outbox (event_id, payload, ...) VALUES ...;
  COMMIT;
  -- CDC/relay reads outbox → publishes to MSK → marks sent

  EDA systems with a database MUST use outbox or suffer
  ghost records.
```

### Pattern 2: Event Sourcing (When the Log Is Truth)

```
NOT every system needs event sourcing. Use when:
  - Audit trail is regulatory (finance, healthcare)
  - Temporal queries ("what was balance on March 3?")
  - Replay to rebuild projections is routine

  ╔═══════════════╗
  ║  Command API  ║
  ╚═══════╤═══════╝
          │ append only
          ▼
  ╔═══════════════╗   project   ╔═══════════════╗
  ║  Event Store  ║ ──────────► ║  Read Models  ║
  ║  (Kafka/ES)   ║             ║  (mat. views) ║
  ╚═══════════════╝             ╚═══════════════╝

  Cost: complexity, schema evolution on immutable history,
  storage growth, snapshot management.

  Most e-commerce: Postgres is truth, Kafka is distribution.
  That is event streaming, NOT event sourcing.
```

### Pattern 3: Strangler Fig Migration to EDA

```
PHASE 1: Extract events from monolith (change data capture)
  Monolith DB → Debezium → MSK → new microservice consumers
  Monolith unaware; consumers build parallel read paths

PHASE 2: Dual-write period
  Monolith writes DB + outbox; new services consume
  Compare outputs (shadow mode)

PHASE 3: Redirect commands
  API gateway routes new features to new services
  Old features still on monolith

PHASE 4: Retire monolith paths
  When consumer lag stable and parity tests pass

  NEVER big-bang flip a payment path.
```

### Pattern 4: Poison Message Quarantine

```
Production handler pseudocode:

  def handle(message):
    try:
      event = deserialize(message)
      validate_schema(event)
      with db.transaction():
        if already_processed(event.event_id):
          return ACK
        do_work(event)
        mark_processed(event.event_id)
      return ACK
    except SchemaValidationError as e:
      publish_to_dlq(message, reason=str(e))
      return ACK  # don't retry forever
    except TransientDownstreamError:
      return NACK  # retry
    except Exception as e:
      if receive_count > 5:
        publish_to_dlq(message, reason=str(e))
        return ACK
      return NACK

  Classify errors: retry vs quarantine. Never one-size-fits-all.
```

### Pattern 5: Consumer Lag SLOs

```
DEFINE SLO PER CONSUMER GROUP:

  ┌─────────────────────┬──────────────┬───────────────────────┐
  │ Consumer            │ Lag SLO      │ User impact           │
  ├─────────────────────┼──────────────┼───────────────────────┤
  │ search-indexer      │ p95 < 30s    │ stale search results  │
  │ inventory-reserver  │ p95 < 5s     │ oversell risk         │
  │ analytics-aggregator│ p95 < 15min  │ dashboard delay OK    │
  │ fraud-scorer        │ p95 < 2s     │ fraud window          │
  └─────────────────────┴──────────────┴───────────────────────┘

  Alert on burn rate, not instantaneous spike.
  Error budget: 30s lag exceeded 1% of time/month → freeze
  deploys on that consumer until root-caused.
```

### Pattern 6: Schema CI Gate

```
# In CI pipeline, before deploy:
aws glue register-schema-version \
  --schema-id SchemaName=OrderPlaced,RegistryName=prod-events \
  --schema-definition file://schemas/OrderPlaced-v3.avsc \
  --schema-version-number LatestVersion=2,LatestSchemaVersion=3

# Fails if backward/full compatibility violated
# Producer cannot deploy breaking schema without coordinated
# multi-service release (the "stop the world" deploy — avoid)
```

---

## Failure Modes

### Failure 1: Duplicate Charge

```
SCENARIO:
  PaymentCaptured event delivered twice (SQS visibility timeout
  too short — handler took 45s, timeout was 30s).

  Consumer charges card twice. Customer angry. Chargeback.

ROOT CAUSE CHAIN:
  visibility timeout < p99 handler time
  + no idempotency key on Stripe call
  + no processed_events table

DETECTION:
  - Same order_id, two capture transactions in Stripe dashboard
  - processed_events missing but two Payment rows
  - CloudWatch: Lambda Duration p99 > VisibilityTimeout

FIX:
  - idempotency-key = eventId on all payment API calls
  - processed_events dedup
  - visibility timeout = 6 × p99 handler time (AWS guidance)
  - FIFO queue if strict ordering needed per order
```

### Failure 2: Phantom Order (Outbox Gap)

```
SCENARIO:
  Order row committed. Outbox insert failed (disk full).
  Debezium never sees event. Fulfillment never ships.
  Customer charged (sync path), no package.

DETECTION:
  - orders table row exists, no matching event in MSK
  - reconciliation job: COUNT(orders) vs COUNT(events) drift
  - customer support tickets

FIX:
  - outbox in SAME transaction as order (mandatory)
  - reconciliation cron: orders created > 5min ago with no
    fulfillment record → alert
  - never publish-to-Kafka outside transaction
```

### Failure 3: Schema Breakage on Deploy

```
SCENARIO:
  Producer deploys OrderPlaced v3: renamed totalCents → total_amount.
  Consumer still expects totalCents → NullPointerException
  → 100% handler failure → DLQ flood in 4 minutes.

DETECTION:
  - DLQ depth alert
  - Consumer error rate spike correlated with producer deploy
  - Glue schema compatibility check skipped in CI

FIX:
  - add field, don't rename (v3 emits both)
  - consumer handles both: total = event.total_amount ?? event.totalCents
  - rollback producer OR forward-fix consumer
  - enable FULL compatibility in schema registry
```

### Failure 4: Ordering Inversion

```
SCENARIO:
  OrderCancelled processed BEFORE OrderPlaced (standard SQS,
  no FIFO, two messages, unlucky receive order).

  System ends in CANCELLED state for a live order customer
  is viewing as CONFIRMED.

DETECTION:
  - state machine violation logs
  - customer reports "order disappeared"
  - compare event timestamps vs final state

FIX:
  - SQS FIFO with MessageGroupId=order_id
  - OR stateVersion: reject Cancel if current state < PLACED
  - OR orchestrator sequences events
```

### Failure 5: DLQ Replay Storm

```
SCENARIO:
  On-call replays 50K DLQ messages from a schema incident
  without fixing consumer. 50K new failures in 3 minutes.
  Amplifies broker load, triggers throttling on payment topic.

DETECTION:
  - DLQ depth drops to 0 then main queue depth spikes
  - error rate unchanged
  - on-call Slack "I replayed the DLQ"

FIX:
  - fix consumer FIRST
  - replay in batches of 100 with error rate monitoring
  - halt replay if error rate > 1%
```

### Failure 6: EventBridge Throttling During Burst

```
SCENARIO:
  Black Friday: 50K orders/sec peak. All operational events
  routed through EventBridge for "consistency." Account limit
  10K events/sec. ThrottledRules metric spikes. Fraud Lambda
  never invoked.

DETECTION:
  - EventBridge ThrottledRules > 0
  - Fraud bypass rate drops to zero while orders succeed
  - PutEvents FailedEntryCount in producer logs

FIX:
  - critical path on MSK/SQS, not EventBridge
  - request limit increase (takes days — plan ahead)
  - shed non-critical rules under load
```

### Failure 7: Kinesis Iterator Age Death Spiral

```
SCENARIO:
  Consumer Lambda times out (downstream DB slow). Iterator
  age grows. Lambda reads larger batches to catch up. More
  timeouts. Age → 1 hour. Data loss when retention = 24h
  and age approaches retention.

DETECTION:
  - GetRecords.IteratorAgeMilliseconds > 300000
  - Lambda concurrent executions at account limit
  - shard metrics show read throttling

FIX:
  - scale consumer (parallelization per shard = 1 for ordered)
  - optimize handler (batch DB writes)
  - increase shard count (split)
  - extend retention temporarily during recovery
```

### Failure 8: Cross-Service Cyclic Event Loop

```
SCENARIO:
  Service A publishes StatusChanged → Service B reacts,
  publishes StateUpdated → Service A reacts, publishes
  StatusChanged. Infinite loop. Kafka volume 100× normal.

DETECTION:
  - topic byte rate spike
  - same entity_id in thousands of events per minute
  - consumer CPU pegged

FIX:
  - guard: don't emit if state unchanged (dedup at source)
  - max hop counter in event metadata
  - choreography review in design doc (cycle detection)
```

---

## SRE Diagnostic Toolkit

```
EDA INCIDENT TRIAGE — FIRST 5 MINUTES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Is the broker healthy?
  2. Is lag growing or stable?
  3. Is error rate on consumers spiking?
  4. Was there a deploy in the last 30 minutes?
  5. Is DLQ depth > 0?


MSK / KAFKA LAG:
━━━━━━━━━━━━━━━━

  # Consumer group lag (burrow, kafka-consumer-groups, or CW)
  kafka-consumer-groups --bootstrap-server $BS \
    --describe --group fulfillment-workers

  # Output: LAG column per partition. ANY partition > 0 for
  # critical group → investigate. Per-partition, not average.

  # Under-replicated partitions (from Kafka module)
  kafka-topics --bootstrap-server $BS \
    --describe --under-replicated-partitions

  # Messages per second per topic
  kafka-run-class kafka.tools.GetOffsetInfo ...  # or metrics


SQS DIAGNOSTICS:
━━━━━━━━━━━━━━━

  # Queue depth and oldest message age
  aws sqs get-queue-attributes \
    --queue-url $QUEUE_URL \
    --attribute-names ApproximateNumberOfMessages \
      ApproximateNumberOfMessagesNotVisible \
      ApproximateAgeOfOldestMessage

  # DLQ depth (ALERT IF > 0)
  aws sqs get-queue-attributes \
    --queue-url $DLQ_URL \
    --attribute-names ApproximateNumberOfMessages

  # Peek DLQ without deleting (receive, inspect, leave)
  aws sqs receive-message \
    --queue-url $DLQ_URL \
    --max-number-of-messages 1 \
    --visibility-timeout 0

  # Redrive DLQ to source (after fix!)
  aws sqs start-message-move-task \
    --source-arn arn:aws:sqs:us-east-1:123:fulfillment-dlq \
    --destination-arn arn:aws:sqs:us-east-1:123:fulfillment-queue


KINESIS DIAGNOSTICS:
━━━━━━━━━━━━━━━━━━━

  # Iterator age per shard (THE metric)
  aws cloudwatch get-metric-statistics \
    --namespace AWS/Kinesis \
    --metric-name GetRecords.IteratorAgeMilliseconds \
    --dimensions Name=StreamName,Value=orders-stream \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
    --period 60 \
    --statistics Maximum

  # Write throttling
  aws cloudwatch get-metric-statistics \
    --namespace AWS/Kinesis \
    --metric-name WriteProvisionedThroughputExceeded \
    --dimensions Name=StreamName,Value=orders-stream \
    --period 60 --statistics Sum ...


EVENTBRIDGE DIAGNOSTICS:
━━━━━━━━━━━━━━━━━━━━━━━

  # Failed invocations per rule
  aws cloudwatch get-metric-statistics \
    --namespace AWS/Events \
    --metric-name FailedInvocations \
    --dimensions Name=RuleName,Value=order-placed-fraud \
    --period 60 --statistics Sum ...

  # Throttled rules
  --metric-name ThrottledRules

  # Replay from archive (incident recovery)
  aws events start-replay \
    --event-source-arn arn:aws:events:us-east-1:123:archive/orders-90d \
    --destination '{"Arn":"arn:aws:events:...:event-bus/default"}' \
    --event-start-time 2026-07-06T14:00:00Z \
    --event-end-time 2026-07-06T14:30:00Z


STEP FUNCTIONS SAGA STUCK:
━━━━━━━━━━━━━━━━━━━━━━━━

  # List running executions
  aws stepfunctions list-executions \
    --state-machine-arn $SAGA_ARN \
    --status-filter RUNNING

  # Execution history (where did it stop?)
  aws stepfunctions get-execution-history \
    --execution-arn $EXEC_ARN \
    --max-results 100

  # Look for TaskFailed, LambdaFunctionFailed


RECONCILIATION QUERIES (ghost detection):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  -- Orders without fulfillment after 10 minutes
  SELECT o.order_id
  FROM orders o
  LEFT JOIN fulfillment f ON o.order_id = f.order_id
  WHERE o.created_at < now() - interval '10 minutes'
    AND o.status = 'PLACED'
    AND f.order_id IS NULL;

  -- Event count vs order count (daily drift)
  SELECT date(created_at), count(*) FROM orders GROUP BY 1;
  -- compare to MSK topic message count per day


LOG PATTERNS (CloudWatch Logs Insights):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Duplicate processing attempts
  fields @timestamp, eventId, orderId
  | filter @message like /already_processed/
  | stats count() by eventId
  | filter count > 1

  # Schema validation failures
  fields @timestamp, @message
  | filter @message like /SchemaValidationError/
  | stats count() by bin(5m)

  # Handler duration vs timeout
  fields @timestamp, @duration
  | filter @type = "REPORT"
  | stats pct(@duration, 99) as p99 by bin(5m)
```

---

## Decision Framework

```
EVENT SHAPE: THIN VS FAT
━━━━━━━━━━━━━━━━━━━━━━━

  Start thin if:
    □ Payload would exceed 64 KB
    □ PII/regulated data involved
    □ Consumers need different views of same entity
    □ Strong API exists with good SLO

  Start fat if:
    □ Building CQRS projection (Week 5)
    □ Consumer autonomy during producer outage is required
    □ Callback would multiply load (fan-out > 10)
    □ Event is the audit record of record


COORDINATION: CHOREOGRAPHY VS ORCHESTRATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────────────┬──────────────┬──────────────┐
  │ Factor                     │ Choreography │ Orchestration│
  ├────────────────────────────┼──────────────┼──────────────┤
  │ Steps                      │ ≤ 3 simple   │ > 3 or $$$   │
  │ Compensation               │ rare         │ required     │
  │ Visibility requirement     │ low          │ high (support│
  │                            │              │  + audit)    │
  │ Team structure             │ independent  │ platform owns│
  │                            │ teams        │ workflow     │
  │ Failure debug time budget  │ hours OK     │ minutes      │
  └────────────────────────────┴──────────────┴──────────────┘

  Hybrid: choreograph notifications (email, analytics);
  orchestrate money (Step Functions / Temporal).


AWS TRANSPORT CHOOSER:
━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────┬────────────────────────────────┐
  │ Need                         │ Pick                           │
  ├──────────────────────────────┼────────────────────────────────┤
  │ One worker per job           │ SQS Standard                   │
  │ Strict per-entity order      │ SQS FIFO or Kinesis or MSK     │
  │ Fan-out to many queues       │ SNS → SQS                      │
  │ Content-based routing        │ EventBridge                    │
  │ Cross-account audit trail    │ EventBridge + Archive          │
  │ High-volume multi-consumer   │ MSK or Kinesis                 │
  │ Replay + Kafka ecosystem     │ MSK                            │
  │ SaaS webhook ingestion       │ EventBridge partner bus        │
  │ Durable workflow + compensate│ Step Functions                 │
  └──────────────────────────────┴────────────────────────────────┘


DELIVERY GUARANTEE CHOOSER:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  Can you tolerate lost messages?
    YES → at-most-once (fire-and-forget metrics)
    NO  ↓

  Can you make handlers idempotent?
    YES → at-least-once (DEFAULT — SQS, Kafka, Kinesis)
    NO  → stop: redesign handler (you need idempotency)

  Need broker-level dedup for producer retries only?
    → Kafka idempotent producer or SQS FIFO dedup window

  Need atomic write-across-partitions + consume?
    → Kafka transactions (narrow use case)

  Claiming end-to-end exactly-once?
    → You are wrong unless every side effect is idempotent.
```

---

### Principal stretch

## Ops Sim: Northstar Order Event Contract Break

**Time box:** 50 minutes  
**Severity:** P1  
**Service / domain:** Order events, schema registry, consumers, warehouse/search/email  
**Northstar system:** Northstar Commerce

### Runbook rules

1. Answer from memory of the Event-Driven Architecture teaching section; do not re-read mid-drill.
2. Write decisions in order: T+0, T+5, T+15, T+30, T+60, and follow-up.
3. Tie every claim to a metric, log line, trace, query output, or config key from this packet.
4. Name the correctness invariant before proposing scale, failover, replay, or data repair.
5. Do not open the answer key until your response is written.

---

### Incident stem

```text
WHAT USERS SEE:
  - Warehouse pick tickets omit gift-wrap instructions.
  - Search shows packed orders as cancellable.
  - Fraud notifications lag for high-value orders.
  - Replay attempts duplicate customer status emails.

WHAT ON-CALL SEES:
  - Schema registry reports compatibility passed.
  - Unknown enum counters spike in multiple consumers.
  - Broker ISR, produce latency, and consumer process health are normal.
  - A replay-after-patch plan is proposed before idempotency exists.

BUSINESS CONSTRAINT:
  Do not ship, cancel, notify, or repair from misinterpreted derived events.
```

### Operational physics

A producer reuses a field for a new enum meaning under the same schema id. Type compatibility passes, but old consumers default unknown values into destructive business states.

Break it into these forces before answering:
- trigger: the release/config/data shape that started the failure
- amplifier: retry, cache, routing, projection, or observability behavior that widened it
- scarce resource: the metric that reaches a limit first
- invariant: what must remain conservative even while users see degraded experience
- repair boundary: the source of truth and operation id used after mitigation

### Deployment clues

- The suspicious production lever is `schema.compatibility: BACKWARD`; tie it to the first bad minute before changing capacity.
- The dashboard that stayed calm does not expose `consumer_unknown_enum_total{field="status_reason"}` for the damaged slice.
- The runbook move closest to "replay immediately after consumer deploy" needs an explicit no-go decision on the bridge.
- The repair path is allowed only after the source-of-truth query and operation key are written down.

### Observed evidence

```text
METRICS:
  - consumer_unknown_enum_total{field="status_reason"}: 0 -> 64200
  - warehouse_pick_ticket_missing_gift_wrap_total: +8700
  - fraud_event_lag_seconds{p99}: 12 -> 980
  - search_order_state_mismatch_total: +19200
  - email_duplicate_status_total: +4100
  - kafka_consumer_lag{group="warehouse"}: 0 -> 240k
  - schema_registry_compatibility_fail_total: 0
  - order_cancel_after_pack_attempt_total: +680

LOG LINES:
  - warehouse-consumer: unknown status_reason=PACKED_WITH_GIFT_WRAP mapped=CUSTOMER_CANCELLED
  - fraud-consumer: skipped event because state transition invalid order_id=ns-441
  - email-replay: sent status template=cancelled operation_id=null
  - schema-registry: compatibility check passed subject=orders-value
  - order-api: source status=PACKED differs from search status=CANCELLABLE

TRACE / QUERY / INSPECTION NOTES:
  - Event diff keeps same schema id while changing enum semantics.
  - Consumers do not share unknown-value behavior.
  - Side-effect ledgers lack event-id idempotency.
  - The broker delivered bytes correctly; semantics are wrong.
```

### Config under suspicion

```yaml
schema.compatibility: BACKWARD
event.version.bump_required_for_enum_semantics: false
consumer.unknown_enum_policy: default_zero
consumer.dlq_on_unknown_semantic: false
replay.email.operation_id: null
```

### Timeline

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | Warehouse/search mismatches page with no broker errors. | Inspect event semantics. |
| T+5 | Producer cites schema compatibility pass. | Challenge semantic compatibility. |
| T+15 | Unknown enum mapping is found. | Pause side-effecting consumers. |
| T+30 | Consumers are patched. | Plan idempotent replay. |
| T+60 | Duplicate emails need repair. | Use communication ledger. |
| T+24h | Platform asks for policy. | Define semantic version gates. |

### Controls you can pull

- Roll back or disable the specific dangerous config from the packet.
- Shed decorative, derived, notification, or analytics work before weakening source-of-truth correctness.
- Throttle retry/replay using the narrowest downstream capacity limit.
- Keep an affected-record ledger before customer-visible repair.
- Verify recovery with the sliced SLI plus the scarce-resource metric, not a fleet average.

### Bad fixes

For each proposal, name the concrete failure mode it creates.

- replay immediately after consumer deploy
- trust schema type compatibility as semantic safety
- drop unknown events
- patch only one consumer

### Principal prompts

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

### Score after answer key

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

**Answer key:** [answers/Week-06-Architecture-Patterns/Event-Driven Architecture Answers.md](../answers/Week-06-Architecture-Patterns/Event-Driven%20Architecture%20Answers.md)

