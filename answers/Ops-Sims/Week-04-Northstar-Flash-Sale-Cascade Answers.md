# Answer Key - Week 04 Northstar Flash Sale Cascade

> Open only after attempting the Ops Sim.

## Q1 - Root-cause chain

Replication:
- Trigger: flash-sale write TPS drives replica lag.
- Amplifier: broad `route_all_cart_reads_to_primary` saturates primary PgBouncer.
- Additional pressure: semi-sync `remote_apply` raises commit latency.

Sharding:
- Trigger: celebrity SKU concentrates reads in one Cassandra partition.
- Amplifier: token movement/streaming on hot nodes adds IO, compaction, and network load.
- Redis summary hot key is a derived-display hotspot, not checkout truth.

Consensus/control plane:
- Trigger: emergency rollout writes thousands of objects.
- Mechanism: WAL fsync p99 exceeds heartbeat/election budget, causing Raft leader churn.
- Amplifier: attempted drains would turn control-plane symptoms into data-plane outage.

## Q2 - Evidence by subsystem

Replication:
- Replica r2 lag=24s.
- Primary PgBouncer `cl_waiting=560`, `sv_idle=0`.
- Cart reads routed 92% to primary after hotfix.

Sharding:
- Hot partition reads=61k/s.
- Exactly three replica nodes >93% CPU while median is 41%.
- Token movement active with compactions=28.

Consensus:
- etcd leader changes +9/5min.
- WAL fsync p99 260ms.
- Proposals pending 21,000 with NotReady lease symptoms.

## Q3 - First 15-minute mitigation

1. Declare P1; split leads for DB, inventory, and control plane.
2. Stop unsafe actions: broad primary-read hotfix, Cassandra token movement, control-plane rollout/drains.
3. Replication: route only recent-writer/required-LSN cart reads to primary; remove lagged r2 from read pool; cancel recovery-conflict queries.
4. Sharding: degrade exact live counters, coalesce/cache display reads, fail closed on checkout reservation uncertainty.
5. Control plane: freeze controllers/deploys creating writes; protect running workloads from eviction; do not drain healthy-serving nodes.
6. Verify after each change: primary pool, write p99, replica lag, hot partition p99, Redis/DB fallbacks, etcd leader stability, pending proposals.

## Q4 - Bad fixes

- Route all reads to primary: consumes write-critical pool and can take down checkout writes.
- `synchronous_commit=off`: acknowledged writes can be lost on crash; requires explicit durability approval.
- Move Cassandra tokens while hot: adds streaming/compaction to saturated replicas and does not split one hot partition.
- Use Redis summary as checkout truth: derived/stale display data can oversell.
- Drain NotReady nodes: workloads are serving; draining causes avoidable data-plane outage.

## Q5 - Capacity / blast radius

Primary PgBouncer:

```text
700 active clients - 240 server connections = 460 waiting clients
```

Rollout writes:

```text
800 nodes x 7 writes/node = 5,600 object writes
```

Hot partition:
- Even token distribution moves ranges, not one partition's internal load.
- All reads for `((auction_id, bucket), event_time)` still hit the same RF=3 replica set until the data model adds shards/buckets.

## Q6 - Durable fixes

Read-your-writes:
- Return commit LSN/version.
- Route recent writers to primary or replicas caught up to required LSN.
- Lag-aware read balancing and separate primary pools for writes.

Celebrity SKU partitioning:
- Add shard bucket to partition key, e.g. `((auction_id, bucket, shard_id), event_time)`.
- Pre-split celebrity auctions and aggregate counters asynchronously.
- Use Redis/search summaries only for display; final reservation uses source of truth.

Control plane:
- Batch rollouts and cap object writes/minute.
- Provision etcd storage IOPS for peak control-plane writes.
- Alert on fsync p99, pending proposals, leader changes, and lease renewals.
- Freeze controllers automatically on etcd saturation.

## Q7 - Org / runbook

By T+10 inform incident commander, checkout/DB owner, inventory/Cassandra owner, platform/control-plane owner, auction business owner, payments/risk, support, and SRE lead.

Explicit senior approval required for durability downgrade, etcd membership/election-timeout changes, snapshot restore, destructive node drains, or accepting checkout based on derived inventory data. Pre-authorized: remove lagged replicas, stop token movement, freeze rollouts, and degrade live counters.
