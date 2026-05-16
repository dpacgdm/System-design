## Part 0: Why This Module Exists (read this first)

Every distributed system you will ever build has one bottleneck and it is almost always the database. Not the network, not the CPU, not the language runtime — the database. Compute is elastic; databases are not. Stateless services scale by adding pods; stateful services scale by *engineering effort*.

This module teaches you how to recognize which kind of bottleneck you have, what the cheapest fix is, when to climb to the next rung, and — the part most courses skip — when to **refuse to climb** because the next rung costs more than the problem.

By the end you will be able to:

1. Diagnose a database performance issue from four numbers (CPU, IOPS, connections, replication lag).
2. Pick the right scaling rung for the actual symptom, not the rumored cause.
3. Avoid the four operational landmines that take down Postgres clusters: connection exhaustion, slot bloat, sync replication degradation, and CDC schema drift.
4. Decide between read replicas, native partitioning, sharding, CQRS, and active/active — with confidence in *both directions* (when to add and when to remove).
5. Walk an interviewer through any of the above without hand-waving.


**Prerequisite mental model**: a database is a **log of writes** plus an **index for reads**. Every scaling technique is either (a) reducing reads against the log, (b) splitting the log across machines, or (c) building separate indexes for different read patterns. Hold that and the rest follows.

---

## Part 1: First Principles — Where the Latency Goes

```plaintext
THE PHYSICS OF A DATABASE QUERY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Client                                 Database server
    │                                          │
    │ ── TCP connect (~1ms LAN, ~50ms WAN) ───►│
    │                                          │
    │ ── auth + session setup (~1-5ms) ───────►│
    │                                          │
    │ ── parse SQL ───────────────────────────►│  CPU: 0.1ms
    │                                          │  (PREPARE caches this)
    │                                          │
    │ ── plan query ──────────────────────────►│  CPU: 0.5-50ms
    │                                          │  (depends on stats freshness,
    │                                          │   joined tables, indexes)
    │                                          │
    │ ── execute ─────────────────────────────►│  Variable:
    │                                          │   index lookup: 0.01ms (RAM)
    │                                          │   index lookup: 0.5ms (SSD)
    │                                          │   seq scan 1M rows: 200ms
    │                                          │   seq scan 100M rows: 20s
    │                                          │
    │ ── fsync WAL (writes only) ─────────────►│  0.5-5ms (NVMe RAID)
    │                                          │
    │ ◄── send result rows ──────────────────  │  Network bandwidth
    │                                          │
    │ ── COMMIT ──────────────────────────────►│
    │                                          │
    │ ◄── ack ───────────────────────────────  │


THE FOUR REAL BOTTLENECKS:

  1. CONNECTION SETUP COST
     A new TCP+TLS+auth handshake is ~5ms. Postgres also FORKS A PROCESS
     per connection (~10MB RSS, kernel scheduling overhead).
     If your app opens a fresh connection per request, you are spending
     more time on handshakes than on queries.
     Fix: connection pooling (Part 4).

  2. WAL FSYNC LATENCY (write path)
     Every COMMIT must fsync the WAL to durable storage. On NVMe RAID-10
     this is 0.3-1ms. On EBS gp3 this is 1-3ms. On EBS gp2 with burst
     credits exhausted, 20-100ms. THIS IS USUALLY YOUR WRITE CEILING.
     Fix: better disks, group commit, semi-sync replication tradeoffs.

  3. INDEX MISS / SEQ SCAN (read path)
     Reading 1 row by primary key from RAM: 1µs.
     Reading 1 row by primary key from SSD: 100µs.
     Seq scanning 100M rows: 10-30 seconds. p99 dead.
     Fix: indexes, query rewrite, partitioning to reduce scan size.

  4. LOCK CONTENTION (concurrency)
     Two transactions update the same row: one waits.
     1000 transactions update the same row (a counter): queue depth = 1000.
     The DB looks idle (low CPU) but every query is slow (waiting on locks).
     Fix: change the data model (sharded counters, queues, append-only log).


THE SYMPTOM-TO-CAUSE MAP (memorize this):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom                          Likely cause              First check
  ────────────────────────────     ─────────────────────     ──────────────
  CPU 100%, p99 high               Bad query plan            EXPLAIN ANALYZE
  CPU low, p99 high                Lock contention           pg_locks
  Disk IO 100%, CPU low            Index miss / seq scan     pg_stat_user_tables
  Connection errors                Pool exhaustion           pg_stat_activity
  Replication lag rising           Replica too small         pg_stat_replication
  Disk filling, no traffic spike   Replication slot bloat    pg_replication_slots
  Writes hang, primary "healthy"   Sync replica all dead     pg_stat_replication
  Random app errors after deploy   PgBouncer mode mismatch   PgBouncer pool stats
  Search results stale by hours    CDC pipeline broken       Debezium connector status
```

**Principle.** Before you scale a database, you must know *which physical resource is saturated*. A scaling decision made without that data is gambling with engineering time. The four queries above are your starter kit.

---

## Part 2: The Cost Model

You cannot reason about scaling without reasoning about cost. Every rung you climb costs **money** (more infrastructure) and **complexity** (more failure modes, more on-call). Here is the reality check.

```plaintext
TYPICAL COST PROGRESSION (single web app, ~1000 RPS):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Rung   Setup                              $/month   Failure modes  Eng time
  ────   ────────────────────────────────   ───────   ─────────────  ─────────
   0     1 Postgres on c5.2xlarge           $300      1               0
   1     + PgBouncer                        $350      2               1 day
   2     + 2 read replicas                  $1,200    7               1 week
   3     Scale up to r6i.16xlarge           $5,000    7               1 day
   4     Native partitioning                $5,200    9               2 weeks
   5     Sharded (Vitess, 4 shards)         $20,000   30+             6 months
   6     CQRS (PG + ES + Redis + ClickHouse) $35,000  50+             6 months
   7     Multi-region active/passive        $60,000   60+             3 months
   8     Multi-region active/active         $150,000  100+            12 months


THE PRINCIPAL'S COST RULE:

  Every rung adds engineering tax that compounds. By Rung 5 you need
  a dedicated database team. By Rung 7 you need a dedicated reliability
  team. By Rung 8 you are operating at FAANG scale and will hire 20
  engineers just to keep it standing.

  The cheapest scaling is the scaling you DON'T do.
  90% of "we need to shard" is actually "we never tuned our queries."
```

---

## Part 3: The Scaling Ladder (the spine of this module)

```plaintext
                  ┌────────────────────────────────────┐
                  │  TIER DATA (Rung 8)                │
                  │  Hot/warm/cold across PG/S3/Glacier│
                  └────────────────┬───────────────────┘
                                   │
                  ┌────────────────┴───────────────────┐
                  │  GEO-DISTRIBUTED (Rung 7)          │
                  │  Active/passive or active/active   │
                  └────────────────┬───────────────────┘
                                   │
                  ┌────────────────┴───────────────────┐
                  │  CQRS + READ MODELS (Rung 6)       │
                  │  PG + ES + Redis + ClickHouse + …  │
                  └────────────────┬───────────────────┘
                                   │
                  ┌────────────────┴───────────────────┐
                  │  HORIZONTAL SHARDING (Rung 5)      │
                  │  Vitess / Citus / CockroachDB      │
                  └────────────────┬───────────────────┘
                                   │
                  ┌────────────────┴───────────────────┐
                  │  NATIVE PARTITIONING (Rung 4)      │
                  │  PARTITION BY RANGE/LIST/HASH      │
                  └────────────────┬───────────────────┘
                                   │
                  ┌────────────────┴───────────────────┐
                  │  VERTICAL SCALE-UP (Rung 3)        │
                  │  Bigger box. The forgotten rung.   │
                  └────────────────┬───────────────────┘
                                   │
                  ┌────────────────┴───────────────────┐
                  │  READ REPLICAS (Rung 2)            │
                  │  Streaming replication, routing    │
                  └────────────────┬───────────────────┘
                                   │
                  ┌────────────────┴───────────────────┐
                  │  CONNECTION POOLING (Rung 1)       │
                  │  PgBouncer / RDS Proxy             │
                  └────────────────┬───────────────────┘
                                   │
                  ┌────────────────┴───────────────────┐
                  │  SINGLE DATABASE (Rung 0)          │
                  │  Tune queries, add indexes         │
                  └────────────────────────────────────┘

THE FIRST LAW OF SCALING: do not skip rungs. Each rung's failure
modes are the prerequisite for understanding the next rung's failures.
```

The rest of this module walks each rung, with the depth determined by how often each rung's failure modes appear in real production.

---

## Part 4: Rung 0 — Tuning Before Scaling

```plaintext
THE QUERIES THAT KILL DATABASES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before you add a single replica, run these four queries against
your primary. They identify 80% of "we need to scale" situations
that don't actually need scaling.


  1. WHAT IS RUNNING RIGHT NOW?
  ─────────────────────────────

    SELECT 
      pid, 
      now() - query_start AS duration,
      state, 
      wait_event_type, 
      wait_event,
      LEFT(query, 100) AS query
    FROM pg_stat_activity
    WHERE state != 'idle'
    ORDER BY duration DESC NULLS LAST;

    What you're looking for:
     - Long-running queries (>1s) that should be fast.
     - Queries stuck on Lock wait events.
     - "idle in transaction" sessions (uncommitted txns
       holding locks and bloating WAL).


  2. WHICH TABLES NEED INDEXES OR VACUUM?
  ───────────────────────────────────────

    SELECT 
      schemaname,
      relname,
      seq_scan,
      seq_tup_read,
      idx_scan,
      n_live_tup,
      n_dead_tup,
      ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup, 0), 1) AS pct_dead
    FROM pg_stat_user_tables
    ORDER BY seq_tup_read DESC
    LIMIT 20;

    Diagnostics:
     - High seq_tup_read with low idx_scan = missing index.
     - pct_dead > 20% = autovacuum behind, tables bloated.
     - Big seq_scan on big tables = your CPU is here.


  3. WHICH QUERIES BURN THE MOST TIME?
  ────────────────────────────────────

    -- Requires pg_stat_statements extension
    SELECT 
      LEFT(query, 100) AS query,
      calls,
      total_exec_time,
      mean_exec_time,
      stddev_exec_time,
      rows
    FROM pg_stat_statements
    ORDER BY total_exec_time DESC
    LIMIT 20;

    The 80/20 rule applies. Usually 5 queries account for
    70% of database time. Optimize those, you bought 6 months.


  4. WHAT IS BLOCKING WHAT?
  ─────────────────────────

    SELECT 
      blocked.pid AS blocked_pid,
      blocked.query AS blocked_query,
      blocking.pid AS blocking_pid,
      blocking.query AS blocking_query
    FROM pg_stat_activity blocked
    JOIN pg_stat_activity blocking 
      ON blocking.pid = ANY(pg_blocking_pids(blocked.pid))
    WHERE blocked.wait_event_type = 'Lock';

    Lock waits are invisible to CPU monitoring. The DB looks
    idle. Every query is slow. This query reveals why.


THE TUNING CHECKLIST (run in order, stop when fixed):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [ ] Run EXPLAIN (ANALYZE, BUFFERS) on the slow query.
       Look for: Seq Scan on big tables, nested loops with
       high row counts, sorts that don't fit in work_mem.

  [ ] Add the missing index. Test impact.
       CREATE INDEX CONCURRENTLY (always CONCURRENTLY in prod).

  [ ] Check pg_stat_statements for top 5 queries by total_time.

  [ ] VACUUM ANALYZE on bloated tables. Tune autovacuum if needed.

  [ ] Increase work_mem if sorts are spilling to disk
       (look for "Sort Method: external merge Disk").

  [ ] Increase shared_buffers if cache hit ratio < 99%
       (target: shared_buffers ≈ 25% of RAM).

  [ ] Kill "idle in transaction" sessions older than 5 minutes
       (idle_in_transaction_session_timeout = '5min').

  [ ] Only after all the above: consider Rung 1.


THE 10× RULE: a missing index can give you 10-1000× improvement.
A read replica gives you 2-3× improvement. Always tune first.
```

