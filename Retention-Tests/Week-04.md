# Week 4 Retention Test

## Rules

- Answer from memory before opening the answer key.
- Keep rapid-fire answers concise: 2-4 sentences unless math is required.
- For the compound scenario, show the causal chain, not only isolated facts.
- Name the layer, invariant, and bad fix for each incident response.
- Staff gate requires a safe first 15-minute sequence and at least one capacity check.

---

## Part 1: Rapid-Fire (Q1-Q24)

**Q1 - TCP: `EADDRNOTAVAIL` with short-lived HTTP connections**
A service opens 50,000 short-lived outbound HTTP/1.1 connections per minute to one destination. It starts returning `connect() EADDRNOTAVAIL`; CPU and memory are normal, and many sockets are in `TIME_WAIT`. Explain the mechanism, name the kernel setting involved in reusing `TIME_WAIT` sockets, and give one kernel-level and one application-level fix.

**Q2 - gRPC + L4 load balancer: imbalanced backend load**
Six backend pods sit behind an L4 load balancer. A small number of clients use gRPC and two pods receive almost all traffic while the others are idle. Explain the mechanism and give the correct balancing fix.

**Q3 - DNS: Java app slow external resolution with `ClusterFirst`**
A Java service in Kubernetes resolves `api.payment.com` slowly while CoreDNS shows many NXDOMAIN responses. Pods use the default `ClusterFirst` DNS policy. Explain the exact resolver behavior and two safe fixes.

**Q4 - CDN: cache-control header interpretation**
Interpret `Cache-Control: s-maxage=86400, max-age=3600, stale-while-revalidate=60, stale-if-error=300`. Which cache uses each directive, and what happens when the origin is slow or down?

**Q5 - PostgreSQL Read Committed: three anomalies**
Read Committed prevents dirty reads but not stronger anomalies. Name three anomalies Serializable prevents and give a real-world example of each.

**Q6 - Composite index: `(customer_id, order_date, status)`**
For this B-tree index, decide which queries are efficient and why:
A. `WHERE customer_id = 42 AND order_date > '2024-01-01'`
B. `WHERE order_date > '2024-01-01' AND status = 'pending'`
C. `WHERE customer_id = 42 AND status = 'pending'`

**Q7 - Cassandra: CL=QUORUM write + CL=ONE read**
With RF=3, W=QUORUM, and R=ONE, is strong consistency guaranteed? Show the quorum math and name the anomaly.

**Q8 - Cache stampede prevention**
Name three cache stampede prevention strategies. For each, state the mechanism and whether application code must change.

**Q9 - PACELC classification**
Classify these systems and explain the tradeoff:
A. PostgreSQL synchronous replication to all standbys
B. Cassandra with CL=ONE
C. DynamoDB strongly consistent reads

**Q10 - Consistency violation: old -> new -> old**
A user refreshes a profile photo and sees old -> new -> old across three page loads. Which consistency property is violated? What property is violated if they only see old -> new after their own write?

**Q11 - Consistent hashing: key movement math**
Compare key movement when growing from 100 to 105 nodes under `hash(key) mod N` versus consistent hashing with 200 vnodes per node. Show approximate movement percentages.

**Q12 - PostgreSQL `synchronous_commit` levels**
List the five levels from weakest to strongest. What exactly has happened at `remote_write`, and what failure can still lose data?

**Q13 - CDC vs cache-aside for Redis consistency**
Why can CDC from the database WAL be safer than cache-aside invalidation for correctness-sensitive cache updates? Include an example of a harmful stale read.

**Q14 - Leader-follower failover: four failure modes**
Name four failure modes during leader-follower failover and one prevention or repair mechanism for each.

**Q15 - DynamoDB GSI update semantics**
Are GSI updates synchronous or asynchronous? What consistency anomaly can a GSI reader see, and how can a hot GSI affect base-table writes?

**Q16 - Elasticsearch: adding shards to an existing index**
Can you add primary shards to an existing index? Explain why, then describe the migration strategy and one ILM rollover condition that prevents recurrence.

