# Answer Key — Design Payment System

> Open only after attempting the learner file questions.

## Expert Analysis


### Question 1: Causal Chain

```
ROOT CAUSE:
  RC1: v3.8.2 Stripe client timeout 25s → 5s while Stripe p99 = 6.1s
  RC2: ReconcileAuth removed/disabled — timeout always → compensate path

AMPLIFIERS:
  A1: User message derives from saga status, not ledger/PSP truth
  A2: Retry creates new order_id + new idempotency_key → double auth
  A3: Void script without capture-state check → wrongful void attempts

IMMEDIATE STOP:
  1. Rollback payment-api to v3.8.1 (ALB weighted routing 100% previous TG)
  2. Enable feature flag reconcile_auth_mandatory=true (kill switch)
  3. Disable void_failed_sagas_cron job
  4. Status page: "Checkout degraded — do not retry payment if charged"
```

### Question 2: order_7712 Remediation

```bash
# 1. Verify Stripe truth
stripe payment_intents retrieve pi_8xx
# expect: status=requires_capture, amount=18900

# 2. Check ledger
psql -c "SELECT * FROM journal_entries WHERE reference_id='pi_8xx';"

# 3. Inventory — reservation released; decide hold or honor
# If stock available: re-reserve for customer; else offer substitute

# 4. If fulfilling: capture (customer intended to buy)
stripe payment_intents capture pi_8xx
# Post ledger CAPTURE entry idempotency_key=manual:order_7712

# 5. Create order record (backfill) linked to pi_8xx
# Update saga status COMPLETED_WITH_REMEDIATION (audit)

# 6. Void pi for duplicate order_7713 if user does not want two orders

# 7. Customer message ONLY after Stripe + ledger agree:
# "We experienced a technical issue. Your payment of $189.00 is confirmed.
#  Order #7712 is processing."
```

### Question 3: Stop Bleeding

```
Rollback v3.8.1 — 5 min via ECS blue/green
Stripe read timeout: restore 25000ms
Step Functions: set AuthorizePayment HeartbeatSeconds=60
Circuit breaker: if stripe_error_rate > 10% for 2 min → open 30s
Rate limit checkout: 5 attempts per user per 10 min (WAF rule)
```

### Question 4: Detection

```
Alert: stripe_p99_latency > 4s for 10 min AND authorize_timeout_rate > 5%
Severity: P2 (page payment on-call)
Panel: overlay Stripe dashboard latency vs our timeout config line (5s)

Synthetic canary: every 1 min create $0.50 test PI in staging mirror prod timeout
```

### Question 5: Long-Term

```
- Reconcile step CANNOT be feature-flagged off in prod (config guard)
- Timeout must be > PSP p99.99 + network (auto from metric)
- User payment status = f(ledger, PSP) not saga alone
- Retry UX: same idempotency_key for same cart_id
- Void script: require human approval + SQL join captures
- Post-deploy: soak test 30 min at 2x traffic before full promotion
```

---

---

## Design Gates (mandatory) - Model Responses

These responses are intentionally gate-shaped rather than a second full design.
Use them to verify the design explicitly covers trust, abuse, tenancy, cost,
and blast radius.

### Gate 1 - Authn/z trust boundary

- State every principal: external user, internal service, admin/support actor,
  background worker, tenant, and third-party partner where applicable.
- Put the first trust boundary at the public edge or private service ingress,
  then name the enforcement point that owns object/action authorization.
- Accept only scoped identity artifacts with issuer, audience, expiry, and
  key/certificate validation. Service-to-service calls should use workload
  identity or mTLS, not ambient network trust.
- Fail closed for money, privacy, admin, and write paths. Degrade or serve
  cached public content only where policy explicitly allows it.

### Gate 2 - Abuse and misuse

- Identify the highest-amplification actor in `Design Payment System`: the one that can turn
  one request into many writes, fetches, fan-outs, model calls, or downstream
  retries.
- Use layered quotas: user/API key, tenant/tier, entity key, endpoint/job
  class, region/cell, and global safety cap.
- Distinguish organic flash traffic from abuse with per-key skew, user-agent
  or principal entropy, retry rate, error mix, and historical baselines.
- Bound retries with budgets, jitter, circuit breakers, and idempotency keys.

### Gate 3 - Multi-tenant isolation

- Name the tenancy model for every stateful plane: relational data, cache,
  queue/topic, object storage, search index, model/vector store, metrics, logs,
  and support exports.
- Tenant context must be explicit in APIs, async messages, cache keys, search
  filters, audit logs, and support tooling. Missing tenant context fails closed.
- Reserve or quota shared scarce resources: DB connections, Kafka partitions
  and bytes, cache memory/ops, worker concurrency, indexing bandwidth, and
  third-party API calls.
- Prove isolation with cross-tenant cache/search/export tests, route-map tests,
  and incident kill switches for one tenant or cell.

### Gate 4 - Unit cost at target scale

- Define one business unit and compute order-of-magnitude cost at target scale
  and at peak multiplier. Include idle headroom and replication, not only
  request CPU.
- Dominant line items usually include storage retention, egress/cross-AZ or
  cross-region transfer, observability ingest, model/API calls, NAT, cache
  memory, and replay/rebuild capacity.
- Page on cost per successful business unit and slope by feature/deploy/tenant,
  not only monthly spend after the fact.
- Preferred degradation cuts optional analytics, freshness, ranking depth,
  export concurrency, or non-critical replicas before correctness-critical
  writes and reads.

### Gate 5 - Failure blast radius

- Declare the intended blast-radius boundary: partition, shard, tenant, topic,
  cell, region, queue, worker pool, cache namespace, or model version.
- Separate critical and non-critical paths so analytics, exports, replay,
  recommendation/ranking, or support tooling cannot starve checkout, payment,
  auth, or core serving.
- Document runbook hazards: global cache flush, raising max connections,
  disabling auth, removing rate limits, replaying without throttle, or widening
  a feature flag globally.
- Game day the highest-risk boundary and verify alerts fire before customer or
  tenant-wide impact.
