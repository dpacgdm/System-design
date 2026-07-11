# Answer Key - Replication Strategies

> Open only after attempting the learner file questions.

# Scenario: E-Commerce Flash Sale — Replication Meltdown

---

## Q1: Cascade Chain Analysis

### The Trigger

```
TRIGGER: Flash sale write TPS spike from 3,200 → 8,100
(2.53x increase).

This is the ONLY external event. Everything else is
a consequence of infrastructure that wasn't sized or
configured for this load.

The 8,100 TPS alone is NOT catastrophic. PostgreSQL
can handle this write volume. The trigger becomes
dangerous only because the infrastructure has no
isolation between failure domains.
```

### The Amplifiers

```
AMPLIFIER 1: Analyst's long-running query on replica-2
  [12:01:30]

  Replica-2 is applying WAL records to stay in sync.
  The analyst's query holds a snapshot that conflicts
  with WAL replay (the query needs rows that WAL replay
  wants to modify/delete). PostgreSQL's recovery conflict
  resolution: after max_standby_streaming_delay (30s),
  it CANCELS the query — but during those 30 seconds,
  WAL replay was PAUSED on replica-2. Lag accumulates.

  After cancellation, replica-2 must replay 30 seconds
  of accumulated WAL at 8,100 TPS. That's ~243,000
  transactions to catch up, while new writes keep
  arriving. Replica-2's lag grows to 14 seconds and
  stays high.

  This didn't cause the outage, but it removed 1/3
  of the read replica capacity at the worst possible
  moment. The remaining 2 replicas absorb replica-2's
  share of read traffic, increasing their load.

AMPLIFIER 2: "Read from primary" hotfix for cart reads
  [12:02:30]

  This is the CRITICAL MISTAKE. Detailed in Q2.
  Redirecting 85% of read traffic that was on replicas
  to the primary overwhelms the primary's connection
  pool. The primary was already handling 8,100 write
  TPS + 15% of reads. Adding cart reads (a significant
  fraction of the 85% read traffic) saturates the
  200-connection PgBouncer pool.

AMPLIFIER 3: Semi-sync standby falling behind
  [12:03:15]

  The semi-sync standby must acknowledge every write
  before the primary can commit (synchronous_commit = on).
  At 8,100 TPS, the standby's fsync rate can't keep up.
  Each write now blocks waiting for standby ACK.
  Write latency: 5ms → 340ms.

  This is a FEEDBACK LOOP: the primary is already
  overloaded (connection pool saturated), now writes
  are 68x slower, connections are held 68x longer,
  pool pressure increases further.

AMPLIFIER 4: Kubernetes health check cascade
  [12:03:45 — 12:04:00]

  Health check timeout = 500ms. Write latency = 340ms +
  queueing delay. Health checks fail → Kubernetes kills
  pods → pods restart → connection storm.

  Each restarting pod creates 20 new connections
  simultaneously (its connection pool initializes on
  startup). Multiple pods restarting = thundering herd
  against PgBouncer.

  PgBouncer crashes under the connection storm.

AMPLIFIER 5: Direct connections bypassing PgBouncer
  [12:04:15]

  With PgBouncer down, application servers fall back to
  direct PostgreSQL connections. max_connections=300 but
  480 connections attempted. "FATAL: too many connections."

  The connection pooler was the LAST LINE OF DEFENSE
  between application connection demand and database
  capacity. Its failure removes all connection management.
```

### The Critical Mistake

```
THE CRITICAL MISTAKE: Redirecting cart reads to primary
at 12:02:30 WITHOUT verifying primary capacity.

This is the moment a MANAGEABLE problem (stale cart
reads — annoying but not fatal) became an UNMANAGEABLE
one (primary overload → write failures → total outage).

Before the redirect:
  → Primary: handling writes (8,100 TPS) + 15% reads
  → Primary PgBouncer: busy but not saturated
  → Problem: stale cart reads on replicas (UX issue)
  → Revenue impact: LOW (users can refresh, retry)

After the redirect:
  → Primary: handling writes + 15% reads + cart reads
  → Primary PgBouncer: SATURATED (200/200)
  → Problem: ALL writes failing, ALL reads failing
  → Revenue impact: TOTAL ($47K/minute)

The team escalated a UX annoyance into a full outage.

THE CASCADE CHAIN:

  Write TPS spike (TRIGGER)
       │
       ▼
  Replica lag grows to 800ms (EXPECTED under load)
       │
       ├──► Analyst query amplifies replica-2 lag to 14s
       │    (AMPLIFIER — reduces replica capacity)
       │
       ▼
  Cart reads show stale data (SYMPTOM — annoying, not fatal)
       │
       ▼
  ╔═══════════════════════════════════════════════════╗
  ║ CRITICAL MISTAKE: Route cart reads to primary     ║
  ║ WITHOUT checking primary pool headroom            ║
  ╚═══════════════════════════════════════════════════╝
       │
       ▼
  Primary PgBouncer saturated (CASCADE BEGINS)
       │
       ├──► Semi-sync blocks writes (FEEDBACK LOOP)
       │         │
       │         ▼
       │    Write latency 5ms → 340ms
       │         │
       │         ▼
       │    Health checks fail (timeout 500ms)
       │         │
       │         ▼
       │    Kubernetes kills pods
       │         │
       │         ▼
       │    Connection storm on restart
       │         │
       │         ▼
       │    PgBouncer crashes
       │         │
       │         ▼
       │    Direct connections: "too many connections"
       │         │
       │         ▼
       ╰──► TOTAL OUTAGE
```

