# Week-08b Answers

Open only after attempting the retention questions.

## Part 1: Rapid-fire answers

**A01 [W1 DNS]**
- Prompt focus: A Route 53 failover changed the A record but Java clients kept the old DB IP for hours. What cache behavior and JVM setting explain it?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A02 [W1 CDN]**
- Prompt focus: A product page with `Set-Cookie` was cached at the edge and served to multiple users. What headers/cache-key evidence proves personalization leaked?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A03 [W1 HTTP/2]**
- Prompt focus: A gRPC client opens one long-lived HTTP/2 connection through an L4 load balancer and one backend is hot. Explain the mechanism and fix.
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A04 [W1 TCP]**
- Prompt focus: Outbound calls fail with `EADDRNOTAVAIL`, high `TIME_WAIT`, and normal upstream CPU. What resource is exhausted and what application fix is safer than only tuning the kernel?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A05 [W1 WebSocket]**
- Prompt focus: A gateway deploy drops 400k sockets and reconnects arrive in one spike. Name the client-side algorithm and server-side limiter.
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A06 [W2 SQL]**
- Prompt focus: A query with `tenant_id = ? AND created_at > ?` is slow only for one large tenant. Name two planner/index explanations.
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A07 [W2 NoSQL]**
- Prompt focus: A DynamoDB table partitions by `tenant_id`; one enterprise seller consumes 65% of WCU. Why is average table utilization misleading?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A08 [W2 Cache]**
- Prompt focus: A Redis key `product:123` stores tenant-specific price. What namespace invariant is missing?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A09 [W2 LSM]**
- Prompt focus: An LSM store shows p99 write stalls, high L0 files, and compaction pending bytes rising. What bad fix should you reject?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A10 [W2 Storage]**
- Prompt focus: A nightly export scans primary OLTP tables for all tenants. Which isolation and workload-placement rule is violated?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A11 [W3 CAP]**
- Prompt focus: During a network partition, checkout must reject stale payment authorization but seller dashboards can be stale. Which side of CAP/PACELC does each path choose?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A12 [W3 Consistency]**
- Prompt focus: A user sees their newly changed setting, then refreshes and sees the old setting. Which session guarantee failed?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A13 [W3 Quorum]**
- Prompt focus: RF=3, W=1, R=1 is used for cart reads/writes. What anomaly should product explicitly accept?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A14 [W3 Hashing]**
- Prompt focus: A tenant migration uses `hash(id) mod N`; moving from 20 to 24 shards moves most keys. Why, and what ring strategy lowers movement?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A15 [W3 Clocks]**
- Prompt focus: Two auth services disagree whether a JWT is expired by 90 seconds. Which clock and leeway signals do you inspect?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A16 [W4 Replication]**
- Prompt focus: An async replica is used for margin checks and lags 45 seconds. What invariant makes this unacceptable?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A17 [W4 Raft]**
- Prompt focus: A candidate missing a committed log entry requests votes. Why should voters reject it?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A18 [W4 Sharding]**
- Prompt focus: One seller's import opens 500 DB connections and unrelated sellers time out. Which shared resource lacked reservation?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A19 [W4 CDC]**
- Prompt focus: A replication slot retains WAL while Kafka is unhealthy. Which metric pages before disk fills?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A20 [W4 Failover]**
- Prompt focus: An old leader recovers and still accepts writes after failover. Name the prevention mechanism.
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A21 [W5 Indexes]**
- Prompt focus: A composite index `(tenant_id, status, created_at)` is used for `status` without tenant. Why is it not a seek?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A22 [W5 Transactions]**
- Prompt focus: Two admins each read 'one owner remains' and remove themselves. Which isolation anomaly is this?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A23 [W5 Pooling]**
- Prompt focus: PgBouncer queue depth rises while Postgres CPU is 35%. Name two possible bottlenecks.
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A24 [W5 CDC/CQRS]**
- Prompt focus: Search is stale but the OLTP write succeeded. What lag metric proves the read model is behind?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A25 [W5 Hot Query]**
- Prompt focus: A prepared statement has a generic plan that is fine for small tenants and awful for a whale tenant. What mitigation can you use?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A26 [W6 Kafka]**
- Prompt focus: Consumer lag is high for one partition and low for all others. What does this say about key distribution?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A27 [W6 Outbox]**
- Prompt focus: Checkout writes DB then publishes Kafka outside the transaction. What failure window does outbox close?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A28 [W6 Sagas]**
- Prompt focus: A refund saga calls PSP twice after timeout. Which persisted operation key prevents double external effects?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A29 [W6 DLQ]**
- Prompt focus: A poison message blocks a payment partition forever. What retry/DLQ policy preserves ordering without infinite retry?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A30 [W6 Backpressure]**
- Prompt focus: A downstream email service is slow and Kafka lag grows. What is a safe degradation?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A31 [W7 Rate limits]**
- Prompt focus: A shared token bucket lets one tenant consume all burst credits. What limiter hierarchy protects others?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A32 [W7 ID generation]**
- Prompt focus: Kubernetes pods share the same Snowflake worker id. Why do duplicate IDs appear under burst?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A33 [W7 Search]**
- Prompt focus: OpenSearch shard size reaches 110 GB and recovery takes hours. What rollover invariant was missed?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A34 [W7 Feature flags]**
- Prompt focus: A tenant-scoped flag evaluates true globally when context is missing. What default should the evaluator enforce?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A35 [W7 Load balancing]**
- Prompt focus: mTLS handshakes spike on every request after a client change. Which connection reuse/pool signal matters?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A36 [W8 Observability]**
- Prompt focus: Adding raw `tenant_id` to every metric creates millions of series. How do you keep tenant visibility safely?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A37 [W8 SLO]**
- Prompt focus: Availability is 99.95% but enterprise tier promised 99.99%. Which slice matters for the error budget?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A38 [W8 Alerting]**
- Prompt focus: CPU alerts fire during every batch job but users are fine. What user-centric symptom should page instead?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A39 [W8 Geospatial]**
- Prompt focus: Driver location older than 30 seconds remains matchable. What staleness guard is missing?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A40 [W8 Ordering]**
- Prompt focus: Trace spans show event B before event A across services. What does a wall-clock timestamp not prove?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A41 [08b Auth]**
- Prompt focus: A JWT has correct signature and `iss` but `aud=seller-admin` for checkout. What vulnerability appears if accepted?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A42 [08b Auth]**
- Prompt focus: JWKS endpoint returns 429 during key rotation and new tokens fail. Which cache behavior should verifiers have?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A43 [08b Auth]**
- Prompt focus: mTLS fails only checkout-api -> pay-ledger. Name four cert/trust-bundle facts to compare.
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A44 [08b Auth]**
- Prompt focus: A secret rotation promotes `AWSCURRENT`, but PgBouncer new connections fail. Which rotation test path was insufficient?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A45 [08b AuthZ]**
- Prompt focus: Support exports an order by `order_id` without tenant context. Which authorization invariant is missing?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A46 [08b Cost]**
- Prompt focus: Cost/order = allocated service cost divided by successful orders. Why can retries improve revenue but worsen unit cost?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A47 [08b Cost]**
- Prompt focus: NAT gateway bytes jump after analytics deploy. Why might compute scaling be the wrong first fix?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A48 [08b Cost]**
- Prompt focus: Trace sampling is set to 100% during incident and never expires. What control prevents recurrence?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A49 [08b Cost]**
- Prompt focus: A feature scans raw S3 across regions every 30 seconds. Name the hidden line items.
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A50 [08b Capacity]**
- Prompt focus: Average CPU is 22%, but p99 latency is high for one cell. What evidence beats fleet average?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A51 [08b Tenancy]**
- Prompt focus: Shared-table tenancy uses `tenant_id` column. Name three non-table paths that can still leak data.
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A52 [08b Tenancy]**
- Prompt focus: Kafka topic keys only by `tenant_id`; one seller drives 70% of bytes. What fairness flaw exists?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A53 [08b Tenancy]**
- Prompt focus: Redis session cache and leaderboard cache share a cluster. Why is this blast-radius mistake?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A54 [08b Tenancy]**
- Prompt focus: Database-per-enterprise-tenant is proposed for all 50k sellers. What operational cost pushes a mixed model?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A55 [08b Tenancy]**
- Prompt focus: An enterprise tenant gets a dedicated cell. Which routing and rollback controls must exist?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A56 [08b Abuse]**
- Prompt focus: An authenticated seller runs exports every second and starves checkout. Why is auth not enough?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A57 [08b Org]**
- Prompt focus: Security suspects cross-tenant exposure during a P1. Which roles join and what evidence is preserved?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A58 [08b Gates]**
- Prompt focus: A design review omits unit cost at target scale. What number should be forced into the doc?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A59 [08b Gates]**
- Prompt focus: A design review says 'multi-tenant' but omits isolation level. What must be named?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

