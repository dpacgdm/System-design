# Week 2, Topic 1: SQL Deep Dive

---

## Step 1: Learning Objectives

```
┌──────────────────────────────────────────────────────────────┐
│  AFTER THIS TOPIC, YOU WILL BE ABLE TO:                      │
│                                                              │
│  1. Explain each ACID property with a concrete failure       │
│     scenario showing what happens WITHOUT it                 │
│                                                              │
│  2. Choose the correct isolation level for a given           │
│     workload and explain the tradeoff you're making          │
│                                                              │
│  3. Look at a slow query and determine which index           │
│     would fix it, what type (B-tree vs hash vs composite),   │
│     and why                                                  │
│                                                              │
│  4. Explain to an interviewer how a B-tree index works       │
│     at the data structure level in under 2 minutes           │
│                                                              │
│  5. Diagnose common SQL production incidents from            │
│     metrics alone (lock contention, missing indexes,         │
│     replication lag, connection pool exhaustion)             │
│                                                              │
│  6. Make the SQL vs NoSQL decision for a given system        │
│     with precise, justified reasoning                        │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 2: Core Teaching

### Part A: ACID — What It Actually Means

Most people can recite "Atomicity, Consistency, Isolation, Durability." That's useless. You need to understand what **breaks** when each property is absent.

```
┌─────────────────────────────────────────────────────────────┐
│                        ACID                                 │
│                                                             │
│  Not just "properties of a transaction."                    │
│  These are GUARANTEES the database makes to you.            │
│  Each one protects you from a specific class of failure.    │
└─────────────────────────────────────────────────────────────┘
```

#### ATOMICITY — "All or Nothing"

```
WHAT IT MEANS:
  A transaction is an indivisible unit. Either ALL 
  operations in the transaction succeed, or NONE do.
  There is no partial state.

THE CLASSIC EXAMPLE (bank transfer):

  Transaction: Transfer $500 from Account A → Account B
  
  Step 1: UPDATE accounts SET balance = balance - 500 
          WHERE id = 'A';
  Step 2: UPDATE accounts SET balance = balance + 500 
          WHERE id = 'B';

WITHOUT ATOMICITY (what goes wrong):
  
  Step 1 succeeds: A loses $500     ✓
  ─── CRASH / POWER FAILURE ───
  Step 2 never runs: B never gets $500  ✗
  
  Result: $500 vanished from the system.
  A has $500 less. B has nothing more.
  Money literally disappeared.

WITH ATOMICITY:
  
  Step 1 succeeds: A loses $500     ✓
  ─── CRASH / POWER FAILURE ───
  Database recovers → sees incomplete transaction
  → ROLLS BACK Step 1
  → A gets $500 back
  → System is exactly as it was before

HOW IT'S IMPLEMENTED:
  ┌──────────────────────────────────────┐
  │  Write-Ahead Log (WAL)               │
  │                                      │
  │  Before ANY data is modified on disk,│
  │  the database writes the intended    │
  │  change to a sequential log file.    │
  │                                      │
  │  Transaction Start → WAL             │
  │  Step 1 intent    → WAL              │
  │  Step 1 execute   → Data file        │
  │  Step 2 intent    → WAL              │
  │  Step 2 execute   → Data file        │
  │  Transaction End  → WAL (COMMIT)     │
  │                                      │
  │  On crash recovery:                  │
  │  - Scan WAL                          │
  │  - Find uncommitted transactions     │
  │  - Roll them back                    │
  │  - Find committed but unflushed      │
  │  - Replay them (redo)                │
  └──────────────────────────────────────┘

  This is called ARIES recovery protocol in most 
  databases (PostgreSQL, MySQL InnoDB, Oracle).
```

#### CONSISTENCY — The Most Misunderstood Property

```
IMPORTANT: "Consistency" in ACID is NOT the same 
as "consistency" in CAP theorem. Different concept, 
same word. This causes massive confusion.

ACID CONSISTENCY means:
  A transaction moves the database from one VALID state 
  to another VALID state. All constraints, rules, 
  triggers, and invariants are respected.

WHAT ARE "CONSTRAINTS"?
  → Primary key uniqueness
  → Foreign key references  
  → CHECK constraints (e.g., balance >= 0)
  → NOT NULL constraints
  → Custom triggers/rules

EXAMPLE:

  Table: accounts
  Constraint: CHECK (balance >= 0)

  Account A has $300.
  
  Transaction: Withdraw $500 from A.
  
  UPDATE accounts SET balance = balance - 500 
  WHERE id = 'A';
  
  This would make balance = -200.
  That violates CHECK (balance >= 0).
  
  The database REJECTS this transaction entirely.
  Account A stays at $300.

WHY THIS IS THE "WEAKEST" ACID PROPERTY:
  
  Consistency is partially the APPLICATION's 
  responsibility, not just the database's.
  
  The database enforces declared constraints.
  But if you don't declare a constraint, the 
  database can't enforce it.
  
  Example: "Total money across all accounts 
  must remain constant" — the database won't 
  enforce this automatically. You need to 
  design your transactions correctly.

  A + I + D are guaranteed by the DATABASE ENGINE.
  C is a CONTRACT between you and the database.
```

#### ISOLATION — Where the Complexity Lives

```
WHAT IT MEANS:
  Concurrent transactions behave AS IF they executed 
  one at a time (serially), even though they're 
  actually running in parallel.

WHY IT'S HARD:
  You have 1000 transactions running simultaneously.
  They're reading and writing overlapping data.
  Making them TRULY serial would be correct but 
  devastatingly slow.
  
  So databases offer ISOLATION LEVELS — a spectrum 
  of tradeoffs between correctness and performance.

  More isolation = more correct = slower
  Less isolation = less correct = faster

