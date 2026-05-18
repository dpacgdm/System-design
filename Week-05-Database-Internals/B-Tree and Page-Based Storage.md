# Week 5, Topic 3: The B-Tree and Page-Based Storage

Last verified: 2026-05-18

---

## 1. Learning Objectives

```text
+--------------------------------------------------------------------------+
| AFTER THIS TOPIC, YOU WILL BE ABLE TO:                                   |
+--------------------------------------------------------------------------+
|                                                                          |
| 1. Explain why relational databases read and write fixed-size pages,      |
|    not individual rows, and how that creates read/write amplification.    |
|                                                                          |
| 2. Draw the physical layout of a slotted page, including page header,     |
|    line pointers, free space, tuple data, tuple IDs, and dead tuples.     |
|                                                                          |
| 3. Trace a point lookup through a B+Tree from root page to internal page  |
|    to leaf page to heap tuple.                                            |
|                                                                          |
| 4. Explain page splits, right-growing indexes, fillfactor, index bloat,   |
|    HOT updates, visibility maps, and TOAST storage.                       |
|                                                                          |
| 5. Compare B-Trees and LSM-Trees using write amplification, read          |
|    amplification, space amplification, range scans, and operations.       |
|                                                                          |
| 6. Diagnose production incidents involving buffer churn, page splits,     |
|    rightmost-page contention, broken index-only scans, and bloat.         |
|                                                                          |
+--------------------------------------------------------------------------+
```

---

## 2. Core Teaching

# Part A: The Fundamental Lie — Databases Do Not Read Rows

A beginner says the database reads a row.

A storage engine does not read a row.

A storage engine reads a page.

A page is a fixed-size block of storage managed by the database engine. PostgreSQL commonly uses 8KB pages. InnoDB commonly uses 16KB pages. When a query needs one 50-byte row, the storage engine usually brings the entire page containing that row into memory.

```text
LOGICAL VIEW

SELECT * FROM orders WHERE id = 42;

Developer mental model:
  read one row

Physical storage model:
  read the index page path
  read the heap/data page
  inspect tuple visibility
  return the row if visible
```

```text
PHYSICAL VIEW

+------------------+       +------------------+
| B+Tree index page| ----> | Heap/data page   |
| contains key 42  |       | contains row 42  |
+------------------+       +------------------+
                             |
                             v
                       page is 8KB or 16KB
                       row may be 50 bytes
```

This mismatch explains many relational database incidents.

If the application updates a 10-byte status field, the engine may dirty an entire 8KB page.

If a query needs one visible tuple, the engine may still fetch a heap page because the index alone cannot prove visibility.

If rows grow larger after updates, the page may not have room, forcing new versions elsewhere.

If indexes bloat, the engine must traverse and cache more pages for the same logical data.

If the hot working set no longer fits in memory, latency jumps from memory-speed to disk-speed.

Principal SRE rule:

```text
Most database performance mysteries become less mysterious when you ask:

Which pages are being read?
Which pages are being dirtied?
Which pages are hot?
Which pages are bloated?
Which pages are being rewritten?
Which pages are impossible to clean because old transactions still need them?
```

---

# Part B: The Slotted Page

Relational engines need to store variable-length rows. A row may contain integers, timestamps, strings, nullable fields, JSON, arrays, or other variable-length data. If the engine packed rows naively, every update that changed row length could require shifting large regions of the page.

The slotted page solves this with indirection.

The page contains a header at the front, a slot array after the header, free space in the middle, and tuple data packed from the end of the page backward.

```text
THE 8KB SLOTTED PAGE PHYSICAL MEMORY MAP

OFFSET 0                                                         OFFSET 8192
+--------------------------------------------------------------------------+
| PAGE HEADER                                                              |
|                                                                          |
|  pd_lsn       last WAL position affecting this page                      |
|  pd_checksum  page corruption detection                                  |
|  pd_flags     page-level flags                                           |
|  pd_lower     end of line pointer array                                  |
|  pd_upper     start of tuple data                                        |
+--------------------------------------------------------------------------+
| LINE POINTERS / SLOT ARRAY                                               |
|                                                                          |
|  slot 1 -> tuple offset + tuple length + flags                           |
|  slot 2 -> tuple offset + tuple length + flags                           |
|  slot 3 -> tuple offset + tuple length + flags                           |
|  slot 4 -> tuple offset + tuple length + flags                           |
+--------------------------------------------------------------------------+
|                                                                          |
|                         FREE SPACE                                       |
|                                                                          |
|                 pd_upper - pd_lower = free bytes                         |
|                                                                          |
+--------------------------------------------------------------------------+
| tuple 4                                                                  |
+--------------------------------------------------------------------------+
| tuple 3                                                                  |
+--------------------------------------------------------------------------+
| tuple 2                                                                  |
+--------------------------------------------------------------------------+
| tuple 1                                                                  |
+--------------------------------------------------------------------------+

Direction of growth:
  header + line pointers grow downward
  tuple data grows upward
  free space is squeezed in the middle
```

