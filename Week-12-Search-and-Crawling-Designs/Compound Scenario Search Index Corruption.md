# Compound SRE Scenario — Search Index Corruption

> **Week 12** — Web search + crawler pipeline — relevance and freshness P1

```
╔════════════════════════════════════════════════════════════════╗
║   RULES OF ENGAGEMENT                                          ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Answer from MEMORY. Do not re-read the teaching           ║
║      modules. The whole point is to test what STUCK in         ║
║      your brain.                                               ║
║                                                                ║
║   2. This is a COMPOUND scenario — multiple symptoms,          ║
║      multiple layers. Identify which subsystem each clue       ║
║      belongs to before proposing fixes.                        ║
║                                                                ║
║   3. Full depth expected. Name root causes, cite evidence,     ║
║      draw causal links, prioritize mitigations, and give       ║
║      exact commands where asked.                               ║
║                                                                ║
║   4. It's OK to say "I don't remember."                        ║
║      That's honest and tells us what to review.                ║
║      Faking an answer teaches nothing.                         ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Knowledge Domains Tested

**Week 12 (primary):** Inverted index structure and posting lists, Crawler politeness, frontier, and deduplication, Ranking signals and index freshness, Near-real-time indexing vs batch rebuild, Spell correction and query understanding, Index sharding and replica recovery

**Prior weeks (integrated):** Kafka CDC pipelines (Week 6), Consistent hashing (Week 3), Elasticsearch ops patterns (Week 7 search intro), Caching invalidation (Week 2), Observability (Week 8), CAP tradeoffs for search (Week 3)

The challenge is not knowing each concept in isolation — it is **mapping each symptom to the correct layer** and understanding how failures cascade across feed/chat, storage, messaging, and edge systems simultaneously.


---

## Compound SRE Scenario

This scenario requires knowledge from **this week's system designs** and **all prior weeks** simultaneously. The challenge is identifying which layer each symptom belongs to and how failures cascade.

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: QueryHub
  900M queries/day; 41% revenue from search ads

  ╔════════════════════════════════════════════════════════════════════════════════╗
  ║ ARCHITECTURE                                                                   ║
  ╠════════════════════════════════════════════════════════════════════════════════╣

  ║ QUERY PATH                                                                     ║
  ║   User → Edge cache (query result cache, 60s TTL)                              ║
  ║   → Query Service → Elasticsearch cluster (180 data nodes)                     ║
  ║   → Ranking layer (LTR model + business rules)                                 ║
  ║   → Ad auction (depends on same doc IDs)                                       ║
  ║                                                                                ║
  ║ INDEXING PATH                                                                  ║
  ║   Crawler fleet → Kafka crawl.raw → Parser → Kafka docs.parsed                 ║
  ║   Doc Builder → bulk index to ES + object store snapshots                      ║
  ║   CDC from merchant DB → Kafka merchant.updates → partial update API           ║
  ║                                                                                ║
  ║ CRAWLER                                                                        ║
  ║   Politeness: per-domain token bucket in Redis                                 ║
  ║   Frontier: priority queue in Cassandra                                        ║
  ║   Robots.txt cache 24h TTL                                                     ║
  ║   Dedup: SimHash + URL canonicalization                                        ║
  ║                                                                                ║
  ║ INCIDENT CONTEXT                                                               ║
  ║   Black Friday merchant feed + SEO algorithm deploy 06:00 UTC                  ║
  ║   Index size 4.2 PB logical; 12 primary shards × 15 replicas                   ║
  ╚════════════════════════════════════════════════════════════════════════════════╝

INCIDENT TIMELINE:

  06:00 — Ranking model v2.14 deployed. New freshness signal weight +40%.

  06:12 — Null result rate +0.02% → +3.8% for brand queries.

  06:18 — Ad CTR drops 22% — ads served on wrong landing doc IDs.

  06:24 — Crawler queue depth 890M URLs; politeness bucket stuck at zero for amazon.com.

  06:30 — Elasticsearch cluster yellow → red on index catalog-v3 shard 7.

  06:36 — Users report top results are 404 pages crawled 6 months ago.

  06:42 — Partial update API returns 200 but docs missing fields in ES.

  06:48 — Query cache serving results for deleted docs (stale-if-error engaged).

  06:54 — On-call identifies problems A–H.

  ─── Additional problems discovered during investigation ───

  06:54 — PROBLEM A:
            Shard 7 corruption after failed forcemerge
            Weekly forcemerge on shard 7 killed mid-merge; segment _0.fnm truncated. Replica promotion copied bad segment.

            Monitoring:
            → Kafka consumer lag: partition 17 = 4.2M, all others < 12K
            → Fan-out worker pod fanout-17 CPU 99%; fanout-03 at 11%
            → posts.created produce rate 890K msg/sec spike on key @nova

  06:56 — PROBLEM B:
            Crawler dedup false positive
            SimHash threshold tightened in deploy; distinct product pages hash-collide. 890M URL frontier stall — skipped as 'duplicate'.

            Monitoring:
            → Redis shard-7: ops/sec 412K on single key timeline:nova
            → redis-cli --hotkeys shows 89% traffic on 3 keys
            → Memory fragmentation ratio 1.42 on shard-7

  06:58 — PROBLEM C:
            CDC ordering violation
            merchant.updates consumed without partition key = merchant_id. Delete event processed before create → ghost docs.

            Monitoring:
            → nodetool status: cass-12 UN (unreachable)
            → Hinted handoff queue depth 890,412 on cass-04
            → UnavailableException rate 1,240/sec on user_timelines CF

  07:00 — PROBLEM D:
            Ranking freshness signal divide-by-zero
            New model uses log(crawl_age_hours); crawl_age=0 for live CDC docs → NaN scores default sort to ancient high-PageRank docs.

            Monitoring:
            → chat.events consumer group: 3/24 members in RevokePartitions
            → Read receipt lag 340s; delivery event lag 12s same message_id
            → cooperative-sticky assignor upgrade deploy 2026-03-14

  07:02 — PROBLEM E:
            Query result cache poison
            Edge cache key = hash(query) only, no index version. Post-deploy bad results cached 60s × millions of queries.

            Monitoring:
            → Feed Gateway: 47,000 gRPC calls/sec to Media Service
            → Media replica-1 CPU 96%; replicas 2-8 at 9%
            → GraphQL resolver post.author.avatar sequential await pattern

  07:05 — PROBLEM F:
            Robots.txt cache stale allow
            Redis robots:amazon.com TTL refreshed but content from 2024 block rule. Crawler fetches disallowed URLs → 403 → retry storm.

            Monitoring:
            → WebSocket disconnect cadence: exactly 60s idle intervals
            → Presence key TTL 120s; last_ping 67s ago on sample clients
            → NLB target group idle timeout: 60s on ws-chat-tg

  07:08 — PROBLEM G:
            Bulk indexer unbounded retry
            Failed bulk requests retried without jitter; ES thread pool rejected execution → cascading rejections cluster-wide.

            Monitoring:
            → Rate limit 503 rate 8.2% in EU; 0.1% in US
            → Shared Redis key ratelimit:asn:3320 token count 0
            → Feature flag aggregate_rate_limit_by_asn=true since 07:55

  07:11 — PROBLEM H:
            Snapshot restore wrong index alias
            Automated recovery script pointed catalog-v3 alias to snapshot from 2025-11-01 during shard 7 recovery attempt.

            Monitoring:
            → CloudFront 403 on signed URL: Signature expired (clock skew)
            → Media pod clock offset +37s vs NTP in eu-west-1
            → S3 presigned URL X-Amz-Date mismatch in access logs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Data Flow Overview

```mermaid
flowchart LR
  subgraph edge [Edge]
    C[Clients]
    CDN[CDN / WAF]
  end
  subgraph gateway [Gateway]
    API[API / GraphQL]
    WS[WebSocket]
  end
  subgraph core [Core — QueryHub]
    SVC[Domain Services]
  end
  subgraph async [Async + Storage]
    K[Kafka]
    R[Redis]
    DB[(Cassandra / PG)]
  end
  C --> CDN --> API
  C --> WS
  API --> SVC
  WS --> SVC
  SVC --> K
  SVC --> R
  SVC --> DB
  K --> SVC
