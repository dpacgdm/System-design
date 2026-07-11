# Week 6, Topic 3 — Saga Pattern

> Distributed transactions without a distributed database. When a business operation spans multiple services, each with its own database, you cannot wrap them in a single ACID transaction. The saga pattern sequences local transactions and defines how to undo them when something fails.

Same density as Message Queues and Kafka. Same teaching contract: every section answers *what do I run, what do I look at, what's the bug nobody warned me about.*

**Prerequisite mental model.** A saga is not a transaction manager. It is a **workflow with compensations** — a sequence of steps where each step commits locally, and failure triggers reverse steps that may themselves fail, timeout, or arrive out of order.

---

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Explain why 2PC fails at microservice scale and           ║
║      when sagas are the correct alternative                    ║
║                                                                ║
║   2. Design choreography vs orchestration sagas and            ║
║      choose between them for a given workflow                  ║
║                                                                ║
║   3. Implement compensating transactions with correct          ║
║      idempotency, saga logs, and timeout semantics             ║
║                                                                ║
║   4. Build sagas on AWS Step Functions, a custom               ║
║      orchestrator, or Kafka — with exact configs               ║
║                                                                ║
║   5. Diagnose production saga failures: stuck executions,      ║
║      phantom charges, double compensation, and                 ║
║      partial rollback in travel/booking domains                ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Saga = distributed 2PC"                        ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Two-phase commit holds locks across services until        ║
║   all vote commit. Sagas commit each step immediately and          ║
║   compensate later. There is no global isolation. Between          ║
║   steps, other transactions see intermediate state.                ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Compensation = undo"                           ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Compensation is a **semantic reversal**, not a time       ║
║   machine. CancelFlight does not erase the fact that a seat        ║
║   was held for 47 seconds. RefundPayment may take 5 days.          ║
║   Compensations have their own failure modes and SLAs.             ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Choreography scales, orchestration             ║
║   doesn't"                                                         ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Choreography scales *code* deployment but not             ║
║   *debuggability*. At 5+ services with money movement,             ║
║   choreography becomes "grep 12 log groups and reconstruct         ║
║   state." Orchestration centralizes state; the bottleneck is       ║
║   usually the orchestrator's DB, not the pattern itself.           ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Idempotency keys fix everything"               ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Idempotency keys prevent duplicate *forward* steps.       ║
║   They do not prevent: compensating twice, compensating            ║
║   before forward completes, or a timeout that looks like           ║
║   failure but actually succeeded. You need saga state +            ║
║   idempotency together.                                            ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Step Functions = sagas for free"               ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Step Functions gives you state machine execution and      ║
║   retries. YOU still design compensations, idempotency,            ║
║   timeout semantics, and what happens when a compensation          ║
║   Lambda times out after the refund actually went through.         ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Kafka ordering guarantees saga correctness"    ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Per-partition ordering helps but does not replace         ║
║   a saga log. Rebalances, retries, and at-least-once delivery      ║
║   still produce duplicates and out-of-order *processing*           ║
║   unless consumers are idempotent and state-aware.                 ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching — The Problem Sagas Solve

### Foundation

### Why Not Two-Phase Commit?

```
THE MICROSERVICES TRANSACTION PROBLEM:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  User books a trip:
    1. Reserve flight seat     (FlightSvc + FlightDB)
    2. Reserve hotel room      (HotelSvc + HotelDB)
    3. Reserve rental car      (CarSvc + CarDB)
    4. Charge credit card      (PaymentSvc + PaymentDB)

  Each service owns its database. No shared transaction coordinator.

  NAIVE APPROACH — 2PC (Two-Phase Commit):
  ┌─────────────┐     prepare      ┌─────────────┐
  │ FlightSvc   │◄────────────────►│ Coordinator │
  └─────────────┘                  │  (XA txn)   │
  ┌─────────────┐     prepare      │             │
  │ HotelSvc    │◄────────────────►│  Phase 1:   │
  └─────────────┘                  │  all vote   │
  ┌─────────────┐     prepare      │  Phase 2:   │
  │ PaymentSvc  │◄────────────────►│  all commit │
  └─────────────┘                  └─────────────┘

  WHY 2PC FAILS IN PRODUCTION:

  1. AVAILABILITY
     Coordinator or any participant down → entire transaction blocks.
     A slow HotelSvc blocks FlightSvc holds on inventory.

  2. LOCK DURATION
     Prepare phase holds row locks until commit/abort.
     Cross-service calls add network latency → lock time explodes.
     Flight inventory locked while waiting for Stripe API.

  3. NO FIRST-CLASS CLOUD SUPPORT
     AWS RDS, DynamoDB, SQS, Lambda — none offer XA transactions
     across service boundaries. You'd build a coordinator yourself
     (you're building a saga, badly).

  4. COUPLING
     All participants must implement prepare/commit protocol.
     Schema changes require coordinator awareness.

  THE SAGA ALTERNATIVE:
     Each step is a LOCAL transaction that commits immediately.
     On failure, run COMPENSATING transactions in reverse order.
     Trade global atomicity for eventual consistency + explicit
     failure handling.
```

### What IS a Saga?

```
SAGA DEFINITION (Chris Richardson, microservices.io):

  A sequence of LOCAL transactions T1, T2, ..., Tn.
  Each Ti:
    - Updates ONE service's database
    - Publishes an event or message triggering Ti+1

  If Tk fails:
    - Run compensating transactions C(k-1), C(k-2), ..., C1
    - Each Cj reverses the effect of Tj (semantically)

  SAGA INVARIANTS (what you must guarantee):

  1. Every forward step is IDEMPOTENT (or keyed by sagaId)
  2. Every compensation is IDEMPOTENT
  3. Saga state is PERSISTED (saga log) before side effects
  4. Timeouts have explicit semantics (unknown ≠ failed)
  5. Partial completion is VISIBLE and QUERYABLE

  SAGA STATE MACHINE (conceptual):

       ┌──────────┐
       │ STARTED  │
       └────┬─────┘
            │ T1 success
            ▼
       ┌──────────┐     T2 fail     ┌─────────────┐
       │ STEP_1   │────────────────►│ COMPENSATING│
       │ COMPLETE │                 │   STEP_1    │
       └────┬─────┘                 └──────┬──────┘
            │ T2 success                   │
            ▼                              ▼
       ┌──────────┐                   ┌──────────┐
       │ STEP_2   │                   │ FAILED   │
       │ COMPLETE │                   │ (terminal)│
       └────┬─────┘                   └──────────┘
            │
           ...
            ▼
       ┌───────────┐
       │ COMPLETED │
       │ (terminal)│
       └───────────┘
```

### Choreography vs Orchestration

```
CHOREOGRAPHY — NO CENTRAL BRAIN:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Services react to each other's events. No coordinator.

  TripBooking (choreography):

    BookingSvc                FlightSvc              HotelSvc
        │                         │                      │
        │ TripBookingRequested    │                      │
        ├────────────────────────►│                      │
        │                         │ reserve seat (local) │
        │◄──FlightReserved────────┤                      │
        │                         │                      │
        │ HotelReservationReq     │                      │
        ├──────────────────────────────────────────────►│
        │                         │                      │
        │◄──────────────HotelReserved─────────────────────┤
        │                         │                      │
        │ ... CarSvc, PaymentSvc listen to prior events   │

  PROS:
    - Loose coupling — BookingSvc doesn't know HotelSvc API
    - No single point of failure for orchestration logic
    - Services can be added as new event listeners

  CONS:
    - Implicit workflow — cannot "grep the saga"
    - Cyclic dependencies if events bounce back
    - Compensation chains are hard to trace
    - "Who compensates what?" becomes tribal knowledge
    - Debugging: reconstruct state from 6 Kafka topics

  WHEN CHOREOGRAPHY WORKS:
    - 2-3 services, simple linear flow
    - No money movement (or money is last step with clear trigger)
    - Team owns entire event contract
    - Failures are cheap to fix manually


ORCHESTRATION — CENTRAL COORDINATOR:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  One component tells each service what to do and tracks state.

    ┌──────────────────┐
    │ Saga Orchestrator│
    │ (Step Functions, │
    │  custom service) │
    └────────┬─────────┘
             │ commands                    events/responses
     ┌───────┼───────┬───────────┐
     ▼       ▼       ▼           ▼
  Flight   Hotel    Car      Payment
   Svc      Svc     Svc        Svc

  Orchestrator state (saga log):
    sagaId: trip_8f3a2b
    currentStep: CHARGE_PAYMENT
    completedSteps: [RESERVE_FLIGHT, RESERVE_HOTEL, RESERVE_CAR]
    status: IN_PROGRESS

  PROS:
    - Explicit workflow — one place to read saga definition
    - Compensation order is defined, not emergent
    - Queryable state: "show me all stuck sagas > 10 min"
    - Timeouts centralized
    - Easier compliance audit ("prove what happened to order X")

  CONS:
    - Orchestrator is a dependency (mitigate: HA, state in DynamoDB)
    - Orchestrator can become a god-service if you're not careful
    - More upfront design (state machine definition)

  WHEN ORCHESTRATION WORKS:
    - Money movement or inventory with compensation
    - > 3 services in the workflow
    - Regulatory/audit requirements
    - Operations team needs runbooks with clear state queries
```

