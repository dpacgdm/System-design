# Week 5, Topic 3: The B-Tree and Page-Based Storage

Last verified: 2026-05-18

---

## 1. Learning Objectives

```text
+------------------------------------------------------------------------------+
| AFTER THIS TOPIC, YOU WILL BE ABLE TO                                        |
+------------------------------------------------------------------------------+
| 1. Explain why relational databases read and write fixed-size pages, not       |
|    individual rows, and why this dominates real incidents.                    |
|                                                                              |
| 2. Draw the physical layout of a slotted page: page header, line pointers,     |
|    free space, tuple bytes, tuple IDs, dead tuples, and tuple movement.        |
|                                                                              |
| 3. Trace a B+Tree lookup from root page to internal page to leaf page to       |
|    heap tuple, including visibility checks and heap fetches.                  |
|                                                                              |
| 4. Explain page splits, right-growing indexes, fillfactor, HOT updates,        |
|    visibility maps, TOAST, and index bloat as physical mechanisms.             |
|                                                                              |
| 5. Compare B-Trees and LSM-Trees using write amplification, read amplification,|
|    space amplification, range scans, and operational maintenance.              |
|                                                                              |
| 6. Diagnose incidents involving buffer churn, non-HOT updates, rightmost-page  |
|    contention, broken index-only scans, TOAST cliffs, bloat, and bad batch     |
|    updates.                                                                   |
|                                                                              |
| 7. Produce safe mitigations: query cancellation, rollback warnings, chunked    |
|    updates, fillfactor planning, index review, REINDEX planning, and guardrails|
|    for WAL, replica lag, and customer-facing latency.                          |
+------------------------------------------------------------------------------+
```

---

## 2. The Atomic Unit: A Page, Not a Row

A beginner says the database reads a row.

A storage engine reads a page.

That distinction is the entrance fee for database internals.

A page is a fixed-size block managed by the database engine. PostgreSQL commonly uses 8KB pages. InnoDB commonly uses 16KB pages. Exact values differ by engine, but the production lesson is the same: a small logical row operation can force a much larger physical page operation.

When an application runs this query:

```sql
SELECT *
FROM payments
WHERE id = 42;
```

The developer sees one row.

The database sees page work.

```text
+------------------------------------------------------------------------------+
| LOGICAL REQUEST                                                               |
+------------------------------------------------------------------------------+
|                                                                              |
|   SELECT * FROM payments WHERE id = 42;                                       |
|                                                                              |
+---------------------------------------+--------------------------------------+
                                        |
                                        v
+------------------------------------------------------------------------------+
| PHYSICAL WORK                                                                 |
+------------------------------------------------------------------------------+
|                                                                              |
|   1. Read B+Tree root page.                                                   |
|   2. Read B+Tree internal page if the tree has that depth.                    |
|   3. Read B+Tree leaf page.                                                   |
|   4. Find the key and tuple identifier.                                       |
|   5. Read heap or data page.                                                  |
|   6. Check tuple visibility.                                                  |
|   7. Return the logical row.                                                  |
|                                                                              |
+------------------------------------------------------------------------------+
```

A 60-byte row can require an 8KB heap page read.

A 10-byte update can dirty an 8KB heap page.

A non-HOT update can dirty heap plus every affected B+Tree index.

A covering index can still need heap reads when visibility-map bits are stale.

A wide JSON column can become a hidden chain of TOAST chunk reads and decompression.

This is why serious SRE diagnosis starts with physical units.

```text
+------------------------------------------------------------------------------+
| PRINCIPAL SRE PAGE QUESTIONS                                                  |
+------------------------------------------------------------------------------+
|                                                                              |
| Which pages are being read?                                                   |
| Which pages are being dirtied?                                                |
| Which pages are hot in the buffer pool?                                       |
| Which pages were evicted by a scan?                                           |
| Which index pages are bloated?                                                |
| Which heap pages contain dead versions?                                       |
| Which leaf page is being split or latched?                                    |
| Which page cannot be vacuumed because an old snapshot still needs it?         |
|                                                                              |
+------------------------------------------------------------------------------+
```