---

## Q2: Evaluating the 12:02:30 Decision

### What They Should Have Checked BEFORE Redirecting

```
CHECK 1: PRIMARY PgBouncer POOL UTILIZATION

  SHOW POOLS;  -- on primary PgBouncer
  -- or:
  psql -h pgbouncer-primary -p 6432 pgbouncer \
    -c "SHOW POOLS;"

  Look at:
  → cl_active: active client connections
  → cl_waiting: clients waiting for a server connection
  → sv_active: active server connections (out of 200 max)
  → sv_idle: idle server connections (available headroom)

  If sv_active is already >150/200 (75%+), adding
  significant read traffic will saturate the pool.

  AT 12:02:30, the primary was handling 8,100 write TPS
  + 15% of reads. With 200 server connections, utilization
  was likely ~70-80% already. Adding cart reads would push
  it past 100%.

  THEY DID NOT CHECK THIS.

CHECK 2: WHAT PERCENTAGE OF TOTAL READ TRAFFIC IS CART READS?

  If cart reads are 5% of all reads: redirecting them
  adds ~4% of total read traffic to the primary. Maybe
  manageable.

  If cart reads are 40% of all reads (likely during a
  flash sale — users are actively adding to carts):
  redirecting them adds ~34% of total read traffic to
  the primary. Definitely not manageable.

  They should have computed:
    additional_load = cart_read_tps × avg_query_time
    current_headroom = (200 - sv_active) × (1000 / avg_query_time)

    if additional_load > current_headroom:
        DO NOT REDIRECT

CHECK 3: CAN THE REPLICA LAG PROBLEM BE FIXED INSTEAD?

  Replica lag was 800ms on healthy replicas, 14s on
  replica-2. The 800ms lag is the actual problem for
  cart reads. Options to fix replica lag directly:
  → Kill the analyst query on replica-2 (immediate)
  → Temporarily increase max_standby_streaming_delay
    (prevent future conflicts)
  → Do nothing — 800ms lag means the cart will be
    correct within 800ms on refresh

CHECK 4: IS THIS ACTUALLY A REVENUE-IMPACTING PROBLEM?

  "Cart shows empty" = user added item, refreshed,
  saw empty cart. This is a read-your-writes violation.
  Annoying, but:
  → The item IS in the cart (write succeeded on primary)
  → Refreshing again (after 800ms replication catches up)
    shows the correct cart
  → No data loss, no financial impact
  → Support impact: some confused users

  This is NOT worth risking the primary's stability.
```

### What I Would Have Done Instead

```
STEP 1: KILL THE ANALYST QUERY [Immediate — 10 seconds]

  The analyst query on replica-2 caused its lag to spike
  to 14s. Kill it:

  -- On replica-2:
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE query_start < now() - interval '30 seconds'
    AND state = 'active'
    AND usename = 'analyst_user';

  With the query killed, replica-2 can start catching up.
  At 8,100 TPS, replaying 14 seconds of WAL takes time,
  but the lag will decrease.

STEP 2: READ-YOUR-WRITES FOR CART ONLY [2-3 minutes]

  Instead of redirecting ALL cart reads to primary,
  implement targeted read-your-writes:

  After a cart WRITE succeeds on the primary, set a
  short-lived cookie/session flag:

  async def add_to_cart(user_id, item):
      await primary_db.execute(
          "INSERT INTO cart_items ...", ...
      )
      # Flag this user for primary reads for 3 seconds
      await redis.set(
          f"cart_ryw:{user_id}", "1", ex=3
      )

  async def get_cart(user_id):
      # Check if user recently wrote to cart
      ryw_flag = await redis.get(f"cart_ryw:{user_id}")
      if ryw_flag:
          # This specific user reads from primary (3s window)
          return await primary_db.fetch(
              "SELECT * FROM cart_items WHERE user_id = $1",
              user_id
          )
      # Everyone else reads from replica
      return await replica_db.fetch(
          "SELECT * FROM cart_items WHERE user_id = $1",
          user_id
      )

  EFFECT: Only users who JUST wrote to their cart read
  from primary, and only for 3 seconds. This is a
  TINY fraction of total read traffic — maybe 2-5% of
  cart reads, not 100%.

  Primary pool impact: negligible (a few dozen extra
  reads/sec vs the thousands that the blanket redirect
  would have added).

STEP 3: IF FEATURE FLAG / CODE CHANGE ISN'T FAST ENOUGH

  Simplest fix: SESSION STICKINESS on replicas.

  Configure the read load balancer to use sticky sessions
  (hash on user_id). Each user consistently hits the SAME
  replica. That replica's state only moves forward →
  monotonic reads guaranteed. The user still experiences
  up to 800ms delay on the first read after a write, but
  they never see the cart go backward (items appearing
  and disappearing).

  This requires ZERO code changes — it's a load balancer
  config change:

  # HAProxy config for read replicas:
  backend pg_read_replicas
      balance source  # sticky by source IP
      # or: balance uri param(user_id) for HTTP-level stickiness
      server replica1 10.0.1.1:5432 check
      server replica2 10.0.1.2:5432 check
      server replica3 10.0.1.3:5432 check

  Combined with killing the analyst query: replica lag
  drops back toward 800ms → 2-5ms as replica-2 catches
  up. Cart reads become fresh within seconds. Problem
  solved without touching the primary.
```