An index usually does not point directly to a byte offset. It points to a tuple identifier.

```text
TID = (page_number, slot_number)

Example:
  TID (42, 3)

Meaning:
  Go to heap page 42.
  Look at slot 3.
  Slot 3 tells where the tuple bytes live inside the page.
```

This indirection is critical. If a tuple moves within the same page because it shrinks or the page is compacted, the slot can be updated while the external TID remains stable.

```text
BEFORE COMPACTION

Index entry key=42 -> TID(page 42, slot 3)
Page 42: slot 3 -> byte offset 7810

AFTER TUPLE BYTES MOVE INSIDE SAME PAGE

Index entry key=42 -> TID(page 42, slot 3)
Page 42: slot 3 -> byte offset 7600

Index did not need to change.
```

This is the first storage-engine lesson: indirection protects indexes from tiny physical rearrangements.

---

# Part C: Tuple Headers and MVCC Clues Inside the Page

Even though full MVCC internals belong in a later topic, page storage cannot be understood without seeing that rows carry visibility metadata.

A tuple is not only user columns. It also contains metadata used to decide whether a transaction can see it.

```text
SIMPLIFIED HEAP TUPLE

+------------------------------------------------------+
| tuple header                                         |
|                                                      |
|  xmin  transaction that created this tuple version   |
|  xmax  transaction that deleted/replaced it          |
|  flags null bitmap / status hints                    |
+------------------------------------------------------+
| user columns                                         |
|                                                      |
|  id                                                  |
|  customer_id                                         |
|  status                                              |
|  amount_cents                                        |
|  created_at                                          |
+------------------------------------------------------+
```

An UPDATE in an MVCC engine usually creates a new tuple version rather than mutating the old tuple in place.

```text
BEFORE UPDATE

slot 1 -> tuple A
          xmin = 100
          xmax = 0
          status = 'pending'

UPDATE status='paid'

AFTER UPDATE

slot 1 -> old tuple A
          xmin = 100
          xmax = 200
          status = 'pending'

slot 2 -> new tuple B
          xmin = 200
          xmax = 0
          status = 'paid'
```

Why keep the old tuple? Because an older transaction may still need to see it.

```text
Transaction T_old started before transaction 200.
T_old may still need status='pending'.

Transaction T_new started after transaction 200 committed.
T_new should see status='paid'.
```

The page now contains multiple versions. Some are live for some snapshots. Some are dead for everyone. Vacuum later reclaims dead space.

SRE implication:

```text
High UPDATE or DELETE rate creates dead tuples.
Dead tuples consume page space.
Page space pressure reduces HOT update probability.
Dead tuples increase table and index bloat.
Long-running transactions prevent cleanup.
```

This is why relational database health is not only about CPU and disk. It is also about version age.

---

# Part D: B+Tree Shape

A B+Tree index is a tree of pages. Internal pages guide the search. Leaf pages contain index entries. Leaf pages are linked to support range scans.

```text
B+TREE WITH DEPTH 3

                              +-------------+
                              | ROOT PAGE   |
                              | keys        |
                              +-------------+
                              /      |      \
                             /       |       \
                            v        v        v
                 +-------------+ +-------------+ +-------------+
                 | INTERNAL A  | | INTERNAL B  | | INTERNAL C  |
                 +-------------+ +-------------+ +-------------+
                  /    |    \      /   |   \       /   |   \
                 v     v     v    v    v    v     v    v    v
              +----+ +----+ +----+ +----+ +----+ +----+ +----+
              | L1 |-| L2 |-| L3 |-| L4 |-| L5 |-| L6 |-| L7 |
              +----+ +----+ +----+ +----+ +----+ +----+ +----+

Leaf pages are linked left-to-right for range scans.
```

Point lookup:

```text
SELECT * FROM orders WHERE id = 42;

1. Read root page.
2. Choose child pointer for key 42.
3. Read internal page.
4. Choose child pointer for key 42.
5. Read leaf page.
6. Find key 42.
7. Get TID for heap row.
8. Read heap page.
9. Check tuple visibility.
10. Return row.
```

Range lookup:

```text
SELECT * FROM orders WHERE id BETWEEN 1000 AND 2000;

1. Traverse tree to first matching leaf.
2. Scan leaf entries sequentially.
3. Follow leaf-page links to next leaves.
4. Fetch heap pages for matching TIDs unless index-only scan is valid.
```