```

Use this map when triaging: **symptoms at the edge** often originate three hops away in async pipelines.


## Pre-Incident Context

The following changes were in flight before the incident. Any may be red herrings; all may contribute.

```
  CHANGE LOG (last 7 days):
  ─────────────────────────────────────────────────────────
  • Feature flag rollout: 5% → 25% → 50% canary
  • Load test cancelled due to change freeze exception
  • One AZ capacity reduction for cost program
  • Dependency upgrade: Kafka client 3.6 → 3.7
  • Redis cluster resharding (add 2 shards) — week 2 of migration
  • On-call runbook updated but not rehearsed
  • SLO review deferred to next quarter
```

**Service:** QueryHub
**Severity:** P1
**Scale:** 900M queries/day; 41% revenue from search ads


```
Slack #incidents-war-room
  T+0m  incident-bot:  P1 opened: QueryHub multi-symptom degradation
  T+2m  oncall-primary:  Joined bridge. Pulling dashboards for feed/chat/index path.
  T+5m  oncall-db:  Cassandra/Redis/Postgres — which store is hot?
  T+8m  eng-lead:  Any deploys in last 24h? Feature flags?
  06:54  oncall-primary:  Problem A hypothesis forming: Shard 7 corruption after failed forcemerge
  06:56  oncall-primary:  Problem B hypothesis forming: Crawler dedup false positive
  06:58  oncall-primary:  Problem C hypothesis forming: CDC ordering violation
  07:00  oncall-primary:  Problem D hypothesis forming: Ranking freshness signal divide-by-zero