---

## Q3: Semi-Sync Durability Decision

### Option A: synchronous_commit = local

```
WHAT IT DOES:
  The primary considers a write committed as soon as
  it's flushed to the PRIMARY's local WAL (fsync on
  primary). The standby receives the WAL stream
  asynchronously. The primary does NOT wait for the
  standby to confirm anything.

DURABILITY IMPLICATIONS:

  SCENARIO: Primary writes transaction T, fsyncs locally,
  commits, returns ACK to client. Client sees "success."

  Primary crashes BEFORE the WAL record reaches the
  standby.

  Standby is promoted. Transaction T is LOST.
  The client received "success" but the transaction
  doesn't exist on the new primary.

  WINDOW OF DATA LOSS:
  → Every transaction between the standby's last received
    WAL position and the primary's crash point is lost.
  → At 8,100 TPS with, say, 50ms of network/write lag,
    that's ~405 transactions per potential failover event.
  → For an e-commerce platform: 405 orders that customers
    were told "succeeded" but don't exist after failover.
  → These are financial transactions. 405 lost orders =
    charged customers with no order record. Reconciliation
    nightmare.

  RECOVERY: Identical to async replication. No durability
  guarantee beyond the primary's local disk. If the
  primary's disk is intact after restart, no data loss.
  If the primary is unrecoverable (disk failure),
  transactions not yet replicated are permanently lost.
```

### Option B: synchronous_commit = remote_write

```
WHAT IT DOES:
  The primary waits until the standby confirms the WAL
  data has been WRITTEN to the standby's OS buffer
  (write() syscall returned). The standby has NOT
  fsynced to disk yet. The data is in the standby's
  OS page cache but not guaranteed to be on physical
  disk.

DURABILITY IMPLICATIONS:

  SCENARIO: Primary writes T, waits for standby to
  confirm remote_write. Standby writes to OS buffer,
  sends ACK. Primary commits, returns ACK to client.

  Case 1: Primary crashes. Standby promotes.
  → Data IS on the standby (in OS buffer or fsynced
    by background process). Transaction T survives.
  → No data loss in this case. ✓

  Case 2: Standby crashes (power loss, kernel panic).
  → OS buffer not fsynced → data in page cache is LOST.
  → But primary still has the data (it fsynced locally).
  → No data loss — primary is the source of truth. ✓

  Case 3: BOTH primary AND standby crash simultaneously.
  → Primary has fsynced locally → data survives on
    primary's disk.
  → Standby had data in OS buffer only → data lost
    on standby's disk.
  → When both restart: primary has the data, standby
    doesn't. Standby re-syncs from primary.
  → No data loss IF primary's disk is intact. ✓

  Case 4: Primary crashes, THEN standby crashes before
  fsync completes.
  → Primary is down (disk may or may not be recoverable).
  → Standby had data in OS buffer, crashes before fsync.
  → Data lost on BOTH nodes.
  → This is the ONLY data loss scenario for remote_write.
  → Probability: extremely low. Requires two independent
    failures in rapid succession (primary crash + standby
    crash before background fsync, which typically
    completes within 5-30ms).

  WINDOW OF DATA LOSS:
  → Only the narrow window between standby write() and
    standby fsync() — typically 5-30ms.
  → AND only if both nodes fail in that window.
  → Versus `local`: data loss on ANY primary crash where
    standby hasn't received the WAL yet (~50ms window,
    single-node failure sufficient).

PERFORMANCE IMPACT:
  remote_write waits for the standby's write() syscall —
  which is a memory copy to the OS page cache. This is
  sub-millisecond (typically 0.1-0.5ms).

  Compare to full synchronous_commit = on:
  → Waits for standby fsync() — physical disk write.
  → 2-10ms for SSD, longer under load.
  → At 8,100 TPS, this is the bottleneck causing 340ms.

  remote_write latency overhead: <1ms (vs 340ms for full sync).
  The standby's background fsync process handles disk
  writes asynchronously — it doesn't block the primary.
```

### My Choice: Option B (remote_write)