WE'LL GO DEEP ON ISOLATION LEVELS IN A MOMENT.
```

#### DURABILITY — "Committed Means Committed"

```
WHAT IT MEANS:
  Once a transaction is committed, it STAYS committed 
  even if the server crashes, loses power, or catches fire.

HOW IT'S IMPLEMENTED:

  When you get "COMMIT OK" back from the database, 
  that means:
  
  1. The WAL entry for this transaction has been 
     written to DISK (not just memory)
  2. The disk has been fsync'd (forced flush from 
     OS buffer cache to physical disk platters)

  ┌──────────────────────────────────┐
  │  Application                     │
  │      │                           │
  │      │ COMMIT                    │
  │      ▼                           │
  │  Database Engine                 │
  │      │                           │
  │      │ Write to WAL (memory)     │
  │      │ fsync WAL to disk         │
  │      │ ← This is the slow part   │
  │      │                           │
  │      ▼                           │
  │  "COMMIT OK" → Application       │
  │                                  │
  │  The actual data pages may be    │
  │  written to disk LATER           │
  │  (checkpoint process).           │
  │  But the WAL on disk is enough   │
  │  to recover.                     │
  └──────────────────────────────────┘

DURABILITY vs PERFORMANCE TRADEOFF:

  fsync on every commit = durable but slow
  
  Some databases offer "relaxed durability":
  
  PostgreSQL: synchronous_commit = off
    → Returns COMMIT OK before fsync
    → Up to ~600ms of transactions can be lost on crash
    → 2-3x faster writes
    → Used when you can tolerate small data loss
      (e.g., session data, analytics events)
  
  MySQL InnoDB: innodb_flush_log_at_trx_commit
    = 1 → fsync every commit (safe, slow)
    = 2 → write to OS cache, fsync every second (risky)
    = 0 → write to log buffer, fsync every second (fastest, most risky)

PRODUCTION REALITY:
  Most production systems use full durability (setting 1).
  The performance cost is real but acceptable.
  
  If you're losing data on crash because you turned 
  off fsync for performance, you've made a catastrophic 
  engineering decision for most workloads.
  
  EXCEPTION: If the data can be regenerated (cache warm-up 
  data, derived tables) then relaxed durability is fine.
```

---

### Part B: Isolation Levels — The Deep Dive

This is where interviews get hard. You need to understand **what anomalies each level permits** and **why you'd choose each one.**

```
THE FOUR STANDARD ISOLATION LEVELS
(SQL standard, weakest to strongest)

┌────────────────────┬──────────┬───────────────┬──────────────┬────────────┐
│                    │ Dirty    │ Non-Repeatable│ Phantom      │ Performance│
│                    │ Read     │ Read          │ Read         │            │
├────────────────────┼──────────┼───────────────┼──────────────┼────────────┤
│ READ UNCOMMITTED   │ Possible │ Possible      │ Possible     │ Fastest    │
│ READ COMMITTED     │ Prevented│ Possible      │ Possible     │ Fast       │
│ REPEATABLE READ    │ Prevented│ Prevented     │ Possible*    │ Moderate   │
│ SERIALIZABLE       │ Prevented│ Prevented     │ Prevented    │ Slowest    │
└────────────────────┴──────────┴───────────────┴──────────────┴────────────┘

* PostgreSQL's REPEATABLE READ actually prevents phantoms too 
  (it uses Snapshot Isolation, which is stronger than the SQL 
  standard requires). MySQL InnoDB does not — it allows phantoms 
  at REPEATABLE READ unless you use SELECT ... FOR UPDATE.
