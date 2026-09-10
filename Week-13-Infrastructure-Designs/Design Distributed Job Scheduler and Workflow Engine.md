# Week 13, Topic 2: Design Distributed Job Scheduler and Workflow Engine

---

## Learning Objectives
```
╔══════════════════════════════════════════════════════════════════════════╗
║   AFTER THIS MODULE, YOU WILL BE ABLE TO:                                ║
╟──────────────────────────────────────────────────────────────────────────╢
║                                                                          ║
║   1. Formulate functional and non-functional requirements for an         ║
║      enterprise job scheduler and DAG workflow engine at 100M+ jobs/day  ║
║                                                                          ║
║   2. Design a clean HLD box-and-arrow architecture separating the        ║
║      API plane, trigger engine, queue broker, and worker fleet           ║
║                                                                          ║
║   3. Compare time-indexed triggers: Redis ZSETs vs Postgres SKIP LOCKED  ║
║      vs Hierarchical Timing Wheels with clear interview tradeoffs        ║
║                                                                          ║
║   4. Solve the dual-execution problem using worker leases, monotonic     ║
║      fencing tokens, and idempotency keys                                ║
║                                                                          ║
║   5. Architect dependency-aware DAG execution, payload handoffs,         ║
║      heterogeneous worker pools, and the midnight thundering herd        ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Section 2: Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Just run Linux cron on a server and hit worker APIs" ║
╟──────────────────────────────────────────────────────────────────────────╢
║   WRONG. Single-server cron is a SPOF. If the node reboots or loses      ║
║   connectivity at midnight, jobs are silently dropped with zero retry    ║
║   tracking, zero horizontal scaling, and zero execution visibility.      ║
╠══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Query SELECT * FROM jobs WHERE trigger_at <= NOW()"  ║
╟──────────────────────────────────────────────────────────────────────────╢
║   WRONG. At millions of jobs, polling an indexed table every second      ║
║   causes severe B-Tree lock contention, CPU thrashing, and connection    ║
║   starvation on database primaries.                                      ║
╠══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "The scheduler can guarantee exactly-once execution"  ║
╟──────────────────────────────────────────────────────────────────────────╢
║   WRONG. Networks are lossy (Two Generals Problem). Schedulers provide   ║
║   at-least-once delivery; idempotency keys in downstream worker logic    ║
║   guarantee effective exactly-once execution.                            ║
╠══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Kafka can be used directly as a delayed task queue"  ║
╟──────────────────────────────────────────────────────────────────────────╢
║   WRONG. Kafka is an append-only sequential log. You cannot easily skip  ║
║   ahead to read a task due in 5 seconds while leaving a task due in      ║
║   3 hours ahead of it in the log. Delay queues require time-indexing.    ║
╠══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Retry failed jobs immediately to meet execution SLAs"║
╟──────────────────────────────────────────────────────────────────────────╢
║   WRONG. If downstream services are degraded, immediate retries multiply ║
║   traffic, creating a self-inflicted DDoS wave. Retries must always use  ║
║   exponential backoff with decorrelated jitter.                          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Section 3: Requirements & Sizing Calculations

### 1. Functional Requirements

```
FUNCTIONAL REQUIREMENTS (Interview Scope):
  P0 — Core Requirements (Must Cover):
    → Submit Job: Clients submit one-time delayed jobs (e.g., "Run in 30 mins").
    → Recurring Cron: Schedule recurring jobs via standard cron expressions (e.g., "0 0 * * *").
    → DAG Workflow Dependencies: Chain dependent tasks (A -> B & C -> D).
    → Job Execution: Disperse jobs to worker fleet with at-least-once delivery.
    → Status & Tracking: Query current execution status (PENDING, RUNNING, SUCCEEDED, FAILED).

  P1 — Desirable Features:
    → Automatic Retries: Configurable exponential backoff with max retry limits.
    → Cancellation: Cancel queued or scheduled jobs before execution.
    → Heterogeneous Worker Routing: Route GPU, high-memory, and I/O tasks to specialized pools.
