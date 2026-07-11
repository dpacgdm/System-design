# Answer Key - SQL Deep Dive

> Open only after attempting the learner file Ops Sim.

## Ops Sim: Northstar Checkout Lock Queue

### Q1 - Layer & root cause

Primary bottleneck: transaction/lock contention in PostgreSQL, amplified by PgBouncer queueing and retry storms.

CPU is misleading because sessions are waiting on locks or pool slots, not burning CPU. The slow query time comes from waiting before the update can proceed.

### Q2 - Evidence

- `pg_locks waiting` rises to 340.
- Long `idle in transaction` admin session holds inventory locks for 112s.
- Deadlocks and serialization failures spike.
- PgBouncer `cl_waiting=720` with `sv_idle=0` shows app clients queueing for server connections.

### Q3 - First 15 minutes

1. Declare P1 and freeze admin/batch jobs touching inventory.
2. Identify the blocking transaction from `pg_stat_activity` / `pg_locks`.
3. Cancel or terminate the admin transaction if it is confirmed non-critical and pre-authorized.
4. Temporarily reduce checkout concurrency or retries to prevent lock retry amplification.
5. Keep inventory correctness: do not accept orders that cannot atomically reserve stock.
6. Verify lock waits, PgBouncer waiting clients, checkout p99, and oversell counter after each change.

### Q4 - Bad fixes

Lowering isolation can hide serialization failures by allowing anomalies. For limited inventory, correctness dominates; oversells are worse than delay.

Raising PgBouncer pool size may push more concurrent lock contenders into Postgres, increasing deadlocks and memory usage. It does not remove the blocker.

### Q5 - Capacity / blast radius

Potential app sessions:

```text
24 pods x 40 sessions = 960 client-side sessions
PgBouncer server connections = 180
```

Queueing should happen at PgBouncer (`cl_waiting`) rather than Postgres. If apps bypass PgBouncer, Postgres can hit `max_connections`, spend memory per backend, and fail unrelated checkout queries.

### Q6 - Durable fix

- Admin jobs must use small committed batches and never wait on external I/O inside a transaction.
- Add lock timeout and statement timeout for admin paths.
- Keep inventory updates short and indexed by `sku`.
- Use jittered bounded transaction retries.
- Add blocking-lock alerts by relation/application.
- Load test flash sale inventory with the admin job disabled/enforced.

Acceptance: no transaction older than runbook threshold on inventory tables; checkout p99 < 300ms under peak; deadlock/serialization retry budget remains below agreed threshold.

### Q7 - Org / runbook

Notify incident commander, checkout owner, DB on-call, inventory/admin-job owner, auction business owner, and support.

Pre-authorized: kill the identified admin blocker, pause inventory imports, and throttle checkout concurrency. Escalate before weakening inventory isolation or accepting eventual stock reservation.
# Answer Key — SQL Deep Dive

> Open only after attempting the learner file questions.

---

# Incident Deep-Dive: PostgreSQL Black Friday Meltdown

---

## Question 1: All Problems — Root Cause and Evidence

### Problem 1: Hot Row Contention on Inventory Table (The Root Cause of the Cascade)

**Root cause:** The `UPDATE inventory SET stock = stock - 1 WHERE product_id = $1 AND stock > 0` query acquires a **row-level exclusive lock** on the inventory row for that product. On Black Friday, hundreds of concurrent users are attempting to buy the SAME popular products simultaneously. Each UPDATE must acquire the lock, decrement stock, and commit before the next UPDATE can proceed. This serializes all purchases for a given product into a **single-threaded bottleneck**.

**Evidence:**
```
→ pg_stat_statements: UPDATE inventory avg_exec_time: 890ms
  (normally 2ms) — 445x slowdown
→ 34,000 calls in 5 minutes = ~113/sec, all competing
  for locks on the same popular product rows
→ lock_waits: 67 — transactions actively waiting for
  row locks held by other transactions
→ "deadlock detected": 340 errors — circular lock dependencies
  from concurrent inventory + order updates
→ "could not serialize access": concurrent modifications
  to the same rows detected by PostgreSQL
→ This is a TEXTBOOK hot-row problem. 47,000 inventory rows
  but Black Friday traffic concentrates on maybe 50-100
  "doorbuster" products. Those rows become the bottleneck.
```

### Problem 2: Connection Pool Exhaustion (Consequence of Problem 1)

**Root cause:** PgBouncer's pool has 100 connections to PostgreSQL. Each connection is held for the duration of a transaction (transaction pooling mode). Because inventory UPDATE transactions are taking 890ms instead of 2ms, connections are held **445x longer** than normal. The pool drains — all 100 connections are occupied by slow checkout transactions, and new requests queue in PgBouncer's wait queue.

**Evidence:**
```
→ PgBouncer cl_waiting: 847 — 847 application requests
  waiting for a database connection
→ PostgreSQL active connections: 100/100 — pool is fully
  consumed, zero headroom
→ idle_in_transaction: 23 — 23 connections have started
  a transaction but are not actively executing a query
  (likely holding locks while the application does other
  work between queries within the same transaction)
→ Checkout API p99: 4,500ms — most of this latency is
  TIME SPENT WAITING IN PGBOUNCER QUEUE, not actual
  query execution
→ Product listing API: 50ms (still fast) — reads go to
  replicas, which don't compete for the pool to primary,
  OR read queries are fast and release connections quickly

The math:
  Normal: 2ms per checkout transaction → 100 connections
    can handle 50,000 transactions/sec
  Now: 890ms per checkout → 100 connections can handle
    ~112 transactions/sec
  Demand: 34,000 / 300 sec = ~113/sec (barely at capacity)
  But with lock waits, many take 2-5 seconds
    → effective throughput drops below demand
    → queue grows → cl_waiting explodes
```

### Problem 3: Idle-in-Transaction Bloat (Amplifies Problems 1 and 2)