Fanout math:

```text
Assume one 8KB index page holds around 400 key/pointer entries.

Depth 1 root:
  400 keys

Depth 2 root + leaves:
  400 * 400 = 160,000 keys

Depth 3 root + internal + leaves:
  400 * 400 * 400 = 64,000,000 keys

Depth 4:
  25,600,000,000 keys
```

This is why B+Tree lookup depth is small even for huge tables. But small depth does not mean cheap if pages are cold, bloated, contended, or repeatedly split.

---

# Part E: Page Splits

A B+Tree page has finite capacity. When a leaf page is full and a new key must be inserted, the engine splits the page.

```text
BEFORE INSERT

Leaf page contains keys:

+------------------------------------------------+
| 10 | 20 | 30 | 40 | 50 | 60 | 70 | 80 | full |
+------------------------------------------------+

Insert key 55.
```

```text
AFTER SPLIT

Left leaf:
+-----------------------+
| 10 | 20 | 30 | 40     |
+-----------------------+

Right leaf:
+-----------------------+
| 50 | 55 | 60 | 70 | 80|
+-----------------------+

Parent page receives separator key.
```

Page split cost:

```text
1. Allocate or reuse a new page.
2. Move about half of entries.
3. Write both leaf pages.
4. Update parent page.
5. Parent may split too.
6. WAL must describe the changes.
7. Locks/latches must protect the structure during modification.
```

What breaks in production:

```text
INSERTs into random keys cause splits throughout the tree.
INSERTs into sequential keys concentrate writes on the rightmost leaf.
Both patterns can hurt, but in different ways.

Random keys:
  more page splits across many pages
  more cache churn
  more random I/O

Sequential keys:
  strong locality
  but hot rightmost leaf contention under high concurrency
```

The best key pattern depends on workload. UUIDv4 spreads writes widely but destroys locality. BIGSERIAL preserves locality but can create rightmost-page contention. UUIDv7/ULID-style time-ordered identifiers often give a better compromise: mostly increasing with enough entropy to spread concurrent writes across a few hot pages.

---

# Part F: Fillfactor and HOT Updates

Fillfactor controls how full new pages are allowed to become during certain operations.

```text
PAGE WITH fillfactor=100

+------------------------------------------------+
| tuple | tuple | tuple | tuple | tuple | full   |
+------------------------------------------------+

UPDATE creates new tuple version.
No room.
New version must go elsewhere.
Indexes may need new entries.
```

```text
PAGE WITH fillfactor=80

+----------------------------------------+--------+
| tuple | tuple | tuple | tuple          | free   |
+----------------------------------------+--------+

UPDATE creates new tuple version.
Room exists on same page.
HOT update may be possible.
```

HOT means Heap-Only Tuple. It avoids index rewrites when two conditions hold:

```text
1. The update does not change any indexed column.
2. The new tuple version fits on the same heap page as the old version.
```

HOT chain:

```text
B+Tree index entry
  key = order_id 42
  TID = (page 10, slot 1)
        |
        v
+----------------------------------------------------------+
| Heap page 10                                             |
|                                                          |
| slot 1 -> old tuple                                      |
|           xmin=100, xmax=200                             |
|           status='pending'                               |
|           HOT link -> slot 2                             |
|                                                          |
| slot 2 -> new tuple                                      |
|           xmin=200, xmax=0                               |
|           status='paid'                                  |
+----------------------------------------------------------+
```

Why this is powerful:

```text
Without HOT:
  update heap
  update index 1
  update index 2
  update index 3
  update index 4
  update index 5

With HOT:
  update heap page only
  no B+Tree index modification
```

Why HOT fails:

```text
1. Updated column is indexed.
2. Page has no free space.
3. Tuple grows too large for page.
4. Long HOT chains create extra heap work until vacuum prunes them.
```

Operational warning:

```text
ALTER TABLE ... SET (fillfactor = 80) affects future page writes.
It does not magically repack existing pages.
Rewriting or rebuilding the table/indexes to apply it can be expensive and dangerous.
```

---

# Part G: Index-Only Scans and the Visibility Map

An index-only scan sounds simple: answer a query from the index without reading the heap.

Example:

```sql
SELECT status
FROM orders
WHERE customer_id = 42;
```

If there is an index on `(customer_id, status)`, the index contains all columns needed by the query.

So why ever read the heap?

Because MVCC visibility is stored in heap tuple metadata, not usually in the B+Tree index entry.

PostgreSQL uses the visibility map to avoid unnecessary heap fetches.

