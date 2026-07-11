# WEEK 5 RETENTION TEST

Covers **Weeks 1–5** (transport through database internals). Answer from memory before opening worked-answer files.

---

## Rules

```
╔═══════════════════════════════════════════════════════════════╗
║   RULES OF ENGAGEMENT                                         ║
╟───────────────────────────────────────────────────────────────╢
║                                                               ║
║   1. Answer from MEMORY. Do not re-read the teaching modules. ║
║                                                               ║
║   2. Rapid-fire: 2–4 sentences per question.                  ║
║                                                               ║
║   3. Compound scenario + in-depth questions: full depth.      ║
║                                                               ║
║   4. "I don't remember" is valid — it tells us what to        ║
║      review.                                                  ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Part 1: Cross-Week Rapid-Fire (Weeks 1–4 recall)

**Q1 (Week 1 — TCP):** `ss -s` shows 38,000 sockets in `TIME_WAIT` but CPU is 20%. Checkout API returns connection timeouts to Postgres. What is the failure mode, and what is the *first* sysctl you set before restarting anything?

**Q2 (Week 2 — SQL):** `EXPLAIN ANALYZE` shows `Index Scan` on `(customer_id, order_date)` but `rows removed by filter: 4,200,000`. The query is `WHERE order_date > '2024-01-01' AND status = 'pending'`. Why is the index inefficient?

**Q3 (Week 3 — Consistency):** A user updates their profile, refreshes immediately, and sees the old email. Replication lag is 200ms. Which consistency guarantee was violated, and what is the *simplest* routing fix?

**Q4 (Week 4 — Replication):** Primary uses async replication. Primary crashes 3 seconds after acknowledging a payment write. Standby is promoted. What data class is at risk, and what replication mode would have prevented it?

**Q5 (Week 4 — Sharding):** Shard key is `user_id`. Dashboard query: "total revenue shipped today across all users." What happens to this query on a sharded OLTP cluster, and what architecture moves it off the hot path?

---

## Part 2: Week 5 Rapid-Fire (Database Scaling & Cassandra)

Answer all 10. Keep each answer concise.

**Q6:** p99 latency went from 50ms → 800ms. Primary CPU is 30%. Team wants to shard. What is your first question?

**Q7:** PgBouncer in transaction mode. App reports `search_path` is randomly wrong. What is wrong?

**Q8:** Postgres at 92% disk; `pg_wal` is 600 GB. All streaming replicas show `replay_lag < 200ms`. What query do you run first?

**Q9:** `synchronous_standby_names = 'FIRST 1 (r1, r2)'`. Both replicas die. What happens to writes?

**Q10:** Debezium connector lag is 2 hours and growing. Kafka consumer offsets are advancing normally. What is wrong?

**Q11:** Sharded by `user_id`. Query "all orders shipped today" runs against the OLTP cluster. What happens, and what is the right architecture?

**Q12:** Inventory active/active two regions with LWW. Customer charged for out-of-stock item. Explain the bug.

**Q13:** Read-your-writes via LSN token, transaction-pooled PgBouncer. Where do you capture the LSN, and where do you NOT?

**Q14:** CDC consumer halted on schema change. Producer dropped a column. What Schema Registry compatibility mode would have prevented this?

**Q15:** Rung 3 exhausted (biggest SKU, 100k writes/s). Boss says "shard." What five questions do you ask before agreeing?

---

## Part 3: Cassandra Rapid-Fire

**Q16:** `nodetool tablestats` shows average 14,200 tombstones per read. Writes are fast; reads are 340ms p99. Compaction strategy is STCS. Name two likely root causes.

**Q17:** What does `gc_grace_seconds` protect against, and what operational mistake makes tombstones *more* dangerous over time?

**Q18:** Why can a single hot partition (2.4 GB) hurt an entire node, not just one query?

---

## Part 4: Extended Rapid-Fire — Scaling, Replication, CDC, Cassandra

Answer these from memory. Keep each to 2-5 sentences.

### A. Scaling Decision Drills

**Q19:** Primary CPU is 35%, p99 is 900ms, and disk read IOPS is 98% saturated. The team wants a bigger primary. What evidence do you ask for before agreeing?

**Q20:** A read replica was added, but checkout p99 got worse. List three ways read replicas can increase latency or inconsistency instead of helping.

**Q21:** The app uses PgBouncer transaction pooling. A developer adds `SET LOCAL app.user_id = ...` and later a function depends on session state. What breaks?

**Q22:** "Shard by customer_id" is proposed for orders. Name two queries that become harder and two that become easier.

**Q23:** You are at Rung 2: indexes tuned, bad queries fixed, replicas used safely. What signals tell you Rung 3 vertical scaling is exhausted?

**Q24:** A team proposes logical sharding by region before product-market fit. What are the operational costs you challenge them on?

**Q25:** Why does adding replicas not increase write throughput for a single Postgres primary?

**Q26:** What is the difference between connection pooling, query caching, read replicas, partitioning, and sharding? Put them in the order you would usually try them.

### B. Replication and Failover Drills

**Q27:** `synchronous_commit=remote_write` is enabled. What has the standby promised, and what has it not promised?

**Q28:** `synchronous_standby_names='ANY 2 (r1,r2,r3)'`. One replica is slow, two are healthy. What happens to writes and why?

**Q29:** A failover promotes a replica with 3 seconds of lag. Which dashboards can look green while the business is still corrupt?

**Q30:** What is the difference between replay lag, write lag, flush lag, and application read staleness?

**Q31:** You need read-your-writes for checkout confirmation. Give two implementation patterns that do not route every read in the company to primary.

**Q32:** Why can replica lag of "only 200ms" still produce user-visible bugs?

**Q33:** A sync replica is in another region. Checkout write latency p99 jumps by 90ms. Explain why and whether you would keep that design.

### C. WAL, CDC, and Outbox Drills

**Q34:** A logical replication slot is inactive. `pg_wal` is growing. Why do streaming replicas look healthy?

**Q35:** What is the first SQL query you run against `pg_replication_slots`, and what columns matter?

**Q36:** Why can `max_slot_wal_keep_size` save the primary and still create a data-platform incident?

**Q37:** Debezium is running, Kafka offsets advance, but OpenSearch is stale. Name three places lag can hide.

**Q38:** Compare transactional outbox vs direct dual-write to DB and Kafka. Which failure does outbox eliminate, and what new operational burden does it add?

**Q39:** A schema migration drops a nullable column. CDC consumer crashes on old payload assumptions. What compatibility rules and deploy order should have prevented this?

**Q40:** Why should high-value payment events not rely only on "best effort" app publish after database commit?

### D. Cassandra and Wide-Column Drills

**Q41:** Cassandra table `events_by_tenant_day` has partition key `(tenant_id, day)`. One enterprise tenant writes 40% of all traffic. What happens and how would you redesign?

**Q42:** Why are large partitions bad even if the cluster has plenty of total disk?

**Q43:** Explain STCS vs LCS vs TWCS at the level needed for incident triage.

**Q44:** A delete-heavy workload has `gc_grace_seconds=10 days` and repair runs monthly. What resurrection risk exists?

**Q45:** What does "read repair" do, and why is it not a substitute for scheduled repair?

**Q46:** A Cassandra node is down for 2 hours during peak. When it returns, p99 gets worse. Explain hinted handoff replay and how to throttle it.

**Q47:** `LOCAL_QUORUM` reads fail in one region but `ONE` succeeds. What is the correctness/availability trade-off of temporarily changing reads to `ONE`?

**Q48:** Why can counters in Cassandra be operationally tricky for inventory or financial counts?

**Q49:** You see `pending_compactions=200`, `SSTables/read=28`, and GC pauses. What is the likely chain from write pattern to read latency?

**Q50:** What five metrics would you put on a Cassandra "do not scale blindly" dashboard?

---

## Part 5: Compound SRE Scenario — "The Black Friday Slot"

```text
THE PAGE (03:47 UTC, Black Friday + 8 hours in):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PagerDuty: [P1] prod-pg-primary-1: disk_used > 85%
             pg_wal volume: 1.6 TB / 2 TB

  Slack #incidents (last 40 minutes, paraphrased):

    03:08  oncall-sre:  "checkout latency spiking, p99 1.2s
                         (normal 80ms). investigating."
    03:11  oncall-sre:  "primary CPU 45%, replicas healthy,
                         replay_lag < 200ms. weird."
    03:14  oncall-app:  "checkout error rate 4%. customers
                         seeing 'order not found' on confirm
                         page after submit."
    03:19  oncall-sre:  "rolled back the 02:00 deploy. no
                         change. p99 still climbing."
    03:26  oncall-sre:  "shared_buffers hit ratio 99.6%,
                         no seq scans in pg_stat_statements
                         top 50. nothing obvious."
    03:33  oncall-data: "search results stale by ~30 min in
                         /search. ES cluster healthy though."
    03:41  oncall-sre:  "checkpoint_completion taking 4×
                         normal. wal volume filling."
    03:47  PagerDuty:   [P1] disk_used > 85%

  THE STAGE:
   - PostgreSQL 15 primary, r6i.16xlarge, 2 TB pg_wal volume.
   - 2 streaming replicas (sync, FIRST 1 (r1, r2)).
   - 1 logical replication slot 'debezium_orders' → Kafka → ES.
   - 1 logical replication slot 'analytics_etl' → ClickHouse.
   - PgBouncer transaction mode in front, 4000 client conns,
     200 backend conns.
   - Black Friday peak: 3.2× normal write volume.

  YOU ARE THE PRINCIPAL ENGINEER joining the bridge at 03:47.
  You have ~13 minutes before disk fills at current rate.