```

---

## Grafana Dashboard Excerpts (Incident Snapshot)

### Panel: Request rate by service

```
  series  incident  notes          
  ------  --------  ---------------
  api     12K       baseline varies
  worker  890K      baseline varies
  ws      2.1M      baseline varies
```

### Panel: Error budget burn

```
  series    incident  notes          
  --------  --------  ---------------
  feed      14×       baseline varies
  chat      8×        baseline varies
  platform  22×       baseline varies
```

### Panel: Saturation

```
  series   incident  notes          
  -------  --------  ---------------
  cpu      94%       baseline varies
  memory   89%       baseline varies
  disk     78%       baseline varies
  network  67%       baseline varies
```


---

## Monitoring Appendix

### PROBLEM-A: Shard 7 corruption after failed forcemerge

Discovery time: **06:54**. Symptom summary: Weekly forcemerge on shard 7 killed mid-merge; segment _0.fnm truncated. Replica promotion copied bad segment.

```
  instance      metric          normal  incident_hot  incident_cold
  ------------  --------------  ------  ------------  -------------
  QueryHub-A-0  cpu_pct         78      94            12           
  QueryHub-A-1  memory_pct      62      89            45           
  QueryHub-A-2  request_rate    12400   89000         2100         
  QueryHub-A-3  error_rate_pct  0.1     8.4           0.02         
  QueryHub-A-4  p99_latency_ms  120     8400          45           
```

```
PagerDuty timeline (filtered P1/P2):
  06:54  [QueryHub/A]  Elevated cpu_pct on critical path
  06:54  [QueryHub/A]  SLO burn rate 14× over 5m window
```

### Log patterns — Problem A

```
level=WARN  service=QueryHub  problem=A  msg="downstream degraded"
level=ERROR service=QueryHub  problem=A  msg="retry budget exhausted"
level=INFO  service=QueryHub  problem=A  msg="circuit breaker state=OPEN"
```

### PROBLEM-B: Crawler dedup false positive

Discovery time: **06:56**. Symptom summary: SimHash threshold tightened in deploy; distinct product pages hash-collide. 890M URL frontier stall — skipped as 'duplicate'.

```
  instance      metric          normal  incident_hot  incident_cold
  ------------  --------------  ------  ------------  -------------
  QueryHub-B-0  cpu_pct         78      94            12           
  QueryHub-B-1  memory_pct      62      89            45           
  QueryHub-B-2  request_rate    12400   89000         2100         
  QueryHub-B-3  error_rate_pct  0.1     8.4           0.02         
  QueryHub-B-4  p99_latency_ms  120     8400          45           
```

```
PagerDuty timeline (filtered P1/P2):
  06:56  [QueryHub/B]  Elevated cpu_pct on critical path
  06:56  [QueryHub/B]  SLO burn rate 14× over 5m window