```
REASONING:

                   ╭──────────────┬──────────────┬─────────────╮
                   │ local (A)    │ remote_write │ on (current)│
                   │              │ (B)          │             │
  ╭────────────────┼──────────────┼──────────────┼─────────────┤
  │ Write latency  │ ~2ms         │ ~3ms         │ 340ms       │
  │ overhead       │ (local fsync │ (local fsync │ (standby    │
  │                │  only)       │  + network + │  fsync)     │
  │                │              │  memcpy)     │             │
  ├────────────────┼──────────────┼──────────────┼─────────────┤
  │ Data loss on   │ YES — all    │ NO — standby │ NO — standby│
  │ primary crash  │ transactions │ has data in  │ has data on │
  │ (single node)  │ not yet      │ OS buffer    │ disk        │
  │                │ replicated   │              │             │
  ├────────────────┼──────────────┼──────────────┼─────────────┤
  │ Data loss on   │ YES          │ TINY window  │ NO          │
  │ dual crash     │              │ (both crash  │             │
  │                │              │  within 5-   │             │
  │                │              │  30ms)       │             │
  ├────────────────┼──────────────┼──────────────┼─────────────┤
  │ Throughput     │ Full         │ Nearly full  │ Bottlenecked│
  │ at 8,100 TPS  │              │              │ (blocking)  │
  ╰────────────────┴──────────────┴──────────────┴─────────────╯

  remote_write gives:
  → 99.99%+ of the durability of full sync
    (only loses data if BOTH nodes crash within 5-30ms)
  → 99%+ of the performance of fully async
    (~3ms vs ~2ms per write — negligible difference)
  → Resolves the immediate crisis (340ms → ~3ms writes)
  → Standby remains a valid failover target
    (has all data, just not fsynced yet)

  `local` gives slightly better performance (~1ms less)
  but opens a real data loss window on any single primary
  failure. For an e-commerce platform processing financial
  transactions at $47K/minute, losing 405 orders on a
  primary crash is unacceptable.

  The tradeoff is clear: remote_write sacrifices ~1ms of
  latency (vs local) to maintain meaningful replication
  durability. That's the right trade for financial data.

  COMMAND:
  ALTER SYSTEM SET synchronous_commit = 'remote_write';
  SELECT pg_reload_conf();
  -- No restart required. Takes effect immediately.
  -- Verify: SHOW synchronous_commit;
```

---

## Q4: Immediate Mitigation Plan (12:04:30, First 10 Minutes)

### Situation at 12:04:30

```
STATE:
  → PgBouncer on primary: CRASHED
  → App servers: attempting direct connections → max_connections hit
  → PostgreSQL primary: rejecting new connections (300/300)
  → Semi-sync standby: blocking writes (340ms per write)
  → Health checks: failing → Kubernetes killing pods → connection storms
  → Revenue loss: $47K/minute
  → Flash sale: ongoing, users actively trying to purchase

PRIORITY HIERARCHY:
  1. Stop the bleeding (prevent further cascade)
  2. Restore write capability (revenue)
  3. Restore read capability (user experience)
  4. Stabilize and monitor
```

### Minute 0-1: Stop the Cascade

```
ACTION 1: STOP KUBERNETES FROM KILLING PODS [0:00 — 15 seconds]

  Kubernetes is making everything worse. Every killed pod
  restarts and creates 20 new connections, amplifying
  the connection storm. Stop the restart loop:

  # Temporarily increase health check tolerance:
  kubectl patch deployment app-server -n prod --type=json \
    -p='[{"op":"replace","path":"/spec/template/spec/containers/0/livenessProbe/failureThreshold","value":30}]'

  # Or faster — suspend the liveness probe entirely:
  kubectl patch deployment app-server -n prod --type=json \
    -p='[{"op":"remove","path":"/spec/template/spec/containers/0/livenessProbe"}]'

  WHY FIRST: Every second Kubernetes kills pods, the
  connection storm intensifies. This is a POSITIVE
  FEEDBACK LOOP — killing pods creates more connections,
  which causes more failures, which kills more pods.
  Breaking this loop is the #1 priority. Everything
  else fails if pods keep restarting.

  VERIFY: No more pod restarts in `kubectl get events`.


ACTION 2: RELIEVE SEMI-SYNC WRITE PRESSURE [0:15 — 30 seconds]

  Switch synchronous_commit to remote_write (per Q3):

  # Connect directly to PostgreSQL (PgBouncer is down):
  psql -h <primary-direct-ip> -p 5432 -U postgres \
    -c "ALTER SYSTEM SET synchronous_commit = 'remote_write';"
  psql -h <primary-direct-ip> -p 5432 -U postgres \
    -c "SELECT pg_reload_conf();"

  # Verify:
  psql -h <primary-direct-ip> -c "SHOW synchronous_commit;"
  # Expected: remote_write

  EFFECT: Write latency drops from 340ms to ~3ms.
  Connections holding transactions for 340ms now release
  in 3ms → connection pool pressure drops ~100x.

  WHY SECOND: Even if we restore PgBouncer, writes at
  340ms will re-saturate the pool within seconds. The
  write bottleneck must be relieved BEFORE restoring
  connection pooling.

  VERIFY:
  psql -h <primary-direct-ip> -c \
    "SELECT avg(total_exec_time/calls)
     FROM pg_stat_statements
     WHERE query LIKE '%INSERT%'
     AND calls > 100;"
  # Should show ~3-5ms, not 340ms.
```