```

### 2. Capacity Sizing (Back-of-the-Envelope)

| Factor | Metric | Average Load | Peak Load (3x Burst) | 1-Year Requirement |
| :--- | :--- | :--- | :--- | :--- |
| **1. Throughput (RPS)** | New Job Submissions | ~1,160 jobs/sec | 3,500 jobs/sec | 36.5 Billion jobs/yr |
| **2. Trigger Dispatch** | Due Tasks Dispatched | ~1,160 tasks/sec | 10,000 tasks/sec (Midnight) | — |
| **3. Storage Growth** | Job Metadata (1 KB / job) | 1.16 MB/sec | 3.5 MB/sec | ~36.5 TB / year |
| **4. In-Memory Working Set**| Next 1-Hour Active Trigger Set | ~4.2M active jobs | ~12.5M active jobs | ~1.5 GB in Redis |
| **5. Network Bandwidth** | Payload ingress / egress | ~1.2 MB/s In / ~2.5 MB/s Out | ~3.6 MB/s In / ~7.5 MB/s Out | Standard 1 Gbps NIC |

---

## Section 4: High-Level Design (HLD) Box-and-Arrow

```
                        DISTRIBUTED JOB SCHEDULER — HLD BLUEPRINT
                        ═════════════════════════════════════════

  ┌──────────────────┐           ┌──────────────────┐
  │ User Client Apps │           │ Internal Cron UI │
  └────────┬─────────┘           └────────┬─────────┘
           │                              │
           └──────────────┬───────────────┘
                          │ HTTP / gRPC (POST /v1/jobs)
                          ▼
             ┌─────────────────────────┐
             │ API Gateway & Auth Rate │
             └────────────┬────────────┘
                          │
                          ▼
             ┌─────────────────────────┐
             │  Scheduler Ingress API  │ ──► Large Payload? ──► [ S3 / Blob Storage ]
             └────────────┬────────────┘                        (Stores >64KB payloads)
                          │
          ┌───────────────┴─────────────────┐
          │ (1) Async Persist               │ (2) Push Due Time
          ▼                                 ▼
  ┌─────────────────────────┐       ┌─────────────────────────────┐
  │ Primary Relational DB   │       │ Sharded Delay Queue (Redis) │
  │ (Postgres / CockroachDB)│       │ `delay_queue:{0..15}`       │
  │ - State of record       │       │ (score = EpochMs, id = task)│
  │ - DAG dependency graph  │       └──────────────┬──────────────┘
  └─────────────────────────┘                      │
                                                   │ (3) Atomic Lua poll & pop
                                                   ▼
                                    ┌─────────────────────────────┐
                                    │ Scheduler Coordinator Fleet │
                                    │ (etcd Leader / Shard Pollers│
                                    └──────────────┬──────────────┘
                                                   │
                                                   │ (4) Enqueue by capability
                                                   ▼
                                    ┌─────────────────────────────┐
                                    │ Worker Message Broker       │
                                    │ (Kafka / RabbitMQ / SQS)    │
                                    │ - topic: `tasks:default`    │
                                    │ - topic: `tasks:gpu`        │
                                    │ - topic: `tasks:high-mem`   │
                                    └──────────────┬──────────────┘
                                                   │
                                                   │ (5) Pull task & acquire lease
                                                   ▼
                                    ┌─────────────────────────────┐
                                    │ Specialized Worker Fleets   │
                                    │ (Standard, GPU, High-Mem)   │
                                    └──────────────┬──────────────┘
                                                   │
                    ┌──────────────────────────────┴────────────────────────────┐
                    ▼                                                           ▼
         [ Payment Settlement API ]                                   [ Email / Notification ]
```

### End-to-End Data Flow

```
STEP 1: SUBMISSION
  Client calls POST /v1/jobs with payload and trigger time (`run_at`).
  The Ingress Service:
    1. If payload > 64 KB, writes raw data to S3 and retains S3 URI pointer.
    2. Generates unique `job_id` and records job definition in Postgres (State = PENDING).
    3. Hashes `job_id % 16` and pushes into Redis Delay Queue shard `delay_queue:{i}` with score = EpochMs.
    4. Returns `202 Accepted` with `job_id` immediately.

STEP 2: TRIGGER & DISPATCH
  The Scheduler Coordinator Fleet periodically polls shards:
    1. Dedicated poller for shard `i` executes atomic Redis Lua script:
       Pops due items where score <= NOW().
    2. Inspects task resource label (e.g. "GPU", "DEFAULT") and pushes to Kafka topic `tasks:{capability}`.

STEP 3: WORKER EXECUTION & LEASING
  1. An eligible Worker pulls the task from its capability topic.
  2. Worker acquires a 30-second TTL lease in Redis (`SET lease:job_id worker_123 EX 30 NX`).
  3. Worker executes business logic while a background heartbeat thread renews the TTL every 10s.
  4. On completion, worker updates Postgres (State = SUCCEEDED) and publishes completion event.
  5. DAG orchestrator resolves downstream children and transitions newly unblocked tasks to `READY`.
```

---

## Section 5: Core Technical Deep Dives (Interview Focus)

### Deep Dive 1: Time-Indexed Triggers — How to Find Due Jobs

```
╔═══════════════════════════════════════════════════════════════════════════════════════════╗
║ OPTION               │ MECHANICS                 │ PROS                   │ CONS          ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ 1. Relational DB     │ SELECT * FROM jobs WHERE  │ ACID durable; zero     │ High disk I/O;║
║    Polling           │ trigger_at <= NOW()       │ extra infrastructure   │ lock thrashes ║
║                      │ FOR UPDATE SKIP LOCKED    │ needed                 │ > 2k QPS      ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ 2. Sharded Redis     │ ZADD key epoch_ms job_id  │ Sub-millisecond        │ Requires      ║
║    Sorted Set (ZSET) │ ZRANGEBYSCORE 0 NOW       │ in-memory dispatch;    │ persistence   ║
║                      │ Atomic pop via Lua script │ partitions across cores│ log (AOF)     ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ 3. Hierarchical      │ Circular bucket wheels    │ O(1) tick dispatch;    │ In-memory;    ║
║    Timing Wheels     │ (Sec -> Min -> Hour)      │ ultra-low CPU overhead │ complex state ║
║    (Netty / Kafka)   │ advance slot each tick    │ at massive scale       │ persistence   ║
╚═══════════════════════════════════════════════════════════════════════════════════════════╝
```

**Recommended Interview Talking Points:**
* **Scale-Out Strategy:** Store active 1-hour due jobs in **Sharded Redis ZSETs** (`delay_queue:{0..15}`). Partitioning across 16 keys spreads load across multi-core Redis clusters.
* **Atomic Pop via Lua Script:** Prevents multiple master pollers from grabbing the same due task:
  ```lua
  local tasks = redis.call('ZRANGEBYSCORE', KEYS[1], 0, ARGV[1], 'LIMIT', 0, ARGV[2])
  if #tasks > 0 then redis.call('ZREM', KEYS[1], unpack(tasks)) end
  return tasks
  ```
* **Tiered Storage:** Only jobs due in the next 60 minutes are loaded into Redis. Long-term jobs (e.g. run in 3 weeks) remain parked in PostgreSQL and are hydrated into Redis by a background loader.

### Deep Dive 2: Preventing Dual Execution (The Zombie Worker Problem)

```
THE FAILURE SCENARIO:
  1. Worker A takes Job #42 with a 30-second lease.
  2. Worker A enters a 45-second JVM Garbage Collection pause or network hiccup.
  3. The lease expires in Redis. The scheduler assumes Worker A died.
  4. Worker B acquires Job #42 and executes it.
  5. Worker A wakes up and commits Job #42! -> DUPLICATE CHARGE / CORRUPTION!

INTERVIEW DEFENSE MECHANISMS:
  1. Monotonic Fencing Tokens (Martin Kleppmann):
     - Distributed lock service returns an auto-incrementing token (e.g., Token = 101).
     - Storage engine enforces atomic conditional update:
       UPDATE jobs SET status = 'SUCCEEDED', fencing_token = :token
       WHERE job_id = :id AND fencing_token < :token;
     - Worker A's commit with stale token 101 is rejected because Worker B already wrote token 102!
  2. Worker Business Idempotency Keys:
     - For non-database side effects (e.g., calling Stripe API), pass a deterministic idempotency key:
       `idempotency_key = hash(job_id, scheduled_date)`
     - Downstream payment or email gateway discards duplicate submissions.
```

### Deep Dive 3: Directed Acyclic Graph (DAG) Execution & Payload Passing

```
                     [ Extract Data ] (Task A)
                            │ Output: writes s3://bucket/taskA.parquet
               ┌────────────┴────────────┐
               ▼                         ▼
       [ Transform Region 1 ]   [ Transform Region 2 ]
             (Task B)                  (Task C)
               │                         │
               └────────────┬────────────┘
                            ▼
                     [ Load to Warehouse ]
                           (Task D)

KEY SENIOR INTERVIEW MECHANICS:
  1. Intermediate Payload Passing:
     - NEVER pass large datasets (e.g., 500MB CSVs) through Kafka or Postgres.
     - Task A writes output to S3 (`s3://workflows/{wf_id}/task_a.parquet`).
     - Task A publishes completion event containing only metadata: `{task_id: "A", output_uri: "s3://..."}`.
     - Downstream Tasks B & C read directly from the S3 URI.
  2. Dependency State Progression:
     - When Task B finishes, it publishes `TaskFinished(Task B)`.
     - DAG Coordinator updates state in PostgreSQL: decrements `unresolved_parents` count for Task D.
     - When count reaches 0, Task D transitions from `PENDING` to `READY` and is enqueued.
  3. Cascading Failure Policy:
     - If Task B fails and exceeds max retries, Task B transitions to `FAILED`.
     - The orchestrator marks all downstream transitive dependencies (Task D) as `SKIPPED` (fail-fast).
```

### Deep Dive 4: The Midnight Thundering Herd (Schedule Jitter)

```
PROBLEM:
  Millions of users set reports to run at exactly "00:00:00 UTC".
  At midnight, 5,000,000 tasks become due at the same millisecond.
  Redis CPU pegs at 100%, queues backlog, and downstream databases crash.

SOLUTION:
  For jobs that do not require exact second precision (e.g., daily analytics syncs):
  Apply deterministic schedule jitter:
    run_at = 00:00:00 + (hash(account_id) % 900 seconds)
  Spreads the 5M tasks evenly across a 15-minute window, reducing peak load by 900x!
```

### Deep Dive 5: Multi-Tenant Fair-Share Queuing

```
PROBLEM:
  Tenant A dumps 10,000,000 batch tasks at 00:00:00.
  Tenant B submits 5 real-time transactional tasks.
  Without fair-share controls, Tenant B waits 4 hours behind Tenant A's batch backlog!

SENIOR INTERVIEW SOLUTION:
  1. Separate Priority Queues: High Priority (real-time customer actions) vs Low Priority (batch syncs).
  2. Deficit Round Robin (DRR) or Tenant Rate Limits:
     - Ingress API limits max in-flight tasks per tenant.
     - Workers pull tasks round-robin across active tenant queues rather than draining one tenant completely.
```

---

## Section 6: API Design & Data Models

### 1. REST APIs

```http
POST /v1/jobs
Content-Type: application/json
{
  "name": "generate_monthly_invoice",
  "schedule_type": "ONE_TIME", // or "RECURRING"
  "cron_expression": "0 0 1 * *",
  "run_at": "2026-10-01T00:00:00Z",
  "resource_label": "DEFAULT", // or "GPU", "HIGH_MEM"
  "payload": { "account_id": "acc_8921" },
  "retry_config": { "max_retries": 3, "backoff_seconds": 10 }
}
Response: 202 Accepted { "job_id": "job_99a8f21b", "status": "PENDING" }

GET /v1/jobs/job_99a8f21b
Response: 200 OK
{
  "job_id": "job_99a8f21b",
  "status": "RUNNING",
  "worker_id": "worker_pod_7b",
  "started_at": "2026-10-01T00:00:02Z",
  "retry_count": 0
}
```

### 2. Database Schema

```sql
CREATE TABLE jobs (
    job_id UUID PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING', -- PENDING, READY, RUNNING, SUCCEEDED, FAILED, SKIPPED
    schedule_type VARCHAR(16) NOT NULL,            -- ONE_TIME, CRON, DAG
    trigger_at TIMESTAMPTZ NOT NULL,
    resource_label VARCHAR(32) DEFAULT 'DEFAULT',  -- DEFAULT, GPU, HIGH_MEM
    payload_uri TEXT,                              -- S3 URI for large payloads (>64KB)
    max_retries INT DEFAULT 3,
    retry_count INT DEFAULT 0,
    fencing_token BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_jobs_due ON jobs (trigger_at) WHERE status = 'PENDING';

CREATE TABLE dag_edges (
    workflow_id UUID NOT NULL,
    parent_job_id UUID NOT NULL,
    child_job_id UUID NOT NULL,
    PRIMARY KEY (workflow_id, parent_job_id, child_job_id)
);
```

---

## Section 7: Failure Modes & Self-Healing Resilience

```
╔═══════════════════════════════════════════════════════════════════════════════════════════╗
║ FAILURE SCENARIO         │ DETECTION                   │ MITIGATION & RECOVERY            ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Worker Crashes           │ Redis lease TTL expires     │ Scheduler detects expired lease  ║
║ Mid-Task                 │ without heartbeat renewal   │ and re-queues task into broker.  ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Scheduler Coordinator    │ etcd keepalive lease drops; │ Follower node wins Raft election ║
║ Leader Dies              │ missed heartbeat > 3s       │ and takes over shard dispatch.   ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Downstream Service       │ Task execution returns      │ Worker backs off using AWS       ║
║ Returns 503 / 429        │ HTTP 429/503 rate limit     │ decorrelated jitter with cap.    ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Single Worker Runs Away  │ Worker execution time       │ Enforce task-level timeout; send ║
║ (Infinite Loop)          │ exceeds hard threshold (10m)│ SIGKILL and mark status FAILED.  ║
╚═══════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 8: Interview Tradeoffs & Architecture Matrix

```
┌────────────────────────┬──────────────────────────┬───────────────────────────────┐
│ System Layer           │ Candidate Choices        │ Interview Recommendation      │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Delay Trigger Store    │ Postgres vs Redis ZSET   │ Redis ZSET: sub-millisecond   │
│                        │ vs Hashed Wheel Timer    │ range scans, memory fast.     │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Coordination / Leader  │ etcd / Raft vs ZooKeeper │ etcd: lightweight leader      │
│                        │ vs DB Locks              │ election and partition leases.│
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Worker Dispatch Queue  │ Kafka vs RabbitMQ vs SQS │ SQS / RabbitMQ for ad-hoc;    │
│                        │                          │ Kafka for massive log stream. │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Delivery Semantics     │ Exactly-Once vs          │ At-least-once with worker     │
│                        │ At-Least-Once            │ idempotency keys on side-fx.  │
└────────────────────────┴──────────────────────────┴───────────────────────────────┘
```

---

## Section 9: Interview Scenario Practice (Test Yourself)

```
Q1: "How do you ensure two workers don't pick up and execute the exact same job
     at the same time when polling Redis?"
TALKING POINTS:
  → Use an atomic Redis Lua script combining ZRANGEBYSCORE with ZREM in a single transaction.
  → Because Redis executes Lua scripts as a single atomic operation on its event loop,
    only one caller receives the task.

Q2: "What happens if a job has been scheduled to run at 2:00 AM, but the entire
     scheduler cluster goes down from 1:59 AM to 2:05 AM?"
TALKING POINTS:
  → State is durably preserved in PostgreSQL and Redis.
  → When the cluster boots at 2:05 AM, the poller queries `WHERE trigger_at <= NOW()`.
  → The 2:00 AM job is discovered and immediately dispatched (catch-up execution).
  → For cron jobs with catch-up policies, coalesce missed runs into a single execution.

Q3: "How does the scheduler scale when the number of scheduled tasks grows to 1 Billion?"
TALKING POINTS:
  → Tiered storage: Keep only tasks due in the next 1 hour in Redis; rest stay in Postgres.
  → Partition Redis delay queues into N virtual shards (e.g., `delay_queue:{0..15}`).
  → Partition workers into specialized pools (e.g., high-memory, GPU, fast-IO).

Q4: "How do you pass 500MB of intermediate data from Task A to Task B in a DAG workflow?"
TALKING POINTS:
  → Never pass heavy blobs through Kafka or PostgreSQL.
  → Task A writes output directly to S3/GCS (`s3://workflows/{id}/taskA.parquet`).
  → Task A emits completion event containing only the S3 URI metadata pointer.
  → Task B downloads the payload directly from S3 when it starts.

Q5: "What if a task takes 4 hours (e.g. video rendering)? How do you prevent the 30-second
     lease from timing out without setting an unsafe 4-hour lease?"
TALKING POINTS:
  → Keep lease short (30s). A background worker thread sends heartbeats every 10s to extend TTL.
  → If the worker crashes or freezes, lease expires in <= 30 seconds rather than 4 hours.
  → Worker saves intermediate checkpoints (e.g. frame offset) so retries resume from checkpoint.
```