---

## Part 5: Rung 1 — Connection Pooling (PgBouncer Deep Dive)

This is the most-skipped, highest-leverage rung. A 60-line config change can take you from "we need to scale" to "we have plenty of headroom."

### 5.1 — Why Postgres Connections Are Expensive

```plaintext
WHAT HAPPENS WHEN YOUR APP OPENS A POSTGRES CONNECTION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. TCP handshake (1 RTT)
  2. TLS handshake (2 RTTs unless 0-RTT resumption)
  3. SCRAM auth challenge/response (1 RTT)
  4. Postmaster receives "new connection" → fork() a backend
     process (NOT a thread — a full Unix process).
  5. Backend process allocates ~10 MB RSS minimum
     (private syscache, relcache, plan cache, work_mem buffers).
  6. SET application_name, search_path, role, timezone, etc.

  Total: ~5-50ms wall time, ~10MB RAM permanently consumed.

  Now multiply by 4000 microservice instances each opening
  a 20-connection pool: 80,000 backend processes, 800GB RAM.
  Postgres dies at ~5,000 connections. You died at 250.


WHAT POOLING ACTUALLY DOES:
━━━━━━━━━━━━━━━━━━━━━━━━━━

   App pool (4000 conns)              Backend pool (200 conns)
   ┌─────────────────────┐            ┌──────────────────────┐
   │ svc-a × 200 conns   │            │                      │
   │ svc-b × 200 conns   │            │   PgBouncer          │
   │ svc-c × 200 conns   │ ───────►   │   (multiplexer)      │ ───►  Postgres
   │ ...                 │            │                      │       (200 backends)
   │ svc-z × 200 conns   │            │                      │
   └─────────────────────┘            └──────────────────────┘

  Apps see "20 connections per service," each cheap.
  Postgres sees "200 connections," each used efficiently.
  Effective ratio: 20:1 to 100:1.
```

### 5.2 — The Three Pool Modes (the choice that breaks apps)

```plaintext
┌───────────────────────────────────────────────────────────────┐
│  MODE 1: SESSION POOLING (pool_mode = session)                │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│  Backend connection assigned to client until client           │
│  disconnects. Pooling ratio ≈ 1:1.                            │
│                                                               │
│  Compatibility: EVERYTHING WORKS.                             │
│   ✓ Server-side prepared statements                           │
│   ✓ Session-scoped temp tables                                │
│   ✓ LISTEN/NOTIFY                                             │
│   ✓ Session advisory locks                                    │
│   ✓ SET (any kind)                                            │
│                                                               │
│  Use when: legacy apps, ORMs that depend on session state.    │
│  Don't use when: you want pooling to actually do something.   │
├───────────────────────────────────────────────────────────────┤
│  MODE 2: TRANSACTION POOLING (pool_mode = transaction)        │
│            ◄──────── DEFAULT FOR 90% OF DEPLOYMENTS           │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│  Backend connection released to the pool after each           │
│  transaction. Pooling ratio: 20:1 to 100:1.                   │
│                                                               │
│  THINGS THAT SILENTLY BREAK (memorize):                       │
│                                                               │
│   ✗ Server-side PREPARE/EXECUTE                               │
│      The prepared statement lives on a backend you may        │
│      not get next query. Symptom: "prepared statement         │
│      'pgbouncer_1' does not exist" intermittently.            │
│      Fix: use protocol-level prepared statements.             │
│      In drivers:                                              │
│        - psycopg3 (Python): default uses protocol prepare     │
│        - pgx (Go): QueryExecModeCacheStatement (default)      │
│        - pgjdbc (Java): prepareThreshold=0 to disable, OR     │
│          use PgBouncer 1.21+ which natively supports them.    │
│                                                               │
│   ✗ SET (without LOCAL)                                       │
│      "SET search_path = 'tenant_a'" leaks. The next client    │
│      using that backend connection sees tenant_a's schema.    │
│      DATA LEAK across tenants. This has caused breaches.      │
│      Fix: SET LOCAL inside a transaction, OR set via the      │
│      connection string, OR set as ROLE default.               │
│                                                               │
│   ✗ Session-scoped temp tables                                │
│      "CREATE TEMP TABLE foo" — pg_temp.foo persists on        │
│      the backend after your txn commits. Next client          │
│      sees ghost table.                                        │
│      Fix: ON COMMIT DROP, or use CTEs instead.                │
│                                                               │
│   ✗ LISTEN/NOTIFY                                             │
│      LISTEN registers on a backend. Notifications arrive      │
│      whenever, possibly to a backend some other client owns.  │
│      Fix: dedicated session-mode pool for LISTEN clients.     │
│                                                               │
│   ✗ Session advisory locks                                    │
│      pg_advisory_lock(N) holds for the session. With          │
│      transaction pooling the "session" ends at txn commit.    │
│      Fix: pg_advisory_xact_lock(N).                           │
│                                                               │
│   ✗ Cursors WITH HOLD                                         │
│      Survive across transactions on a session, not on you.    │
│      Fix: don't use them, or use session pooling.             │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│  MODE 3: STATEMENT POOLING (pool_mode = statement)            │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│  Backend released after every statement. BEGIN errors out.    │
│  Multi-statement transactions banned.                         │
│                                                               │
│  Pooling ratio: 200:1+. Maximum density.                      │
│                                                               │
│  Use when: serverless functions doing autocommit-only,        │
│  read-heavy analytics, AWS Aurora Data API style.             │
│  Almost never the right answer for OLTP.                      │
└───────────────────────────────────────────────────────────────┘
```

### 5.3 — The Tuning Numbers

```plaintext
PGBOUNCER CONFIG (annotated):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  pool_mode = transaction              # default for web apps

  # Per (user, db) pair backend pool size.
  # Rule of thumb: 2-4 × CPU cores on Postgres.
  # 16-core Postgres → default_pool_size = 25-50.
  default_pool_size = 25

  # App-side cap. How many clients can simultaneously hold a
  # PgBouncer slot (whether or not they have a backend).
  max_client_conn = 5000

  # Reserved for emergencies. Tapped when pool exhausted
  # for reserve_pool_timeout seconds.
  reserve_pool_size = 5
  reserve_pool_timeout = 3.0

  # Hard cap to protect Postgres from PgBouncer misconfig.
  max_db_connections = 200

  # Idle backends are closed after N seconds.
  server_idle_timeout = 600

  # Max time a client waits in queue for a backend.
  query_wait_timeout = 120

  # Validate connection health before handing to client.
  # 'lazy' = check on first use; 'aggressive' = check periodically.
  server_check_query = SELECT 1
  server_check_delay = 30


THE MATH THAT MUST BALANCE:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  Postgres max_connections   ≥
      Σ default_pool_size (over all pools)
    + reserve_pool_size
    + superuser_reserved_connections (default 3)
    + admin_headroom (10)

  Get this wrong → Postgres rejects new conns →
  PgBouncer queues clients → query_wait_timeout →
  cascading 5xx errors across the fleet.


THE METRICS TO MONITOR (on PgBouncer admin port):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  $ psql -h pgbouncer -p 6432 -U pgbouncer pgbouncer

  pgbouncer=# SHOW POOLS;
   database │ user │ cl_active │ cl_waiting │ sv_active │ sv_idle
   ─────────┼──────┼───────────┼────────────┼───────────┼─────────
   prod     │ app  │ 1842      │ 47         │ 25        │ 0
                                  ▲                       ▲
                                  │                       │
                             ◄ ALARM            ◄ pool exhausted

  cl_waiting > 0 sustained = pool too small or queries too slow.
  sv_idle = 0 sustained    = pool maxed, scale Postgres or pool.


CROSS-MODULE CONNECTION (Read-Your-Writes via LSN, see Part 8):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  In transaction pooling, the connection you used to write
  is NOT the connection you use to read 3ms later. So you
  CANNOT do:

    BEGIN;
    INSERT INTO orders ...;
    COMMIT;
    -- different connection now!
    SELECT pg_current_wal_lsn();   ← LIES. Wrong LSN.

  Capture LSN INSIDE the writing transaction:

    BEGIN;
    INSERT INTO orders ...;
    SELECT pg_current_wal_insert_lsn();   ← CORRECT.
    COMMIT;

  Then propagate that LSN as application state to the read.
```

### 5.4 — Why RDS Proxy Is Different

```plaintext
RDS PROXY VS PGBOUNCER:
━━━━━━━━━━━━━━━━━━━━━━

  RDS Proxy is AWS's managed connection pooler. Differences:

   - Multi-AZ HA built-in. PgBouncer requires you to run it.
   - IAM auth integration (no DB password in app).
   - Automatic failover orchestration with RDS.
   - Cost: ~$0.015/vCPU-hour ≈ $11/month per vCPU.
   - Pinning: certain operations "pin" a client to a backend
     until disconnect, defeating pooling. The pinning rules
     are documented and surprisingly aggressive (any SET,
     any prepared statement in some drivers, any temp table).

  Choose PgBouncer when:
   - Running outside AWS or want vendor neutrality.
   - You want fine-grained control over pool modes.
   - Your scale demands 10:1+ ratios that RDS Proxy's
     pinning rules prevent.

  Choose RDS Proxy when:
   - You want zero ops, are AWS-native, and your traffic
     is light enough that pinning doesn't hurt.
   - You want IAM auth and failover orchestration.
```

---

## Part 6: Rung 2 — Read Replicas (Streaming Replication Internals)

### 6.1 — How PostgreSQL Streaming Replication Actually Works

