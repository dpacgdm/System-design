# Week-14 Retention Test

Questions only. Covers Weeks 1-14 with emphasis on Google Docs, Feature Store, LLM Serving Platform, collaborative/AI designs. Attempt without opening answers.

## Rules

```text
1. Answer from memory; do not open modules or answer keys.
2. Rapid-fire answers should name mechanism, evidence, invariant, and one bad fix.
3. The compound Ops Sim should be answered like you are incident lead.
4. If unsure, write the safest invariant-preserving action and move on.
5. Open the answer key only after completing your attempt.
```

## Part 1: Rapid-fire spaced review (80 questions)

The mix is intentional: current week, recent weeks, and older foundations.

**Q01 [W1 DNS]**
A Route 53 failover changes the A record, but Java clients keep the old endpoint for hours. What cache behavior and JVM setting explain it?

**Q02 [W1 CDN]**
A product response with `Set-Cookie` is cached at the edge and served cross-user. What header and cache-key evidence proves the leak?

**Q03 [W1 HTTP/2]**
A gRPC client uses one long-lived HTTP/2 connection through an L4 load balancer and one backend is hot. Explain why scaling pods does not fix it.

**Q04 [W1 TCP]**
Outbound calls fail with `EADDRNOTAVAIL`, high `TIME_WAIT`, and normal upstream CPU. What resource is exhausted?

**Q05 [W1 WebSocket]**
A gateway deploy drops 600k sockets and reconnects arrive in a synchronized spike. Name the client and gateway defenses.

**Q06 [W2 SQL]**
A query `tenant_id=? AND created_at>?` is slow only for one large tenant. Name two planner/index explanations.

**Q07 [W2 NoSQL]**
A DynamoDB table partitions by `tenant_id`; one seller consumes 70% of WCU. Why is average table utilization misleading?

**Q08 [W2 Cache]**
Redis key `product:123` stores tenant-specific price. Which invariant is missing?

**Q09 [W2 LSM]**
An LSM store has high L0 files, pending compaction bytes, and p99 write stalls. What should you reject?

**Q10 [W2 Cache Stampede]**
A hot key expires and database QPS jumps 80x. What pattern prevents it?

**Q11 [W3 CAP]**
During a partition, checkout rejects stale payment authorization but dashboards stay stale. Which tradeoff does each choose?

**Q12 [W3 Consistency]**
A user changes a setting, refreshes, and sees the old value. Which session guarantee failed?

**Q13 [W3 Quorum]**
RF=3, W=1, R=1 is used for carts. What anomaly must product accept?

**Q14 [W3 Hashing]**
Moving from `hash(id) mod 20` to `mod 24` moves most keys. What strategy lowers movement?

**Q15 [W3 Clocks]**
Two auth services disagree whether a JWT is expired by 90 seconds. What do you inspect?

**Q16 [W4 Replication]**
An async replica is used for fraud margin checks and lags 45 seconds. Why is that unacceptable?

**Q17 [W4 Raft]**
A candidate missing a committed log entry requests votes. Why reject it?

**Q18 [W4 Sharding]**
One seller import opens 500 DB connections and unrelated sellers time out. Which resource lacked reservation?

**Q19 [W4 CDC]**
A replication slot retains WAL while Kafka is unhealthy. Which metric pages before disk fills?

**Q20 [W4 Failover]**
An old leader recovers and still accepts writes after failover. Name the prevention mechanism.

**Q21 [W5 Pooling]**
PgBouncer queue depth rises while Postgres CPU is 35%. Name two possible bottlenecks.

**Q22 [W5 CQRS]**
Search is stale but OLTP write succeeded. What lag proves the read model is behind?

**Q23 [W5 Cassandra]**
Tombstones per read jump to 100k after deletes. Why can reads fail while writes are fine?

**Q24 [W5 Sharding]**
A composite key omits tenant for a multi-tenant table. What incident shape follows?

**Q25 [W6 Kafka]**
Consumer lag is high for one partition only. What does that imply before adding consumers?

**Q26 [W6 Outbox]**
Checkout writes DB then publishes Kafka outside the transaction. What failure window exists?

**Q27 [W6 Saga]**
A refund saga calls PSP twice after timeout. Which persisted key prevents duplicate external effect?

**Q28 [W6 Backpressure]**
Email service slows and Kafka lag grows. What degradation is safe?

**Q29 [W6 Circuit]**
A dependency has p99 8s and clients retry every 200ms. What pattern reduces blast radius?

**Q30 [W7 Rate Limit]**
A shared token bucket lets one tenant spend all burst credits. What limiter hierarchy protects others?

**Q31 [W7 ID]**
Kubernetes pods share the same Snowflake worker id. Why do duplicate IDs appear?

**Q32 [W7 Search]**
OpenSearch shards reach 120GB and recovery takes hours. What invariant was missed?

**Q33 [W7 Flags]**
A tenant-scoped flag evaluates true globally when context is missing. What default should apply?

**Q34 [W7 LB]**
mTLS handshakes spike on every request after a client change. Which signal matters?

