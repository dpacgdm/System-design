# Answer Key — Week-05

> Open only after attempting the learner file questions.

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

---

## Extended Answer Key for Added Week-05 Material

Use the linked Week 5 worked-answer files for the original short test. The sections below cover the newly added rapid-fire, expanded Black Friday scenario, capacity worksheet, and post-incident prompts.

---

## Part 4: Extended Rapid-Fire Model Answers

### A. Scaling Decision Drills

**Q19:** Disk read IOPS saturation points to storage/query access pattern, not CPU. Ask for top queries by total time, buffer hit ratio by query, `pg_stat_io`, index usage, checkpoint/IO wait, and whether p99 aligns with read bursts or locks.

**Q20:** Replicas can hurt if reads become stale, if cross-AZ/network latency is higher, or if the app now waits on replica routing/pool contention. They also add replication load and can hide read-your-writes bugs.

**Q21:** Transaction pooling does not preserve session state between transactions. Any reliance on `search_path`, temp tables, prepared statements, or per-session variables can leak, disappear, or apply to the wrong transaction.

**Q22:** Easier: user order history and per-customer checkout/order writes. Harder: global revenue by day, fraud scans across customers, seller-wide views when seller spans shards, and cross-customer analytics.

**Q23:** Rung 3 is exhausted when the largest safe instance/storage tier is near CPU/IO/memory limits, vertical changes no longer reduce p99, write throughput is primary-bound, and headroom/cost/maintenance windows are unacceptable.

**Q24:** Challenge cross-region transactions, resharding, migrations, backups, schema changes, analytics, joins, incident debugging, tenant moves, and on-call maturity. Early sharding creates permanent complexity before evidence demands it.

**Q25:** A single primary still serializes writes through WAL, locks, indexes, constraints, and storage. Replicas copy writes; they do not accept independent writes for the same dataset.

**Q26:** Usual ladder: connection pooling, query/index tuning, caching for safe reads, read replicas for read-heavy paths, partitioning within the database, then sharding. Pooling manages connections; caching avoids reads; replicas scale reads; partitioning manages tables/indexes; sharding splits ownership across databases.

### B. Replication and Failover Drills

**Q27:** `remote_write` means WAL reached standby OS/kernel buffers, not necessarily flushed to durable disk or replayed. A standby crash can still lose what was not flushed.

**Q28:** `ANY 2` lets writes proceed when any two of the three standbys acknowledge, so one slow replica does not block writes if two healthy replicas remain. It trades deterministic standby choice for availability/latency.

**Q29:** Replica lag, DB health, and HTTP 2xx dashboards can look green while acknowledged writes are missing after promotion. Business correctness dashboards like payment/ledger/order reconciliation reveal corruption.

**Q30:** Write lag is WAL sent delay; flush lag is durable-on-standby delay; replay lag is applied-to-queryable-state delay. Application read staleness includes routing, transaction timing, cache, and whether a specific commit LSN is visible.

**Q31:** Use primary stickiness for a short window after write, or pass a last-seen LSN/session token and route to a replica only after it has replayed that LSN. Some systems also use per-user write-through cache invalidation.

**Q32:** A confirmation read can arrive 20ms after commit and hit a replica 200ms behind. Average lag hides per-replica/per-LSN tail behavior.

**Q33:** Synchronous cross-region replication adds WAN round-trip latency to every commit and couples checkout availability to remote region health. Keep it only for rare data classes that require multi-region zero data loss; most checkout OLTP uses local sync plus async DR.

### C. WAL, CDC, and Outbox Drills

**Q34:** Logical slots retain WAL until the logical consumer confirms flush. Physical streaming replicas can be caught up because they use a different replication mechanism and are not blocking logical slot retention.

**Q35:** Query `pg_replication_slots` for `slot_name`, `active`, `restart_lsn`, `confirmed_flush_lsn`, and retained bytes via `pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)`. Also identify slot owner/purpose.

**Q36:** A cap prevents primary disk exhaustion by invalidating the slot. The downstream consumer then cannot resume from the retained WAL and needs a snapshot/rebuild, creating a data freshness or rebuild incident.

**Q37:** Lag can hide between Postgres and Debezium source offset, Debezium and Kafka, Kafka consumer group and indexer, indexer bulk rejections/retries, or OpenSearch refresh/merge backlog.