The rest of this module explains the machinery behind those questions.

---

## 3. Slotted Page Layout

Rows are variable length.

An order row with a small status is not the same size as an event row with JSON metadata. If an engine stored variable-length rows naively, an update that changed row length would require shifting many bytes. That would make ordinary updates brutally expensive.

The slotted page solves this with indirection.

The page header and line pointer array grow from the front.

Tuple bytes grow from the back.

Free space lives in the middle.

The line pointer points to the tuple bytes.

```text
+------------------------------------------------------------------------------+
| 8KB SLOTTED PAGE, CONCEPTUAL LAYOUT                                           |
+------------------------------------------------------------------------------+
| PAGE HEADER                                                                  |
|   pd_lsn       WAL position of last change affecting this page                |
|   pd_checksum  optional page corruption detection                             |
|   pd_flags     page-level flags                                               |
|   pd_lower     end of line-pointer area                                       |
|   pd_upper     start of tuple-data area                                       |
+------------------------------------------------------------------------------+
| LINE POINTER ARRAY                                                            |
|                                                                              |
|   slot 1: offset=8080, length=96,  flags=normal                               |
|   slot 2: offset=7960, length=112, flags=normal                               |
|   slot 3: offset=7816, length=128, flags=dead                                 |
|   slot 4: offset=7600, length=184, flags=normal                               |
|                                                                              |
+------------------------------------------------------------------------------+
|                                                                              |
|                               FREE SPACE                                      |
|                                                                              |
|                    pd_upper - pd_lower = reusable bytes                       |
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

  header + line pointers grow downward through the diagram
  tuple bytes grow upward through the diagram
  free space is squeezed between them
```

An index usually stores a tuple identifier rather than a byte offset.

```text
+------------------------------------------------------------------------------+
| TUPLE IDENTIFIER                                                              |
+------------------------------------------------------------------------------+
|                                                                              |
|   TID = (heap_page_number, slot_number)                                       |
|                                                                              |
|   Example: (42, 3)                                                            |
|                                                                              |
|   Meaning:                                                                   |
|     read heap page 42                                                         |
|     inspect line pointer slot 3                                               |
|     follow slot 3 to tuple bytes                                              |
|                                                                              |
+------------------------------------------------------------------------------+
```

This protects indexes from local movement inside the same page.

```text
+------------------------------------------------------------------------------+
| LOCAL TUPLE MOVEMENT                                                          |
+------------------------------------------------------------------------------+
|                                                                              |
| Before page cleanup:                                                          |
|                                                                              |
|   B+Tree entry key=42 -> TID(page=42, slot=3)                                 |
|   heap page 42 slot 3 -> byte offset 7816                                     |
|                                                                              |
| After page cleanup moves tuple bytes:                                         |
|                                                                              |
|   B+Tree entry key=42 -> TID(page=42, slot=3)                                 |
|   heap page 42 slot 3 -> byte offset 7600                                     |
|                                                                              |
| Result:                                                                       |
|   tuple bytes moved                                                           |
|   slot stayed stable                                                          |
|   index entry did not change                                                  |
|                                                                              |
+------------------------------------------------------------------------------+
```

That indirection is elegant. It is also the reason page-level fragmentation, dead line pointers, and cleanup behavior matter.

---

## 4. Tuple Headers and Page-Level MVCC Clues

A tuple contains user columns and metadata.

The metadata decides visibility.

