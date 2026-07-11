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

## Principal model response

### Incident thesis

This is a three-plane cascade: database read freshness,
Cassandra hot partitions, and Kubernetes/etcd control-plane
pressure. The dangerous move is to optimize one graph while
weakening another invariant. The invariant is:

> Accepted checkout decisions must be based on authoritative
> cart and inventory state, while the control plane must not
> evict healthy data-plane capacity during peak.

### T+0 to T+15 sequence

1. Declare P1; split leads for Postgres/replication,
   Cassandra/inventory, platform/control plane, checkout,
   payments/risk, support, and auction business.
2. Freeze new hotfixes, rollouts, node drains, Cassandra token
   movement, and global routing changes.
3. Undo broad `route_all_cart_reads_to_primary`; keep primary
   for writes and required-LSN recent-reader paths only.
4. Remove lagged replica `r2` from decision reads; use primary
   or replicas whose replay LSN satisfies the user's commit.
5. Cancel or throttle long replica queries that create
   recovery conflicts.
6. Stop Cassandra token movement and compaction-heavy work on
   the hot replica set.
7. Degrade exact live counters and cache display reads; final
   checkout reservation remains source-of-truth Cassandra or a
   reservation service.
8. Freeze deployment controllers and protect existing serving
   pods from eviction while etcd is saturated.
9. Verify after each move with primary pool waiters, write p99,
   replica lag, hot partition p99, Redis fallback rate, etcd
   leader changes, and proposals pending.

### Replication analysis

Replica lag means not all reads are equal. A product detail
read can be stale with a freshness label, but a cart or
discount decision after a write needs read-your-writes
semantics. The broad primary-read hotfix is unsafe because it
moves every stale-read complaint into the write-critical pool.

Use required-LSN routing:

- write returns commit LSN/version;
- read carries required LSN for decision paths;
- router sends to a replica at or beyond that LSN, or primary
  if no replica qualifies within the budget;
- noncritical reads can use stale replicas with labels.

### Sharding/hot-key analysis

The celebrity SKU problem is logical. Token movement moves
ranges between nodes; it does not split one partition's
internal read/write rate. With replication factor three, the
same three nodes remain hot until the data model includes
buckets/shards or a different reservation pattern.

Derived Redis summaries can support display, but they cannot
be checkout truth. If Redis says 17 left and Cassandra/source
reservation is uncertain, checkout must fail closed or pending
rather than oversell.

### Consensus/control-plane analysis

etcd leader changes, fsync p99 260ms, and 21k pending
proposals show write pressure. A NotReady lease symptom may
reflect control-plane delay while pods are still serving.
Draining those nodes creates more API writes, new scheduling,
image pulls, and data-plane churn. Freeze first; repair
control-plane capacity after preserving serving capacity.

### Capacity math

Primary pool:

- 700 active clients and 240 server connections means about
  460 clients waiting.
- If cart reads are 92% primary after the hotfix, most of the
  write-critical capacity is being consumed by reads that
  should be routed by LSN.

Control plane:

- 800 nodes times 7 writes per rollout event is 5,600 object
  writes, before retries and controller status updates.
- With fsync p99 above heartbeat/election budgets, write
  bursts can trigger leader churn.

Hot partition:

- 61k reads/sec into one logical key concentrate on the RF=3
  replica set. Adding nodes changes cluster aggregate capacity
  but not that key's immediate blast radius.

### Bad-fix physics

- `synchronous_commit=off` changes durability semantics during
  an incident and requires explicit business approval.
- All-primary reads convert read freshness into write outage.
- Faster token movement adds streaming and compaction to hot
  nodes.
- Redis summary as checkout truth can oversell because it is a
  derived display view.
- Draining NotReady nodes can evict healthy-serving pods and
  intensify etcd pressure.
- Scaling application pods before DB pool relief can increase
  client waiters.

### Durable acceptance gates

- Read paths are classified as decision, recent-user, or
  display, with required-LSN routing for decision paths.
- Primary pools reserve write capacity and alert on waiters,
  read-to-primary ratio, and replica eligibility.
- Celebrity auctions are pre-bucketed by SKU/campaign and
  tested at peak RF=3 load.
- Token movement is blocked during hot-key incidents unless an
  owner proves it reduces the specific key's pressure.
- Live counters are explicitly non-authoritative in checkout.
- etcd has rollout write-rate budgets, fsync/proposal/leader
  alerts, and automatic controller freeze gates.
- Runbook distinguishes pre-authorized safe mitigations from
  senior-approval durability or destructive changes.