**Q38:** Outbox eliminates DB-commit-success/Kafka-publish-fail dual-write loss. It adds an outbox table, publisher/CDC ops, idempotent consumers, retention cleanup, and lag monitoring.

**Q39:** Use backward/forward-compatible schema evolution: add nullable fields first, deploy consumers that tolerate both schemas, then stop producing old field, then drop later. Schema Registry compatibility would reject incompatible drops.

**Q40:** App publish after commit can fail during process crash, network issue, or broker outage while the payment write remains committed. High-value events need an atomic outbox or ledger-driven reconciliation.

### D. Cassandra and Wide-Column Drills

**Q41:** `(tenant_id, day)` makes the enterprise tenant/day a huge hot partition. Add bucketing such as `(tenant_id, day, bucket)` or partition by tenant+hour+hash, and query/merge buckets deliberately.

**Q42:** Large partitions create wide reads, large indexes, compaction pressure, memory/GC pressure, and slow repair/streaming. Total cluster disk can be fine while one replica set is overloaded.

**Q43:** STCS groups similarly sized SSTables and is write-friendly but can cause read amplification. LCS keeps levels and improves reads at higher write amp. TWCS groups by time windows and is good for TTL time-series if queries align with windows.

**Q44:** If repair runs monthly but tombstones expire after 10 days, a replica that missed a delete can later reintroduce deleted data during repair/read. This is zombie resurrection.

**Q45:** Read repair fixes inconsistent replicas observed during reads. It is probabilistic and workload-dependent, so cold data may never be repaired before tombstones expire.

**Q46:** Hinted handoff stores missed writes on other nodes and replays them when the node returns. Throttle hint delivery, restore during lower traffic, monitor pending hints, and avoid letting replay compete unbounded with live traffic.

**Q47:** `ONE` improves availability and latency but can return stale/missing data and break quorum overlap. It may be acceptable for noncritical display reads, not for inventory/payment correctness without explicit business signoff.

**Q48:** Cassandra counters have special consistency/repair semantics and are hard to make idempotent under retries. Inventory/finance usually need explicit ledger/reservation records rather than blind distributed increments.

**Q49:** A hot/write-heavy pattern creates many SSTables and tombstones; compaction cannot keep up; reads touch many SSTables and tombstones; GC pauses increase; p99 rises and timeouts create retries.

**Q50:** Hot partitions/top keys, p99 by table, pending compactions, SSTables per read, tombstones per read, coordinator timeouts, dropped mutations, hints pending, disk/IO, repair age, and GC pauses.

---

## Expanded Black Friday Scenario - Expert Analysis

### Root Cause Pattern

The connecting pattern is **logical replication slot WAL retention**. Streaming replicas are healthy because physical replication is caught up, but logical slots retain WAL independently until their consumers confirm flush. Search is stale because Debezium/OpenSearch is behind; the primary is endangered because retained WAL cannot be recycled.

### First 60 Seconds

Run:

```sql
SELECT
  slot_name,
  plugin,
  slot_type,
  active,
  restart_lsn,
  confirmed_flush_lsn,
  pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained,
  pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes
FROM pg_replication_slots
ORDER BY retained_bytes DESC;

SELECT application_name, state, sync_state, write_lag, flush_lag, replay_lag
FROM pg_stat_replication;
```

Pin graphs: pg_wal free bytes/time-to-full, retained bytes per slot, Debezium source lag, OpenSearch bulk rejection, checkout p99 and confirmation error rate. Tell IC: "Primary survival deadline is minutes; streaming replicas being green does not reduce WAL slot risk."

### T+5 Decision

First, buy time without destroying the highest-value CDC path. Dropping inactive `analytics_etl` is often the cleanest first move if it is noncritical and owner agrees, buying about 210GB. In parallel, expand disk because it is reversible headroom. Do not throttle Debezium if it is the only path draining `debezium_orders`; instead fix downstream bottleneck or temporarily reduce low-priority indexing.

If disk cannot be expanded fast enough and the primary will die, dropping a logical slot may be justified. Prefer dropping the least critical/inactive slot before `debezium_orders`.

### T+15 Tracks

Track 1: primary safety and CDC drain. Keep WAL growth below free-space slope, scale/fix indexer only to the point OpenSearch accepts bulk writes, and monitor retained bytes.

