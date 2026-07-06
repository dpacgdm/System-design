# Week 5, Topic 2 — Database Scaling Patterns: Worked Answers

> Principal-grade answers to the Four In-Depth Questions in
> `Database Scaling Patterns.md` (Part 23), plus the Black Friday Slot
> scenario (Parts 21–22). Attempt them yourself first — the value is in
> the reasoning, not the conclusion. Each answer separates the "easy
> answer" from the "principal answer."

---

## Scenario Recap (Parts 21–22)

```
The Black Friday Slot incident (the shared context for all 4 questions):

  02:55  Debezium consumer throughput drops (ES ingest can't keep up).
  →      Postgres replication SLOT for the Debezium connector stops
         advancing (consumer not confirming LSNs).
  →      Postgres must RETAIN all WAL since the slot's confirmed LSN.
         WAL directory (pg_wal) grows unbounded.
  03:14  Customers report "order not found on confirm page after submit."
  →      Disk fills toward 100% on the PRIMARY. If pg_wal fills the
         volume, the PRIMARY STOPS ACCEPTING WRITES (hard outage).

Root cause class: a SLOW/STALLED CDC CONSUMER turns into a PRIMARY-DB
disk-exhaustion outage via unbounded replication-slot WAL retention
(Part 7 "slot bloat" + Part 14 "CDC failure modes").
```

---

## Question 1 — The Counterfactual (`max_slot_wal_keep_size = 200GB`)

**What the question tests:** that the WAL cap is not "the right answer" but
a *trade between two failure modes* — unbounded disk growth vs. broken CDC.

### (a) The exact moment Postgres invalidates the slot

`max_slot_wal_keep_size` bounds how much WAL Postgres will retain for a
slow slot. Timeline from 02:55:

```
02:55  Debezium throughput drops. Slot's confirmed_flush_lsn freezes.
       WAL begins accumulating behind that LSN.
       Retained WAL grows at (write rate − 0) = full Black Friday write rate.
       Say ~15 GB/min of WAL during peak.
02:55 → ~03:08  ~13 minutes to accumulate 200 GB (at 15 GB/min).
~03:08 The retained WAL for the slot crosses 200 GB.
       Postgres INVALIDATES the slot (pg_replication_slots.wal_status =
       'lost'; the slot is marked invalid). It then REMOVES the WAL it was
       only keeping for that slot — disk pressure is relieved.
```

The precise trigger is retained-WAL-for-slot exceeding the cap, checked at
checkpoint / WAL-recycle time — so it fires at the next checkpoint after
crossing 200 GB, not to the exact byte.

### (b) What the on-call SRE sees, and on which dashboard

```
- RDS/CloudWatch (or node exporter): FreeStorageSpace stops its steep
  decline and RECOVERS (the retained WAL is freed). Disk-full outage AVOIDED.
- Postgres: `SELECT slot_name, wal_status, active FROM pg_replication_slots;`
  → wal_status = 'lost' for the Debezium slot.
- Log line: "terminating process ... to release replication slot" / slot
  invalidation warning in the Postgres log.
- Debezium/Kafka Connect: connector task FAILS with "requested WAL segment
  has already been removed" — it can no longer resume from its last LSN.
- ES search: now permanently stale for the gap (no new CDC events) until
  the connector is rebuilt with a fresh snapshot.
```

So the SRE sees a *healthy primary* but a *dead CDC pipeline*.

### (c) The recovery path and its time cost

```
1. Primary is healthy — no write outage. (This is the whole point.)
2. Rebuild the Debezium connector: drop the invalid slot, create a new
   slot, and trigger a NEW INITIAL SNAPSHOT of the orders table into ES
   (or a filtered incremental snapshot for the affected window).
3. Snapshot cost = table size / snapshot throughput. For a large orders
   table this is tens of minutes to hours, during which ES is stale.
4. Backfill/verify: reconcile ES against Postgres for the gap window.

Time cost: minutes to invalidate + snapshot/backfill hours. Search stale
throughout, but ORDERS (source of truth in Postgres) are never at risk.
```

### (d) Better or worse than what actually happened — and two flips

**Default (no cap):** disk fills → **primary stops accepting writes** →
checkout is down → lost revenue during Black Friday. Catastrophic, but CDC
is intact once you drain it.