### Minute 1-3: Restore Connection Infrastructure

```
ACTION 3: RESTART PgBouncer ON PRIMARY [1:00 — 45 seconds]

  systemctl restart pgbouncer
  # or if containerized:
  kubectl rollout restart deployment/pgbouncer-primary -n prod

  # Verify PgBouncer is up and accepting connections:
  psql -h pgbouncer-primary -p 6432 pgbouncer \
    -c "SHOW POOLS;"
  # Should show pools initializing with sv_active < 200

  WHY AFTER ACTION 2: If we restart PgBouncer before
  fixing semi-sync, the 340ms writes will immediately
  re-saturate the 200 connection pool.
  Order matters: fix the bottleneck, THEN restore the
  pooler.

  VERIFY: sv_active < 150, cl_waiting = 0 or minimal.


ACTION 4: REVERT CART READS TO REPLICAS [1:45 — 30 seconds]

  The 12:02:30 hotfix (cart reads to primary) is still
  active. This is STILL dumping read traffic onto the
  primary. Revert it:

  # Feature flag, config change, or deployment revert:
  feature_flag.set("CART_READ_SOURCE", "replica")
  # or revert the config change from 12:02:30

  EFFECT: Primary load drops significantly. The 85/15
  read split resumes. Primary handles only writes +
  15% reads.

  WHY AFTER ACTION 3: PgBouncer must be running before
  we redirect traffic away from direct connections.
  The sequence: PgBouncer up → app servers reconnect
  through PgBouncer → revert cart reads → primary
  load normalizes.

  VERIFY: Primary PgBouncer sv_active drops. Primary
  CPU drops.
```

### Minute 3-5: Restore Read Path

```
ACTION 5: VERIFY AND FIX READ REPLICAS [3:00 — 2 minutes]

  Check replication lag on all three replicas:

  psql -h primary -c "
    SELECT client_addr,
           state,
           replay_lsn,
           (pg_current_wal_lsn() - replay_lsn) AS lag_bytes,
           now() - pg_last_xact_replay_timestamp() AS lag_time
    FROM pg_stat_replication;"

  EXPECTED: replica-1 and replica-3 catching up (lag
  decreasing). Replica-2 still behind (14s from the
  analyst query).

  Kill any remaining long queries on replica-2:
  psql -h replica-2 -c "
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE state = 'active'
      AND query_start < now() - interval '10 seconds'
      AND usename NOT IN ('replication_user', 'postgres');"

  Set hot_standby_feedback = off on replica-2 to prevent
  future recovery conflicts from blocking replication
  (or increase max_standby_streaming_delay):

  psql -h replica-2 -c \
    "ALTER SYSTEM SET max_standby_streaming_delay = '5s';"
  psql -h replica-2 -c "SELECT pg_reload_conf();"

  VERIFY: All three replicas show decreasing lag_time.
  Within 2-3 minutes, lag should return to <100ms.


ACTION 6: VERIFY CART READS ARE WORKING [5:00 — 1 minute]

  With replicas catching up and cart reads back on
  replicas, verify the user-facing issue is resolved:

  → Cart reads should show correct data (lag < 100ms)
  → If residual staleness: implement session sticky
    routing on read replicas (Q2 solution) as a
    non-emergency change
  → Monitor: cache hit rate, read latency, error rate
```

### Minute 5-10: Stabilize and Monitor

```
ACTION 7: RESTORE HEALTH CHECKS [6:00 — 1 minute]

  Now that the system is stable, re-enable liveness
  probes with MORE GENEROUS thresholds:

  kubectl patch deployment app-server -n prod --type=json \
    -p='[{"op":"add","path":"/spec/template/spec/containers/0/livenessProbe","value":{
      "httpGet":{"path":"/health","port":8080},
      "initialDelaySeconds":30,
      "periodSeconds":15,
      "timeoutSeconds":5,
      "failureThreshold":10
    }}]'

  Changes from original:
  → timeout: 500ms → 5s (accommodates temporary spikes)
  → failureThreshold: original → 10 (more tolerant)
  → periodSeconds: check less frequently during recovery

  WHY LAST: Health checks can only be safely re-enabled
  after the system is genuinely healthy. Re-enabling
  too early risks restarting the cascade.

  VERIFY: No pod restarts for 5 consecutive minutes.


ACTION 8: MONITOR CONTINUOUSLY [7:00 — ongoing]

  # Watch key metrics for the next 30 minutes:
  watch -n 5 "psql -h pgbouncer-primary -p 6432 pgbouncer \
    -c 'SHOW POOLS;' | grep -E 'sv_active|cl_waiting'"

  watch -n 5 "psql -h primary -c \"
    SELECT client_addr,
           now() - pg_last_xact_replay_timestamp() AS lag
    FROM pg_stat_replication;\""

  # Key thresholds:
  # → PgBouncer sv_active < 160/200 (20% headroom)
  # → Replication lag < 100ms
  # → Write latency p99 < 20ms
  # → Error rate < 0.1%
  # → No pod restarts

  If any threshold is breached: STOP and investigate
  before making further changes.
```