Track 2: checkout correctness. Stop replica-preferred confirmation reads; add primary stickiness or LSN token route. Investigate PgBouncer transaction pooling/session-variable bugs separately.

Track 3: search freshness. Communicate stale search, shed low-priority indexing, and drain CDC after OpenSearch rejection is resolved.

### T+60 Data Integrity Checks

- Count orders committed in Postgres by time window vs application request ids.
- Verify no sequence gaps that imply missing committed rows.
- Compare outbox/CDC high-water marks with table counts.
- Rebuild search deltas from a snapshot plus CDC if needed.
- Audit payment/order confirmation for read-your-writes failures separately from data loss.

### Bad-Fix Gallery Answers

1. Restart primary: WAL files do not disappear; restart risks longer outage.
2. Drop every slot: saves disk but destroys CDC resume for search/analytics and may require full rebuilds.
3. Increase indexer concurrency blindly: OpenSearch already rejects bulk; more concurrency worsens retries.
4. Switch confirms to replicas: worsens read-your-writes bugs.
5. Disable sync replication: may improve latency but increases data-loss risk during sale.
6. Vacuum full: exclusive locks and huge IO; not for active incident.
7. PgBouncer session mode globally: may explode server connections and primary memory.
8. "Search stale, checkout fine": false until confirmation read path is checked.

---

## Part 6: In-Depth Written Answer Sketches

**Q51:** With a 200GB cap, Postgres invalidates the slot once retained WAL exceeds the cap. On-call sees Debezium fail with missing WAL/slot invalidation and search stops catching up from CDC. Recovery requires fresh snapshot or rebuild from source tables plus resume from a new slot. Better when primary survival matters more than downstream continuity; worse when CDC is the only low-cost way to keep a critical read model current.

**Q52:** The create request commits on primary and returns before the replica has replayed that commit. The confirm GET routes to a replica without LSN token/stickiness and may miss the order. `replay_lag <200ms` is average/current, not proof that this specific commit is visible. Diagnostics: compare `pg_last_wal_replay_lsn()` to token LSN on replica; sample confirm errors with commit timestamp/source. A 10s primary stickiness window likely fixes most immediate confirmations.

**Q53:** Transactional outbox removes the logical slot as the sole integration point for business events if implemented on the write path and drained independently. It adds table growth, publisher lag, cleanup, and consumer idempotency needs. Sharded Postgres plus per-shard Debezium distributes load but multiplies slots/connectors and operational complexity. Choose sharding for true write scale; choose outbox for correctness and simpler event publication.

**Q54:** Bigger primary buys time but not logical-slot failure prevention. More Kafka brokers help if Kafka is bottleneck, not if OpenSearch rejects. Transactional outbox removes dual-write gaps and can scope event flow but does not fix all search lag. Dedicated data-platform SRE improves ownership/runbooks and likely reduces P1s across CDC. Pick depends on evidence; for this incident, outbox plus owner/runbook is the best compounding investment.

---

## Part 7: Capacity Worksheet Answers

### Worksheet A

1. `400GB / 31GB/min = 12.9 min`.
2. New free space `610GB`; `610 / 31 = 19.7 min`, so about 6.8 extra minutes.
3. `610 / 8 = 76.25 min`; if no slot dropped, `400 / 8 = 50 min`.
4. Space may not return instantly if WAL is also needed by another slot, archiving, checkpoints/recycling behavior, filesystem accounting, or the dropped slot was not the oldest retained LSN.

### Worksheet B

1. No. Replica replay LSN `0/DA790000` is behind commit LSN `0/DA7BEEF0`.
2. Average lag is not per-user/per-LSN and hides tails.
3. Create returns `last_commit_lsn`; client sends it on confirmation; router selects a replica whose replay LSN >= token or primary.
4. Fallback to primary or wait up to budget then primary.

### Worksheet C

1. Normal rough concurrency: `900/sec * 0.080s = 72` active transactions, so 200 should be enough at p95.
2. Incident rough concurrency: `900 * 0.260 = 234`, exceeding server connections and causing pool queueing even with low CPU.
3. Shorten transactions, remove chatty queries, add indexes, batch reads, avoid holding transactions across network calls.
4. Raising server connections blindly can overwhelm Postgres memory/context switching.

