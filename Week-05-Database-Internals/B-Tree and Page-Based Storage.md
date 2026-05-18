# Week 5, Topic 3: The B-Tree and Page-Based Storage

Last verified: 2026-05-18

---

## 1. Learning Objectives

```text
+------------------------------------------------------------------------------+
| AFTER THIS TOPIC, YOU WILL BE ABLE TO                                        |
+------------------------------------------------------------------------------+
|                                                                              |
| 1. Explain the fundamental storage-engine tradeoff between B-Tree engines and |
|    LSM-Tree engines using physical I/O, not vendor names.                     |
|                                                                              |
| 2. Trace a relational point lookup from SQL predicate to B+Tree root page,    |
|    internal page, leaf page, tuple identifier, heap page, and visibility      |
|    check.                                                                     |
|                                                                              |
| 3. Draw and explain a slotted page: page header, line pointer array, free     |
|    space, tuple bytes, tuple IDs, dead tuples, and tuple movement.            |
|                                                                              |
| 4. Explain how B+Tree fanout keeps tree depth small and why low depth does    |
|    not guarantee low latency when pages are cold, bloated, or contended.      |
|                                                                              |
| 5. Explain page splits, parent propagation, right-growing indexes, and the    |
|    difference between logical locks and physical page latches.                |
|                                                                              |
| 6. Explain heap-only tuple updates, fillfactor, tuple chains, and why one     |
|    indexed mutable column can turn a cheap update into a write-amplification  |
|    storm.                                                                     |
|                                                                              |
| 7. Explain visibility maps, free space maps, index-only scans, heap fetches,  |
|    and why plan names can lie about physical I/O.                             |
|                                                                              |
| 8. Explain TOAST-style oversized attribute storage, chunking, compression,    |
|    hidden reads, and why SELECT * can become a CPU/I/O/network cliff.         |
|                                                                              |
| 9. Diagnose table bloat, index bloat, HOT failure, rightmost-page contention, |
|    broken index-only scans, wide-row cliffs, vacuum lag, and unsafe REINDEX   |
|    attempts using real metrics and commands.                                  |
|                                                                              |
| 10. Defend safe mitigations during incidents: cancellation, rollback-warning, |
|     throttling, chunked updates, index review, fillfactor rollout, partition  |
|     strategy, and current-state/event-history separation.                     |
|                                                                              |
+------------------------------------------------------------------------------+
```

---

## 2. Core Teaching

# Part 1: The Fundamental Tradeoff, B-Tree vs LSM-Tree

Database internals are not a zoo of product names.

They are a set of physical tradeoffs.

The first tradeoff in Week 5 is the one Cassandra already introduced from the LSM side.

This module now teaches the opposite side.

Cassandra's LSM-tree path says: make writes cheap now by appending to a commitlog and memory structure, then pay later through flushes, SSTables, bloom filters, read amplification, compaction, tombstones, and repair.

A B-Tree engine says: keep the searchable structure current now, pay for page updates now, and make point/range reads efficient against a maintained tree.

```text
+------------------------------------------------------------------------------+
| STORAGE ENGINE PHYSICS                                                        |
+----------------------------+-----------------------------+-------------------+
| Question                   | B-Tree engine               | LSM-Tree engine   |
+----------------------------+-----------------------------+-------------------+
| What is optimized first?   | current searchable pages     | fast ingest       |
| Write shape                | modify heap/index pages      | append log + mem  |
| Read shape                 | traverse maintained tree     | merge structures  |
| Maintenance debt           | bloat, vacuum, reindex       | compaction, repair|
| Best natural fit           | OLTP, ledgers, constraints   | write-heavy ingest|
+----------------------------+-----------------------------+-------------------+
```

The beginner version is:

```text
B-Trees are good for reads.
LSM-Trees are good for writes.
```

That is too shallow.

The Principal Engineer version is:

```text
B-Trees keep mutable search structures current by modifying pages and indexes
as writes happen. This keeps point lookups and ordered range scans efficient,
but creates immediate write amplification, page splits, latch contention,
visibility maintenance, bloat, and vacuum/reindex obligations.

LSM-Trees make foreground writes cheap by appending and sorting later. This
pushes work into background compaction and creates read amplification, space
amplification, tombstone pain, and repair/compaction operational risk.
```

This is the central mental model.

Every section below explains one piece of that cost.

---

# Part 2: The Page, The Atomic Unit

Application developers talk about rows.

Storage engines move pages.

This is the same level of physical truth as Cassandra's commitlog/memtable/SSTable path.

A page is a fixed-size block of storage managed by the database engine.

PostgreSQL commonly uses 8KB pages.

InnoDB commonly uses 16KB pages.

The exact page size differs by engine, but the operational truth is stable: a tiny row-level change can become page-level work.

```sql
SELECT *
FROM payments
WHERE payment_id = 42;
```

Developer mental model:

```text
read one payment row
```

Storage-engine mental model:

```text
read index pages
find tuple reference
read heap/data page
check visibility
return logical row
```

```text
+------------------------------------------------------------------------------+
| POINT LOOKUP, PHYSICAL VIEW                                                   |
+------------------------------------------------------------------------------+
|                                                                              |
| SQL predicate                                                                 |
|   payment_id = 42                                                             |
|        |                                                                      |
|        v                                                                      |
| B+Tree root page                                                              |
|        |                                                                      |
|        v                                                                      |
| B+Tree internal page                                                          |
|        |                                                                      |
|        v                                                                      |
| B+Tree leaf page                                                              |
|        |                                                                      |
|        v                                                                      |
| tuple identifier                                                              |
|        |                                                                      |
|        v                                                                      |
| heap/data page                                                                |
|        |                                                                      |
|        v                                                                      |
| tuple visibility check                                                        |
|        |                                                                      |
|        v                                                                      |
| logical row returned                                                          |
|                                                                              |
+------------------------------------------------------------------------------+
```

One 60-byte row can require an 8KB heap page read.

One 20-byte update can dirty an 8KB page.

One non-HOT update can dirty the heap page plus multiple index pages.

One wide-column query can follow TOAST pointers into many hidden chunks.

One large scan can evict the hot working set from the buffer pool.

That is why page thinking is not optional.

```text
+------------------------------------------------------------------------------+
| PRINCIPAL SRE PAGE QUESTIONS                                                  |
+------------------------------------------------------------------------------+
|                                                                              |
| Which pages are being read?                                                   |
| Which pages are being dirtied?                                                |
| Which pages are hot in memory?                                                |
| Which pages were evicted by this job?                                         |
| Which index pages are bloated?                                                |
| Which heap pages contain dead versions?                                       |
| Which B+Tree leaf page is being split or latched?                             |
| Which pages cannot be cleaned because old snapshots still need them?          |
| Which pages need full-page images after checkpoint?                           |
|                                                                              |
+------------------------------------------------------------------------------+
```

A database incident often appears as CPU, disk, network, pool, or application trouble.

Underneath, it may be a page-level incident wearing a fake mustache.

---

# Part 3: Slotted Page Anatomy

Rows are not all the same length.

A row can contain fixed-width integers, timestamps, nullable fields, strings, JSON, arrays, compressed values, and pointers to out-of-line data.

If a page stored variable-length rows without indirection, changing a row's length would force large regions of the page to move and would invalidate external references.

The slotted page solves this with stable slots.

The line pointer array grows from the front.

Tuple bytes grow from the back.

Free space lives in the middle.

```text
+------------------------------------------------------------------------------+
| 8KB SLOTTED PAGE, CONCEPTUAL LAYOUT                                           |
+------------------------------------------------------------------------------+
| PAGE HEADER                                                                  |
|   pd_lsn       WAL position of last change affecting this page                |
|   pd_checksum  optional corruption detection                                  |
|   pd_flags     page-level flags                                               |
|   pd_lower     end of line pointer area                                       |
|   pd_upper     start of tuple data area                                       |
+------------------------------------------------------------------------------+
| LINE POINTER ARRAY                                                            |
|                                                                              |
|   slot 1 -> offset=8080, len=88,  flags=normal                                |
|   slot 2 -> offset=7952, len=120, flags=normal                                |
|   slot 3 -> offset=7816, len=128, flags=dead                                  |
|   slot 4 -> offset=7600, len=184, flags=normal                                |
|                                                                              |
+------------------------------------------------------------------------------+
|                                                                              |
|                               FREE SPACE                                      |
|                                                                              |
|                  available bytes = pd_upper - pd_lower                       |
|                                                                              |
+------------------------------------------------------------------------------+
| tuple bytes for slot 4                                                        |
+------------------------------------------------------------------------------+
| tuple bytes for slot 3, dead or reusable after cleanup                        |
+------------------------------------------------------------------------------+
| tuple bytes for slot 2                                                        |
+------------------------------------------------------------------------------+
| tuple bytes for slot 1                                                        |
+------------------------------------------------------------------------------+

Growth pattern:

  line pointers grow downward through this diagram
  tuple bytes grow upward through this diagram
  free space is squeezed between them
```

A B+Tree index usually stores a tuple identifier.

It does not store a raw byte offset into the page.

