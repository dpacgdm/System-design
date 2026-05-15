# Week 6, Topic 4: Saga Pattern

Last verified: 2026-05-15

A saga is a way to coordinate a business workflow across multiple services when there is no single database transaction covering the whole workflow.

It is not rollback magic. It is explicit forward recovery and compensation.

Classic database transaction:

```text
BEGIN
  reserve inventory
  capture payment
  create shipment
COMMIT
```

Microservice workflow:

```text
Orders service      owns order state
Inventory service   owns stock reservation
Payment service     owns payment authorization/capture
Shipping service    owns shipment creation
```

No single local transaction can safely cover all four services. The saga pattern makes the workflow explicit.

---

## 1. Learning objectives

```text
After this topic, you should be able to:

1. Explain why local ACID transactions do not solve multi-service workflows.
2. Compare orchestration and choreography sagas.
3. Design compensating actions and understand their limits.
4. Model saga state, timeouts, retries, and idempotency keys.
5. Diagnose stuck, duplicated, partially completed, and over-compensated sagas.
6. Explain why sagas provide eventual consistency, not isolation.
7. Handle ambiguous external side effects such as payment timeouts.
```

---

## 2. What people get wrong

### Wrong model 1: compensation is rollback

Rollback restores database state before commit. Compensation is a new business action that attempts to undo or offset a previous action.

```text
Rollback:
  undo uncommitted database changes

Compensation:
  create a new business action that reverses meaning
```

Example:

```text
ReserveInventory -> ReleaseInventory
CapturePayment   -> RefundPayment
CreateShipment   -> CancelShipment if not shipped
```

Some actions cannot truly be undone.

```text
email sent
package delivered
payment settled
external webhook fired
```

For those, the system needs correction, reconciliation, and customer support processes.

### Wrong model 2: saga means no consistency problem

Sagas trade immediate atomic consistency for recoverable eventual consistency.

During the workflow, users or services may see intermediate states.

```text
Order status:        PAYMENT_PENDING
Inventory status:    RESERVED
Payment status:      UNKNOWN
Shipment status:     NOT_CREATED
```

That is not a bug by itself. It becomes a bug when the product pretends the state is final.

### Wrong model 3: retry fixes timeout

A timeout means the caller did not receive an answer. It does not prove the action failed.

```text
Payment request sent
Provider times out

Possibilities:
  payment failed
  payment succeeded but response was lost
  payment is still pending
```

Retrying without an idempotency key can double-charge.

---

## 3. Basic saga flow

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

If payment fails after inventory reservation:

```text
CapturePay failed
       |
       v
+----------------+
| ReleaseInv     |
+----------------+
       |
       v
+----------------+
| CancelOrder    |
+----------------+
```

The compensation sequence is part of the business design, not an afterthought.

---

## 4. Orchestration saga

One coordinator owns the workflow state.

```text
+----------------+
| Saga Manager   |
+----------------+
   |       |       |
   v       v       v
Orders  Inventory Payment
```

Flow:

```text
1. Saga manager creates saga instance.
2. Sends ReserveInventory command.
3. Waits for InventoryReserved or InventoryFailed.
4. Sends CapturePayment command.
5. Waits for PaymentCaptured or PaymentFailed.
6. Sends CreateShipment command.
7. Completes saga or compensates.
```

Strengths:

```text
clear workflow state
central timeout policy
easier incident debugging
explicit compensation order
```

Weaknesses:

```text
coordinator becomes critical
workflow logic centralizes
can become business-process monolith
```

Good fit:

```text
checkout
loan approval
travel booking
subscription provisioning
any long-running workflow with explicit states
```

---

## 5. Choreography saga

Services react to events without a central coordinator.

```text
+--------+   OrderCreated   +-----------+
| Orders | ---------------> | Inventory |
+--------+                  +-----------+
                                  |
                                  | InventoryReserved
                                  v
                              +---------+
                              | Payment |
                              +---------+
                                  |
                                  | PaymentCaptured
                                  v
                              +----------+
                              | Shipping |
                              +----------+
```

Strengths:

```text
loose central control
services stay autonomous
natural event flow
```

Weaknesses:

```text
workflow is hard to see
cycles are easy
ownership can blur
failure handling is scattered
```

Bad smell:

```text
To understand checkout, you must read six repos and three Slack threads.
```

---

## 6. Saga state model

A saga should have explicit states.

```text
ORDER_CREATED
INVENTORY_RESERVING
INVENTORY_RESERVED
PAYMENT_CAPTURING
PAYMENT_CAPTURED
SHIPMENT_CREATING
COMPLETED
COMPENSATING
COMPENSATED
FAILED_REQUIRES_MANUAL_REVIEW
```

State table shape:

```text
saga_id
order_id
current_state
last_successful_step
next_step
attempt_count
last_error
idempotency_key
created_at
updated_at
deadline_at
```

Why this matters:

```text
If state is not explicit, recovery becomes log archaeology.
```

---

## 7. Idempotency

Every saga command should have an idempotency key.

```text
ReserveInventory(order_id=ord_123, idempotency_key=inv_ord_123_v1)
CapturePayment(order_id=ord_123, idempotency_key=pay_ord_123_v1)
CreateShipment(order_id=ord_123, idempotency_key=ship_ord_123_v1)
```

Consumer behavior:

