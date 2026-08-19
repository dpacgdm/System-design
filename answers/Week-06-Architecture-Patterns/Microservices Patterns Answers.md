# Answer Key - Microservices Patterns

> Open only after attempting the learner file questions.

## Ops Sim: Northstar Seller Profile Cascade

> Open only after attempting the learner-side drill.

### Executive diagnosis

A decorative seller-profile call became mandatory in broad GraphQL fanout. Retries from product, checkout, and support saturate a shared Redis cluster used by auth.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `bff_request_duration_seconds{route="product",p99}: 0.21 -> 5.4`
- `checkout_marketplace_latency_seconds{p99}: 0.48 -> 6.8`
- `seller_profile_error_rate: 0.4`
- `seller_profile_qps: 3k -> 48k`
- `upstream_retry_total{dependency="seller-profile"}: +2.8M/10m`
- `redis_connected_clients{cluster="shared-auth-meta"}: 1200 -> 18000`
- Config clue: `graphql.seller_display.nullable: false`
- Config clue: `seller_profile.required_for_checkout: true`
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

- `scale seller-profile 10x first`: feeds the bottleneck or idle side of the system without fixing assignment, retries, or the scarce resource.
- `bypass auth to restore dashboards`: uses a derived view as truth, so it can miss or invent records during repair.
- `return empty compliance-required data`: can create legal/marketplace obligations from fabricated seller state.
- `shut down all marketplace checkout`: improves a visible symptom while weakening the incident invariant or repair boundary.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: seller-profile database/compliance service for seller truth, auth service for tenant decisions.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- route-level dependency classification
- nullable/degradable GraphQL fields
- auth and metadata cache bulkheads
- outlier ejection based on downstream health

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

### Principal model response

The root mechanism is dependency criticality inversion. A
decorative seller-profile call becomes mandatory through
GraphQL and checkout. Retries then concentrate load on
seller-profile and a shared Redis cluster that auth also uses,
turning a profile failure into marketplace checkout risk.

First 15 minutes:

1. Declare P1 for marketplace checkout availability and auth
   cache protection.
2. Assign incident command, BFF/GraphQL owner,
   seller-profile owner, checkout owner, Redis/platform owner,
   auth owner, support, and business owner.
3. Freeze deploys/config that make optional profile fields
   mandatory.
4. Make `seller_display` nullable/degradable again on product
   and checkout paths.
5. Disable or cap retries to seller-profile; add jitter and
   retry budget.
6. Bulkhead Redis/auth from profile metadata traffic or shed
   profile metadata cache use.
7. Preserve compliance-required seller fields; do not invent
   empty values for legal/marketplace obligations.
8. Monitor checkout SLO, auth cache latency, seller-profile
   QPS/error rate, Redis clients, and retry volume.

Telemetry interpretation:

- `seller_profile_error_rate: 0.4` is the trigger.
- `seller_profile_qps: 3k -> 48k` and `retry_total:
  +2.8M/10m` show retries as amplifier.
- `redis_connected_clients: 1200 -> 18000` shows the shared
  scarce resource.
- `graphql.seller_display.nullable: false` and
  `seller_profile.required_for_checkout: true` name the
  contract bug.
- Checkout p99 rising proves optional metadata contaminated a
  critical path.

Capacity math:

- Seller-profile QPS increases 16x from 3k to 48k.
- If 2.8M retries happen in 10 minutes, retries alone add
  about 4,667 requests/sec.
- Redis clients grow 15x. If auth uses that same Redis
  cluster, profile retries can cause auth latency and failure
  even when auth service code is healthy.

Bad fixes:

- Scaling seller-profile 10x can simply feed more Redis
  clients into the shared bottleneck.
- Bypassing auth restores superficial availability by creating
  a security incident.
- Returning empty compliance fields can violate seller/legal
  obligations.
- Shutting down all marketplace checkout ignores that only a
  decorative dependency needs degradation.

Repair:

- Source of truth for seller compliance remains seller-profile
  database or compliance service.
- GraphQL product display can omit or stale-label decorative
  seller metadata.
- Checkout should require only the seller facts actually
  needed for legality/risk.
- Affected customer ledger should track failed checkout
  attempts, route, seller id, profile dependency outcome, and
  idempotency key.

Durable architecture:

- Dependency inventory classifies each field as mandatory,
  decision, display, or decorative.
- GraphQL schema preserves nullable/degradable semantics for
  optional fields.
- Critical auth/cache resources have bulkheads and reserved
  capacity.
- Retries are bounded with budgets and do not cross into
  shared infrastructure blindly.
- Circuit breakers trip on semantic dependency failure, not
  just 5xx.
- Load tests include dependency brownout and retry budgets.

Question-by-question grading notes:

- Q1 should identify optional-to-mandatory dependency coupling.
- Q2 should use seller-profile QPS/error, retries, Redis
  clients, and config clues.
- Q3 should degrade seller display before scaling everything.
- Q4 should reject auth bypass and fabricated compliance data.
- Q5 should compute retry/QPS or shared-client amplification.
- Q6 should define seller truth and checkout idempotency
  repair ledger.
- Q7 should name owners for BFF, profile, checkout, Redis,
  auth, product, and support.

Recovery is complete when:

- checkout p99 and success recover without auth bypass;
- Redis auth latency is isolated from profile metadata;
- seller display can degrade with clear UX;
- compliance-required seller fields are either fresh or
  checkout is held;
- retry volume returns to budget;
- runbook documents which dependencies may fail open, fail
  closed, or degrade.

Minimum learner bar:

- If the answer makes optional metadata mandatory during
  recovery, it fails.
- If it bypasses auth to reduce latency, it creates a security
  incident.
- If it cannot distinguish display seller data from compliance
  seller data, it is unsafe.
- If it ignores shared Redis/auth bulkheads, it misses the
  actual blast-radius path.

Interview-caliber close:

- Name the dependency as decorative, decision, compliance, or
  auth-critical before choosing fail-open/fail-closed.
- State which routes may return partial GraphQL data and which
  must hold checkout.
- Verify recovery by reduced retry volume and protected auth
  cache latency, not seller-profile success alone.

---


---