```text
+------------------------------------------------------------------------------+
| TUPLE IDENTIFIER                                                              |
+------------------------------------------------------------------------------+
|                                                                              |
|   TID = (heap_page_number, slot_number)                                       |
|                                                                              |
|   Example                                                                     |
|     TID = (42, 3)                                                             |
|                                                                              |
|   Meaning                                                                     |
|     read heap page 42                                                         |
|     inspect line pointer slot 3                                               |
|     follow slot 3 to tuple bytes                                              |
|                                                                              |
+------------------------------------------------------------------------------+
```

This indirection is the entire trick.

Tuple bytes can move inside the same page, but the slot number can remain stable.

The index entry remains valid because it points to the slot, not the byte address.

```text
+------------------------------------------------------------------------------+
| LOCAL TUPLE MOVEMENT                                                          |
+------------------------------------------------------------------------------+
|                                                                              |
| Before cleanup                                                                |
|                                                                              |
|   B+Tree entry                                                                |
|     key = 42                                                                  |
|     TID = page 42, slot 3                                                     |
|                                                                              |
|   Heap page 42                                                                |
|     slot 3 -> byte offset 7816                                                |
|                                                                              |
| After cleanup                                                                 |
|                                                                              |
|   B+Tree entry                                                                |
|     key = 42                                                                  |
|     TID = page 42, slot 3                                                     |
|                                                                              |
|   Heap page 42                                                                |
|     slot 3 -> byte offset 7600                                                |
|                                                                              |
| Result                                                                        |
|   tuple bytes moved                                                           |
|   slot stayed stable                                                          |
|   index entry did not change                                                  |
|                                                                              |
+------------------------------------------------------------------------------+
```

This is the B-Tree equivalent of understanding Cassandra's SSTable component files.

If you cannot explain the page, you cannot explain bloat, HOT updates, index-only scans, or vacuum behavior.

---

# Part 4: Tuple Headers and Page-Level MVCC Clues

A tuple is not just user data.

A tuple also carries visibility metadata.

Full MVCC belongs in Topic 5, but the physical tuple layout already exposes the shape of the problem.

```text
+------------------------------------------------------------------------------+
| SIMPLIFIED HEAP TUPLE                                                         |
+------------------------------------------------------------------------------+
| TUPLE HEADER                                                                  |
|   xmin    transaction that created this tuple version                         |
|   xmax    transaction that deleted or replaced this tuple version             |
|   flags   null bitmap, status bits, hint bits                                 |
+------------------------------------------------------------------------------+
| USER COLUMNS                                                                  |
|   payment_id                                                                  |
|   merchant_id                                                                 |
|   status                                                                      |
|   amount_cents                                                                |
|   processor_ref                                                               |
|   created_at                                                                  |
|   updated_at                                                                  |
+------------------------------------------------------------------------------+
```

An UPDATE usually creates a new tuple version.

It does not simply overwrite the old version in place.

```text
+------------------------------------------------------------------------------+
| BEFORE UPDATE                                                                 |
+------------------------------------------------------------------------------+
| heap page 10                                                                  |
|                                                                              |
|   slot 1 -> tuple A                                                           |
|             xmin   = 100                                                      |
|             xmax   = 0                                                        |
|             status = 'authorized'                                             |
|                                                                              |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| AFTER UPDATE status='captured' BY TRANSACTION 200                             |
+------------------------------------------------------------------------------+
| heap page 10                                                                  |
|                                                                              |
|   slot 1 -> old tuple A                                                       |
|             xmin   = 100                                                      |
|             xmax   = 200                                                      |
|             status = 'authorized'                                             |
|                                                                              |
|   slot 2 -> new tuple B                                                       |
|             xmin   = 200                                                      |
|             xmax   = 0                                                        |
|             status = 'captured'                                               |
|                                                                              |
+------------------------------------------------------------------------------+
```

Why keep the old tuple?

Because an older transaction may still need the old version.

```text
+------------------------------------------------------------------------------+
| SNAPSHOT CONSEQUENCE                                                          |
+------------------------------------------------------------------------------+
|                                                                              |
| Transaction T_old started before transaction 200 committed.                   |
| T_old may still need to see status='authorized'.                              |
|                                                                              |
| Transaction T_new started after transaction 200 committed.                    |
| T_new should see status='captured'.                                           |
|                                                                              |
+------------------------------------------------------------------------------+
```

This means a single heap page can hold live tuple versions, old tuple versions, dead tuple versions, and free space at the same time.

SRE consequences:

```text
+------------------------------------------------------------------------------+
| UPDATE AND DELETE CONSEQUENCES                                                |
+------------------------------------------------------------------------------+
|                                                                              |
| High UPDATE rate creates old tuple versions.                                  |
| High DELETE rate creates dead tuple versions.                                 |
| Dead versions consume heap page space until cleanup.                          |
| Less free space reduces HOT update probability.                               |
| Fewer HOT updates increase index writes.                                      |
| More index writes increase WAL, bloat, and cache pressure.                    |
| Long transactions can prevent cleanup.                                        |
|                                                                              |
+------------------------------------------------------------------------------+
```

A table can have a reasonable number of live rows and still be physically sick.

The database may be carrying dead versions, stale line pointers, fragmented pages, bloated indexes, and visibility debt.

That is why row count alone is a trap.

---

# Part 5: B+Tree Anatomy

A B+Tree index is a tree of pages.

Most database indexes called B-Trees are practically B+Trees: internal pages route the search, leaf pages contain ordered entries, and leaf pages are linked for range scans.

The diagram below is deliberately boxy and top-to-bottom.

```text
+------------------------------------------------------------------------------+
| B+TREE STRUCTURE                                                              |
+------------------------------------------------------------------------------+
| LEVEL 0: ROOT PAGE                                                            |
|                                                                              |
|   +----------------------------+                                             |
|   | root page                  |                                             |
|   | separator keys: 100, 500   |                                             |
|   +-------------+--------------+                                             |
|                 |                                                            |
|                 v                                                            |
+------------------------------------------------------------------------------+
| LEVEL 1: INTERNAL PAGES                                                       |
|                                                                              |
|   +--------------------+        +--------------------+                       |
|   | internal page A    |        | internal page B    |                       |
|   | key range: 1..499  |        | key range: 500..999|                       |
|   +----------+---------+        +----------+---------+                       |
|              |                             |                                 |
|              v                             v                                 |
+------------------------------------------------------------------------------+
| LEVEL 2: LEAF PAGES                                                           |
|                                                                              |
|   +----------+     +----------+     +----------+     +----------+             |
|   | leaf 01  | --> | leaf 02  | --> | leaf 03  | --> | leaf 04  |             |
|   | keys ... |     | keys ... |     | keys ... |     | keys ... |             |
|   +----------+     +----------+     +----------+     +----------+             |
|                                                                              |
|   Leaf pages are linked left-to-right for efficient range scans.              |
|                                                                              |
+------------------------------------------------------------------------------+
```

Point lookup:

```text
+------------------------------------------------------------------------------+
| POINT LOOKUP                                                                  |
+------------------------------------------------------------------------------+
| SQL                                                                           |
|   SELECT * FROM payments WHERE payment_id = 42;                               |
|                                                                              |
| Physical path                                                                 |
|                                                                              |
|   root page                                                                   |
|      |                                                                        |
|      v                                                                        |
|   internal page covering key 42                                               |
|      |                                                                        |
|      v                                                                        |
|   leaf page containing key 42                                                 |
|      |                                                                        |
|      v                                                                        |
|   index entry gives TID                                                       |
|      |                                                                        |
|      v                                                                        |
|   heap page                                                                   |
|      |                                                                        |
|      v                                                                        |
|   tuple visibility check                                                      |
|      |                                                                        |
|      v                                                                        |
|   row returned                                                                |
|                                                                              |
+------------------------------------------------------------------------------+
```

Range scan:

```text
+------------------------------------------------------------------------------+
| RANGE SCAN                                                                    |
+------------------------------------------------------------------------------+
| SQL                                                                           |
|   SELECT *                                                                    |
|   FROM payments                                                               |
|   WHERE payment_id BETWEEN 1000 AND 2000;                                     |
|                                                                              |
| Physical path                                                                 |
|                                                                              |
|   1. Traverse from root to first leaf containing key 1000.                    |
|   2. Scan entries inside that leaf.                                           |
|   3. Follow leaf-page link to next leaf.                                      |
|   4. Continue until key 2000 is passed.                                       |
|   5. Fetch heap pages unless index-only scan can avoid them.                  |
|                                                                              |
|   +----------+     +----------+     +----------+     +----------+             |
|   | leaf 12  | --> | leaf 13  | --> | leaf 14  | --> | leaf 15  |             |
|   | 1000..   |     | ...      |     | ...      |     | ..2000   |             |
|   +----------+     +----------+     +----------+     +----------+             |
|                                                                              |
+------------------------------------------------------------------------------+
```

B+Tree depth stays small because fanout is high.

```text
+------------------------------------------------------------------------------+
| FANOUT MATH                                                                   |
+------------------------------------------------------------------------------+
|                                                                              |
| Assume one 8KB index page holds about 400 key/pointer entries.                |
|                                                                              |
| Depth 1                                                                       |
|   root only                                                                   |
|   about 400 keys                                                              |
|                                                                              |
| Depth 2                                                                       |
|   root + leaves                                                               |
|   400 * 400 = 160,000 keys                                                    |
|                                                                              |
| Depth 3                                                                       |
|   root + internal + leaves                                                    |
|   400 * 400 * 400 = 64,000,000 keys                                           |
|                                                                              |
| Depth 4                                                                       |
|   about 25.6 billion keys                                                     |
|                                                                              |
+------------------------------------------------------------------------------+
```