```text
If idempotency key was already processed:
  return prior result
else:
  perform action and store result
```

This protects against duplicate events, retries, and coordinator crashes.

---

## 8. Isolation anomalies

Sagas do not provide serializable isolation across services.

Example:

```text
T1: Order A reserves last item.
T2: Order B sees stale availability and also tries to reserve.
T3: One order later fails.
```

Mitigation options:

```text
local transaction inside inventory service
reservation expiration
optimistic version checks
single writer per aggregate
explicit pending states
user-visible state wording
```

Do not pretend intermediate states are final.

---

## 9. Production failure patterns

### Failure 1: timeout ambiguity in payment

Shape:

```text
+---------+      +---------+      +----------+
| Saga    | ---> | Payment | ---> | Provider |
+---------+      +---------+      +----------+
                         timeout
```

The payment provider may have succeeded.

Mitigation:

```text
1. Do not blindly retry without idempotency key.
2. Query provider by idempotency key or transaction reference.
3. Move saga to PAYMENT_UNKNOWN.
4. Reconcile asynchronously.
5. Complete or compensate after truth is known.
```

### Failure 2: compensation fails

```text
Payment failed
ReleaseInventory command sent
Inventory service unavailable
```

Mitigation:

```text
keep saga in COMPENSATING
retry with backoff
alert on compensation age
manual review queue
protect compensation paths as critical
```

### Failure 3: duplicate command

```text
CapturePayment sent twice
```

Mitigation:

```text
idempotency key at payment service
unique transaction reference
provider idempotency support
ledger unique constraint
```

### Failure 4: choreography cycle

```text
OrderUpdated -> InventoryUpdated -> OrderUpdated -> InventoryUpdated
```

Mitigation:

```text
clear event taxonomy
causation IDs
cycle detection in architecture review
bounded consumer side effects
```

### Failure 5: stuck saga

Symptoms:

```text
many sagas in PAYMENT_PENDING
state age exceeds SLA
no completion or compensation events
customers see pending orders
```

Mitigation:

```text
timeout scanner
state-machine dashboard
per-state age alerts
manual repair tooling
```

---

## 10. SRE diagnostic toolkit

Useful queries:

```sql
SELECT current_state, count(*)
FROM sagas
GROUP BY current_state
ORDER BY count(*) DESC;
```

```sql
SELECT saga_id, order_id, current_state, last_error, updated_at
FROM sagas
WHERE updated_at < now() - interval '15 minutes'
  AND current_state NOT IN ('COMPLETED', 'COMPENSATED')
ORDER BY updated_at ASC
LIMIT 50;
```

Track:

```text
saga completion rate
saga age by state
compensation rate
manual review queue length
idempotency conflict count
external provider timeout rate
reconciliation mismatch count
```

Trace fields:

```text
saga_id
order_id
idempotency_key
correlation_id
causation_id
external_reference
```

---

## 11. Decision framework

```text
+--------------------------------+-----------------------------+
| Workflow property              | Preferred pattern           |
+--------------------------------+-----------------------------+
| simple local data change       | local transaction           |
| multi-service visible workflow | orchestration saga          |
| independent reactions          | choreography                |
| high audit requirement         | explicit state machine      |
| external payment/shipping      | idempotency + reconciliation|
| cannot tolerate intermediate state | avoid async split or add lock |
+--------------------------------+-----------------------------+
```

Use a saga only when the business can tolerate intermediate states and recovery logic is explicit.

---

## 12. Incident scenario: charged but no order confirmation

Architecture:

```text
+--------+      +------------+      +-----------+
| Client | ---> | Order Saga | ---> | Inventory |
+--------+      +------------+      +-----------+
                      |
                      v
                 +---------+
                 | Payment |
                 +---------+
                      |
                      v
                 +----------+
                 | Shipping |
                 +----------+
```

Symptoms:

```text
orders stuck in PAYMENT_UNKNOWN: 18,400
payment provider timeout rate: 22%
inventory reservations active: 18,100
customer complaints: charged but no confirmation
retry count on CapturePayment: high
```

Recent change:

```text
payment client timeout lowered from 10s to 2s
provider p95 during sale is 3.5s
client retries capture without stable idempotency key
```

Expert diagnosis:

```text
The saga treats timeout as failure, but provider may still capture payment. The
retry path lacks stable idempotency, so duplicate charge risk exists. Inventory
is held while payment truth is unknown.
```

Mitigation:

```text
1. Stop unsafe payment retries.
2. Move affected sagas to PAYMENT_RECONCILING.
3. Query provider by order/payment references.
4. Confirm orders with successful captures.
5. Release inventory for failed captures.
6. Refund duplicate captures.
7. Restore timeout budget and stable idempotency keys.
```

Long-term:

```text
payment idempotency contract
provider reconciliation worker
saga state dashboard
manual review tooling
compensation age alert
load-test provider latency during sale
```

---

## 13. Key takeaways

```text
1. A saga is explicit workflow recovery, not rollback magic.
2. Compensation is a business action and may fail.
3. Timeouts are ambiguous until reconciled.
4. Idempotency keys are mandatory for retries and external side effects.
5. Orchestration gives visibility; choreography gives autonomy.
6. Sagas provide eventual consistency, not isolation.
7. Every saga needs state, deadlines, retries, and repair tooling.
```
