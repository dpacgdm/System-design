# Week 6, Topic 2: Event-Driven Architecture

Last verified: 2026-05-15

Event-driven architecture means systems communicate by publishing facts that happened, not by forcing every downstream action into the request path.

## Learning objectives

```text
1. Distinguish events, commands, queries, messages, and CDC records.
2. Decide when async boundaries help and when they hide correctness bugs.
3. Explain choreography, orchestration, event-carried state transfer, and event sourcing.
4. Diagnose lag, duplicate handling, schema drift, and replay failures.
```

## Core model

```text
+---------+      +---------+      +-------------+
| Orders  | ---> | Events  | ---> | Consumers   |
+---------+      +---------+      +-------------+
     |                               |   |   |
     |                               v   v   v
     |                            Email Search Analytics
     v
Authoritative DB
```

An event is a durable business fact:

```text
OrderPlaced
PaymentCaptured
InventoryReserved
ShipmentDispatched
```

A command asks something to happen:

```text
ReserveInventory
CapturePayment
SendEmail
```

Queries ask for current state and should not mutate state.

## Design rules

```text
- Events are named in past tense.
- Events need stable IDs, timestamps, schema versions, and correlation IDs.
- Consumers must be idempotent.
- Replay must not duplicate external effects.
- Critical correctness paths need explicit consistency policy.
```

## Failure modes

```text
Consumer lag:
  business process delayed even though APIs look healthy.

Duplicate event:
  same event delivered twice; unsafe consumer double-charges or double-emails.

Schema drift:
  producer changes payload; old consumers fail or silently misread.

Ghost consumer:
  abandoned consumer group still processes old events.

Event storm:
  one business action emits many low-value events and melts downstream systems.
```

## Diagnostics

```text
Check:
  - event publish rate
  - consumer lag by group
  - DLQ growth
  - duplicate-event rate
  - schema-version error rate
  - end-to-end business latency
```

## Scenario

```text
Checkout writes orders successfully, but customers do not receive confirmation.
Order API p95 is normal. Email service is healthy. Kafka lag for email-consumer
is 9M records. Search indexing is also behind.
```

Expert diagnosis:

```text
The user-facing write path is healthy, but async side effects are delayed.
Classify impact separately: order authority is safe; notification freshness is
broken. Protect critical consumers, pause non-critical ones, verify downstream
throughput, and communicate delayed confirmation clearly.
```

## Key takeaways

```text
1. Events are facts, not remote procedure calls in disguise.
2. Async improves isolation but introduces lag and replay complexity.
3. Idempotency is not optional.
4. Schema compatibility is an operational requirement.
5. Business latency must include async completion, not only API latency.
```