Small depth is why B+Trees are powerful.

Small depth does not mean every lookup is cheap.

If leaf pages are bloated, cold, fragmented, or contended, latency still hurts.

---

# Part 6: Page Splits

A B+Tree leaf page has finite capacity.

When it is full and a new key belongs there, the engine must split the page.

```text
+------------------------------------------------------------------------------+
| BEFORE INSERT                                                                 |
+------------------------------------------------------------------------------+
|                                                                              |
| Leaf page L7 is full.                                                         |
|                                                                              |
|   +--------------------------------------------------------------+             |
|   | 10 | 20 | 30 | 40 | 50 | 60 | 70 | 80 | no free slot        |             |
|   +--------------------------------------------------------------+             |
|                                                                              |
| New key: 55                                                                   |
|                                                                              |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| AFTER SPLIT                                                                   |
+------------------------------------------------------------------------------+
|                                                                              |
| Left leaf page                                                                |
|   +---------------------------+                                              |
|   | 10 | 20 | 30 | 40         |                                              |
|   +---------------------------+                                              |
|                                                                              |
| Right leaf page                                                               |
|   +---------------------------+                                              |
|   | 50 | 55 | 60 | 70 | 80    |                                              |
|   +---------------------------+                                              |
|                                                                              |
| Parent page receives a separator key.                                         |
|                                                                              |
+------------------------------------------------------------------------------+
```

A split is not just a logical operation.

It is physical work.

```text
+------------------------------------------------------------------------------+
| PAGE SPLIT COST                                                               |
+------------------------------------------------------------------------------+
|                                                                              |
| Allocate or reuse another page.                                               |
| Move roughly half of entries.                                                 |
| Write old leaf page.                                                          |
| Write new leaf page.                                                          |
| Insert separator into parent page.                                            |
| Split parent too if parent is full.                                           |
| Generate WAL records for structural changes.                                  |
| Hold latches while the tree is made safe.                                     |
|                                                                              |
+------------------------------------------------------------------------------+
```

Insert pattern matters.

```text
+------------------------------------------------------------------------------+
| RANDOM KEYS                                                                   |
+------------------------------------------------------------------------------+
| Benefit                                                                       |
|   Spread concurrent writes across many leaves.                                |
|                                                                              |
| Cost                                                                          |
|   More random page access.                                                    |
|   More cache churn.                                                           |
|   More splits across the tree.                                                |
|   Worse locality for time-ordered access.                                     |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| SEQUENTIAL KEYS                                                               |
+------------------------------------------------------------------------------+
| Benefit                                                                       |
|   Excellent locality.                                                         |
|   Rightmost leaf usually stays hot in memory.                                 |
|                                                                              |
| Cost                                                                          |
|   High concurrency can concentrate on one rightmost leaf page.                |
|   Page-latch waits can appear.                                                |
+------------------------------------------------------------------------------+
```

A good primary key is not universally random or universally sequential.

It is a conscious choice of locality, contention, range access, storage size, operational behavior, and migration risk.

---

# Part 7: Right-Growing Index Contention

Sequential IDs such as BIGSERIAL grow at the right edge of the primary-key B+Tree.

This is usually efficient.

At extreme write concurrency, it can become a latch bottleneck.

```text
+------------------------------------------------------------------------------+
| RIGHT-GROWING PRIMARY KEY INDEX                                               |
+------------------------------------------------------------------------------+
|                                                                              |
|             root and internal pages                                           |
|                       |                                                       |
|                       v                                                       |
|              +----------------+                                               |
|              | rightmost leaf | <---- insert worker 1                         |
|              | newest keys    | <---- insert worker 2                         |
|              | hot page       | <---- insert worker 3                         |
|              +----------------+ <---- insert worker 4                         |
|                                                                              |
+------------------------------------------------------------------------------+
```

Lock and latch are different words for different beasts.

```text
+------------------------------------------------------------------------------+
| LOCK VS LATCH                                                                 |
+----------------------+-------------------------------------------------------+
| Lock                 | Protects logical data correctness.                    |
|                      | Example: two transactions update the same account row. |
+----------------------+-------------------------------------------------------+
| Latch                | Protects physical in-memory structure mutation.        |
|                      | Example: many inserts modify the same B+Tree leaf.     |
+----------------------+-------------------------------------------------------+
```

Symptoms:

```text
+------------------------------------------------------------------------------+
| RIGHTMOST-PAGE CONTENTION SYMPTOMS                                            |
+------------------------------------------------------------------------------+
|                                                                              |
| Insert throughput plateaus.                                                   |
| CPU may be below saturation.                                                  |
| Disk may not be saturated at first.                                           |
| Wait events show buffer-content, page-latch, or engine-specific latch waits. |
| Primary-key index is sequential and very hot.                                 |
| Adding more application workers does not help.                                |
|                                                                              |
+------------------------------------------------------------------------------+
```

Mitigations:

```text
+------------------------------------------------------------------------------+
| MITIGATION OPTIONS                                                            |
+-------------------------------+----------------------------------------------+
| Reduce unnecessary indexes    | Every insert updates fewer trees.             |
| Batch inserts                 | Fewer round trips and less overhead.          |
| Time-partition hot tables     | Smaller active indexes per partition.         |
| Use UUIDv7/ULID carefully     | Time locality with some write spread.         |
| Avoid panic key migrations    | Key changes are application/data migrations.  |
+-------------------------------+----------------------------------------------+
```

Do not blindly replace every sequential key with UUIDv4.

That can trade a latch problem for random I/O, worse cache locality, larger indexes, larger foreign keys, worse compression, and uglier range scans.

---

# Part 8: Fillfactor and HOT Updates

Fillfactor controls how tightly pages are packed.

A fillfactor of 100 packs pages tightly.

A fillfactor of 80 leaves about 20 percent room for future updates.

```text
+------------------------------------------------------------------------------+
| PAGE PACKED TOO TIGHTLY                                                       |
+------------------------------------------------------------------------------+
|                                                                              |
|   +----------+----------+----------+----------+----------+                    |
|   | tuple 1  | tuple 2  | tuple 3  | tuple 4  | tuple 5  |                    |
|   +----------+----------+----------+----------+----------+                    |
|                                                                              |
|   Free space: almost none                                                     |
|                                                                              |
|   UPDATE needs a new tuple version.                                           |
|   New version cannot fit on this page.                                        |
|   Indexes may need new entries.                                               |
|                                                                              |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| PAGE WITH UPDATE ROOM                                                         |
+------------------------------------------------------------------------------+
|                                                                              |
|   +----------+----------+----------+----------------------+                    |
|   | tuple 1  | tuple 2  | tuple 3  | free space           |                    |
|   +----------+----------+----------+----------------------+                    |
|                                                                              |
|   UPDATE needs a new tuple version.                                           |
|   New version can fit on this page.                                           |
|   HOT update may be possible.                                                 |
|                                                                              |
+------------------------------------------------------------------------------+
```

HOT means Heap-Only Tuple.

HOT avoids index rewrites when two conditions hold.

```text
+------------------------------------------------------------------------------+
| HOT CONDITIONS                                                                |
+------------------------------------------------------------------------------+
|                                                                              |
| 1. The update does not modify any indexed column.                             |
| 2. The new tuple version fits on the same heap page as the old version.       |
|                                                                              |
+------------------------------------------------------------------------------+
```

HOT chain:

```text
+------------------------------------------------------------------------------+
| HOT UPDATE CHAIN                                                              |
+------------------------------------------------------------------------------+
|                                                                              |
| B+Tree entry                                                                  |
|   key = payment_id 42                                                         |
|   TID = page 10, slot 1                                                       |
|            |                                                                 |
|            v                                                                 |
| +--------------------------------------------------------------------------+ |
| | heap page 10                                                             | |
| |                                                                          | |
| | slot 1 -> old tuple                                                      | |
| |           status='authorized'                                             | |
| |           xmax=200                                                        | |
| |           HOT next -> slot 2                                              | |
| |                                                                          | |
| | slot 2 -> new tuple                                                       | |
| |           status='captured'                                               | |
| |           xmax=0                                                          | |
| |                                                                          | |
| +--------------------------------------------------------------------------+ |
|                                                                              |
+------------------------------------------------------------------------------+
```

Non-HOT update cost:

```text
+------------------------------------------------------------------------------+
| NON-HOT UPDATE WITH FIVE INDEXES                                              |
+------------------------------------------------------------------------------+
|                                                                              |
| Logical operation                                                             |
|   UPDATE payments SET status='captured' WHERE payment_id=42;                  |
|                                                                              |
| Physical work                                                                 |
|   write heap page                                                             |
|   write primary-key index page                                                |
|   write customer_id index page                                                |
|   write status index page                                                     |
|   write merchant_id index page                                                |
|   write updated_at index page                                                 |
|   generate WAL for heap and index changes                                     |
|                                                                              |
+------------------------------------------------------------------------------+
```

HOT update cost:

```text
+------------------------------------------------------------------------------+
| HOT UPDATE                                                                    |
+------------------------------------------------------------------------------+
|                                                                              |
| Logical operation                                                             |
|   UPDATE non-indexed field                                                    |
|                                                                              |
| Physical work                                                                 |
|   write heap page                                                             |
|   keep existing index entries                                                 |
|   follow HOT chain during lookup if needed                                    |
|                                                                              |
+------------------------------------------------------------------------------+
```

HOT failure conditions:

```text
+------------------------------------------------------------------------------+
| WHY HOT FAILS                                                                 |
+------------------------------------------------------------------------------+
|                                                                              |
| Updated column is indexed.                                                    |
| Heap page has no free space.                                                  |
| Tuple grows too large for the page.                                           |
| Vacuum is behind and HOT chains are not pruned.                               |
| Long-running snapshots prevent cleanup.                                       |
|                                                                              |
+------------------------------------------------------------------------------+
```

Fillfactor warning:

```text
+------------------------------------------------------------------------------+
| FILLFACTOR IS NOT RETROACTIVE MAGIC                                           |
+------------------------------------------------------------------------------+
|                                                                              |
| ALTER TABLE payments SET (fillfactor = 80);                                   |
|                                                                              |
| This changes future page packing.                                             |
| It does not repack existing pages.                                            |
| Applying the new physical shape to old data requires rewrite, repack, or      |
| rebuild work. That work can cause an outage if run at the wrong time.         |
|                                                                              |
+------------------------------------------------------------------------------+
```

SRE proof point:

```sql
SELECT relname,
       n_tup_upd,
       n_tup_hot_upd,
       round(100.0 * n_tup_hot_upd / nullif(n_tup_upd, 0), 2) AS hot_pct,
       n_dead_tup
FROM pg_stat_user_tables
WHERE relname = 'payments';
```

Interpretation:

```text
high n_tup_upd + low hot_pct + rising n_dead_tup = update amplification problem
```

---

# Part 9: Visibility Map, Free Space Map, and Index-Only Scans

A covering index contains all columns needed by a query.

That does not automatically mean the heap can be skipped.

The executor still needs to know whether the tuple version is visible to the current transaction.

PostgreSQL uses a visibility map for this.

```text
+------------------------------------------------------------------------------+
| INDEX-ONLY SCAN FAST PATH                                                     |
+------------------------------------------------------------------------------+
|                                                                              |
| Query                                                                         |
|   SELECT payment_id, status                                                   |
|   FROM payments                                                               |
|   WHERE merchant_id = 123;                                                    |
|                                                                              |
| Covering index                                                                |
|   (merchant_id, payment_id, status)                                           |
|                                                                              |
| Flow                                                                          |
|                                                                              |
|   B+Tree leaf entry                                                           |
|          |                                                                    |
|          v                                                                    |
|   check visibility-map bit for heap page                                      |
|          |                                                                    |
|          v                                                                    |
|   bit = all-visible                                                           |
|          |                                                                    |
|          v                                                                    |
|   return columns from index without heap fetch                                |
|                                                                              |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| INDEX-ONLY SCAN SLOW PATH                                                     |
+------------------------------------------------------------------------------+
|                                                                              |
|   B+Tree leaf entry                                                           |
|          |                                                                    |
|          v                                                                    |
|   check visibility-map bit for heap page                                      |
|          |                                                                    |
|          v                                                                    |
|   bit = not all-visible                                                       |
|          |                                                                    |
|          v                                                                    |
|   fetch heap page                                                             |
|          |                                                                    |
|          v                                                                    |
|   inspect tuple xmin/xmax visibility                                          |
|          |                                                                    |
|          v                                                                    |
|   return row if visible                                                       |
|                                                                              |
+------------------------------------------------------------------------------+
```

Visibility map:

```text
+------------------------------------------------------------------------------+
| VISIBILITY MAP                                                                |
+------------+----------------------+------------------------------------------+
| Heap page  | all-visible bit      | Meaning                                  |
+------------+----------------------+------------------------------------------+
| page 100   | 1                    | heap fetch can be skipped                |
| page 101   | 1                    | heap fetch can be skipped                |
| page 102   | 0                    | must visit heap for visibility           |
| page 103   | 0                    | recent writes or vacuum lag              |
+------------+----------------------+------------------------------------------+
```

Free space map:

```text
+------------------------------------------------------------------------------+
| FREE SPACE MAP                                                                |
+------------------------------------------------------------------------------+
|                                                                              |
| Problem                                                                       |
|   When inserting or updating, the engine needs to find a page with room.      |
|                                                                              |
| Solution                                                                      |
|   Track approximate free space per heap page.                                 |
|                                                                              |
| Operational consequence                                                       |
|   Poor free-space distribution and update-heavy churn can increase page       |
|   allocation, fragmentation, and bloat.                                       |
|                                                                              |
+------------------------------------------------------------------------------+
```

Broken index-only scan:

```text
+------------------------------------------------------------------------------+
| PLAN NAME VS PHYSICAL REALITY                                                 |
+------------------------------------------------------------------------------+
|                                                                              |
| Plan node       Index Only Scan                                               |
| Actual behavior high heap fetch count                                         |
| Cause           visibility-map bits are not all-visible                       |
| Root reasons    recent writes, vacuum lag, long transactions                  |
|                                                                              |
+------------------------------------------------------------------------------+
```

Proof:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT payment_id, status
FROM payments
WHERE merchant_id = 123;
```

Red flag:

```text
Index Only Scan using payments_merchant_covering_idx
  Heap Fetches: 281943
  Buffers: shared hit=12044 read=92211