```text
VISIBILITY MAP

+---------+-------------------+------------------------------------------+
| Heap Pg | VM bit            | Meaning                                  |
+---------+-------------------+------------------------------------------+
| 0       | 1                 | all tuples visible to all transactions   |
| 1       | 1                 | heap fetch can be skipped                |
| 2       | 0                 | must fetch heap page to check visibility |
| 3       | 0                 | recent changes or not vacuumed enough    |
+---------+-------------------+------------------------------------------+
```

Index-only scan fast path:

```text
1. Traverse index.
2. Find key/customer_id/status in index leaf.
3. Check visibility map for heap page.
4. VM says all-visible.
5. Return data from index.
6. No heap page read.
```

Slow path:

```text
1. Traverse index.
2. Find entry.
3. VM bit is 0.
4. Fetch heap page.
5. Inspect tuple xmin/xmax visibility.
6. Return row if visible.
```

What breaks:

```text
Autovacuum falls behind.
Visibility map bits stay 0.
Execution plan still says Index Only Scan.
But actual heap fetches are high.
Read latency spikes.
```

SRE proof:

```text
Use EXPLAIN with ANALYZE and BUFFERS.
Look for Heap Fetches under Index Only Scan.

High Heap Fetches means the index-only scan is not truly heap-free.
```

---

# Part H: TOAST and Oversized Attributes

A page cannot hold arbitrarily large values. PostgreSQL uses TOAST for oversized attributes.

TOAST stands for The Oversized-Attribute Storage Technique.

If a row becomes too large, PostgreSQL may compress large attributes and/or store them out-of-line in a hidden TOAST table.

```text
MAIN HEAP TABLE

+----------------------------------------------------------+
| user_events                                              |
+----------------------------------------------------------+
| id: 42                                                   |
| status: 'failed'                                         |
| payload: TOAST_POINTER(chunk_id=998877)                  |
+----------------------------------------------------------+

                       |
                       v

HIDDEN TOAST TABLE

+----------+-----------+------------+----------------------+
| chunk_id | chunk_seq | chunk_len  | chunk_data            |
+----------+-----------+------------+----------------------+
| 998877   | 0         | 1996       | bytes...              |
| 998877   | 1         | 1996       | bytes...              |
| 998877   | 2         | 1996       | bytes...              |
| 998877   | 3         | 1996       | bytes...              |
+----------+-----------+------------+----------------------+
```

Fast query:

```sql
SELECT id, status
FROM user_events
WHERE id = 42;
```

This can read the main heap page and ignore the TOAST payload.

Dangerous query:

```sql
SELECT *
FROM user_events
WHERE status = 'failed';
```

If thousands of matching rows contain large payloads, the engine may need to read heap pages, follow TOAST pointers, fetch chunks, decompress payloads, reassemble values, and send huge rows to the application.

Production symptoms:

```text
CPU spikes due to decompression.
I/O rises due to TOAST chunk reads.
Network output rises due to large result sets.
Application memory rises due to ORM hydration.
The query may look harmless because the WHERE clause is selective.
```

SRE mitigation:

```text
1. Avoid SELECT * on wide tables.
2. Split large payloads into separate tables or object storage when appropriate.
3. Use explicit projection: SELECT id, status, created_at.
4. Monitor query result size, CPU, and buffer reads.
5. Review ORM default query behavior.
```

---

# Part I: Index Bloat

B+Trees do not always shrink neatly after deletes and updates. Heavy UPDATE and DELETE workloads can leave empty space, half-empty pages, dead entries, and inefficient tree shape.

```text
HEALTHY INDEX PAGES

+-----------+-----------+-----------+
| 85% full  | 88% full  | 82% full  |
+-----------+-----------+-----------+
```

```text
BLOATED INDEX PAGES

+-----------+-----------+-----------+-----------+-----------+
| 12% full  | 18% full  | 9% full   | 22% full  | 15% full  |
+-----------+-----------+-----------+-----------+-----------+
```

Same logical keys. More pages.

Consequences:

```text
1. More memory needed to cache the same index.
2. More disk reads on cache miss.
3. More CPU to traverse and compare entries.
4. Worse checkpoint and backup volume.
5. More WAL during maintenance.
```

REINDEX can fix bloat by building a fresh compact index. But REINDEX is dangerous.

```text
REINDEX CONCURRENTLY danger:

1. Builds new index alongside old index.
2. Temporarily needs roughly another copy of index disk space.
3. Generates heavy read and write I/O.
4. Can extend runtime under write load.
5. Can worsen an already I/O-bound incident.
```

Principal SRE rule:

```text
Do not treat REINDEX CONCURRENTLY as harmless because it says concurrently.
It reduces locking risk, not resource risk.
```

---

# Part J: B-Tree vs LSM-Tree

B-Trees and LSM-Trees optimize opposite physical realities.