**Q35 [W8 Observability]**
Adding raw tenant_id and order_id to every metric creates millions of series. What is safer?

**Q36 [W8 SLO]**
Global availability is green but enterprise tier is red. Which budget matters?

**Q37 [W8 Alerting]**
CPU pages fire during a batch job while users are fine. What should page instead?

**Q38 [W8 Geo]**
Driver location older than 90 seconds remains matchable. What guard is missing?

**Q39 [W8 Causality]**
Trace spans show event B before event A across services. What does wall-clock time not prove?

**Q40 [W8 CRDT]**
A deleted cart item reappears after offline sync. What merge rule is suspect?

**Q41 [W8 Clocks]**
A coupon expires early in one region and late in another. What is the likely class of bug?

**Q42 [08b Auth]**
JWT has valid signature and issuer but wrong audience. What vulnerability appears if accepted?

**Q43 [08b mTLS]**
mTLS fails only checkout -> ledger in one AZ. What facts do you compare?

**Q44 [08b Cost]**
NAT gateway bytes jump after analytics deploy. Why may compute scaling be wrong?

**Q45 [08b Tenancy]**
Support exports by order_id without tenant context. What invariant is missing?

**Q46 [08b Noisy Neighbor]**
A seller export starves checkout in a shared pool. What isolation is missing?

**Q47 [W14 Docs]**
Why do collaborative editors need operation transforms or CRDTs? Add the mechanism you would name in a Northstar incident.

**Q48 [W14 Docs]**
What is the difference between presence and document state? Add the evidence you would name in a Northstar incident.

**Q49 [W14 Docs]**
Why are snapshots plus operation logs common? Add the first mitigation you would name in a Northstar incident.

**Q50 [W14 Feature Store]**
What is training-serving skew? Add the bad fix you would name in a Northstar incident.

**Q51 [W14 Feature Store]**
Why is point-in-time correctness needed for training data? Add the capacity check you would name in a Northstar incident.

**Q52 [W14 Feature Store]**
How do feature freshness and backfill interact? Add the durable guardrail you would name in a Northstar incident.

**Q53 [W14 LLM]**
Why do LLM serving platforms need admission control? Add the tenant/blast-radius check you would name in a Northstar incident.

**Q54 [W14 LLM]**
What is prompt/data leakage risk in shared LLM systems? Add the recovery step you would name in a Northstar incident.

**Q55 [W14 LLM]**
How do you degrade LLM serving safely? Add the alerting signal you would name in a Northstar incident.

**Q56 [W14 AI Ops]**
Which telemetry matters more than average GPU utilization? Add the design invariant you would name in a Northstar incident.

**Q57 [W14 Docs]**
Why do collaborative editors need operation transforms or CRDTs? Add the runbook owner you would name in a Northstar incident.

**Q58 [W14 Docs]**
What is the difference between presence and document state? Add the mechanism you would name in a Northstar incident.

**Q59 [W14 Docs]**
Why are snapshots plus operation logs common? Add the evidence you would name in a Northstar incident.

**Q60 [W14 Feature Store]**
What is training-serving skew? Add the first mitigation you would name in a Northstar incident.

**Q61 [W14 Feature Store]**
Why is point-in-time correctness needed for training data? Add the bad fix you would name in a Northstar incident.

**Q62 [W14 Feature Store]**
How do feature freshness and backfill interact? Add the capacity check you would name in a Northstar incident.

**Q63 [W14 LLM]**
Why do LLM serving platforms need admission control? Add the durable guardrail you would name in a Northstar incident.

**Q64 [W14 LLM]**
What is prompt/data leakage risk in shared LLM systems? Add the tenant/blast-radius check you would name in a Northstar incident.

**Q65 [W14 LLM]**
How do you degrade LLM serving safely? Add the recovery step you would name in a Northstar incident.

**Q66 [W14 AI Ops]**
Which telemetry matters more than average GPU utilization? Add the alerting signal you would name in a Northstar incident.

**Q67 [W14 Docs]**
Why do collaborative editors need operation transforms or CRDTs? Add the design invariant you would name in a Northstar incident.

**Q68 [W14 Docs]**
What is the difference between presence and document state? Add the runbook owner you would name in a Northstar incident.

**Q69 [W14 Mix]**
A launch feature touches checkout, Kafka, Redis, and search. What decides which subsystem gets protected first?

**Q70 [W14 Mix]**
A global dashboard is green while one paid tier is red. What is your next query?

**Q71 [W14 Mix]**
A team proposes replaying all backlog at max concurrency. What do you ask first?

**Q72 [W14 Mix]**
A cache contains derived state. When can it be source of truth?

**Q73 [W14 Mix]**
A retry storm starts after a dependency p99 spike. Name the limiter stack.

**Q74 [W14 Mix]**
A NoSQL hot partition appears during a celebrity or enterprise event. What metric disproves fleet-average comfort?

**Q75 [W14 Mix]**
A bad flag is cached on mobile for 30 minutes. What rollback design should exist?