```
SIDE-BY-SIDE COMPARISON:
━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────────┬──────────────────┬────────────────────┐
  │ Dimension              │ Choreography     │ Orchestration      │
  ├────────────────────────┼──────────────────┼────────────────────┤
  │ Control flow           │ Implicit (events)│ Explicit (FSM)     │
  │ State location         │ Distributed      │ Saga log           │
  │ Debug "where stuck?"   │ Hard             │ Easy               │
  │ Add new step           │ New listener     │ Edit state machine │
  │ Compensation order     │ Event-driven     │ Defined in FSM     │
  │ Coupling               │ Event schema     │ Command API        │
  │ Single point of failure│ None (theoretic) │ Orchestrator       │
  │ Best for               │ Analytics flows  │ Booking/payments   │
  └────────────────────────┴──────────────────┴────────────────────┘

  HYBRID (common in production):
    Orchestrator for the money path (reserve → charge → confirm)
    Choreography for side effects (send email, update analytics,
    push notification) — these don't need compensation in the
    critical path.
```

### Compensating Transactions

### Staff

```
FORWARD vs COMPENSATE — NOT MIRROR IMAGES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Forward step              Compensation           Semantics
  ────────────────────────  ─────────────────────  ──────────────────
  ReserveFlight(seat 12A)   CancelFlight(seat 12A) Release hold; seat
                                                     may go to waitlist
  ReserveHotel(room 401)    CancelHotel(room 401)  Cancellation policy
                                                     may charge fee
  ChargeCard($847.00)       RefundCard($847.00)    Refund is async;
                                                     partial refunds exist
  SendConfirmationEmail()   SendCancellationEmail() Email can't be
                                                     "unsent" — compensate
                                                     with new message

  COMPENSATION RULES:

  1. COMPENSATE ONLY COMPLETED STEPS
     If ChargeCard timed out, you don't know if it succeeded.
     DO NOT blindly RefundCard — query payment status first.

  2. COMPENSATIONS ARE IDEMPOTENT
     CancelFlight(trip_8f3a2b) called twice must not double-release
     or error on "already cancelled."

  3. COMPENSATION ORDER IS REVERSE OF FORWARD
     Forward: Flight → Hotel → Car → Payment
     Compensate: Refund Payment → Cancel Car → Cancel Hotel → Cancel Flight
     (Payment first when money was captured; inventory order may vary
      by business rules)

  4. COMPENSATION CAN FAIL
     RefundCard fails (card expired). Saga enters COMPENSATION_FAILED.
     Human intervention required. Alert fires. Manual refund queue.

  5. PIVOTAL vs RETRYABLE vs COMPENSATABLE (step classification)

     PIVOTAL:     failure aborts saga, run compensations
     RETRYABLE:   transient error, retry with backoff
     COMPENSATABLE: failure triggers compensation chain

     Example:
       ReserveFlight  → RETRYABLE (network blip) then PIVOTAL (no seats)
       ChargeCard     → PIVOTAL (decline = abort)
       SendEmail      → fire-and-forget; saga already COMPLETED
```

```
COMPENSATION STATE MACHINE (per step):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  For step "ReserveHotel":

       ┌─────────────┐
       │  PENDING    │
       └──────┬──────┘
              │ execute forward
              ▼
       ┌─────────────┐     timeout      ┌─────────────┐
       │  EXECUTING  │─────────────────►│  UNKNOWN    │
       └──────┬──────┘                  └──────┬──────┘
              │ success                       │ status query
              ▼                               ▼
       ┌─────────────┐                  ┌─────────────┐
       │  COMPLETED  │                  │  COMPLETED  │ or FAILED
       └──────┬──────┘                  └─────────────┘
              │ saga fails
              ▼
       ┌─────────────┐
       │ COMPENSATING│
       └──────┬──────┘
              │
     ┌────────┼────────┐
     ▼        ▼        ▼
 COMPENSATED FAILED  SKIPPED
 (terminal) (alert)  (never completed forward)
```

### Idempotency Keys

```
WHY IDEMPOTENCY IS NON-NEGOTIABLE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  At-least-once delivery (SQS, Kafka, Step Functions retries)
  means every saga step WILL be delivered more than once.

  WITHOUT IDEMPOTENCY:
    Retry ReserveFlight → two seats held for one passenger
    Retry ChargeCard    → double charge
    Retry RefundCard    → double refund (merchant loss)

  IDEMPOTENCY KEY DESIGN:
  ┌────────────────────────────────────────────────────────────┐
  │  idempotencyKey = f(sagaId, stepName, [attempt?])          │
  │                                                            │
  │  trip_8f3a2b:RESERVE_FLIGHT     → one seat hold max        │
  │  trip_8f3a2b:CHARGE_PAYMENT     → one charge max           │
  │  trip_8f3a2b:COMPENSATE_REFUND  → one refund max           │
  └────────────────────────────────────────────────────────────┘

  DO NOT include attempt number in the key for forward steps.
  Same saga step retried = same key = same outcome.

  DO use separate keys for compensation:
    Forward:  trip_8f3a2b:CHARGE_PAYMENT
    Compensate: trip_8f3a2b:REFUND_PAYMENT
  (Different operations; both must be idempotent independently)

  STORAGE PATTERN (DynamoDB idempotency table):

  Table: idempotency_keys
  PK: idempotencyKey (String)
  Attributes:
    status: IN_PROGRESS | COMPLETED | FAILED
    result: (serialized response, written on completion)
    ttl: epoch (24-72h cleanup)
    createdAt: ISO8601

  Handler logic:
    1. Conditional put: status=IN_PROGRESS, only if key absent
    2. If ConditionalCheckFailed → read existing status/result
       - COMPLETED → return cached result (don't re-execute)
       - IN_PROGRESS → return 409 or wait (another worker active)
    3. Execute business logic
    4. Update status=COMPLETED, result=...

  STRIPE ALIGNMENT (payment services):
    Stripe-Idempotency-Key: trip_8f3a2b:CHARGE_PAYMENT
    Same key within 24h → same PaymentIntent, no double charge.
```

### The Saga Log