```

### Telemetry Pack

Use this pack to deepen your answer. Do not assume every metric is causal; separate leading indicators, symptoms, and red herrings.

```text
POSTGRES PRIMARY:
  pg_wal volume: 1.6 TB / 2 TB, growth +31 GB/min
  wal_buffers_full: +18k/min
  checkpoint_write_time: 4x baseline
  checkpoint_sync_time: 1.6x baseline
  max_wal_size: 64GB
  archive_command failures: 0
  primary CPU: 45%
  disk write IOPS: 86% of provisioned
  disk read IOPS: 42% of provisioned

STREAMING REPLICAS:
  r1 replay_lag: 160ms
  r2 replay_lag: 190ms
  sync_state: one sync, one potential
  replication slots for physical replicas: none

LOGICAL SLOTS:
  debezium_orders:
    active=true
    restart_lsn lag: 1.42 TB
    confirmed_flush_lsn advancing slowly
    consumer owner: search-platform
  analytics_etl:
    active=false
    restart_lsn lag: 210 GB
    last active: 02:56 UTC

KAFKA / DOWNSTREAM:
  topic dbserver1.public.orders partitions=96 RF=3
  broker disk used: 72%
  Kafka consumer lag for opensearch-indexer: 38M events
  Debezium connector task status: RUNNING
  Debezium source lag: 2h 11m
  OpenSearch indexing bulk rejection: 14%
  search freshness p99: 31 min