```text
+-----------------------+-----------------------------+-----------------------------+
| Axis                  | B-Tree                      | LSM-Tree                    |
+-----------------------+-----------------------------+-----------------------------+
| Write pattern         | in-place page modification  | append to log/memtable      |
| Write amplification   | high under updates/indexes  | shifted to compaction       |
| Read amplification    | low for point lookup        | can be high across SSTables |
| Space amplification   | bloat/fragmentation         | old versions until compact  |
| Range scans           | excellent through leaf links| good within sorted runs     |
| Maintenance           | vacuum/reindex              | compaction/repair           |
| Best fit              | OLTP, ledgers, constraints  | write-heavy time-series     |
+-----------------------+-----------------------------+-----------------------------+
```

B-Tree write cost example:

```text
UPDATE one status field on table with 5 indexes.

Possible writes:
  heap page
  index page 1
  index page 2
  index page 3
  index page 4
  index page 5
  WAL records
  maybe full-page images after checkpoint
```

LSM write cost example:

```text
INSERT metric sample.

Writes:
  append commitlog
  update memtable
  later flush SSTable sequentially
  later compact SSTables
```

Decision framing:

```text
Use B-Tree engines when you need:
  strong transactions
  constraints
  secondary indexes
  low-latency point lookups
  range queries
  relational joins
  ledgers and order systems

Use LSM engines when you need:
  huge write throughput
  append-heavy workloads
  wide-column access patterns
  predictable partition-key queries
  time-series or event-like ingestion
```

The correct answer is not PostgreSQL good, Cassandra bad. The correct answer is physical fit.

---

## 3. Production Patterns and Failure Modes

```text
+--------------------------------------------------------------------------+
| FAILURE MODE 1: BUFFER POOL THRASHING                                    |
+--------------------------------------------------------------------------+
| Symptom                                                                  |
|   API p99 jumps from 12ms to 900ms. CPU drops. Disk read IOPS maxes.      |
|                                                                          |
| Cause                                                                    |
|   A query or batch job scans cold pages from a large table. Those pages   |
|   evict hot index and heap pages from the database buffer pool. Queries   |
|   that were memory-only now need physical reads.                          |
|                                                                          |
| Proof                                                                    |
|   Buffer read metrics spike. Backend reads or engine-specific sync reads  |
|   climb. EXPLAIN BUFFERS shows large shared/local read counts.            |
|                                                                          |
| Mitigation                                                               |
|   Kill or throttle the scan. Add statement timeout. Batch work. Restore   |
|   hot cache naturally. Do not run another full-table job during recovery. |
+--------------------------------------------------------------------------+
```

```text
+--------------------------------------------------------------------------+
| FAILURE MODE 2: RIGHTMOST B-TREE PAGE CONTENTION                         |
+--------------------------------------------------------------------------+
| Symptom                                                                  |
|   INSERT throughput plateaus. Waits show page latch or buffer-content     |
|   contention. Disk may not look fully saturated at first.                 |
|                                                                          |
| Cause                                                                    |
|   Sequential primary key forces all concurrent inserts into the same      |
|   rightmost leaf page. That page becomes a latch bottleneck.              |
|                                                                          |
| Proof                                                                    |
|   High insert concurrency, sequential key, latch waits, hot index leaf,   |
|   throughput plateau.                                                    |
|                                                                          |
| Mitigation                                                               |
|   Use time-ordered randomized IDs where appropriate. Reduce unnecessary   |
|   indexes. Batch writes. Partition hot tables when justified.             |
+--------------------------------------------------------------------------+
```

```text
+--------------------------------------------------------------------------+
| FAILURE MODE 3: INDEX BLOAT                                              |
+--------------------------------------------------------------------------+
| Symptom                                                                  |
|   Table is 50GB but primary key index is 120GB. Read latency creeps over  |
|   weeks. Cache hit ratio falls.                                           |
|                                                                          |
| Cause                                                                    |
|   Heavy update/delete workload leaves sparsely populated index pages.     |
|   Vacuum removes dead entries but does not always compact the B-Tree      |
|   back to an ideal shape.                                                 |
|                                                                          |
| Proof                                                                    |
|   Index size much larger than expected. Bloat tools show low density.     |
|   Query plans show more buffers touched than expected.                    |
|                                                                          |
| Mitigation                                                               |
|   REINDEX CONCURRENTLY during safe window. Verify disk headroom. Watch    |
|   I/O. Consider fillfactor and workload changes.                          |
+--------------------------------------------------------------------------+
```