**With cap:** primary survives; **CDC dies and search goes stale**. Degraded,
not down.

```
Business context that FLIPS the answer:

  FLIP 1 — Search staleness is business-critical (e.g., the app READS from
    ES for the confirm page / inventory availability). Then a "stale search"
    is effectively a customer-facing outage anyway, and losing CDC silently
    may be WORSE than a loud disk alert you'd have caught earlier. Here the
    cap trades a visible failure for an invisible one.

  FLIP 2 — Orders/checkout must never stop (payments in flight, regulatory).
    Then keeping the primary alive at ALL costs is right, and the cap is
    unambiguously better: sacrifice the derivative (search) to protect the
    source of truth (orders).
```

**Principal takeaway:** the cap converts a *source-of-truth outage* into a
*derived-system outage*. That is almost always the right trade — but only
if you also ALERT on slot lag early (so you fix the consumer before either
failure mode triggers). The cap is a backstop, not a strategy.

---

## Question 2 — The Routing Decision (stale confirm page, replay_lag < 200ms)

**What the question tests:** Part 6.3 (replica routing) + Part 8
(read-your-writes via LSN) integration. The easy answer blames replica lag;
`replay_lag < 200ms` rules that out.

### (a) The exact request flow that fails

```
1. Client POSTs /checkout → write goes to PRIMARY, commits at LSN = L.
2. App is supposed to capture L (the commit LSN) and pass it to the
   confirm-page read so the read waits for a replica that has replayed ≥ L.
3. Client GETs /order/confirm → read routed to a READ REPLICA.
4. Read-your-writes contract: replica must have replay_lsn ≥ L. If the
   app fails to capture/propagate L, the read has no barrier and can land
   on a replica that hasn't yet applied the order row → "order not found."

Where L can be lost:
  - Not captured after COMMIT (needs pg_current_wal_lsn() / RETURNING).
  - Lost across service hops (not put in the request context / header).
  - Captured on the WRONG connection (see (b)).
```

### (b) Why LSN-routed reads still fail with replay_lag < 200ms

Because the failure is not lag — it's **capturing the wrong LSN**, and the
prime suspect is **PgBouncer in transaction-pooling mode** (Part 5.3):

```
- In transaction pooling, the app's "connection" is a PgBouncer-managed
  session multiplexed over many real server connections.
- If the app runs COMMIT, then a SEPARATE `SELECT pg_current_wal_lsn()`
  to capture L, PgBouncer may route that second statement to a DIFFERENT
  server backend than the one that did the commit.
- That backend can report an LSN that does NOT reflect the just-committed
  order (or an unrelated position). The captured L is wrong/too-early.
- The confirm read then "waits" for a bogus barrier that a replica already
  satisfies → reads a replica missing the order → "order not found."

So replay_lag is genuinely < 200ms (replicas are fine); the barrier value
itself is corrupt because it was captured on the wrong pooled backend.
```

Secondary suspect: capturing L outside the write transaction (a
non-atomic "commit then ask for LSN" instead of `RETURNING pg_current_wal_lsn()`
or capturing inside the txn).

### (c) Two 30-second diagnostic queries on the replica

```sql
-- 1. Is the replica actually behind the write's LSN, or ahead?
--    Compare the replica's replay position to the LSN the app captured.
SELECT pg_last_wal_replay_lsn() AS replica_replayed,
       :captured_lsn AS app_captured_lsn,
       pg_wal_lsn_diff(pg_last_wal_replay_lsn(), :captured_lsn) AS bytes_ahead;
-- If bytes_ahead >= 0, the replica HAS the data → routing/barrier bug,
-- not lag. (Confirms the hypothesis: not a lag problem.)

-- 2. Does the row actually exist on this replica right now?
SELECT id, created_at FROM orders WHERE id = :order_id;
-- If present on the replica but the user saw "not found", the read hit a
-- DIFFERENT replica or fired before the barrier → routing/LSN-capture bug.
```

If (1) shows the replica already past the captured LSN and (2) shows the
row present, the replica is innocent — the bug is LSN capture/routing.

### (d) Would the time-window (10s sticky-primary) strategy behave differently?

Yes, and better for this incident:

```
Time-window stickiness: for N seconds after a user's write, route THAT
user's reads to the PRIMARY (no LSN needed).

- The confirm page read (seconds after checkout) would go to the PRIMARY,
  which definitionally has the order → NO "order not found."
- It sidesteps the PgBouncer LSN-capture bug entirely (no LSN to capture).
- Cost: primary read load spikes during the sticky window (fine for
  low-QPS confirm pages; watch it for hot write paths).
- Tradeoff: coarser than LSN routing (some reads needlessly hit primary),
  but far more robust to pooling quirks.
```

**Principal takeaway:** LSN read-your-writes is elegant but fragile under
transaction pooling. For "read immediately after my own write" UX, a short
sticky-primary window is simpler and harder to break.

---

## Question 3 — The Design Alternative (Outbox vs. Sharded Debezium)

**What the question tests:** Parts 11 (sharding), 13 (CQRS), 14 (CDC
failure). Does the change eliminate the failure CLASS or just parallelize it?

### (a) Which eliminates the class vs. mitigates

```
PROPOSAL X (Transactional Outbox): ELIMINATES the class.
  The pipeline no longer depends on Postgres retaining WAL for a slow
  consumer. The app writes order + tiny outbox row in ONE transaction; a
  poller reads the outbox TABLE and publishes. If the publisher is slow,
  the OUTBOX TABLE grows (bounded, cheap, on its own storage) — it does
  NOT pin pg_wal and cannot fill the primary's WAL volume. The
  disk-exhaustion-from-slow-consumer failure mode is gone.

PROPOSAL Y (Sharded Debezium, 8 shards, 8 slots): only MITIGATES.
  Each shard still has a replication slot that bloats if ITS consumer
  stalls. You now have 8 ways to hit the exact same failure — and a single
  hot shard (celebrity seller, one popular SKU) recreates it on that shard.
  It divides the blast radius by ~8 but does not remove the mechanism.
```

### (b) New failure modes each introduces

```
X (Outbox):
  - Dual-write-in-one-txn is fine, but the POLLER can double-publish →
    consumers must be idempotent (dedupe by outbox id / event id).
  - Outbox table bloat + vacuum pressure if the poller lags (bounded,
    but must be monitored + purged after publish).
  - Ordering: single poller = ordered but a throughput ceiling; parallel
    pollers need partitioned ordering keys.

Y (Sharded Debezium):
  - 8× operational surface: 8 connectors, 8 slots, 8 snapshot/rebuild
    procedures, cross-shard ordering is now undefined.
  - Cross-shard queries/transactions (Part 12) become app problems.
  - Rebalancing/adding shards is a heavy migration.
  - The primary-disk failure mode still exists per shard.
```

### (c) Migration cost, team of 4

```
X (Outbox): ~2–3 eng-months.
  - Add outbox table + write it inside existing order txns.
  - Build/borrow an outbox-publisher service (poll → Kafka, mark sent).
  - Make ES/Kafka consumers idempotent. Backfill/cutover.
  Mostly application work; no data re-partitioning.

Y (Sharded Debezium): ~6–9+ eng-months.
  - Shard the orders table (Citus or app-level), migrate data (biggest
    cost + risk), reshape every query, run 8 connectors, redo runbooks.
  - Sharding is the most invasive rung (Part 11). You take on it AND keep
    the CDC fragility.
```

### (d) When you'd choose the other (Y) anyway

```
Choose Y despite its cost if the REAL constraint is that the PRIMARY is
already WRITE-SATURATED for reasons unrelated to CDC (Part 11 territory) —
i.e., you need to shard for write throughput regardless. Then sharding is
happening anyway, and per-shard Debezium is the incremental CDC design.
In that world, ALSO add the outbox per shard to fix the CDC class — the
two are not mutually exclusive; Y is orthogonal infrastructure you needed.
```

**Principal takeaway:** X fixes the *cause* (shrink the payload the pipeline
must carry — tiny outbox rows vs. full WAL) and removes the coupling to
pg_wal. Y gives you 8 parallel copies of the same failure. Prefer X unless
you must shard for write scale anyway — then do both.

---

## Question 4 — The Capacity Plan (fund exactly ONE)

**What the question tests:** judgment under economic constraint — the actual
principal job. Easy answer buys hardware; principal answer eliminates the
failure class and notices the dependency graph.

### (a) Failure mode each option addresses / does NOT

