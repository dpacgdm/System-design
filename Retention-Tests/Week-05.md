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

## Part 4: Compound SRE Scenario — "The Black Friday Slot"

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

**Your tasks:**

1. What is the root cause pattern connecting WAL disk growth, healthy streaming replicas, and ES staleness?
2. What exact SQL do you run in the first 60 seconds?
3. You have three levers: drop slot, scale consumer, extend disk + scale consumer. Argue for one path with trade-offs.
4. What do you execute in parallel at minute 7? Be specific (commands/services).
5. Why did customers see "order not found on confirm" when search was stale but checkout reads Postgres?
6. List five post-incident architectural or operational changes with owners.

---

## Part 5: In-Depth Written Questions

Work through these in writing after the scenario. Aim for principal-grade answers.

**Q19 — The Counterfactual:** `max_slot_wal_keep_size = 200GB` had been set before the incident. Walk through minute-by-minute from 02:55 (Debezium throughput drop). Identify: (a) when Postgres invalidates the slot, (b) what on-call sees, (c) recovery path and time, (d) two business contexts where capped WAL is better vs worse than the actual outcome.

**Q20 — The Routing Decision:** Explain the "order not found on confirm" symptom via read-your-writes + PgBouncer transaction pooling. Include: request flow, why `replay_lag < 200ms` does not rule out your hypothesis, two 30-second diagnostic queries, and whether a 10s primary stickiness window would have changed symptoms.

**Q21 — The Design Alternative:** Argue for transactional outbox (Proposal X) vs sharded Postgres + per-shard Debezium (Proposal Y). Cover: which eliminates this failure class, new failure modes, migration cost (4 engineers), and when you'd choose the other anyway.

**Q22 — The Capacity Plan:** CFO funds exactly one of: (i) bigger primary, (ii) more Kafka brokers/partitions, (iii) transactional outbox build, (iv) dedicated data-platform SRE. For each: failure mode addressed vs not, expected P1 reduction, compounding vs one-time relief, your pick and hedge.

---

## Scoring Guide (self-check after worked answers)

```text
Part 1 (Q1–Q5):     4/5+  → Weeks 1–4 still solid
Part 2 (Q6–Q15):    8/10+ → Week 5 scaling module retained
Part 3 (Q16–Q18):   2/3+  → Cassandra internals retained
Part 4 (scenario):    Principal depth on diagnosis + sequencing
Part 5 (Q19–Q22):   Trade-off reasoning, not checklist answers

Overall:
  Ready for Week 6  → 85%+ across parts
  Review Week 5     → below 70% on Parts 2–3
  Review Weeks 2–4  → below 60% on Part 1
```

---

> **Worked answers:**
> - [Database Scaling Patterns Worked Answers](../Week-05-Database-Internals/Database%20Scaling%20Patterns%20Worked%20Answers.md)
> - [Cassandra Architecture Worked Answers](../Week-05-Database-Internals/Cassandra%20Architecture%20Worked%20Answers.md)
