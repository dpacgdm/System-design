# Worked Answers — Database Scaling Patterns

Companion to [Database Scaling Patterns](./Database%20Scaling%20Patterns.md) and [Retention Test Week 5](../Retention-Tests/Week-05.md).

Attempt all questions from memory before reading these answers.

---

## Rapid-Fire Answers (Q6–Q15)

```plaintext
ANSWER IN YOUR HEAD BEFORE READING.

Q1. p99 went from 50ms → 800ms. CPU on primary is 30%.
    Team wants to shard. What's your first question?

Q2. PgBouncer in transaction mode. App reports
    "search_path is randomly wrong." What's wrong?

Q3. Postgres at 92% disk, pg_wal is 600 GB. All replicas
    current. What query do you run?

Q4. synchronous_standby_names = 'FIRST 1 (r1, r2)'.
    Both replicas die. What happens to writes?

Q5. Debezium connector lag 2h, growing. Consumer offsets
    advancing normally. What's wrong?

Q6. Sharded by user_id. Query "all orders shipped today"
    runs against the OLTP cluster. What happens, and
    what's the right architecture?

Q7. Inventory active/active two regions, LWW. Customer
    charged for out-of-stock item. Explain the bug.

Q8. Read-your-writes via LSN, transaction-pooled. Where
    do you capture the LSN, and where do you NOT?

Q9. CDC consumer halted on schema change. Producer
    dropped a column. What Schema Registry config
    would have prevented this?

Q10. Rung 3 exhausted (biggest SKU, 100k writes/s).
     Boss says "shard." What 5 questions do you ask?


ANSWERS:
━━━━━━━

A1. "What changed in the query pattern, dataset size, or
    indexes?" Latency rising with low CPU = lock waits or
    bad plan flip from grown data. Sharding fixes neither.

A2. SET search_path (without LOCAL) leaks across clients
    sharing the backend connection. Fix: SET LOCAL inside
    a txn, or set via connection string / role default.

A3. SELECT slot_name, active, pg_wal_lsn_diff(
      pg_current_wal_lsn(), restart_lsn)
    FROM pg_replication_slots ORDER BY 3 DESC;
    An inactive slot is almost certainly pinning WAL.
    "Replicas current" doesn't mean all CDC consumers
    are current.

A4. Writes hang indefinitely. wait_event = SyncRep.
    Three solutions: (a) keep sync, accept availability
    hit; (b) auto-degrade to async (alarm the transition!);
    (c) quorum across 3 replicas. Most teams should pick
    (b) with explicit sync_state monitoring.

A5. Lag is upstream, not downstream. Debezium can't read
    WAL fast enough. Check connector throughput, task
    count, and slot confirmed_flush_lsn vs primary's
    current LSN. Consumer offsets are about Kafka, not
    about CDC source.

A6. Scatter-gather across all shards → p99 explodes.
    Right architecture: CQRS read model. Replicate
    orders to a read store keyed/indexed by ship_date
    (Elasticsearch, ClickHouse, or Citus reference table).

A7. Both regions accepted concurrent purchases of the
    last unit; LWW kept one and discarded the other,
    BUT customers were charged locally before conflict
    resolution → the discarded write's customer paid for
    nothing.

A8. Capture INSIDE the writing transaction:
      INSERT ... RETURNING id, pg_current_wal_insert_lsn();
    NEVER capture in a separate connection after commit —
    you'd get the cluster's current LSN, which is not
    necessarily yours and may belong to another commit.

A9. Forward compatibility was set; consumer required the
    dropped column. Correct config: BACKWARD (consumer
    can read old data with new schema). Process fix:
    drop-column changes follow expand → migrate →
    contract over multiple deploys.

A10. (1) What's the dataset growth curve over 12 months?
     (2) Are reads or writes the bottleneck?
     (3) Have we tried CQRS to move dominant reads off
         the OLTP primary?
     (4) What's our shard key candidate, and which
         queries does it serve badly?
     (5) What's the migration plan and rollback strategy?
     Sharding is a 1-way door; these five answers decide
     whether you walk through it.


SCORING:
━━━━━━━

  9-10  Ready for Week 5 T2 (Kafka/Streaming).
  7-8   Re-read Parts 5, 6, 7, 8, 14 before moving on.
  <7    Re-read the whole module. Week 6 (event-driven)
        depends on this.
```