Full MVCC internals belong in Topic 5, but page storage already exposes the shape of MVCC.

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
|   id                                                                          |
|   merchant_id                                                                 |
|   status                                                                      |
|   amount_cents                                                                |
|   created_at                                                                  |
|   updated_at                                                                  |
+------------------------------------------------------------------------------+
```

An UPDATE usually creates a new tuple version.

It does not simply overwrite the old one.

```text
+------------------------------------------------------------------------------+
| BEFORE UPDATE                                                                 |
+------------------------------------------------------------------------------+
| heap page 10                                                                  |
|                                                                              |
|   slot 1 -> tuple A                                                           |
|             xmin = 100                                                        |
|             xmax = 0                                                          |
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
|             xmin = 100                                                        |
|             xmax = 200                                                        |
|             status = 'authorized'                                             |
|                                                                              |
|   slot 2 -> new tuple B                                                       |
|             xmin = 200                                                        |
|             xmax = 0                                                          |
|             status = 'captured'                                               |
|                                                                              |
+------------------------------------------------------------------------------+
```

The old tuple remains because an older transaction may still need it.

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

This creates a storage truth that every SRE must respect.

A table can have a reasonable number of live rows and still be physically unhealthy.

```text
+------------------------------------------------------------------------------+
| PHYSICAL CONSEQUENCES OF UPDATE AND DELETE WORKLOADS                          |
+------------------------------------------------------------------------------+
|                                                                              |
| High UPDATE rate creates old tuple versions.                                  |
| High DELETE rate creates dead tuple versions.                                 |
| Dead versions consume heap page space until cleanup.                          |
| Less free space reduces HOT update probability.                               |
| Fewer HOT updates increase index writes.                                      |
| More index writes increase WAL, bloat, and buffer churn.                      |
| Long transactions prevent cleanup.                                            |
|                                                                              |
+------------------------------------------------------------------------------+
```

The database may be slow not because it has too many live rows, but because it has too many physical ghosts.

---

## 5. B+Tree Structure

A B+Tree index is a tree of pages.

Most database indexes described as B-Trees are practically B+Trees: internal pages route the search, leaf pages contain ordered entries, and leaf pages are linked for range scans.

The diagram below avoids diagonal spaghetti. Read it top to bottom.

```text
+------------------------------------------------------------------------------+
| B+TREE STRUCTURE                                                              |
+------------------------------------------------------------------------------+
| LEVEL 0: ROOT PAGE                                                            |
|                                                                              |
|   +----------------------------+                                             |
|   | root                       |                                             |
|   | separator keys: 100, 500   |                                             |
|   +-------------+--------------+                                             |
|                 |                                                            |
|                 v                                                            |
+------------------------------------------------------------------------------+
| LEVEL 1: INTERNAL PAGES                                                       |
|                                                                              |
|   +--------------------+        +--------------------+                       |
|   | internal page A    |        | internal page B    |                       |
|   | keys: 1..499       |        | keys: 500..999     |                       |
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
| POINT LOOKUP: SELECT * FROM payments WHERE id = 42                            |
+------------------------------------------------------------------------------+
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
|   TID = heap page number + slot number                                        |
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
| RANGE SCAN: WHERE id BETWEEN 1000 AND 2000                                    |
+------------------------------------------------------------------------------+
|                                                                              |
|   1. Traverse from root to first leaf containing key 1000.                    |
|   2. Scan entries inside that leaf.                                           |
|   3. Follow leaf-page link to the next leaf.                                  |
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

B+Tree depth is small because fanout is high.

```text
+------------------------------------------------------------------------------+
| B+TREE FANOUT INTUITION                                                       |
+------------------------------------------------------------------------------+
|                                                                              |
| If one 8KB index page holds about 400 key/pointer entries:                    |
|                                                                              |
|   depth 1: root only                                                          |
|     about 400 keys                                                            |
|                                                                              |
|   depth 2: root + leaves                                                      |
|     400 * 400 = 160,000 keys                                                  |
|                                                                              |
|   depth 3: root + internal + leaves                                           |
|     400 * 400 * 400 = 64,000,000 keys                                         |
|                                                                              |
|   depth 4:                                                                    |
|     25,600,000,000 keys                                                       |
|                                                                              |
+------------------------------------------------------------------------------+
```

Small depth does not guarantee low latency.

Cold pages, bloated pages, repeated page splits, and latch contention still hurt.

---

## 6. Page Splits

A leaf page has finite capacity.

When the page is full and a new key belongs there, the engine splits it.

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

A page split is physical work.

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