```
SAGA LOG = SOURCE OF TRUTH FOR SAGA STATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Without a saga log, you have events in Kafka and hope.
  With a saga log, you can answer:
    - How many sagas are stuck in COMPENSATING?
    - What step failed for trip_8f3a2b?
    - Did we charge before or after hotel reservation?

  MINIMUM SCHEMA (DynamoDB or PostgreSQL):

  Table: saga_instances
  ┌──────────────────┬───────────────────────────────────────────┐
  │ sagaId (PK)      │ trip_8f3a2b                               │
  │ sagaType         │ TRIP_BOOKING                              │
  │ status           │ IN_PROGRESS | COMPLETED | FAILED |        │
  │                  │ COMPENSATING | COMPENSATION_FAILED        │
  │ currentStep      │ RESERVE_HOTEL                             │
  │ payload          │ { userId, itinerary, ... }  (JSON)        │
  │ createdAt        │ 2026-07-06T14:22:01Z                      │
  │ updatedAt        │ 2026-07-06T14:22:47Z                      │
  │ expiresAt        │ TTL for cleanup of terminal states        │
  │ correlationId    │ trace-id for observability                │
  └──────────────────┴───────────────────────────────────────────┘

  Table: saga_step_log (append-only audit)
  ┌──────────────────┬───────────────────────────────────────────┐
  │ sagaId + stepSeq │ trip_8f3a2b#003 (sort key)                │
  │ stepName         │ RESERVE_HOTEL                             │
  │ direction        │ FORWARD | COMPENSATE                      │
  │ status           │ STARTED | COMPLETED | FAILED | TIMEOUT    │
  │ idempotencyKey   │ trip_8f3a2b:RESERVE_HOTEL                 │
  │ request          │ { hotelId, checkIn, ... }                 │
  │ response         │ { confirmationCode: "HTL-9912" }          │
  │ error            │ null or { code, message }                 │
  │ startedAt        │ 2026-07-06T14:22:45Z                      │
  │ completedAt      │ 2026-07-06T14:22:47Z                      │
  └──────────────────┴───────────────────────────────────────────┘

  WRITE ORDER (critical):
    1. Insert saga_instances (status=IN_PROGRESS)
    2. Insert saga_step_log (step=RESERVE_FLIGHT, status=STARTED)
    3. Call FlightSvc
    4. Update saga_step_log (status=COMPLETED, response=...)
    5. Update saga_instances (currentStep=RESERVE_HOTEL)

  Never call external service before logging STARTED.
  If you crash between (3) and (4), reconciliation job finds
  STARTED without COMPLETED → query external system or retry.

  DYNAMODB EXAMPLE — create saga:

  aws dynamodb put-item \
    --table-name saga_instances \
    --item '{
      "sagaId": {"S": "trip_8f3a2b"},
      "sagaType": {"S": "TRIP_BOOKING"},
      "status": {"S": "IN_PROGRESS"},
      "currentStep": {"S": "RESERVE_FLIGHT"},
      "payload": {"S": "{\"userId\":\"usr_12\",\"itinerary\":{...}}"},
      "createdAt": {"S": "2026-07-06T14:22:01Z"},
      "updatedAt": {"S": "2026-07-06T14:22:01Z"},
      "correlationId": {"S": "trace-abc123"}
    }' \
    --condition-expression "attribute_not_exists(sagaId)"
```

### Timeout Handling

```
THE TIMEOUT PROBLEM:
━━━━━━━━━━━━━━━━━━

  Orchestrator calls ReserveHotel Lambda with 30s timeout.
  Lambda calls HotelSvc HTTP with 25s timeout.
  HotelSvc commits reservation at t=24s.
  Network partition: response never arrives.
  Lambda times out at t=30s.
  Orchestrator marks RESERVE_HOTEL as FAILED.
  Orchestrator starts compensation (cancel flight).
  Hotel reservation EXISTS. User has hotel + no flight. Or worse:
  orchestrator retries ReserveHotel → double booking.

  TIMEOUT IS NOT FAILURE. TIMEOUT IS UNKNOWN.

  CORRECT HANDLING:

  1. CLASSIFY OUTCOMES
     ┌────────────┬──────────────────────────────────────────────┐
     │ Outcome    │ Action                                       │
     ├────────────┼──────────────────────────────────────────────┤
     │ Success    │ Advance saga                                 │
     │ Definite   │ Compensate (e.g., 409 InsufficientStock)     │
     │ failure    │                                              │
     │ Timeout    │ Mark step UNKNOWN; run reconciliation        │
     │            │ DO NOT compensate until status confirmed     │
     │            │ DO NOT retry forward blindly                 │
     └────────────┴──────────────────────────────────────────────┘

  2. RECONCILIATION LOOP (saga watchdog)
     Every 60s, query saga_step_log where status=TIMEOUT or UNKNOWN
     For each:
       - Call HotelSvc GET /reservations?sagaId=trip_8f3a2b
       - If exists → mark COMPLETED, advance saga
       - If not exists → mark FAILED, trigger compensation

  3. TIMEOUT BUDGETS (travel booking example)
     ┌────────────────────┬──────────┬──────────┬───────────────┐
     │ Step               │ Client   │ Lambda   │ Step Fn wait  │
     ├────────────────────┼──────────┼──────────┼───────────────┤
     │ ReserveFlight      │ 10s      │ 15s      │ 20s           │
     │ ReserveHotel       │ 10s      │ 15s      │ 20s           │
     │ ReserveCar         │ 8s       │ 12s      │ 15s           │
     │ ChargePayment      │ 30s      │ 45s      │ 60s (Stripe)  │
     │ Each compensation  │ 30s      │ 45s      │ 60s           │
     └────────────────────┴──────────┴──────────┴───────────────┘
     Client timeout < Lambda timeout < Step Functions HeartbeatTimeout
     Always leave margin for cleanup code.

  4. HEARTBEAT PATTERN (long steps)
     Step Functions: HeartbeatSeconds + SendTaskHeartbeat
     Worker reports progress; if heartbeats stop, Step Functions
     fails the task → triggers Catch → compensation path.
     Use for steps that legitimately take minutes (manual approval).

  5. SAGA-LEVEL TIMEOUT
     Trip booking saga: max 15 minutes wall clock.
     If not COMPLETED by expiresAt → mark FAILED, alert, manual review.
     Prevents infinite COMPENSATING loops.
```

### Partial Failure

```
PARTIAL FAILURE = SOME STEPS SUCCEEDED, THEN A LATER STEP FAILED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Forward progress:
    ✓ Flight reserved (confirmation FL-8821)
    ✓ Hotel reserved (confirmation HTL-9912)
    ✗ Car rental failed (no cars at airport)
    → Saga aborts BEFORE payment (good — no charge yet)

  Compensation:
    Cancel HTL-9912  ✓
    Cancel FL-8821   ✗ (airline API down)

  PARTIAL COMPENSATION STATE:
    status: COMPENSATION_FAILED
    completedSteps: [RESERVE_FLIGHT, RESERVE_HOTEL]
    compensatedSteps: [CANCEL_HOTEL]
    pendingCompensation: [CANCEL_FLIGHT]

  USER-VISIBLE STATE DURING PARTIAL FAILURE:
    - Flight still held (may expire in 24h or incur fee)
    - Hotel cancelled
    - No car, no charge
    - Support ticket auto-created

  OPERATIONAL REQUIREMENTS:

  1. PERSIST partial compensation state — never lose pendingCompensation
  2. RETRY compensations with exponential backoff (separate from forward retries)
  3. DEAD LETTER after N compensation failures → human queue
  4. IDEMPOTENT compensations — retry CancelFlight must be safe
  5. CUSTOMER COMMUNICATION — don't say "booking failed" if flight still held

  PARTIAL FAILURE vs SPLIT BRAIN:

  Orchestrator thinks: Hotel NOT reserved (timeout)
  HotelSvc reality:     Hotel IS reserved

  This is worse than partial failure — it's inconsistent state.
  Prevention: reconciliation on UNKNOWN + idempotency keys on forward steps
  so retry doesn't create duplicate reservation.
```

### AWS Step Functions vs Custom Orchestrator

### Principal stretch

