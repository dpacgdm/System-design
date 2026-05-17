# Worked Answers — Cassandra Architecture

This companion retrofit answers the principal-grade questions implied by the Cassandra Architecture module. The focus is production reasoning: consistency levels, write/read paths, tombstones, compaction, repair, hotspots, and incident response.

---

## Answer 1 — Choosing Cassandra correctly

### Scenario

```text
A team wants Cassandra for:
  - shopping cart
  - payment ledger
  - clickstream events
  - user profile records
  - inventory counters

Which workloads fit Cassandra, and which are dangerous?
```

### Principal answer

Cassandra is strongest when the workload is high-write, horizontally scalable, partition-key driven, and tolerant of its query model. It is weakest when the workload needs ad hoc joins, multi-row transactions, strong global constraints, or financial correctness without careful modeling.

```text
Shopping cart:
  Maybe fit if modeled per user/cart and conflict semantics are explicit
  Risk: concurrent updates, LWW, item merge semantics, abandoned carts

Payment ledger:
  Dangerous as primary source of truth unless architecture is extremely deliberate
  Reason: ledgers need auditability, constraints, idempotency, reconciliation, often relational semantics
  Better: relational ledger source of truth; Cassandra may store derived high-volume views

Clickstream events:
  Strong fit
  Reason: append-heavy, partitionable, TTL/retention-oriented, high write volume
  Caveat: TTL creates tombstones; design buckets and compaction accordingly

User profile:
  Maybe fit for simple key-value profile reads
  Risk: partial updates, uniqueness constraints, email lookup, conflict semantics

Inventory counters:
  Dangerous if exact inventory is required
  Reason: counters, conflicts, and eventual consistency can oversell
  Better: reservation/ledger model with strong source-of-truth, Cassandra as derived availability view
```

Principal rule:

```text
Cassandra rewards query-first modeling and punishes relational thinking.
If the business invariant needs global correctness, prove the model before choosing Cassandra.
```

---

## Answer 2 — Write path and consistency levels

### Scenario

```text
Cluster: 9 nodes across 3 AZs
Replication factor: 3
Write consistency: QUORUM
A client writes order_event(user_id=123, event_id=abc)

Explain the write path and what QUORUM means.
```

### Principal answer

The client sends the write to a coordinator node. The coordinator uses the partitioner to map the partition key to a token range and identify replicas. It sends the mutation to the replicas responsible for that key. Each replica writes to the commit log for durability and updates the memtable. Later the memtable flushes to immutable SSTables.

With RF=3 and QUORUM:

```text
quorum = floor(RF / 2) + 1 = 2
```

The write succeeds after two of three replicas acknowledge. The third may receive the write later, or be repaired through hinted handoff/read repair/anti-entropy repair depending the failure and configuration.

Important nuance:

```text
QUORUM does not mean all replicas have the write.
It means enough replicas acknowledged to create overlap with a future QUORUM read.
```

Failure cases:

```text
one replica down:
  write can still succeed with two acknowledgements

two replicas down:
  QUORUM write fails

slow replica:
  coordinator waits until enough responses arrive or timeout occurs
```

Principal operational signal:

```text
Write timeouts do not always mean write failure.
A timeout can be ambiguous if some replicas applied the write but the coordinator did not receive enough acknowledgements in time.
```

That is why idempotent writes and retry discipline matter.

---

## Answer 3 — Read path, stale reads, and repair

### Scenario

```text
A service reads inventory_available by sku.
Cassandra uses RF=3 and LOCAL_QUORUM reads.
Users occasionally see stale inventory.
Explain how that can happen and what to inspect.
```

### Principal answer

A Cassandra read goes to a coordinator. The coordinator contacts replicas according to consistency level. Replicas check memtables and SSTables, using bloom filters and indexes to avoid unnecessary disk reads. The coordinator reconciles responses using timestamps and returns the winning value.

With LOCAL_QUORUM, stale reads are reduced but not impossible from the application perspective. Causes include:

```text
write was not actually successful at required CL
client retried non-idempotently
read and write used inconsistent CL choices
clock/timestamp issues affect last-write-wins resolution
tombstones or compaction cause slow reads/timeouts
application is reading a derived view that lags source-of-truth
multi-region LOCAL_QUORUM only guarantees local DC quorum, not global latest
```

Inspect:

```text
read latency by table and percentile
coordinator vs replica latency
read timeout/unavailable counts
SSTables per read
bloom filter false positives
tombstone scanned warnings
repair status
consistency level used by actual clients
whether reads hit the same DC as writes
```