Insert pattern determines the pain.

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
|   Page latch waits can appear.                                                |
+------------------------------------------------------------------------------+
```

Good key design means choosing the failure mode you can operate.

---

## 7. Right-Growing Index Contention

Sequential IDs such as BIGSERIAL grow at the right edge of the primary-key B+Tree.

That is usually efficient.

At extreme concurrency, it can become a latch bottleneck.

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

A lock protects logical data correctness.

A latch protects an in-memory data structure.

Do not mix them.

```text
+------------------------------------------------------------------------------+
| LOCK VS LATCH                                                                 |
+----------------------+-------------------------------------------------------+
| Lock                 | Protects logical data correctness.                    |
|                      | Example: two transactions update the same account row. |
+----------------------+-------------------------------------------------------+
| Latch                | Protects in-memory page structure during mutation.     |
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
| Disk may not be the first obvious bottleneck.                                 |
| Wait events show buffer-content, page-latch, or engine-specific latch waits. |
| Primary key index is sequential and very hot.                                 |
| Adding more app workers does not help.                                        |
|                                                                              |
+------------------------------------------------------------------------------+
```

Mitigations require care.

```text
+------------------------------------------------------------------------------+
| MITIGATION OPTIONS                                                            |
+-------------------------------+----------------------------------------------+
| Reduce unnecessary indexes    | Every insert updates fewer trees.             |
| Batch inserts                 | Fewer round trips and less overhead.          |
| Time-partition hot tables     | Smaller active indexes per partition.         |
| Use UUIDv7/ULID carefully     | Time locality with some write spread.         |
| Avoid panic migrations        | Key changes are application/data migrations.  |
+-------------------------------+----------------------------------------------+
```

Do not blindly replace every BIGSERIAL key with UUIDv4.

That can trade a latch problem for random I/O, worse cache locality, larger indexes, and ugly range scans.

---

## 8. Fillfactor and HOT Updates

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

It avoids new index entries when two conditions hold.

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

Without HOT, one logical update can become many physical writes.

```text
+------------------------------------------------------------------------------+
| NON-HOT UPDATE WITH FIVE INDEXES                                              |
+------------------------------------------------------------------------------+
|                                                                              |
| Logical operation                                                             |
|   UPDATE payments SET status='captured' WHERE id=42;                          |
|                                                                              |
| Physical work                                                                 |
|   write heap page                                                             |
|   write primary key index page                                                |
|   write customer_id index page                                                |
|   write status index page                                                     |
|   write merchant_id index page                                                |
|   write updated_at index page                                                 |
|   generate WAL for heap and index changes                                     |
|                                                                              |
+------------------------------------------------------------------------------+
```

With HOT:

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

Why HOT fails:

```text
+------------------------------------------------------------------------------+
| HOT FAILURE CONDITIONS                                                        |
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

Fillfactor is an operational control.

But it is not retroactive magic.

```text
+------------------------------------------------------------------------------+
| FILLFACTOR WARNING                                                            |
+------------------------------------------------------------------------------+
|                                                                              |
| ALTER TABLE payments SET (fillfactor = 80);                                   |
|                                                                              |
| This changes future page packing.                                             |
| It does not repack existing pages.                                            |
| Applying the new physical shape to old data requires rewrite, repack, or      |
| rebuild work. That work can be heavy enough to cause an outage if run at the  |
| wrong time.                                                                   |
|                                                                              |
+------------------------------------------------------------------------------+
```

---

## 9. Visibility Map and Index-Only Scans

A covering index contains all columns needed by a query.

That does not automatically mean the heap can be skipped.

The executor still needs to know whether the tuple version is visible to the current transaction.

PostgreSQL uses a visibility map to make this cheap when possible.

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
| page 103   | 0                    | recent changes or vacuum is behind       |
+------------+----------------------+------------------------------------------+
```

Broken index-only scan:

```text
+------------------------------------------------------------------------------+
| PLAN NAME VS PHYSICAL REALITY                                                 |
+------------------------------------------------------------------------------+
|                                                                              |
| Plan node:       Index Only Scan                                              |
| Actual behavior: high heap fetch count                                        |
| Cause:           visibility-map bits are not all-visible                      |
| Root reasons:    recent writes, vacuum lag, long transactions                 |
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

Example red flag:

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