```
WHEN TO USE STEP FUNCTIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  AWS Step Functions is a managed saga orchestrator:
    - State machine ASL (Amazon States Language) = workflow definition
    - Built-in retry, catch, parallel, choice, wait
    - Execution history (audit trail)
    - Integrates with Lambda, ECS, SNS, SQS, DynamoDB, etc.
    - Pay per state transition (~$25 per million transitions)

  GOOD FIT:
    - Team is AWS-native
    - Workflow changes monthly, not hourly
    - < 1000 concurrent saga executions typical
    - Need visual execution graph in console
    - Compliance wants AWS-managed audit logs

  LIMITATIONS:
    - 25,000 event history entries per execution (long sagas need ContinueAsNew)
    - 1 year max execution duration (Express: 5 min)
    - ASL in JSON is painful for complex branching
    - Testing locally requires mocking or SAM
    - High transition volume → cost at scale (millions of bookings/day)


WHEN TO BUILD CUSTOM ORCHESTRATOR:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Custom orchestrator = your service + saga log DB + command dispatch

  Architecture:
    ┌──────────────────┐
    │ SagaOrchestrator │  (ECS/Fargate, 3 AZ)
    │  - poll saga_log │
    │  - dispatch cmds │
    │  - handle events │
    └────────┬─────────┘
             │
    ┌────────┼────────┬─────────────┐
    ▼        ▼        ▼             ▼
  DynamoDB  SQS per   EventBridge   PostgreSQL
  saga_log  service   (responses)   (optional read model)

  GOOD FIT:
    - > 10k sagas/minute (Step Functions cost)
    - Complex dynamic branching (ML-driven routing)
    - Need sub-100ms orchestration latency
    - Existing workflow engine expertise (Temporal, Cadence)
    - Multi-cloud requirement

  COST OF CUSTOM:
    - YOU own HA, scaling, deployment, bug fixes
    - YOU implement retry, timeout, compensation routing
    - YOU build the operations UI (or use Temporal Web UI)
    - On-call owns orchestrator outages


DECISION MATRIX:
━━━━━━━━━━━━━━━━

  ┌────────────────────────────┬───────────────┬─────────────────┐
  │ Factor                     │ Step Functions│ Custom          │
  ├────────────────────────────┼───────────────┼─────────────────┤
  │ Time to first saga         │ Days          │ Weeks-months    │
  │ Ops burden                 │ Low           │ High            │
  │ Cost at 1M sagas/month     │ ~$low hundreds│ Infra + eng     │
  │ Cost at 100M sagas/month   │ Significant   │ May be cheaper  │
  │ Debuggability              │ Console+CLI   │ Build dashboards│
  │ Max execution length       │ 1 year        │ Unlimited*      │
  │ Vendor lock-in             │ AWS           │ Portable logic  │
  └────────────────────────────┴───────────────┴─────────────────┘
  *Temporal/Cadence provide durable execution with open-source option
```

```
STEP FUNCTIONS — TRIP BOOKING STATE MACHINE (ASL excerpt):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  {
    "Comment": "Trip booking saga",
    "StartAt": "ReserveFlight",
    "States": {
      "ReserveFlight": {
        "Type": "Task",
        "Resource": "arn:aws:lambda:us-east-1:123456789012:function:reserve-flight",
        "TimeoutSeconds": 20,
        "Retry": [{
          "ErrorEquals": ["Lambda.ServiceException", "Lambda.TooManyRequestsException"],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2
        }],
        "Catch": [{
          "ErrorEquals": ["InsufficientSeats", "FlightUnavailable"],
          "Next": "BookingFailed"
        }, {
          "ErrorEquals": ["States.Timeout"],
          "Next": "ReconcileFlight"
        }, {
          "ErrorEquals": ["States.ALL"],
          "Next": "BookingFailed"
        }],
        "Next": "ReserveHotel"
      },
      "ReconcileFlight": {
        "Type": "Task",
        "Resource": "arn:aws:lambda:us-east-1:123456789012:function:reconcile-flight",
        "Next": "ReserveHotel"
      },
      "ReserveHotel": {
        "Type": "Task",
        "Resource": "arn:aws:lambda:us-east-1:123456789012:function:reserve-hotel",
        "TimeoutSeconds": 20,
        "Catch": [{
          "ErrorEquals": ["States.ALL"],
          "Next": "CompensateFlight"
        }],
        "Next": "ReserveCar"
      },
      "ReserveCar": {
        "Type": "Task",
        "Resource": "arn:aws:lambda:us-east-1:123456789012:function:reserve-car",
        "TimeoutSeconds": 15,
        "Catch": [{
          "ErrorEquals": ["States.ALL"],
          "Next": "CompensateHotel"
        }],
        "Next": "ChargePayment"
      },
      "ChargePayment": {
        "Type": "Task",
        "Resource": "arn:aws:lambda:us-east-1:123456789012:function:charge-payment",
        "TimeoutSeconds": 60,
        "Parameters": {
          "sagaId.$": "$.sagaId",
          "idempotencyKey.$": "States.Format('{}:CHARGE_PAYMENT', $.sagaId)",
          "amount.$": "$.totalAmount"
        },
        "Catch": [{
          "ErrorEquals": ["States.ALL"],
          "Next": "CompensateCar"
        }],
        "Next": "BookingComplete"
      },
      "CompensateCar": {
        "Type": "Task",
        "Resource": "arn:aws:lambda:us-east-1:123456789012:function:cancel-car",
        "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "CompensationFailed" }],
        "Next": "CompensateHotel"
      },
      "CompensateHotel": {
        "Type": "Task",
        "Resource": "arn:aws:lambda:us-east-1:123456789012:function:cancel-hotel",
        "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "CompensationFailed" }],
        "Next": "CompensateFlight"
      },
      "CompensateFlight": {
        "Type": "Task",
        "Resource": "arn:aws:lambda:us-east-1:123456789012:function:cancel-flight",
        "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "CompensationFailed" }],
        "Next": "BookingFailed"
      },
      "BookingComplete": {
        "Type": "Succeed"
      },
      "BookingFailed": {
        "Type": "Task",
        "Resource": "arn:aws:lambda:us-east-1:123456789012:function:notify-booking-failed",
        "End": true
      },
      "CompensationFailed": {
        "Type": "Task",
        "Resource": "arn:aws:lambda:us-east-1:123456789012:function:escalate-compensation-failure",
        "End": true
      }
    }
  }

  DEPLOY:
  aws stepfunctions create-state-machine \
    --name TripBookingSaga \
    --definition file://trip-booking-saga.asl.json \
    --role-arn arn:aws:iam::123456789012:role/StepFunctionsTripBookingRole

  START EXECUTION:
  aws stepfunctions start-execution \
    --state-machine-arn arn:aws:states:us-east-1:123456789012:stateMachine:TripBookingSaga \
    --name trip_8f3a2b \
    --input '{
      "sagaId": "trip_8f3a2b",
      "userId": "usr_12",
      "totalAmount": 84700,
      "flight": {"flightId": "UA-442", "seat": "12A"},
      "hotel": {"hotelId": "marriott-sfo", "roomType": "king"},
      "car": {"vendor": "hertz", "class": "economy"}
    }'

  INSPECT STUCK EXECUTION:
  aws stepfunctions describe-execution \
    --execution-arn arn:aws:states:us-east-1:123456789012:execution:TripBookingSaga:trip_8f3a2b

  aws stepfunctions get-execution-history \
    --execution-arn arn:aws:states:us-east-1:123456789012:execution:TripBookingSaga:trip_8f3a2b \
    --max-results 100
```

### Kafka-Based Saga

```
KAFKA SAGA = CHOREOGRAPHY + SAGA LOG TOPIC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Most Kafka sagas are choreographed: each service consumes
  events and publishes the next. The "saga log" is either:
    (a) a dedicated compacted topic saga-events, or
    (b) inferred from multiple domain topics (hard to debug)

  RECOMMENDED TOPOLOGY (travel booking):

  Topics:
    trip.commands          (orchestrator → services, keyed by sagaId)
    trip.events            (services → orchestrator, keyed by sagaId)
    trip.saga-state        (compacted, materialized state — optional)

  Partition key: sagaId (trip_8f3a2b)
  → All events for one saga land in one partition → ordering per saga

  PRODUCER CONFIG (command dispatch):
    acks=all
    enable.idempotence=true
    max.in.flight.requests.per.connection=5
    retries=2147483647

  CONSUMER CONFIG (saga workers):
    isolation.level=read_committed   (if using transactions)
    enable.auto.commit=false
    max.poll.interval.ms=300000      (5 min for slow hotel API)

  EVENT ENVELOPE (every message):
    {
      "sagaId": "trip_8f3a2b",
      "sagaType": "TRIP_BOOKING",
      "step": "RESERVE_HOTEL",
      "direction": "FORWARD",
      "idempotencyKey": "trip_8f3a2b:RESERVE_HOTEL",
      "correlationId": "trace-abc123",
      "timestamp": "2026-07-06T14:22:45Z",
      "payload": { "hotelId": "marriott-sfo", ... }
    }

  ORCHESTRATED KAFKA SAGA (hybrid — often better):

    ┌─────────────┐     trip.commands      ┌─────────────┐
    │ Orchestrator│───────────────────────►│ FlightSvc   │
    │             │◄───────────────────────│             │
    │  (reads     │     trip.events        └─────────────┘
    │   saga log  │
    │   in Dynamo)│     trip.commands      ┌─────────────┐
    │             │───────────────────────►│ HotelSvc    │
    └─────────────┘◄───────────────────────│             │
                                           └─────────────┘

    Orchestrator is the only writer to trip.commands.
    Services only execute commands and emit trip.events.
    State lives in DynamoDB saga log, not inferred from Kafka.

  CREATE TOPICS (MSK):

  kafka-topics.sh --create \
    --topic trip.commands \
    --partitions 24 \
    --replication-factor 3 \
    --config min.insync.replicas=2 \
    --config retention.ms=604800000

  kafka-topics.sh --create \
    --topic trip.events \
    --partitions 24 \
    --replication-factor 3 \
    --config min.insync.replicas=2 \
    --config retention.ms=2592000000

  MONITORING:
    kafka-consumer-groups.sh --bootstrap-server $BROKERS \
      --describe --group trip-orchestrator

    Alert: lag on trip.commands > 1000 for 5 min
```