**Root cause:** 23 connections are in "idle in transaction" state — they've begun a `BEGIN` transaction, executed some queries, but haven't yet executed the next query or committed. This typically happens when the application opens a transaction, does a database query, then does **non-database work** (API calls, computation, rendering) before continuing the transaction. In transaction pooling mode, PgBouncer **cannot reclaim these connections** because the transaction is still open.

**Evidence:**
```
→ idle_in_transaction: 23 (out of 100 total connections)
→ 23% of the entire connection pool is HELD but IDLE
→ longest_running_transaction: 45 seconds — at least one
  transaction has been open for 45 seconds without committing
→ This wastes 23 connections that could be serving the
  847 waiting clients
→ These idle transactions may also be HOLDING ROW LOCKS
  on inventory rows, making Problem 1 worse
```

### Problem 4: Replica-3 Replication Lag (Separate Infrastructure Issue)

**Root cause:** Replica-3 has 12.4 seconds of replication lag while replicas 1 and 2 are at 0.1s. This is a separate issue from the primary's lock contention — analyzed in detail in Question 3.

**Evidence:**
```
→ replica-3: 12.4s lag (vs 0.1s for replicas 1 and 2)
→ This means replica-3's data is 12.4 seconds behind
  the primary
→ Any read query routed to replica-3 may return stale data
→ Directly causes the "purchased but doesn't show" complaint
```

### Problem 5: Read-After-Write Inconsistency (User-Facing Symptom)

**Root cause:** Customer places an order (write goes to primary), then immediately views "My Orders" (read may be routed to a replica). If the read hits replica-3 (12.4s behind), the order doesn't appear yet. Even replicas 1-2 at 0.1s lag could cause this in a fast page redirect. Analyzed in detail in Question 4.

**Evidence:**
```
→ "I purchased but my order doesn't show in My Orders page"
→ Writes go to primary, reads to replicas
→ Replica lag means recently written data isn't visible
  on replicas yet
```

### Problem Map

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   Hot Row Contention (Problem 1) ← ROOT CAUSE                ║
║     │                                                        ║
║     ├─► Lock waits (67 transactions waiting)                 ║
║     ├─► Deadlocks (340 in 5 minutes)                         ║
║     ├─► Serialization errors                                 ║
║     │                                                        ║
║     ▼                                                        ║
║   Connection Pool Exhaustion (Problem 2)                     ║
║     │  (transactions hold connections 445x longer)           ║
║     │                                                        ║
║     ├─► cl_waiting: 847                                      ║
║     ├─► Checkout latency: 4,500ms                            ║
║     │                                                        ║
║     ▼                                                        ║
║   Idle-in-Transaction (Problem 3) ← AMPLIFIER                ║
║     │  (23% of pool held by idle transactions)               ║
║     │                                                        ║
║     ▼                                                        ║
║   Effective pool capacity: 77 connections, not 100           ║
║   (makes Problem 2 even worse)                               ║
║                                                              ║
║   ─────────────────────────────────────────────────          ║
║                                                              ║
║   Replica-3 Lag (Problem 4) ← SEPARATE ISSUE                 ║
║     │                                                        ║
║     ▼                                                        ║
║   Read-After-Write Inconsistency (Problem 5)                 ║
║     ("I purchased but don't see my order")                   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 2: Serialization Errors vs Deadlocks — Same or Different?

**These are TWO DIFFERENT problems with different causes and different PostgreSQL mechanisms.**

### "could not serialize access due to concurrent update"

```
This is a SERIALIZATION FAILURE — PostgreSQL's
concurrency control detecting a write-write conflict.

WHAT'S HAPPENING:

  Transaction A (at time T1):
    BEGIN;
    SELECT stock FROM inventory WHERE product_id = 42;
    -- sees stock = 5
    -- application logic: "5 > 0, ok to purchase"
    UPDATE inventory SET stock = stock - 1
      WHERE product_id = 42 AND stock > 0;
    -- waiting to commit...

  Transaction B (at time T1 + 10ms):
    BEGIN;
    SELECT stock FROM inventory WHERE product_id = 42;
    -- ALSO sees stock = 5 (depending on isolation level)
    UPDATE inventory SET stock = stock - 1
      WHERE product_id = 42 AND stock > 0;
    -- CONFLICT: Transaction A already modified this row

  If the isolation level is SERIALIZABLE or REPEATABLE READ:
    PostgreSQL detects that Transaction B's view of the
    data is stale (it read stock=5, but A already changed it).
    PostgreSQL ABORTS Transaction B with:
    "ERROR: could not serialize access due to concurrent update"

  This is PostgreSQL DOING ITS JOB — it's preventing
  a lost update anomaly. This error means the database
  correctly rejected a transaction that would have
  violated isolation guarantees.

  THE APPLICATION MUST RETRY this transaction.
  If it doesn't, the user sees an error.

WHEN IT HAPPENS:
  → Multiple transactions read-then-write the SAME row
  → Under SERIALIZABLE or REPEATABLE READ isolation
  → High concurrency on hot rows (exactly our scenario)
```

### "deadlock detected"

```
This is a DEADLOCK — a circular dependency between
two or more transactions, each waiting for a lock
held by the other.

WHAT'S HAPPENING:

  The checkout process likely does MULTIPLE updates
  within a single transaction:

  Transaction A:
    BEGIN;
    UPDATE inventory SET stock = stock - 1
      WHERE product_id = 42;   ← acquires lock on product 42
    -- now needs to:
    UPDATE inventory SET stock = stock - 1
      WHERE product_id = 99;   ← WAITING for lock on product 99

  Transaction B:
    BEGIN;
    UPDATE inventory SET stock = stock - 1
      WHERE product_id = 99;   ← acquires lock on product 99
    -- now needs to:
    UPDATE inventory SET stock = stock - 1
      WHERE product_id = 42;   ← WAITING for lock on product 42

  ╔══════════════════════════════════════════════════════════════╗
  ║  Transaction A │          │ Transaction B                    ║
  ║  HOLDS: row 42 │──WAITS──►│ HOLDS: row 99                    ║
  ║  WANTS: row 99 │◄──WAITS──│ WANTS: row 42                    ║
  ╚══════════════════════════════════════════════════════════════╝

  CIRCULAR DEPENDENCY. Neither can proceed.

  PostgreSQL detects this (via a wait-for graph) and
  KILLS one of the transactions:
  "ERROR: deadlock detected"

  The killed transaction is rolled back.
  The surviving transaction proceeds.

WHY IT'S HAPPENING IN CHECKOUT:
  → Users buying MULTIPLE items in a single cart
  → Each cart checkout UPDATEs multiple inventory rows
    within a single transaction
  → Two users buying products {42, 99} vs {99, 42}
    acquire locks in DIFFERENT ORDERS
  → Different lock ordering = deadlock risk

THE CLASSIC FIX:
  Always acquire locks in a CONSISTENT ORDER
  (e.g., sorted by product_id).

  If both transactions lock product 42 first, then 99:
    → Transaction A gets 42, then 99 ✓
    → Transaction B waits for 42 (A holds it)
    → No circular dependency — B just waits, no deadlock
```