CHECKOUT READ PATH:
  order create transaction p99: 160ms -> 880ms
  confirm page read source:
    64% read replica
    36% primary fallback
  "order not found" reports:
    72% within 2s of submit
    91% mobile app version 9.18+
  app passes last_seen_lsn token: false

PGBOUNCER:
  mode=transaction
  client connections: 4000
  server connections: 200
  avg wait for server conn: 90ms -> 540ms
  session variable use detected: search_path, app.tenant_id
```

### Config Pack

```text
postgres:
  synchronous_standby_names='FIRST 1 (r1, r2)'
  max_slot_wal_keep_size=-1
  wal_keep_size=8GB
  idle_replication_slot_timeout=disabled
  hot_standby_feedback=on

debezium_orders:
  snapshot.mode=never
  max.batch.size=2048
  poll.interval.ms=500
  errors.tolerance=none
  table.include.list=public.orders,public.order_items

opensearch-indexer:
  bulk.size=5000
  max.in.flight.requests=8
  retry.backoff.ms=100
  dead_letter_queue=false

checkout-api:
  confirmation_read=replica_preferred
  primary_stickiness_after_write=disabled
  retry_policy=fixed_100ms_3
  pgbouncer_pool_mode=transaction
```

### Decision Points

**T+0 (first 60 seconds):** What SQL do you run, what graph do you pin, and what do you tell the incident commander about risk?

**T+5:** Disk will fill in ~8 minutes. You can drop `analytics_etl`, expand disk, pause checkout writes, or throttle Debezium. What do you choose first and why?

**T+15:** Disk headroom is restored, but search freshness remains 30+ minutes and checkout confirmation still says "order not found." What parallel tracks do you open?

**T+60:** The immediate P1 is mitigated. What data integrity checks prove no orders were lost, and what backlog drain plan avoids re-filling WAL?

### Bad-Fix Gallery

For each proposed fix, write why it is unsafe or incomplete:

1. Restart the Postgres primary to "clear WAL."
2. Drop every logical slot immediately.
3. Increase fan-out/indexer concurrency without checking OpenSearch rejections.
4. Switch all confirmation reads to replicas because primary is busy.
5. Disable synchronous replication during the sale.
6. Vacuum full the orders table during the incident.
7. Set PgBouncer to session mode for every service immediately.
8. Tell Support "search is stale, checkout is fine" without checking read-your-writes.

**Your tasks:**

1. What is the root cause pattern connecting WAL disk growth, healthy streaming replicas, and ES staleness?
2. What exact SQL do you run in the first 60 seconds?
3. You have three levers: drop slot, scale consumer, extend disk + scale consumer. Argue for one path with trade-offs.
4. What do you execute in parallel at minute 7? Be specific (commands/services).
5. Why did customers see "order not found on confirm" when search was stale but checkout reads Postgres?
6. List five post-incident architectural or operational changes with owners.

---

## Part 6: In-Depth Written Questions

Work through these in writing after the scenario. Aim for principal-grade answers.

**Q51 — The Counterfactual:** `max_slot_wal_keep_size = 200GB` had been set before the incident. Walk through minute-by-minute from 02:55 (Debezium throughput drop). Identify: (a) when Postgres invalidates the slot, (b) what on-call sees, (c) recovery path and time, (d) two business contexts where capped WAL is better vs worse than the actual outcome.

**Q52 — The Routing Decision:** Explain the "order not found on confirm" symptom via read-your-writes + PgBouncer transaction pooling. Include: request flow, why `replay_lag < 200ms` does not rule out your hypothesis, two 30-second diagnostic queries, and whether a 10s primary stickiness window would have changed symptoms.

**Q53 — The Design Alternative:** Argue for transactional outbox (Proposal X) vs sharded Postgres + per-shard Debezium (Proposal Y). Cover: which eliminates this failure class, new failure modes, migration cost (4 engineers), and when you'd choose the other anyway.

**Q54 — The Capacity Plan:** CFO funds exactly one of: (i) bigger primary, (ii) more Kafka brokers/partitions, (iii) transactional outbox build, (iv) dedicated data-platform SRE. For each: failure mode addressed vs not, expected P1 reduction, compounding vs one-time relief, your pick and hedge.

---

## Part 7: Capacity Worksheet

Show your math. Approximate answers are fine if assumptions are explicit.

### Worksheet A — WAL Fill Time

Given:

```text
pg_wal free space at 03:47: 400 GB
current WAL growth: 31 GB/min
normal WAL growth: 3 GB/min
disk expansion operation time: 8-12 min
logical slot retained WAL:
  debezium_orders: 1.42 TB
  analytics_etl: 210 GB