```
(i)  r6i.16xl → r6i.32xl ($60K/yr):
     Addresses: raw write/IOPS/connection headroom on the primary.
     Does NOT address: slot bloat / CDC coupling. Disk still fills if a
       consumer stalls — just at a higher volume next year.

(ii) +16 Kafka brokers, 3× CDC partitions ($45K/yr):
     Addresses: Kafka/consumer throughput (helps the "consumer can't keep
       up" trigger by raising ES ingest ceiling).
     Does NOT address: the primary-disk mechanism if a consumer STILL
       stalls (bad deploy, ES outage). Reduces likelihood, not the class.

(iii) Transactional outbox + publisher (~3 eng-mo, $20K/yr):
     Addresses: the FAILURE CLASS — decouples CDC from pg_wal entirely.
     Does NOT address: primary write saturation from real order growth
       (that's a rung-1..5 problem, not this one).

(iv) +1 data-platform SRE ($220K/yr):
     Addresses: CAPACITY TO BUILD/OPERATE the above; faster detection and
       response; better runbooks/alerts.
     Does NOT address: any failure mode directly by itself.
```

### (b) Expected P1 reduction per year (stated assumptions)

```
Assume: 3 data-platform P1s/year historically; ~1/year is this
slot-bloat/CDC class, ~1 is write-saturation, ~1 is misc/human.

(i)   ~0.3 P1/yr avoided now (headroom), but re-emerges at higher volume;
      net ~0.3 this year, ~0 compounding.
(ii)  ~0.4 P1/yr avoided (lower chance the consumer stalls); does not
      remove the class.
(iii) ~1.0 P1/yr avoided (removes the slot-bloat class outright) and it
      STAYS removed as volume grows.
(iv)  ~0.5–1.0 P1/yr avoided via faster detection + enabling (iii); large
      but INDIRECT and hard to attribute.
```

### (c) Compounding vs one-time

```
Compounding (helps this year AND future years):
  (iii) outbox — the failure class is gone permanently.
  (iv)  SRE — capacity compounds (builds iii, then next fixes).

One-time relief (buys headroom for the SAME failure at higher volume):
  (i)  bigger instance.
  (ii) more brokers/partitions (raises a ceiling that growth re-approaches).
```

### (d) What I'd choose, and the hedge

```
CHOICE: (iii) transactional outbox — it eliminates the failure CLASS with
the lowest recurring cost ($20K/yr) and compounds.

But the dependency graph is iv → iii: with the current team at capacity,
"3 eng-months" may never materialize. So my REAL recommendation to the CFO
is sequenced:

  If forced to pick literally one: (iii), and I renegotiate scope so the
  existing team can ship it (cut a smaller MVP outbox for the orders table
  only). 

  If I can influence the framing: fund (iv) FIRST when the constraint is
  execution capacity, because without an owner, (iii) stays a ticket. (iv)
  then delivers (iii) and future fixes.

HEDGE (because my P1-reduction estimates in (b) may be wrong):
  - Ship the cheap backstop NOW regardless of funding: set
    max_slot_wal_keep_size (Q1) + slot-lag alerting. This caps the
    downside (primary never dies from slot bloat) for near-zero cost while
    the funded work lands.
  - Instrument to VALIDATE the estimate: track slot lag, WAL retention, and
    near-miss events so next year's funding argument is data-driven.
```

**Principal takeaway:** more hardware (i) buys time for the same failure to
recur at higher volume; the outbox (iii) removes the class; and none of it
ships without someone to build it (iv). State the dependency graph and hedge
with the cheap backstop.

---

## Key Takeaways

```
╔═══════════════════════════════════════════════════════════════╗
║   1. A stalled CDC consumer can kill the PRIMARY via          ║
║      replication-slot WAL retention. Cap it AND alert on      ║
║      slot lag early.                                          ║
║   2. The WAL cap trades a source-of-truth outage for a        ║
║      derived-system (search) outage — usually correct.        ║
║   3. Read-your-writes via LSN is fragile under PgBouncer      ║
║      transaction pooling; a sticky-primary window is robust.  ║
║   4. Transactional outbox eliminates the CDC-coupling failure ║
║      CLASS; sharding CDC only parallelizes the same failure.  ║
║   5. Prefer changes that remove a failure CLASS and compound; ║
║      buy hardware only for genuine headroom. Mind iv → iii.   ║
╚═══════════════════════════════════════════════════════════════╝
```