---

## Concrete Examples

### Example 1: Travel Booking Domain Model

```
TRIP BOOKING — THE CANONICAL SAGA EXAMPLE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Business: TravelCo — package deals (flight + hotel + car)

  Services:
    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
    │ FlightSvc   │  │ HotelSvc    │  │ CarSvc      │  │ PaymentSvc  │
    │ RDS Postgres│  │ RDS Postgres│  │ RDS Postgres│  │ Stripe API  │
    └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘

  Forward saga steps:
    T1: ReserveFlight   → holds seat, 24h expiry, confirmation FL-*
    T2: ReserveHotel    → holds room, free cancel until check-in - 48h
    T3: ReserveCar      → holds vehicle at airport
    T4: ChargePayment   → Stripe PaymentIntent capture
    T5: ConfirmBooking  → write trip record, send confirmation email

  Compensations (reverse order on failure after payment):
    C4: RefundPayment
    C3: CancelCar
    C2: CancelHotel
    C1: CancelFlight

  Pricing example (trip_8f3a2b):
    Flight:  $412.00
    Hotel:   $289.00 (2 nights)
    Car:     $96.00  (3 days)
    Tax:     $50.00
    Total:   $847.00  (stored as 84700 cents)

  FLIGHTSVC — reservation table:
    CREATE TABLE flight_reservations (
      id              UUID PRIMARY KEY,
      saga_id         VARCHAR(64) NOT NULL,
      idempotency_key VARCHAR(128) NOT NULL UNIQUE,
      flight_id       VARCHAR(32) NOT NULL,
      seat            VARCHAR(8),
      status          VARCHAR(20) NOT NULL,
      expires_at      TIMESTAMPTZ,
      created_at      TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX idx_flight_res_saga ON flight_reservations(saga_id);
```

### Example 2: Payment Idempotency with Stripe

```
CHARGE_PAYMENT LAMBDA — PRODUCTION PATTERN:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  def handler(event, context):
      saga_id = event['sagaId']
      idempotency_key = f"{saga_id}:CHARGE_PAYMENT"
      amount_cents = event['totalAmount']

      cached = idempotency_table.get(idempotency_key)
      if cached and cached['status'] == 'COMPLETED':
          return cached['result']

      intent = stripe.PaymentIntent.create(
          amount=amount_cents,
          currency='usd',
          metadata={'sagaId': saga_id},
          idempotency_key=idempotency_key,
          confirm=True,
          payment_method=event['paymentMethodId']
      )

      if intent.status != 'succeeded':
          raise PaymentPending(intent.status)

      result = {'paymentIntentId': intent.id, 'chargedAmount': amount_cents}
      idempotency_table.complete(idempotency_key, result)
      return result

  REFUND (compensation):
      stripe.Refund.create(
          payment_intent=event['paymentIntentId'],
          idempotency_key=f"{saga_id}:REFUND_PAYMENT"
      )

  TIMEOUT SCENARIO:
    Lambda times out after Stripe succeeded.
    Reconciliation: stripe.PaymentIntent.list(metadata={'sagaId': saga_id})
    If succeeded → mark step COMPLETED, do NOT refund.
```

### Example 3: Saga Watchdog (Reconciliation Cron)

```
ECS SCHEDULED TASK — EVERY 60 SECONDS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Query — stuck IN_PROGRESS:
    SELECT saga_id, current_step, updated_at
    FROM saga_instances
    WHERE status = 'IN_PROGRESS'
      AND updated_at < now() - interval '10 minutes'

  Query — UNKNOWN steps:
    SELECT saga_id, step_name, idempotency_key
    FROM saga_step_log
    WHERE status IN ('TIMEOUT', 'UNKNOWN')
      AND started_at < now() - interval '2 minutes'

  For each UNKNOWN step RESERVE_HOTEL:
    response = hotel_svc.get_reservation(saga_id=saga_id)
    if response.found:
      mark_step_completed(saga_id, 'RESERVE_HOTEL', response)
      resume_saga(saga_id)
    elif started_at < now() - interval '15 minutes':
      mark_step_failed(saga_id, 'RESERVE_HOTEL')
      trigger_compensation(saga_id)

  DYNAMODB SCAN:
    aws dynamodb scan \
      --table-name saga_instances \
      --filter-expression "#s = :inprog AND updatedAt < :cutoff" \
      --expression-attribute-names '{"#s":"status"}' \
      --expression-attribute-values '{
        ":inprog":{"S":"IN_PROGRESS"},
        ":cutoff":{"S":"2026-07-06T14:00:00Z"}
      }'
```

---

## Production Patterns

### Pattern 1: Orchestrator + Saga Log + Outbox

```
THE PRODUCTION TRINITY:
━━━━━━━━━━━━━━━━━━━━━━━

  1. Saga orchestrator (Step Functions or custom) owns workflow
  2. Saga log (DynamoDB) owns state
  3. Outbox (per service) guarantees event delivery

  FlightSvc reserve flow:
    BEGIN TXN
      INSERT flight_reservations ...
      INSERT outbox_events (event_type=FlightReserved, saga_id=...)
    COMMIT

    Outbox relay polls outbox → publishes to trip.events
    Orchestrator consumes FlightReserved → dispatches ReserveHotel

  Without outbox: DB commit succeeds, crash before Kafka publish →
  saga stuck forever. Watchdog must reconcile.
```

### Pattern 2: Compensation Priority Queue

```
WHEN COMPENSATIONS MUST RUN FAST:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Payment captured, hotel cancel fails.
  User charged $847, hotel room still held.

  Separate SQS FIFO: trip-compensate-urgent
    MessageGroupId = sagaId
    Dedicated compensation workers

  SQS CONFIG:
    aws sqs create-queue \
      --queue-name trip-compensate-urgent.fifo \
      --attributes '{
        "FifoQueue": "true",
        "ContentBasedDeduplication": "true",
        "VisibilityTimeout": "120",
        "MessageRetentionPeriod": "1209600",
        "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:123:trip-compensate-dlq.fifo\",\"maxReceiveCount\":\"5\"}"
      }'

  Metric: saga_compensation_lag_seconds p99 < 30
```

### Pattern 3: Human-in-the-Loop Compensation

```
NON-REFUNDABLE FLIGHT + SYSTEM ERROR:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Saga enters: AWAITING_MANUAL_COMPENSATION
  Step Functions Task token pattern:
    → Lambda creates support ticket with saga context
    → Returns task token (execution waits)
    → Agent waives fee in internal tool
    → SendTaskSuccess resumes compensation chain

  aws stepfunctions send-task-success \
    --task-token "$TOKEN" \
    --output '{"flightCancelled": true, "feeWaived": true}'
```

### Pattern 4: Async API with Sync UX Cap