### Mitigation Timeline Summary

```
╔══════════════════════════════════════════════════════════════╗
║  TIME   │ ACTION                           │ WHY THIS ORDER  ║
╠══════════════════════════════════════════════════════════════╣
║  0:00   │ Stop K8s from killing pods       │ Break feedback  ║
║         │ (disable liveness probe)         │ loop FIRST      ║
╠══════════════════════════════════════════════════════════════╣
║  0:15   │ Switch synchronous_commit to     │ Must fix write  ║
║         │ remote_write                     │ bottleneck      ║
║         │                                  │ BEFORE pooler   ║
╠══════════════════════════════════════════════════════════════╣
║  1:00   │ Restart PgBouncer on primary     │ Pooler needs    ║
║         │                                  │ healthy writes  ║
║         │                                  │ to function     ║
╠══════════════════════════════════════════════════════════════╣
║  1:45   │ Revert cart reads to replicas    │ Reduce primary  ║
║         │                                  │ load after      ║
║         │                                  │ pooler is up    ║
╠══════════════════════════════════════════════════════════════╣
║  3:00   │ Fix read replicas (kill analyst  │ Restore read    ║
║         │ query, tune conflict settings)   │ capacity        ║
╠══════════════════════════════════════════════════════════════╣
║  5:00   │ Verify cart reads working        │ Confirm UX      ║
║         │                                  │ restored        ║
╠══════════════════════════════════════════════════════════════╣
║  6:00   │ Restore health checks with       │ Only after      ║
║         │ generous thresholds              │ system is       ║
║         │                                  │ stable          ║
╠══════════════════════════════════════════════════════════════╣
║  7:00   │ Continuous monitoring            │ Watch for       ║
║         │                                  │ recurrence      ║
╚══════════════════════════════════════════════════════════════╝

ORDER DEPENDENCY CHAIN:
  Action 1 → enables all subsequent actions (pods stop dying)
  Action 2 → must precede Action 3 (writes must be fast
    before pooler can function)
  Action 3 → must precede Action 4 (pooler must be up
    before redirecting traffic through it)
  Action 4 → must precede Action 5 (primary load must
    drop before replica recovery matters for reads)
  Action 7 → must be LAST (system must be healthy before
    health checks can enforce health)
```

---

## Q5: Post-Mortem Architecture Changes

### Change 1: Separate Connection Pools for Reads and Writes

```
WHAT: Configure separate PgBouncer instances (or separate
pools within PgBouncer) for read and write operations
on the primary.

  # pgbouncer.ini on primary:
  [databases]
  primary_writes = host=postgresql-primary port=5432
                   pool_size=120
  primary_reads  = host=postgresql-primary port=5432
                   pool_size=60

  # Application config:
  WRITE_DSN = postgresql://pgbouncer:6432/primary_writes
  READ_DSN  = postgresql://pgbouncer:6432/primary_reads

  120 connections reserved for writes (cannot be
  consumed by reads). 60 connections for the 15% of
  reads that go to primary. Total: 180/200 with
  20 reserved for admin/monitoring.

CASCADE LINK IT BREAKS:
  At 12:02:30, cart reads consumed write connections.
  With separate pools: cart reads can only consume the
  60 read connections. Even if all 60 are consumed,
  the 120 write connections are untouched. Writes
  continue at full speed.

  "Cart reads to primary" hotfix would have been SAFE
  with this architecture — it would saturate the read
  pool (degrading reads) but never affect writes.
```

### Change 2: Dedicated Analytics Replica

```
WHAT: Deploy a separate PostgreSQL replica specifically
for analytical/reporting queries. Remove analyst access
from the three operational replicas entirely.

  Operational replicas (1, 2, 3):
  → Serve application reads only
  → max_standby_streaming_delay = 5s (aggressive)
  → hot_standby_feedback = off
  → No analyst users have access

  Analytics replica (4):
  → Serves analyst queries, dashboards, reports
  → max_standby_streaming_delay = 300s (tolerant)
  → hot_standby_feedback = on (preserves snapshots)
  → Can lag behind significantly — analysts don't
    need real-time data
  → If it falls hours behind: fine. It's isolated.

CASCADE LINK IT BREAKS:
  At 12:01:30, the analyst query on replica-2 caused
  a recovery conflict that spiked replica-2's lag to
  14 seconds. This removed 1/3 of operational read
  capacity during peak traffic.

  With a dedicated analytics replica: the analyst query
  runs on replica-4. Recovery conflicts on replica-4
  don't affect operational replicas 1-3. Even if
  replica-4 falls hours behind, operational read
  capacity is unaffected.
```