```plaintext
THE WAL PIPELINE:
━━━━━━━━━━━━━━━━

  Primary:
    Client → INSERT → backend writes to:
                       1. Shared buffers (RAM — the table)
                       2. WAL buffer (RAM — the log)
                          │
                          ▼ at COMMIT (or wal_writer flush)
                       3. WAL file on disk (fsync)
                          │
                          ▼ async, by walsender process
                       4. Streamed to replicas over TCP

  Replica:
    walreceiver → writes WAL to local disk → fsyncs
                  ▼
    startup process → replays WAL records into shared buffers
                       and table files. Visible to readers.


THE FOUR REPLICATION POSITIONS (memorize):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  On the PRIMARY, for each replica:

   sent_lsn       : how far we've SENT to the replica
   write_lsn      : how far the replica has WRITTEN to memory
   flush_lsn      : how far the replica has FSYNCED to disk
   replay_lsn     : how far the replica has APPLIED to tables

  Order: sent ≥ write ≥ flush ≥ replay
                                  ▲
                            this is what readers see


  ┌──────────────┬────────────────────────────────────┐
  │ Lag metric   │ Definition                         │
  ├──────────────┼────────────────────────────────────┤
  │ write_lag    │ time(sent) − time(write_lsn ack)   │
  │ flush_lag    │ time(sent) − time(flush_lsn ack)   │
  │ replay_lag   │ time(sent) − time(replay_lsn ack)  │
  └──────────────┴────────────────────────────────────┘

  THE LAG THAT MATTERS for read-after-write is replay_lag.
  Most monitoring shows you flush_lag because it's smaller
  and looks better. Demand replay_lag.


THE QUERY TO RUN ON PRIMARY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  SELECT 
    application_name, 
    client_addr, 
    state,                  -- streaming | catchup | startup | backup
    sync_state,             -- async | potential | sync | quorum
    pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn)   AS sent_lag_b,
    pg_wal_lsn_diff(pg_current_wal_lsn(), write_lsn)  AS write_lag_b,
    pg_wal_lsn_diff(pg_current_wal_lsn(), flush_lsn)  AS flush_lag_b,
    pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_b,
    write_lag, 
    flush_lag, 
    replay_lag
  FROM pg_stat_replication;
```

### 6.2 — The Four Sync Modes (and the silent degradation)

```plaintext
synchronous_commit settings:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

   off            primary acks before fsync. RPO ~5s on crash.
                  Use NEVER in prod for important data.

   local          (DEFAULT) fsync to primary's WAL.
                  RPO=0 if primary survives. RPO>0 on primary loss.

   remote_write   wait for replica to RECEIVE WAL into memory.
                  RPO≈0, but replica memory loss = data loss.

   remote_apply   wait for replica to REPLAY WAL.
                  Strongest. RPO=0 even on primary loss.
                  Reads on replica see committed writes immediately.


synchronous_standby_names — the topology:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   FIRST 1 (r1, r2)         wait for r1; if r1 down, wait for r2
   FIRST 2 (r1, r2, r3)     wait for any 2 of the listed
   ANY 1 (r1, r2)           wait for any 1 (quorum)
   ANY 2 (r1, r2, r3)       wait for any 2 of 3 (quorum)


THE SILENT DEGRADATION (the Week 4 T1 trap):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Config: synchronous_standby_names = 'FIRST 1 (r1, r2)'

  Timeline:
    14:00  r1 + r2 healthy, writes wait for fastest ack (~2ms). 
    14:30  r1 dies. Writes wait for r2. Latency unchanged.
    14:32  r2 dies too. WRITES NOW HANG indefinitely.

  Symptoms to the app:
   - DB accepts new connections (looks healthy).
   - Every transaction blocks at COMMIT.
   - Connection pool fills.
   - App reports "DB connection timeout" — wrong diagnosis.

  pg_stat_activity shows:
   wait_event_type = 'IPC', wait_event = 'SyncRep'
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   That string is the smoking gun. Memorize it.


THE THREE BAD CHOICES (pick one):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  A. Keep sync, accept availability hit.
     When all sync replicas fail → primary halts writes.
     Strong durability, weaker availability.
     For: financial ledgers, regulated systems.

  B. Auto-degrade to async on replica loss.
     Patroni / pg_auto_failover / Stolon can flip
     synchronous_standby_names dynamically when no candidates
     remain. Availability preserved; durability silently weakens.
     ⚠ THE BUG: this transition is the most underloggged
     event in Postgres ops. You think you have RPO=0.
     You have RPO=∞ for the next 47 minutes.

  C. Run quorum across 3+ replicas: ANY 2 of 3.
     Survives one replica loss with sync still active.
     Costs 3× replica infra.

  Principal's answer:
   - Regulated/financial: C (quorum), with explicit alarm
     on sync_state transitions on every standby.
   - Standard web app: B (auto-degrade), with the same alarm.
   - Never: A without alarm. Never: silent transition.


THE METRIC YOU MUST EXPOSE TO MONITORING:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  -- sync_state per replica
  SELECT application_name, sync_state FROM pg_stat_replication;

  Alert when sync_state for any expected-sync standby
  flips to 'async' or 'potential'. 30-second detection.
  Otherwise you find out at the next failover when 47
  minutes of "lost" data is actually missing.
```

### 6.3 — Routing Reads to Replicas (the part that breaks apps)

```plaintext
THE FOUR ROUTING STRATEGIES (in increasing sophistication):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  STRATEGY 1: ALL READS TO REPLICAS
  ─────────────────────────────────
    GET /orders       → replica
    POST /orders      → primary
    GET /orders/123   → replica  ← BUG: just-created order

    Failure: read-after-write breaks. Customer creates order,
    refresh page, "order not found." Returns 47 minutes later.

    Use only for: heavily cached pages where lag doesn't matter.


  STRATEGY 2: SESSION STICKINESS (read-after-write window)
  ────────────────────────────────────────────────────────
    On write: set cookie "primary_until = now() + 10s"
    On read with cookie active → primary. Else → replica.

    Failure: cross-device staleness. Customer writes on
    phone, opens laptop. Different cookie. Sees stale data.

    Use for: in-session UX. Not durable.


  STRATEGY 3: LSN TOKEN (causal consistency)
  ──────────────────────────────────────────
    On write inside the transaction:
      INSERT INTO orders ... RETURNING id, pg_current_wal_insert_lsn();
    Return LSN to client. Client sends LSN with next read.
    Read router checks replica:
      SELECT pg_last_wal_replay_lsn() >= '<token>';
    If true → replica serves. If false → wait or fall back to primary.

    This is what Vitess, ProxySQL, and modern PG proxies do.

    Failure modes:
     - LSN captured outside the writing txn → wrong LSN.
     - Token forwarded across regions → replica there may
       lag indefinitely; need a timeout policy.

    Use for: multi-tab, multi-device, durable causal reads.


  STRATEGY 4: DOMAIN-DRIVEN ROUTING
  ──────────────────────────────────
    Different read SLAs per business operation:

      Account balance check    → primary    (correctness)
      Order list page          → primary    (read-after-write)
      Search results           → replica    (eventually OK)
      Recommendations          → replica    (cache OK)
      Reporting dashboard      → analytics replica (10s lag fine)
      Historical reports       → cold replica or warehouse

    Codify this in a router library, not service-by-service.


THE HEALTH-AWARE ROUTER:
━━━━━━━━━━━━━━━━━━━━━━━

  For each replica, every 5s:
   1. Measure replay_lag.
   2. lag < 1s     → eligible for all reads.
      lag 1-5s    → eligible for non-critical reads only.
      lag 5-30s   → eligible for eventual-only reads.
      lag > 30s   → EVICT from rotation, alert ops.

  The router publishes a routing table; SDK consumes it.
  Stale routing tables = stampede onto primary or onto a
  bad replica. Refresh aggressively, fail open to primary.
```

---

## Part 7: Replication Slot Bloat — The Silent Killer

```plaintext
WHAT A REPLICATION SLOT IS:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  A persistent server-side bookmark on the PRIMARY that says
  "do not delete WAL until consumer X has read up to position Y."

  Used by:
   - Physical streaming replicas (optional but recommended).
   - Logical replication (REQUIRED).
   - CDC tools: Debezium, Wal2json, AWS DMS, Airbyte, Striim.

  Why it exists:
   Without slots, primary recycles WAL based on
   wal_keep_size / max_wal_size. If a consumer falls behind
   beyond that window, it can never catch up — primary
   discarded the WAL it needs.

  The slot prevents that by pinning WAL retention.
  And pinning is the killer.


THE FAILURE MODE:
━━━━━━━━━━━━━━━━

  Consumer dies, network partitions, or someone forgot to
  drop a test slot. Slot stays. Primary's pg_wal grows.
  And grows. Until disk fills. Until PRIMARY GOES DOWN.

  Real outages caused by this:
   - GitHub October 2018 (compounding factor)
   - Multiple Atlassian incidents
   - Countless smaller incidents (most never publicized)

  The cruelty of this failure: nothing in your normal
  monitoring (CPU, traffic, latency) shows it. The disk
  graph creeps up over hours. Then page at 3am.


THE DETECTION QUERY (run hourly, alarm on results):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  SELECT 
    slot_name,
    plugin,                                   -- pgoutput, wal2json, etc
    slot_type,                                -- physical | logical
    active,                                   -- consumer connected NOW?
    active_pid,
    pg_size_pretty(
      pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)
    ) AS retained_wal,
    pg_size_pretty(
      pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)
    ) AS pending_to_consumer
  FROM pg_replication_slots
  ORDER BY pg_wal_lsn_diff(
    pg_current_wal_lsn(), restart_lsn
  ) DESC;


  ALARM THRESHOLDS:
   retained_wal > 10 GB                  → warn
   retained_wal > 50 GB                  → page
   retained_wal > 70% of pg_wal volume   → fire the world
   active = false for > 1 hour           → page (slot abandoned)


THE PREVENTION (Postgres 13+):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  postgresql.conf:
    max_slot_wal_keep_size = 100GB

  Postgres will INVALIDATE the slot if it would exceed this.
  Better to lose the consumer than lose the primary.

  Trade-off:
   No cap     → consumer can always catch up; primary can die.
   Cap set    → primary safe; stale consumer must re-snapshot
                from scratch (hours/days for large databases).

  In 95% of cases: SET THE CAP.
  Re-snapshot is recoverable. Disk-full is a deep-recovery event.


RECOVERY (when it happens):
━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Identify stale slot:
       SELECT slot_name, active, restart_lsn
       FROM pg_replication_slots WHERE active = false;

  2. If consumer is gone forever:
       SELECT pg_drop_replication_slot('zombie_slot');
       WAL freed at next checkpoint.

  3. If consumer should exist but is broken:
       Fix consumer FIRST. It will advance the slot naturally.
       Dropping the slot loses consumer's progress = re-snapshot.

  4. EMERGENCY: if disk fills in 10 minutes, no fix available:
       DROP THE SLOT. Survive now. Re-snapshot tomorrow.


OPERATIONAL DISCIPLINE:
━━━━━━━━━━━━━━━━━━━━━━

  - Every slot has a documented owner in a registry.
  - Every slot has max_slot_wal_keep_size cap.
  - Every slot is alarmed for inactivity AND retention.
  - Test/dev slots auto-cleaned by daily cron (regex: ^test_).
  - Pre-deploy hook: "is your CDC consumer ready?" check.
```

---

## Part 8: Read-Your-Writes Patterns (the consistency lever)