## Compound Scenario Setup (reference) — "The Black Friday Slot"

```plaintext
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
  You have 13 minutes before disk fills at current rate.
  What do you do, in what order, and why?
```

---

## Compound Scenario — Expert Walkthrough (read AFTER you've thought it through)

```plaintext
MINUTE 0 (03:47) — DIAGNOSIS BEFORE ACTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom set:
   - Disk filling on pg_wal volume (not data volume).
   - Replicas current (replay_lag < 200ms).
   - CPU healthy.
   - p99 climbing on primary.
   - ES search results stale by 30 min.
   - Checkpoint completion 4× normal.

  THE PATTERN:
   pg_wal filling + replicas current + downstream stale
   = a CONSUMER of WAL is behind. Not a streaming replica.
   Almost certainly a logical replication slot.

  The "ES stale by 30 min" is the smoking gun the team
  hasn't connected to the disk alarm yet. It's the same
  incident.

  Run the slot query FIRST (Part 7):

    SELECT slot_name, active, active_pid,
      pg_size_pretty(pg_wal_lsn_diff(
        pg_current_wal_lsn(), restart_lsn)) AS retained
    FROM pg_replication_slots
    ORDER BY pg_wal_lsn_diff(
      pg_current_wal_lsn(), restart_lsn) DESC;

  Hypothetical (and realistic) output:

    slot_name           active   retained
    ─────────────────   ──────   ────────
    debezium_orders     true     1.4 TB    ← here
    analytics_etl       true     180 GB
    replica_r1          true     12 MB
    replica_r2          true     12 MB

  Debezium slot is ACTIVE (consumer connected) but
  retention is 1.4 TB. That means Debezium is connected
  but not advancing confirmed_flush_lsn fast enough.
  Producer is overwhelmed, not dead.


MINUTE 2 (03:49) — CONFIRM, DON'T GUESS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Verify Debezium is the cause, not just correlated:

    SELECT slot_name,
      pg_size_pretty(pg_wal_lsn_diff(
        pg_current_wal_lsn(), confirmed_flush_lsn)) AS pending
    FROM pg_replication_slots
    WHERE slot_name = 'debezium_orders';

  pending = 1.4 TB → consumer is 1.4 TB behind on flush.

  Check Debezium connector:
   - Connect to Kafka Connect REST: GET /connectors/debezium-orders/status
   - Hypothetical: RUNNING, but task throughput dropped from
     baseline 80 MB/s to 8 MB/s at 02:55.

  Check Kafka:
   - Producer-side throttling? Broker disk? Topic partition count?
   - Hypothetical finding: orders topic has 6 partitions. Black
     Friday traffic needs 24. Single producer thread is the
     bottleneck. Debezium can't shove WAL into Kafka fast
     enough.

  Now you know the cause. Now you can choose.


MINUTE 5 (03:52) — THE THREE CHOICES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Disk fills in ~10 minutes at current rate. You have
  three levers, each with a different cost.

  CHOICE A — DROP THE SLOT.
    SELECT pg_drop_replication_slot('debezium_orders');
    
    Effect: WAL freed at next checkpoint (~2 min). Disk
    safe within 5 min. Debezium connector breaks. ES will
    be stale until you re-snapshot orders table (~4 hours
    on this dataset).
    
    Cost: 4 hours of stale search during Black Friday peak.
    Search results are degraded but checkout works.

  CHOICE B — SCALE THE CONSUMER.
    Increase orders topic partitions: 6 → 24.
    Restart Debezium with max.batch.size and 
    max.queue.size raised, producer.acks=1 (from all),
    producer.compression.type=lz4.
    
    Effect: throughput recovers to ~80 MB/s. But you have
    1.4 TB of backlog to drain. At 80 MB/s net drain rate
    (after new WAL keeps coming), drain takes 6+ hours.
    Disk fills before drain completes.
    
    Cost: doesn't solve the immediate disk problem.

  CHOICE C — EMERGENCY DISK EXTENSION + B.
    AWS: modify EBS volume 2 TB → 4 TB (online, ~minutes
    to be available, hours to fully optimize).
    Then execute Choice B.
    
    Effect: buys 4-6 hours of headroom. Consumer drains
    over that window. No data loss, no re-snapshot.
    
    Cost: $200 of EBS for the day. Operator vigilance.


  PRINCIPAL'S DECISION:
   C, then B in parallel.
   Drop-slot (A) loses ES freshness during peak revenue
   hours. Disk extension is reversible and cheap. The
   right call is almost always "buy time, then fix the
   real problem."

   But: kick off snapshot preparation in case C fails.
   "Hope is not a strategy. Plan B for plan B."


MINUTE 7 (03:54) — EXECUTE
━━━━━━━━━━━━━━━━━━━━━━━━━

  In parallel:
   1. SRE-1: aws ec2 modify-volume --size 4096
   2. SRE-2: increase orders topic partition count.
              kafka-topics --alter --partitions 24
              (re-keying caveat: see Part 14 Failure 5;
               in this case, Debezium re-keys by PK so
               same-PK events stay in same partition only
               if you use a sticky partitioner — verify.)
   3. SRE-3: bump Debezium task max.batch.size, restart
              connector with rolling restart.
   4. Comms: post in #incidents and to status page:
              "search results may be stale up to 60 min
               during recovery; checkout unaffected."

  At 03:58: disk extension live, retention growth slows.
  At 04:05: Debezium throughput at 110 MB/s, draining backlog.
  At 04:42: pending < 50 GB, ES catching up.
  At 05:30: pending < 1 GB, fully recovered.


MINUTE 60+ — POSTMORTEM PRELOADS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Five things this incident taught (or should have taught
  before it happened):

  1. NO max_slot_wal_keep_size CAP.
     Postgres 13+ supports it. We didn't set it. The
     primary was one bad consumer away from death.
     Action: set max_slot_wal_keep_size = 200GB cluster-wide.
     Trade-off acknowledged: a stuck consumer triggers
     re-snapshot. Re-snapshot is recoverable; disk-full
     primary failover is not.

  2. KAFKA TOPIC SIZING WAS NEVER LOAD-TESTED.
     6 partitions was fine at baseline. Nobody computed
     headroom for 3.2× peak. Capacity planning ignored
     the CDC pipeline because "Kafka scales infinitely."
     Action: load test EVERY pipeline at 4× peak before
     peak season. Document headroom per component.

  3. THE SLOT GROWTH GRAPH HAD NO ALARM.
     We had alarms on disk%. We had alarms on replication
     lag (replay_lag — the wrong metric for this!). We
     had no alarm on pg_replication_slots.retained_wal.
     The alarm we DID get fired with 13 minutes of runway.
     Action: alarm at 50 GB warn, 200 GB page, per slot,
     not per disk.

  4. ES STALENESS WAS A LEADING INDICATOR. NOBODY OWNED IT.
     Search team noticed staleness at 03:33. Database team
     paged at 03:47. Same incident, two teams, fourteen
     minutes of lost diagnostic time.
     Action: cross-team CDC dashboard. ES staleness routes
     to BOTH teams. Eliminate the silo.

  5. WE HAVE NO RUNBOOK FOR "SLOT BLOAT WITH ACTIVE CONSUMER."
     Runbook covered "dead consumer, drop slot." Did not
     cover "alive but slow consumer." Operator at 03:08
     spent 20 minutes ruling out query plans because
     that's where the runbook started.
     Action: rewrite runbook with the symptom-to-cause
     map from Part 1.
```

