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