```plaintext
THE PROBLEM:
━━━━━━━━━━━

  Customer updates profile picture (write to primary).
  Frontend redirects to /profile (read).
  Read goes to replica that hasn't replayed yet.
  Customer sees old picture.
  Customer thinks save failed.
  Customer hits save again. And again. Stampede.


THE THREE SOLUTIONS (from weakest to strongest):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. TIME-WINDOW STICKINESS
  ─────────────────────────
    Cookie/header: "primary_until = now + 10s"
    All reads in window go to primary.
    Pros: simple, no LSN plumbing.
    Cons: arbitrary window, doesn't span devices, false
          positives (10s of primary load for a no-op).
    Use when: low-stakes UX, single-device session.


  2. SESSION-PINNED ROUTING
  ─────────────────────────
    All reads in this session → same replica (or primary).
    Pros: simple to reason about.
    Cons: replica may lag; replica may die mid-session;
          no guarantee replica has YOUR write yet.
    Use when: rare, mostly inside read-only analytical sessions.


  3. LSN CAUSAL TOKEN (the right answer)
  ──────────────────────────────────────
    On write transaction:
      BEGIN;
      INSERT INTO orders ...;
      SELECT pg_current_wal_insert_lsn();    -- captured
      COMMIT;

    Return LSN to client (HTTP header, cookie, JWT claim).

    On subsequent read:
      Client sends LSN.
      Router queries replica: SELECT pg_last_wal_replay_lsn();
      If replica_lsn >= client_lsn → serve from replica.
      Else → wait briefly, or fall back to primary.

    Pros: rigorous causal consistency; survives across devices
          if LSN is propagated (e.g., in JWT after login).
    Cons: requires LSN plumbing through API; stale tokens
          on read replicas in remote regions need timeout.
    Use when: any production app with read replicas and
              user-visible writes.


THE MISTAKE EVERYONE MAKES (TRANSACTION POOLING + LSN):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  WRONG:
    BEGIN;
    INSERT INTO orders ...;
    COMMIT;
    -- different connection now (transaction pooling)
    SELECT pg_current_wal_lsn();   ← cluster-wide LSN, may
                                     have advanced past your
                                     write OR may belong to
                                     someone else's commit.

  RIGHT:
    BEGIN;
    INSERT INTO orders ... RETURNING id;
    SELECT pg_current_wal_insert_lsn();   ← inside same txn
    COMMIT;

  Or use the RETURNING clause to embed the LSN with the row:
    INSERT INTO orders (...) VALUES (...)
    RETURNING id, pg_current_wal_insert_lsn() AS lsn;
```

---

## Part 9: Rung 3 — Vertical Scale (the forgotten rung)

```plaintext
THE PRINCIPLE:
━━━━━━━━━━━━━

  Modern hardware is absurdly powerful. An r6i.32xlarge
  has 128 vCPU, 1 TB RAM, 50 Gbps network, and (with NVMe
  instance store + RAID-10) > 1M IOPS.

  A well-tuned Postgres on that machine handles:
   - 100,000+ writes/sec sustained
   - 500,000+ reads/sec from cache
   - 10-50 TB datasets without partitioning

  Cost: $20K/month. Operating sharded Postgres at the
  same throughput costs >$100K/month + 2-3 FTEs.

  PRINCIPAL'S RULE: vertical scale until it physically
  cannot work, THEN consider horizontal.


THE SATURATION CHECKLIST (you have NOT exhausted vertical scale until ALL are true):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [ ] You are on the largest instance class your cloud provider
      sells for OLTP (e.g., r6i.32xlarge, db.r6i.32xlarge).

  [ ] At least one resource is pinned:
        - CPU > 80% sustained
        - IOPS at provisioned ceiling
        - Memory bandwidth saturated (perf stat)
        - Network bandwidth saturated
        - WAL fsync latency > 5ms (disk-bound)

  [ ] You ran pg_stat_statements; top 10 queries are tuned.

  [ ] You evaluated native partitioning (Rung 4) and confirmed
      it doesn't help your access pattern.

  [ ] You added all useful indexes; bloated indexes rebuilt;
      autovacuum tuned.

  [ ] Your shared_buffers is 25% of RAM, work_mem is sized,
      effective_cache_size matches actual cache.

  If any are NO → do that first. Sharding can wait.


THE PG TUNING KNOBS THAT MATTER (annotated):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  shared_buffers          25% of RAM (don't go higher; OS cache
                          is more efficient beyond that).
  effective_cache_size    50-75% of RAM (planner hint, not allocation).
  work_mem                Per-sort/hash. Start 16MB; raise carefully —
                          this is multiplied by concurrent operations.
  maintenance_work_mem    1GB+ for big VACUUMs and CREATE INDEX.
  wal_compression         on (saves WAL bandwidth at modest CPU cost).
  max_wal_size            Larger = fewer checkpoints = smoother. 16-64GB.
  checkpoint_timeout      15-30 min for OLTP.
  checkpoint_completion_target  0.9 (spread checkpoint I/O).
  random_page_cost        1.1 on NVMe (default 4.0 assumes spinning rust).
  effective_io_concurrency  256+ on NVMe.
  max_worker_processes    Match CPU count.
  max_parallel_workers    Match CPU count.
  max_parallel_workers_per_gather  4-8 for OLTP, more for analytics.
  jit                     off for OLTP unless queries are CPU-bound on
                          complex expressions. Default on can hurt.
```

---

## Part 10: Rung 4 — Native Partitioning

```plaintext
THE PROBLEM PARTITIONING SOLVES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Your "events" table is 800 GB. Indexes are 200 GB.
  Symptoms:
   - INDEX SCANs are fast on hot rows but cache-cold pages
     take 5ms each (index doesn't fit in shared_buffers).
   - VACUUM of the whole table takes 6 hours and locks
     autovacuum workers from doing useful work elsewhere.
   - DROPping old rows (DELETE WHERE created_at < ...) is
     impossibly expensive — writes a tombstone per row,
     bloats indexes, kills replication.
   - CREATE INDEX takes 14 hours and blocks DDL.

  PARTITIONING splits the table into smaller child tables
  by a key. Each child has its own indexes, its own
  vacuum, and can be DROPped in O(1).


THE THREE PARTITION TYPES:
━━━━━━━━━━━━━━━━━━━━━━━━━

  RANGE  — for time-series and ordered keys.
           Each partition holds rows whose key falls in a range.
           Most common.

           CREATE TABLE events (
             id BIGSERIAL,
             user_id BIGINT,
             event_type TEXT,
             created_at TIMESTAMPTZ NOT NULL,
             payload JSONB
           ) PARTITION BY RANGE (created_at);

           CREATE TABLE events_2026_05
             PARTITION OF events
             FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

  LIST   — for discrete category keys (region, tenant, etc).

           CREATE TABLE customers (
             id BIGSERIAL, region TEXT, ...
           ) PARTITION BY LIST (region);

           CREATE TABLE customers_us PARTITION OF customers
             FOR VALUES IN ('us-east', 'us-west');

  HASH   — for spreading writes evenly when no natural
           range/list exists. Common for high-write user_id.

           CREATE TABLE messages (
             id BIGSERIAL, user_id BIGINT, body TEXT
           ) PARTITION BY HASH (user_id);

           CREATE TABLE messages_p0 PARTITION OF messages
             FOR VALUES WITH (MODULUS 16, REMAINDER 0);
           -- … through messages_p15


WHAT YOU GAIN:
━━━━━━━━━━━━━

  ✓ Partition pruning: queries with WHERE on partition key
    skip irrelevant partitions at plan time. EXPLAIN shows
    only the relevant partitions scanned.

  ✓ Drop old data in O(1):
       DROP TABLE events_2024_01;
    No DELETE storm, no autovacuum aftermath.

  ✓ Per-partition indexes are smaller, cache better.

  ✓ Per-partition VACUUM is parallelizable and bounded.

  ✓ Per-partition tablespace: hot partitions on NVMe, cold
    partitions on slower/cheaper storage.


WHAT YOU LOSE (the gotchas):
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ✗ Queries without partition key in WHERE scan ALL partitions.
    Plan check is critical.

  ✗ UNIQUE indexes must INCLUDE the partition key.
    If your unique constraint is on email, but partition key
    is region, you cannot guarantee global uniqueness via
    a unique index — you must enforce in app or via
    cross-partition trigger.

  ✗ Foreign keys: pre-PG12 not supported pointing TO a
    partitioned table. PG12+ supports it but with caveats.

  ✗ ATTACH PARTITION takes a brief lock. PG14+ greatly
    reduced this. Plan for it.

  ✗ Many partitions = planner overhead. PG13+ handles
    thousands of partitions well. Earlier versions degrade
    past ~100.


PG_PARTMAN: the autopilot.
━━━━━━━━━━━━━━━━━━━━━━━━━

  pg_partman extension automates:
   - Creating future partitions ahead of time (you don't
     want INSERTs failing because next month's partition
     doesn't exist yet).
   - Detaching old partitions on a schedule.
   - Optionally exporting old partitions to slower storage.

  In production, every range-partitioned table should be
  managed by pg_partman or equivalent. Manual partition
  management is a 3am bug waiting to happen.
```

---

## Part 11: Rung 5 — Horizontal Sharding

The 1-way door. Read this twice before walking through it.

### 11.1 — What Sharding Is and Why It Hurts

```plaintext
THE PRINCIPLE:
━━━━━━━━━━━━━

  Data physically split across N independent databases.
  Each shard is a complete Postgres instance, owning a
  subset of the data. A "router" or "coordinator" sits
  in front and dispatches queries.

  Approaches:
   A. App-level sharding: your app code knows shards.
   B. Vitess (MySQL): YouTube/Slack/GitHub/HubSpot.
   C. Citus (Postgres): Microsoft-owned distributed PG.
   D. Native distributed SQL: CockroachDB, Spanner, Yugabyte.


WHY IT'S A 1-WAY DOOR:
━━━━━━━━━━━━━━━━━━━━━

  Once you shard:
   - Cross-shard JOINs become expensive scatter-gather.
   - Cross-shard transactions need 2PC or sagas (Part 12).
   - Schema migrations must apply to N shards atomically.
   - Re-sharding (changing the shard key) is a 3-12 month
     project requiring shadow-copying every row.
   - The "we'll un-shard later" plan has never worked at
     any company I've seen. Estimates never include the
     cost of preserving the new feature surface.


THE THREE SHARDING ARCHITECTURES (annotated):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌─────────────────────────────────────────────────────┐
  │  APP-LEVEL SHARDING                                 │
  │                                                     │
  │  Your app:                                          │
  │    shard_id = hash(user_id) % 16                    │
  │    conn = pool[shard_id]                            │
  │                                                     │
  │  ✓ No new infra component.                          │
  │  ✓ Full control over routing.                       │
  │  ✗ You write all the cross-shard logic.             │
  │  ✗ Re-sharding is YOUR problem.                     │
  │  ✗ Every language/SDK reimplements the router.      │
  └─────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────┐
  │  VITESS (MySQL) — proxy-based                       │
  │                                                     │
  │   Apps → VTGate (proxy, speaks MySQL protocol)      │
  │           ▼                                         │
  │         topology service (etcd)                     │
  │           ▼                                         │
  │         VTTablet (one per MySQL shard)              │
  │           ▼                                         │
  │         MySQL                                       │
  │                                                     │
  │  ✓ Apps speak vanilla MySQL — zero code change.     │
  │  ✓ VTGate handles cross-shard scatter-gather.       │
  │  ✓ Online resharding (split a shard live).          │
  │  ✓ VReplication: continuous logical replication     │
  │    between shards for migrations.                   │
  │  ✗ MySQL-only.                                      │
  │  ✗ Operational complexity ≈ Kubernetes-level.       │
  │  ✗ Some SQL features unsupported (full GROUP BY     │
  │    across shards is tricky, etc).                   │
  │                                                     │
  │  Real users: YouTube (billions of rows), Slack,     │
  │  GitHub, HubSpot, Square.                           │
  └─────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────┐
  │  CITUS (Postgres) — coordinator-based               │
  │                                                     │
  │   Apps → Citus coordinator (looks like Postgres)    │
  │           ▼                                         │
  │         Citus workers (Postgres shards)             │
  │                                                     │
  │  ✓ SELECT create_distributed_table('orders',        │
  │       'tenant_id') — one command, sharded.          │
  │  ✓ Reference tables: small lookup tables replicated │
  │    to every worker for joins.                       │
  │  ✓ Co-location: tables sharded by the same key      │
  │    can be JOINed locally on each worker.            │
  │  ✓ Owned by Microsoft, integrated into Azure.       │
  │  ✗ Coordinator can become bottleneck for writes;    │
  │    Citus 11+ allows querying any worker as          │
  │    "coordinator" to mitigate.                       │
  │  ✗ Cross-shard transactions limited.                │
  │  ✗ Schema changes are coordinator-orchestrated.     │
  └─────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────┐
  │  COCKROACHDB / SPANNER / YUGABYTE — native          │
  │                                                     │
  │  Range-sharded automatically. Raft per range.       │
  │  Strong serializable across the cluster.            │
  │                                                     │
  │  ✓ One database, transparently distributed.         │
  │  ✓ Cross-shard transactions are FREE (built-in).    │
  │  ✓ Multi-region with consensus per range.           │
  │  ✗ Write latency = inter-region quorum (50-150ms).  │
  │  ✗ Most expensive option.                           │
  │  ✗ SQL feature parity ≠ Postgres (improving).       │
  └─────────────────────────────────────────────────────┘
```