```

### Log patterns — Problem B

```
level=WARN  service=QueryHub  problem=B  msg="downstream degraded"
level=ERROR service=QueryHub  problem=B  msg="retry budget exhausted"
level=INFO  service=QueryHub  problem=B  msg="circuit breaker state=OPEN"
```

### PROBLEM-C: CDC ordering violation

Discovery time: **06:58**. Symptom summary: merchant.updates consumed without partition key = merchant_id. Delete event processed before create → ghost docs.

```
  instance      metric          normal  incident_hot  incident_cold
  ------------  --------------  ------  ------------  -------------
  QueryHub-C-0  cpu_pct         78      94            12           
  QueryHub-C-1  memory_pct      62      89            45           
  QueryHub-C-2  request_rate    12400   89000         2100         
  QueryHub-C-3  error_rate_pct  0.1     8.4           0.02         
  QueryHub-C-4  p99_latency_ms  120     8400          45           
```

```
PagerDuty timeline (filtered P1/P2):
  06:58  [QueryHub/C]  Elevated cpu_pct on critical path
  06:58  [QueryHub/C]  SLO burn rate 14× over 5m window
```

### Log patterns — Problem C

```
level=WARN  service=QueryHub  problem=C  msg="downstream degraded"
level=ERROR service=QueryHub  problem=C  msg="retry budget exhausted"
level=INFO  service=QueryHub  problem=C  msg="circuit breaker state=OPEN"
```

### PROBLEM-D: Ranking freshness signal divide-by-zero

Discovery time: **07:00**. Symptom summary: New model uses log(crawl_age_hours); crawl_age=0 for live CDC docs → NaN scores default sort to ancient high-PageRank docs.

```
  instance      metric          normal  incident_hot  incident_cold
  ------------  --------------  ------  ------------  -------------
  QueryHub-D-0  cpu_pct         78      94            12           
  QueryHub-D-1  memory_pct      62      89            45           
  QueryHub-D-2  request_rate    12400   89000         2100         
  QueryHub-D-3  error_rate_pct  0.1     8.4           0.02         
  QueryHub-D-4  p99_latency_ms  120     8400          45           
```

```
PagerDuty timeline (filtered P1/P2):
  07:00  [QueryHub/D]  Elevated cpu_pct on critical path
  07:00  [QueryHub/D]  SLO burn rate 14× over 5m window
```

### Log patterns — Problem D

```
level=WARN  service=QueryHub  problem=D  msg="downstream degraded"
level=ERROR service=QueryHub  problem=D  msg="retry budget exhausted"
level=INFO  service=QueryHub  problem=D  msg="circuit breaker state=OPEN"
```

### PROBLEM-E: Query result cache poison

Discovery time: **07:02**. Symptom summary: Edge cache key = hash(query) only, no index version. Post-deploy bad results cached 60s × millions of queries.

```
  instance      metric          normal  incident_hot  incident_cold
  ------------  --------------  ------  ------------  -------------
  QueryHub-E-0  cpu_pct         78      94            12           
  QueryHub-E-1  memory_pct      62      89            45           
  QueryHub-E-2  request_rate    12400   89000         2100         
  QueryHub-E-3  error_rate_pct  0.1     8.4           0.02         
  QueryHub-E-4  p99_latency_ms  120     8400          45           
```

```
PagerDuty timeline (filtered P1/P2):
  07:02  [QueryHub/E]  Elevated cpu_pct on critical path
  07:02  [QueryHub/E]  SLO burn rate 14× over 5m window
```

### Log patterns — Problem E

```
level=WARN  service=QueryHub  problem=E  msg="downstream degraded"
level=ERROR service=QueryHub  problem=E  msg="retry budget exhausted"
level=INFO  service=QueryHub  problem=E  msg="circuit breaker state=OPEN"
```

### PROBLEM-F: Robots.txt cache stale allow

Discovery time: **07:05**. Symptom summary: Redis robots:amazon.com TTL refreshed but content from 2024 block rule. Crawler fetches disallowed URLs → 403 → retry storm.

```
  instance      metric          normal  incident_hot  incident_cold
  ------------  --------------  ------  ------------  -------------
  QueryHub-F-0  cpu_pct         78      94            12           
  QueryHub-F-1  memory_pct      62      89            45           
  QueryHub-F-2  request_rate    12400   89000         2100         
  QueryHub-F-3  error_rate_pct  0.1     8.4           0.02         
  QueryHub-F-4  p99_latency_ms  120     8400          45           
```

```
PagerDuty timeline (filtered P1/P2):
  07:05  [QueryHub/F]  Elevated cpu_pct on critical path
  07:05  [QueryHub/F]  SLO burn rate 14× over 5m window