## 10. TOAST and Oversized Attributes

A page cannot hold arbitrarily large values.

PostgreSQL uses TOAST for oversized attributes.

TOAST stands for The Oversized-Attribute Storage Technique.

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

The engine can ignore the large metadata value.

Dangerous query:

```sql
SELECT *
FROM payment_events
WHERE status = 'failed';
```

This can force hidden work.

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

## 11. Index Bloat

B+Tree indexes do not always shrink neatly after churn.

Heavy UPDATE and DELETE workloads can leave dead entries, low-density pages, and inefficient tree shape.

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

Why index bloat hurts:

```text
+------------------------------------------------------------------------------+
| INDEX BLOAT COST                                                              |
+------------------------------------------------------------------------------+
|                                                                              |
| More pages must be cached for the same logical index.                         |
| More disk reads occur on cache misses.                                        |
| More CPU is spent traversing and comparing entries.                           |
| Backups and replicas move more bytes.                                         |
| Checkpoints and maintenance touch more pages.                                 |
| REINDEX needs extra space and I/O.                                            |
|                                                                              |
+------------------------------------------------------------------------------+
```

REINDEX can fix bloat by building a fresh compact index.

But REINDEX is not a feather duster.

It is a forklift.

```text
+------------------------------------------------------------------------------+
| REINDEX CONCURRENTLY RISK                                                     |
+------------------------------------------------------------------------------+
|                                                                              |
| What it helps:                                                                |
|   Reduces blocking compared with a plain rebuild.                             |
|                                                                              |
| What it still costs:                                                          |
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

## 12. B-Tree vs LSM-Tree

B-Trees and LSM-Trees optimize different physical realities.

A B-Tree performs page-oriented maintenance in existing structures.

An LSM-Tree converts writes into append and later compaction.

```text
+------------------------------------------------------------------------------+
| B-TREE VS LSM-TREE                                                            |
+------------------------+----------------------------+------------------------+
| Axis                   | B-Tree                     | LSM-Tree               |
+------------------------+----------------------------+------------------------+
| Primary write shape    | modify pages and indexes   | append log, memtable   |
| Write amplification    | immediate index/page cost  | delayed compaction     |
| Read amplification     | usually low for point read | can span SSTables      |
| Space amplification    | bloat and dead entries     | old SSTables until     |
|                        |                            | compaction             |
| Range scans            | strong linked leaves       | strong sorted runs,    |
|                        |                            | but may merge runs     |
| Maintenance            | vacuum, reindex, analyze   | compaction, repair     |
| Operational pain       | bloat, locks, page churn   | tombstones, compaction |
| Good fit               | OLTP, ledgers, constraints | write-heavy ingestion  |
+------------------------+----------------------------+------------------------+
```

B-Tree write cost:

```text
+------------------------------------------------------------------------------+
| ONE UPDATE ON TABLE WITH FIVE INDEXES                                         |
+------------------------------------------------------------------------------+
|                                                                              |
| Logical operation                                                             |
|   UPDATE payments SET status='captured' WHERE id=123;                         |
|                                                                              |
| Physical possibilities                                                        |
|   dirty heap page                                                             |
|   write new tuple version                                                     |
|   update primary key index if needed                                          |
|   update status index if status is indexed                                    |
|   update merchant/status index if status appears there                        |
|   update updated_at index if updated_at is indexed                            |
|   generate WAL for heap and index changes                                     |
|   maybe log full-page images after checkpoint                                 |
|                                                                              |
+------------------------------------------------------------------------------+
```

LSM write cost:

```text
+------------------------------------------------------------------------------+
| ONE INSERT INTO LSM-STYLE ENGINE                                              |
+------------------------------------------------------------------------------+
|                                                                              |
| Immediate path                                                                |
|   append commitlog                                                            |
|   update memtable                                                             |
|                                                                              |
| Later path                                                                    |
|   flush immutable SSTable                                                     |
|   compact SSTables                                                            |
|   discard overwritten or deleted versions when safe                           |
|                                                                              |
+------------------------------------------------------------------------------+
```

Use B-Tree engines when you need transactions, constraints, secondary indexes, relational joins, low-latency point reads, range scans, and ledger-like correctness.

Use LSM engines when you need massive write throughput, append-heavy access patterns, wide-column models, and predictable partition-key queries.

The correct answer is not PostgreSQL good and Cassandra bad.

The correct answer is physical fit.

---

## 13. Production Failure Modes

```text
+------------------------------------------------------------------------------+
| FAILURE MODE 1: BUFFER POOL THRASHING                                         |
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

