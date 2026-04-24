# Week 2, Topic 1: SQL Deep Dive

---

## Step 1: Learning Objectives

```
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Explain each ACID property with a concrete failure      ║
║      scenario showing what happens WITHOUT it                ║
║                                                              ║
║   2. Choose the correct isolation level for a given          ║
║      workload and explain the tradeoff you're making         ║
║                                                              ║
║   3. Look at a slow query and determine which index          ║
║      would fix it, what type (B-tree vs hash vs composite),  ║
║      and why                                                 ║
║                                                              ║
║   4. Explain to an interviewer how a B-tree index works      ║
║      at the data structure level in under 2 minutes          ║
║                                                              ║
║   5. Diagnose common SQL production incidents from           ║
║      metrics alone (lock contention, missing indexes,        ║
║      replication lag, connection pool exhaustion)            ║
║                                                              ║
║   6. Make the SQL vs NoSQL decision for a given system       ║
║      with precise, justified reasoning                       ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Step 2: Core Teaching

### Part A: ACID — What It Actually Means

Most people can recite "Atomicity, Consistency, Isolation, Durability." That's useless. You need to understand what **breaks** when each property is absent.

```
╔══════════════════════════════════════════════════════════════╗
║                         ACID                                 ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   Not just "properties of a transaction."                    ║
║   These are GUARANTEES the database makes to you.            ║
║   Each one protects you from a specific class of failure.    ║
╚══════════════════════════════════════════════════════════════╝
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
  ╔══════════════════════════════════════════════════════════════╗
  ║   Write-Ahead Log (WAL)                                      ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Before ANY data is modified on disk,                       ║
  ║   the database writes the intended                           ║
  ║   change to a sequential log file.                           ║
  ║                                                              ║
  ║   Transaction Start → WAL                                    ║
  ║   Step 1 intent    → WAL                                     ║
  ║   Step 1 execute   → Data file                               ║
  ║   Step 2 intent    → WAL                                     ║
  ║   Step 2 execute   → Data file                               ║
  ║   Transaction End  → WAL (COMMIT)                            ║
  ║                                                              ║
  ║   On crash recovery:                                         ║
  ║   - Scan WAL                                                 ║
  ║   - Find uncommitted transactions                            ║
  ║   - Roll them back                                           ║
  ║   - Find committed but unflushed                             ║
  ║   - Replay them (redo)                                       ║
  ╚══════════════════════════════════════════════════════════════╝

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

  ╔══════════════════════════════════════════════════════════════╗
  ║   Application                                                ║
  ║       │                                                      ║
  ║       │ COMMIT                                               ║
  ║       ▼                                                      ║
  ║   Database Engine                                            ║
  ║       │                                                      ║
  ║       │ Write to WAL (memory)                                ║
  ║       │ fsync WAL to disk                                    ║
  ║       │ ← This is the slow part                              ║
  ║       │                                                      ║
  ║       ▼                                                      ║
  ║   "COMMIT OK" → Application                                  ║
  ║                                                              ║
  ║   The actual data pages may be                               ║
  ║   written to disk LATER                                      ║
  ║   (checkpoint process).                                      ║
  ║   But the WAL on disk is enough                              ║
  ║   to recover.                                                ║
  ╚══════════════════════════════════════════════════════════════╝

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

╭────────────────────┬──────────┬───────────────┬──────────────┬────────────╮
│                    │ Dirty    │ Non-Repeatable│ Phantom      │ Performance│
│                    │ Read     │ Read          │ Read         │            │
├────────────────────┼──────────┼───────────────┼──────────────┼────────────┤
│ READ UNCOMMITTED   │ Possible │ Possible      │ Possible     │ Fastest    │
│ READ COMMITTED     │ Prevented│ Possible      │ Possible     │ Fast       │
│ REPEATABLE READ    │ Prevented│ Prevented     │ Possible*    │ Moderate   │
│ SERIALIZABLE       │ Prevented│ Prevented     │ Prevented    │ Slowest    │
╰────────────────────┴──────────┴───────────────┴──────────────┴────────────╯

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

  ╔══════════════════════════════════════════════════════════════╗
  ║   id: 1, 3, 5, 8, 12                                         ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Row locks protect: 1, 3, 5, 8, 12                          ║
  ║   Gap locks protect: (1,3), (3,5),                           ║
  ║     (5,8), (8,12), (12,+∞)                                   ║
  ║                                                              ║
  ║   Gap lock on (5,8) means no one can                         ║
  ║   INSERT a row with id 6 or 7.                               ║
  ╚══════════════════════════════════════════════════════════════╝