```

### Log patterns — Problem F

```
level=WARN  service=QueryHub  problem=F  msg="downstream degraded"
level=ERROR service=QueryHub  problem=F  msg="retry budget exhausted"
level=INFO  service=QueryHub  problem=F  msg="circuit breaker state=OPEN"
```

### PROBLEM-G: Bulk indexer unbounded retry

Discovery time: **07:08**. Symptom summary: Failed bulk requests retried without jitter; ES thread pool rejected execution → cascading rejections cluster-wide.

```
  instance      metric          normal  incident_hot  incident_cold
  ------------  --------------  ------  ------------  -------------
  QueryHub-G-0  cpu_pct         78      94            12           
  QueryHub-G-1  memory_pct      62      89            45           
  QueryHub-G-2  request_rate    12400   89000         2100         
  QueryHub-G-3  error_rate_pct  0.1     8.4           0.02         
  QueryHub-G-4  p99_latency_ms  120     8400          45           
```

```
PagerDuty timeline (filtered P1/P2):
  07:08  [QueryHub/G]  Elevated cpu_pct on critical path
  07:08  [QueryHub/G]  SLO burn rate 14× over 5m window
```

### Log patterns — Problem G

```
level=WARN  service=QueryHub  problem=G  msg="downstream degraded"
level=ERROR service=QueryHub  problem=G  msg="retry budget exhausted"
level=INFO  service=QueryHub  problem=G  msg="circuit breaker state=OPEN"
```

### PROBLEM-H: Snapshot restore wrong index alias

Discovery time: **07:11**. Symptom summary: Automated recovery script pointed catalog-v3 alias to snapshot from 2025-11-01 during shard 7 recovery attempt.

```
  instance      metric          normal  incident_hot  incident_cold
  ------------  --------------  ------  ------------  -------------
  QueryHub-H-0  cpu_pct         78      94            12           
  QueryHub-H-1  memory_pct      62      89            45           
  QueryHub-H-2  request_rate    12400   89000         2100         
  QueryHub-H-3  error_rate_pct  0.1     8.4           0.02         
  QueryHub-H-4  p99_latency_ms  120     8400          45           
```

```
PagerDuty timeline (filtered P1/P2):
  07:11  [QueryHub/H]  Elevated cpu_pct on critical path
  07:11  [QueryHub/H]  SLO burn rate 14× over 5m window
```

### Log patterns — Problem H

```
level=WARN  service=QueryHub  problem=H  msg="downstream degraded"
level=ERROR service=QueryHub  problem=H  msg="retry budget exhausted"
level=INFO  service=QueryHub  problem=H  msg="circuit breaker state=OPEN"
```


---

## On-Call Runbook Stubs (Reference)

These stubs exist in the wiki but may be stale. Do NOT assume they match production.

### Runbook RB-QUER-A

**Title:** Shard 7 corruption after failed forcemerge

```
  Trigger:  Automated alert QueryHub-A-*
  Impact:   User-facing degradation on primary path
  Steps:
    1. Confirm metric spike in Grafana dashboard row 1
    2. Check recent deploys / feature flags
    3. Escalate to service owner if not resolved in 15m
  Last reviewed: 2025-11-14 (STALE)
```

### Runbook RB-QUER-B

**Title:** Crawler dedup false positive

```
  Trigger:  Automated alert QueryHub-B-*
  Impact:   User-facing degradation on primary path
  Steps:
    1. Confirm metric spike in Grafana dashboard row 2
    2. Check recent deploys / feature flags
    3. Escalate to service owner if not resolved in 15m
  Last reviewed: 2025-11-14 (STALE)
```

### Runbook RB-QUER-C

**Title:** CDC ordering violation

```
  Trigger:  Automated alert QueryHub-C-*
  Impact:   User-facing degradation on primary path
  Steps:
    1. Confirm metric spike in Grafana dashboard row 3
    2. Check recent deploys / feature flags
    3. Escalate to service owner if not resolved in 15m
  Last reviewed: 2025-11-14 (STALE)
```

### Runbook RB-QUER-D

**Title:** Ranking freshness signal divide-by-zero

```
  Trigger:  Automated alert QueryHub-D-*
  Impact:   User-facing degradation on primary path
  Steps:
    1. Confirm metric spike in Grafana dashboard row 4
    2. Check recent deploys / feature flags
    3. Escalate to service owner if not resolved in 15m
  Last reviewed: 2025-11-14 (STALE)
