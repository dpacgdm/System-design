# Answer Key - Week-13

> Open only after attempting `Retention-Tests/Week-13.md`.

---

## Part 1: Rapid-Fire Model Answers

**Q1:** With RF=3 and R=2/W=2, read and write quorums overlap, so a successful read should see at least one replica that saw the latest successful write. It does not eliminate concurrent-write conflicts, clock/LWW problems, bad clients, or stale reads when sloppy quorum/failed repairs violate assumptions.

**Q2:** Hinted handoff stores writes for a temporarily unavailable replica; anti-entropy repair finds and fixes divergence later. Hint replay can flood a recovering node and its peer replicas, adding write load exactly when the cluster is fragile.

**Q3:** Consistent hashing moves only some ranges when nodes are added, and a single hot key/prefix still maps to the same replica set. You need key redesign, salting/sub-sharding, rate limits, or workload changes.

**Q4:** Kafka retains records independent of consumption; consumers track offsets as cursors. Multiple consumer groups can read the same log, replay, and process independently.

**Q5:** `acks=all` waits for all replicas currently in ISR as constrained by `min.insync.replicas`. With RF=3 and min ISR=2, a write is acknowledged only when leader plus at least one follower are in sync, reducing data-loss risk if one broker dies.

**Q6:** Config/coordination decisions like locks, leader election, and rollout state need one agreed value. Raft/CP may reject writes during partitions, which is safer than split-brain config.

**Q7:** A watch storm is too many clients watching broad/hot prefixes and receiving huge notification fan-out. Watch proxies or local agents maintain a small number of upstream watches and fan out cached changes locally.

**Q8:** A paused client can retain a lease in its own mind after TTL expiration and still issue writes. Fencing tokens let downstream resources reject stale lock holders with older tokens.

**Q9:** Kafka EOS helps broker-side consume/produce transactions, not arbitrary OLTP ledger invariants or external PSP correctness. The ledger must remain queryable, auditable, transactional source of truth.

**Q10:** Redis flag cache is fast but approximate and can be stale/AP. etcd config is versioned, watchable, and linearizable for coordination-critical changes.

**Q11:** Under-replicated partitions, ISR shrink, offline partition count, broker disk fullness, request handler saturation, produce latency, controller changes, and unclean election count.

**Q12:** `gc_grace_seconds` keeps tombstones long enough to prevent deleted data from resurrecting on replicas that missed the delete. Repairs must run before grace expires so all replicas learn tombstones.

**Q13:** AP KV may accept writes on available replicas and reconcile conflicts later. CP Raft config store will refuse operations without quorum to avoid split-brain state.

**Q14:** Per-tenant coordinator limits stop one tenant/keyspace from consuming all coordinator threads, disk, compaction, and replica bandwidth. They preserve global SLO by shedding noisy workloads.

**Q15:** Local caching reduces load and keeps apps running during transient config-store issues. Dangerous config needs TTL/max-staleness and safe defaults so clients do not run forever on revoked or unsafe settings.

**Q16:** RF=3 writes three copies and stores three copies, so base disk/write bandwidth roughly triples. Compaction, WAL, indexes, tombstones, and repair add further transient and steady overhead.

---

## Part 2: Compound Scenario - Expert Analysis

### Data-Loss Risks

Actual confirmed:

- Kafka audit gap offsets unavailable after unclean leader election/broker death.

Potential/likely:

- Payment events acknowledged with `acks=1` and `min.insync.replicas=1` may have been lost before replication.
- Inventory duplicate reserves from stale config and retry behavior may create inconsistent stock state.
- etcd stale watches do not directly lose data, but they cause unsafe behavior by leaving 38% of pods on old revision.

Not data loss by itself:

- Consumer lag, watch compacted errors, and KV timeouts. They are serious but need reconciliation evidence before calling loss.

### T+0 Decision

Protect money/event correctness first while stabilizing config and inventory:

1. Freeze flash-sale risky flags and roll to a safe known config revision.
2. Stop or degrade checkout paths that emit payment events without durable Kafka guarantees.
3. Change payment producers/topics to safe durability where possible: `acks=all`, `enable.idempotence=true`, `min.insync.replicas=2`, `unclean.leader.election=false`.
4. Rate limit hot SKU reservations and disable `inventory_fast_reserve`.
5. Stabilize etcd by narrowing watches, removing broad `/` watchers, defrag/snapshot only if safe, and scaling through watch proxy/local agents.