### Summary: Different Problems, Different Fixes

```


```
╔═════════════════════════════════════════════════════════════════╗
║                       │ SERIALIZATION      │ DEADLOCK           ║
║                       │ ERROR              │                    ║
╠═════════════════════════════════════════════════════════════════╣
║  What                 │ Write-write        │ Circular lock      ║
║                       │ conflict on SAME   │ dependency across  ║
║                       │ row                │ MULTIPLE rows      ║
╠═════════════════════════════════════════════════════════════════╣
║  How many rows        │ ONE row            │ TWO or more rows   ║
║  involved             │ (hot product)      │ (multi-item cart)  ║
╠═════════════════════════════════════════════════════════════════╣
║  PostgreSQL           │ MVCC snapshot      │ Wait-for graph     ║
║  detection mechanism  │ conflict detection │ cycle detection    ║
╠═════════════════════════════════════════════════════════════════╣
║  Isolation level      │ SERIALIZABLE or    │ ANY isolation      ║
║  required             │ REPEATABLE READ    │ level (even READ   ║
║                       │                    │ COMMITTED)         ║
╠═════════════════════════════════════════════════════════════════╣
║  PostgreSQL behavior  │ Aborts the         │ Aborts ONE of the  ║
║                       │ conflicting txn    │ deadlocked txns    ║
╠═════════════════════════════════════════════════════════════════╣
║  Fix                  │ Application-level  │ Consistent lock    ║
║                       │ retry logic OR     │ ordering (sort by  ║
║                       │ SELECT ... FOR     │ product_id before  ║
║                       │ UPDATE to acquire  │ updating)          ║
║                       │ lock upfront       │                    ║
╠═════════════════════════════════════════════════════════════════╣
║  In this incident     │ Two users buying   │ Two users buying   ║
║                       │ the SAME product   │ products {A,B} vs  ║
║                       │ simultaneously     │ {B,A} in different ║
║                       │                    │ orders             ║
╚═════════════════════════════════════════════════════════════════╝
```

---

## Question 3: Why Is Replica-3 at 12.4s While Replicas 1-2 Are at 0.1s?

Replicas 1 and 2 are healthy. Replica-3 is 124x more behind. This is NOT a primary-side issue (if it were, ALL replicas would lag). This is something specific to replica-3.

### Hypothesis 1: Replica-3 Is Processing a Long-Running Read Query (Most Likely)

```
PostgreSQL streaming replication has a conflict:
  → The primary sends WAL (Write-Ahead Log) records
    to replicas
  → Replicas must APPLY these WAL records to stay current
  → BUT: if a replica is executing a long-running
    read query, applying certain WAL records would
    INVALIDATE that query's snapshot

Example:
  1. A reporting query starts on replica-3 at 09:19:
     SELECT product_id, SUM(quantity) FROM orders
     GROUP BY product_id;
     (scanning 2.3M rows — takes 30+ seconds)

  2. While this query runs, the primary sends WAL
     records that UPDATE or DELETE rows in the orders
     table (from checkout transactions)

  3. Replica-3 has two choices:
     a) APPLY the WAL records → kills the running query
        (the rows it's reading are being modified)
     b) DELAY applying WAL records → let the query finish
        but replication falls behind

  4. If hot_standby_feedback = on OR
     max_standby_streaming_delay is set high,
     PostgreSQL chooses option (b):
     → Delays WAL application
     → Replication lag grows
     → Query finishes → replica catches up

EVIDENCE THAT SUPPORTS THIS:
  → Only replica-3 is lagging (query-specific, not systemic)
  → It's Black Friday — someone likely kicked off a
    reporting query ("How are sales going?")
  → 12.4s lag matches a long-running analytical query
    blocking WAL apply
  → Replicas 1-2 have no such query → apply WAL immediately
    → 0.1s lag (normal streaming delay)
```

### Hypothesis 2: Replica-3 Has an I/O or Resource Bottleneck

```
Replica-3 may be on degraded infrastructure:

  → Disk I/O saturation: applying WAL records requires
    writing to disk. If replica-3's disk is slower
    (degraded EBS volume, noisy neighbor on shared storage,
    different instance type), it cannot apply WAL as fast
    as replicas 1-2.

  → CPU saturation: if replica-3 is handling a
    disproportionate share of read traffic (load balancer
    imbalance), its CPU may be consumed by read queries,
    leaving insufficient cycles for WAL application.

  → Network: if replica-3 is in a different availability
    zone with network congestion, WAL streaming could be
    delayed (but 12.4s is too large for pure network delay
    — this is more likely I/O bound).

EVIDENCE THAT SUPPORTS THIS:
  → Only replica-3 affected (infrastructure-specific)
  → Would need to check: iostat, CPU utilization,
    and network throughput on replica-3 specifically
  → If replica-3 has 12 indexes on the inventory table
    and is receiving heavy write WAL from the UPDATE storm,
    index maintenance during WAL replay could be the
    bottleneck (each UPDATE to inventory requires updating
    up to 12 indexes on the replica too)