### Change 3: Read-Your-Writes at the Application Layer

```
WHAT: Implement the targeted read-your-writes pattern
from Q2 as a PERMANENT application feature, not a
hotfix.

  After ANY write operation, flag the user's session
  for primary reads for a configurable window (default
  3 seconds). Reads within the window go to primary.
  Reads after the window go to replicas.

  This PERMANENTLY prevents the "added item to cart
  but cart shows empty" symptom without ever needing
  to redirect ALL cart reads to the primary.

CASCADE LINK IT BREAKS:
  At 12:02:00, the symptom ("cart shows empty")
  triggered the engineering team's panic response
  (redirect all reads to primary). If read-your-writes
  is built in from the start, this symptom NEVER
  OCCURS. The panic redirect never happens. The
  cascade never starts.

  This is the most critical change because it removes
  the HUMAN DECISION that caused the cascade. The
  system handles consistency correctly by default —
  no one needs to make a high-pressure decision
  about redirecting traffic.
```

### Change 4: Autoscaling PgBouncer with Connection Backpressure

```
WHAT: Configure PgBouncer to reject new connections
with a meaningful error when pool utilization exceeds
a threshold, rather than queuing indefinitely until
it crashes.

  # pgbouncer.ini:
  max_client_conn = 1000     # max client connections
  default_pool_size = 200    # max server connections
  reserve_pool_size = 10     # emergency reserve
  reserve_pool_timeout = 3   # wait 3s before using reserve
  client_idle_timeout = 30   # disconnect idle clients
  query_wait_timeout = 10    # fail if queued > 10s
                             # (instead of infinite wait)

  The key parameter: query_wait_timeout = 10.
  If a client's query can't get a server connection
  within 10 seconds, PgBouncer returns an error instead
  of queuing indefinitely and eventually crashing.

  Application handles the error:
  → Retry with exponential backoff
  → Return 503 to client with Retry-After header
  → Trigger autoscaling alert

CASCADE LINK IT BREAKS:
  At 12:04:00, PgBouncer crashed because queued
  connections grew without bound. With query_wait_timeout,
  excess connections get a clean error after 10 seconds.
  PgBouncer stays healthy. The application can back off
  gracefully instead of crashing the connection pooler.
```

### Change 5: Kubernetes Health Check Circuit Breaker

```
WHAT: Configure health checks with a circuit breaker
pattern — if the DATABASE is degraded, the application
should report "degraded but alive" instead of "dead."

  # Health check endpoint:
  @app.route('/health')
  async def health_check():
      try:
          # Fast check: can we reach PgBouncer?
          await asyncio.wait_for(
              db.execute("SELECT 1"), timeout=2.0
          )
          return Response(status=200, body="healthy")
      except asyncio.TimeoutError:
          # DB is slow but we're not dead
          # Report degraded, not failed
          return Response(status=200, body="degraded",
                         headers={"X-Health": "degraded"})
      except ConnectionRefusedError:
          # DB is truly unreachable
          return Response(status=503, body="unhealthy")

  # Kubernetes config:
  livenessProbe:
    httpGet:
      path: /health
      port: 8080
    timeoutSeconds: 10       # generous timeout
    failureThreshold: 10     # 10 failures before kill
    periodSeconds: 15        # check every 15s

  readinessProbe:
    httpGet:
      path: /ready           # separate endpoint
      port: 8080
    timeoutSeconds: 5
    failureThreshold: 3      # remove from LB faster
    periodSeconds: 5

  CRITICAL DISTINCTION:
  → Liveness probe: "Is the PROCESS alive?" Kill only
    if the process is truly stuck (OOM, deadlock).
    A slow database is NOT a reason to kill the app.
  → Readiness probe: "Can this pod serve traffic?"
    Remove from load balancer if degraded, but DON'T
    restart it.

CASCADE LINK IT BREAKS:
  At 12:03:45, Kubernetes killed pods because the
  500ms health check timeout was exceeded (writes
  at 340ms + queueing). With a 10s timeout and
  failureThreshold=10, Kubernetes tolerates ~150
  seconds of degradation before restarting pods.

  More importantly: the readiness probe removes
  degraded pods from the load balancer WITHOUT
  killing them. No restart → no connection storm →
  PgBouncer doesn't crash.
```

### Change 6: Pre-Sale Load Testing and Capacity Planning