**A60 [08b Gates]**
- Prompt focus: A design review has retries but no retry budget. What abuse/cost failure can result?
- Expected details: layer, invariant, telemetry, immediate mitigation, and one rejected bad fix.

## Part 2: Scenario answers

### Scenario 1: JWKS rotation storm

Prompt: At 10:00 Cognito begins signing with kid B. At 10:03 checkout 401s spike, JWKS 429s spike, old tokens still work on some pods, and session Redis is normal. Identify layer, first mitigation, rejected fix, and durable acceptance test.

Strong response:
1. Layer: JWT verifier public key cache / JWKS fetch stampede, not session store.
2. First mitigation: Pause key rotation, push local JWKS cache config containing both kid A and kid B public keys.
3. Rejected fix: Disabling signature validation or dropping token audience checks.
4. Acceptance test: Rotation game day causes < 0.5% 401 spike and zero 429 stampede on JWKS endpoint.

### Scenario 2: mTLS partial outage

Prompt: Only checkout-api to pay-ledger returns gRPC UNAVAILABLE after mesh rollout. Sidecars show `unknown authority` in one AZ. Sequence telemetry, mitigation, and rollback.

Strong response:
1. Telemetry: Check SAN/SPIFFE ID mismatch, mesh SDS push version, and root CA trust bundle expiration per AZ.
2. Mitigation: Push missing root CA trust bundle revision to affected AZ sidecars.
3. Rollback: Roll back sidecar SDS mesh revision in affected AZ to previous known-good bundle.

