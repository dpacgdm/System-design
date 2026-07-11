# Week-08b Retention Test

Questions only. Attempt without opening answers. This is a spaced mix of Weeks 1-8 plus trust, cost, and multi-tenancy. For every incident question, name the layer, the invariant, a metric, and one bad fix.

## Part 1: Rapid-fire mechanism checks

**Q01 [W1 DNS]**
A Route 53 failover changed the A record but Java clients kept the old DB IP for hours. What cache behavior and JVM setting explain it?

**Q02 [W1 CDN]**
A product page with `Set-Cookie` was cached at the edge and served to multiple users. What headers/cache-key evidence proves personalization leaked?

**Q03 [W1 HTTP/2]**
A gRPC client opens one long-lived HTTP/2 connection through an L4 load balancer and one backend is hot. Explain the mechanism and fix.

**Q04 [W1 TCP]**
Outbound calls fail with `EADDRNOTAVAIL`, high `TIME_WAIT`, and normal upstream CPU. What resource is exhausted and what application fix is safer than only tuning the kernel?

**Q05 [W1 WebSocket]**
A gateway deploy drops 400k sockets and reconnects arrive in one spike. Name the client-side algorithm and server-side limiter.

**Q06 [W2 SQL]**
A query with `tenant_id = ? AND created_at > ?` is slow only for one large tenant. Name two planner/index explanations.

**Q07 [W2 NoSQL]**
A DynamoDB table partitions by `tenant_id`; one enterprise seller consumes 65% of WCU. Why is average table utilization misleading?

**Q08 [W2 Cache]**
A Redis key `product:123` stores tenant-specific price. What namespace invariant is missing?

**Q09 [W2 LSM]**
An LSM store shows p99 write stalls, high L0 files, and compaction pending bytes rising. What bad fix should you reject?

**Q10 [W2 Storage]**
A nightly export scans primary OLTP tables for all tenants. Which isolation and workload-placement rule is violated?

**Q11 [W3 CAP]**
During a network partition, checkout must reject stale payment authorization but seller dashboards can be stale. Which side of CAP/PACELC does each path choose?

**Q12 [W3 Consistency]**
A user sees their newly changed setting, then refreshes and sees the old setting. Which session guarantee failed?

**Q13 [W3 Quorum]**
RF=3, W=1, R=1 is used for cart reads/writes. What anomaly should product explicitly accept?

**Q14 [W3 Hashing]**
A tenant migration uses `hash(id) mod N`; moving from 20 to 24 shards moves most keys. Why, and what ring strategy lowers movement?

**Q15 [W3 Clocks]**
Two auth services disagree whether a JWT is expired by 90 seconds. Which clock and leeway signals do you inspect?

**Q16 [W4 Replication]**
An async replica is used for margin checks and lags 45 seconds. What invariant makes this unacceptable?

**Q17 [W4 Raft]**
A candidate missing a committed log entry requests votes. Why should voters reject it?

**Q18 [W4 Sharding]**
One seller's import opens 500 DB connections and unrelated sellers time out. Which shared resource lacked reservation?

**Q19 [W4 CDC]**
A replication slot retains WAL while Kafka is unhealthy. Which metric pages before disk fills?

**Q20 [W4 Failover]**
An old leader recovers and still accepts writes after failover. Name the prevention mechanism.

**Q21 [W5 Indexes]**
A composite index `(tenant_id, status, created_at)` is used for `status` without tenant. Why is it not a seek?

**Q22 [W5 Transactions]**
Two admins each read 'one owner remains' and remove themselves. Which isolation anomaly is this?

**Q23 [W5 Pooling]**
PgBouncer queue depth rises while Postgres CPU is 35%. Name two possible bottlenecks.

**Q24 [W5 CDC/CQRS]**
Search is stale but the OLTP write succeeded. What lag metric proves the read model is behind?

**Q25 [W5 Hot Query]**
A prepared statement has a generic plan that is fine for small tenants and awful for a whale tenant. What mitigation can you use?

**Q26 [W6 Kafka]**
Consumer lag is high for one partition and low for all others. What does this say about key distribution?

**Q27 [W6 Outbox]**
Checkout writes DB then publishes Kafka outside the transaction. What failure window does outbox close?

**Q28 [W6 Sagas]**
A refund saga calls PSP twice after timeout. Which persisted operation key prevents double external effects?