```
WHAT: Load test the flash sale scenario at 2x expected
peak BEFORE the event. Verify the system handles
8,100+ write TPS with:
  → Connection pool headroom > 20%
  → Replication lag < 1 second
  → Semi-sync standby keeping pace
  → No recovery conflicts on replicas

Specific test:
  → Simulate 8,100 write TPS for 30 minutes
  → Simultaneously run long analytical queries on
    replicas (simulate the analyst)
  → Simultaneously redirect cart reads to primary
    (simulate the hotfix)
  → Monitor for cascade indicators:
    → PgBouncer queue depth
    → Semi-sync write latency
    → Replication lag

  If any cascade indicator triggers during the test:
  the architecture cannot handle the flash sale.
  Apply Changes 1-5 before the event.

CASCADE LINK IT BREAKS:
  ALL of them. Load testing under realistic conditions
  reveals cascade risks before they affect production.
  The entire incident could have been discovered and
  prevented in a staging environment.
```

### Post-Mortem Changes Summary

```
╔══════════════════════════════════════════════════════════════╗
║  # │ CHANGE                       │ CASCADE LINK BROKEN      ║
╠══════════════════════════════════════════════════════════════╣
║  1 │ Separate read/write          │ Cart reads can't starve  ║
║    │ connection pools             │ writes                   ║
╠══════════════════════════════════════════════════════════════╣
║  2 │ Dedicated analytics replica  │ Analyst queries can't    ║
║    │                              │ degrade operational      ║
║    │                              │ replicas                 ║
╠══════════════════════════════════════════════════════════════╣
║  3 │ Built-in read-your-writes    │ "Cart empty" symptom     ║
║    │                              │ never occurs → panic     ║
║    │                              │ redirect never happens   ║
╠══════════════════════════════════════════════════════════════╣
║  4 │ PgBouncer backpressure       │ PgBouncer fails cleanly  ║
║    │ (query_wait_timeout)         │ instead of crashing      ║
╠══════════════════════════════════════════════════════════════╣
║  5 │ K8s health check circuit     │ Pods stop being killed   ║
║    │ breaker (liveness vs         │ during DB degradation    ║
║    │ readiness separation)        │                          ║
╠══════════════════════════════════════════════════════════════╣
║  6 │ Pre-sale load testing        │ ALL cascade links        ║
║    │                              │ discovered before        ║
║    │                              │ production               ║
╚══════════════════════════════════════════════════════════════╝

DEFENSE IN DEPTH:
  If Change 3 fails (read-your-writes bug):
    → Change 1 prevents the cascade (separate pools)
  If Change 1 fails (misconfigured pools):
    → Change 4 prevents PgBouncer crash (backpressure)
  If Change 4 fails (PgBouncer crashes anyway):
    → Change 5 prevents pod restart storm (health checks)
  If Change 5 fails (pods restart anyway):
    → Change 6 would have caught this in testing

  No single change is the complete fix. Together,
  they break the cascade at EVERY link in the chain.
```

---

Ready for evaluation. 🎯

---

## Preserved notes from retired Northstar drill

## Ops Sim: Northstar Checkout Replica Lag Hotfix

### Q1 - Layer & root cause

Trigger: flash-sale write TPS increased WAL generation and async replica lag; replica-2 also had a recovery conflict from a long query.

Amplifier: broad hotfix routed all cart reads to the primary, saturating primary PgBouncer. Semi-sync `remote_apply` added write latency while the standby struggled.

### Q2 - Evidence

- Replica lag: r2 at 18s and recovery conflict log.
- Primary pool saturation: `cl_waiting=480`, `sv_idle=0`, PgBouncer too-many-clients log.
- Semi-sync pressure: commit latency 8ms -> 290ms and WAL write p99 44ms.

### Q3 - First 15 minutes

1. Keep writes safe; do not make durability changes first.
2. Remove the broad primary-read hotfix. Route only recent-writer sessions / required LSN reads to primary.
3. Remove replica-2 from read rotation until lag is below threshold.
4. Cancel/report the long query causing recovery conflict.
5. Add cart "updating" state for stale replicas rather than reading everything from primary.
6. Watch primary pool, write latency, replica lag, and cart anomaly rate.

### Q4 - Bad fixes

Routing all cart reads to primary destroys primary write headroom and can cascade into checkout writes/payment capture.

`synchronous_commit=off` can lose acknowledged transactions on crash. It is a durability downgrade and inappropriate without explicit business/DB approval for money/inventory paths.

### Q5 - Capacity / blast radius

```text
620 active clients - 220 server connections = 400 clients waiting
```

Waits increase app latency, trigger retries, and can cause more PgBouncer clients, exhausting app workers and DB connections.

### Q6 - Durable fix

- Return commit LSN/version after writes.
- Recent sessions read from primary or a replica with replay LSN >= required LSN.
- Replica lag-aware load balancing removes lagged replicas automatically.
- Query governance on replicas prevents recovery conflicts during sale windows.
- Separate cart read pools from primary write-critical pools.

Acceptance: under induced 20s lag, confirmed cart writes do not disappear, primary write p99 stays within SLO, and only bounded recent-writer reads hit primary.

### Q7 - Org / runbook

Notify incident commander, checkout owner, DB on-call, payments/inventory owners, support, and sale business owner.

Durability downgrades (`synchronous_commit` changes) require DB lead plus business/risk approval. Pre-authorized actions include removing lagged replicas and canceling long-running replica queries.
