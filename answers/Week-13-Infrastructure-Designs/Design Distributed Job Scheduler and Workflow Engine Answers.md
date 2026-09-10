# Answer Key - Week 13: Distributed Job Scheduler and Workflow Engine

> Open only after attempting the learner file scenario questions.

# Incident Deep-Dive: Northstar Financial Midnight Batch Scheduler Meltdown

---

## Question 1: The Three Compounding Root Causes

```
╔══════════════════════════════════════════════════════════════════════════╗
║ COMPOUNDING FAILURE CHAIN (How 12 Million Tasks Collapsed Platform)      ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 1. UNJITTERED TEMPORAL COINCIDENCE (Midnight Thundering Herd)            ║
║    → 12,000,000 tasks were configured for the exact timestamp 00:00:00.  ║
║    → Concentrated an entire day's batch workload into a 1ms window.      ║
║    → Redis single-threaded event loop on Shard 0 locked 100% CPU         ║
║      executing large ZRANGEBYSCORE range scans over millions of items.   ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 2. CONTROL-PLANE CASCADING TIMEOUT & RAFT ELECTION FLAPPING              ║
║    → Master Node 1 event loop blocked waiting on Redis socket reads.     ║
║    → Because heartbeats shared the same process thread/event loop,       ║
║      Master Node 1 missed its Raft heartbeat deadline (3,000ms).         ║
║    → Triggered unneeded Raft elections across the 3-node master cluster. ║
║      During election flapping, leader dispatch halted for 4 minutes,     ║
║      allowing the queue of pending due tasks to balloon even further.    ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 3. CONNECTION POOL SATURATION & UNJITTERED RETRY AMPLIFICATION           ║
║    → When Master Node 2 stabilized, it dumped 500k task IDs into Kafka.  ║
║    → 200 worker pods pulled tasks, each opening 5 Postgres connections.  ║
║    → 200 pods * 5 connections = 1,000 connections (max_connections hit). ║
║    → PostgreSQL began refusing connections (53300: too many clients).    ║
║    → Workers failed to write task completion state to PostgreSQL,        ║
║      assumed the task failed, and immediately re-enqueued into Kafka!    ║
║    → Multiplied Kafka traffic from 500k to 1,000k tasks (self-DDoS).     ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Question 2: Mathematical Analysis of Schedule Jitter

### Throughput Reduction Calculation

```
WITHOUT JITTER:
  12,000,000 tasks due at T = 00:00:00 UTC.
  Target dispatch window: 1 second.
  Peak Instantaneous Arrival Rate (Lambda_peak):
    Lambda_peak = 12,000,000 tasks / 1 second = 12,000,000 tasks/sec.
  Redis Single-Shard ZSET Capacity: ~80,000 ops/sec.
  Overload Ratio: 12,000,000 / 80,000 = 150x over maximum theoretical saturation!

WITH DETERMINISTIC HASH JITTER:
  Formula: trigger_at = 00:00:00 + (hash(account_id) % 900 seconds)
  Window length: W = 900 seconds (15 minutes).
  Distribution: Uniformly distributed across 900 discrete seconds.
  Average Arrival Rate (Lambda_jitter):
    Lambda_jitter = 12,000,000 tasks / 900 seconds = 13,333 tasks/sec.

THROUGHPUT REDUCTION FACTOR:
  Reduction Factor = Lambda_peak / Lambda_jitter = 12,000,000 / 13,333 = 900x reduction!

ACROSS 6 REDIS SHARDS:
  Per-shard load = 13,333 / 6 = 2,222 ops/sec.
  Utilization: 2,222 / 80,000 = 2.7% of Redis shard CPU capacity.
  The cluster transitions from catastrophic CPU saturation to virtually idle headroom!