```

### Which Hypothesis Is More Likely?

```
HYPOTHESIS 1 (long-running query blocking WAL apply)
is more likely because:

  1. The lag is EXACTLY on one replica, not a gradient
     (12.4s vs 0.1s vs 0.1s — binary, not proportional)
  2. I/O degradation would show SOME lag on other replicas
     too (shared infrastructure patterns)
  3. It's Black Friday morning — high probability someone
     ran an ad-hoc analytics query against a replica
  4. The lag magnitude (12.4s) is consistent with a
     large sequential scan being protected by
     max_standby_streaming_delay

TO VERIFY:
  -- On replica-3, check for long-running queries:
  SELECT pid, now() - query_start AS duration, query
  FROM pg_stat_activity
  WHERE state = 'active'
  ORDER BY duration DESC
  LIMIT 5;
```

---

## Question 4: "I Purchased but My Order Doesn't Show"

This is a **read-after-write consistency violation** caused by replication lag.

### The Exact Sequence

```
STEP 1: Customer clicks "Place Order"
  → Application sends INSERT to PostgreSQL PRIMARY:
    INSERT INTO orders (user_id, product_id, quantity, ...)
    VALUES (12345, 42, 1, ...);
  → PRIMARY commits the transaction
  → Returns HTTP 200 to the customer: "Order confirmed!"
  → Customer sees: "Thank you for your purchase!"

STEP 2: Customer clicks "My Orders" (1-2 seconds later)
  → Application sends SELECT to a READ REPLICA:
    SELECT * FROM orders WHERE user_id = 12345
    ORDER BY created_at DESC;
  → Load balancer routes this read to... replica-3

STEP 3: Replica-3 is 12.4 seconds behind
  → Replica-3's orders table does NOT YET contain the
    row inserted 1-2 seconds ago
  → The WAL record for that INSERT hasn't been applied yet
  → Query returns the user's PREVIOUS orders but NOT
    the one they just placed
  → Customer sees their old orders. New order is missing.

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   TIME    PRIMARY          REPLICA-3                         ║
  ║   ─────   ────────         ─────────                         ║
  ║   T+0s    INSERT order     (12.4s behind)                    ║
  ║           ✓ committed      doesn't have it yet               ║
  ║                                                              ║
  ║   T+1s    "Order confirmed"                                  ║
  ║           shown to user                                      ║
  ║                                                              ║
  ║   T+2s                     SELECT * FROM orders              ║
  ║                            → order NOT FOUND ✗               ║
  ║                                                              ║
  ║   T+12.4s                  WAL applied,                      ║
  ║                            order now visible                 ║
  ║                            (but user already                 ║
  ║                             saw the empty page)              ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝
```

### Why This Happens Even With Replicas 1-2 at 0.1s Lag

```
Even 0.1 seconds (100ms) of lag can cause this.

If the user's browser redirects from the checkout
confirmation page to "My Orders" in under 100ms
(which is possible with a client-side redirect or
a fast 302 response), the read can hit a replica
that hasn't received the INSERT yet.

With replica-3's 12.4s lag, the window is enormous —
the user would need to wait 12+ seconds before their
order appears. But even replicas 1-2 at 0.1s can
cause the issue for fast redirects.

This is a FUNDAMENTAL challenge of read-replica
architectures: writes and reads go to different
servers, and those servers are not perfectly synchronized.
```

### The Correct Pattern: Read-Your-Writes Consistency

```
After a WRITE operation, subsequent READS from the
SAME user session should be routed to the PRIMARY
(or a replica known to be caught up) for a brief window.

Implementation options:

  1. SESSION AFFINITY TO PRIMARY AFTER WRITE
     After a write, set a flag in the user's session:
       session['read_from_primary_until'] = now() + 15s
     For the next 15 seconds, route that user's reads
     to primary instead of replicas.

  2. CAUSAL CONSISTENCY WITH LSN TRACKING
     After a write, record the WAL LSN (Log Sequence Number):
       write_lsn = pg_current_wal_lsn()
     Before a read on a replica, check:
       IF replica_lsn < write_lsn → route to primary
       ELSE → replica is caught up, safe to read

  3. SYNCHRONOUS REPLICATION (expensive)
     Configure one replica as synchronous — the primary
     won't confirm a commit until the replica has it.
     Guarantees zero lag on that replica but adds
     write latency.
```

---

## Question 5: Prioritized Mitigation Plan

### Sequencing Principle: One Change → Verify → Next Change

```
PRIORITY ORDER:
  1. Kill idle-in-transaction sessions (free pool capacity)
  2. Fix the deadlock lock ordering (stop error bleeding)
  3. Address hot-row contention (root cause)
  4. Fix replica-3 lag (data consistency)
  5. Scale connection pool if needed (capacity)
```

### Step 1: Kill Idle-in-Transaction Sessions (Minute 0-2)

```sql
-- RATIONALE: 23 connections are idle in transaction,
-- wasting 23% of the pool. Killing them immediately
-- frees connections for the 847 waiting clients.
-- This is the FASTEST way to relieve pressure.

-- First, identify them:
SELECT pid, now() - xact_start AS xact_duration,
       now() - state_change AS idle_duration,
       query, usename, application_name
FROM pg_stat_activity
WHERE state = 'idle in transaction'
ORDER BY xact_duration DESC;

-- Kill the longest-running idle transactions first:
-- (45-second transaction is definitely stuck or abandoned)
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle in transaction'
AND now() - xact_start > interval '10 seconds';

-- VERIFY:
-- cl_waiting should drop (freed connections serve waiters)
-- idle_in_transaction count should drop to near 0
-- Check PgBouncer stats:
-- psql -p 6432 pgbouncer -c "SHOW POOLS;"
```

```bash
# PREVENT RECURRENCE: Set idle-in-transaction timeout
# so PostgreSQL automatically kills stale transactions

psql -c "ALTER SYSTEM SET idle_in_transaction_session_timeout = '5s';"
psql -c "SELECT pg_reload_conf();"