**Q29 [W6 DLQ]**
A poison message blocks a payment partition forever. What retry/DLQ policy preserves ordering without infinite retry?

**Q30 [W6 Backpressure]**
A downstream email service is slow and Kafka lag grows. What is a safe degradation?

**Q31 [W7 Rate limits]**
A shared token bucket lets one tenant consume all burst credits. What limiter hierarchy protects others?

**Q32 [W7 ID generation]**
Kubernetes pods share the same Snowflake worker id. Why do duplicate IDs appear under burst?

**Q33 [W7 Search]**
OpenSearch shard size reaches 110 GB and recovery takes hours. What rollover invariant was missed?

**Q34 [W7 Feature flags]**
A tenant-scoped flag evaluates true globally when context is missing. What default should the evaluator enforce?

**Q35 [W7 Load balancing]**
mTLS handshakes spike on every request after a client change. Which connection reuse/pool signal matters?

**Q36 [W8 Observability]**
Adding raw `tenant_id` to every metric creates millions of series. How do you keep tenant visibility safely?

**Q37 [W8 SLO]**
Availability is 99.95% but enterprise tier promised 99.99%. Which slice matters for the error budget?

**Q38 [W8 Alerting]**
CPU alerts fire during every batch job but users are fine. What user-centric symptom should page instead?

**Q39 [W8 Geospatial]**
Driver location older than 30 seconds remains matchable. What staleness guard is missing?

**Q40 [W8 Ordering]**
Trace spans show event B before event A across services. What does a wall-clock timestamp not prove?

**Q41 [08b Auth]**
A JWT has correct signature and `iss` but `aud=seller-admin` for checkout. What vulnerability appears if accepted?

**Q42 [08b Auth]**
JWKS endpoint returns 429 during key rotation and new tokens fail. Which cache behavior should verifiers have?

**Q43 [08b Auth]**
mTLS fails only checkout-api -> pay-ledger. Name four cert/trust-bundle facts to compare.

**Q44 [08b Auth]**
A secret rotation promotes `AWSCURRENT`, but PgBouncer new connections fail. Which rotation test path was insufficient?

**Q45 [08b AuthZ]**
Support exports an order by `order_id` without tenant context. Which authorization invariant is missing?

**Q46 [08b Cost]**
Cost/order = allocated service cost divided by successful orders. Why can retries improve revenue but worsen unit cost?

**Q47 [08b Cost]**
NAT gateway bytes jump after analytics deploy. Why might compute scaling be the wrong first fix?

**Q48 [08b Cost]**
Trace sampling is set to 100% during incident and never expires. What control prevents recurrence?

**Q49 [08b Cost]**
A feature scans raw S3 across regions every 30 seconds. Name the hidden line items.

**Q50 [08b Capacity]**
Average CPU is 22%, but p99 latency is high for one cell. What evidence beats fleet average?

**Q51 [08b Tenancy]**
Shared-table tenancy uses `tenant_id` column. Name three non-table paths that can still leak data.

**Q52 [08b Tenancy]**
Kafka topic keys only by `tenant_id`; one seller drives 70% of bytes. What fairness flaw exists?

**Q53 [08b Tenancy]**
Redis session cache and leaderboard cache share a cluster. Why is this blast-radius mistake?

**Q54 [08b Tenancy]**
Database-per-enterprise-tenant is proposed for all 50k sellers. What operational cost pushes a mixed model?

**Q55 [08b Tenancy]**
An enterprise tenant gets a dedicated cell. Which routing and rollback controls must exist?

**Q56 [08b Abuse]**
An authenticated seller runs exports every second and starves checkout. Why is auth not enough?

**Q57 [08b Org]**
Security suspects cross-tenant exposure during a P1. Which roles join and what evidence is preserved?

**Q58 [08b Gates]**
A design review omits unit cost at target scale. What number should be forced into the doc?

**Q59 [08b Gates]**
A design review says 'multi-tenant' but omits isolation level. What must be named?

**Q60 [08b Gates]**
A design review has retries but no retry budget. What abuse/cost failure can result?

## Part 2: Scenario drills

### Scenario 1: JWKS rotation storm

At 10:00 Cognito begins signing with kid B. At 10:03 checkout 401s spike, JWKS 429s spike, old tokens still work on some pods, and session Redis is normal. Identify layer, first mitigation, rejected fix, and durable acceptance test.