### Scenario 3: Secret rotation pool split

Prompt: Secrets Manager rotates DB password. Existing pooled connections work; new PgBouncer connections fail. Explain the missing rotation verification and safe recovery.

Strong response:
1. Missing verification: Rotation test checked direct DB admin connection instead of testing fresh connections through PgBouncer pooler path.
2. Recovery: Enable dual-password acceptance on database, update PgBouncer user secret, then drain old connection pool.

### Scenario 4: Cross-region analytics cost

Prompt: Seller analytics in eu-west-1 scans raw us-east-1 S3 every 15 seconds. Cross-region bytes rise 7x, NAT cost jumps, dashboards lag, checkout is healthy. Triage cost driver and safe degradation.

Strong response:
1. Triage: Inter-region WAN transfer ($0.09/GB) and NAT processing ($0.045/GB) of uncompressed raw S3 reads.
2. Degradation: Disable standard-tier real-time refresh, switch analytics to regional curated aggregate table, and add S3 VPC Gateway Endpoint.

### Scenario 5: Observability ingest runaway

Prompt: During an incident traces were set to 100% for all tenants and stayed there. Observability cost exceeds checkout compute. Design the control plane guardrail.

Strong response:
1. Control plane guardrail: Enforce automated 60-minute TTL on 100% sampling overrides and add per-team daily ingest byte quotas.

### Scenario 6: Noisy seller import

Prompt: Seller_4812 opens 500 DB connections, spills 800 GB temp, and unrelated checkout calls time out. Identify scarce resources, first limiter, bad fixes, and permanent isolation.

Strong response:
1. Scarce resources: DB connection pool slots and disk I/O / temp tablespace.
2. First limiter: Throttle connection limit for Seller_4812 and terminate queries spilling to disk.
3. Rejected fix: Increasing max_connections globally without pooler isolation.
4. Isolation: Dedicated database read replica / worker node for bulk CSV import workloads.

### Scenario 7: Tenant cache bleed

Prompt: Two sellers share `product:123`; cache returns seller A price to seller B. State impact classification, immediate mitigation, evidence, and tests.

Strong response:
1. Classification: Critical Multi-Tenant Security & Isolation Incident (Data Bleed).
2. Mitigation: Flush `product:123` cache key immediately and deploy fix adding `tenant_id` namespace to cache key prefix.
3. Tests: CI suite asserting all cache keys contain tenant ID namespace.

### Scenario 8: Kafka hot tenant

Prompt: Tenant_id is the Kafka partition key; a celebrity seller drives 70% bytes and broker-9 hits 96% network. Redesign partitioning/fairness.

Strong response:
1. Redesign: Composite partition key (`tenant_id#order_id_hash`) for high-volume tenants to distribute messages across partitions evenly while preserving order per item.

### Scenario 9: Support export exposure

Prompt: A support endpoint exports by order_id without tenant context during an incident. Logs show one request. Sequence security/legal evidence preservation and product mitigation.

Strong response:
1. Preservation: Export audit log trace with caller identity, timestamp, and query parameters to S3 WORM storage for legal review.
2. Product mitigation: Require tenant_id parameter in support export API route and enforce object-level AuthZ policy.

### Scenario 10: Cell migration

Prompt: Move 2 TB enterprise seller data into a dedicated cell while writes continue. List route-map, dual-write, verification, rollback, and blast-radius checks.

Strong response:
1. Sequence: Snapshot ──► CDC Dual-Write ──► Shadow Parity Verification ──► Tenant Router Key Update ──► Old Cell Deprecation.

## Part 3: Decision answers

**Decision 1.** Choose browser session cookie, bearer access token, or both for checkout. Compare replay, revocation, XSS, CSRF, and audit.
- Model answer: Use HttpOnly, SameSite=Strict session cookies for browser state with short-lived access tokens for API requests, pairing instant server-side Redis token revocation for sensitive checkout actions.