```

---

## Question 3: PACELC Analysis of Worker Database Starvation

```
PACELC MAPPING OF NORTHSTAR FINANCIAL SETTLEMENT ENGINE:

  Normal Operation (E):
    → Should be EC (Else Consistency): Financial settlement transactions MUST commit
      synchronously to maintain strict double-entry ledger balance invariants.

  During Partition / Resource Exhaustion (P):
    → The system attempted to act as PC (rejecting connection requests when limits exceeded).
    → HOWEVER, the worker business logic erroneously fell back to PA (Partition Availability):
      When workers couldn't reach Postgres to record task execution status, instead of
      halting and backing off, they treated the error as an ephemeral task retry!
    → In PACELC terms, the worker fleet confused "Storage Unavailable (PC)" with
      "Task Execution Failed (PA)", leading to duplicate money transfers!

WHY WORKERS DUPLICATED TRANSACTIONS:
  1. Worker A executed the inter-bank payment API call against the external bank gateway (Side effect committed!).
  2. Worker A attempted: UPDATE task_executions SET status = 'DONE' WHERE id = 42;
  3. PostgreSQL threw: "FATAL: remaining connection slots are reserved for non-replication superuser connections".
  4. Worker A caught the exception. Because the transaction update failed, Worker A assumed
     the entire task failed.
  5. Worker A re-published Task #42 to Kafka.
  6. Worker B picked up Task #42 and executed the inter-bank payment AGAIN!
  7. ROOT CAUSE: Lack of an Idempotent External Side-Effect Gateway + Lack of Monotonic Fencing Tokens.
```

---

## Question 4: Immediate Incident Commander Containment Runbook

```bash
# ==============================================================================
# SRE INCIDENT COMMANDER IMMEDIATE TRIAGE RUNBOOK (T = 00:08)
# ==============================================================================

# STEP 1: HALT WORKER FLEET INGESTION (SEVER RETRY CASCADE)
# Scale worker consumer deployment to zero immediately to stop hammering PostgreSQL
kubectl scale deployment/settlement-worker-pods --replicas=0 -n batch-processing

# STEP 2: PAUSE KAFKA CONSUMER GROUP
# Ensure Kafka partitions do not rebalance or commit false offsets
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --group settlement-batch-consumers --pause

# STEP 3: TERMINATE ORPHANED POSTGRESQL CONNECTIONS
# Connect as superuser and terminate idle or blocked worker backend processes
psql -U postgres -h postgres-primary -d northstar_db -c "
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE usename = 'batch_worker_user'
  AND (state = 'idle in transaction' OR query_start < NOW() - INTERVAL '30 seconds');
"

# STEP 4: VERIFY POSTGRESQL CONNECTION POOL RECOVERY
psql -U postgres -h postgres-primary -d northstar_db -c "
SELECT count(*), state FROM pg_stat_activity GROUP BY state;
"

# STEP 5: ENABLE CIRCUIT BREAKER ON KAFKA DLQ
# Divert unacknowledged duplicate retries to Dead Letter Queue for deduplication audit
```

---

## Question 5: Permanent Architectural Fix (50,000 Tasks/Sec)

```
╔══════════════════════════════════════════════════════════════════════════╗
║ PERMANENT ARCHITECTURE: TRANSACTIONAL OUTBOX + ASYNC BATCH FLUSH         ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 1. DEDICATED CONNECTION POOLING LAYER (PgBouncer)                        ║
║    → Deploy PgBouncer in Transaction Pooling Mode in front of Postgres.  ║
║    → 200 worker pods share a maximum of 30 physical Postgres server      ║
║      connections. Rejections replaced by microsecond queuing.            ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 2. IDEMPOTENCY KEY GATEWAY AT STORAGE LAYER                              ║
║    → Every settlement task carries a deterministic hash.                 ║
║    → Postgres enforces unique constraint: UNIQUE(idempotency_key).       ║
║    → Duplicate worker executions fail harmlessly with DO NOTHING.        ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 3. ASYNC STATE BATCHING VIA KAFKA COMMIT LOG                             ║
║    → Workers DO NOT write status updates directly to PostgreSQL.         ║
║    → Workers emit completion events to Kafka topic: `task_completions`.  ║
║    → Dedicated State Ingestion Service micro-batches completions:        ║
║      INSERT INTO task_executions VALUES (...), (...) [5k rows/commit].   ║
║    → Scales to 100,000 tasks/sec with < 20 SQL commits/sec on Postgres!  ║
╚══════════════════════════════════════════════════════════════════════════╝
```