Answer prompts:
- Root cause layer and evidence
- First 15-minute mitigation sequence
- Bad fix to reject
- Durable prevention and owner

### Scenario 2: mTLS partial outage

Only checkout-api to pay-ledger returns gRPC UNAVAILABLE after mesh rollout. Sidecars show `unknown authority` in one AZ. Sequence telemetry, mitigation, and rollback.

Answer prompts:
- Root cause layer and evidence
- First 15-minute mitigation sequence
- Bad fix to reject
- Durable prevention and owner

### Scenario 3: Secret rotation pool split

Secrets Manager rotates DB password. Existing pooled connections work; new PgBouncer connections fail. Explain the missing rotation verification and safe recovery.

Answer prompts:
- Root cause layer and evidence
- First 15-minute mitigation sequence
- Bad fix to reject
- Durable prevention and owner

### Scenario 4: Cross-region analytics cost

Seller analytics in eu-west-1 scans raw us-east-1 S3 every 15 seconds. Cross-region bytes rise 7x, NAT cost jumps, dashboards lag, checkout is healthy. Triage cost driver and safe degradation.

Answer prompts:
- Root cause layer and evidence
- First 15-minute mitigation sequence
- Bad fix to reject
- Durable prevention and owner

### Scenario 5: Observability ingest runaway

During an incident traces were set to 100% for all tenants and stayed there. Observability cost exceeds checkout compute. Design the control plane guardrail.

Answer prompts:
- Root cause layer and evidence
- First 15-minute mitigation sequence
- Bad fix to reject
- Durable prevention and owner

### Scenario 6: Noisy seller import

Seller_4812 opens 500 DB connections, spills 800 GB temp, and unrelated checkout calls time out. Identify scarce resources, first limiter, bad fixes, and permanent isolation.

Answer prompts:
- Root cause layer and evidence
- First 15-minute mitigation sequence
- Bad fix to reject
- Durable prevention and owner

### Scenario 7: Tenant cache bleed

Two sellers share `product:123`; cache returns seller A price to seller B. State impact classification, immediate mitigation, evidence, and tests.

Answer prompts:
- Root cause layer and evidence
- First 15-minute mitigation sequence
- Bad fix to reject
- Durable prevention and owner

### Scenario 8: Kafka hot tenant

Tenant_id is the Kafka partition key; a celebrity seller drives 70% bytes and broker-9 hits 96% network. Redesign partitioning/fairness.

Answer prompts:
- Root cause layer and evidence
- First 15-minute mitigation sequence
- Bad fix to reject
- Durable prevention and owner

### Scenario 9: Support export exposure

A support endpoint exports by order_id without tenant context during an incident. Logs show one request. Sequence security/legal evidence preservation and product mitigation.

Answer prompts:
- Root cause layer and evidence
- First 15-minute mitigation sequence
- Bad fix to reject
- Durable prevention and owner

### Scenario 10: Cell migration

Move 2 TB enterprise seller data into a dedicated cell while writes continue. List route-map, dual-write, verification, rollback, and blast-radius checks.

Answer prompts:
- Root cause layer and evidence
- First 15-minute mitigation sequence
- Bad fix to reject
- Durable prevention and owner

## Part 3: Design decision drills

**Decision 1.** Choose browser session cookie, bearer access token, or both for checkout. Compare replay, revocation, XSS, CSRF, and audit.

**Decision 2.** Choose shared table, schema per tenant, database per tenant, and cell-based tenancy for 50k small sellers plus 40 enterprise auction sellers.

**Decision 3.** Choose on-demand, reserved/Savings Plan, spot, or serverless for checkout API, image processing, and unknown analytics.

**Decision 4.** Choose tenant_id metrics, tier/cell metrics, exemplars, logs, or sketches for tenant visibility without cardinality explosion.

**Decision 5.** Choose primary, sync replica, async replica with lag guard, or cache for margin checks, dashboards, and order history.

**Decision 6.** Choose Kafka keying strategy for per-order ordering plus tenant fairness when some tenants are whales.

**Decision 7.** Choose fail-open, fail-closed, or degraded mode for auth, pricing, seller analytics, and checkout capture.

**Decision 8.** Choose rate-limit scope: user, tenant, endpoint, job class, cell, and global safety cap for seller exports.

**Decision 9.** Choose a secret rotation rollout: all-at-once, canary by cell, dual credentials, or maintenance window.

