# Week 6, Topic 4: Saga Pattern

Last verified: 2026-05-15

A saga coordinates a business transaction across services without using one global database transaction.

## Learning objectives

```text
1. Explain why distributed transactions are avoided in many microservice systems.
2. Compare choreography and orchestration.
3. Design compensating actions.
4. Diagnose stuck, duplicated, and partially completed sagas.
```

## Core model

```text
+-------------+
| CreateOrder |
+-------------+
       |
       v
+-------------+
| ReserveInv  |
+-------------+
       |
       v
+-------------+
| CapturePay  |
+-------------+
       |
       v
+-------------+
| ShipOrder   |
+-------------+
```

If a later step fails, previous steps may need compensation.

```text
CapturePay fails
  -> ReleaseInventory
  -> CancelOrder
```

## Choreography

```text
+-------+     OrderCreated     +-----------+
| Order | -------------------> | Inventory |
+-------+                      +-----------+
                                      |
                                      | InventoryReserved
                                      v
                                  +---------+
                                  | Payment |
                                  +---------+
```

Pros:

```text
less central coordinator
natural event flow
services stay autonomous
```

Cons:

```text
hard to see full workflow
cycles are easy
failure handling is scattered
```

## Orchestration

```text
+-------------+
| Saga Manager|
+-------------+
   |     |     |
   v     v     v
Order Inventory Payment
```

Pros:

```text
clear workflow state
central timeout and retry policy
easier incident diagnosis
```

Cons:

```text
coordinator becomes critical
workflow logic centralizes
```

## Failure modes

```text
Compensation fails:
  inventory release fails after payment failure.

Duplicate event:
  payment captured twice without idempotency key.

Timeout ambiguity:
  provider timed out, but action may have succeeded.

Isolation anomaly:
  users observe intermediate state.
```

## Diagnostics

```text
Track:
  - saga_id
  - current_step
  - previous_step
  - compensation_attempts
  - timeout_count
  - idempotency_key
  - external_provider_reference
```

## Scenario

Payment provider times out after inventory is reserved. Some customers are charged, but orders are marked pending.

Expert answer:

```text
Do not blindly retry capture without idempotency. Query provider by idempotency
key or transaction reference. Reconcile payment state, then either confirm order
or compensate inventory. Add explicit saga states and timeout recovery workers.
```

## Key takeaways

```text
1. Sagas trade atomicity for recoverable workflow state.
2. Compensation is business logic, not rollback magic.
3. Timeouts are ambiguous until reconciled.
4. Idempotency keys are mandatory for external side effects.
5. Orchestration improves visibility; choreography improves autonomy.
```