```

Interpretation:

The optimizer chose an index-only scan node.

The engine still visited the heap many times.

Fixing vacuum and snapshot pressure may matter more than adding another covering index.

---

# Part 10: TOAST and Wide Rows

A page cannot hold arbitrarily large values.

PostgreSQL uses TOAST for oversized attributes.

TOAST means The Oversized-Attribute Storage Technique.

Large values may be compressed or stored out-of-line in a hidden TOAST table.

```text
+------------------------------------------------------------------------------+
| WIDE ROW WITH OUT-OF-LINE VALUE                                               |
+------------------------------------------------------------------------------+
|                                                                              |
| Main heap table: payment_events                                               |
|                                                                              |
| +------------+------------+------------------------------------------------+ |
| | id         | status     | metadata                                       | |
| +------------+------------+------------------------------------------------+ |
| | 42         | failed     | TOAST pointer -> chunk_id 998877              | |
| +------------+------------+------------------------------------------------+ |
|                                                                              |
|                                  |                                           |
|                                  v                                           |
|                                                                              |
| Hidden TOAST table                                                            |
|                                                                              |
| +----------+-----------+------------+----------------------+                 |
| | chunk_id | chunk_seq | chunk_len  | chunk_data           |                 |
| +----------+-----------+------------+----------------------+                 |
| | 998877   | 0         | 1996       | bytes...             |                 |
| | 998877   | 1         | 1996       | bytes...             |                 |
| | 998877   | 2         | 1996       | bytes...             |                 |
| | 998877   | 3         | 1996       | bytes...             |                 |
| +----------+-----------+------------+----------------------+                 |
|                                                                              |
+------------------------------------------------------------------------------+
```

Fast query:

```sql
SELECT id, status
FROM payment_events
WHERE id = 42;
```

The engine can often ignore the large metadata value.

Dangerous query:

```sql
SELECT *
FROM payment_events
WHERE status = 'failed';
```

Hidden work:

```text
+------------------------------------------------------------------------------+
| SELECT * OVER TOAST-HEAVY ROWS                                                |
+------------------------------------------------------------------------------+
|                                                                              |
| heap page read                                                                |
|      |                                                                       |
|      v                                                                       |
| find TOAST pointer                                                            |
|      |                                                                       |
|      v                                                                       |
| read TOAST chunks                                                             |
|      |                                                                       |
|      v                                                                       |
| decompress chunks                                                             |
|      |                                                                       |
|      v                                                                       |
| reassemble value                                                              |
|      |                                                                       |
|      v                                                                       |
| send large row over network                                                   |
|      |                                                                       |
|      v                                                                       |
| ORM hydrates huge object                                                      |
|                                                                              |
+------------------------------------------------------------------------------+
```

TOAST math:

```text
+------------------------------------------------------------------------------+
| TOAST CHUNK MATH                                                              |
+------------------------------------------------------------------------------+
|                                                                              |
| metadata value size       5MB                                                 |
| approximate chunk size    2KB                                                 |
| chunk rows                about 2,500                                         |
|                                                                              |
| Query returning 1,000 rows with 5MB metadata each:                            |
|   about 5GB logical payload before client/object overhead                     |
|                                                                              |
| The WHERE clause can be selective and still create a result-size incident.    |
|                                                                              |
+------------------------------------------------------------------------------+
```

Symptoms:

```text
+------------------------------------------------------------------------------+
| TOAST CLIFF SYMPTOMS                                                          |
+------------------------------------------------------------------------------+
|                                                                              |
| CPU rises from decompression and serialization.                               |
| Network output rises.                                                         |
| Query result bytes explode.                                                   |
| Application memory rises.                                                     |
| ORM p95 latency rises.                                                        |
| WHERE clause looks selective, but SELECT * is the trap.                       |
|                                                                              |
+------------------------------------------------------------------------------+
```

Mitigation:

```text
+------------------------------------------------------------------------------+
| TOAST MITIGATION                                                              |
+------------------------------------------------------------------------------+
|                                                                              |
| Select only required columns.                                                 |
| Split large payloads into side tables when common queries do not need them.   |
| Store blobs in object storage when relational filtering is unnecessary.        |
| Review ORM defaults that silently fetch all columns.                          |
| Add query result byte metrics, not only query count metrics.                  |
|                                                                              |
+------------------------------------------------------------------------------+
```

---

# Part 11: Bloat, Vacuum, and REINDEX Risk

B+Tree indexes and heap tables do not automatically return to perfect shape after churn.

Heavy UPDATE and DELETE workloads can leave dead tuples, dead index entries, low-density pages, and inefficient tree shape.

```text
+------------------------------------------------------------------------------+
| HEALTHY INDEX                                                                 |
+------------------------------------------------------------------------------+
|                                                                              |
|   +------------+  +------------+  +------------+                              |
|   | page 1     |  | page 2     |  | page 3     |                              |
|   | 85% full   |  | 88% full   |  | 82% full   |                              |
|   +------------+  +------------+  +------------+                              |
|                                                                              |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| BLOATED INDEX                                                                 |
+------------------------------------------------------------------------------+
|                                                                              |
|   +------------+  +------------+  +------------+  +------------+              |
|   | page 1     |  | page 2     |  | page 3     |  | page 4     |              |
|   | 12% full   |  | 18% full   |  | 09% full   |  | 15% full   |              |
|   +------------+  +------------+  +------------+  +------------+              |
|                                                                              |
|   Same logical key count. More pages. More cache pressure.                   |
|                                                                              |
+------------------------------------------------------------------------------+
```

Why bloat hurts:

```text
+------------------------------------------------------------------------------+
| BLOAT COST                                                                    |
+------------------------------------------------------------------------------+
|                                                                              |
| More pages must be cached for the same logical data.                          |
| More disk reads occur on cache misses.                                        |
| More CPU is spent traversing and comparing entries.                           |
| Backups and replicas move more bytes.                                         |
| Checkpoints and maintenance touch more pages.                                 |
| REINDEX or table rewrite needs extra disk and I/O.                            |
|                                                                              |
+------------------------------------------------------------------------------+
```

Vacuum can mark space reusable.

It does not always compact the structure into an ideal shape.

REINDEX can rebuild an index into a cleaner structure.

But REINDEX is not harmless.

```text
+------------------------------------------------------------------------------+
| REINDEX CONCURRENTLY RISK                                                     |
+------------------------------------------------------------------------------+
|                                                                              |
| What it helps                                                                 |
|   Reduces blocking compared with plain rebuild.                               |
|                                                                              |
| What it still costs                                                           |
|   Builds another copy of the index.                                           |
|   Requires disk headroom.                                                     |
|   Generates heavy read I/O.                                                   |
|   Generates heavy write I/O and WAL.                                          |
|   Can run for a long time under write load.                                   |
|   Can worsen an already saturated system.                                     |
|                                                                              |
+------------------------------------------------------------------------------+
```

Do not treat CONCURRENTLY as cheap.

It means reduced blocking, not reduced physics.

---

## 3. Production Patterns and Failure Modes

The Cassandra module teaches compaction, tombstones, repair, and read amplification through named failure modes.

This B-Tree module uses the same standard.

### Failure Mode 1: Buffer Pool Thrashing

```text
+------------------------------------------------------------------------------+
| BUFFER POOL THRASHING                                                         |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   API p99 jumps from 12ms to 900ms. CPU drops. Disk reads spike.              |
|                                                                              |
| Cause                                                                         |
|   A large scan pulls cold heap pages into memory and evicts hot index and      |
|   heap pages used by live traffic.                                            |
|                                                                              |
| Proof                                                                         |
|   EXPLAIN BUFFERS shows high read counts. Database read IOPS spike.           |
|   Previously hot queries start doing physical reads.                          |
|                                                                              |
| Mitigation                                                                    |
|   Cancel or throttle scan. Add statement timeout. Batch background work.       |
|   Do not start another full-table job during cache recovery.                  |
+------------------------------------------------------------------------------+
```

### Failure Mode 2: Non-HOT Update Storm

```text
+------------------------------------------------------------------------------+
| NON-HOT UPDATE STORM                                                          |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   A status update causes index write I/O, WAL, bloat, and replica lag far     |
|   beyond expected row count.                                                  |
|                                                                              |
| Cause                                                                         |
|   Updated column is indexed, or page free space is exhausted, so HOT updates   |
|   are impossible.                                                             |
|                                                                              |
| Proof                                                                         |
|   Low HOT update ratio. High index growth. High WAL per updated row.          |
|                                                                              |
| Mitigation                                                                    |
|   Remove unnecessary indexes on mutable columns. Lower fillfactor for future   |
|   pages. Use chunked updates. Move mutable state to narrow table.             |
+------------------------------------------------------------------------------+
```

### Failure Mode 3: Rightmost Leaf Contention

```text
+------------------------------------------------------------------------------+
| RIGHTMOST LEAF CONTENTION                                                     |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   Insert throughput plateaus. Waits show page-latch or buffer-content waits.  |
|                                                                              |
| Cause                                                                         |
|   Sequential primary key concentrates concurrent inserts on the rightmost      |
|   leaf page.                                                                  |
|                                                                              |
| Proof                                                                         |
|   Sequential key, high insert concurrency, latch waits, hot primary index.     |
|                                                                              |
| Mitigation                                                                    |
|   Reduce unnecessary indexes. Batch writes. Review ID strategy. Partition      |
|   only when justified by access pattern and operations.                       |
+------------------------------------------------------------------------------+
```

### Failure Mode 4: Broken Index-Only Scan

```text
+------------------------------------------------------------------------------+
| BROKEN INDEX-ONLY SCAN                                                        |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   Plan says Index Only Scan, but latency and heap reads are high.             |
|                                                                              |
| Cause                                                                         |
|   Visibility-map bits are not all-visible due to recent writes, vacuum lag,    |
|   or long-running snapshots.                                                  |
|                                                                              |
| Proof                                                                         |
|   EXPLAIN ANALYZE BUFFERS shows high Heap Fetches.                            |
|                                                                              |
| Mitigation                                                                    |
|   Fix vacuum lag. Remove long transactions. Tune autovacuum. Do not add       |
|   another covering index until visibility is understood.                      |
+------------------------------------------------------------------------------+
```

### Failure Mode 5: TOAST Decompression Cliff

```text
+------------------------------------------------------------------------------+
| TOAST DECOMPRESSION CLIFF                                                     |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   CPU spikes. Query result bytes explode. Application memory grows.           |
|                                                                              |
| Cause                                                                         |
|   SELECT * over wide rows forces TOAST chunk reads, decompression, reassembly, |
|   network transfer, and ORM hydration.                                        |
|                                                                              |
| Proof                                                                         |
|   Removing wide payload column makes query fast. Result size dominates.        |
|                                                                              |
| Mitigation                                                                    |
|   Select only needed columns. Split wide payloads. Review ORM behavior.       |
+------------------------------------------------------------------------------+
```

### Failure Mode 6: REINDEX During a Hot Incident

```text
+------------------------------------------------------------------------------+
| REINDEX DURING SATURATION                                                     |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   An attempt to fix bloat makes I/O saturation worse.                         |
|                                                                              |
| Cause                                                                         |
|   REINDEX CONCURRENTLY reduces blocking, but still builds another physical    |
|   index and generates heavy I/O and WAL.                                      |
|                                                                              |
| Proof                                                                         |
|   Disk headroom falls. Write IOPS rise. WAL rises. Replica lag grows.          |
|                                                                              |
| Mitigation                                                                    |
|   Stop if unsafe. Reschedule during maintenance. Verify disk headroom.         |
|   Rebuild one index at a time.                                                |
+------------------------------------------------------------------------------+
```

### Failure Mode 7: Vacuum Starvation

```text
+------------------------------------------------------------------------------+
| VACUUM STARVATION                                                             |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   Dead tuples rise. Index-only scans degrade. Table bloat grows.              |
|                                                                              |
| Cause                                                                         |
|   Autovacuum cannot keep up, or long-running transactions prevent cleanup.     |
|                                                                              |
| Proof                                                                         |
|   n_dead_tup rises. Old transaction age rises. Heap Fetches rise.             |
|                                                                              |
| Mitigation                                                                    |
|   End idle-in-transaction sessions. Tune autovacuum per table. Reduce update  |
|   churn. Schedule bloat cleanup after pressure is controlled.                 |
+------------------------------------------------------------------------------+
```

### Failure Mode 8: Full-Page Write Surge After Checkpoint

```text
+------------------------------------------------------------------------------+
| FULL-PAGE WRITE SURGE                                                         |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   WAL generation spikes far beyond logical row-change size.                   |
|                                                                              |
| Cause                                                                         |
|   First modification to many pages after checkpoint logs full-page images for  |
|   torn-page protection.                                                       |
|                                                                              |
| Proof                                                                         |
|   WAL rate spikes immediately after checkpoint plus broad page updates.        |
|                                                                              |
| Mitigation                                                                    |
|   Chunk writes. Avoid huge post-checkpoint batch jobs. Tune checkpointing in   |
|   Topic 4. Add WAL budget to batch controller.                                |
+------------------------------------------------------------------------------+
```

---

## 4. Hands-On Exercise: Inspect Pages and Bloat

This exercise uses PostgreSQL because it exposes page structures well.

```bash
# Start PostgreSQL.
docker run --name pg-btree-pages \
  -e POSTGRES_PASSWORD=pass \
  -p 5432:5432 \
  -d postgres:16