**Q17 - Raft election restriction: can node D win?**
In a 5-node cluster, committed entry X exists on A, B, C. A crashes. D does not have X and starts an election. Can D win? Prove your answer using the election restriction and majority overlap.

**Q18 - etcd: leader crashes before replicating**
A leader accepts a write but crashes before replicating it to a majority. What can the client observe, and why is the write not committed under Raft?

**Q19 - Sharding: hot tenant and resharding risk**
A single tenant creates a hot shard while average cluster utilization is low. Name two mitigation patterns and one resharding hazard.

**Q20 - Replication/CDC safety-critical reads**
When is an async replica acceptable, and when must a read route to primary or a bounded-staleness/synchronous source? Give one financial or safety-critical example.

**Q21 - Follower reads with required LSN**
A write response includes `commit_lsn=7/ABCD1234`. A later read can hit any replica. What must the router check before allowing a replica read, and what should it do if no replica has reached the LSN?

**Q22 - Raft linearizable reads**
Why is reading from a Raft leader's local state not automatically linearizable after a partition? Name two safe read mechanisms.

**Q23 - Shard-key choice under celebrity traffic**
A table is sharded by `(event_id)` and one event receives 80% of all writes. Why does adding nodes not fix the immediate hot shard, and what key design changes the write distribution?

**Q24 - Replication slot bloat**
A Debezium connector is down for six hours and PostgreSQL disk usage grows quickly. Explain the mechanism and the safe response sequence.

---

## Part 2: Compound Scenario - Northstar Ledger, Inventory, and Control-Plane Cascade

