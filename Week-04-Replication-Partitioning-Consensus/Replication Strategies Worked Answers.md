# Worked Answers — Replication Strategies

This companion retrofit answers the principal-grade questions implied by the Replication Strategies module. The goal is not memorization; it is decision-quality reasoning under design-review and incident pressure.

---

## Answer 1 — Choosing a replication strategy for mixed business criticality

### Scenario

```text
You are designing a global commerce platform.

Workloads:
  - payment ledger writes
  - order status reads
  - product catalog reads
  - analytics exports
  - customer profile updates

Question:
  Which replication strategy should each use, and why?
```

### Principal answer

Use different replication strategies per consequence class. A single topology for every workload is usually a sign that the system was designed around infrastructure convenience instead of business invariants.

```text
Payment ledger:
  Strategy: leader-follower with synchronous or semi-synchronous replication
  Reason: committed money movement must not disappear after leader failure
  RPO target: 0 or near-0
  Tradeoff: higher write latency is acceptable because correctness beats speed

Order status reads:
  Strategy: leader-follower with async read replicas, plus read-your-writes routing
  Reason: reads can scale horizontally, but a user must see their own order update
  Caveat: follower reads are okay for support dashboards, not immediately after write

Product catalog reads:
  Strategy: async replication + CDN/cache/search index
  Reason: catalog is read-heavy and can tolerate short freshness windows
  Caveat: price/inventory may need stronger guarantees than descriptions/images

Analytics exports:
  Strategy: CDC to Kafka/data lake
  Reason: analytics needs replayability and fan-out more than synchronous correctness
  Caveat: dashboards must show data freshness and not pretend to be real-time truth

Customer profile updates:
  Strategy: single-leader or multi-region with conflict-aware design
  Reason: profile edits need read-your-writes; multi-leader may create conflicts
  Caveat: if offline/mobile writes are required, define merge rules explicitly
```

The key design sentence:

```text
Replication topology follows the consequence of stale, lost, duplicated, or conflicting data.
```

A weaker answer says “use read replicas everywhere.” A principal answer says read replicas scale reads, not writes, and every replica creates a freshness and failover story that must be owned.

---

## Answer 2 — Async leader failure with replication lag

### Scenario

```text
PostgreSQL primary uses async replication to one standby.
At 12:00:00, primary acknowledges order writes.
At 12:00:04, primary crashes.
Standby is 3 seconds behind.
Operations promotes the standby.

Question:
  What data can be lost, what must be checked, and how do you recover safely?
```

### Principal answer

Async replication means the primary can acknowledge commits before the standby has received or replayed the WAL. If the primary dies while the standby is behind, the promoted standby may not contain some transactions that clients were already told had committed.

The data at risk is the lag window:

```text
committed_on_primary_but_not_replayed_on_standby
```

Immediate investigation:

```sql
-- On primary before failure, if available
SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn,
       pg_wal_lsn_diff(sent_lsn, replay_lsn) AS replay_lag_bytes,
       write_lag, flush_lag, replay_lag
FROM pg_stat_replication;

-- On promoted standby
SELECT pg_is_in_recovery();
SELECT pg_last_wal_replay_lsn();
SELECT pg_last_xact_replay_timestamp();
```

Operational response:

```text
1. Freeze or slow writes if the old primary may return.
2. Confirm a single writable primary exists; prevent split brain.
3. Determine promotion LSN and last known primary LSN.
4. Identify business records created during the lag window.
5. Reconcile against external systems: payment provider, Kafka outbox, order confirmations, audit logs.
6. Do not simply replay blindly unless idempotency and ordering are understood.
```

The dangerous mistake is assuming failover means no data loss. Failover restores availability; it does not retroactively make async replication synchronous.

If the system cannot tolerate this risk, use semi-sync or sync replication for that dataset:

```text
leader waits for at least one standby before acknowledging commit
```

Cost:

```text
higher write latency
possible write unavailability if sync standby is unavailable
```

Principal tradeoff:

```text
If losing 3 seconds of data is worse than blocking writes for 3 seconds, async replication is the wrong topology.
```

---

## Answer 3 — Semi-synchronous replication across AZs

### Scenario

```text
You have one primary in AZ-a and two replicas in AZ-b and AZ-c.
The team proposes synchronous replication to both replicas.
Another team proposes async replication to both.
You must choose for an order database.
```

### Principal answer

A strong default is semi-synchronous replication: wait for one synchronous standby, keep another asynchronous standby for extra read capacity and recovery flexibility.