**Q76 [W14 Mix]**
An incident bridge wants to lower durability to recover p99. What process applies?

**Q77 [W14 Mix]**
Support asks for affected customers. What data do you preserve?

**Q78 [W14 Mix]**
What distinguishes a passing answer from a principal answer in this curriculum?

## Part 2: Compound Ops Sim - Northstar Collaboration and AI Platform Degradation

Use the shared Northstar Commerce context. Answer as incident lead; include layer, invariant, metric, and rejected bad fix for every major claim.

```text
INCIDENT REPORT

Severity: P1
Company: Northstar Commerce
Systems involved:
  - collaborative seller docs
  - feature store online/offline pipeline
  - LLM serving gateway
  - vector cache/embeddings
  - tenant isolation and audit logging

Business event:
  A high-visibility launch exercises Google Docs, Feature Store, LLM Serving Platform, collaborative/AI designs under production traffic.
  The incident starts as a slow burn, then accelerates after an unsafe mitigation.

Timeline:
  09:00 - Launch begins with canary guardrails partially enabled.
  09:20 - First VIP tickets arrive; global dashboards remain green.
  09:35 - One subsystem owner scales workers without checking downstream headroom.
  09:50 - Retry/queue/cache pressure spills into checkout-adjacent paths.
  10:10 - Product asks to preserve the launch because revenue is high.
  10:30 - New traffic stabilizes after a kill switch, but repair/replay remains.
```

### Telemetry Pack

```text
USER / SLO SIGNALS:
  northstar_checkout_success_rate: 99.3% -> 91.8% on affected slice
  tenant_tier=enterprise error_rate: 0.2% -> 7.9%
  global_api_availability: 99.94% (misleading aggregate)
  redis_cpu_hot_shard: 94%

CURRENT-WEEK SIGNALS:
  doc_op_transform_conflicts: 0.4% -> 9.6%
  feature_freshness_lag_seconds: 40 -> 3600
  llm_queue_wait_p99_seconds: 2 -> 81
  tokens_per_second_enterprise: -62%
  tenant_cache_isolation_miss: 47 suspected

SPACED FOUNDATION SIGNALS:
  kafka_lag_hot_partition: 11.8M; peer partitions <80k
  postgres_pgbouncer_waiting: 0 -> 620
  search_or_projection_lag_seconds: 15 -> 1800
  retry_attempts_per_request_p95: 1 -> 9
  customer_ticket_rate_vip: +14x
  slo_burn_rate_5m_critical_slice: 18x budget

LOG LINES:
  incident: unsafe mitigation enabled by launch owner without capacity signoff
  gateway: retry budget exceeded; client version old-mobile still fixed retry
  data: source-of-truth writes healthy but derived projection behind
  observability: high-cardinality label caused dashboard query timeout
  support: VIP seller reports path-specific failure before global alert
```

### Config Pack

```yaml
feature_flags:
  launch_mode: enabled
  rollback_requires_mobile_refresh: true
  critical_path_guardrail: partial
retries:
  max_retries: 12
  backoff: fixed_200ms
  jitter: false
observability:
  labels_kept: [service]
  dropped_labels: [tenant_tier, region, client_version]
  raw_id_metric_label_enabled: true
capacity:
  replay_max_concurrency: unlimited
  downstream_headroom_check_required: false
runbook:
  incident_commander_required: false
```

### Decision Points

Answer each with action, evidence, and verification signal.

**T+0:** What are the first three facts you confirm before scaling or rollback?

**T+10:** Global dashboards are green but VIP tickets and sliced telemetry are red. What do you page on?

**T+20:** A team wants to replay/scale backlog at maximum concurrency. What must be proven first?

**T+35:** Product asks to keep launch behavior enabled. What degradation do you offer instead?

**T+60:** New traffic is safe. What repair sequence restores correctness without a second incident?

### Scenario Questions

1. Identify the primary root cause, two amplifiers, and one independent defect. Tie each to telemetry.
2. Separate source-of-truth correctness from derived freshness or UX degradation.
3. Write the first-15-minute mitigation sequence in order.
4. Reject five bad fixes from the config and timeline.
5. Do capacity math for the scarce resource most likely to exhaust first.
6. Define the affected-record set and replay/reconciliation strategy.
7. Propose durable design, observability, and runbook changes.
8. Name the owner for each postmortem action and the acceptance test.

---

## Self-Score Error-Type Table

| Error type | Count | Notes to review |
|------------|-------|-----------------|
| Current-week design miss | | |
| Spaced-foundation miss | | |
| Wrong layer/root cause | | |
| Unsafe mitigation order | | |
| Capacity math miss | | |
| Correctness invariant miss | | |
| Telemetry/slicing miss | | |
| Repair/replay miss | | |
| Org/runbook gap | | |

---

> **Answer key (do not open until you attempt the test):**
> [`../answers/Retention-Tests/Week-14 Answers.md`](../answers/Retention-Tests/Week-14%20Answers.md)