# Open psql.
docker exec -it pg-btree-pages psql -U postgres
```

Enable inspection extensions:

```sql
CREATE EXTENSION pageinspect;
CREATE EXTENSION pgstattuple;
```

Create a table:

```sql
CREATE TABLE internals_test (
  id INT PRIMARY KEY,
  status TEXT,
  payload TEXT
);

INSERT INTO internals_test
SELECT generate_series(1, 1000), 'new', 'small payload';
```

Inspect heap page slots:

```sql
SELECT lp, lp_off, lp_len, t_xmin, t_xmax
FROM heap_page_items(get_raw_page('internals_test', 0))
LIMIT 10;
```

Update and inspect tuple versions:

```sql
UPDATE internals_test
SET status = 'paid'
WHERE id = 1;

SELECT lp, lp_off, lp_len, t_xmin, t_xmax
FROM heap_page_items(get_raw_page('internals_test', 0))
LIMIT 10;
```

Check table-level dead tuple statistics:

```sql
SELECT *
FROM pgstattuple('internals_test');
```

Check relation sizes:

```sql
SELECT
  pg_size_pretty(pg_relation_size('internals_test')) AS heap_size,
  pg_size_pretty(pg_indexes_size('internals_test')) AS indexes_size;
```

Inspect index root/metadata depending extension support:

```sql
SELECT *
FROM bt_metap('internals_test_pkey');
```

Index-only scan check:

```sql
CREATE INDEX internals_status_idx ON internals_test(status, id);
VACUUM internals_test;