# Any transaction idle for >5 seconds will be auto-terminated.
# This is safe for transaction pooling — PgBouncer transactions
# should be short-lived by design.
```

**VERIFY before proceeding:**
```
→ idle_in_transaction dropped from 23 to <5
→ cl_waiting dropping (check every 10 seconds)
→ No new application errors from the kills
  (or acceptable retry-able errors)
```

### Step 2: Fix Deadlock Lock Ordering (Minute 2-5)

```python
# The deadlocks are caused by multi-item cart checkouts
# acquiring inventory locks in ARBITRARY order.
# Fix: sort items by product_id before updating.

# ✗ BEFORE (in checkout service):
async def checkout(cart_items):
    async with db.transaction():
        for item in cart_items:  # arbitrary order
            await db.execute(
                "UPDATE inventory SET stock = stock - 1 "
                "WHERE product_id = $1 AND stock > 0",
                item.product_id
            )
            await db.execute(
                "INSERT INTO orders (...) VALUES (...)"
            )

# ✓ AFTER:
async def checkout(cart_items):
    # Sort by product_id to ensure consistent lock ordering
    sorted_items = sorted(cart_items, key=lambda x: x.product_id)
    async with db.transaction():
        for item in sorted_items:  # DETERMINISTIC order
            await db.execute(
                "UPDATE inventory SET stock = stock - 1 "
                "WHERE product_id = $1 AND stock > 0",
                item.product_id
            )
            await db.execute(
                "INSERT INTO orders (...) VALUES (...)"
            )
```

```bash
# Deploy this fix:
kubectl rollout restart deployment/checkout-service

# VERIFY:
# → Deadlock count should drop to 0 within 1-2 minutes
# → Monitor: SELECT deadlocks FROM pg_stat_database
#   WHERE datname = 'ecommerce';
# → Sentry deadlock errors should stop
```

**VERIFY before proceeding:**
```
→ Deadlock errors stopped in Sentry
→ No new deadlock entries in pg_stat_database
→ Checkout service pods healthy after restart
```

### Step 3: Address Hot-Row Contention (Minute 5-10)

The sorted lock ordering from Step 2 eliminates deadlocks, but the fundamental problem remains: hundreds of transactions serializing on the same inventory row. The UPDATE takes 890ms because of **lock wait time**, not query complexity.

```sql
-- IMMEDIATE: Use SELECT ... FOR UPDATE SKIP LOCKED
-- to avoid waiting on locked rows.
-- Instead of blocking, transactions that can't get
-- the lock immediately SKIP and fail fast.

-- But this changes application semantics (user gets
-- "out of stock" when stock exists but is locked).
-- NOT IDEAL for Black Friday.

-- BETTER IMMEDIATE FIX: Use advisory locks with retry
-- to reduce the lock hold time window.
```

```python
# BEST IMMEDIATE FIX: Minimize transaction scope.
# The checkout transaction likely does TOO MUCH in one txn.
#
# Instead of one long transaction:
#   BEGIN → check inventory → update inventory →
#   create order → create payment → COMMIT
#
# Split into smaller transactions:

async def checkout_optimized(cart_items):
    sorted_items = sorted(cart_items, key=lambda x: x.product_id)

    # TRANSACTION 1: Reserve inventory (FAST — just the UPDATE)
    async with db.transaction():
        for item in sorted_items:
            result = await db.execute(
                "UPDATE inventory SET stock = stock - 1 "
                "WHERE product_id = $1 AND stock > 0 "
                "RETURNING product_id",
                item.product_id
            )
            if not result:
                raise OutOfStockError(item.product_id)
    # ← Lock released HERE, as soon as inventory is decremented

    # TRANSACTION 2: Create order (no inventory lock held)
    async with db.transaction():
        order = await db.execute(
            "INSERT INTO orders (...) VALUES (...) RETURNING id",
            ...
        )

    # Transaction 1 held the hot row lock for ~2ms (just the UPDATE)
    # instead of 890ms (entire checkout flow)
```

```bash
# Deploy the optimized checkout:
kubectl set env deployment/checkout-service CHECKOUT_V2=true
# (or deploy via normal CI/CD)

# VERIFY:
# → UPDATE inventory avg_exec_time should drop from 890ms
#   toward 2-10ms
# → lock_waits should drop dramatically
# → cl_waiting should approach 0
# → Serialization errors should reduce

# Check pg_stat_statements:
psql -c "SELECT mean_exec_time, calls
         FROM pg_stat_statements
         WHERE query LIKE 'UPDATE inventory%';"
```

**VERIFY before proceeding:**
```
→ Inventory UPDATE avg_exec_time < 50ms
→ lock_waits < 10
→ cl_waiting < 50 (and declining)
→ Checkout p99 latency declining toward target
```

### Step 4: Fix Replica-3 Lag (Minute 10-12)

```sql
-- Check if a long-running query is blocking WAL apply:
-- (run on replica-3)

SELECT pid, now() - query_start AS duration,
       state, query
FROM pg_stat_activity
WHERE state = 'active'
AND now() - query_start > interval '10 seconds'
ORDER BY duration DESC;

-- If a long-running analytics query is found:
-- OPTION A: Cancel it
SELECT pg_cancel_backend(<pid>);

-- OPTION B: If it doesn't cancel, terminate it
SELECT pg_terminate_backend(<pid>);
```

```bash
# VERIFY:
# → Replica lag should drop rapidly after the blocking
#   query is killed
# → Monitor: SELECT now() - pg_last_xact_replay_timestamp()
#   AS lag FROM replica-3;
# → Should converge to ~0.1s within seconds

# PREVENT RECURRENCE:
psql -h replica-3 -c "ALTER SYSTEM SET max_standby_streaming_delay = '5s';"
psql -h replica-3 -c "SELECT pg_reload_conf();"
# This limits how long a query can block WAL apply to 5 seconds.
# Queries running longer than 5s on the replica will be
# CANCELLED to allow replication to proceed.
# Replication health > query completion.
```

**ALSO: Fix the read-after-write issue for checkout:**

```python
# In the My Orders endpoint, route to primary after checkout:

async def get_my_orders(request):
    # Check if user recently placed an order
    read_primary_until = request.session.get('read_primary_until')

    if read_primary_until and time.time() < read_primary_until:
        # User just checked out — read from primary
        db = get_primary_connection()
    else:
        # Normal read — use replica
        db = get_replica_connection()

    return await db.fetch(
        "SELECT * FROM orders WHERE user_id = $1 "
        "ORDER BY created_at DESC",
        request.user.id
    )

# In the checkout endpoint, set the flag:
async def checkout(request):
    # ... process checkout ...
    request.session['read_primary_until'] = time.time() + 15
    return {"status": "success"}
```

**VERIFY:**
```
→ Replica-3 lag < 1s
→ "Order doesn't show" complaints stop
→ My Orders page shows correct data immediately after checkout
```

### Step 5: Scale Pool If Needed (Minute 12-15)

```bash
# If cl_waiting is still elevated after Steps 1-3,
# consider temporarily increasing the PgBouncer pool:

# Edit PgBouncer config:
# default_pool_size = 150  (up from 100)
#
# BUT: Check PostgreSQL max_connections first:
psql -c "SHOW max_connections;"
# PostgreSQL default is often 100. If PgBouncer pool >
# max_connections, connections will be rejected at PG level.
# May need: ALTER SYSTEM SET max_connections = 200;
# (requires restart)

# SAFER OPTION: Reduce pool need by reducing transaction duration
# (already done in Step 3). If Step 3 is effective,
# this step should be unnecessary.

# VERIFY:
# → cl_waiting = 0 (no clients waiting)
# → Checkout p99 latency < 500ms
# → Deadlocks = 0
# → Serialization errors = occasional (expected under
#   high concurrency, application retries handle them)
```

### Mitigation Timeline Summary

```
╔══════════════════════════════════════════════════════════════╗
║  MINUTE   │ ACTION                                           ║
╠══════════════════════════════════════════════════════════════╣
║  0-2      │ Kill idle-in-transaction (free 23 conns)         ║
║           │ Set idle_in_transaction_session_timeout = 5s     ║
║           │ VERIFY: cl_waiting dropping                      ║
╠══════════════════════════════════════════════════════════════╣
║  2-5      │ Deploy sorted lock ordering (stop deadlocks)     ║
║           │ VERIFY: deadlock count = 0                       ║
╠══════════════════════════════════════════════════════════════╣
║  5-10     │ Deploy minimized transaction scope               ║
║           │ (reduce lock hold time from 890ms to ~2ms)       ║
║           │ VERIFY: UPDATE exec time < 50ms, lock_waits↓     ║
╠══════════════════════════════════════════════════════════════╣
║  10-12    │ Kill blocking query on replica-3                 ║
║           │ Set max_standby_streaming_delay = 5s             ║
║           │ Deploy read-after-write routing                  ║
║           │ VERIFY: replica lag < 1s, complaints stop        ║
╠══════════════════════════════════════════════════════════════╣
║  12-15    │ Assess: is pool scaling needed?                  ║
║           │ If cl_waiting > 0, increase pool                 ║
║           │ VERIFY: all metrics nominal                      ║
╠══════════════════════════════════════════════════════════════╣
║  15+      │ Monitor for stability                            ║
║           │ Write post-incident review                       ║
╚══════════════════════════════════════════════════════════════╝

PRINCIPLE FOLLOWED:
  Step 1 → VERIFY → Step 2 → VERIFY → Step 3 → VERIFY...
  One change at a time. Never stack changes.
  If something breaks, you know exactly which change caused it.
```


---

---

### SRE Scenario Answers

---

#### Q1: The 10-Link Cascade

The meltdown is a classic multi-layered system cascade where an unthrottled batch database operation triggers memory, network, and lock exhaustion across independent physical layers.

```text
THE 10-LINK CASCADING FAILURE CHAIN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[02:00:05] Trigger: Unbatched Batch UPDATE
The reconciliation script issues an un-chunked UPDATE matching 45 million rows.
                   │
                   ▼
Link 1: Random Heap Seeks
The query uses a secondary B-Tree index on status, generating 45 million random
heap seeks across the 8TB on-disk table partition.
                   │
                   ▼
Link 2: Buffer Pool Thrashing (The Read Cliff)
shared_buffers (512GB) is overwhelmed by the influx of cold historical pages.
The Clock-Sweep algorithm evicts hot pages (e.g., indexes for active API traffic).
PROOF: buffers_backend spikes to 450,000/min.
                   │
                   ▼
Link 3: API Latency Explosion (GET /tx/123) [02:01:30]
Point-lookups previously cached in RAM (12ms) now require 3 physical disk reads
to traverse the B-Tree. API read latency spikes to 1,400ms.
                   │
                   ▼
Link 4: EBS Network Saturation (The Redis Red Herring) [02:02:00]
EBS volumes are network-attached. The massive page-fault I/O (reads) combined
with the WAL write stream (writes) saturates the EC2 instance's ENI bandwidth.
TCP packets to Redis are dropped. The Redis timeout alert is a false symptom.
                   │
                   ▼
Link 5: Full Page Writes (FPW) WAL Storm [02:03:00]
Because a checkpoint just finished, the first update to any page triggers an
8KB FPW in the WAL. WAL volume spikes 15x to 1.2GB/s, saturating NVMe bandwidth.
                   │
                   ▼
Link 6: Physical Replication Lag Spike
The single-threaded replica-1 WAL receiver cannot apply 1.2GB/s of incoming WAL
to its local disk fast enough. Lag spikes to 45 seconds and diverges.
                   │
                   ▼
Link 7: Right-Growing Index Latch Contention [02:04:30]
The BIGSERIAL Primary Key forces all concurrent INSERTS to target the exact same
rightmost leaf page. Because commits are stalled waiting for disk I/O, threads
hold the X-Latch on this page. 280 threads block on LWLock: buffer_content.
                   │
                   ▼