### Worksheet D

1. `120k * 0.35 = 42k logical writes/sec`.
2. `42k * RF3 = 126k replica writes/sec`.
3. `126k * 1.2KB * 4 = 604,800KB/sec`, about 590MB/sec before overhead.
4. It ignores reads touching tombstones/SSTables, GC, repair, hints, coordination, and skew on a small replica set.

### Worksheet E

"Not yet" if any critical axis is 0, or total score is below about 9/12. A strong sharding approval needs stable query patterns, a measured shard key, transaction/reshard/backfill plans, and named on-call ownership.

---

## Part 8: Post-Incident Design Review Answer Sketches

**Q55:** "Sharding might be necessary later, but this incident was logical slot retention plus read-your-writes and downstream indexing backpressure. Sharding without fixing CDC ownership and confirmation routing would create more slots and more places to fail."

**Q56:** Required artifacts: query inventory, top write/read paths, shard-key heat analysis, cross-shard transaction design, resharding plan, dual-write/backfill plan, rollback strategy, data reconciliation tests, dashboards, and named owning team.

**Q57:** Add LSN-token/primary-stickiness for confirmation reads, fix top slow query/index, or reduce transaction duration. These are reversible and targeted.

**Q58:** Dropping a slot is riskiest for data platform continuity; disabling sync replication is riskiest for data durability. The answer should tie risk to business data class.

**Q59:** Search and seller analytics can be stale with disclosure. Checkout confirmation, payment capture, and inventory reservation cannot be casually stale because they affect money/customer commitments.

**Q60:** Support can say order is confirmed but search/confirmation display is delayed; system should repair read model/index from source of truth.

**Q61:** Search doc without order row suggests phantom derived state or source-of-truth loss; derived systems should not invent orders.

**Q62:** Reconcile primary table counts, WAL/backup continuity, order ids/request ids, payment records, outbox entries, and customer-visible confirmations.

**Q63:** Prefer TTL with TWCS/time-bucketed tables or mark abandoned by status in a new table; avoid hourly mass deletes over wide partitions.

**Q64:** Cassandra primary tables serve known partition-key queries, not global sorted scans across users. Build an analytics/search table or warehouse.

**Q65:** Use `(tenant_id, hour, bucket)` with bucket derived from user/event hash; query known buckets and merge.

**Q66:** Deletes can resurrect if a replica misses tombstones and repair does not run before grace expires.

**Q67:** It means idempotent final document state by deterministic document id/version, not magical exactly-once network execution.

**Q68:** Use stable order id as document id plus version/LSN for idempotent updates.

**Q69:** DLQ isolates poison events and lets the stream continue; ignoring events silently corrupts the index.

**Q70:** Rebuild when lag is too large, slot invalidated, mappings changed incompatibly, or index correctness is untrusted.

**Q71:** Example first lines: check time-to-full; identify retained slots; page DB/search owners; stop risky deploys; choose buy-time lever.

**Q72:** Incident commander, DBA, search/data-platform owner, checkout owner, SRE, support/comms, and product/business owner.

**Q73:** Customer impact: checkout success/confirmation errors. Primary survival: WAL free bytes/time-to-full or retained bytes by slot.

**Q74:** "Some search and order-confirmation views are delayed. Orders are being verified against the source of truth; we will update affected customers as reconciliation completes."

**Q75:** After core OLTP write path, introduce CDC/search as async read model, not source of truth.

**Q76:** In API/read-path requirements and again during replica/caching discussion.

**Q77:** "Replicas copy data to serve more reads; sharding splits ownership so writes are distributed, but cross-shard work becomes harder."

**Q78:** "Scale databases by removing avoidable load and preserving correctness first; topology changes come only after measured bottlenecks and operational readiness."

---

## Updated 85% Gate

```text
Part 1 original recall (Q1-Q18):       18 points
Extended rapid-fire (Q19-Q50):         24 points
Expanded scenario decisions:           22 points
Capacity worksheet:                    16 points
Post-incident design review:           12 points
Self-score quality / review plan:       8 points

Pass: 85%+
Review before moving on: below 70%, or any critical miss on
  - logical slot WAL retention
  - read-your-writes on checkout confirmation
  - Cassandra hot partitions/tombstones
  - sharding as a last-resort topology change
```
