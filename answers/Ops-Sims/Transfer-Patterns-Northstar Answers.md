# Answer Key - Transfer Patterns Northstar

> Open only after attempting the transfer drill.

## Q1 - Problem inventory

Expected mechanisms: saga timeout mismatch, unbounded compensation retry storm, payment unknown requiring reconciliation, outbox backlog, Kafka rebalance loop (`p99 420s` > `max.poll.interval` 300s), poison message on one partition/tenant, weak in-memory idempotency, JWKS stampede from low TTL and no negative cache, dangerous `alg=none`, cardinality explosion from `refund_id`/exception labels, excessive trace/log volume, shared worker-pool tenant starvation, shared DLQ leak risk, and retry-driven NAT/egress cost.

## Q2 - Correctness first

Pause or rate-limit new instant refunds where payment status cannot be proven. Keep idempotency checks on. Fail closed on duplicate or unknown provider state. Separate user acknowledgement from backend completion: return accepted/pending with reconciliation rather than retrying money movement aggressively.

## Q3 - Saga repair

For `PAYMENT_UNKNOWN`, query provider by idempotency key/charge reference before compensating. Move stuck sagas into a reconciliation state with bounded retries and exponential backoff with jitter. Preserve saga log as source of audit truth. Compensation should be idempotent and sequenced by state transitions, not ad hoc retries.

## Q4 - Kafka/outbox repair

A 420s processing p99 exceeds the 300s max poll interval, causing consumers to be considered dead and triggering rebalances. Poison seller-redwood messages should be quarantined to a tenant-scoped DLQ after bounded attempts, preserving order strategy for unaffected keys. Use cooperative rebalancing, increase poll interval only with processing fixes, and scale partitions after key review.

## Q5 - Auth repair

Increase JWKS cache TTL to a sane value with single-flight refresh and negative caching for unknown `kid`. Keep old and new keys during overlap; do not delete old key early. Enforce algorithm allowlist (`RS256` etc.) and remove `none`. Pin issuer/audience and avoid logging tokens.

## Q6 - Observability repair

Immediately remove unbounded labels (`refund_id`, `exception_message`, never JWT/user secrets), reduce trace sample rate with tail/error sampling, redact token claims, and cap log volume. Keep low-cardinality safety signals: tenant tier, status, saga state, provider, error class, and backlog age.

## Q7 - Tenant isolation

Introduce per-tenant concurrency caps/reservations and tenant-scoped queues/DLQs. Quarantine seller-redwood poison messages with full audit trail. Reserve worker capacity for other tenants and enforce fair-share scheduling so one enterprise tenant cannot consume 510/600 workers.

## Q8 - Cost response

Worker capture: 510/600 = 85%, leaving 90 workers for everyone else. Metrics ingest multiplier: 14M/1.8M = 7.8x. NAT extra data is 9TB/day. Retry storms to payment provider and 100% tracing/logging drive cost. Degrade high-cardinality telemetry and noncritical traces, not audit logs or money-safety metrics.

## Q9 - Bad fixes

Turning off idempotency risks duplicate refunds. Faster retries amplify provider outage. Deleting old JWKS breaks valid tokens. Adding user/JWT labels explodes cardinality and leaks secrets. Shared DLQ replay can cross-contaminate tenants and re-poison partitions. 10x workers can overload provider and raise cost. Auth bypass is a security incident. Partition jump without key review may not fix hot keys and complicates ordering.

## Q10 - Verification

Track stuck saga counts by state, duplicate blocked rate, provider p99, compensation retry rate, outbox oldest age, Debezium lag, Kafka rebalance count, consumer lag by partition/tenant, JWKS p99 and fetch rate, auth failure by reason, Prometheus head series/samples, trace/log ingest, worker utilization by tenant, DLQ age, NAT/egress cost, and refund correctness audit mismatches.

## Q11 - Principal operating model

Create a refund platform ownership model with money-movement invariants, provider reconciliation runbooks, idempotency schema reviews, tenant fairness SLOs, DLQ replay approvals, auth rotation rehearsals, telemetry budgets, cost anomaly ownership, and quarterly game days. Finance/risk owns correctness acceptance; platform owns limits and safe degradation; product owns customer messaging for pending refunds.



## Deep recovery sequence

1. **Stop money ambiguity:** pause instant completion where provider state is unknown; keep customer-visible pending state honest.
2. **Bound retries:** replace fixed 1s unlimited compensation with exponential backoff, jitter, max attempts, and reconciliation queue.
3. **Quarantine poison:** move seller-redwood poison messages to tenant-scoped DLQ with payload hash and replay owner.
4. **Stabilize consumers:** fix processing time or poll interval mismatch, then reduce rebalances before scaling consumers.
5. **Fix auth safely:** single-flight JWKS refresh, positive and negative cache, old-key overlap, strict alg allowlist, token redaction.
6. **Reduce telemetry blast:** rollback high-cardinality labels and 100% traces while preserving low-cardinality safety alerts.
7. **Restore fairness:** tenant worker caps and reserved global capacity prevent one tenant from occupying 85% of the pool.
8. **Track cost:** monitor NAT/egress, provider retry traffic, trace/log ingest, and worker spend as first-class incident metrics.

## Audit artifacts to preserve