### T+5 Kafka Action

If ISR is unhealthy, accepting `acks=1` payment events is unsafe. Acceptable actions: pause nonessential payment-event producers, route payment writes through durable ledger/outbox, raise producer durability settings for topics with enough ISR, disable unclean election, and fail closed for money movement when min ISR cannot be met. Do not prefer availability over auditability for payment topics.

### T+15 Inventory Action

Short term: rate limit the hot SKU prefix, shed low-priority traffic, disable fast reserve, and if business approves, queue reservations rather than timing out/retrying. Lowering consistency to ONE may reduce errors but risks oversell; use only under explicit business decision for non-money/low-risk stock.

Long term: split/salt hot SKU counters, pre-allocate inventory buckets, use reservation tokens, improve compaction strategy for TTL/tombstone workload, enable per-tenant/key limits, and load-test flash-sale prefixes.

### T+60 Reconstruction

Use the ledger/outbox/PSP as truth, not Kafka alone:

1. Identify affected Kafka offset/time window.
2. Compare payment ledger journal entries, order outbox rows, PSP/payment provider records, and Kafka audit logs.
3. For ledger entries missing Kafka events, republish idempotent events with original event ids or reconciliation ids.
4. For Kafka events with no ledger/PSP truth, do not recreate money movement automatically.
5. Rebuild consumers/read models from corrected event stream.
6. Produce an audit report of missing, reconstructed, duplicate, and unverifiable events.

### etcd Watch Misuse

Apps watch `/` directly, producing 18,000 broad streams and 50k-style event fan-out. With 1h auto-compaction, slow clients trying to resume from old revisions receive compacted errors and must relist then watch from current revision. If clients fail that logic, they stay on revision 582811 while desired is 582901 even though etcd still has quorum.

### Kafka Durability Failure

`acks=1` acknowledges after leader append only. `min.insync.replicas=1` allows the leader to be the only in-sync copy. `unclean.leader.election=true` permits a stale replica to become leader after failure, losing acknowledged records that existed only on the old leader. Broker-7 disk 99%, under-replicated partitions, and offline partitions are leading indicators.

### KV Hot-Partition Cascade

One SKU prefix accounts for a large write fraction and maps to a small replica set. LOCAL_QUORUM forces the same overloaded replicas into every write. Compaction backlog and tombstones raise read/write latency, timeouts create retries, failed replicas generate hints, and hint replay adds more writes later.

### Bad-Fix Gallery

| Bad fix | Failure mode |
|---------|--------------|
| Inventory CL=ONE globally | Can oversell and read stale stock; masks hot partition |
| Restart all etcd nodes | Risks losing quorum and worsens leader election storm |
| Enable unclean election | Restores availability by accepting data loss for Kafka |
| Add Kafka consumers | Does not fix producer durability or lost offsets |
| Full Cassandra repair during peak | Massive IO/streaming load; worsens hot cluster |

### Capacity Answer

Hot prefix writes: `200,000/sec * 40% = 80,000 logical writes/sec`.

With RF=3, the replica set receives `80,000 * 3 = 240,000 replica writes/sec` before WAL, indexes, compaction, hints, and retries. If LOCAL_QUORUM times out and clients retry, effective load can exceed this quickly.

### Org/Runbook Invariants

- Payment Kafka topics: RF=3+, `acks=all`, idempotence enabled, `min.insync.replicas>=2`, unclean election disabled.
- etcd: no app watches `/`; use scoped prefixes, watch proxy/agent, compact-relist client tests, and small values.
- KV: per-tenant/key coordinator limits, hot-key dashboards, flash-sale key simulation, and no monthly-only repair when `gc_grace` requires tighter cadence.
- Flash sale review: config rollout gates, inventory hotspot model, Kafka durability check, rollback owner, and business decision matrix for availability vs correctness.

---

## Scoring Guide - 85% Gate

| Area | Points |
|------|--------|
| Rapid-fire correctness | 32 |
| Data-loss classification | 14 |
| Kafka durability explanation | 14 |
| etcd/watch analysis | 10 |
| KV hot-partition analysis | 10 |
| Timed decisions and bad fixes | 10 |
| Capacity math | 5 |
| Org/runbook invariants | 5 |

Pass gate: **85%+**. Critical misses: approving unclean election for payment durability, confusing consumer lag with producer durability, or fixing hot KV partitions only by adding consumers/nodes.