---

## In-Depth Questions — Principal Answers Framework

Answer in writing. Each one has a "easy answer" and a "principal answer." Aim for the latter.

```plaintext
QUESTION 1 — THE COUNTERFACTUAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Suppose max_slot_wal_keep_size = 200GB had been set
  before the incident. Walk through what would have
  happened minute-by-minute starting at 02:55 (when
  Debezium throughput dropped). Identify:
  
   (a) The exact moment Postgres would invalidate the
       slot.
   (b) What the SRE on-call sees, and on which dashboard.
   (c) The recovery path and its time cost.
   (d) Whether this outcome is BETTER or WORSE than what
       actually happened, and why your answer depends on
       business context (give two scenarios where the
       answer flips).

  This question tests whether you understand that the
  cap is not "the right answer" — it is a TRADE between
  two failure modes. A principal can articulate both
  sides.


QUESTION 2 — THE ROUTING DECISION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  At 03:14, customers reported "order not found on confirm
  page after submit." Search was stale, but checkout reads
  go to Postgres, not ES. So why were customers seeing
  this error?

  Hypothesis: checkout's confirm page reads from a
  read replica with read-your-writes implemented via
  the LSN-token strategy (Part 8).

   (a) Sketch the exact request flow that fails. Where
       could LSN propagation break in this scenario?
   (b) Given that streaming replicas had replay_lag <
       200ms, why would LSN-routed reads still fail?
   (c) Propose two diagnostic queries the SRE could
       have run on the replica to confirm or refute
       this hypothesis in 30 seconds.
   (d) Suppose the team had used the time-window
       stickiness strategy instead (10s primary window).
       Would this incident have manifested differently?
       How?

  This question tests Part 6.3 + Part 8 integration.
  An easy answer says "replicas were lagging." A
  principal answer notices replay_lag < 200ms rules
  that out and points elsewhere — likely PgBouncer
  transaction-pool LSN capture bug (Part 5.3 + 8).


QUESTION 3 — THE DESIGN ALTERNATIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Your post-incident review proposes one of two
  architectural changes. Argue for ONE and against
  the other, with cost and failure-mode reasoning:

  PROPOSAL X: Replace Debezium → Kafka → ES with
  the TRANSACTIONAL OUTBOX pattern. Application writes
  the order AND an outbox row in the same Postgres
  transaction. A separate poller reads outbox and
  publishes to Kafka.

  PROPOSAL Y: Keep Debezium, but switch the orders
  table to a SHARDED Postgres setup (Citus, 8 shards),
  with one Debezium connector per shard. Each shard
  has its own slot.

  Required in your answer:
   (a) Which proposal eliminates THIS incident's class
       of failure, and which only mitigates it?
   (b) What new failure modes does each introduce?
   (c) What's the migration cost in eng-months for
       each, given a team of 4?
   (d) Under what business conditions would you choose
       the OTHER one anyway?

  This question tests Parts 11, 13, and 14 together.
  The principal answer recognizes that X solves the
  cause (consumer-can't-keep-up) by shrinking the
  payload — outbox rows are tiny vs full WAL — while
  Y just gives you 8 ways to have the same problem
  in parallel. But Y might still be right if the
  primary is already write-saturated for OTHER reasons.


QUESTION 4 — THE CAPACITY PLAN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  You're now responsible for capacity planning for
  next year's Black Friday. The CFO will fund exactly
  ONE of the following. Pick one and defend it with
  numbers:

   (i)   Upgrade primary r6i.16xlarge → r6i.32xlarge
         ($60K/year incremental).
   (ii)  Add 16 more Kafka brokers and triple all
         CDC topic partition counts ($45K/year).
   (iii) Implement transactional outbox + dedicated
         outbox-publisher service (~3 eng-months
         build, $20K/year ops).
   (iv)  Hire one additional SRE dedicated to data
         platform ($220K/year fully loaded).

  Required:
   (a) For each option, state the failure mode it
       addresses AND the failure mode it does NOT.
   (b) Compute (with stated assumptions) the
       expected reduction in P1 incidents per year.
   (c) Identify which option produces compounding
       returns (helps next year and the year after)
       vs which produces one-time relief.
   (d) State which option you'd actually choose
       and why, given that you might be wrong about
       (b). What's your hedge?

  This question tests judgment under economic
  constraint — the actual job of a principal. The
  easy answer picks (i) (more hardware). The
  principal answer notices that (iii) eliminates the
  failure CLASS while (i) only buys headroom for the
  same failure to happen at higher volume next year.
  But the truly principal answer also notices that
  without (iv), nobody has time to build (iii), so
  the dependency graph is iv → iii.
```