### 11.2 — Shard Key Selection (the choice you cannot un-make)

```plaintext
THE FOUR PROPERTIES OF A GOOD SHARD KEY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. EVENLY DISTRIBUTED
     Hash(key) spreads writes evenly across shards. No hotspot.
     hash(user_id) good. hash(country) bad (10% of users in US).

  2. PRESENT IN MOST QUERIES
     90%+ of queries should filter on the shard key, so they
     hit one shard, not all. Plan your access patterns first.

  3. CO-LOCATES RELATED DATA
     Tables joined frequently should share the shard key.
     Orders + order_items both sharded by user_id → JOIN
     stays on one shard. Sharded by different keys → scatter.

  4. STABLE
     Shard key shouldn't change after row creation. If user
     can change their tenant_id, that's a CROSS-SHARD MOVE
     (delete from shard A, insert into shard B, atomically).


SHARD KEY CHOICES (worked examples):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  E-COMMERCE:
   Candidates: user_id, order_id, region, tenant_id.
   Best: user_id. Most queries filter on user (their orders,
         their cart, their addresses). Co-locates user-owned
         data. Hash spreads evenly (~hundreds of millions).
   Failure: queries like "all orders shipped today" become
            scatter-gather. Solution: CQRS read model (Rung 6).

  MULTI-TENANT SAAS:
   Candidates: tenant_id (organization), user_id.
   Best: tenant_id. Tenants are the natural unit of isolation.
         Tenant-aware queries hit one shard. Big tenants get
         their own dedicated shard ("tenant pinning").
   Failure: one whale tenant (Spotify on Slack) saturates
            their shard. Solution: per-tenant shard, possibly
            a dedicated cluster.

  SOCIAL NETWORK:
   Candidates: user_id, post_id.
   Best: user_id for user-owned data (profile, followers).
         post_id for posts (with secondary index on author).
   Hard problem: timelines. A user's feed contains posts from
                 N other users on N shards → fan-out. This is
                 why Twitter built fan-out-on-write (push posts
                 to follower inboxes) instead of fan-out-on-read.

  MESSAGING:
   Candidates: conversation_id, user_id.
   Best: conversation_id. Both participants find their
         messages on the same shard. Cross-conversation
         queries (mention search) go to a separate index.

  TIMESERIES / EVENTS:
   Candidates: time, source_id.
   Best: hash(source_id) + range(time) — composite. Source
         spreads evenly; time enables retention drops.
   Anti-pattern: sharding by time alone. The "current"
   shard takes 100% of writes. Cold shards waste capacity.


THE HOT SHARD (the failure mode that ruins migrations):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  After sharding, monitoring shows:
   shard_0: 80% CPU
   shard_1: 12% CPU
   shard_2: 11% CPU
   ...
   shard_15: 9% CPU

  Causes:
   - Bad shard key (one tenant or user is huge).
   - Hash function bias (rare but happens).
   - Sequential keys (hash(autoincrement_id)) where Postgres
     INSERT pattern lands them on one shard.

  Fixes:
   - Salt the key: hash(user_id || random_bucket).
   - Shard the whale into a dedicated shard.
   - Re-shard with a different key (the painful option).
   - Apply rate limits per tenant.


THE RE-SHARD OPERATION (when you must):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Add new shards (empty).
  2. Set up CDC from old shards to new layout.
  3. Backfill historical data shard-by-shard.
  4. Wait for CDC to catch up (real-time).
  5. Pause writes briefly OR use dual-write with idempotency.
  6. Verify row counts and checksums per shard.
  7. Cut over reads.
  8. Cut over writes.
  9. Decommission old shards (weeks later, after confidence).

  Vitess does steps 2-8 with VReplication and VDiff.
  Doing this manually is a 6-12 month project.
```

---

## Part 12: Cross-Shard Transactions (the hardest problem)

```plaintext
ONCE YOU SHARD, ATOMICITY ACROSS SHARDS DIES.

You need to update user.balance on shard 3 AND
account.ledger on shard 7 together. Both succeed or
both fail. Three approaches.


  ┌──────────────────────────────────────────────────────┐
  │  APPROACH 1: TWO-PHASE COMMIT (2PC)                  │
  ├──────────────────────────────────────────────────────┤
  │                                                      │
  │   Coordinator                Shard 3      Shard 7    │
  │       │                         │             │      │
  │       │── PREPARE TRANSACTION ─►│             │      │
  │       │── PREPARE TRANSACTION ──┼────────────►│      │
  │       │◄─ ready ───────────────│             │      │
  │       │◄─ ready ────────────────┼─────────────│      │
  │       │── COMMIT PREPARED ─────►│             │      │
  │       │── COMMIT PREPARED ──────┼────────────►│      │
  │                                                      │
  │  Postgres syntax:                                    │
  │    BEGIN;                                            │
  │    UPDATE balance ...;                               │
  │    PREPARE TRANSACTION 'tx-uuid-1';                  │
  │    -- on success on both shards:                     │
  │    COMMIT PREPARED 'tx-uuid-1';                      │
  │                                                      │
  │  ✓ ACID across shards.                               │
  │  ✗ Coordinator failure between PREPARE and COMMIT    │
  │    leaves prepared transactions HOLDING LOCKS until  │
  │    manual recovery. Hours of downtime in real        │
  │    incidents.                                        │
  │  ✗ Latency = max RTT to all shards × 2.              │
  │  ✗ One slow shard blocks all participants.           │
  │                                                      │
  │  Use when: regulatory requirement; shards in same    │
  │            DC; coordinator is highly available.      │
  │  Avoid when: anything else. Most teams should never  │
  │              use 2PC.                                │
  ├──────────────────────────────────────────────────────┤
  │  APPROACH 2: SAGA PATTERN                            │
  ├──────────────────────────────────────────────────────┤
  │                                                      │
  │  A long transaction is broken into a sequence of     │
  │  local transactions, each on one shard. If any step  │
  │  fails, COMPENSATING transactions undo prior steps.  │
  │                                                      │
  │   Forward path:                                      │
  │     1. Reserve inventory on shard A.                 │
  │     2. Charge payment on shard B.                    │
  │     3. Create order on shard C.                      │
  │                                                      │
  │   On failure at step 3:                              │
  │     2'. Refund payment on shard B (compensation).    │
  │     1'. Release inventory on shard A (compensation). │
  │                                                      │
  │  ✓ No distributed locks.                             │
  │  ✓ Each step is a fast local transaction.            │
  │  ✓ Naturally fits long-running business processes    │
  │    (waiting on user input, payment provider, etc).   │
  │  ✗ Eventually consistent — between steps, system     │
  │    state is "partially applied."                     │
  │  ✗ Compensations must be IDEMPOTENT and ALWAYS       │
  │    succeed (or you have stuck sagas requiring        │
  │    operator intervention).                           │
  │  ✗ Reasoning about state is harder than 2PC.         │
  │                                                      │
  │  Implementation:                                     │
  │   - Choreography: events drive the saga (each step   │
  │     emits event, next step subscribes).              │
  │   - Orchestration: a coordinator (Temporal, Camunda) │
  │     drives the saga. Easier to reason about.         │
  │     STRONGLY PREFER orchestration at scale.          │
  │                                                      │
  │  Use when: cross-service business processes,         │
  │            payment flows, multi-step provisioning.   │
  ├──────────────────────────────────────────────────────┤
  │  APPROACH 3: AVOID CROSS-SHARD ENTIRELY              │
  ├──────────────────────────────────────────────────────┤
  │                                                      │
  │  Pick a shard key that co-locates the data that      │
  │  must be transactionally consistent.                 │
  │                                                      │
  │  Example: shard by user_id. user.balance and         │
  │  user.ledger_entries both live on the same shard.    │
  │  Local Postgres ACID handles atomicity.              │
  │                                                      │
  │  ✓ Best performance, simplest reasoning.             │
  │  ✗ Constrains shard key choice.                      │
  │  ✗ Cross-user transfers (Alice → Bob, different      │
  │    shards) still need saga or 2PC.                   │
  │                                                      │
  │  Use when: you can. Always prefer this.              │
  └──────────────────────────────────────────────────────┘


PRINCIPAL'S CHOICE (the hierarchy):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Co-locate via shard key. Strongest, simplest.
  2. Saga + Temporal/Camunda orchestration.
  3. Native distributed SQL (Cockroach/Spanner) gives
     you cross-shard txns "for free."
  4. 2PC. Last resort. Almost never the right answer.
```

---

## Part 13: Rung 6 — CQRS and Polyglot Persistence

```plaintext
THE INSIGHT:
━━━━━━━━━━━

  Different access patterns deserve different storage.
  One database can't be optimal for:
   - Transactional writes (PG, normalized)
   - Full-text search (Elasticsearch, inverted index)
   - Sub-millisecond cache (Redis)
   - Aggregate analytics (ClickHouse, columnar)
   - Graph traversal (Neo4j)
   - Vector similarity (pgvector, Pinecone)

  CQRS (Command Query Responsibility Segregation) formalizes
  this: WRITE side is normalized PG; READ sides are
  purpose-built stores fed by events.


THE ARCHITECTURE:
━━━━━━━━━━━━━━━━

   App writes
       │
       ▼
   ┌──────────────┐
   │ PostgreSQL   │  source of truth, ACID, normalized
   │  (write)     │
   └──┬───────────┘
      │  WAL → Debezium (CDC) → Kafka
      │
      ├──► Elasticsearch    (full-text search)
      ├──► Redis            (hot reads)
      ├──► ClickHouse       (analytics)
      ├──► Neo4j            (graph features)
      └──► S3 + Iceberg     (data lake)

   App reads
     ├─ search query    → Elasticsearch
     ├─ get user        → Redis (or PG fallback)
     ├─ dashboard       → ClickHouse
     ├─ recommendations → Neo4j
     └─ historical      → Iceberg via Trino


THE INVARIANTS YOU MUST UPHOLD:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. WRITE SIDE IS THE TRUTH.
     If read models drift, rebuild them from PG. Never
     accept "ES says X, PG says Y, customer believes ES."

  2. EVERY READ MODEL IS REBUILDABLE FROM SCRATCH.
     Bootstrap a new ES cluster: snapshot PG, replay
     CDC. Total time bounded. Document the procedure.

  3. EVERY READ MODEL HAS AN OWNER.
     Who pages when ES drifts from PG? Who decides the
     index schema? Who manages lifecycle? Without an
     owner, read models rot.

  4. EVERY EVENT IS IDEMPOTENT.
     CDC will deliver duplicates. Consumers MUST dedupe
     by event_id or LSN.


THE OPERATIONAL TAX:
━━━━━━━━━━━━━━━━━━━

  Each new read store adds:
   - A consumer service to maintain.
   - A schema to evolve.
   - A failure mode (drift) to detect.
   - A reconciliation job to validate.
   - A dashboard. An on-call.

  CQRS done right is powerful. CQRS done casually is
  the architecture equivalent of opening 7 browser tabs
  and ignoring them.

  Rule: never add a read store without retiring or
  replacing one when its purpose subsumes another.
```