```text
+--------------------------------------------------------------------------+
| FAILURE MODE 4: BROKEN INDEX-ONLY SCAN                                   |
+--------------------------------------------------------------------------+
| Symptom                                                                  |
|   Plan says Index Only Scan, but latency and heap reads are high.         |
|                                                                          |
| Cause                                                                    |
|   Visibility map bits are not all-visible because pages had recent        |
|   modifications or vacuum is behind. Engine must fetch heap pages to      |
|   check tuple visibility.                                                 |
|                                                                          |
| Proof                                                                    |
|   EXPLAIN ANALYZE BUFFERS shows high Heap Fetches under Index Only Scan.  |
|                                                                          |
| Mitigation                                                               |
|   Fix vacuum lag. Reduce long transactions. Improve autovacuum settings.  |
|   Avoid assuming covering index means heap-free read.                     |
+--------------------------------------------------------------------------+
```

```text
+--------------------------------------------------------------------------+
| FAILURE MODE 5: TOAST DECOMPRESSION CLIFF                                |
+--------------------------------------------------------------------------+
| Symptom                                                                  |
|   CPU hits 100%. I/O is moderate. Query uses SELECT * over wide JSONB     |
|   rows. Application memory and network output rise.                       |
|                                                                          |
| Cause                                                                    |
|   Large attributes are stored out-of-line in TOAST chunks. SELECT *       |
|   forces chunk lookup, fetch, decompression, and reassembly for each row. |
|                                                                          |
| Proof                                                                    |
|   Query returns wide payloads. Removing payload column makes query fast.   |
|   CPU profile shows decompression and serialization.                      |
|                                                                          |
| Mitigation                                                               |
|   Select only required columns. Split wide payloads. Store huge blobs in  |
|   object storage when relational access is unnecessary.                   |
+--------------------------------------------------------------------------+
```

```text
+--------------------------------------------------------------------------+
| FAILURE MODE 6: HOT UPDATE FAILURE                                       |
+--------------------------------------------------------------------------+
| Symptom                                                                  |
|   Update-heavy table generates high index write I/O and bloat.           |
|                                                                          |
| Cause                                                                    |
|   Updated column is indexed or page has no free space. HOT updates are    |
|   impossible, so every update touches heap plus indexes.                  |
|                                                                          |
| Proof                                                                    |
|   Low HOT update ratio. High index growth. Fillfactor at 100 on hot table.|
|                                                                          |
| Mitigation                                                               |
|   Remove unnecessary index on frequently updated column. Lower fillfactor |
|   for future pages. Repack/rewrite only during safe maintenance window.   |
+--------------------------------------------------------------------------+
```

---

## 4. Hands-On Exercise

This exercise is PostgreSQL-oriented because PostgreSQL exposes page inspection tools clearly.

```bash
# 1. Start PostgreSQL.
docker run --name pg-btree-pages \
  -e POSTGRES_PASSWORD=pass \
  -p 5432:5432 \
  -d postgres:16

# 2. Open psql.
docker exec -it pg-btree-pages psql -U postgres
```

```sql
-- 3. Enable inspection extensions.
CREATE EXTENSION pageinspect;
CREATE EXTENSION pgstattuple;

-- 4. Create a small table.
CREATE TABLE internals_test (
  id INT PRIMARY KEY,
  status TEXT,
  payload TEXT
);

INSERT INTO internals_test
SELECT generate_series(1, 1000), 'new', 'small payload';

-- 5. Inspect tuple slots on heap page 0.
SELECT lp, lp_off, lp_len, t_xmin, t_xmax
FROM heap_page_items(get_raw_page('internals_test', 0))
LIMIT 10;

-- 6. Update one row and inspect MVCC versioning.
UPDATE internals_test
SET status = 'paid'
WHERE id = 1;

SELECT lp, lp_off, lp_len, t_xmin, t_xmax
FROM heap_page_items(get_raw_page('internals_test', 0))
LIMIT 10;

-- 7. Check table dead tuple statistics.
SELECT *
FROM pgstattuple('internals_test');

-- 8. Look at relation sizes.
SELECT
  pg_size_pretty(pg_relation_size('internals_test')) AS heap_size,
  pg_size_pretty(pg_indexes_size('internals_test')) AS indexes_size;
```

What to observe:

```text
1. A page has line pointers and tuple data.
2. UPDATE creates a new tuple version.
3. Old tuple has xmax set.
4. Dead tuple percentage can rise.
5. Index and heap sizes are separate physical costs.
```

Optional index-only scan check:

```sql
CREATE INDEX internals_status_idx ON internals_test(status, id);
VACUUM internals_test;

EXPLAIN (ANALYZE, BUFFERS)
SELECT id
FROM internals_test
WHERE status = 'paid';
```

Look for:

```text
Index Only Scan
Heap Fetches
shared hit/read buffers
```

A plan name alone is not enough. The buffer and heap-fetch counters reveal physical truth.

---

## 5. SRE Scenario