Link 8: PgBouncer Connection Exhaustion [02:06:00]
Api queries taking 1,400ms instead of 12ms hold connections 116x longer.
The 300 server connections are saturated. 2,400 clients queue up.
                   │
                   ▼
Link 9: API Gateway Timeouts (503 Meltdown)
Upstream timeouts are breached. The platform fails entirely.
```

---

### Q2: The WAL Spike Math

```text
The cron job modified a 15-byte status column and a timestamp, but WAL generated 1.2GB/s.
The physical cause is the interaction between the 02:00:00 Checkpoint and Full Page Writes (FPW).

MATHEMATICAL PROOF OF WAL AMPLIFICATION:

1.  A checkpoint completed at 02:00:00. This synced all dirty buffers in RAM to disk
    and advanced the REDO pointer.
2.  Postgres must protect against "Torn Pages" (where the OS writes in 4KB blocks but
    Postgres writes in 8KB pages; a crash mid-write corrupts the page).
3.  The rule: The first write to an 8KB page after a checkpoint writes the ENTIRE
    8KB page image (FPW) to the WAL, rather than just the 15-byte delta.
4.  Because the 45 million updated rows are scattered randomly across the 8TB table,
    almost every row modification occurs on a unique 8KB page that has not been modified
    since the 02:00:00 checkpoint.

Calculation at 150,000 row updates/sec:

  Standard delta WAL record size  ≈ 150 bytes (headers + data)
  Full Page Write (FPW) size      = 8192 bytes (8KB)

  Expected WAL without FPW:
    150,000 updates/sec × 150 bytes = 22.5 MB/sec

  Actual WAL with FPW:
    150,000 updates/sec × 8192 bytes = 1,228.8 MB/sec (≈ 1.2 GB/sec)

This represents an I/O amplification factor of 54.6x. The 1.2GB/s write throughput
physically saturates the EBS network pipe, blocking all transactions at COMMIT.
```

---

### Q3: The Latch Contention

```text
The new INSERTS are blocked on `LWLock: buffer_content` (a CPU latch) rather than
directly on disk.

1.  **The Sequential Bottleneck:** The Primary Key of the `transactions` table is a
    `BIGSERIAL` data type. Under high concurrency, every single `INSERT` must be written
    to the exact same physical 8KB leaf page at the far right edge of the B+ Tree.
2.  **Latching vs Locking:** To write to this rightmost leaf page, a thread must acquire
    an exclusive Latch (`X-Latch`) on the buffer in the Buffer Pool. This is a CPU-level
    spinlock, managed as `LWLock: buffer_content` or `BtreeRightmostPage`.
3.  **The I/O Block:** The thread that currently holds the `X-Latch` on the rightmost
    page cannot release it until its insert is completed and written to the WAL Buffer.
    However, the WAL Buffer cannot be flushed because the disk subsystem is 100% saturated
    by the 1.2GB/s FPW storm.
4.  **The Gridlock:** The active thread waits on the NVMe disk. The other 280 threads
    waiting to insert new payments spin on the CPU, waiting for the `X-Latch` to be released.

The physical resource bottleneck (Disk I/O) has transformed into a CPU lock contention
(LWLock) on a single 8192-byte block of RAM because the sequential `BIGSERIAL` primary
key prevents concurrent insertions from being distributed across different pages.
```

---

### Q4: The 4-Hour Mitigation Timeline (The Incident Commander)

#### Minute 0-5: Stop the Bleeding (Stop the I/O Engine)

```bash
## 02:06:30 — Declare P1 Outage. Assume Incident Command.
## 02:07:00 — Identify the rogue PID.
SELECT pid, query_start, query
FROM pg_stat_activity
WHERE query LIKE '%UPDATE transactions_2026_04%';
## Assume PID is 4055.

## 02:07:30 — THE STAKEHOLDER WARNING (The Rollback Penalty):
## Broadcast to the bridge: "I am going to kill the reconciliation cron job (PID 4055).
## However, this transaction has already modified millions of rows.
## Postgres must execute a physical rollback: it must write abort status to pg_xact (CLOG)
## and mark the xmin/xmax headers of the modified heap tuples as invalid.
## This rollback will continue to saturate the NVMe disk I/O.
## Latency will NOT recover immediately. Expect another 15-20 minutes of high I/O wait.
## Do NOT restart the database, as doing so will force crash recovery to replay this
## massive transaction, extending our downtime by hours."

## 02:08:00 — Terminate the backend query gracefully:
SELECT pg_cancel_backend(4055);

## 02:08:10 — Monitor pg_stat_activity. If the query remains stuck in uninterruptible D-state:
SELECT pg_terminate_backend(4055);
```

#### Minute 5-15: Clear the Connection Block

```bash
## 02:10:00 — The query is terminated. The database enters rollback phase.
## The PgBouncer pool is saturated with 2,400 queued clients that have already timed out.
## Flush the PgBouncer pool to drop dead connections and allow fresh traffic to enter
## once the rollback clears.

## Connect to PgBouncer Admin:
psql -h 127.0.0.1 -p 6432 -U pgbouncer pgbouncer

## Force-restart the connection pools:
RELOAD;
PAUSE;
## This blocks incoming clients temporarily while we sever the old server connections.
RESUME;

## VERIFY:
## SHOW POOLS; -> cl_waiting should drop to 0.
```

#### Minute 15-30: Monitor Rollback and Latency Decay

```bash
## 02:15:00 — Monitor the WAL and disk I/O drop as the rollback completes.
## On the database server shell:
iostat -x 1 10 | grep -E 'await|util'
## Wait until %util drops below 50% and await drops below 2ms.

## Monitor the Buffer Pool thrashing recovery:
SELECT buffers_backend FROM pg_stat_bgwriter;
## The rate of incrementing buffers_backend should drop from 450,000/min back to <100/min.

## 02:30:00 — The Buffer Pool is now cold. Latency on GET queries will be elevated (~50ms)
## as pages are pulled back into memory, but checkout writes (INSERTS) should recover to 12ms.
```

#### Hour 1-4: Restore Replication & Complete Recovery

```bash
## 03:00:00 — Replica-1 lag has peaked and must catch up.
## Monitor lag bytes:
SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes
FROM pg_stat_replication;

