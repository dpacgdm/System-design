# WEEK 13 RETENTION TEST

Covers **Weeks 1-13** with emphasis on distributed KV stores, Kafka, configuration stores, consensus, and data loss.

---

## Rules

```text
RULES OF ENGAGEMENT

1. Answer from memory. Do not open answer files or design modules.
2. Keep rapid-fire answers to 2-4 sentences.
3. Treat the Ops Sim as a real incident: evidence, decision, verification.
4. Say "I do not remember" rather than inventing facts.
5. Open the answer key only after attempting every section.
```

---

## Part 1: Rapid-Fire Concept Recall (16 Questions)

**Q1 (Current - KV):** In a Dynamo-style KV store with RF=3, R=2, W=2, why does R+W>N matter, and what does it not solve?

**Q2 (Current - KV):** What are hinted handoff and anti-entropy repair solving, and why can hint replay become dangerous after a node returns?

**Q3 (Current - KV):** A hot partition causes compaction backlog and p99 read latency. Why does adding random nodes not immediately fix that key?

**Q4 (Current - Kafka):** Kafka is a distributed log, not a queue. What does that mean for retention, offsets, and multiple consumers?

**Q5 (Current - Kafka):** Explain `acks=all`, ISR, and `min.insync.replicas=2` for RF=3.

**Q6 (Current - config store):** Why is a configuration/coordination store usually CP/Raft rather than AP/gossip?

**Q7 (Current - watches):** What is a watch storm, and how do watch proxies/local agents reduce load?

**Q8 (Current - leases):** Why do distributed locks need fencing tokens in addition to TTL leases?

**Q9 (Mid - outbox):** Why should a database remain the payment ledger source of truth even if Kafka has exactly-once producer support?

**Q10 (Mid - feature flags):** What is the difference between a feature flag stored in Redis cache and a config change coordinated by etcd?

**Q11 (Mid - observability):** Name three metrics that indicate Kafka durability risk before produce errors spike.

**Q12 (Mid - Cassandra):** What does `gc_grace_seconds` protect against, and why is repair schedule tied to it?

**Q13 (Old - CAP):** During a network partition, what is the user-visible difference between AP leaderless KV and CP Raft config store?

**Q14 (Old - rate limits/tenancy):** How do per-tenant coordinator limits protect a shared KV store?

**Q15 (Old - CDN/caching):** Why should config clients cache locally, but not continue using stale dangerous config forever?

**Q16 (Old - cost/capacity):** Why does RF=3 multiply disk and write bandwidth, and what extra overhead does compaction add?

---

## Part 2: Compound Ops Sim - Consensus and Data Loss at Northstar

```text
INCIDENT REPORT

Severity: P0
Company: Northstar Commerce
Systems:
  - inv-cas: Cassandra/Dynamo-style inventory KV
  - payment-events: Kafka/MSK
  - config-store: etcd for feature flags and service discovery
  - checkout-api and pay-ledger consumers

Business event:
  Flash sale with a new `inventory_fast_reserve` flag. The flag is stored
  in config-store and watched by checkout-api. Payment events publish to
  Kafka; inventory reservations write to inv-cas.

Timeline:
  12:00 - Sale starts.
  12:04 - etcd leader changes repeatedly.
  12:08 - Kafka under-replicated partitions rise.
  12:11 - Inventory KV p99 jumps to 2.8s for one SKU family.
  12:16 - Producers continue after ISR shrinks to 1.
  12:23 - Broker with unflushed logs dies; payment events missing in audit.
  12:31 - Some checkout pods still use old config revision.
```

### Telemetry Pack

```text
config-store (etcd):
  nodes=3, quorum=2
  leader_changes_seen_total: +47 in 15 min
  db_size: 7.9GB / 8GB quota
  watch streams on /: 18,000
  watch_compacted_errors/min: 2,400
  disk_wal_fsync_p99: 180ms

Kafka:
  topic payment-events RF=3 partitions=240
  min.insync.replicas=1
  producer acks=1
  unclean.leader.election.enable=true
  UnderReplicatedPartitions: 0 -> 96
  OfflinePartitionsCount: 0 -> 12
  broker-7 disk used: 99%
  audit gap: offsets 88312900-88324150 unavailable after leader election

Inventory KV:
  RF=3, LOCAL_QUORUM reads/writes
  hot key prefix: sku:flash:console:*
  coordinator_timeout_rate: 0.1% -> 9%
  pending_compactions: 4 -> 88
  hints_in_progress: 0 -> 12M
  tombstones/read p95: 15,600

Checkout:
  config revision desired: 582901
  pods on revision 582901: 62%
  pods on old revision 582811: 38%
  order duplicate reserve attempts: +6.5%
```

### Config Pack

```text
etcd:
  auto-compaction-retention=1h
  snapshot-count=100000
  no watch proxy; apps watch / directly
  large flag payload: 1.3MB

Kafka producers:
  acks=1
  enable.idempotence=false
  retries=3
  delivery.timeout.ms=120000

Kafka brokers:
  min.insync.replicas=1
  unclean.leader.election.enable=true
  log.retention.hours=168

Inventory KV:
  compaction=STCS
  gc_grace_seconds=864000
  repair cadence=monthly
  per-tenant coordinator rate limits=disabled
```

### Decision Points

**T+0:** Which system do you protect first for correctness: etcd, Kafka, or inventory KV? What immediate safety switches do you throw?

**T+5:** Producers are still accepting payment events with `acks=1` while ISR is unhealthy. What config changes or traffic actions are acceptable?

**T+15:** Inventory hot keys are timing out. Do you lower consistency, add nodes, rate limit, or split keys? Give a short-term and long-term answer.

**T+60:** Payment event gaps are confirmed. What reconstruction path uses ledgers, outbox tables, PSP data, and Kafka audit?

### Scenario Questions

1. Identify all data-loss risks and classify actual vs potential.
2. Explain how etcd watch misuse can leave pods on stale config even while the cluster is "up."
3. Explain the Kafka durability failure using ISR, acks, and unclean leader election.
4. Explain the KV hot-partition cascade and why hinted handoff can amplify it.
5. **Bad-fix gallery:** Analyze (a) set all inventory reads/writes to ONE, (b) restart all etcd nodes, (c) enable unclean election to restore availability, (d) add Kafka consumers, (e) run full Cassandra repair during peak.
6. **Capacity question:** If one SKU prefix generates 40% of 200k writes/sec and RF=3, what write load hits the replica set before compaction overhead?
7. **Org/runbook question:** What invariants should be enforced for Kafka payment topics, etcd watches, KV tenant limits, and flash-sale launch reviews?

---

## Self-Score Error-Type Table

| Error type | Count | Notes to review |
|------------|-------|-----------------|
| Quorum/consistency error | | |
| Kafka durability/ISR error | | |
| etcd/Raft/watch error | | |
| KV hot partition/repair error | | |
| Data-loss reconstruction error | | |
| Bad-fix sequencing error | | |
| Capacity math error | | |
| Org/runbook gap | | |

---

> **Answer key (do not open until you attempt the test):**  
> [`../answers/Retention-Tests/Week-13 Answers.md`](../answers/Retention-Tests/Week-13%20Answers.md)