```text
INCIDENT: Cross-region trading and checkout cascade

Northstar has a marketplace wallet, flash-sale inventory, and a Kubernetes-based
control plane. The incident begins during a limited drop that also allows sellers
to move proceeds into a brokerage wallet.

BUSINESS INVARIANTS

  1. Do not accept a purchase if inventory reservation is uncertain.
  2. Do not approve a wallet transfer against stale available balance.
  3. Do not trade control-plane recovery speed for data-plane outage.
  4. Do not lose acknowledged ledger writes without executive approval.

ARCHITECTURE

  Checkout API -> PostgreSQL primary in us-east-1
  Checkout API -> async read replicas in us-east-1 and eu-west-1
  Ledger API -> CockroachDB ranges across us-east-1/us-west-2/eu-west-1
  Inventory API -> Cassandra RF=3 per region
  CDC -> Debezium -> Kafka -> Redis read models and search indexes
  Kubernetes -> etcd on gp3 volumes, API servers shared by deploy system

CHANGE LOG

  08:55 - Network firewall policy changed between us-east-1 and eu-west-1.
  09:00 - Flash-sale controller begins rollout to 900 nodes.
  09:02 - Inventory service enables dynamic token movement during hot sale.
  09:04 - Checkout hotfix routes all cart reads to primary.
  09:06 - Ledger risk job switches EU broker margin checks to local async replica.

TELEMETRY PACK

PostgreSQL / checkout:
  write TPS: 3,200 -> 9,100
  primary pgbouncer: cl_active=740 cl_waiting=630 sv_active=260 sv_idle=0
  replica lag: use1-r1=1.8s, use1-r2=5.1s, euw1-r1=52s
  synchronous_commit: remote_apply for ledger-adjacent tables
  recovery conflicts on replicas: 0 -> 480/min

CockroachDB / ledger:
  inter-region RTT use1<->euw1: 74ms -> packet loss / blocked ports
  quorum path remains use1 + usw2
  leaseholder transfers: 9,400 ranges in 4 min
  commit p50/p99: 6ms/24ms -> 190ms/740ms
  closed timestamp lag: 1.5s -> 38s
  EU broker margin check read source: euw1 async Postgres replica
  reported available margin: $2.4M
  true available margin after recent withdrawals: $600K
  accepted transfer/trade: $2.1M

Cassandra / inventory:
  partition key: ((drop_id), sku_id, event_time)
  hot drop_id: sneaker-77
  writes to hot partition: 68k/sec
  replica node CPU for hot partition: [97, 95, 94]
  cluster median CPU: 43
  token movement streaming: 240MB/sec
  pending compactions: 31
  read timeouts: 0.2% -> 9.4%

CDC / Kafka / Redis:
  Debezium replication slot retained WAL: 18GB -> 220GB
  connector lag: 14s -> 31m
  Kafka consumer lag for wallet-read-model: 0 -> 4.8M messages
  Redis wallet read model age p99: 2s -> 26m
  search index inventory age p99: 5s -> 18m

etcd / control plane:
  leader changes: +11 in 5 min
  WAL fsync p99: 6ms -> 290ms
  proposals_pending: 42 -> 24,000
  API server 5xx: 0.1% -> 8%
  node NotReady: 163 nodes
  eviction timers: 3m remaining
  serving checkout capacity on existing pods: 71% utilized and stable

CONFIG PACK

checkout_reads:
  route_all_cart_reads_to_primary: true
  required_lsn_routing: false

ledger_risk:
  margin_check_source: eu-west-1-async-replica
  max_staleness_seconds: 60
  enforce_primary_for_trade_approval: false

inventory:
  partition_key: "((drop_id), sku_id, event_time)"
  dynamic_token_move_during_sale: true
  reservation_truth_from_redis_summary: false

cdc:
  replication_slot_max_wal_keep_size: unlimited
  connector_restart_policy: manual
  lag_alert_threshold: 20m

control_plane:
  rollout_max_concurrent_nodes: 900
  writes_per_node: 8
  emergency_drain_notready_nodes: true
  etcd_volume_iops: 3000

TIMELINE

T+0 / 09:00
  Customers report slow checkout and inconsistent inventory counters.
  Ledger team sees EU margin checks reading much higher balances than expected.
  Platform sees etcd proposal backlog.

T+5 / 09:05
  Primary reads hotfix is active.
  Cassandra token movement is streaming.
  CockroachDB ranges are moving leaseholders away from eu-west-1.
  Debezium lag begins rising.

T+15 / 09:15
  Unauthorized $2.1M trade is detected.
  163 nodes are NotReady, but existing checkout pods still serve.
  Someone proposes draining all NotReady nodes and setting `synchronous_commit=off`.

T+60 / 10:00
  Sale can continue at reduced rate if inventory reservations use source of truth.
  Ledger risk wants all broker transfers paused until balances are reconciled.
  Platform wants to restart Debezium immediately even though disk is near full.

BAD FIX GALLERY

  A. Route all reads to primary until replica lag is zero.
  B. Set `synchronous_commit=off` globally to reduce commit latency.
  C. Move Cassandra tokens now because the cluster average CPU is low.
  D. Trust Redis wallet read model because it is faster than PostgreSQL.
  E. Drain NotReady nodes to force Kubernetes to recreate everything cleanly.
  F. Drop the Debezium replication slot to free disk immediately.
  G. Increase CockroachDB leaseholder transfer aggressiveness.
```

### Questions

**Q1 - Root cause chain (10 pts)**
Map the cascade link by link. Separate direct triggers, amplifiers, symptoms, and the single architectural link that would have prevented the financial loss.

**Q2 - Unauthorized trade data path (10 pts)**
Trace how the real balance became a stale margin-check read. Where should the protection exist? Should EU brokers read from the eu-west-1 async replica for trade approval?

**Q3 - Replication and read-routing plan (10 pts)**
Design the next 10-30 minutes of read routing for cart, wallet, and ledger-risk reads. Include required LSN, primary routing, bounded staleness, and replica removal.

**Q4 - Immediate mitigation plan at 09:15 (10 pts)**
Give priority order for financial exposure, firewall rollback, retry amplification, CockroachDB leaseholder storm, PostgreSQL pressure, Cassandra hot partition, CDC lag, etcd, and Redis/search read models.

**Q5 - Verification and rollback safety (10 pts)**
For each mitigation, state the evidence you would check before and after execution. Include commands or queries where useful.

**Q6 - Bad fix rejection (10 pts)**
Reject A-G. Explain the mechanism that makes each unsafe or incomplete and the safer alternative.