Principal sentence:

```text
Consistency level is a contract only if every client uses the expected read/write CL and the data model matches the invariant.
```

---

## Answer 4 — Tombstone incident reasoning

### Scenario

```text
A notification table uses TTL=7 days.
Traffic is high.
After a month, reads by user_id start timing out.
CPU is normal, disk is busy, and logs show tombstone warnings.
```

### Principal answer

TTL creates tombstones when data expires. Tombstones are retained long enough to ensure deletes propagate to replicas. Reads must scan and reconcile tombstones until compaction safely purges them. A TTL-heavy workload can create a graveyard under a hot partition.

Why CPU can be normal:

```text
bottleneck is disk reads and SSTable scanning, not pure compute
queries scan many expired cells/tombstones
compaction may be behind
large partitions amplify the problem
```

Immediate actions:

```text
identify table/partition patterns producing tombstone scans
check query shape: is it reading wide partitions?
check compaction backlog and disk I/O
reduce or disable expensive query path if possible
rate-limit affected workload
avoid blind node restarts; they do not remove tombstones
```

Long-term fixes:

```text
bucket partitions by time: user_id + day/week
choose TTL aligned with compaction strategy
use TimeWindowCompactionStrategy for time-series TTL workloads
avoid querying across large expired ranges
monitor tombstones scanned per query
redesign table to avoid unbounded partition growth
```

Principal line:

```text
Tombstone problems are data-model problems that surface as latency incidents.
```

---

## Answer 5 — Compaction and repair tradeoffs

### Scenario

```text
A Cassandra cluster shows rising read latency and many SSTables per read.
An engineer says: “Run major compaction now.”
```

### Principal answer

Major compaction can reduce SSTable count, but it is a heavy operation. It can consume disk I/O, CPU, and temporary disk space, and may worsen customer-facing latency during peak traffic. It can also create very large SSTables that are less convenient for future incremental compaction.

First inspect:

```text
pending compactions
SSTables per read histogram
read amplification
write amplification
free disk headroom
table compaction strategy
hot partitions
tombstone warnings
repair status
node-level I/O utilization
```

Safer actions:

```text
throttle compaction
run targeted compaction off-peak
add capacity before compaction if disk headroom is low
fix query/data model if large partitions are the cause
use table-appropriate compaction strategy
```

Repair distinction:

```text
Compaction cleans/merges local SSTables.
Repair compares replicas and fixes divergence.
```

Running compaction does not guarantee replica consistency. Running repair does not magically fix poor query modeling.

Principal answer:

```text
Never prescribe compaction as a ritual. Name the symptom it fixes, the resource it consumes, and the risk window it creates.
```

---

## Answer 6 — Partial AZ impairment with LOCAL_QUORUM

### Scenario

```text
3-AZ Cassandra cluster.
Nodes are up, but AZ-b has packet loss.
LOCAL_QUORUM reads/writes start timing out.
Node health dashboards are green.
```

### Principal answer

Partial failure is harder than clean failure. If a node is cleanly down, clients and coordinators can route around it. If it is up but slow or lossy, coordinators may wait for responses until timeout, clients may retry, and the system may amplify load.

What happens:

```text
coordinator sends requests to replicas
some replicas respond slowly or not at all
coordinator waits for required CL responses
timeouts occur even though nodes are technically alive
client retries increase duplicate pressure
thread pools and request queues grow
p99 latency explodes while median may look okay
```

Inspect:

```text
per-AZ latency
coordinator read/write timeouts
unavailable vs timeout exceptions
client retry rate
speculative execution behavior
network packet loss
pending tasks/dropped messages
repair/hinted handoff accumulation
```

Mitigation:

```text
reduce retry amplification
route coordinators away from impaired AZ if safe
temporarily lower noncritical traffic
protect correctness-critical writes from unsafe CL downgrade
communicate uncertainty to product
```

Principal caveat:

```text
Do not lower consistency level during an incident unless the business accepts the correctness risk.
```

---

## Final rubric

```text
Passing answer:
  - explains coordinator, replicas, commit log, memtable, SSTables
  - knows QUORUM math
  - identifies tombstones and compaction

Principal answer:
  - ties CL choices to business invariants
  - treats timeouts as ambiguous outcomes
  - separates Cassandra root cause from downstream symptoms
  - avoids unsafe CL downgrades
  - recognizes data-model defects behind latency incidents
  - designs monitoring around p99, tombstones, compaction, repair, and per-AZ behavior
```
