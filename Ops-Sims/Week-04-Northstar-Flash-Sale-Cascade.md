# Ops Sim: Week 04 - Northstar Flash Sale Cascade

**Time box:** 50 minutes
**Severity:** P1
**Service / domain:** Replication, sharding, consensus/control plane
**Northstar system:** Checkout OLTP, Inventory, Control plane

## Rules

1. Answer from memory of Week 4 modules.
2. Work in order: T+0 -> T+5 -> T+15 -> T+60.
3. Name evidence and capacity assumptions.
4. Do not open the answer key until finished.

---

## 1. Scenario stem

```text
WHAT USERS SEE:
  Flash-sale product pages are slow, some carts appear empty after add-to-cart,
  and deploy/config changes fail. Existing checkout pods still serve traffic.

WHAT ON-CALL SEES:
  PostgreSQL replicas lag; Cassandra inventory has one celebrity SKU hot
  partition; etcd leader changes spike after an emergency controller rollout.

BUSINESS CONSTRAINT:
  Avoid oversells and duplicate charges. You can degrade live counters and
  non-critical deploys, but the sale should continue if existing capacity is safe.
```

---

## 2. Telemetry pack

```text
REPLICATION / POSTGRES:
  checkout write TPS: 3,100 -> 8,700
  replica lag: r1=1.2s r2=24s r3=2.0s
  primary PgBouncer: cl_active=700 cl_waiting=560 sv_active=240 sv_idle=0
  semi-sync commit latency: 7ms -> 310ms
  cart reads routed_to_primary=92% after hotfix

SHARDING / INVENTORY:
  Cassandra hot partition (auction_id='watch-8844', bucket='live') reads=61k/s
  three replica nodes CPU=[96,94,93]; cluster median=41
  Redis summary key reads=160k/min on one slot
  token movement active: 220MB/s streaming; compactions active=28

CONSENSUS / CONTROL PLANE:
  etcd leader changes: +9 in 5 min
  etcd WAL fsync p99: 5ms -> 260ms
  proposals_pending: 35 -> 21,000
  143 nodes marked NotReady; eviction timers=4m remaining
  checkout serving capacity=68% utilized and stable
```

---

## 3. Config pack

```yaml
checkout_reads:
  route_all_cart_reads_to_primary: true   # wrong broad hotfix
postgres:
  synchronous_commit: remote_apply
  primary_pgbouncer_max_server_conn: 240

inventory_table:
  primary_key: "((auction_id, bucket), event_time)"  # wrong for celebrity SKU
incident_action:
  move_cassandra_tokens_now: true
  use_redis_summary_as_checkout_truth: false

control_plane:
  rollout_max_concurrent_nodes: 800
  writes_per_node: 7
  emergency_drain_notready_nodes: true
  etcd_volume: gp3-baseline-3000-iops
```

---

## 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | P1: cart anomalies, inventory timeouts, API-server write failures. | |
| T+5 | Broad primary-read hotfix and Cassandra token movement are both active. | |
| T+15 | 143 nodes NotReady; someone proposes draining/recreating them. | |
| T+60 | Sale continues; replica lag and hot partition reduced, but control plane backlog remains. | |

---

## 5. Questions

**Q1 - Root-cause chain:** Identify the trigger, amplifiers, and independent failures across replication, sharding, and consensus.

**Q2 - Evidence:** Pick 3 signals per subsystem that confirm the diagnosis.

**Q3 - Sequencing:** Write a first-15-minute mitigation plan. Include what you stop, what you degrade, and what you must not touch.

**Q4 - Bad fix gallery:** Reject these fixes:
- route all reads to the primary
- set `synchronous_commit=off`
- move Cassandra tokens while hot
- use Redis summary as checkout truth
- drain NotReady nodes

**Q5 - Capacity / blast radius:** Calculate/estimate:
- primary PgBouncer waiters from active clients vs server connections
- rollout object writes from 800 nodes x 7 writes/node
- why one Cassandra hot partition does not improve from even token distribution

**Q6 - Durable fix:** Propose postmortem changes for:
- read-your-writes replica routing
- celebrity SKU partitioning/counter design
- etcd/control-plane rollout safety

**Q7 - Org / runbook:** Who is informed by T+10, and which durability/control-plane actions require explicit senior approval?

---

## 6. Self-score

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Wrong subsystem | | |
| Unsafe first action | | |
| Capacity miss | | |
| Consistency/durability miss | | |
| Control-plane/data-plane confusion | | |

**Answer key:** [`../answers/Ops-Sims/Week-04-Northstar-Flash-Sale-Cascade Answers.md`](../answers/Ops-Sims/Week-04-Northstar-Flash-Sale-Cascade%20Answers.md)