### Scenario: The End-of-Month Reconciliation Meltdown

```text
SETUP

You are the Principal SRE for a payment gateway.

Database:
  PostgreSQL primary
  512GB RAM
  EBS io2 storage
  one async replica

Table:
  transactions_2026_04
  8TB partition
  id BIGSERIAL PRIMARY KEY
  merchant_id
  status
  amount_cents
  payload JSONB
  updated_at

Traffic:
  8,000 inserts/sec
  25,000 reads/sec

Normal state:
  Checkout API p99: 12ms
  DB CPU: 40 percent
  WAL generation: 80MB/sec
  replica lag: < 50ms
```

Incident:

```text
02:00:00
  A checkpoint completes.

02:00:05
  Finance cron runs:

  UPDATE transactions_2026_04
  SET status = 'reconciled', updated_at = NOW()
  WHERE status = 'settled'
    AND created_at < NOW() - INTERVAL '30 days';

  It matches 45 million scattered rows.

02:01:30
  API read latency jumps from 12ms to 1,400ms.

02:02:00
  Red herring alert: Redis connection timeouts.
  EC2 network out is saturated.

02:03:00
  WAL generation jumps from 80MB/sec to 1.2GB/sec.
  EBS write throughput saturates.
  Replica lag climbs to 45 seconds.

02:04:30
  New payment inserts time out.
  pg_stat_activity shows many sessions waiting on LWLock: buffer_content.

02:06:00
  PgBouncer pool saturates.
  API gateway returns 503s.
```

Questions:

```text
Q1. Trace the cascade from the unbounded UPDATE to the global 503s.

Q2. Why can a tiny status update produce a huge WAL spike right after a checkpoint?

Q3. Why are new INSERTs waiting on a page latch while the visible resource problem is disk saturation?

Q4. What is the minute-by-minute mitigation plan, and what rollback warning must be communicated before killing the query?

Q5. What architecture changes prevent this class of incident?
```

---

## 6. Scenario Answers

### Answer 1: Cascade Chain

```text
1. Unbounded UPDATE starts.
   It matches 45 million old rows scattered across a huge partition.

2. Cold heap pages are pulled into the buffer pool.
   Hot pages used by live checkout traffic are evicted.

3. API reads lose cache locality.
   Queries that used to hit memory now perform physical reads.
   p99 jumps from 12ms to 1,400ms.

4. The Redis alert is a red herring.
   EBS traffic uses instance network bandwidth.
   Massive database read/write traffic saturates the instance pipe.
   Redis packets time out because the network is congested, not because Redis is root cause.

5. WAL generation spikes.
   The UPDATE touches many pages shortly after checkpoint.
   Full-page images may be logged for first modifications after checkpoint.

6. Replica lag grows.
   Replica must receive and replay WAL faster than it is generated.
   It cannot keep up with 1.2GB/sec.

7. INSERTs contend on hot B+Tree pages.
   BIGSERIAL concentrates inserts on the rightmost primary-key leaf page.
   Slow I/O and commit pressure stretch critical sections and increase latch waits.

8. PgBouncer saturates.
   Queries hold connections far longer than normal.
   Client wait queue grows.
   API gateway returns 503s.
```

### Answer 2: WAL Spike After Checkpoint

A small logical update can create large physical logging.

Immediately after a checkpoint, the first modification to a page may require logging a full-page image. This protects against torn pages: partial page writes during crash or power loss.

```text
Logical change:
  status: 'settled' -> 'reconciled'
  maybe tens of bytes

Physical protection:
  log full 8KB page image on first modification after checkpoint
```

Approximate math:

```text
If 150,000 distinct pages are first-modified per second:

150,000 pages/sec * 8KB = 1.2GB/sec
```

The application changed a small field. The storage engine protected many full pages.

That is the point of this topic: logical size is not physical cost.

### Answer 3: INSERTs Waiting on LWLock / Page Latch

BIGSERIAL keys insert at the right edge of the B+Tree. Many concurrent inserts need to modify the same rightmost leaf page. Normally that latch is held briefly. During I/O saturation, commits slow down, dirty page pressure rises, WAL flushes stall, and the system spends longer in paths that need hot page structures.

The visible wait is an in-memory latch. The underlying cause is the physical design and overloaded write path.

```text
Sequential key:
  good locality
  bad extreme-concurrency hot edge

Random UUIDv4:
  spreads contention
  bad locality and more random page churn

UUIDv7 / time-ordered random IDs:
  compromise: mostly ordered, less single-page contention
```

### Answer 4: Mitigation Plan

Minute 0-1: Identify the query.

```sql
SELECT pid, query_start, state, wait_event_type, wait_event, query
FROM pg_stat_activity
WHERE query ILIKE '%UPDATE transactions_2026_04%reconciled%';
```