```

### Runbook RB-QUER-E

**Title:** Query result cache poison

```
  Trigger:  Automated alert QueryHub-E-*
  Impact:   User-facing degradation on primary path
  Steps:
    1. Confirm metric spike in Grafana dashboard row 5
    2. Check recent deploys / feature flags
    3. Escalate to service owner if not resolved in 15m
  Last reviewed: 2025-11-14 (STALE)
```

### Runbook RB-QUER-F

**Title:** Robots.txt cache stale allow

```
  Trigger:  Automated alert QueryHub-F-*
  Impact:   User-facing degradation on primary path
  Steps:
    1. Confirm metric spike in Grafana dashboard row 6
    2. Check recent deploys / feature flags
    3. Escalate to service owner if not resolved in 15m
  Last reviewed: 2025-11-14 (STALE)
```

### Runbook RB-QUER-G

**Title:** Bulk indexer unbounded retry

```
  Trigger:  Automated alert QueryHub-G-*
  Impact:   User-facing degradation on primary path
  Steps:
    1. Confirm metric spike in Grafana dashboard row 7
    2. Check recent deploys / feature flags
    3. Escalate to service owner if not resolved in 15m
  Last reviewed: 2025-11-14 (STALE)
```

### Runbook RB-QUER-H

**Title:** Snapshot restore wrong index alias

```
  Trigger:  Automated alert QueryHub-H-*
  Impact:   User-facing degradation on primary path
  Steps:
    1. Confirm metric spike in Grafana dashboard row 8
    2. Check recent deploys / feature flags
    3. Escalate to service owner if not resolved in 15m
  Last reviewed: 2025-11-14 (STALE)
```


---

## Diagnostic Questions

Answer all questions in writing. Cite monitoring evidence, name the subsystem/layer, and explain interactions between problems.

**Question 1:** Classify A–H as query-path, index-path, or crawler-path failures. Root cause + evidence for each.

**Question 2:** Explain why ads CTR dropped 22% while null results only rose 3.8%. Which problems cause wrong doc ID without null?

**Question 3:** At 07:15, can you serve search from catalog-v2 alias? Analyze problems H, A, and E in that decision.

**Question 4:** Draw the CDC ordering bug (C) for one merchant SKU lifecycle: create → update → delete. What partition key strategy fixes it?

**Question 5:** Prioritize A–H. Consider ad revenue, user trust (404 in top results), and recovery time.

**Question 6:** Give exact ES API calls / Kafka consumer commands for top-3 mitigations.

**Question 7:** Design index versioning in the query cache to prevent E. Include cache key structure.

**Question 8:** Post-incident: when to rebuild vs repair shard 7? Compare reindex-from-remote, snapshot restore, and live dual-write migration.

**Question 9:** Crawler politeness stuck at zero (problem F context) — diagnose Redis token bucket vs robots.txt interaction.

**Question 10:** Five monitoring alerts for indexing pipeline health before next Black Friday.


---

## Submission Notes

- Work in a single document; label answers by question number.
- Cite evidence from the timeline and monitoring appendix.
- Diagrams may be ASCII or Mermaid.
- **This file contains questions only — no worked answers.**
- Recorded answers belong in your retention notebook or a separate worked-answers file.

---

## Diagnostic Command Cheat Sheet

The following commands are available to on-call. In your answers, cite which you would run and what output pattern you expect.

### Kafka consumer lag

```bash
kafka-consumer-groups.sh --bootstrap-server $BROKERS \
  --describe --group queryhub-workers
kafka-topics.sh --bootstrap-server $BROKERS \
  --describe --topic events.main | grep -A2 Partition