```

1. How many minutes until disk fills at current growth?
2. If dropping `analytics_etl` releases 210 GB instantly, how many extra minutes do you buy?
3. If Debezium catches up and growth drops to 8 GB/min, how does the deadline change?
4. What hidden assumption makes "drop slot releases disk instantly" sometimes false?

### Worksheet B — Replica Read Staleness

Given:

```text
checkout create commit LSN: 0/DA7BEEF0
replica replay LSN at confirmation read: 0/DA790000
average replay lag metric: 180ms
mobile confirm request arrives 120ms after commit
```

1. Is the replica safe for this user's confirmation read?
2. Why can average replay lag be misleading?
3. Sketch a last-write-LSN token flow from checkout create to confirmation GET.
4. What is the fallback if the replica has not replayed the token LSN within 200ms?

### Worksheet C — PgBouncer Pool Saturation

Given:

```text
4000 client connections
200 server connections
checkout transaction p95 duration: 80ms normal, 260ms incident
arrival rate: 900 transactions/sec
```

1. Estimate whether 200 server connections should be enough at normal p95.
2. Estimate why the incident p95 creates queueing even if CPU is 45%.
3. Name two query or transaction changes that reduce pool pressure.
4. Name one PgBouncer setting change that would be tempting but dangerous.

### Worksheet D — Cassandra Hot Partition

Given:

```text
inventory table writes: 120k/sec
one tenant/product family: 35% of writes
RF=3
average write payload: 1.2 KB
compaction write amplification: 4x during peak
```

1. Logical writes/sec for the hot family?
2. Replica writes/sec before compaction?
3. Approximate write bandwidth after compaction amplification?
4. Why does this still understate read-path pain?

### Worksheet E — Sharding Readiness

Score the system 0-2 on each axis before approving sharding:

| Axis | 0 | 1 | 2 | Your score |
|------|---|---|---|------------|
| Query patterns known | Unknown/ad hoc | Mostly known | Stable and measured | |
| Shard key candidate | None | One weak | Strong with heat data | |
| Cross-shard transaction plan | None | Manual | Designed/tested | |
| Resharding plan | None | Downtime | Online/double-write | |
| Operational ownership | None | Shared vague | Named team/on-call | |
| Backfill/reconciliation | None | Script | Tested runbook | |

What score would make you say "not yet"?

---

## Part 8: Post-Incident Design Review Prompts

These are short written prompts. They are not asking for definitions; they are asking for engineering judgment.

### A. Scaling Ladder Review

**Q55:** The team says, "We should have sharded six months ago." Write a rebuttal that distinguishes hindsight from evidence-based scaling.

**Q56:** List the exact artifacts you would require before approving a sharding project: dashboards, query inventory, migration plan, rollback plan, and ownership.

**Q57:** What is the smallest reversible change that could reduce checkout p99 next week without changing data topology?

**Q58:** What is the riskiest "simple" change in this incident: bigger instance, more replicas, more Kafka consumers, or dropping a slot? Defend your choice.

### B. Data Correctness Review

**Q59:** Which data in the Black Friday incident is allowed to be stale for 30 minutes, and which data is not? Classify: search results, checkout confirmation, payment capture, seller analytics, inventory display.

**Q60:** If an order row exists but the search document is missing, what should customer support say? What should the system do automatically?

**Q61:** If the search document exists but the order row is missing, why is that more alarming?

**Q62:** How do you prove no orders were lost when the primary nearly ran out of WAL disk?

### C. Cassandra Design Review

**Q63:** A product manager asks for "delete all abandoned carts older than 7 days" every hour. How do you design this in Cassandra without creating a tombstone storm?

**Q64:** A tenant wants a dashboard sorted by all events across all users for the last 24 hours. Why is this not a good primary-table query in Cassandra?

**Q65:** What table would you build for `events_by_tenant_hour`, and how would you avoid one large enterprise tenant creating one massive partition?

**Q66:** What is the operational consequence of lowering `gc_grace_seconds` to 1 hour without proving repair cadence?

### D. CDC and Search Review

**Q67:** Search Platform wants exactly-once indexing from Debezium to OpenSearch. What does "exactly once" realistically mean at the OpenSearch document level?

**Q68:** What idempotency key should the indexer use for order documents?

**Q69:** Why is a dead-letter queue better than crashing forever on one malformed CDC event, and what is the danger of ignoring the event?

**Q70:** When should the team rebuild OpenSearch from a Postgres snapshot instead of trying to drain CDC lag?

### E. Runbook Review

**Q71:** Write the first five lines of the incident runbook for "logical slot WAL retention threatening primary disk."

**Q72:** Who must be on the bridge within 10 minutes? Name roles, not people.

**Q73:** What is the one graph the incident commander should keep visible for customer impact, and what is the one graph for primary survival?

**Q74:** What customer-facing status wording is honest without over-disclosing internals?

### F. Interview Synthesis

**Q75:** In a 45-minute system design interview, where would you introduce CDC and search indexing in an e-commerce design?

**Q76:** Where would you explicitly state that checkout confirmation must be read-your-writes?

**Q77:** How would you explain the difference between "scale reads with replicas" and "scale writes with sharding" without sounding dogmatic?

**Q78:** What single sentence summarizes the lesson of Week 5 database scaling?

---

## Self-Score Error-Type Table

| Error type | Count | Notes to review |
|------------|-------|-----------------|
| Scaling ladder/sharding error | | |
| Replication/failover error | | |
| WAL/logical slot error | | |
| CDC/outbox/schema evolution error | | |
| Cassandra partition/tombstone error | | |
| PgBouncer/read-your-writes error | | |
| Capacity math error | | |
| Incident sequencing/runbook gap | | |

---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**  
> [`../answers/Retention-Tests/Week-05 Answers.md`](../answers/Retention-Tests/Week-05 Answers.md)