```text
+------------------------------------------------------------------------------+
| FAILURE MODE 2: RIGHTMOST B-TREE PAGE CONTENTION                              |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   INSERT throughput plateaus. Waits show page-latch or buffer-content waits.  |
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
|   only when justified by access and operations.                               |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| FAILURE MODE 3: NON-HOT UPDATE EXPLOSION                                      |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   A status update causes index write I/O, WAL, and bloat far beyond expected. |
|                                                                              |
| Cause                                                                         |
|   Updated column is indexed, or page free space is exhausted, so HOT updates   |
|   are impossible.                                                             |
|                                                                              |
| Proof                                                                         |
|   Low HOT update ratio. High index growth. High WAL per updated row.          |
|                                                                              |
| Mitigation                                                                    |
|   Remove unnecessary indexes on frequently updated columns. Lower fillfactor   |
|   for future writes. Use chunked updates. Schedule rewrites safely.            |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| FAILURE MODE 4: BROKEN INDEX-ONLY SCAN                                        |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   Plan says Index Only Scan, but latency and heap reads are high.             |
|                                                                              |
| Cause                                                                         |
|   Visibility-map bits are not all-visible, usually due to recent changes,      |
|   vacuum lag, or long-running snapshots.                                      |
|                                                                              |
| Proof                                                                         |
|   EXPLAIN ANALYZE BUFFERS shows high Heap Fetches.                            |
|                                                                              |
| Mitigation                                                                    |
|   Fix vacuum lag. Remove long transactions. Tune autovacuum for the table.     |
|   Do not add another covering index until visibility is understood.           |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| FAILURE MODE 5: TOAST DECOMPRESSION CLIFF                                     |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   CPU spikes. Query result bytes explode. Application memory grows.           |
|                                                                              |
| Cause                                                                         |
|   SELECT * over wide rows forces TOAST chunk reads and decompression.          |
|                                                                              |
| Proof                                                                         |
|   Removing wide payload column makes query fast. Result size dominates.        |
|                                                                              |
| Mitigation                                                                    |
|   Select only needed columns. Split large payloads. Review ORM behavior.       |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| FAILURE MODE 6: REINDEX DURING A HOT INCIDENT                                 |
+------------------------------------------------------------------------------+
| Symptom                                                                       |
|   An attempt to fix bloat makes I/O saturation worse.                         |
|                                                                              |
| Cause                                                                         |
|   REINDEX CONCURRENTLY reduces blocking, but still builds another physical    |
|   index and generates heavy I/O and WAL.                                      |
|                                                                              |
| Proof                                                                         |
|   Disk headroom falls, write IOPS rise, WAL rises, replica lag grows.          |
|                                                                              |
| Mitigation                                                                    |
|   Stop if unsafe. Reschedule during maintenance. Verify disk headroom.         |
|   Rebuild one index at a time.                                                |
+------------------------------------------------------------------------------+
```

---

## 14. Hands-On Exercise: Inspect Pages

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

-- 6. Update one row and inspect tuple versioning.
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
+------------------------------------------------------------------------------+
| OBSERVATION CHECKLIST                                                         |
+------------------------------------------------------------------------------+
| Heap pages contain line pointers and tuple data.                              |
| UPDATE creates another tuple version.                                         |
| Old tuple version can have xmax set.                                          |
| Dead tuple percentage can rise.                                               |
| Heap size and index size are separate physical costs.                         |
+------------------------------------------------------------------------------+
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

Look for Index Only Scan, Heap Fetches, and shared hit/read buffers.

A plan name alone is not enough.

The buffer and heap-fetch counters reveal physical truth.