**Decision 10.** Choose cost anomaly owner and escalation path when unit cost crosses break-even during a sale.

## Part 4: Mini Ops Sim - Northstar trust/cost/tenancy pile-up

You are incident commander at T+0 for a flash-sale deploy. Within 20 minutes, these alerts fire:

```
10:00 deploy sale-gateway v42 and seller-analytics v18
10:03 checkout_401_rate 0.2% -> 18%
10:04 jwks_fetch_429_total 0 -> 7k/min; unknown_kid high
10:06 kafka_lag{topic=checkout.events, partition=113} 0 -> 21M
10:07 redis_evicted_keys{cluster=session} 0 -> 22k/min
10:08 cost_per_successful_order $0.18 -> $0.31
10:09 nat_gateway_bytes 120GB/h -> 2.8TB/h
10:10 pg_connections{tenant=seller_4812} 40 -> 640
10:11 support_export tenant_context=null on /internal/orders/debug
10:12 checkout_success_rate 99.7% -> 92.1%
```

Write a response plan with five workstreams:

1. Timeline and blast-radius separation: which symptoms share a cause and which are independent?
2. Auth/JWKS containment: how do you restore availability without weakening token validation?
3. Noisy-neighbor containment: how do you protect checkout from seller analytics, Redis, Kafka, and DB pressure?
4. Cost containment: how do you lower unit cost without cutting revenue-critical capacity?
5. Security/privacy handling: how do you preserve evidence and handle possible cross-tenant exposure?

For each workstream include one metric, one command/config action, one owner, and one bad fix to reject.

## Part 5: Extra spaced recall gates

**E01 [W1 CDN/Auth]**
A CDN caches `Authorization` responses for `GET /me`. Which headers and cache policy must be present to make this safe or impossible?

**E02 [W2 Cache/Tenancy]**
A cache invalidation job deletes by product_id only. Why can this evict or expose another tenant's data?

**E03 [W3 Causal]**
A support note references an order update that another service has not observed. Which causal metadata would help?

**E04 [W4 Replica Lag]**
A replica lag metric is null after failover. Why can null be more dangerous than a high number?

**E05 [W5 Locking]**
A tenant export holds row locks and checkout writers queue. Which lock-wait metrics prove the export is the blocker?

**E06 [W6 Outbox]**
A polling outbox publisher and Debezium both run during fallback. What dedupe key must downstream use?

**E07 [W7 Rate Limit]**
A per-IP limiter is ineffective because one tenant uses many NAT IPs. Which principal should the limiter include?

**E08 [W8 SLO]**
Global p99 is healthy but enterprise p99 is breaching. Which SLO view should drive incident severity?

**E09 [08b AuthZ]**
A background worker consumes a message with tenant_id but loads policy using only user_id. What class of bug is this?

**E10 [08b Abuse]**
An authenticated webhook endpoint is replayed 10,000 times. Which signature, timestamp, and idempotency checks should exist?

**E11 [08b Cost]**
A dashboard query is cheap per run but refreshes every second for every seller. What multiplication turns it expensive?

**E12 [08b FinOps]**
Savings Plans lower hourly rate but not waste. Which utilization and latency evidence must be reviewed first?

**E13 [08b Tenancy]**
A shared search index stores documents for all tenants. Which filter and index-alias tests prevent leakage?

**E14 [08b Cell]**
One cell loses Kafka. How do you keep the incident from becoming global in DNS, routing, and replay?

**E15 [08b Evidence]**
A possible cross-tenant response was served from cache. Which logs and samples must be preserved before invalidation?

**E16 [08b Org]**
Finance wants to turn off a loss-making feature during a sale. What engineering and product facts should be in that decision?

**E17 [08b Capacity]**
A worker pool is 30% utilized but queue age grows. Why is utilization the wrong primary metric?

**E18 [08b Secrets]**
A secret rotation works in staging but fails prod. Which environment parity checks should the runbook require?

**E19 [08b mTLS]**
A trust bundle expires in 12 hours. Which pre-expiry alert and rollout check prevent surprise outage?

**E20 [08b Gates]**
The design says fail open for availability. Which data classes make that unacceptable?

---

> **Answer key (do not open until you attempt the retention test):**
> [`../answers/Retention-Tests/Week-08b Answers.md`](../answers/Retention-Tests/Week-08b%20Answers.md)