---

## Part 14: CDC Failure Modes (the bridge that breaks all of this)

CDC is the connective tissue of CQRS. When CDC breaks, every read model drifts. Five failure modes you must know.

```plaintext
FAILURE 1 — SNAPSHOT RESTART
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Connector crashed mid-snapshot. Default behavior on
  restart: re-snapshots from scratch. Downstream sees
  every row twice with op=READ.

  Defense:
   - snapshot.mode = initial (default) requires consumer
     idempotency to handle re-snapshot duplicates.
   - snapshot.mode = never (or initial_only): risky;
     skips snapshot, you must guarantee data already
     exists downstream.
   - Custom: bookmark snapshot progress per table in a
     state table; resume from bookmark on restart.


FAILURE 2 — SCHEMA EVOLUTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Producer DBA: ALTER TABLE orders DROP COLUMN promo_code;
  Debezium emits new schema to Schema Registry.
  Consumer with FORWARD compatibility REJECTS schema.
  Consumer halts. Lag grows. Slot bloats. Primary disk fills.

  Schema Registry compatibility rules:
   - BACKWARD: new schema can read old data. (Drop column OK.)
   - FORWARD: old schema can read new data. (Add column OK.)
   - FULL:    both. (Most restrictive — only optional fields change.)
   - NONE:    no checks. Don't.

  Defense:
   - Schema Registry: BACKWARD or FULL.
   - Process: drop-column migrations follow expand →
     migrate → contract over multiple deploys.
   - Pre-deploy gate: schema diff against registry,
     fail PR if incompatible.


FAILURE 3 — DELETES AND TOMBSTONES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Debezium emits DELETE event followed by tombstone
  (key=PK, value=null) to enable Kafka log compaction.

  Consumer pitfalls:
   - Treating null value as "no change" → ghost rows
     persist downstream forever.
   - Treating tombstone as a record → null pointer hell.

  Defense: explicitly handle op=DELETE; ignore tombstones
  except for compaction.


FAILURE 4 — DLQ POISONING
━━━━━━━━━━━━━━━━━━━━━━━━

  Bad message (corrupt Avro, schema mismatch). Without DLQ,
  consumer loops forever, lag grows, slot bloats.

  With DLQ:
   - Bad messages routed to dead-letter topic.
   - Consumer advances.
   - DLQ alarmed: max size, age, fill rate.
   - DLQ has finite retention so it can't fill disk itself.


FAILURE 5 — KEY-LEVEL ORDERING VIOLATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Kafka preserves order WITHIN a partition.
  Debezium partitions by PK by default → events for one
  row stay ordered.

  If you re-key (e.g., by user_id for user-feed projection),
  events for one row land in different partitions, may be
  consumed out of order. UPDATE arrives before DELETE.
  Downstream shows resurrected data.

  Defense:
   - Always store last_lsn per key in consumer state.
   - On incoming event, compare incoming LSN to stored.
     Discard older. Apply newer.
   - This is THE idempotency contract for CDC consumers.


THE CDC HEALTH DASHBOARD (build this):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Per CDC pipeline, expose:
   - Connector status (running/paused/failed)
   - Replication slot active flag
   - Replication slot retained_wal size
   - Producer LSN vs source primary LSN (lag in bytes)
   - Producer LSN vs current time (lag in seconds)
   - Per-topic message rate
   - DLQ size, oldest message age
   - Schema Registry compatibility violations (count)
   - Downstream consumer lag (Kafka consumer group)
   - Reconciliation drift (sample row counts PG vs ES)
```

---

## Part 15: Rung 7 — Multi-Region

```plaintext
WHY YOU MIGHT NEED IT:
━━━━━━━━━━━━━━━━━━━━━

  - GEOGRAPHIC LATENCY: Tokyo users hit Virginia DB at
    200ms RTT. Page load times unacceptable.
  - REGULATORY: GDPR data residency requires EU data
    physically in EU.
  - DR / BUSINESS CONTINUITY: survive a region-wide outage.

WHY YOU MIGHT NOT:
━━━━━━━━━━━━━━━━━

  - "Higher availability" alone is rarely enough. Active/
    passive failover is simpler than active/active.
  - 95% of your traffic is one region. Don't pay for the
    complexity.


THE TWO TOPOLOGIES:
━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────────────────────────────┐
  │  ACTIVE / PASSIVE                                    │
  │                                                      │
  │   Region A (primary)         Region B (standby)      │
  │     ┌─────────┐                ┌──────────┐          │
  │     │ Writes  │── async repl ─►│ Replica  │          │
  │     │ Reads   │                │ Reads    │          │
  │     └─────────┘                └──────────┘          │
  │                                                      │
  │  Aurora Global DB: <1s cross-region replication.     │
  │  PG logical replication: 5-30s typical.              │
  │  Failover: DNS/global LB shifts traffic to B,        │
  │  promote B's replica to primary.                     │
  │                                                      │
  │  ✓ Simple. Same write semantics as single-region.    │
  │  ✓ Most apps need only this.                         │
  │  ✗ RPO > 0 on regional failure (some writes lost).   │
  │  ✗ B's replicas may be stale at failover moment.     │
  └──────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────┐
  │  ACTIVE / ACTIVE                                     │
  │                                                      │
  │   Region A           Region B           Region C     │
  │   Writes ◄────────► Writes ◄────────► Writes         │
  │     │                  │                  │          │
  │     └──── conflict resolution ──── consensus or LWW  │
  │                                                      │
  │  All regions accept writes. Writes replicate to other │
  │  regions. Conflicts (same row written in two regions │
  │  simultaneously) MUST be resolved.                   │
  │                                                      │
  │  ✓ Local write latency in every region.              │
  │  ✓ Survives regional partitions (writes continue).   │
  │  ✗ Conflict resolution is hard. See §16.             │
  │  ✗ Operational complexity = 10× active/passive.      │
  └──────────────────────────────────────────────────────┘
```

---

## Part 16: Multi-Master Conflict Resolution

```plaintext
THE FOUR STRATEGIES (in increasing strength):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────────────────────────────┐
  │  1. LAST-WRITE-WINS (LWW)                            │
  │                                                      │
  │  Each write has a timestamp. On conflict, highest    │
  │  timestamp wins. Other write LOST silently.          │
  │                                                      │
  │  Used by: Cassandra default, DynamoDB Global Tables, │
  │  most NoSQL.                                         │
  │                                                      │
  │  ✓ Trivial to implement.                             │
  │  ✗ Loses data. ✗ Clock skew = wrong winner.          │
  │                                                      │
  │  Safe for: ephemeral data (last-known-location,      │
  │  cache-like, presence indicators).                   │
  │  UNSAFE FOR: anything you bill the customer for.     │
  ├──────────────────────────────────────────────────────┤
  │  2. VECTOR CLOCKS / CAUSAL                           │
  │                                                      │
  │  Each write carries a vector (node_id → counter).    │
  │  System detects causal vs concurrent. Causal: keep   │
  │  newer. Concurrent: surface conflict to app.         │
  │                                                      │
  │  Used by: Riak, original Dynamo, early CouchDB.      │
  │                                                      │
  │  ✓ Preserves causality.                              │
  │  ✗ App must implement merge per type.                │
  ├──────────────────────────────────────────────────────┤
  │  3. CRDTs (CONFLICT-FREE REPLICATED DATA TYPES)      │
  │                                                      │
  │  Data types with mathematically commutative,         │
  │  associative, idempotent merge. All replicas         │
  │  converge regardless of message order.               │
  │                                                      │
  │  Types:                                              │
  │   G-Counter    increment-only counter                │
  │   PN-Counter   increment + decrement                 │
  │   OR-Set       observed-remove set                   │
  │   LWW-Register single value with LWW                 │
  │   RGA / Yjs    sequences (collaborative editing)     │
  │   Automerge    full document CRDTs                   │
  │                                                      │
  │  Used by: Redis Active-Active (CRDB), Riak, Figma,   │
  │  collaborative editors, ElectricSQL.                 │
  │                                                      │
  │  ✓ Math-guaranteed convergence.                      │
  │  ✗ Limited to operations expressible as CRDTs.       │
  │  ✗ Storage overhead per element.                     │
  ├──────────────────────────────────────────────────────┤
  │  4. CONSENSUS PER RANGE (NewSQL)                     │
  │                                                      │
  │  Raft/Paxos quorum elects leader per data range.     │
  │  Writes route to range leader. Strong serializable.  │
  │  Spanner uses TrueTime; CockroachDB uses HLC.        │
  │                                                      │
  │  Used by: Spanner, CockroachDB, Yugabyte, FoundationDB. │
  │                                                      │
  │  ✓ Strong consistency, standard SQL semantics.       │
  │  ✗ Write latency = inter-region quorum (50-150ms).   │
  │  ✗ Most expensive. Hardest to operate.               │
  └──────────────────────────────────────────────────────┘


WHICH TO PICK (by data type):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Money / billing / inventory     → Consensus, OR don't
                                     active/active.
  Social-media counters / likes   → CRDTs (PN-Counter).
  Shopping carts (eventual OK)    → CRDTs (OR-Set).
  User profile last_seen          → LWW with HLC timestamps.
  Collaborative documents         → CRDTs (Yjs, Automerge).
  Inventory                       → SINGLE source of truth.
                                     Reservations propagate
                                     async. NEVER LWW.


THE INVENTORY LESSON:
━━━━━━━━━━━━━━━━━━━━

  Real incident, 2015, major retailer:
   - Inventory in active/active LWW across two regions.
   - Black Friday. Customer in Tokyo and customer in NYC
     buy the LAST UNIT of an item within 50ms.
   - Both writes succeed locally.
   - LWW conflict resolution kept one. Other discarded.
   - But: both customers were CHARGED locally before
     conflict resolution.
   - Phantom sale. Customer charged for nothing.
   - × 12,000 SKUs across the day.
   - $4M refunds + brand damage.

  Lesson: SCARCE RESOURCES need a single writer. LWW is
  for data where simultaneous winners are tolerable.
  Inventory, balances, seat reservations are not.
```

---

## Part 17: Rung 8 — Tier Your Data (the de-scaling rung)