---

## 15. Principal SRE Scenario: The Merchant Ledger Page Storm

This scenario is intentionally complex because real database incidents rarely fail one layer at a time.

### System context

```text
+------------------------------------------------------------------------------+
| COMPANY                                                                      |
+------------------------------------------------------------------------------+
| MegaPay processes card payments for global merchants.                         |
| The payment API is tier 0.                                                    |
| Every accepted payment must be durable, auditable, and reconcilable.          |
| Payments must not double-capture, disappear, or silently use stale state.      |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| DATABASE                                                                      |
+------------------------------------------------------------------------------+
| Engine:             PostgreSQL 16                                             |
| Topology:           primary + two async replicas                              |
| Primary instance:   96 vCPU, 768GB RAM                                        |
| Storage:            cloud block volume with provisioned IOPS and throughput   |
| Pooling:            PgBouncer transaction pooling                             |
| Normal API p99:     18ms                                                      |
| Normal WAL rate:    120MB/s                                                   |
| Normal replica lag: less than 200ms                                           |
| Normal HOT ratio:   about 70% on mutable state tables                         |
+------------------------------------------------------------------------------+
```

### Table shape

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
| Result: ordinary business transitions create heap churn, index churn, WAL,    |
| visibility-map churn, and vacuum debt.                                        |
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

It matches 67 million rows.

Rows are scattered across many heap pages.

`status` is indexed.

`updated_at` changes.

Many rows have TOASTed metadata.

There is no chunking, no statement timeout, no replica-lag guard, no WAL budget, no API-latency guard, and no kill switch.

### Timeline

```text
+----------+-------------------------------------------------------------------+
| Time     | Event                                                             |
+----------+-------------------------------------------------------------------+
| 01:58:00 | Checkpoint completes.                                             |
| 02:00:00 | Settlement UPDATE starts.                                         |
| 02:00:45 | WAL jumps from 120MB/s to 1.7GB/s.                                |
| 02:01:10 | Buffer read rate spikes.                                          |
| 02:01:40 | API p99 moves from 18ms to 420ms.                                 |
| 02:02:15 | Replica lag reaches 9s, then 22s.                                 |
| 02:02:40 | PgBouncer waiting clients rise.                                   |
| 02:03:00 | Merchant dashboard queries time out.                              |
| 02:03:25 | Payment authorization p99 crosses 1.8s.                           |
| 02:03:50 | App logs show Redis timeouts.                                     |
| 02:04:20 | DB waits show BufferContent and WALWrite.                         |
| 02:05:00 | Replica lag reaches 84s.                                          |
| 02:05:15 | Fraud service starts reading stale replica data.                  |
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
| API p99                       | 18ms                 | 1.8s                  |
| WAL generation                | 120MB/s              | 1.7GB/s               |
| Replica lag                   | < 200ms              | 84s and growing       |
| DB read IOPS                  | 22K                  | 190K                  |
| DB write throughput           | 450MB/s              | volume cap            |
| PgBouncer waiting clients     | 0                    | 2,800                 |
| Index cache hit ratio         | 99.6%                | 91.2%                 |
| Heap read blocks/sec          | normal               | 8x normal             |
| Dead tuples                   | stable               | rising quickly        |
| HOT update ratio              | 76%                  | 4%                    |
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
+-----------------------------+------------------------------------------------+
```

---

## 16. Incident Analysis

The settlement job looked like one SQL statement.

Physically, it was a page storm.

```text
+------------------------------------------------------------------------------+
| ROOT CAUSE CHAIN                                                              |
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
| 6. The job started soon after checkpoint.                                     |
|    First modifications to many pages created full-page-write pressure.        |
|                                                                              |
| 7. Live inserts continued on BIGSERIAL primary key.                           |
|    New inserts fought over hot rightmost B+Tree leaf pages.                   |
|                                                                              |
| 8. WAL and storage throughput saturated.                                      |
|    Commit latency rose and replicas fell behind.                              |
|                                                                              |
| 9. PgBouncer filled because DB sessions held connections longer.              |
|                                                                              |
| 10. API gateway returned 503s because database access became slow and scarce. |
|                                                                              |
+------------------------------------------------------------------------------+
```