```
TRIP BOOKING SLA:
━━━━━━━━━━━━━━━━

  POST /trips → 202 Accepted { sagaId, statusUrl }
  GET /trips/{sagaId}/status → polls saga log

  UI spinner: max 90 seconds
  Backend saga: up to 15 minutes (payment retries)

  If 90s and still IN_PROGRESS:
    "We're confirming with partners. Email within 10 min."

  If 15 min:
    Watchdog marks FAILED or escalates
    Verify payment status BEFORE telling user "not charged"
```

### Pattern 5: Temporal as Custom Orchestrator

```
TEMPORAL WORKFLOW (Go excerpt — trip booking):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  func TripBookingSaga(ctx workflow.Context, input TripInput) error {
      ao := workflow.ActivityOptions{
          StartToCloseTimeout: 30 * time.Second,
          RetryPolicy: &temporal.RetryPolicy{
              MaximumAttempts: 3,
          },
      }
      ctx = workflow.WithActivityOptions(ctx, ao)

      var flightResult FlightResult
      err := workflow.ExecuteActivity(ctx, ReserveFlight, input).Get(ctx, &flightResult)
      if err != nil {
          return err  // no compensation needed yet
      }

      var hotelResult HotelResult
      err = workflow.ExecuteActivity(ctx, ReserveHotel, input).Get(ctx, &hotelResult)
      if err != nil {
          workflow.ExecuteActivity(ctx, CancelFlight, flightResult)
          return err
      }

      var carResult CarResult
      err = workflow.ExecuteActivity(ctx, ReserveCar, input).Get(ctx, &carResult)
      if err != nil {
          workflow.ExecuteActivity(ctx, CancelHotel, hotelResult)
          workflow.ExecuteActivity(ctx, CancelFlight, flightResult)
          return err
      }

      var paymentResult PaymentResult
      err = workflow.ExecuteActivity(ctx, ChargePayment, input).Get(ctx, &paymentResult)
      if err != nil {
          workflow.ExecuteActivity(ctx, CancelCar, carResult)
          workflow.ExecuteActivity(ctx, CancelHotel, hotelResult)
          workflow.ExecuteActivity(ctx, CancelFlight, flightResult)
          return err
      }

      return workflow.ExecuteActivity(ctx, ConfirmBooking, input).Get(ctx, nil)
  }

  WHY TEMPORAL OVER RAW CUSTOM:
    - Durable timers (saga timeout without cron)
    - Automatic activity retry with policies
    - Web UI: tctl workflow show -w trip_8f3a2b
    - Versioning for workflow changes
```

### Pattern 6: DynamoDB Saga Log with GSI

```
TABLE DESIGN:
━━━━━━━━━━━━━

  saga_instances (base table):
    PK: sagaId
    GSI1: status-updatedAt-index
      PK: status
      SK: updatedAt
    → Query all IN_PROGRESS sagas older than 10 min

  aws dynamodb create-table \
    --table-name saga_instances \
    --attribute-definitions \
      AttributeName=sagaId,AttributeType=S \
      AttributeName=status,AttributeType=S \
      AttributeName=updatedAt,AttributeType=S \
    --key-schema AttributeName=sagaId,KeyType=HASH \
    --global-secondary-indexes '[
      {
        "IndexName": "status-updatedAt-index",
        "KeySchema": [
          {"AttributeName": "status", "KeyType": "HASH"},
          {"AttributeName": "updatedAt", "KeyType": "RANGE"}
        ],
        "Projection": {"ProjectionType": "ALL"},
        "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
      }
    ]' \
    --billing-mode PAY_PER_REQUEST

  QUERY STUCK SAGAS:
    aws dynamodb query \
      --table-name saga_instances \
      --index-name status-updatedAt-index \
      --key-condition-expression "#s = :status AND updatedAt < :cutoff" \
      --expression-attribute-names '{"#s":"status"}' \
      --expression-attribute-values '{
        ":status":{"S":"IN_PROGRESS"},
        ":cutoff":{"S":"2026-07-06T14:00:00Z"}
      }'
```

---

## Failure Modes

### Failure 1: Phantom Charge (Timeout After Success)

```
SCENARIO:
━━━━━━━━━

  ChargePayment Lambda calls Stripe at t=0.
  Stripe captures $847 at t=2s.
  Lambda OOMs at t=3s before returning.
  Step Functions marks ChargePayment FAILED (timeout).
  Catch block runs CompensateCar → CompensateHotel → CompensateFlight.
  User has NO booking but WAS charged $847.

HOW TO DETECT:
  → Stripe dashboard shows succeeded PaymentIntent
  → Step Functions history shows ChargePayment → Failed → Compensate*
  → saga_step_log: CHARGE_PAYMENT status=TIMEOUT
  → User support: "I was charged but no confirmation email"

ROOT CAUSE:
  Treated timeout as definite failure.
  Compensation ran without checking payment status.

FIX:
  1. ReconcileFlight/ReconcilePayment step on timeout (query Stripe)
  2. Never refund unless charge confirmed OR duplicate charge detected
  3. Idempotency key on charge prevents double-charge on retry
  4. saga_step_log status=UNKNOWN until reconciliation completes

PREVENTION CHECKLIST:
  □ Every payment step has reconciliation handler
  □ Compensation for payment requires paymentIntentId confirmed
  □ Alert: Stripe charge without matching saga COMPLETED within 5 min
```

### Failure 2: Double Compensation

```
SCENARIO:
━━━━━━━━━

  Car reservation fails. Orchestrator sends CancelHotel.
  HotelSvc cancels successfully.
  SQS redelivers CancelHotel (visibility timeout too short).
  HotelSvc cancels again → API returns 404 "already cancelled."
  Handler throws exception → message goes to DLQ.
  Orchestrator retries entire compensation chain.
  RefundPayment runs twice → double refund to customer.

HOW TO DETECT:
  → Stripe: two Refunds for same PaymentIntent
  → saga_step_log: two COMPENSATE entries for CANCEL_HOTEL
  → DLQ depth spike on trip-compensate-hotel queue
  → Finance: refund total exceeds charge total for sagaId

ROOT CAUSE:
  Compensation not idempotent OR
  saga_step_log not checked before executing compensation

FIX:
  CancelHotel handler:
    if reservation.status == CANCELLED:
      return success  # idempotent no-op
    else:
      cancel and update status

  Orchestrator:
    before dispatch compensation, check saga_step_log for
    step COMPENSATED already → skip

PREVENTION:
  □ Compensations return 200 on "already done"
  □ saga_step_log append-only with COMPENSATED terminal state
  □ Refund idempotency key: {sagaId}:REFUND_PAYMENT (not per-attempt)
```

### Failure 3: Stuck Saga (Zombie)

```
SCENARIO:
━━━━━━━━━

  ReserveHotel completes. Orchestrator crashes before logging COMPLETED.
  On restart, orchestrator thinks hotel step is IN_PROGRESS.
  No new commands dispatched. Saga frozen 6 hours.
  Flight hold expires. Hotel hold still active. User confused.

HOW TO DETECT:
  → saga_instances updatedAt stale > 10 min, status=IN_PROGRESS
  → Step Functions execution RUNNING with no recent history events
  → trip.commands consumer lag = 0 (nothing to process)
  → User: booking spinner forever / status endpoint returns IN_PROGRESS

ROOT CAUSE:
  State not persisted atomically with external effect OR
  orchestrator crash between side effect and state update

FIX (watchdog):
  1. Find stale IN_PROGRESS sagas
  2. For currentStep, query external service by sagaId
  3. If external confirms success → advance saga
  4. If external confirms failure → compensate
  5. If ambiguous → alert human

  resume_saga(saga_id):
    aws stepfunctions start-execution \
      --state-machine-arn ...:stateMachine:TripBookingSagaResume \
      --input "{\"sagaId\": \"$saga_id\", \"resumeFrom\": \"$(current_step)\"}"
```

### Failure 4: Choreography Compensation Loop