```text
Primary in AZ-a
  sync standby in AZ-b
  async standby in AZ-c
```

Why not sync to both?

```text
commit latency = primary work + slowest required standby path
one slow AZ can slow or block every write
availability becomes hostage to both replicas
```

Why not async to both?

```text
lowest latency, but leader failure can lose acknowledged writes
acceptable for analytics, risky for order source-of-truth
```

Semi-sync gives a middle path:

```text
at least two durable copies before commit acknowledgement
one standby can fail without total data loss
write latency pays one cross-AZ RTT, not all replicas
```

Key settings to reason about:

```text
PostgreSQL synchronous_standby_names
synchronous_commit
replica health and promotion policy
client retry behavior during sync standby loss
```

Principal caveat:

```text
Semi-sync is not magic. You must define what happens when no synchronous standby is healthy.
```

Possible policies:

```text
block writes:
  safer for ledgers and inventory correctness
  hurts availability

downgrade to async:
  preserves writes
  creates possible RPO > 0
  must be explicit and alerted
```

A mature production system does not hide this behind a default. It names the mode, alerts on mode changes, and records the business risk.

---

## Answer 4 — Physical replication vs logical replication vs CDC

### Scenario

```text
A team wants one replica for HA, one feed to Elasticsearch, one path for major-version upgrade, and one analytics stream.
They ask if “replication” solves all of it.
```

### Principal answer

Replication is not one mechanism. Different replication forms answer different questions.

```text
HA standby:
  Use physical WAL replication
  Why: fastest path to byte-identical failover target
  Limitation: same engine/version/platform constraints, read-only standby

Major-version upgrade:
  Use logical replication
  Why: row-level operations can cross versions and allow controlled cutover
  Limitation: DDL, sequences, schema compatibility, conflicts need handling

Elasticsearch/search indexing:
  Use CDC or outbox-backed event stream
  Why: downstream system needs changes as events, not a byte-identical DB copy
  Limitation: eventual consistency and consumer lag

Analytics stream:
  Use CDC/Kafka/data-lake pipeline
  Why: many consumers, replay, decoupled processing
  Limitation: not a substitute for source-of-truth transactions
```

The common trap:

```text
Physical replica != event stream
CDC stream != failover replica
Logical replication != automatic business event model
```

For business-domain events, prefer the outbox pattern when event meaning matters:

```text
OrderCreated
PaymentAuthorized
RefundIssued
InventoryReserved
```

Direct row CDC is excellent for replication to search/warehouse, but row changes are not always the same as domain events.

Principal check:

```text
Ask what the consumer needs: byte-identical recovery, row-level migration, business event, or replayable analytics feed.
```

---

## Answer 5 — Multi-leader conflicts and why “last writer wins” is dangerous

### Scenario

```text
A global profile service accepts writes in US and EU.
US user updates email at the same time EU support updates the same profile.
The database uses last-writer-wins conflict resolution.

Question:
  What can go wrong and what is a better design?
```

### Principal answer

Multi-leader replication improves local write latency and regional write availability, but creates concurrent-write conflicts. Last-writer-wins is simple, but it can silently discard valid business intent.

Example:

```text
US write:
  email = alice@example.com
  timestamp = 10:00:01.100

EU write:
  phone_verified = true
  timestamp = 10:00:01.050

LWW result:
  US write wins
  EU support update may be lost if the conflict is record-level
```

This is unacceptable when fields have independent meanings. Clock skew makes it worse because the “last” writer may not actually be last.

Better options:

```text
Field-level merge:
  independent fields merge without conflict

Version vectors/vector clocks:
  detect concurrency instead of pretending one write is newer

Domain-specific merge:
  cart item additions union together
  profile security changes require explicit workflow

Single-writer partitioning:
  route all writes for a user/account to one home region

Command/event model:
  store intent as events and resolve with business rules
```

Principal rule:

```text
If losing either write is unacceptable, do not use blind last-writer-wins.
```

Multi-leader is a business semantics problem wearing a database hat. The hard part is not copying bytes across regions; it is defining what should happen when two humans or services are both correct at the same time.

---

## Final rubric

```text
Passing answer:
  - identifies replication topology
  - names consistency/availability tradeoff
  - recognizes lag and failover risk

Principal answer:
  - ties topology to business consequence
  - distinguishes HA replication from CDC/events
  - names exact failure mode and detection signal
  - states recovery steps and reconciliation needs
  - refuses silent data loss for correctness-critical domains
```