```

Let me show you each anomaly concretely:

#### Dirty Read

```
Transaction A                    Transaction B
─────────────                    ─────────────
BEGIN;
UPDATE accounts 
SET balance = 200 
WHERE id = 1;
(balance was 1000, 
 now 200 in A's view)
                                 BEGIN;
                                 SELECT balance FROM accounts 
                                 WHERE id = 1;
                                 → Reads 200 ← DIRTY READ
                                 (A hasn't committed yet!)
                                 
                                 Uses this value for a 
                                 business decision...

ROLLBACK;
(balance goes back to 1000)
                                 ...but B acted on 200,
                                 which NEVER EXISTED as 
                                 committed data.

IMPACT: B made a decision based on data that was 
never real. In a financial system, this could mean 
denying a loan because the balance "looked" low.

WHO ALLOWS THIS: Only READ UNCOMMITTED.
Almost nobody uses READ UNCOMMITTED in production.
It exists mostly for bulk read-only analytics where 
approximate data is acceptable.
```

#### Non-Repeatable Read

```
Transaction A                    Transaction B
─────────────                    ─────────────
BEGIN;
SELECT balance FROM accounts 
WHERE id = 1;
→ Reads 1000
                                 BEGIN;
                                 UPDATE accounts 
                                 SET balance = 500 
                                 WHERE id = 1;
                                 COMMIT;

SELECT balance FROM accounts 
WHERE id = 1;
→ Reads 500  ← DIFFERENT VALUE!

Same query, same transaction, different result.

IMPACT: Within a SINGLE transaction, the world changed 
under your feet. If A was calculating something using 
the balance at two points, it got inconsistent values.

Example: Generating a financial report.
  Line 1: "Account balance: $1000" (first read)
  ...calculations...
  Line 47: "Account balance: $500" (second read)
  
  The report contradicts itself.

WHO ALLOWS THIS: READ UNCOMMITTED, READ COMMITTED.
WHO PREVENTS: REPEATABLE READ, SERIALIZABLE.
```

#### Phantom Read

```
Transaction A                    Transaction B
─────────────                    ─────────────
BEGIN;
SELECT COUNT(*) FROM orders 
WHERE status = 'pending';
→ Returns 10
                                 BEGIN;
                                 INSERT INTO orders 
                                 (status) VALUES ('pending');
                                 COMMIT;

SELECT COUNT(*) FROM orders 
WHERE status = 'pending';
→ Returns 11  ← PHANTOM ROW

The difference from non-repeatable read:
  Non-repeatable: an EXISTING row's value changed
  Phantom: a NEW row appeared (or disappeared)

WHY IS THIS DISTINCT?

  Preventing non-repeatable reads means locking 
  the ROWS you've already read.
  
  Preventing phantoms means locking the GAPS — 
  the space where NEW rows could appear.
  
  This is why MySQL InnoDB uses "gap locks" and 
  "next-key locks" at SERIALIZABLE level.

  ┌──────────────────────────────────────────┐
  │  id: 1, 3, 5, 8, 12                      │
  │                                          │
  │  Row locks protect: 1, 3, 5, 8, 12       │
  │  Gap locks protect: (1,3), (3,5),        │
  │    (5,8), (8,12), (12,+∞)                │
  │                                          │
  │  Gap lock on (5,8) means no one can      │
  │  INSERT a row with id 6 or 7.            │
  └──────────────────────────────────────────┘

WHO ALLOWS THIS: Everything below SERIALIZABLE.
(Except PostgreSQL REPEATABLE READ, which uses 
 snapshot isolation and prevents phantoms too.)
```

#### What Each Level Is Used For in Practice

```
┌──────────────────────────────────────────────────────────────┐
│  READ UNCOMMITTED                                            │
│  Use case: Almost never. Maybe bulk analytics on a           │
│  replica where approximate counts are fine.                  │
│  Real-world: "How many rows roughly match this condition?"   │
│  Production frequency: ~1% of workloads                      │
├──────────────────────────────────────────────────────────────┤
│  READ COMMITTED ← DEFAULT in PostgreSQL, Oracle              │
│  Use case: Most OLTP workloads. Web applications.            │
│  Why: Good balance of performance and safety.                │
│  Each statement sees the latest committed data.              │
│  Good enough when transactions are short-lived.              │
│  Production frequency: ~60% of workloads                     │
├──────────────────────────────────────────────────────────────┤
│  REPEATABLE READ ← DEFAULT in MySQL InnoDB                   │
│  Use case: When you need consistent reads within a           │
│  transaction. Report generation. Multi-step calculations.    │
│  Why: Snapshot of data at transaction start.                 │
│  Production frequency: ~30% of workloads                     │
├──────────────────────────────────────────────────────────────┤
│  SERIALIZABLE                                                │
│  Use case: Financial transactions where correctness is       │
│  more important than throughput. Seat booking. Inventory.    │
│  Why: Guarantees transactions behave as if serial.           │
│  Cost: Significant — lock contention, deadlocks, retries.    │
│  Production frequency: ~5% of workloads (critical paths)     │
│  Often used for SPECIFIC transactions, not the whole DB.     │
└──────────────────────────────────────────────────────────────┘

CRITICAL PRODUCTION PATTERN:

  Don't set isolation level globally to SERIALIZABLE.
  
  Set the DEFAULT to READ COMMITTED (PostgreSQL) or 
  REPEATABLE READ (MySQL — it's the default anyway).
  
  Then for SPECIFIC critical transactions:
  
  SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
  BEGIN;
    -- critical financial operation here
  COMMIT;
  
  This gives you performance where it matters and 
  correctness where it matters.
```

#### How Isolation Is Actually Implemented

```
TWO MAIN APPROACHES:

┌──────────────────────────────────────────────────────────────┐
│  1. LOCKING (Pessimistic Concurrency Control)                │
│                                                              │
│  "I'll lock what I'm using so no one else can touch it"      │
│                                                              │
│  Types of locks:                                             │
│  → Shared lock (S): Multiple readers allowed                 │
│  → Exclusive lock (X): Only one writer, blocks everyone      │
│  → Row locks: Lock individual rows                           │
│  → Table locks: Lock entire table (nuclear option)           │
│  → Gap locks: Lock ranges between index values               │
│                                                              │
│  Used heavily by: MySQL InnoDB                               │
│                                                              │
│  Problem: DEADLOCKS                                          │
│                                                              │
│  Transaction A: Locks row 1, wants row 2                     │
│  Transaction B: Locks row 2, wants row 1                     │
│  → Both wait forever → Database detects → kills one          │
│                                                              │
│  Deadlock detection: wait-for graph.                         │
│  If cycle detected → roll back the "cheaper" transaction.    │
├──────────────────────────────────────────────────────────────┤
│  2. MVCC (Multi-Version Concurrency Control)                 │
│                                                              │
│  "I'll keep multiple versions of each row so readers         │
│   and writers don't block each other"                        │
│                                                              │
│  How it works:                                               │
│                                                              │
│  Row: { id: 1, balance: 1000, xmin: 100, xmax: ∞ }           │
│                                                              │
│  Transaction 200 updates balance to 500:                     │
│                                                              │
│  Old: { id: 1, balance: 1000, xmin: 100, xmax: 200 }         │
│  New: { id: 1, balance: 500,  xmin: 200, xmax: ∞ }           │
│                                                              │
│  Transaction 150 (started before 200) reads row 1:           │
│  → Sees xmin:100 (started before me) ✓                       │
│  → Sees xmax:200 (committed after me) → use OLD version      │
│  → Reads balance = 1000                                      │
│                                                              │
│  Transaction 250 (started after 200) reads row 1:            │
│  → Sees the NEW version                                      │
│  → Reads balance = 500                                       │
│                                                              │
│  READERS NEVER BLOCK WRITERS.                                │
│  WRITERS NEVER BLOCK READERS.                                │
│  Only WRITERS block WRITERS (on the same row).               │
│                                                              │
│  Used by: PostgreSQL, Oracle, MySQL InnoDB (hybrid)          │
│                                                              │
│  Tradeoff: Old versions accumulate → need VACUUM             │
│  (PostgreSQL) or purge thread (MySQL) to clean up.           │
└──────────────────────────────────────────────────────────────┘
```

```
MVCC VISUAL:

Timeline ──────────────────────────────────────────►

  Txn 100 starts
  │  Writes row: balance=1000 (xmin=100)
  │
  │  Txn 150 starts
  │  │
  │  │  Txn 200 starts
  │  │  │  Updates row: balance=500 (xmin=200)
  │  │  │  Old version: xmax=200
  │  │  │  COMMITS
  │  │  │
  │  │  Txn 150 reads row
  │  │  → Which version? 
  │  │  → 150 < 200, so Txn 200's changes invisible
  │  │  → Sees balance=1000 ✓ (snapshot consistency)
  │  │
  │  Txn 250 starts
  │     Reads row
  │     → 250 > 200, Txn 200 committed, visible
  │     → Sees balance=500 ✓

This is why PostgreSQL calls REPEATABLE READ 
"Snapshot Isolation" — each transaction gets a 
snapshot of the database as of its start time.
```

---

### Part C: Indexing — How Databases Find Data Fast

This is one of the most practically important topics. Bad indexing is the #1 cause of slow queries in production.

#### B-Tree Index (The Default)

```
WHAT IS A B-TREE?

A self-balancing tree where:
  → Each node can have multiple keys
  → All leaf nodes are at the same depth
  → Leaf nodes are linked (B+ tree, technically)
  → Data is SORTED within the tree

WHY B-TREE AND NOT BINARY TREE?
  
  Binary tree: Each node has 2 children
  → Deep tree → many disk reads to traverse
  
  B-tree: Each node has HUNDREDS of children
  → Shallow tree → few disk reads
  
  Each node is sized to fit one DISK PAGE (typically 
  4KB-16KB). One disk read = one node traversal.
  
  For a table with 1 BILLION rows:
  → Binary tree depth: log₂(1B) ≈ 30 levels
    → 30 disk reads to find one row
  → B-tree depth: log₁₀₀(1B) ≈ 5 levels  
    → 5 disk reads to find one row (with fanout ~100)
    → Root + level 1 often cached in memory
    → So really 2-3 disk reads

B+ TREE STRUCTURE (what databases actually use):

  ┌──────────────────────────────────────┐
  │  ROOT NODE                           │
  │  [50 | 100]                          │
  │  /    |     \                        │
  └─/─────|──────\───────────────────────┘
   /      |       \
  ▼       ▼        ▼
┌──────┐ ┌──────┐ ┌──────┐
│INTERN│ │INTERN│ │INTERN│
│[20|35│ │[70|85│ │[120| │
│/ | \ │ │/ | \ │ │ /  \ │
└──────┘ └──────┘ └──────┘
  │         │         │
  ▼         ▼         ▼
┌──────┐ ┌──────┐ ┌──────┐
│LEAF  │→│LEAF  │→│LEAF  │→ ...
│10,15,│ │20,25,│ │35,40,│
│18,19 │ │30,33 │ │42,48 │
└──────┘ └──────┘ └──────┘

KEY PROPERTIES:
  1. Internal nodes: only keys + pointers to children
  2. Leaf nodes: keys + pointers to actual data rows
  3. Leaf nodes are LINKED (→) for range scans
  4. Data is SORTED — enables efficient range queries

OPERATIONS:
  Point lookup (WHERE id = 42):
    Root → Internal → Leaf → Row pointer
    O(log n) — typically 2-4 disk reads
    
  Range scan (WHERE id BETWEEN 30 AND 50):
    Find 30 via tree traversal
    Then follow leaf node links → 33 → 35 → 40 → 42 → 48 → 50
    Sequential read — very fast
    
  INSERT:
    Find correct leaf → insert in sorted position
    If leaf full → split into two leaves
    May cascade splits up to parent nodes
    
  DELETE:
    Find and remove → may merge underfull nodes
```

#### Hash Index

```
HOW IT WORKS:
  hash(key) → bucket → row pointer
  
  O(1) lookup for exact matches.

WHEN TO USE:
  → Only equality lookups (WHERE id = 42)
  → NEVER for range queries (WHERE id > 30)
    Hash destroys ordering — hash(30) and hash(31) 
    are in completely different buckets

  ┌──────────────────────────────┐
  │  hash("alice") = bucket 3    │
  │  hash("bob")   = bucket 7    │
  │  hash("carol") = bucket 1    │
  │                              │
  │  Bucket 1: carol → row ptr   │
  │  Bucket 2: (empty)           │
  │  Bucket 3: alice → row ptr   │
  │  ...                         │
  │  Bucket 7: bob → row ptr     │
  └──────────────────────────────┘

USED IN:
  → PostgreSQL: CREATE INDEX ... USING HASH
  → In-memory hash tables (Redis, Memcached)
  → Hash joins in query execution

NOT DEFAULT because most real queries need range 
support, ORDER BY support, or prefix matching — 
all impossible with hash indexes.
```

#### Composite Index (Multi-Column)

```
THIS IS WHERE INTERVIEW QUESTIONS LIVE.

CREATE INDEX idx_user_status_date 
ON orders(user_id, status, created_at);

This creates a B-tree sorted by:
  1. user_id (primary sort)
  2. status (secondary sort, within same user_id)
  3. created_at (tertiary sort, within same user_id+status)

IT'S LIKE A PHONE BOOK:
  Sorted by: Last Name → First Name → Middle Name

  You CAN efficiently look up:
  ✓ Last Name = "Smith" 
  ✓ Last Name = "Smith" AND First Name = "John"
  ✓ Last Name = "Smith" AND First Name = "John" AND Middle = "A"
  
  You CANNOT efficiently look up:
  ✗ First Name = "John" (skipped Last Name!)
  ✗ Middle Name = "A" (skipped Last Name AND First Name!)

THIS IS THE "LEFTMOST PREFIX RULE":

  Index on (A, B, C) supports:
  ✓ WHERE A = ?
  ✓ WHERE A = ? AND B = ?
  ✓ WHERE A = ? AND B = ? AND C = ?
  ✓ WHERE A = ? AND B = ? AND C > ?
  ✗ WHERE B = ?          ← Can't skip A
  ✗ WHERE A = ? AND C = ? ← Can't skip B (partially)
  ✗ WHERE C = ?          ← Can't skip A and B
  
  Think of it as: the index is usable for any 
  LEFT PREFIX of the column list.

COLUMN ORDER MATTERS ENORMOUSLY:

  Query: WHERE user_id = 123 AND created_at > '2024-01-01'
  
  Index (user_id, status, created_at):
    → Uses user_id (equality) ✓
    → Cannot skip status to reach created_at ✗
    → Scans ALL statuses for user 123, then filters by date
    → Partially useful
  
  Index (user_id, created_at, status):
    → Uses user_id (equality) ✓
    → Uses created_at (range) ✓
    → Efficiently narrows to exact rows
    → Optimal for this query

DESIGNING COMPOSITE INDEXES:
  
  Rule of thumb:
  1. Equality columns FIRST (WHERE x = ?)
  2. Range column LAST (WHERE y > ?)
  3. Most selective column first among equals
  
  This is called the "EqualityFirst-RangeLast" rule.
```

#### Covering Index

```
A covering index contains ALL columns needed by a query,
so the database never reads the actual table row.

Query: SELECT status, created_at FROM orders 
       WHERE user_id = 123;

Index: (user_id, status, created_at)

The index ITSELF contains user_id, status, and created_at.
The query only needs user_id, status, and created_at.

→ Index-only scan. Never touches the table.
→ MUCH faster (less I/O).

PostgreSQL EXPLAIN shows: "Index Only Scan"
MySQL EXPLAIN shows: "Using index" in Extra column

PRODUCTION TIP:
  If a query is hot (runs thousands of times per second) 
  and you can make it a covering index by adding 1-2 
  columns, DO IT. The extra index size is worth the 
  I/O savings.
  
  PostgreSQL even has INCLUDE syntax for this:
  CREATE INDEX idx ON orders(user_id) 
  INCLUDE (status, created_at);
  
  The INCLUDE columns are in leaf nodes but NOT in 
  the tree structure — so they don't affect sort order 
  but enable index-only scans.
```

#### When Indexes Hurt

```
INDEXES ARE NOT FREE:

  1. WRITE OVERHEAD
     Every INSERT/UPDATE/DELETE must update ALL indexes 
     on that table. 
     
     Table with 10 indexes → every write does 11 
     operations (1 table + 10 indexes).
     
     Write-heavy workload + too many indexes = disaster.

  2. STORAGE
     Each index is a separate B-tree on disk.
     A table with 10 indexes might have indexes that 
     are collectively LARGER than the table itself.

  3. QUERY PLANNER CONFUSION
     Too many indexes → the query planner has too many 
     choices → might pick the wrong one.

PRODUCTION RULES:
  → OLTP (read-heavy): 5-8 indexes per table is typical
  → OLTP (write-heavy): 2-4 indexes, carefully chosen
  → OLAP (analytics): Different strategy entirely 
    (columnar storage, bitmap indexes)
  → Monitor unused indexes and DROP them
    PostgreSQL: pg_stat_user_indexes → idx_scan = 0 means unused
```

---

### Part D: Query Optimization — Reading EXPLAIN

```
Every database has an EXPLAIN command that shows 
HOW the database plans to execute your query.

If you can't read EXPLAIN output, you're guessing 
about performance. Don't guess.

POSTGRESQL EXAMPLE:

  EXPLAIN ANALYZE SELECT * FROM orders 
  WHERE user_id = 123 AND status = 'pending';

  Output:
  ┌─────────────────────────────────────────────────────┐
  │ Index Scan using idx_user_status on orders          │
  │   Index Cond: (user_id = 123 AND status = 'pending')│
  │   Rows Removed by Filter: 0                         │
  │   Actual Rows: 47                                   │
  │   Actual Time: 0.052..0.341 ms                      │
  │   Planning Time: 0.128 ms                           │
  │   Execution Time: 0.389 ms                          │
  └─────────────────────────────────────────────────────┘

  GOOD SIGNS:
  ✓ "Index Scan" or "Index Only Scan"
  ✓ Rows Removed by Filter: 0 (index did all the work)
  ✓ Sub-millisecond execution

  BAD SIGNS:
  ✗ "Seq Scan" on a large table (scanning every row)
  ✗ "Rows Removed by Filter: 999,953" (read 1M rows, kept 47)
  ✗ "Sort" with "Sort Method: external merge Disk"
    (sorting spilled to disk — not enough work_mem)
  ✗ "Nested Loop" with large outer table 
    (O(n×m) join — probably missing an index)

THE MOST COMMON PERFORMANCE KILLERS:

  1. Missing index → Seq Scan on millions of rows
  2. Wrong index chosen → Index exists but planner 
     picks a worse plan (stale statistics → ANALYZE)
  3. N+1 query pattern → Application runs 1000 
     individual queries instead of one JOIN
  4. Implicit type casting → WHERE phone = 1234567890
     on a VARCHAR column → can't use index because 
     it has to cast every row
  5. Function on indexed column → WHERE YEAR(created_at) = 2024
     → Can't use index on created_at
     → Fix: WHERE created_at >= '2024-01-01' AND 
             created_at < '2025-01-01'
```

---

## Step 3: Production Patterns & Failure Modes

```
┌──────────────────────────────────────────────────────────────┐
│  PRODUCTION FAILURE MODE #1: LOCK CONTENTION                 │
│                                                              │
│  Symptom: Query latency spikes. p99 goes from 5ms to 3s.     │
│  But CPU is low. Disk I/O is low. Network is fine.           │
│                                                              │
│  What's happening:                                           │
│  Transactions are WAITING for locks held by other            │
│  transactions. Everyone is blocked, nobody is working.       │
│                                                              │
│  Diagnosis:                                                  │
│  PostgreSQL:                                                 │
│    SELECT * FROM pg_stat_activity                            │
│    WHERE wait_event_type = 'Lock';                           │
│                                                              │
│    SELECT * FROM pg_locks WHERE NOT granted;                 │
│                                                              │
│  MySQL:                                                      │
│    SHOW ENGINE INNODB STATUS;                                │
│    → Look for "LATEST DETECTED DEADLOCK" section             │
│    → Look for "TRANSACTIONS" section with lock waits         │
│                                                              │
│  Common causes:                                              │
│  → Long-running transaction holding locks (forgot COMMIT)    │
│  → Hot row (everyone updating the same counter row)          │
│  → Table-level lock from DDL (ALTER TABLE on big table)      │
│                                                              │
│  Fix:                                                        │
│  → Kill the long-running transaction                         │
│  → Redesign hot row (use per-shard counters, aggregate)      │
│  → Use online DDL tools (pt-online-schema-change, gh-ost)    │
├──────────────────────────────────────────────────────────────┤
│  PRODUCTION FAILURE MODE #2: CONNECTION POOL EXHAUSTION      │
│                                                              │
│  Symptom: Application errors: "too many connections"         │
│  or "connection pool timeout after 30s"                      │
│                                                              │
│  What's happening:                                           │
│  Each database connection consumes ~5-10MB of memory         │
│  on the database server (PostgreSQL forks a process          │
│  per connection).                                            │
│                                                              │
│  PostgreSQL default max_connections = 100                    │
│  20 app servers × 10 connections each = 200 needed           │
│  → Exhausted.                                                │
│                                                              │
│  Fix:                                                        │
│  → Connection pooler: PgBouncer or pgpool                    │
│    Sits between app and database                             │
│    App servers connect to PgBouncer (thousands OK)           │
│    PgBouncer maintains ~100 actual DB connections            │
│    Multiplexes app requests onto shared connections          │
│                                                              │
│  ┌──────────┐    ┌───────────┐    ┌──────────┐               │
│  │ App (200 │───→│ PgBouncer │───→│ Postgres │               │
│  │  conns)  │    │ (100 pool)│    │ (100 max)│               │
│  └──────────┘    └───────────┘    └──────────┘               │
│                                                              │
│  PgBouncer modes:                                            │
│  → Session: 1:1 mapping (doesn't help much)                  │
│  → Transaction: Connection returned to pool after each       │
│    transaction COMMIT (most common, most efficient)          │
│  → Statement: Connection returned after each statement       │
│    (can't use multi-statement transactions)                  │
├──────────────────────────────────────────────────────────b───┤
│  PRODUCTION FAILURE MODE #3: REPLICATION LAG                 │
│                                                              │
│  Symptom: User updates their profile. Refreshes page.        │
│  Sees the OLD profile. Panics. "Where's my update?!"         │
│                                                              │
│  What's happening:                                           │
│  ┌──────────┐         ┌──────────┐                           │
│  │ Primary  │───WAL──→│ Replica  │                           │
│  │ (writes) │  stream  │ (reads)  │                          │
│  └──────────┘         └──────────┘                           │
│                                                              │
│  Write goes to Primary. Read goes to Replica.                │
│  Replica hasn't applied the WAL entry yet.                   │
│  User reads stale data.                                      │
│                                                              │
│  Replication lag: Primary is at WAL position 1000.           │
│  Replica is at WAL position 950. Lag = 50 entries.           │
│                                                              │
│  Solutions:                                                  │
│  1. Read-your-own-writes: After a write, route that          │
│     USER's subsequent reads to Primary for N seconds.        │
│     Everyone else reads from Replica.                        │
│                                                              │
│  2. Synchronous replication: Primary waits for Replica       │
│     to confirm before returning COMMIT OK.                   │
│     → Durable but SLOW (doubles write latency).              │
│     → Use for critical data, async for the rest.             │
│                                                              │
│  3. Causal consistency: Track which WAL position a user      │
│     has written to. Only serve reads from replicas that      │
│     have caught up past that position.                       │
│                                                              │
│  Monitoring:                                                 │
│  PostgreSQL:                                                 │
│    SELECT now() - pg_last_xact_replay_timestamp()            │
│    AS replication_lag;                                       │
│                                                              │
│  MySQL:                                                      │
│    SHOW SLAVE STATUS\G                                       │
│    → Seconds_Behind_Master                                   │
│                                                              │
│  Alert threshold: > 1 second for OLTP workloads.             │
├──────────────────────────────────────────────────────────────┤
│  PRODUCTION FAILURE MODE #4: MISSING INDEX (slow query)      │
│                                                              │
│  Symptom: One specific API endpoint is slow. p50 = 2s.       │
│  Everything else is fine.                                    │
│                                                              │
│  Diagnosis:                                                  │
│  PostgreSQL:                                                 │
│    SELECT query, calls, mean_exec_time, rows                 │
│    FROM pg_stat_statements                                   │
│    ORDER BY mean_exec_time DESC                              │
│    LIMIT 10;                                                 │
│                                                              │
│  MySQL:                                                      │
│    SELECT * FROM performance_schema.events_statements_       │
│    summary_by_digest                                         │
│    ORDER BY AVG_TIMER_WAIT DESC                              │
│    LIMIT 10;                                                 │
│                                                              │
│  Slow query log:                                             │
│    PostgreSQL: log_min_duration_statement = 100              │
│    (log everything taking > 100ms)                           │
│                                                              │
│    MySQL: slow_query_log = 1                                 │
│    long_query_time = 0.1                                     │
│                                                              │
│  Then: EXPLAIN ANALYZE the slow query.                       │
│  Look for Seq Scan on large table → add index.               │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 4: Hands-On Exercises

```
┌──────────────────────────────────────────────────────────────┐
│  EXERCISE 1: See Isolation Levels In Action                  │
│                                                              │
│  Requires: PostgreSQL (install via Docker if needed:         │
│    docker run -p 5432:5432 -e POSTGRES_PASSWORD=test         │
│    postgres:16)                                              │
│                                                              │
│  Open TWO terminal windows, both connected to psql:          │
│    psql -h localhost -U postgres                             │
│                                                              │
│  Setup:                                                      │
│    CREATE TABLE accounts (id INT PRIMARY KEY,                │
│                           balance INT);                      │
│    INSERT INTO accounts VALUES (1, 1000);                    │
│                                                              │
│  Terminal A:                                                 │
│    BEGIN;                                                    │
│    SET TRANSACTION ISOLATION LEVEL READ COMMITTED;           │
│    SELECT balance FROM accounts WHERE id = 1;                │
│    -- Note the value (1000)                                  │
│                                                              │
│  Terminal B:                                                 │
│    UPDATE accounts SET balance = 500 WHERE id = 1;           │
│    -- (auto-commits since no BEGIN)                          │
│                                                              │
│  Terminal A:                                                 │
│    SELECT balance FROM accounts WHERE id = 1;                │
│    -- What do you see? (500 — non-repeatable read!)          │
│    COMMIT;                                                   │
│                                                              │
│  Now repeat with REPEATABLE READ:                            │
│    Reset: UPDATE accounts SET balance = 1000 WHERE id = 1;   │
│                                                              │
│  Terminal A:                                                 │
│    BEGIN;                                                    │
│    SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;          │
│    SELECT balance FROM accounts WHERE id = 1; -- 1000        │
│                                                              │
│  Terminal B:                                                 │
│    UPDATE accounts SET balance = 500 WHERE id = 1;           │
│                                                              │
│  Terminal A:                                                 │
│    SELECT balance FROM accounts WHERE id = 1;                │
│    -- Still 1000! Snapshot isolation in action.              │
│    COMMIT;                                                   │
│                                                              │
│  YOU JUST WITNESSED the difference between                   │
│  READ COMMITTED and REPEATABLE READ with your own eyes.      │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 2: See Index Impact                                │
│                                                              │
│  Create a large table:                                       │
│    CREATE TABLE big_orders AS                                │
│    SELECT generate_series(1, 1000000) AS id,                 │
│           (random()*1000)::int AS user_id,                   │
│           CASE WHEN random() > 0.5                           │
│                THEN 'pending' ELSE 'completed' END           │
│           AS status,                                         │
│           NOW() - (random()*365)::int * INTERVAL '1 day'     │
│           AS created_at;                                     │
│                                                              │
│  WITHOUT index:                                              │
│    EXPLAIN ANALYZE SELECT * FROM big_orders                  │
│    WHERE user_id = 42 AND status = 'pending';                │
│    -- Note: Seq Scan, execution time                         │
│                                                              │
│  ADD index:                                                  │
│    CREATE INDEX idx_user_status                              │
│    ON big_orders(user_id, status);                           │
│                                                              │
│  WITH index:                                                 │
│    EXPLAIN ANALYZE SELECT * FROM big_orders                  │
│    WHERE user_id = 42 AND status = 'pending';                │
│    -- Note: Index Scan, execution time                       │
│    -- Compare the two times. Should be 100-1000x faster.     │
│                                                              │
│  Now try the WRONG column order:                             │
│    EXPLAIN ANALYZE SELECT * FROM big_orders                  │
│    WHERE status = 'pending' AND user_id = 42;                │
│    -- Does the planner still use the index?                  │
│    -- (Yes — the planner is smart enough to reorder          │
│    --  AND conditions to match the index)                    │
│                                                              │
│  Now try SKIPPING the leftmost column:                       │
│    EXPLAIN ANALYZE SELECT * FROM big_orders                  │
│    WHERE status = 'pending';                                 │
│    -- Does it use idx_user_status?                           │
│    -- (No — leftmost prefix rule violated)                   │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 3: See Deadlocks                                   │
│                                                              │
│  Setup:                                                      │
│    CREATE TABLE inventory (id INT PRIMARY KEY,               │
│                            qty INT);                         │
│    INSERT INTO inventory VALUES (1, 100), (2, 200);          │
│                                                              │
│  Terminal A:                                                 │
│    BEGIN;                                                    │
│    UPDATE inventory SET qty = qty - 10 WHERE id = 1;         │
│    -- (holds lock on row 1)                                  │
│                                                              │
│  Terminal B:                                                 │
│    BEGIN;                                                    │
│    UPDATE inventory SET qty = qty - 10 WHERE id = 2;         │
│    -- (holds lock on row 2)                                  │
│                                                              │
│  Terminal A:                                                 │
│    UPDATE inventory SET qty = qty + 10 WHERE id = 2;         │
│    -- (BLOCKS — waiting for B's lock on row 2)               │
│                                                              │
│  Terminal B:                                                 │
│    UPDATE inventory SET qty = qty + 10 WHERE id = 1;         │
│    -- DEADLOCK DETECTED!                                     │
│    -- PostgreSQL kills one transaction with:                 │
│    -- ERROR: deadlock detected                               │
│                                                              │
│  YOU JUST CREATED AND OBSERVED A DEADLOCK.                   │
│  Note which transaction PostgreSQL chose to kill.            │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 5: SRE Scenario

```
┌──────────────────────────────────────────────────────────────┐
│  SCENARIO: E-Commerce Platform — Black Friday                │
│                                                              │
│  You're the on-call SRE for an e-commerce platform.          │
│  Stack:                                                      │
│  → PostgreSQL 15, primary + 3 read replicas                  │
│  → PgBouncer in transaction mode (pool size: 100)            │
│  → 30 application servers (Django/Python)                    │
│  → Redis for session cache                                   │
│                                                              │
│  Black Friday starts. Traffic 5x normal.                     │
│  Everything was fine for 20 minutes. Then:                   │
│                                                              │
│  ALERT TIMELINE:                                             │
│                                                              │
│  09:20 — Checkout API p99 latency: 200ms → 4,500ms           │
│  09:21 — Product listing API: still fast (50ms p99)          │
│  09:22 — PgBouncer: cl_waiting = 847                         │
│          (847 client connections waiting for a DB conn)      │
│  09:23 — PostgreSQL primary:                                 │
│          active connections: 100/100                         │
│          idle in transaction: 23                             │
│          longest running transaction: 45 seconds             │
│          lock waits: 67                                      │
│  09:24 — Replica lag: replica-1: 0.1s, replica-2: 0.1s,      │
│          replica-3: 12.4s                                    │
│  09:25 — Application logs flooding with:                     │
│          "ERROR: could not serialize access due to           │
│           concurrent update"                                 │
│  09:26 — Sentry alert: 340 "deadlock detected" errors        │
│          in last 5 minutes, all from checkout service        │
│  09:27 — Customer complaints: "I purchased but my order      │
│          doesn't show in My Orders page"                     │
│  09:28 — Monitoring: inventory table has                     │
│          47,000 rows, 12 indexes                             │
│          orders table has 2.3M rows, 8 indexes               │
│          pg_stat_statements top query:                       │
│            UPDATE inventory SET stock = stock - 1            │
│            WHERE product_id = $1 AND stock > 0               │
│            avg_exec_time: 890ms (normally 2ms)               │
│            calls in last 5 min: 34,000                       │
│                                                              │
└──────────────────────────────────────────────────────────────┘

QUESTIONS:

Q1: Identify ALL the problems from the alerts above.
    For each, specify the root cause and what evidence 
    points to it.

Q2: The "could not serialize access" errors and the 
    deadlocks — are these the same problem or different 
    problems? Explain precisely what each one means and 
    why they're happening.

Q3: Why is replica-3 lagging at 12.4s while replicas 
    1 and 2 are fine at 0.1s? Give your top 2 hypotheses.

Q4: The customer says "I purchased but my order doesn't 
    show in My Orders." Using ONLY what you learned today, 
    explain the most likely cause.

Q5: Give your prioritized mitigation plan. Exact commands 
    where possible. Remember: one change at a time, verify, 
    then next change.
```

---

## Step 6: Targeted Reading

```
┌──────────────────────────────────────────────────────────────┐
│  READ AFTER THIS LESSON:                                     │
│                                                              │
│  DDIA Chapter 2: "Data Models and Query Languages"           │
│  → Pages 27-42 (Relational vs Document model)                │
│  → Focus on: "Are Document Databases Repeating History?"     │
│    section — it connects to WHY relational model won         │
│                                                              │
│  DDIA Chapter 3: "Storage and Retrieval"                     │
│  → Pages 69-79 (Hash indexes, SSTables, LSM-trees)           │
│  → Pages 79-85 (B-Trees — compare with what you learned)     │
│  → Pages 85-90 (Comparing B-Trees and LSM-Trees)             │
│  → Skip: Pages 90-104 first pass (OLAP/column stores —       │
│    we'll cover this with NoSQL)                              │
│                                                              │
│  DDIA Chapter 7: "Transactions"                              │
│  → Pages 223-232 (ACID meaning, single-object ops)           │
│  → Pages 232-251 (Weak Isolation Levels — this is the        │
│    BEST explanation of isolation levels ever written.        │
│    Read CAREFULLY.)                                          │
│  → Pages 251-266 (Serializability — skim, we'll revisit)     │
│                                                              │
│  TOTAL: ~60 pages. Read as reinforcement, not introduction.  │
│  You already know the concepts. The book fills in nuances.   │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 7: Key Takeaways

```
┌──────────────────────────────────────────────────────────────┐
│  5 THINGS TO REMEMBER IF YOU FORGET EVERYTHING ELSE          │
│                                                              │
│  1. ACID's real complexity lives in ISOLATION.               │
│     A, C, and D are relatively straightforward.              │
│     Isolation levels are where you make tradeoffs            │
│     between correctness and performance.                     │
│                                                              │
│  2. MVCC lets readers never block writers.                   │
│     This is WHY PostgreSQL and modern databases can          │
│     handle high concurrency. Old versions are kept           │
│     so concurrent transactions see consistent snapshots.     │
│                                                              │
│  3. B-tree indexes: leftmost prefix rule.                    │
│     Index on (A, B, C) helps queries on A, A+B, A+B+C.       │
│     NOT B alone, NOT C alone. Column order is critical.      │
│     Equality columns first, range column last.               │
│                                                              │
│  4. The #1 production DB problem is lock contention,         │
│     not CPU or disk. When latency spikes but resources       │
│     look fine, check for lock waits and long-running         │
│     transactions.                                            │
│                                                              │
│  5. EXPLAIN ANALYZE is your best friend.                     │
│     Never guess about query performance. Look at the plan.   │
│     Seq Scan on large table = missing index. Always.         │
└──────────────────────────────────────────────────────────────┘
```

---

Take your time with the SRE scenario. All five questions. This one is designed to test whether you can **apply** everything from today's lesson to a realistic production incident. 🎯