```
SCENARIO:
━━━━━━━━━

  EventBridge choreography for trip booking.
  CarSvc publishes CarReservationFailed.
  HotelSvc compensates, publishes HotelCancelled.
  FlightSvc compensates, publishes FlightCancelled.
  Bug: FlightCancelled handler in HotelSvc also listens
  (copy-paste error) → tries to cancel hotel again.
  Publishes HotelCancelFailed → triggers escalation storm.

HOW TO DETECT:
  → EventBridge invocations 10× normal on hotel-cancel-handler
  → CloudWatch Logs: "reservation not found" loop
  → Multiple compensation events for same sagaId within seconds

ROOT CAUSE:
  Event subscriptions too broad; no saga state guard

FIX:
  Every compensation handler:
    1. Load saga state from saga log
    2. If step already COMPENSATED → return (no event publish)
    3. Only publish downstream compensation event if this step
       was actually COMPLETED in forward path

PREVENTION:
  □ Prefer orchestration for compensation paths
  □ If choreography: strict event schema + saga log guard
  □ Integration test: inject failure at each step, assert
    exactly one compensation event per service
```

### Failure 5: Partial Compensation After Payment

```
SCENARIO:
━━━━━━━━━

  Full forward path succeeds. Payment captured.
  ConfirmBooking fails (email service down — irrelevant).
  Bad orchestrator: treats ConfirmBooking as pivotal → runs full
  compensation including RefundPayment.
  User refunded but holds flight+hotel+car still active.
  TravelCo loses $847 + inventory locked.

HOW TO DETECT:
  → Refund without user request
  → Active reservations in Flight/Hotel/Car DB for FAILED saga
  → saga status FAILED but compensation steps mixed

ROOT CAUSE:
  Non-pivotal step (notification) classified as pivotal

FIX:
  Step classification:
    PIVOTAL: inventory + payment
    NON-PIVOTAL: email, analytics, loyalty points

  ConfirmBooking failure:
    retry 5× → if still fails, mark saga COMPLETED_WITH_WARNINGS
    do NOT compensate inventory

PREVENTION:
  □ Document pivotal vs non-pivotal per step in ASL comments
  □ Alert on compensation after saga was COMPLETED forward path
```

### Failure 6: Ordering Violation in Kafka Choreography

```
SCENARIO:
━━━━━━━━━

  PaymentSvc and HotelSvc both consume from trip.events.
  PaymentSvc processes CarReserved (partition 3) fast.
  HotelSvc still processing FlightReserved (same saga, replay lag).
  Payment charges card before hotel reserved.
  Hotel then fails (no rooms) → must refund.

HOW TO DETECT:
  → saga_step_log timestamps: CHARGE before RESERVE_HOTEL complete
  → PaymentCaptured event offset < HotelReserved offset (same saga)
  → Increased refund rate correlated with hotel availability

ROOT CAUSE:
  Choreography without strict step sequencing;
  or events on different topics/partitions

FIX:
  Orchestration: sequential steps only
  OR choreography: each service only listens to immediate predecessor event
  PaymentSvc listens to CarReserved, NOT FlightReserved

PREVENTION:
  □ Sequence diagram matches event subscription list
  □ Integration test with artificial consumer lag
```

### Failure 7: Saga Log Split Brain

```
SCENARIO:
━━━━━━━━━

  DynamoDB global table for saga_instances (active-active).
  Orchestrator in us-east-1 and eu-west-1 both process same sagaId
  (duplicate start-execution call from retried API request).
  Both dispatch ReserveFlight with same idempotency key (good).
  Both try to update saga status to RESERVE_HOTEL (bad).
  Last writer wins → one orchestrator's state lost.

HOW TO DETECT:
  → Two Step Functions executions with same sagaId name
  → Conflicting currentStep in saga log over time
  → FlightSvc logs show duplicate reserve attempts (second idempotent)

ROOT CAUSE:
  saga start not idempotent at orchestrator level

FIX:
  start_saga:
    conditional put sagaId (attribute_not_exists)
    if fails → return existing saga state (don't start new execution)

  Step Functions:
    --name trip_8f3a2b  (execution name = sagaId, unique per state machine)
    Duplicate start returns ExecutionAlreadyExists
```

---

## SRE Diagnostic Toolkit

```
SAGA DEBUGGING — STEP FUNCTIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Get execution status
aws stepfunctions describe-execution \
  --execution-arn arn:aws:states:us-east-1:123:execution:TripBookingSaga:trip_8f3a2b \
  --query '{status:status,startDate:startDate,stopDate:stopDate,error:error,cause:cause}'

# Full event history (find exact failure state)
aws stepfunctions get-execution-history \
  --execution-arn arn:aws:states:us-east-1:123:execution:TripBookingSaga:trip_8f3a2b \
  --reverse-order \
  --max-results 20

# List RUNNING executions (stuck sagas)
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:123:stateMachine:TripBookingSaga \
  --status-filter RUNNING \
  --max-results 50

# CloudWatch Logs (Lambda behind each step)
aws logs filter-log-events \
  --log-group-name /aws/lambda/charge-payment \
  --filter-pattern "trip_8f3a2b" \
  --start-time $(date -d '1 hour ago' +%s000)

# X-Ray trace by sagaId (if correlationId in metadata)
aws xray get-trace-summaries \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --filter-expression 'annotation.sagaId = "trip_8f3a2b"'


SAGA LOG QUERIES (DynamoDB):
━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Get saga instance
aws dynamodb get-item \
  --table-name saga_instances \
  --key '{"sagaId":{"S":"trip_8f3a2b"}}'

# Get all steps for saga
aws dynamodb query \
  --table-name saga_step_log \
  --key-condition-expression "sagaId = :sid" \
  --expression-attribute-values '{":sid":{"S":"trip_8f3a2b"}}'

# Count sagas by status (CloudWatch metric from scheduled Lambda)
# Custom metric: SagaCount by status dimensions


PAYMENT RECONCILIATION (Stripe CLI):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Find charges for saga
stripe payment_intents list \
  --limit 10 \
  --query "data[?metadata.sagaId=='trip_8f3a2b']"

# Check refunds
stripe refunds list \
  --payment-intent pi_3abc123

# Verify idempotency
stripe payment_intents create \
  -d amount=84700 \
  -d currency=usd \
  -d "metadata[sagaId]=trip_8f3a2b" \
  -H "Idempotency-Key: trip_8f3a2b:CHARGE_PAYMENT"
# Second call returns same pi_, no double charge


KAFKA SAGA DIAGNOSTICS:
━━━━━━━━━━━━━━━━━━━━━━━

# Consumer lag on orchestrator group
kafka-consumer-groups.sh --bootstrap-server $BROKERS \
  --describe --group trip-orchestrator

# Find all events for saga (consume with filter — dev only)
kafka-console-consumer.sh --bootstrap-server $BROKERS \
  --topic trip.events \
  --from-beginning \
  --property print.key=true \
  | grep trip_8f3a2b

# DLQ depth
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/123/trip-commands-flight-dlq \
  --attribute-names ApproximateNumberOfMessages


RESERVATION LOOKUP (per service):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# FlightSvc
curl -s "https://flight.internal/reservations?sagaId=trip_8f3a2b" \
  -H "Authorization: Bearer $INTERNAL_TOKEN" | jq .

# HotelSvc
curl -s "https://hotel.internal/api/v1/holds/by-saga/trip_8f3a2b" | jq .

# Expected fields: status, confirmationCode, idempotencyKey


METRICS TO DASHBOARD (minimum):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  saga_started_total                    (counter, by sagaType)
  saga_completed_total                  (counter, by status: COMPLETED/FAILED)
  saga_duration_seconds                 (histogram, by sagaType)
  saga_stuck_count                      (gauge, status=IN_PROGRESS AND age>10m)
  saga_compensation_total               (counter, by step)
  saga_compensation_failed_total        (counter — page on > 0)
  saga_step_unknown_total               (counter, by step — timeout/reconcile)
  payment_charge_without_complete_total (counter — CRITICAL alert)

  ALERT RULES (Prometheus/CloudWatch):
    saga_stuck_count > 5 for 10m           → P2
    saga_compensation_failed_total > 0     → P1
    payment_charge_without_complete > 0    → P1 (money)
    saga_duration_seconds p99 > 300        → P3


COMMON "WHY IS THIS SAGA STUCK?" FLOWCHART:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. describe-execution → RUNNING? FAILED? 
  2. get-execution-history → which state last?
  3. saga_step_log → last step status?
  4. If TIMEOUT/UNKNOWN → query external service by sagaId
  5. If Lambda error → CloudWatch logs for that step
  6. If waiting → Task token? Heartbeat? External API down?
  7. Check DLQ for command queue of stuck step
  8. If all else fails → manual compensation runbook
```