Collision map:

```text
+------------------------------------------------------------------------------+
| MECHANISM COLLISION MAP                                                       |
+-------------------------+----------------------------------------------------+
| Mechanism               | How it hurt                                       |
+-------------------------+----------------------------------------------------+
| Slotted pages           | many tuple versions and dead space                |
| B+Tree indexes          | non-HOT updates touched multiple indexes          |
| Page latches            | live inserts fought over hot leaf pages           |
| Visibility              | new/dead versions increased visibility work       |
| Buffer pool             | cold scan evicted hot checkout pages              |
| Full-page writes        | post-checkpoint page changes amplified WAL        |
| Replication             | replicas could not replay WAL fast enough         |
| PgBouncer               | slow DB work exhausted scarce connections         |
+-------------------------+----------------------------------------------------+
```

Why the tiny status update created huge WAL:

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
|   first modification to a page after checkpoint can log full page image        |
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

Why inserts waited on BufferContent while disk was overloaded:

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

## 17. Incident Response

### Minute 0 to 2: Establish command and stop guessing

Incident message:

```text
We have a database-primary saturation event. Redis errors are secondary until proven otherwise. Do not restart services. Do not fail over. I am identifying the top database writers, wait events, and replica-lag risk now.
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
I am stopping the settlement UPDATE. The database will not recover instantly. If the transaction already changed many rows, PostgreSQL must abort that work and cleanup/vacuum debt will remain. WAL and I/O pressure should fall gradually, not instantly. Do not restart the primary unless we discover an independent database failure. A restart can lengthen recovery and add uncertainty.
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
       n_dead_tup
FROM pg_stat_user_tables
WHERE relname = 'payment_events_2026_05';
```

Interpretation:

```text
WAL falling means write pressure is easing.
Replica lag falling means replay is catching up.
PgBouncer queue falling means request pressure is clearing.
HOT ratio staying low confirms schema/index design problem.
Dead tuples rising means vacuum debt must be handled later.
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

## 18. Prevention and Redesign

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

Controller loop:

```text
+------------------------------------------------------------------------------+
| SAFE BATCH CONTROLLER                                                         |
+------------------------------------------------------------------------------+
| 1. Run one batch of 2,500 rows.                                               |
| 2. Commit.                                                                    |
| 3. Measure WAL rate.                                                          |
| 4. Measure replica lag.                                                       |
| 5. Measure API p99.                                                           |
| 6. Sleep 100ms to 500ms.                                                      |
| 7. Continue only if safety thresholds are green.                              |
| 8. Stop automatically if lag or p99 crosses guardrail.                        |
+------------------------------------------------------------------------------+
```

### Review indexes on hot mutable columns

```text
+------------------------------------------------------------------------------+
| INDEX REVIEW FOR MUTABLE COLUMNS                                              |
+------------------------------------------------------------------------------+
| 1. Is this column part of hot state transitions?                              |
| 2. Does the query really need this exact index?                               |
| 3. Can a partial index reduce write cost?                                     |
| 4. Can partition pruning remove the need?                                     |
| 5. Can the mutable state move to a narrow table?                              |
| 6. What is the write amplification per business transition?                   |
+------------------------------------------------------------------------------+
```

Possible partial index:

```sql
CREATE INDEX CONCURRENTLY payev_captured_old_idx
ON payment_events_2026_05 (created_at, merchant_id)
WHERE status = 'captured';
```

This helps candidate lookup, but it still has write cost when a row enters or leaves the predicate.

Partial indexes are scalpels, not confetti.

### Use fillfactor for update-heavy partitions

```sql
ALTER TABLE payment_current_state_2026_06 SET (fillfactor = 80);
```

Apply before data lands when possible.

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

### Guardrails

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

## 19. Scenario Questions and Answers

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

Redis timeouts appeared because the application and instance network were under pressure.

Database reads and writes saturated shared infrastructure.

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

---

## 20. Targeted Reading

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

## 21. Key Takeaways

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