```

### Redis hot key scan

```bash
redis-cli -c -h $REDIS_CLUSTER --hotkeys
redis-cli -c -h $REDIS_CLUSTER INFO commandstats | head -40
redis-cli -c -h $REDIS_CLUSTER --latency-history
```

### Cassandra cluster health

```bash
nodetool status
nodetool tpstats | head -30
nodetool tablestats keyspace.cf | grep -i hint
```

### PostgreSQL / replication

```bash
SELECT * FROM pg_stat_replication;
SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) FROM pg_replication_slots;
SHOW POOLS;  -- PgBouncer admin console
```

### Elasticsearch index health

```bash
curl -s $ES/_cluster/health?pretty
curl -s $ES/_cat/shards?v | grep UNASSIGNED
curl -s $ES/index/_segments | jq '.[] | select(.num==7)'
```

### Kubernetes / mesh

```bash
kubectl top pods -n production --sort-by=cpu | head -20
kubectl get events -n production --sort-by=.lastTimestamp | tail -30
istioctl proxy-stats deploy/$SVC | grep cx_active
```

---

## Red Herring Register

The following observations were raised on the bridge and may mislead. In Question 1 or 2, note which are red herrings and why.

1. Primary database CPU is elevated but within SLO — not every CPU spike is the root cause.
2. A deploy occurred 6 hours before incident — correlation is not causation unless evidence links.
3. Single PoP latency elevated — may be symptom of origin overload, not edge misconfiguration.
4. Error rate dashboard shows 0.0% HTTP 5xx — application errors may hide in 200 bodies or async lag.
5. Auto-scaling added capacity 10 minutes before complaints — scaling treats symptoms, not causes.
6. Vendor status page all-green — third-party APIs can degrade without public incident.

---

## Distributed Trace Samples

Sample OpenTelemetry exports. Trace IDs correlate with log lines in the monitoring appendix.

### Trace TB-0000 (tags: problem=A)

```
trace_id=tb-queryhub-0000
duration_ms=480
service=QueryHub
spans:
  - span=0 name=HTTP/gateway duration_ms=15 status=OK
  - span=0.1 name=downstream/Shard 7 corruption after failed forcemer duration_ms=60
  - span=1 name=HTTP/gateway duration_ms=27 status=OK
  - span=1.1 name=downstream/Shard 7 corruption after failed forcemer duration_ms=85
  - span=2 name=HTTP/gateway duration_ms=39 status=OK
  - span=2.1 name=downstream/Shard 7 corruption after failed forcemer duration_ms=110
  - span=3 name=HTTP/gateway duration_ms=51 status=ERROR
  - span=3.1 name=downstream/Shard 7 corruption after failed forcemer duration_ms=135
  - span=4 name=HTTP/gateway duration_ms=63 status=OK
  - span=4.1 name=downstream/Shard 7 corruption after failed forcemer duration_ms=160
```

### Trace TB-0001 (tags: problem=B)

```
trace_id=tb-queryhub-0001
duration_ms=497
service=QueryHub
spans:
  - span=0 name=HTTP/gateway duration_ms=15 status=OK
  - span=0.1 name=downstream/Crawler dedup false positive duration_ms=60
  - span=1 name=HTTP/gateway duration_ms=27 status=OK
  - span=1.1 name=downstream/Crawler dedup false positive duration_ms=85
  - span=2 name=HTTP/gateway duration_ms=39 status=OK
  - span=2.1 name=downstream/Crawler dedup false positive duration_ms=110
  - span=3 name=HTTP/gateway duration_ms=51 status=OK
  - span=3.1 name=downstream/Crawler dedup false positive duration_ms=135
  - span=4 name=HTTP/gateway duration_ms=63 status=OK
  - span=4.1 name=downstream/Crawler dedup false positive duration_ms=160
```

### Trace TB-0002 (tags: problem=C)

```
trace_id=tb-queryhub-0002
duration_ms=514
service=QueryHub
spans:
  - span=0 name=HTTP/gateway duration_ms=15 status=OK
  - span=0.1 name=downstream/CDC ordering violation duration_ms=60
  - span=1 name=HTTP/gateway duration_ms=27 status=OK
  - span=1.1 name=downstream/CDC ordering violation duration_ms=85
  - span=2 name=HTTP/gateway duration_ms=39 status=OK
  - span=2.1 name=downstream/CDC ordering violation duration_ms=110
  - span=3 name=HTTP/gateway duration_ms=51 status=OK
  - span=3.1 name=downstream/CDC ordering violation duration_ms=135
  - span=4 name=HTTP/gateway duration_ms=63 status=OK
  - span=4.1 name=downstream/CDC ordering violation duration_ms=160