---

## Decision Framework

```
WHICH SAGA STYLE?
━━━━━━━━━━━━━━━━

  ┌────────────────────────────┬──────────────┬──────────────┬─────────────┐
  │ Requirement                │ Choreography │ Orchestration│ Hybrid      │
  ├────────────────────────────┼──────────────┼──────────────┼─────────────┤
  │ Money movement             │ Avoid        │ Preferred    │ Orch. core  │
  │ 2-3 services               │ OK           │ OK           │ Either      │
  │ > 5 services               │ Avoid        │ Preferred    │ Orch. core  │
  │ Audit / compliance         │ Hard         │ Preferred    │ Orch. + log │
  │ High throughput (>10k/min) │ Kafka chor.  │ Custom/Temp  │ Kafka+orch  │
  │ Team knows only Lambda     │ EventBridge  │ Step Func    │ Step Func   │
  │ Debug "where stuck?"       │ Poor         │ Good         │ Good        │
  └────────────────────────────┴──────────────┴──────────────┴─────────────┘

ORCHESTRATOR CHOICE:
━━━━━━━━━━━━━━━━━━

  ┌────────────────────────────┬─────────────────┬─────────────────┐
  │ Factor                     │ Step Functions  │ Temporal/Custom │
  ├────────────────────────────┼─────────────────┼─────────────────┤
  │ AWS-only, < 1M sagas/mo    │ ✓ Start here    │ Overkill        │
  │ Multi-cloud                │ ✗               │ ✓               │
  │ > 10M sagas/month          │ Cost review     │ ✓               │
  │ Complex human-in-loop      │ Task tokens OK  │ ✓ Native        │
  │ Long-running (days)        │ Standard 1yr    │ ✓ Temporal      │
  │ Team has Go/Java workflow  │ ASL learning    │ ✓ Leverage      │
  └────────────────────────────┴─────────────────┴─────────────────┘

MESSAGING CHOICE FOR SAGA COMMANDS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Step Functions + Lambda sync invoke     → simplest, no extra bus
  Step Functions + SQS (async worker)       → backpressure, DLQ
  Custom orchestrator + Kafka               → highest throughput
  Custom orchestrator + SQS FIFO            → per-saga ordering, AWS-native
  EventBridge choreography                  → low volume, many subscribers

WHEN NOT TO USE SAGAS:
━━━━━━━━━━━━━━━━━━━━

  → Single database, single service — use local ACID transaction
  → Strong consistency required across reads — consider 2PC or redesign
  → Compensation is impossible (sent physical goods, sent email to wrong person
    without follow-up) — redesign workflow or use saga only until commit point
  → "We'll figure out compensation later" — you won't, and prod will teach you
```

---

## Ops Sim: Northstar Refund Saga Compensation Loop

**Time box:** 50 minutes  
**Severity:** P1  
**Service / domain:** Refund orchestrator, payment gateway, ledger, shipment cancellation  
**Northstar system:** Northstar Commerce

### How to run it

1. Answer from memory of the Saga Pattern teaching section; do not re-read mid-drill.
2. Write decisions in order: T+0, T+5, T+15, T+30, T+60, and follow-up.
3. Tie every claim to a metric, log line, trace, query output, or config key from this packet.
4. Name the correctness invariant before proposing scale, failover, replay, or data repair.
5. Do not open the answer key until your response is written.

---

### Scenario packet

```text
WHAT USERS SEE:
  - Refunds flip from complete to pending in customer UI.
  - Warehouse cancellations succeed after some refunds are already ambiguous.
  - Support sees several ledger adjustments per refund request.
  - Restocked inventory is unavailable for VIP sellers.

WHAT ON-CALL SEES:
  - Compensating saga states spike after retry policy rollout.
  - Gateway success callbacks arrive late, not never.
  - Ledger duplicate suppression stays at zero.
  - Inventory release occurs before payment terminal state.

BUSINESS CONSTRAINT:
  Do not refund twice, claw back a valid refund, or release inventory tied to a shipment; customer status may remain pending.
```

### Causal chain

Gateway timeouts are treated as hard refund failures. Compensation starts before payment reaches a terminal state, and ledger idempotency is scoped to saga attempt instead of refund id.

Break it into these forces before answering:
- trigger: the release/config/data shape that started the failure
- amplifier: retry, cache, routing, projection, or observability behavior that widened it
- scarce resource: the metric that reaches a limit first
- invariant: what must remain conservative even while users see degraded experience
- repair boundary: the source of truth and operation id used after mitigation

### Change suspects

- The suspicious production lever is `refund.timeout_ms: 3000`; tie it to the first bad minute before changing capacity.
- The dashboard that stayed calm does not expose `refund_saga_state{state="COMPENSATING"}` for the damaged slice.
- The runbook move closest to "treat timeout as failed" needs an explicit no-go decision on the bridge.
- The repair path is allowed only after the source-of-truth query and operation key are written down.

### Telemetry and inspection notes

```text
METRICS:
  - refund_saga_state{state="COMPENSATING"}: 2% -> 41%
  - payment_refund_request_duration_seconds{p99}: 1.2 -> 8.8
  - payment_refund_timeout_total: +12600/15m
  - payment_refund_late_success_callback_total: +7100
  - ledger_duplicate_adjustment_suppressed_total: 0
  - inventory_release_before_refund_terminal_total: +2840
  - customer_refund_status_flip_total: +9300
  - orchestrator_retry_rate: 4k/min

LOG LINES:
  - refund-orchestrator: timeout treated as REFUND_FAILED refund_id=rf_8844 attempt=7
  - payment-webhook: refund succeeded refund_id=rf_8844 after 11s
  - ledger: posted adjustment operation_id=rf_8844-attempt-8
  - inventory: released units before payment terminal state refund_id=rf_8844
  - shipment: cancel accepted after pick_ticket_printed=true

TRACE / QUERY / INSPECTION NOTES:
  - Saga trace is timeout, compensation branch, late success, then another compensation.
  - Ledger unique key is operation_id, not refund_id.
  - Gateway hard-failure rate is lower than timeout rate.
  - State machine has no PENDING_EXTERNAL state.
```

### Config fragment

```yaml
refund.timeout_ms: 3000
refund.retry.backoff: fixed_2s
refund.timeout_treated_as: FAILED
ledger.idempotency_key: saga_attempt_id
compensate_on_refund_timeout: true
saga.max_compensation_attempts: unlimited
```

### Incident clock

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | Refund status flips page while gateway is slow. | Classify timeout as UNKNOWN. |
| T+5 | Team wants faster polling and disabled webhooks. | Keep resolving signals alive. |
| T+15 | Duplicate ledger adjustments confirmed. | Freeze compensation branches. |
| T+30 | Late-success feed is complete. | Reconcile by refund id. |
| T+60 | Shipment state is mixed. | Separate warehouse repair. |
| T+24h | Product asks for faster refunds. | Design saga terminal states. |

### Mitigation handles

- Roll back or disable the specific dangerous config from the packet.
- Shed decorative, derived, notification, or analytics work before weakening source-of-truth correctness.
- Throttle retry/replay using the narrowest downstream capacity limit.
- Keep an affected-record ledger before customer-visible repair.
- Verify recovery with the sliced SLI plus the scarce-resource metric, not a fleet average.

### Bad fix review

For each proposal, name the concrete failure mode it creates.

- treat timeout as failed
- disable gateway webhooks
- retry faster against the gateway
- edit ledger rows manually without audit

### Written response prompts

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

### After-action scoring

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

**Answer key:** [answers/Week-06-Architecture-Patterns/Saga Pattern Answers.md](../answers/Week-06-Architecture-Patterns/Saga%20Pattern%20Answers.md)