Minute 1-2: Communicate rollback penalty.

```text
Stakeholder warning:

I am going to stop the batch job. The database will not recover instantly.
If the UPDATE already changed many rows inside an open transaction, PostgreSQL must roll back or mark that transaction aborted and later clean dead versions.
This creates additional I/O and vacuum work.
Do not restart the primary unless we are handling a separate database failure.
Expect recovery to take minutes, not seconds.
```

Minute 2: Cancel, then terminate if needed.

```sql
SELECT pg_cancel_backend(<pid>);

-- If it does not stop quickly and business impact is severe:
SELECT pg_terminate_backend(<pid>);
```

Minute 3-5: Reduce pressure.

```text
1. Pause finance batch scheduler.
2. Stop other non-critical analytics/batch jobs.
3. Consider temporarily shifting read traffic away from overloaded paths if replica is not too stale.
4. If replica lag is unsafe, do not route correctness-sensitive reads there.
```

Minute 5-10: Watch recovery.

```sql
SELECT buffers_checkpoint, buffers_clean, buffers_backend
FROM pg_stat_bgwriter;

SELECT now() - pg_last_xact_replay_timestamp() AS replica_lag;
```

Do not run REINDEX, VACUUM FULL, or huge backfill during the hot recovery window.

### Answer 5: Prevention Matrix

```text
+--------------------------+----------------------+----------------------+----------------------+
| Failure                  | L1 prevention        | L2 guardrail         | L3 emergency         |
+--------------------------+----------------------+----------------------+----------------------+
| unbounded UPDATE         | chunked job          | statement timeout    | kill query runbook   |
| buffer pool thrash       | small batches        | off-peak schedule    | pause batch traffic  |
| WAL spike                | chunk + sleep        | max_wal_size review  | throttle writes      |
| rightmost contention     | ID strategy review   | reduce indexes       | scale hardware       |
| HOT failure              | fillfactor + indexes | table rewrite plan   | defer updates        |
| replica lag              | WAL budget           | lag alert            | stop read routing    |
+--------------------------+----------------------+----------------------+----------------------+
```

Chunked update pattern:

```sql
WITH batch AS (
  SELECT id
  FROM transactions_2026_04
  WHERE status = 'settled'
    AND created_at < NOW() - INTERVAL '30 days'
  ORDER BY id
  LIMIT 2500
  FOR UPDATE SKIP LOCKED
)
UPDATE transactions_2026_04 t
SET status = 'reconciled', updated_at = NOW()
FROM batch
WHERE t.id = batch.id;
```

Application loop:

```text
1. Run one batch.
2. Commit.
3. Sleep 100-300ms.
4. Measure WAL rate and replica lag.
5. Continue only if below safety thresholds.
```

Operational danger:

```text
Changing fillfactor alone does not repack old pages.
Repacking or rebuilding can require heavy I/O and extra disk.
A maintenance fix can reproduce the outage if run casually.
```

---

## 7. Targeted Reading

```text
Designing Data-Intensive Applications, Chapter 3: Storage and Retrieval
  Focus on B-Trees, LSM-Trees, update-in-place costs, and storage engine tradeoffs.

PostgreSQL documentation:
  - pageinspect extension
  - routine vacuuming
  - index-only scans
  - storage TOAST
  - fillfactor storage parameter
```

---

## 8. Key Takeaways

```text
1. Relational databases read and write pages, not individual rows.

2. Slotted pages use line pointers so tuple bytes can move inside a page
   without changing external tuple IDs.

3. B+Trees are excellent for point lookups and range scans because depth is
   small and leaf pages are linked.

4. Page splits are the B+Tree write penalty. They allocate pages, move keys,
   update parents, generate WAL, and hold latches.

5. Sequential keys preserve locality but can create rightmost-page contention.
   Random keys spread contention but can destroy locality.

6. HOT updates are the golden path for update-heavy tables because they avoid
   rewriting every index when indexed columns do not change.

7. HOT updates require same-page free space, so fillfactor is an operational
   control, not cosmetic storage tuning.

8. Index-only scans require visibility information. A stale visibility map
   turns a supposed index-only plan into heap I/O.

9. TOAST hides huge values behind pointers. SELECT * can accidentally force
   chunk reads, decompression, network output, and ORM memory pressure.

10. Index bloat increases the number of pages needed to represent the same
    logical keys. More pages means more cache pressure and slower reads.

11. B-Trees and LSM-Trees are not rivals in a popularity contest. They are
    different physical answers to different workload shapes.

12. Principal SRE diagnosis starts from physical units: pages, latches, WAL,
    buffers, indexes, tuple versions, and cache residency.
```