**Q7 - Capacity and blast radius (10 pts)**
Calculate or estimate:
- PgBouncer client waiters versus server connections.
- Control-plane object writes from 900 nodes x 8 writes/node.
- Why even token distribution does not fix one hot Cassandra partition.
- How much stale margin exposure existed in dollars.

**Q8 - Long-term prevention (10 pts)**
Design durable fixes for staleness-bounded financial reads, retry budgets, CockroachDB placement/rebalancing safety, CDC lag alerts, PgBouncer isolation, Cassandra partitioning, and runbook ownership.

**Q9 - Org / runbook (10 pts)**
Who is informed by T+10? Which actions require senior approval? What customer/legal/accounting follow-up begins before the technical incident is fully resolved?

---

## Part 3: Focused Staff Transfer Stems (Q10-Q16)

These questions thicken the Week 4 gate with novel combinations of replication, sharding, and Raft. They are not additional teaching notes; answer from memory.

### Stem A - Replica freshness versus capacity

```text
Service: seller-wallet
Write path: PostgreSQL primary
Read path: async replicas through a router
New feature: seller can withdraw proceeds 3 seconds after a sale settles

Telemetry:
  primary write TPS: 1,900 -> 5,600
  replica replay lag:
    r1 = 900ms
    r2 = 12s
    r3 = 41s
  router policy:
    allow_replica_if_lag_seconds < 60
    ignore_required_lsn: true
  pgbouncer primary:
    sv_active=180
    sv_idle=0
    cl_waiting=310
  incident:
    seller sees available balance $18,000
    true available after chargeback hold is $2,100
    withdrawal approved for $12,000
```

**Q10:** Why is `lag_seconds < 60` the wrong contract for this read? What contract should replace it for withdrawal approval?

**Q11:** How do you reduce primary pressure without returning to unsafe stale reads?

### Stem B - Raft control-plane write storm

```text
Cluster: 5-node etcd
Recent change: node controller writes one status object per pod per node during rollout
Rollout size: 1,200 nodes
Objects per node: 9
Telemetry:
  proposals_pending: 50 -> 31,000
  leader changes: +14 in 10m
  WAL fsync p99: 4ms -> 310ms
  committed index advances slowly but steadily
  220 nodes NotReady
  running checkout pods on those nodes are still serving
Proposal:
  remove two slow etcd members and drain NotReady nodes
```

**Q12:** Calculate the object-write burst and explain how it destabilizes Raft leadership.

**Q13:** Reject or accept removing members and draining nodes. What should happen first?

### Stem C - Shard split under hot key pressure

```text
System: inventory reservations
Current partition key: ((launch_id), sku_id)
Hot launch_id: sapphire-early-access
Writes: 82,000/sec to one launch
Cluster: 48 nodes, RF=3
Median node CPU: 37%
Hot replica CPU: [99, 97, 96]
Operator action started:
  split token ranges and add 24 nodes
  streaming throughput: 420MB/sec
  compaction pending: 44
```

**Q14:** Why does adding nodes and splitting token ranges not solve this hot key during the incident?

**Q15:** What immediate degradation protects reservation correctness, and what future data model distributes this write load?

### Stem D - CDC lag and derived read models

```text
Pipeline:
  PostgreSQL WAL -> Debezium -> Kafka -> Redis wallet summary -> Search index
Lag:
  Debezium: 24m
  Kafka wallet-summary consumer: 3.1M messages
  Redis summary age p99: 21m
  Search wallet facets age p99: 43m
Config:
  checkout_uses_redis_summary_for_limit_check: true
  alert_on_cdc_lag_threshold: 30m
  replication_slot_drop_to_free_disk: proposed
```

**Q16:** Which derived views must be removed from decision paths immediately, and why is dropping the slot dangerous?

---

## Self-score

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Stale financial read missed | | |
| Unsafe durability downgrade | | |
| Control-plane/data-plane confusion | | |
| Hot partition misunderstood | | |
| CDC slot data-loss risk missed | | |
| Capacity math skipped | | |
| Org/legal escalation skipped | | |

---

> **Answer key (do not open until you attempt the retention test):**
> [`../answers/Retention-Tests/Week-04 Answers.md`](../answers/Retention-Tests/Week-04%20Answers.md)