```

### Trace TB-0003 (tags: problem=D)

```
trace_id=tb-queryhub-0003
duration_ms=531
service=QueryHub
spans:
  - span=0 name=HTTP/gateway duration_ms=15 status=OK
  - span=0.1 name=downstream/Ranking freshness signal divide-by-zero duration_ms=60
  - span=1 name=HTTP/gateway duration_ms=27 status=OK
  - span=1.1 name=downstream/Ranking freshness signal divide-by-zero duration_ms=85
  - span=2 name=HTTP/gateway duration_ms=39 status=OK
  - span=2.1 name=downstream/Ranking freshness signal divide-by-zero duration_ms=110
  - span=3 name=HTTP/gateway duration_ms=51 status=OK
  - span=3.1 name=downstream/Ranking freshness signal divide-by-zero duration_ms=135
  - span=4 name=HTTP/gateway duration_ms=63 status=OK
  - span=4.1 name=downstream/Ranking freshness signal divide-by-zero duration_ms=160
```

### Trace TB-0004 (tags: problem=E)

```
trace_id=tb-queryhub-0004
duration_ms=548
service=QueryHub
spans:
  - span=0 name=HTTP/gateway duration_ms=15 status=OK
  - span=0.1 name=downstream/Query result cache poison duration_ms=60
  - span=1 name=HTTP/gateway duration_ms=27 status=OK
  - span=1.1 name=downstream/Query result cache poison duration_ms=85
  - span=2 name=HTTP/gateway duration_ms=39 status=OK
  - span=2.1 name=downstream/Query result cache poison duration_ms=110
  - span=3 name=HTTP/gateway duration_ms=51 status=ERROR
  - span=3.1 name=downstream/Query result cache poison duration_ms=135
  - span=4 name=HTTP/gateway duration_ms=63 status=OK
  - span=4.1 name=downstream/Query result cache poison duration_ms=160
```

### Trace TB-0005 (tags: problem=F)

```
trace_id=tb-queryhub-0005
duration_ms=565
service=QueryHub
spans:
  - span=0 name=HTTP/gateway duration_ms=15 status=OK
  - span=0.1 name=downstream/Robots.txt cache stale allow duration_ms=60
  - span=1 name=HTTP/gateway duration_ms=27 status=OK
  - span=1.1 name=downstream/Robots.txt cache stale allow duration_ms=85
  - span=2 name=HTTP/gateway duration_ms=39 status=OK
  - span=2.1 name=downstream/Robots.txt cache stale allow duration_ms=110
  - span=3 name=HTTP/gateway duration_ms=51 status=OK
  - span=3.1 name=downstream/Robots.txt cache stale allow duration_ms=135
  - span=4 name=HTTP/gateway duration_ms=63 status=OK
  - span=4.1 name=downstream/Robots.txt cache stale allow duration_ms=160
```

### Trace TB-0006 (tags: problem=G)

```
trace_id=tb-queryhub-0006
duration_ms=582
service=QueryHub
spans:
  - span=0 name=HTTP/gateway duration_ms=15 status=OK
  - span=0.1 name=downstream/Bulk indexer unbounded retry duration_ms=60
  - span=1 name=HTTP/gateway duration_ms=27 status=OK
  - span=1.1 name=downstream/Bulk indexer unbounded retry duration_ms=85
  - span=2 name=HTTP/gateway duration_ms=39 status=OK
  - span=2.1 name=downstream/Bulk indexer unbounded retry duration_ms=110
  - span=3 name=HTTP/gateway duration_ms=51 status=OK
  - span=3.1 name=downstream/Bulk indexer unbounded retry duration_ms=135
  - span=4 name=HTTP/gateway duration_ms=63 status=OK
  - span=4.1 name=downstream/Bulk indexer unbounded retry duration_ms=160
```

### Trace TB-0007 (tags: problem=H)

```
trace_id=tb-queryhub-0007
duration_ms=599
service=QueryHub
spans:
  - span=0 name=HTTP/gateway duration_ms=15 status=OK
  - span=0.1 name=downstream/Snapshot restore wrong index alias duration_ms=60
  - span=1 name=HTTP/gateway duration_ms=27 status=OK
  - span=1.1 name=downstream/Snapshot restore wrong index alias duration_ms=85
  - span=2 name=HTTP/gateway duration_ms=39 status=OK
  - span=2.1 name=downstream/Snapshot restore wrong index alias duration_ms=110
  - span=3 name=HTTP/gateway duration_ms=51 status=OK
  - span=3.1 name=downstream/Snapshot restore wrong index alias duration_ms=135
  - span=4 name=HTTP/gateway duration_ms=63 status=OK
  - span=4.1 name=downstream/Snapshot restore wrong index alias duration_ms=160
```