## If replica-1 is caught on a long-running read query (recovery conflict):
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pg_is_in_recovery() = true;

## 04:00:00 — Declare Full Recovery. Replica lag < 50ms. Latency < 12ms.
## Hand over to Post-Mortem.
```

---

### Q5: Post-Mortem Architecture (The L1/L2/L3 Defense Matrix)

```text
THE DEFENSE MATRIX FOR THE B-TREE MELTDOWN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Failure Mode: Buffer Pool Thrashing (The Read Cliff)
  → L1 (Primary)   : Bounded SQL Chunking with Sleep Windows (Preventative)
  → L2 (Fallback)  : `statement_timeout = '15s'` (Force-kills rogue queries)
  → L3 (Last Line) : SRE Manual Query Termination via `pg_terminate_backend()`

  Failure Mode: LWLock Contention (Right-Growing Index)
  → L1 (Primary)   : Migration of Primary Key to UUIDv7 (Saves latch contention)
  → L2 (Fallback)  : PgBouncer rate-limiting queue
  → L3 (Last Line) : Vertical scaling of CPU cores (allows spinlock resolution)

  Failure Mode: WAL I/O Saturation (FPW Storm)
  → L1 (Primary)   : HOT Updates via Fillfactor Tuning (Bypasses B-Tree writes)
  → L2 (Fallback)  : Dedicated WAL SSD partition (Separates WAL I/O from heap)
  → L3 (Last Line) : On-the-fly provisioned IOPS increase via AWS API
```

#### A) Redesigning the Batch Job (The Chunking Pattern)
We must replace the monolithic `UPDATE` with a strictly bounded, indexed, time-delayed chunking script. This ensures we never modify more than 2,500 rows in a single transaction, keeping the memory footprint within a single page set and allowing Autovacuum to clean up continuously.

```sql
-- The Redesigned, Non-Blocking Reconciliation Pattern
DO $$
DECLARE
  row_count INT;
  batch_limit INT := 2500;
  processed_rows INT := 0;
BEGIN
  LOOP
    -- Step 1: Update a highly bounded, indexed chunk
    WITH batch AS (
      SELECT id FROM transactions_2026_04
      WHERE status = 'settled'
        AND created_at < NOW() - INTERVAL '30 days'
      ORDER BY id -- Forces sequential B-Tree traversal
      LIMIT batch_limit
      FOR UPDATE SKIP LOCKED -- Bypasses blocked rows
    )
    UPDATE transactions_2026_04 t
    SET status = 'reconciled', updated_at = NOW()
    FROM batch
    WHERE t.id = batch.id;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    processed_rows := processed_rows + row_count;

    -- Step 2: Exit loop if no more rows are left to reconcile
    IF row_count = 0 THEN
      EXIT;
    END IF;

    -- Step 3: Sleep to let the bgwriter flush dirty pages
    -- and allow Autovacuum to clean dead tuples
    COMMIT; -- Explicitly commit the chunk to release locks
    PERFORM pg_sleep(0.2); -- 200ms sleep window
  END LOOP;

  RAISE NOTICE 'Reconciliation complete. Total rows processed: %', processed_rows;
END $$;
```

#### B) Fixing the Latch Bottleneck (UUIDv7 Migration)
We must migrate the Primary Key from `BIGSERIAL` to `UUIDv7` to eliminate the `LWLock: buffer_content` right-growing index contention.

```sql
-- 1. Create a custom function to generate time-ordered UUIDv7 in Postgres
CREATE OR REPLACE FUNCTION generate_uuid_v7() RETURNS uuid AS $$
DECLARE
  timestamp_ms bigint;
  uuid_hex text;
BEGIN
  -- Extract millisecond timestamp
  timestamp_ms := (extract(epoch from clock_timestamp()) * 1000)::bigint;
  -- Hex representation of timestamp (48 bits / 12 hex chars)
  uuid_hex := lpad(to_hex(timestamp_ms), 12, '0');
  -- Append version 7 and random entropy bits (80 bits / 20 hex chars)
  uuid_hex := uuid_hex || '7' || substr(to_hex((random()*15)::int), 1, 1) ||
              lpad(to_hex((random()*65535)::int), 4, '0') ||
              lpad(to_hex((random()*4294967295)::bigint), 8, '0') ||
              lpad(to_hex((random()*65535)::int), 4, '0');
  RETURN uuid_hex::uuid;
END;
$$ LANGUAGE plpgsql;

-- 2. Alter the table to use UUIDv7 on future inserts:
ALTER TABLE transactions ALTER COLUMN id SET DEFAULT generate_uuid_v7();
```
*Why this works:* UUIDv7 embeds a millisecond-precision timestamp in the first 48 bits, keeping new inserts clustered in the same general range of the B-Tree (good for Buffer Pool locality). However, the random trailing bits distribute concurrent writes across several adjacent leaf pages rather than the exact same page, eliminating the single-page `X-Latch` bottleneck.

#### C) Enabling HOT Updates (Fillfactor Tuning)
Since the `status` column is updated frequently, we must configure the page fillfactor to leave space for HOT updates.

```sql
## Step 1: Alter the table fillfactor to 85%
ALTER TABLE transactions_2026_04 SET (fillfactor = 85);

## Step 2: Apply the change to existing data CONCURRENTLY
## SRE Warning: This is an extremely I/O intensive operation. It requires
## a full rebuild of the index. If executed during business hours, the concurrent
## sequential scan will saturate the disk and trigger another read cliff.
REINDEX INDEX CONCURRENTLY idx_transactions_status;

## THE CORRECT DEPLOYMENT STRATEGY:
## 1. Verify EBS capacity has been temporarily upgraded to maximum.
## 2. Execute during Sunday low-traffic window (03:00 AM).
## 3. Throttle index replication to standby to prevent standbys from lagging
##    and breaking read scalability.
```

--- END OF FILE Database Storage Internals - B-Trees and Pages.md ---