Keep saga logs, idempotency records, provider request IDs, DLQ entries, JWKS rotation timeline, metric-label deploy diff, tenant worker allocation history, and customer refund status transitions. These are needed for finance reconciliation and post-incident proof that duplicates were prevented.

## Principal model response

### Incident thesis

The refund system is failing as a distributed workflow, not as
a single Kafka or payment-provider problem. The trigger is a
provider/consumer slowdown, but the amplifiers are saga retry
semantics, poison messages, weak idempotency, JWKS stampede,
telemetry cardinality, and shared tenant worker pools. The
money invariant is stronger than the latency objective:

> No refund is duplicated, lost, or marked final without a
> reconciled provider state and an auditable idempotency key.

### T+0 to T+15 sequence

1. Declare P1 for refund correctness and tenant isolation.
2. Assign incident command plus payments, workflow/saga,
   Kafka/outbox, auth, observability, tenant platform,
   finance/risk, support, and product owners.
3. Freeze deploys touching refund workflow, JWKS rotation,
   metric labels, DLQ replay, and worker-pool scaling.
4. Pause instant completion for provider-unknown refunds.
   Return customer-visible pending state instead of retrying
   money movement.
5. Stop unbounded compensation retries; switch to bounded
   exponential backoff with jitter and reconciliation queue.
6. Quarantine the seller-redwood poison message into a
   tenant-scoped DLQ after bounded attempts.
7. Stabilize consumers: stop rebalance loop before scaling.
   A 420s p99 cannot survive a 300s max poll interval.
8. Fix JWKS fetch storm with single-flight, longer TTL,
   negative cache for unknown `kid`, and strict algorithm
   allowlist.
9. Roll back high-cardinality telemetry labels and reduce
   100% tracing while preserving audit and money metrics.
10. Apply tenant worker caps/reservations so one tenant cannot
    occupy 510 of 600 workers.

### Telemetry interpretation

Saga/payment:

- `PAYMENT_UNKNOWN` is not success and not failure; it is a
  reconciliation state.
- Provider request id plus idempotency key must be the join
  key for provider lookup.
- Fixed 1s retries convert uncertainty into load and duplicate
  risk.

Kafka/outbox:

- `p99 420s > max.poll.interval 300s` predicts consumer group
  death and rebalances.
- A poison tenant message should not block other tenants or
  enter a shared DLQ that leaks tenant data.
- Outbox oldest age and Debezium lag measure repair debt.

Auth:

- JWKS low TTL plus no negative cache lets random `kid` values
  become a verifier DoS.
- `alg=none` is a hard security bug, not a performance knob.

Observability/cost:

- `refund_id` and exception-message labels explode series
  cardinality and query cost.
- 14M samples vs 1.8M baseline is a 7.8x ingest multiplier.
- 9TB/day extra NAT egress is an incident cost signal, not a
  monthly finance surprise.

Tenant fairness:

- 510/600 workers is 85% of the pool captured by one tenant,
  leaving only 90 workers for all other tenants.

### Bad-fix physics

- Turning off idempotency makes repeated compensation produce
  duplicate refunds.
- Retrying faster turns provider ambiguity into provider and
  worker saturation.
- Deleting old JWKS early breaks valid tokens already issued.
- Allowing `alg=none` trades availability for account
  takeover risk.
- Adding JWT/user/refund labels leaks secrets and explodes
  cardinality.
- Replaying a shared DLQ can cross-contaminate tenants and
  re-poison partitions.
- Adding 10x workers can overwhelm the provider and multiply
  cost while preserving the poison/rebalance root cause.
- Partition increases without key review may not split the hot
  key and can disrupt ordering guarantees.

### Reconciliation plan

The affected set should be built from:

- saga id, tenant id, refund id, provider idempotency key,
  provider request id, and current saga state;
- outbox event id and Kafka partition/offset;
- DLQ payload hash and bounded replay attempt count;
- customer-visible state transitions.

For each `PAYMENT_UNKNOWN`, query provider by idempotency key.
If provider succeeded, mark saga succeeded and prevent
compensation. If provider failed or not found after provider
SLA, compensate idempotently. If provider is still ambiguous,
remain pending with backoff and owner-visible age.

### T+30 support/product update

Tell customers refunds may remain pending while provider state
is reconciled. Do not promise completion until provider state
is known. For unaffected tenants, say worker isolation has
been applied. For seller-redwood, state that a tenant-specific
queue item is quarantined and will be replayed after validation.
Finance owns final duplicate/lost-refund audit; support should
not improvise manual payments outside policy.

### Durable acceptance gates

- Saga state machine has explicit UNKNOWN and RECONCILING
  states with bounded retry budgets.
- Idempotency is durable and shared across API, saga,
  provider, outbox, replay, and support tooling.
- Poison messages enter tenant-scoped DLQs with payload hashes,
  replay owner, and approval.
- Kafka consumers have poll interval, processing time, and
  cooperative rebalance tests.
- JWKS verifier has TTL, single-flight, negative cache,
  issuer/audience pinning, and algorithm allowlist tests.
- Telemetry budgets reject unbounded labels and secret-bearing
  values.
- Tenant worker pools enforce caps, reservations, and fairness
  alerts.
- Cost dashboards include NAT/egress, provider retries, trace
  ingest, log ingest, and worker spend.