```plaintext
THE INSIGHT:
━━━━━━━━━━━

  At scale, the cheapest "scaling" is REMOVING data from
  the hot path. Most rows are read once and never again.
  Why pay primary-DB prices to keep them online forever?


THE TIERS:
━━━━━━━━━

  HOT     last 30 days        primary OLTP           Postgres
  WARM    30 days - 1 year    cheaper storage        Postgres replica
                                                      on gp3 / cold
                                                      partitions
  COLD    > 1 year            object store + query   S3 + Iceberg
                                                      + Trino/Athena
  FROZEN  compliance hold     archival               Glacier Deep
                                                      Archive


IMPLEMENTATION:
━━━━━━━━━━━━━

  1. Range-partition by created_at (Part 10).
  2. pg_partman manages monthly partition lifecycle.
  3. Partitions older than 1 year:
     - Detach from parent.
     - Export to S3 in Parquet (Iceberg).
     - Drop from Postgres.
  4. Cross-tier queries via Trino federation:
     - SELECT * FROM orders WHERE created_at > '2025-01-01';
       → Postgres only.
     - SELECT * FROM orders WHERE created_at > '2020-01-01';
       → Trino federates Postgres + Iceberg.

THE COST DELTA:
━━━━━━━━━━━━━

  60TB on RDS gp3:        ~$8,000/month
  60TB on S3 + Glacier:   ~$300/month
  Tier ratio: 26×.

  This is the rung Stripe / Shopify / Airbnb climb instead
  of buying ever-bigger primary databases.
```

---

## Part 18: The Decision Framework (the capstone)

```plaintext
SYMPTOM-DRIVEN DECISION TREE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌─ "Database is slow"
  │
  │  Q1. Is CPU pegged?
  │       Yes → bad query plan. EXPLAIN ANALYZE.    [Rung 0]
  │       No  → next.
  │
  │  Q2. Is disk IO pegged?
  │       Yes → missing index OR insufficient cache.  [Rung 0]
  │       No  → next.
  │
  │  Q3. Are connections at limit?
  │       Yes → pooling.                              [Rung 1]
  │       No  → next.
  │
  │  Q4. Are reads dominant and replicas absent?
  │       Yes → add replicas.                         [Rung 2]
  │       No  → next.
  │
  │  Q5. Is largest instance class exhausted?
  │       No  → scale up.                             [Rung 3]
  │       Yes → next.
  │
  │  Q6. Does table size exceed practical single-server limits
  │      (>5TB hot, >100k writes/s sustained)?
  │       No  → partition.                            [Rung 4]
  │       Yes → next.
  │
  │  Q7. Is the workload truly partitionable by a stable key?
  │       Yes → shard.                                [Rung 5]
  │       No  → re-architect; you may have a domain modeling
  │             problem, not a scaling problem.
  │
  │  Q8. Are read patterns radically different from writes?
  │       Yes → CQRS read models.                     [Rung 6]
  │
  │  Q9. Is geographic latency the bottleneck?
  │       Yes → multi-region.                         [Rung 7]
  │
  │  Q10. Is dataset growing and old data rarely accessed?
  │       Yes → tier.                                 [Rung 8]


THE RETREAT TREE (just as important):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  - 4 read replicas, lag never matters, primary at 20% CPU
      → drop 2 replicas.

  - Sharded 16 ways, 6 shards at 5% CPU
      → re-merge or rebalance.

  - CQRS read store used by 1 endpoint that runs 3×/day
      → kill the read store, run query on primary.

  - Multi-region for a product 95% in one region
      → collapse, save 40% spend.

  Complexity has a maintenance tax. Pay only when it pays
  for itself.
```

---

## Part 19: Cross-Module Integration (where it clicks)

```plaintext
THIS MODULE IS NOT AN ISLAND.

CDN Fundamentals (Wk 1 T6):
  CDN with 95% hit ratio reduces DB QPS by 20×. Equivalent
  to climbing 4 rungs without touching the DB. Always
  cache-first.

Caching Patterns (Wk 2 T3):
  Redis cache-aside reduces DB QPS by 10-100×. The
  Rung-1-to-Rung-2 transition should usually go through
  "add aggressive caching" first.

Cassandra Architecture (Wk 5 T1):
  Cassandra is what happens when you pre-shard on day 1.
  Eventual consistency by default, tunable, no Rung 5
  migration trauma — but you pay operational complexity
  upfront.

Week 4 T1 (sync replication failover):
  Part 6.2 is the formalization of that bug. Silent
  degradation to async appears in every replicated
  system: Kafka ISR, Cassandra hinted handoff, Mongo
  write concerns. Same shape, same defense (alarm on
  state transitions).

Week 4 T2 (cascade analysis):
  Part 13 (CQRS) and Part 14 (CDC failures) are where
  cascades start. CDC halts → read models drift →
  search stale → users retry → app hits OLTP directly
  → primary saturates → cascade.

Week 6 (Event-driven, upcoming):
  Part 12 (sagas) and Part 13 (CQRS + outbox) are the
  bridge to event sourcing. CDC is the rough version;
  outbox + Kafka is the disciplined version.
```

---

## Part 20: Retention Test (no peeking)

```plaintext
ANSWER IN YOUR HEAD BEFORE READING.

Q1. p99 went from 50ms → 800ms. CPU on primary is 30%.
    Team wants to shard. What's your first question?

Q2. PgBouncer in transaction mode. App reports
    "search_path is randomly wrong." What's wrong?

Q3. Postgres at 92% disk, pg_wal is 600 GB. All replicas
    current. What query do you run?

Q4. synchronous_standby_names = 'FIRST 1 (r1, r2)'.
    Both replicas die. What happens to writes?

Q5. Debezium connector lag 2h, growing. Consumer offsets
    advancing normally. What's wrong?

Q6. Sharded by user_id. Query "all orders shipped today"
    runs against the OLTP cluster. What happens, and
    what's the right architecture?

Q7. Inventory active/active two regions, LWW. Customer
    charged for out-of-stock item. Explain the bug.

Q8. Read-your-writes via LSN, transaction-pooled. Where
    do you capture the LSN, and where do you NOT?

Q9. CDC consumer halted on schema change. Producer
    dropped a column. What Schema Registry config
    would have prevented this?

Q10. Rung 3 exhausted (biggest SKU, 100k writes/s).
     Boss says "shard." What 5 questions do you ask?


ANSWERS:
━━━━━━━

A1. "What changed in the query pattern, dataset size, or
    indexes?" Latency rising with low CPU = lock waits or
    bad plan flip from grown data. Sharding fixes neither.

A2. SET search_path (without LOCAL) leaks across clients
    sharing the backend connection. Fix: SET LOCAL inside
    a txn, or set via connection string / role default.

A3. SELECT slot_name, active, pg_wal_lsn_diff(
      pg_current_wal_lsn(), restart_lsn)
    FROM pg_replication_slots ORDER BY 3 DESC;
    An inactive slot is almost certainly pinning WAL.
    "Replicas current" doesn't mean all CDC consumers
    are current.

A4. Writes hang indefinitely. wait_event = SyncRep.
    Three solutions: (a) keep sync, accept availability
    hit; (b) auto-degrade to async (alarm the transition!);
    (c) quorum across 3 replicas. Most teams should pick
    (b) with explicit sync_state monitoring.

A5. Lag is upstream, not downstream. Debezium can't read
    WAL fast enough. Check connector throughput, task
    count, and slot confirmed_flush_lsn vs primary's
    current LSN. Consumer offsets are about Kafka, not
    about CDC source.

A6. Scatter-gather across all shards → p99 explodes.
    Right architecture: CQRS read model. Replicate
    orders to a read store keyed/indexed by ship_date
    (Elasticsearch, ClickHouse, or Citus reference table).

A7. Both regions accepted concurrent purchases of the
    last unit; LWW kept one and discarded the other,
    BUT customers were charged locally before conflict
    resolution → the discarded write's customer paid for
    nothing.

A8. Capture INSIDE the writing transaction:
      INSERT ... RETURNING id, pg_current_wal_insert_lsn();
    NEVER capture in a separate connection after commit —
    you'd get the cluster's current LSN, which is not
    necessarily yours and may belong to another commit.

A9. Forward compatibility was set; consumer required the
    dropped column. Correct config: BACKWARD (consumer
    can read old data with new schema). Process fix:
    drop-column changes follow expand → migrate →
    contract over multiple deploys.

A10. (1) What's the dataset growth curve over 12 months?
     (2) Are reads or writes the bottleneck?
     (3) Have we tried CQRS to move dominant reads off
         the OLTP primary?
     (4) What's our shard key candidate, and which
         queries does it serve badly?
     (5) What's the migration plan and rollback strategy?
     Sharding is a 1-way door; these five answers decide
     whether you walk through it.


SCORING:
━━━━━━━

  9-10  Ready for Week 5 T2 (Kafka/Streaming).
  7-8   Re-read Parts 5, 6, 7, 8, 14 before moving on.
  <7    Re-read the whole module. Week 6 (event-driven)
        depends on this.
```

## Part 21: SRE Scenario — "The Black Friday Slot"

```plaintext
THE PAGE (03:47 UTC, Black Friday + 8 hours in):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PagerDuty: [P1] prod-pg-primary-1: disk_used > 85%
             pg_wal volume: 1.6 TB / 2 TB

  Slack #incidents (last 40 minutes, paraphrased):

    03:08  oncall-sre:  "checkout latency spiking, p99 1.2s
                         (normal 80ms). investigating."
    03:11  oncall-sre:  "primary CPU 45%, replicas healthy,
                         replay_lag < 200ms. weird."
    03:14  oncall-app:  "checkout error rate 4%. customers
                         seeing 'order not found' on confirm
                         page after submit."
    03:19  oncall-sre:  "rolled back the 02:00 deploy. no
                         change. p99 still climbing."
    03:26  oncall-sre:  "shared_buffers hit ratio 99.6%,
                         no seq scans in pg_stat_statements
                         top 50. nothing obvious."
    03:33  oncall-data: "search results stale by ~30 min in
                         /search. ES cluster healthy though."
    03:41  oncall-sre:  "checkpoint_completion taking 4×
                         normal. wal volume filling."
    03:47  PagerDuty:   [P1] disk_used > 85%

  THE STAGE:
   - PostgreSQL 15 primary, r6i.16xlarge, 2 TB pg_wal volume.
   - 2 streaming replicas (sync, FIRST 1 (r1, r2)).
   - 1 logical replication slot 'debezium_orders' → Kafka → ES.
   - 1 logical replication slot 'analytics_etl' → ClickHouse.
   - PgBouncer transaction mode in front, 4000 client conns,
     200 backend conns.
   - Black Friday peak: 3.2× normal write volume.

  YOU ARE THE PRINCIPAL ENGINEER joining the bridge at 03:47.
  You have 13 minutes before disk fills at current rate.
  What do you do, in what order, and why?
```

---

## Part 22: The Walkthrough (read AFTER you've thought it through)