EXPLAIN (ANALYZE, BUFFERS)
SELECT id
FROM internals_test
WHERE status = 'paid';
```

What each command proves:

```text
+------------------------------------------------------------------------------+
| COMMAND INTERPRETATION                                                        |
+----------------------------------+-------------------------------------------+
| heap_page_items                  | page slots and tuple version metadata      |
| pgstattuple                      | dead tuple and free-space proportions      |
| pg_relation_size                 | heap physical size                         |
| pg_indexes_size                  | index physical size                        |
| bt_metap                         | B+Tree metadata                            |
| EXPLAIN ANALYZE BUFFERS         | physical buffer reads/hits and heap fetches|
+----------------------------------+-------------------------------------------+
```

The goal is not to memorize extension functions.

The goal is to see rows become pages.

---

## 5. SRE Scenario: The Merchant Ledger Page Storm

This scenario mirrors the Cassandra module's level of operational density.

It has preconditions, trigger, metrics, red herrings, root cause chain, unsafe mitigations, safe mitigations, and redesign.

### System Context

MegaPay processes card payments for global merchants.

The payment API is tier 0.

Every accepted payment must be durable, auditable, and reconcilable.

The system cannot double-capture, lose captures, silently use stale payment state, or confuse dashboard freshness with ledger truth.

```text
+------------------------------------------------------------------------------+
| DATABASE TOPOLOGY                                                             |
+---------------------------+--------------------------------------------------+
| Engine                    | PostgreSQL 16                                    |
| Topology                  | primary + two async replicas                    |
| Primary instance          | 96 vCPU, 768GB RAM                              |
| Storage                   | cloud block volume with provisioned throughput  |
| Connection pool           | PgBouncer transaction pooling                   |
| Normal payment API p99    | 18ms                                             |
| Normal WAL generation     | 120MB/s                                          |
| Normal replica lag        | less than 200ms                                  |
| Normal HOT update ratio   | about 70% on mutable state tables               |
+---------------------------+--------------------------------------------------+
```

### Table Shape

```sql
CREATE TABLE payment_events_2026_05 (
  id BIGSERIAL PRIMARY KEY,
  merchant_id BIGINT NOT NULL,
  customer_id BIGINT NOT NULL,
  status TEXT NOT NULL,
  amount_cents BIGINT NOT NULL,
  currency TEXT NOT NULL,
  processor_ref TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
```

Indexes:

```sql
CREATE INDEX payev_merchant_created_idx
ON payment_events_2026_05 (merchant_id, created_at DESC);

CREATE INDEX payev_status_created_idx
ON payment_events_2026_05 (status, created_at DESC);

CREATE INDEX payev_customer_created_idx
ON payment_events_2026_05 (customer_id, created_at DESC);

CREATE INDEX payev_processor_ref_idx
ON payment_events_2026_05 (processor_ref);
```

Table reality:

```text
+------------------------------------------------------------------------------+
| TABLE REALITY                                                                 |
+-----------------------------------+------------------------------------------+
| Partition size                    | 9.4TB                                    |
| Row count                         | 8.1 billion                              |
| Normal insert rate                | 14,000 rows/sec                          |
| Normal read rate                  | 38,000 queries/sec                       |
| metadata column                   | often TOASTed for failed attempts        |
| status transitions                | authorized -> captured -> settled        |
| hot access window                 | newest 48 hours                          |
| painful design smell              | mutable status is indexed                |
+-----------------------------------+------------------------------------------+
```

The core design flaw:

```text
+------------------------------------------------------------------------------+
| DESIGN FLAW                                                                   |
+------------------------------------------------------------------------------+
|                                                                              |
| payment_events is physically shaped like an append-heavy audit table.         |
| The application uses it like a mutable current-state table.                   |
|                                                                              |
| status changes frequently.                                                    |
| status is indexed.                                                            |
| updated_at changes frequently.                                                |
| metadata is wide and often TOASTed.                                           |
|                                                                              |
| Result                                                                        |
|   ordinary business transitions create heap churn, index churn, WAL,          |
|   visibility-map churn, vacuum debt, and bloat.                              |
|                                                                              |
+------------------------------------------------------------------------------+
```

### Trigger

Finance deploys a faster settlement cron job.

It runs at 02:00, shortly after a checkpoint window.

```sql
UPDATE payment_events_2026_05
SET status = 'settled', updated_at = now()
WHERE status = 'captured'
  AND created_at < now() - interval '2 days'
  AND merchant_id IN (
    SELECT merchant_id
    FROM settlement_merchants
    WHERE settlement_tier = 'daily'
  );
```

The job matches 67 million rows.

Rows are scattered across many heap pages.

The updated `status` column is indexed.

`updated_at` also changes.

Many rows contain TOASTed metadata.

There is no chunking, statement timeout, replica-lag guard, WAL budget, API-latency guard, or kill switch.

### Timeline

```text
+----------+-------------------------------------------------------------------+
| Time     | Event                                                             |
+----------+-------------------------------------------------------------------+
| 01:58:00 | Checkpoint completes.                                             |
| 02:00:00 | Settlement UPDATE starts.                                         |
| 02:00:45 | WAL jumps from 120MB/s to 1.7GB/s.                                |
| 02:01:10 | Buffer read rate spikes.                                          |
| 02:01:40 | Payment API p99 moves from 18ms to 420ms.                         |
| 02:02:15 | Replica lag reaches 9s, then 22s.                                 |
| 02:02:40 | PgBouncer waiting clients rise.                                   |
| 02:03:00 | Merchant dashboard queries time out.                              |
| 02:03:25 | Payment authorization p99 crosses 1.8s.                           |
| 02:03:50 | Application logs show Redis timeouts.                             |
| 02:04:20 | DB waits show BufferContent and WALWrite.                         |
| 02:05:00 | Replica lag reaches 84s.                                          |
| 02:05:15 | Fraud service begins reading stale replica data.                  |
| 02:06:00 | API gateway begins returning 503s.                                |
+----------+-------------------------------------------------------------------+
```

Dashboard snapshot:

```text
+------------------------------------------------------------------------------+
| SIGNALS                                                                       |
+-------------------------------+----------------------+-----------------------+
| Signal                        | Baseline             | Incident              |
+-------------------------------+----------------------+-----------------------+
| Payment API p99               | 18ms                 | 1.8s                  |
| WAL generation                | 120MB/s              | 1.7GB/s               |
| Replica lag                   | < 200ms              | 84s and growing       |
| DB read IOPS                  | 22K                  | 190K                  |
| DB write throughput           | 450MB/s              | volume cap            |
| PgBouncer waiting clients     | 0                    | 2,800                 |
| Index cache hit ratio         | 99.6%                | 91.2%                 |
| Heap read blocks/sec          | normal               | 8x normal             |
| Dead tuples                   | stable               | rising quickly        |
| HOT update ratio              | 76%                  | 4%                    |
| Query result bytes            | normal               | 6x normal             |
+-------------------------------+----------------------+-----------------------+
```

Wait events:

```text
+------------------------------------------------------------------------------+
| WAIT EVENTS                                                                   |
+---------------------------+--------------------------------------------------+
| WALWrite                  | commits and WAL flush under pressure             |
| DataFileRead              | cold heap and index page reads                   |
| BufferContent             | page-level latch contention                      |
| ClientRead                | clients slow or backed up                        |
| Lock: transactionid       | secondary symptom from long update visibility    |
+---------------------------+--------------------------------------------------+
```

Red herrings:

```text
+------------------------------------------------------------------------------+
| RED HERRINGS                                                                  |
+-----------------------------+------------------------------------------------+
| Redis timeout logs          | app/network starvation, not Redis root cause   |
| CPU not fully saturated     | page/I/O/latch problem, not pure CPU problem   |
| Replicas still accepting    | data is stale, not correctness-safe            |
| Query plan uses index       | index access can still touch millions of pages |
| Merchant dashboards failing | symptom, not authority failure                 |
+-----------------------------+------------------------------------------------+
```

---

## 6. Scenario Answer: Root Cause Cascade

The settlement job looked like one SQL statement.

Physically, it was a page storm.

```text
+------------------------------------------------------------------------------+
| ROOT CAUSE CASCADE                                                            |
+------------------------------------------------------------------------------+
|                                                                              |
| 1. Unbounded settlement UPDATE matched 67 million rows.                       |
|                                                                              |
| 2. Rows were scattered across many heap pages.                                |
|    Cold historical pages entered the buffer pool.                             |
|                                                                              |
| 3. Hot checkout pages were evicted.                                           |
|    Live API reads became physical reads.                                      |
|                                                                              |
| 4. status was indexed, so updates were non-HOT.                               |
|    Each logical update touched heap plus multiple index structures.           |
|                                                                              |
| 5. updated_at changed too.                                                    |
|    More tuple versions and index maintenance appeared.                        |
|                                                                              |
| 6. Visibility-map bits flipped away from all-visible on many pages.           |
|    Existing index-only scans began fetching heap pages.                       |
|                                                                              |
| 7. The job started soon after checkpoint.                                     |
|    First modifications to many pages created full-page-write pressure.        |
|                                                                              |
| 8. Live inserts continued on BIGSERIAL primary key.                           |
|    New inserts fought over hot rightmost B+Tree leaf pages.                   |
|                                                                              |
| 9. WAL and storage throughput saturated.                                      |
|    Commit latency rose and replicas fell behind.                              |
|                                                                              |
| 10. PgBouncer filled because DB sessions held connections longer.             |
|                                                                              |
| 11. API gateway returned 503s because database access became slow and scarce. |
|                                                                              |
+------------------------------------------------------------------------------+
```

This was not one failure.

It was several mechanisms colliding.

```text
+------------------------------------------------------------------------------+
| MECHANISM COLLISION MAP                                                       |
+-------------------------+----------------------------------------------------+
| Mechanism               | How it hurt                                       |
+-------------------------+----------------------------------------------------+
| Slotted pages           | many tuple versions and dead space                |
| B+Tree indexes          | non-HOT updates touched multiple indexes          |
| Page latches            | live inserts fought over hot leaf pages           |
| Visibility map          | index-only scans degraded into heap fetches       |
| Buffer pool             | cold scan evicted hot checkout pages              |
| TOAST                   | dashboard SELECT * amplified result cost          |
| Full-page writes        | post-checkpoint page changes amplified WAL        |
| Replication             | replicas could not replay WAL fast enough         |
| PgBouncer               | slow DB work exhausted scarce connections         |
+-------------------------+----------------------------------------------------+
```

Full-page write math:

```text
+------------------------------------------------------------------------------+
| FULL-PAGE WRITE MATH                                                          |
+------------------------------------------------------------------------------+
|                                                                              |
| Logical change                                                                |
|   status: 'captured' -> 'settled'                                             |
|   maybe tens of bytes                                                         |
|                                                                              |
| Physical protection                                                           |
|   first modification to a page after checkpoint can log full-page image        |
|                                                                              |
| Approximation                                                                 |
|   210,000 distinct pages modified per second                                  |
|   210,000 * 8KB = about 1.7GB/s                                                |
|                                                                              |
| Meaning                                                                       |
|   The application changed small fields.                                       |
|   The storage engine protected many full pages.                               |
|                                                                              |
+------------------------------------------------------------------------------+
```

Why inserts waited on BufferContent while storage was overloaded:

```text
+------------------------------------------------------------------------------+
| LATCH WAIT EXPLANATION                                                        |
+------------------------------------------------------------------------------+
|                                                                              |
| BIGSERIAL sends live inserts to the right edge of the primary-key B+Tree.     |
| Many workers need to mutate the same hot leaf page.                           |
| A latch protects the in-memory page while it is modified.                     |
| Under normal I/O, the latch is held briefly.                                  |
| Under WAL/storage pressure, critical paths stretch.                           |
| Workers pile up on the page latch.                                            |
|                                                                              |
| The visible wait is a memory latch.                                           |
| The underlying amplifier is page design plus storage saturation.              |
|                                                                              |
+------------------------------------------------------------------------------+
```

---

## 7. Incident Response

### Minute 0 to 2: Establish command and stop guessing

Incident message:

```text
We have a database-primary saturation event. Redis errors are secondary until proven otherwise. Do not restart services. Do not fail over. I am identifying top database writers, wait events, and replica-lag risk now.
```

Find the offender:

```sql
SELECT pid,
       now() - query_start AS age,
       state,
       wait_event_type,
       wait_event,
       left(query, 180) AS query
FROM pg_stat_activity
WHERE state <> 'idle'
ORDER BY age DESC
LIMIT 20;
```

Expected smoking gun:

```text
UPDATE payment_events_2026_05
SET status = 'settled', updated_at = now()
WHERE status = 'captured' ...
```

### Minute 2 to 4: Communicate rollback penalty before killing

Stakeholder warning:

```text
I am stopping the settlement UPDATE. The database will not recover instantly.
If the transaction already changed many rows, PostgreSQL must abort that work
and cleanup/vacuum debt will remain. WAL and I/O pressure should fall gradually,
not instantly. Do not restart the primary unless we discover an independent
database failure. A restart can lengthen recovery and add uncertainty.
```

Cancel first:

```sql
SELECT pg_cancel_backend(<pid>);
```

Terminate only if needed:

```sql
SELECT pg_terminate_backend(<pid>);
```

### Minute 4 to 8: Prevent automatic re-entry

```text
Disable settlement cron.
Disable scheduler retries.
Pause non-critical exports touching payment_events_2026_05.
Freeze schema/index maintenance.
Stop ad hoc dashboard backfills.
```

### Minute 8 to 15: Protect correctness

```text
Do not route payment correctness reads to replicas with 84s lag.
Fraud and ledger workflows must use primary or freshness-checked paths.
Merchant dashboards may degrade to stale-with-banner if approved.
Analytics exports can pause.
Payment authorization must not silently use stale state.
```

### Minute 15 to 30: Watch recovery shape

Replica lag:

```sql
SELECT now() - pg_last_xact_replay_timestamp() AS replica_lag;
```

Background writer and checkpoint pressure:

```sql
SELECT checkpoints_timed,
       checkpoints_req,
       buffers_checkpoint,
       buffers_clean,
       buffers_backend
FROM pg_stat_bgwriter;
```

HOT ratio and dead tuples:

```sql
SELECT relname,
       n_tup_upd,
       n_tup_hot_upd,
       round(100.0 * n_tup_hot_upd / nullif(n_tup_upd, 0), 2) AS hot_pct,
       n_dead_tup
FROM pg_stat_user_tables
WHERE relname = 'payment_events_2026_05';
```

Index usage and heap fetch evidence:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT payment_id, status
FROM payment_events_2026_05
WHERE merchant_id = 123
ORDER BY created_at DESC
LIMIT 100;
```

Interpretation:

```text
WAL falling means write pressure is easing.
Replica lag falling means replay is catching up.
PgBouncer queue falling means request pressure is clearing.
HOT ratio staying low confirms schema/index design problem.
Dead tuples rising means vacuum debt must be handled later.
High Heap Fetches confirm visibility-map/index-only scan degradation.
```

Dangerous actions:

```text
+------------------------------------------------------------------------------+
| DO NOT                                                                        |
+--------------------------------+---------------------------------------------+
| Restart primary                | can extend recovery and add uncertainty      |
| Fail over to stale replica     | can corrupt payment correctness             |
| Run VACUUM FULL                | heavy rewrite and lock/resource risk         |
| Run REINDEX immediately        | adds I/O and WAL during saturation           |
| Add another index              | worsens write amplification                  |
| Route all reads to replica     | stale data can break payment decisions       |
| Retry settlement job           | repeats the incident                         |
+--------------------------------+---------------------------------------------+
```

---

## 8. Prevention and Redesign

### Replace unbounded UPDATE with chunked settlement

```sql
WITH batch AS (
  SELECT id
  FROM payment_events_2026_05
  WHERE status = 'captured'
    AND created_at < now() - interval '2 days'
  ORDER BY id
  LIMIT 2500
  FOR UPDATE SKIP LOCKED
)
UPDATE payment_events_2026_05 p
SET status = 'settled', updated_at = now()
FROM batch
WHERE p.id = batch.id;
```

Batch controller:

```text
+------------------------------------------------------------------------------+
| SAFE BATCH CONTROLLER                                                         |
+------------------------------------------------------------------------------+
| 1. Run one batch of 2,500 rows.                                               |
| 2. Commit.                                                                    |
| 3. Measure WAL rate.                                                          |
| 4. Measure replica lag.                                                       |
| 5. Measure API p99.                                                           |
| 6. Measure PgBouncer waiting clients.                                         |
| 7. Sleep 100ms to 500ms.                                                      |
| 8. Continue only if safety thresholds are green.                              |
| 9. Stop automatically if lag, p99, or WAL crosses guardrail.                  |
+------------------------------------------------------------------------------+
```

### Review indexes on mutable columns

```text
+------------------------------------------------------------------------------+
| INDEX REVIEW FOR MUTABLE COLUMNS                                              |
+------------------------------------------------------------------------------+
| 1. Is this column part of hot state transitions?                              |
| 2. Does the query really need this exact index?                               |
| 3. Can a partial index reduce write cost?                                     |
| 4. Can partition pruning remove the need?                                     |
| 5. Can mutable state move to a narrow current-state table?                    |
| 6. What is the write amplification per business transition?                   |
+------------------------------------------------------------------------------+
```

Possible partial index:

```sql
CREATE INDEX CONCURRENTLY payev_captured_old_idx
ON payment_events_2026_05 (created_at, merchant_id)
WHERE status = 'captured';
```

This helps candidate lookup.

It still has write cost when a row enters or leaves the predicate.

Partial indexes are scalpels, not confetti.

### Use fillfactor for future update-heavy partitions

```sql
ALTER TABLE payment_current_state_2026_06 SET (fillfactor = 80);
```

Rollout rule:

```text
+------------------------------------------------------------------------------+
| FILLFACTOR ROLLOUT RULE                                                       |
+------------------------------------------------------------------------------+
| New partitions        easy to set before writes                               |
| Existing partitions   rewrite/repack required for full benefit                |
| During incident       do not rewrite                                          |
| During maintenance    one partition at a time with disk and WAL budget        |
+------------------------------------------------------------------------------+
```

### Separate immutable event history from current mutable state

The deepest fix is physical modeling.

Do not make a wide append-heavy audit table behave like a mutable current-state table.

```text
+------------------------------------------------------------------------------+
| BETTER PHYSICAL MODEL                                                         |
+------------------------------------------------------------------------------+
|                                                                              |
| payment_events                                                                |
|   append-only facts                                                           |
|   audit-friendly                                                              |
|   minimal updates                                                             |
|   metadata allowed but not fetched by default                                 |
|                                                                              |
| payment_current_state                                                         |
|   one row per payment                                                         |
|   narrow row                                                                  |
|   status updated here                                                         |
|   tuned fillfactor                                                            |
|   indexes only for serving queries                                            |
|                                                                              |
| settlement_jobs                                                               |
|   chunked controller                                                          |
|   progress table                                                              |
|   WAL and replica-lag guardrails                                              |
|   kill switch                                                                 |
|                                                                              |
+------------------------------------------------------------------------------+
```

This is not event-sourcing theater.

It is physical damage control.

Guardrails:

```text
+------------------------------------------------------------------------------+
| REQUIRED GUARDRAILS                                                           |
+-----------------------------+------------------------------------------------+
| Guardrail                   | Why it exists                                  |
+-----------------------------+------------------------------------------------+
| statement_timeout           | stops unbounded damage                         |
| lock_timeout                | avoids waiting behind dangerous locks          |
| WAL rate budget             | protects replicas and storage                  |
| replica lag budget          | protects correctness of reads                  |
| API p99 guard               | protects user-facing workload                  |
| batch kill switch           | stops scheduler retry storms                   |
| maintenance calendar        | prevents REINDEX/VACUUM collisions             |
| query result byte metric    | catches TOAST and SELECT * cliffs              |
+-----------------------------+------------------------------------------------+
```

---

## 9. Scenario Questions and Answers

### Q1. Why did a small status update create so much I/O?

Because the logical field is small but the physical operation is page-based.

The update created new tuple versions.

`status` was indexed, so updates were not HOT.

The engine touched heap pages and index pages.

The job ran soon after checkpoint, so first modifications to many pages created full-page-write pressure.

Small business fields can ride inside large physical writes.

### Q2. Why did HOT updates fail?

HOT requires that updated columns are not indexed and that the new tuple version fits on the same heap page.

This workload updated `status`, which was indexed.

It also updated `updated_at`.

Many old pages were tightly packed.

So the engine could not use the cheap heap-only path.

### Q3. Why was Redis a red herring?

Redis timeout logs appeared because the application and shared network were under pressure.

Database reads and writes saturated infrastructure.

Application threads waited longer on DB calls.

Connection pools backed up.

Redis was visible in logs, but the root cause was database page and write-path saturation.

### Q4. Why is failing over to an 84-second-lagged replica dangerous?

A lagged replica is stale.

Payment correctness cannot use stale state casually.

Failover may expose old status, missing captures, missing settlements, or old fraud state.

Failover is for primary failure, not for escaping a bad query by making correctness worse.

### Q5. Why is REINDEX CONCURRENTLY a bad immediate mitigation?

It reduces blocking, but it still builds another physical index.

That requires disk headroom, read I/O, write I/O, and WAL.

During saturation, it can worsen the outage.

Measure bloat and schedule controlled maintenance after recovery.

### Q6. What changes reduce future update amplification?

Chunk batch updates.

Review indexes on mutable columns.

Use lower fillfactor for future update-heavy partitions.

Separate immutable event history from narrow current state.

Use partial indexes carefully.

Avoid SELECT * over TOAST-heavy rows.

### Q7. What degradation is safe?

Safe with product approval:

```text
merchant dashboards show stale state with timestamp banner
analytics exports pause
non-critical reconciliation views degrade
```

Unsafe:

```text
payment authorization silently reads stale replica state
ledger correctness is approximated
fraud decisions use old state without policy approval
```

### Q8. What is the architecture fix?

```text
+------------------------------------------------------------------------------+
| NEXT-QUARTER DESIGN                                                           |
+------------------------------------------------------------------------------+
|                                                                              |
| payment_events_YYYY_MM                                                        |
|   append-only facts                                                           |
|   partitioned by time                                                         |
|   minimal updates                                                             |
|   metadata not fetched by default                                             |
|                                                                              |
| payment_current_state                                                         |
|   narrow mutable row per payment                                              |
|   tuned fillfactor                                                            |
|   fewer indexes                                                               |
|   status transitions happen here                                              |
|                                                                              |
| settlement_controller                                                         |
|   chunked batches                                                             |
|   progress table                                                              |
|   WAL budget                                                                  |
|   replica-lag budget                                                          |
|   API-latency guard                                                           |
|   kill switch                                                                 |
|                                                                              |
+------------------------------------------------------------------------------+
```

---

## 10. Targeted Reading

```text
Designing Data-Intensive Applications, Chapter 3: Storage and Retrieval
  Focus on B-Trees, LSM-Trees, update-in-place costs, and storage engine tradeoffs.

PostgreSQL documentation:
  pageinspect extension
  pgstattuple extension
  routine vacuuming
  index-only scans
  TOAST storage
  fillfactor storage parameter
  REINDEX CONCURRENTLY

Reading goal:
  Do not memorize engine trivia.
  Connect logical SQL behavior to physical page behavior.
```

---

## 11. Key Takeaways

```text
+------------------------------------------------------------------------------+
| KEY TAKEAWAYS                                                                 |
+------------------------------------------------------------------------------+
| 1. Relational databases read and write pages, not individual rows.            |
|                                                                              |
| 2. Slotted pages use line pointers so tuple bytes can move inside a page      |
|    without changing external tuple IDs.                                       |
|                                                                              |
| 3. Tuple headers carry visibility clues. Page storage and MVCC are physically |
|    connected.                                                                 |
|                                                                              |
| 4. B+Trees are excellent for point lookups and range scans because tree depth |
|    is small and leaf pages are linked.                                        |
|                                                                              |
| 5. Page splits are the B+Tree write penalty. They allocate pages, move keys,  |
|    update parents, generate WAL, and require latches.                         |
|                                                                              |
| 6. Sequential keys preserve locality but can create rightmost-page contention.|
|    Random keys spread contention but can destroy locality.                    |
|                                                                              |
| 7. HOT updates are the golden path for update-heavy tables because they avoid |
|    rewriting every index when indexed columns do not change.                  |
|                                                                              |
| 8. HOT updates require same-page free space. Fillfactor is an operational     |
|    control, not cosmetic storage tuning.                                      |
|                                                                              |
| 9. Index-only scans require visibility proof. A stale visibility map turns a  |
|    supposed index-only scan into heap I/O.                                    |
|                                                                              |
| 10. TOAST hides huge values behind pointers. SELECT * can trigger chunk reads,|
|     decompression, network cost, and application memory pressure.             |
|                                                                              |
| 11. Index bloat increases the number of pages needed to represent the same    |
|     logical keys. More pages means more cache pressure and slower reads.      |
|                                                                              |
| 12. B-Trees and LSM-Trees are different physical answers to different         |
|     workload shapes. Choose based on physics, not fashion.                   |
|                                                                              |
| 13. Principal SRE diagnosis starts from physical units: pages, latches, WAL,  |
|     buffers, indexes, tuple versions, visibility, and cache residency.        |
+------------------------------------------------------------------------------+
```