WHO ALLOWS THIS: Everything below SERIALIZABLE.
(Except PostgreSQL REPEATABLE READ, which uses 
 snapshot isolation and prevents phantoms too.)
```

#### What Each Level Is Used For in Practice

```
╭──────────────────────────────────────────────────────────────╮
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
╰──────────────────────────────────────────────────────────────╯

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

╭──────────────────────────────────────────────────────────────╮
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
╰──────────────────────────────────────────────────────────────╯
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

  ╔══════════════════════════════════════════════════════════════╗
  ║   ROOT NODE                                                  ║
  ║   [50 | 100]                                                 ║
  ║   /    |     \                                               ║
  ╚══════════════════════════════════════════════════════════════╝
   /      |       \
  ▼       ▼        ▼
╔══════════════════════════════════════════════════════════════╗
║ INTERN│ │INTERN│ │INTERN                                     ║
║ [20|35│ │[70|85│ │[120|                                      ║
║ / | \ │ │/ | \ │ │ /  \                                      ║
╚══════════════════════════════════════════════════════════════╝
  │         │         │
  ▼         ▼         ▼
╭──────╮ ╭──────╮ ╭──────╮
│LEAF  │→│LEAF  │→│LEAF  │→ ...
│10,15,│ │20,25,│ │35,40,│
│18,19 │ │30,33 │ │42,48 │
╰──────╯ ╰──────╯ ╰──────╯

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

  ╔══════════════════════════════════════════════════════════════╗
  ║   hash("alice") = bucket 3                                   ║
  ║   hash("bob")   = bucket 7                                   ║
  ║   hash("carol") = bucket 1                                   ║
  ║                                                              ║
  ║   Bucket 1: carol → row ptr                                  ║
  ║   Bucket 2: (empty)                                          ║
  ║   Bucket 3: alice → row ptr                                  ║
  ║   ...                                                        ║
  ║   Bucket 7: bob → row ptr                                    ║
  ╚══════════════════════════════════════════════════════════════╝

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
  ╔══════════════════════════════════════════════════════════════╗
  ║  Index Scan using idx_user_status on orders                  ║
  ║    Index Cond: (user_id = 123 AND status = 'pending')        ║
  ║    Rows Removed by Filter: 0                                 ║
  ║    Actual Rows: 47                                           ║
  ║    Actual Time: 0.052..0.341 ms                              ║
  ║    Planning Time: 0.128 ms                                   ║
  ║    Execution Time: 0.389 ms                                  ║
  ╚══════════════════════════════════════════════════════════════╝

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
╭──────────────────────────────────────────────────────────────╮
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
│  ╔══════════════════════════════════════════════════════════════╗
│  ║   │ App (200 │───→│ PgBouncer │───→│ Postgres │              ║
│  ║   │  conns)  │    │ (100 pool)│    │ (100 max)│              ║
│  ╚══════════════════════════════════════════════════════════════╝
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
│  ╔══════════════════════════════════════════════════════════════╗
│  ║   │ Primary  │───WAL──→│ Replica  │                          ║
│  ║   │ (writes) │  stream  │ (reads)  │                         ║
│  ╚══════════════════════════════════════════════════════════════╝
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
╰──────────────────────────────────────────────────────────────╯
```

---

## Step 4: Hands-On Exercises

```
╭──────────────────────────────────────────────────────────────╮
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
╰──────────────────────────────────────────────────────────────╯
```

---

## Step 5: SRE Scenario

```
╔══════════════════════════════════════════════════════════════╗
║   SCENARIO: E-Commerce Platform — Black Friday               ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   You're the on-call SRE for an e-commerce platform.         ║
║   Stack:                                                     ║
║   → PostgreSQL 15, primary + 3 read replicas                 ║
║   → PgBouncer in transaction mode (pool size: 100)           ║
║   → 30 application servers (Django/Python)                   ║
║   → Redis for session cache                                  ║
║                                                              ║
║   Black Friday starts. Traffic 5x normal.                    ║
║   Everything was fine for 20 minutes. Then:                  ║
║                                                              ║
║   ALERT TIMELINE:                                            ║
║                                                              ║
║   09:20 — Checkout API p99 latency: 200ms → 4,500ms          ║
║   09:21 — Product listing API: still fast (50ms p99)         ║
║   09:22 — PgBouncer: cl_waiting = 847                        ║
║           (847 client connections waiting for a DB conn)     ║
║   09:23 — PostgreSQL primary:                                ║
║           active connections: 100/100                        ║
║           idle in transaction: 23                            ║
║           longest running transaction: 45 seconds            ║
║           lock waits: 67                                     ║
║   09:24 — Replica lag: replica-1: 0.1s, replica-2: 0.1s,     ║
║           replica-3: 12.4s                                   ║
║   09:25 — Application logs flooding with:                    ║
║           "ERROR: could not serialize access due to          ║
║            concurrent update"                                ║
║   09:26 — Sentry alert: 340 "deadlock detected" errors       ║
║           in last 5 minutes, all from checkout service       ║
║   09:27 — Customer complaints: "I purchased but my order     ║
║           doesn't show in My Orders page"                    ║
║   09:28 — Monitoring: inventory table has                    ║
║           47,000 rows, 12 indexes                            ║
║           orders table has 2.3M rows, 8 indexes              ║
║           pg_stat_statements top query:                      ║
║             UPDATE inventory SET stock = stock - 1           ║
║             WHERE product_id = $1 AND stock > 0              ║
║             avg_exec_time: 890ms (normally 2ms)              ║
║             calls in last 5 min: 34,000                      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

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
╔══════════════════════════════════════════════════════════════╗
║   READ AFTER THIS LESSON:                                    ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   DDIA Chapter 2: "Data Models and Query Languages"          ║
║   → Pages 27-42 (Relational vs Document model)               ║
║   → Focus on: "Are Document Databases Repeating History?"    ║
║     section — it connects to WHY relational model won        ║
║                                                              ║
║   DDIA Chapter 3: "Storage and Retrieval"                    ║
║   → Pages 69-79 (Hash indexes, SSTables, LSM-trees)          ║
║   → Pages 79-85 (B-Trees — compare with what you learned)    ║
║   → Pages 85-90 (Comparing B-Trees and LSM-Trees)            ║
║   → Skip: Pages 90-104 first pass (OLAP/column stores —      ║
║     we'll cover this with NoSQL)                             ║
║                                                              ║
║   DDIA Chapter 7: "Transactions"                             ║
║   → Pages 223-232 (ACID meaning, single-object ops)          ║
║   → Pages 232-251 (Weak Isolation Levels — this is the       ║
║     BEST explanation of isolation levels ever written.       ║
║     Read CAREFULLY.)                                         ║
║   → Pages 251-266 (Serializability — skim, we'll revisit)    ║
║                                                              ║
║   TOTAL: ~60 pages. Read as reinforcement, not introduction. ║
║   You already know the concepts. The book fills in nuances.  ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Step 7: Key Takeaways

```
╔══════════════════════════════════════════════════════════════╗
║   5 THINGS TO REMEMBER IF YOU FORGET EVERYTHING ELSE         ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. ACID's real complexity lives in ISOLATION.              ║
║      A, C, and D are relatively straightforward.             ║
║      Isolation levels are where you make tradeoffs           ║
║      between correctness and performance.                    ║
║                                                              ║
║   2. MVCC lets readers never block writers.                  ║
║      This is WHY PostgreSQL and modern databases can         ║
║      handle high concurrency. Old versions are kept          ║
║      so concurrent transactions see consistent snapshots.    ║
║                                                              ║
║   3. B-tree indexes: leftmost prefix rule.                   ║
║      Index on (A, B, C) helps queries on A, A+B, A+B+C.      ║
║      NOT B alone, NOT C alone. Column order is critical.     ║
║      Equality columns first, range column last.              ║
║                                                              ║
║   4. The #1 production DB problem is lock contention,        ║
║      not CPU or disk. When latency spikes but resources      ║
║      look fine, check for lock waits and long-running        ║
║      transactions.                                           ║
║                                                              ║
║   5. EXPLAIN ANALYZE is your best friend.                    ║
║      Never guess about query performance. Look at the plan.  ║
║      Seq Scan on large table = missing index. Always.        ║
╚══════════════════════════════════════════════════════════════╝
```

---

Take your time with the SRE scenario. All five questions. This one is designed to test whether you can **apply** everything from today's lesson to a realistic production incident. 🎯


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
    → Transaction A gets 42, then 99 ✅
    → Transaction B waits for 42 (A holds it)
    → No circular dependency — B just waits, no deadlock
```

### Summary: Different Problems, Different Fixes

```


```
╭──────────────────────┬────────────────────┬───────────────────╮
│                      │ SERIALIZATION      │ DEADLOCK          │
│                      │ ERROR              │                   │
├──────────────────────┼────────────────────┼───────────────────┤
│ What                 │ Write-write        │ Circular lock     │
│                      │ conflict on SAME   │ dependency across │
│                      │ row                │ MULTIPLE rows     │
├──────────────────────┼────────────────────┼───────────────────┤
│ How many rows        │ ONE row            │ TWO or more rows  │
│ involved             │ (hot product)      │ (multi-item cart) │
├──────────────────────┼────────────────────┼───────────────────┤
│ PostgreSQL           │ MVCC snapshot      │ Wait-for graph    │
│ detection mechanism  │ conflict detection │ cycle detection   │
├──────────────────────┼────────────────────┼───────────────────┤
│ Isolation level      │ SERIALIZABLE or    │ ANY isolation     │
│ required             │ REPEATABLE READ    │ level (even READ  │
│                      │                    │ COMMITTED)        │
├──────────────────────┼────────────────────┼───────────────────┤
│ PostgreSQL behavior  │ Aborts the         │ Aborts ONE of the │
│                      │ conflicting txn    │ deadlocked txns   │
├──────────────────────┼────────────────────┼───────────────────┤
│ Fix                  │ Application-level  │ Consistent lock   │
│                      │ retry logic OR     │ ordering (sort by │
│                      │ SELECT ... FOR     │ product_id before │
│                      │ UPDATE to acquire  │ updating)         │
│                      │ lock upfront       │                   │
├──────────────────────┼────────────────────┼───────────────────┤
│ In this incident     │ Two users buying   │ Two users buying  │
│                      │ the SAME product   │ products {A,B} vs │
│                      │ simultaneously     │ {B,A} in different│
│                      │                    │ orders            │
╰──────────────────────┴────────────────────┴───────────────────╯
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
  ║           ✅ committed      doesn't have it yet               ║
  ║                                                              ║
  ║   T+1s    "Order confirmed"                                  ║
  ║           shown to user                                      ║
  ║                                                              ║
  ║   T+2s                     SELECT * FROM orders              ║
  ║                            → order NOT FOUND ❌               ║
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

# ❌ BEFORE (in checkout service):
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

# ✅ AFTER:
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
╭──────────┬───────────────────────────────────────────────╮
│ MINUTE   │ ACTION                                        │
├──────────┼───────────────────────────────────────────────┤
│ 0-2      │ Kill idle-in-transaction (free 23 conns)      │
│          │ Set idle_in_transaction_session_timeout = 5s  │
│          │ VERIFY: cl_waiting dropping                   │
├──────────┼───────────────────────────────────────────────┤
│ 2-5      │ Deploy sorted lock ordering (stop deadlocks)  │
│          │ VERIFY: deadlock count = 0                    │
├──────────┼───────────────────────────────────────────────┤
│ 5-10     │ Deploy minimized transaction scope            │
│          │ (reduce lock hold time from 890ms to ~2ms)    │
│          │ VERIFY: UPDATE exec time < 50ms, lock_waits↓  │
├──────────┼───────────────────────────────────────────────┤
│ 10-12    │ Kill blocking query on replica-3              │
│          │ Set max_standby_streaming_delay = 5s          │
│          │ Deploy read-after-write routing               │
│          │ VERIFY: replica lag < 1s, complaints stop     │
├──────────┼───────────────────────────────────────────────┤
│ 12-15    │ Assess: is pool scaling needed?               │
│          │ If cl_waiting > 0, increase pool              │
│          │ VERIFY: all metrics nominal                   │
├──────────┼───────────────────────────────────────────────┤
│ 15+      │ Monitor for stability                         │
│          │ Write post-incident review                    │
╰──────────┴───────────────────────────────────────────────╯

PRINCIPLE FOLLOWED:
  Step 1 → VERIFY → Step 2 → VERIFY → Step 3 → VERIFY...
  One change at a time. Never stack changes.
  If something breaks, you know exactly which change caused it.
```