```plaintext
MINUTE 0 (03:47) — DIAGNOSIS BEFORE ACTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom set:
   - Disk filling on pg_wal volume (not data volume).
   - Replicas current (replay_lag < 200ms).
   - CPU healthy.
   - p99 climbing on primary.
   - ES search results stale by 30 min.
   - Checkpoint completion 4× normal.

  THE PATTERN:
   pg_wal filling + replicas current + downstream stale
   = a CONSUMER of WAL is behind. Not a streaming replica.
   Almost certainly a logical replication slot.

  The "ES stale by 30 min" is the smoking gun the team
  hasn't connected to the disk alarm yet. It's the same
  incident.

  Run the slot query FIRST (Part 7):

    SELECT slot_name, active, active_pid,
      pg_size_pretty(pg_wal_lsn_diff(
        pg_current_wal_lsn(), restart_lsn)) AS retained
    FROM pg_replication_slots
    ORDER BY pg_wal_lsn_diff(
      pg_current_wal_lsn(), restart_lsn) DESC;

  Hypothetical (and realistic) output:

    slot_name           active   retained
    ─────────────────   ──────   ────────
    debezium_orders     true     1.4 TB    ← here
    analytics_etl       true     180 GB
    replica_r1          true     12 MB
    replica_r2          true     12 MB

  Debezium slot is ACTIVE (consumer connected) but
  retention is 1.4 TB. That means Debezium is connected
  but not advancing confirmed_flush_lsn fast enough.
  Producer is overwhelmed, not dead.


MINUTE 2 (03:49) — CONFIRM, DON'T GUESS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Verify Debezium is the cause, not just correlated:

    SELECT slot_name,
      pg_size_pretty(pg_wal_lsn_diff(
        pg_current_wal_lsn(), confirmed_flush_lsn)) AS pending
    FROM pg_replication_slots
    WHERE slot_name = 'debezium_orders';

  pending = 1.4 TB → consumer is 1.4 TB behind on flush.

  Check Debezium connector:
   - Connect to Kafka Connect REST: GET /connectors/debezium-orders/status
   - Hypothetical: RUNNING, but task throughput dropped from
     baseline 80 MB/s to 8 MB/s at 02:55.

  Check Kafka:
   - Producer-side throttling? Broker disk? Topic partition count?
   - Hypothetical finding: orders topic has 6 partitions. Black
     Friday traffic needs 24. Single producer thread is the
     bottleneck. Debezium can't shove WAL into Kafka fast
     enough.

  Now you know the cause. Now you can choose.


MINUTE 5 (03:52) — THE THREE CHOICES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Disk fills in ~10 minutes at current rate. You have
  three levers, each with a different cost.

  CHOICE A — DROP THE SLOT.
    SELECT pg_drop_replication_slot('debezium_orders');
    
    Effect: WAL freed at next checkpoint (~2 min). Disk
    safe within 5 min. Debezium connector breaks. ES will
    be stale until you re-snapshot orders table (~4 hours
    on this dataset).
    
    Cost: 4 hours of stale search during Black Friday peak.
    Search results are degraded but checkout works.

  CHOICE B — SCALE THE CONSUMER.
    Increase orders topic partitions: 6 → 24.
    Restart Debezium with max.batch.size and 
    max.queue.size raised, producer.acks=1 (from all),
    producer.compression.type=lz4.
    
    Effect: throughput recovers to ~80 MB/s. But you have
    1.4 TB of backlog to drain. At 80 MB/s net drain rate
    (after new WAL keeps coming), drain takes 6+ hours.
    Disk fills before drain completes.
    
    Cost: doesn't solve the immediate disk problem.

  CHOICE C — EMERGENCY DISK EXTENSION + B.
    AWS: modify EBS volume 2 TB → 4 TB (online, ~minutes
    to be available, hours to fully optimize).
    Then execute Choice B.
    
    Effect: buys 4-6 hours of headroom. Consumer drains
    over that window. No data loss, no re-snapshot.
    
    Cost: $200 of EBS for the day. Operator vigilance.


  PRINCIPAL'S DECISION:
   C, then B in parallel.
   Drop-slot (A) loses ES freshness during peak revenue
   hours. Disk extension is reversible and cheap. The
   right call is almost always "buy time, then fix the
   real problem."

   But: kick off snapshot preparation in case C fails.
   "Hope is not a strategy. Plan B for plan B."


MINUTE 7 (03:54) — EXECUTE
━━━━━━━━━━━━━━━━━━━━━━━━━

  In parallel:
   1. SRE-1: aws ec2 modify-volume --size 4096
   2. SRE-2: increase orders topic partition count.
              kafka-topics --alter --partitions 24
              (re-keying caveat: see Part 14 Failure 5;
               in this case, Debezium re-keys by PK so
               same-PK events stay in same partition only
               if you use a sticky partitioner — verify.)
   3. SRE-3: bump Debezium task max.batch.size, restart
              connector with rolling restart.
   4. Comms: post in #incidents and to status page:
              "search results may be stale up to 60 min
               during recovery; checkout unaffected."

  At 03:58: disk extension live, retention growth slows.
  At 04:05: Debezium throughput at 110 MB/s, draining backlog.
  At 04:42: pending < 50 GB, ES catching up.
  At 05:30: pending < 1 GB, fully recovered.


MINUTE 60+ — POSTMORTEM PRELOADS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Five things this incident taught (or should have taught
  before it happened):

  1. NO max_slot_wal_keep_size CAP.
     Postgres 13+ supports it. We didn't set it. The
     primary was one bad consumer away from death.
     Action: set max_slot_wal_keep_size = 200GB cluster-wide.
     Trade-off acknowledged: a stuck consumer triggers
     re-snapshot. Re-snapshot is recoverable; disk-full
     primary failover is not.

  2. KAFKA TOPIC SIZING WAS NEVER LOAD-TESTED.
     6 partitions was fine at baseline. Nobody computed
     headroom for 3.2× peak. Capacity planning ignored
     the CDC pipeline because "Kafka scales infinitely."
     Action: load test EVERY pipeline at 4× peak before
     peak season. Document headroom per component.

  3. THE SLOT GROWTH GRAPH HAD NO ALARM.
     We had alarms on disk%. We had alarms on replication
     lag (replay_lag — the wrong metric for this!). We
     had no alarm on pg_replication_slots.retained_wal.
     The alarm we DID get fired with 13 minutes of runway.
     Action: alarm at 50 GB warn, 200 GB page, per slot,
     not per disk.

  4. ES STALENESS WAS A LEADING INDICATOR. NOBODY OWNED IT.
     Search team noticed staleness at 03:33. Database team
     paged at 03:47. Same incident, two teams, fourteen
     minutes of lost diagnostic time.
     Action: cross-team CDC dashboard. ES staleness routes
     to BOTH teams. Eliminate the silo.

  5. WE HAVE NO RUNBOOK FOR "SLOT BLOAT WITH ACTIVE CONSUMER."
     Runbook covered "dead consumer, drop slot." Did not
     cover "alive but slow consumer." Operator at 03:08
     spent 20 minutes ruling out query plans because
     that's where the runbook started.
     Action: rewrite runbook with the symptom-to-cause
     map from Part 1.
```

---

## Part 23: The Four In-Depth Questions

Answer in writing. Each one has a "easy answer" and a "principal answer." Aim for the latter.

```plaintext
QUESTION 1 — THE COUNTERFACTUAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Suppose max_slot_wal_keep_size = 200GB had been set
  before the incident. Walk through what would have
  happened minute-by-minute starting at 02:55 (when
  Debezium throughput dropped). Identify:
  
   (a) The exact moment Postgres would invalidate the
       slot.
   (b) What the SRE on-call sees, and on which dashboard.
   (c) The recovery path and its time cost.
   (d) Whether this outcome is BETTER or WORSE than what
       actually happened, and why your answer depends on
       business context (give two scenarios where the
       answer flips).

  This question tests whether you understand that the
  cap is not "the right answer" — it is a TRADE between
  two failure modes. A principal can articulate both
  sides.


QUESTION 2 — THE ROUTING DECISION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  At 03:14, customers reported "order not found on confirm
  page after submit." Search was stale, but checkout reads
  go to Postgres, not ES. So why were customers seeing
  this error?

  Hypothesis: checkout's confirm page reads from a
  read replica with read-your-writes implemented via
  the LSN-token strategy (Part 8).

   (a) Sketch the exact request flow that fails. Where
       could LSN propagation break in this scenario?
   (b) Given that streaming replicas had replay_lag <
       200ms, why would LSN-routed reads still fail?
   (c) Propose two diagnostic queries the SRE could
       have run on the replica to confirm or refute
       this hypothesis in 30 seconds.
   (d) Suppose the team had used the time-window
       stickiness strategy instead (10s primary window).
       Would this incident have manifested differently?
       How?

  This question tests Part 6.3 + Part 8 integration.
  An easy answer says "replicas were lagging." A
  principal answer notices replay_lag < 200ms rules
  that out and points elsewhere — likely PgBouncer
  transaction-pool LSN capture bug (Part 5.3 + 8).


QUESTION 3 — THE DESIGN ALTERNATIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Your post-incident review proposes one of two
  architectural changes. Argue for ONE and against
  the other, with cost and failure-mode reasoning:

  PROPOSAL X: Replace Debezium → Kafka → ES with
  the TRANSACTIONAL OUTBOX pattern. Application writes
  the order AND an outbox row in the same Postgres
  transaction. A separate poller reads outbox and
  publishes to Kafka.

  PROPOSAL Y: Keep Debezium, but switch the orders
  table to a SHARDED Postgres setup (Citus, 8 shards),
  with one Debezium connector per shard. Each shard
  has its own slot.

  Required in your answer:
   (a) Which proposal eliminates THIS incident's class
       of failure, and which only mitigates it?
   (b) What new failure modes does each introduce?
   (c) What's the migration cost in eng-months for
       each, given a team of 4?
   (d) Under what business conditions would you choose
       the OTHER one anyway?

  This question tests Parts 11, 13, and 14 together.
  The principal answer recognizes that X solves the
  cause (consumer-can't-keep-up) by shrinking the
  payload — outbox rows are tiny vs full WAL — while
  Y just gives you 8 ways to have the same problem
  in parallel. But Y might still be right if the
  primary is already write-saturated for OTHER reasons.


QUESTION 4 — THE CAPACITY PLAN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  You're now responsible for capacity planning for
  next year's Black Friday. The CFO will fund exactly
  ONE of the following. Pick one and defend it with
  numbers:

   (i)   Upgrade primary r6i.16xlarge → r6i.32xlarge
         ($60K/year incremental).
   (ii)  Add 16 more Kafka brokers and triple all
         CDC topic partition counts ($45K/year).
   (iii) Implement transactional outbox + dedicated
         outbox-publisher service (~3 eng-months
         build, $20K/year ops).
   (iv)  Hire one additional SRE dedicated to data
         platform ($220K/year fully loaded).

  Required:
   (a) For each option, state the failure mode it
       addresses AND the failure mode it does NOT.
   (b) Compute (with stated assumptions) the
       expected reduction in P1 incidents per year.
   (c) Identify which option produces compounding
       returns (helps next year and the year after)
       vs which produces one-time relief.
   (d) State which option you'd actually choose
       and why, given that you might be wrong about
       (b). What's your hedge?

  This question tests judgment under economic
  constraint — the actual job of a principal. The
  easy answer picks (i) (more hardware). The
  principal answer notices that (iii) eliminates the
  failure CLASS while (i) only buys headroom for the
  same failure to happen at higher volume next year.
  But the truly principal answer also notices that
  without (iv), nobody has time to build (iii), so
  the dependency graph is iv → iii.
```