**Decision 2.** Choose shared table, schema per tenant, database per tenant, and cell-based tenancy for 50k small sellers plus 40 enterprise auction sellers.
- Model answer: Use shared-table multitenancy with `tenant_id` row-level security (RLS) for 50k small sellers to optimize cost, while deploying isolated database instances and dedicated cells for the 40 enterprise sellers.

**Decision 3.** Choose on-demand, reserved/Savings Plan, spot, or serverless for checkout API, image processing, and unknown analytics.
- Model answer: Baseline compute on 1/3-year Savings Plans for predictable API load, use Spot Instances for batch image processing, and use Serverless with concurrency caps for intermittent analytics.

**Decision 4.** Choose tenant_id metrics, tier/cell metrics, exemplars, logs, or sketches for tenant visibility without cardinality explosion.
- Model answer: Tag high-frequency metrics by `tenant_tier` and `cell`, while attaching `tenant_id` to OpenTelemetry trace exemplars and structured logs for deep single-tenant debugging.

**Decision 5.** Choose primary, sync replica, async replica with lag guard, or cache for margin checks, dashboards, and order history.
- Model answer: Use primary for financial checkout commits, sync replicas for high-value margin validation, async replicas with Max-Lag assertions for seller dashboards, and cached ElastiCache keys for non-sensitive catalog order history.

**Decision 6.** Choose Kafka keying strategy for per-order ordering plus tenant fairness when some tenants are whales.
- Model answer: Key Kafka partitions by composite `tenant_id#order_id_hash` to balance messages evenly across partition workers while preserving strict sequence ordering per order.

**Decision 7.** Choose fail-open, fail-closed, or degraded mode for auth, pricing, seller analytics, and checkout capture.
- Model answer: Fail closed for Auth and Payment Capture (preserve security & money invariants); fail degraded for Seller Analytics (serve cached stale data) and Pricing (serve last-known list price).

**Decision 8.** Choose rate-limit scope: user, tenant, endpoint, job class, cell, and global safety cap for seller exports.
- Model answer: Apply hierarchical token buckets: Tier 1 Endpoint Cost Limit ──► Tier 2 Per-Tenant Export Quota ──► Tier 3 Global Cell Safety Cap to prevent heavy exports from starving API workers.

**Decision 9.** Choose a secret rotation rollout: all-at-once, canary by cell, dual credentials, or maintenance window.
- Model answer: Use a 3-step dual-credential rotation: deploy secondary secret accepted by database ──► update PgBouncer pooler configuration ──► retire primary secret after connection drain window.

**Decision 10.** Choose cost anomaly owner and escalation path when unit cost crosses break-even during a sale.
- Model answer: Incident Command assigns Financial SRE Lead with break-even authority to temporarily shed non-critical background jobs, disable uncompressed cross-region trace streams, and enforce VPC endpoints.

## Part 4: Mini Ops Sim model response

A principal answer separates five tracks rather than searching for one magical root cause.

### 1. Timeline and blast radius
- Freeze deploys except approved mitigations and create a shared timeline from deploy events, auth errors, Kafka lag, Redis evictions, DB connections, and cost tags.
- Evidence: deploy IDs v42/v18, first-bad timestamps, tenant/cell dimensions, and traces with route versions.
- Reject: rolling back every service at once without knowing which rollback touches auth, analytics, or checkout.

### 2. Auth/JWKS
- Layer: token verification/JWKS cache, not session Redis.
- Action: pause rotation, publish a known-good JWKS bundle containing old and new kids, enable single-flight and stale-if-error for public keys, and canary checkout pods by cell.
- Owner: identity platform with checkout and security.
- Reject: disabling signature, issuer, audience, or expiry validation.

### 3. Noisy neighbor
- DB: cap seller_4812 analytics connections and reserve checkout pool.
- Kafka: throttle or isolate hot tenant partition; do not raise producer quota while broker-9 is 96% network.
- Redis: move leaderboard/cache workload away from session Redis or disable that feature for seller_4812; do not flush sessions.
- Owner: seller analytics, DB, Kafka/platform, runtime cache.

### 4. Cost containment
- Root likely seller-analytics raw cross-region scans plus trace ingest, not checkout compute.
- Action: disable standard-tier live analytics, switch to curated regional aggregate, restore sampling with expiry, and verify NAT/egress slope.
- Reject: cutting checkout capacity or scaling OpenSearch before stopping data movement.

### 5. Security/privacy
- Treat tenant_context=null support export as possible P0 until proven otherwise.
- Preserve request logs, authz decisions, DB audit, trace IDs, support approval, response metadata, and route-map versions.
- Include security incident lead, legal/privacy, support owner, service owner, and incident command.
- Reject: deleting logs, rotating evidence away, or reopening debug endpoint without object-level tenant authorization.
