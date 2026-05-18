# Week 5, Topic 3: The B-Tree and Page-Based Storage

Last verified: 2026-05-18

---

## 1. Learning Objectives

```text
+------------------------------------------------------------------------------+
| AFTER THIS TOPIC, YOU WILL BE ABLE TO                                        |
+------------------------------------------------------------------------------+
|                                                                              |
| 1. Explain why relational databases read and write fixed-size pages, not       |
|    individual rows, and why that difference dominates real incidents.          |
|                                                                              |
| 2. Draw a slotted page and explain page header, line pointers, free space,     |
|    tuple bytes, tuple IDs, dead tuples, and tuple movement.                    |
|                                                                              |
| 3. Trace a B+Tree point lookup from root page to internal page to leaf page    |
|    to heap tuple, including visibility checks.                                |
|                                                                              |
| 4. Trace a B+Tree range scan and explain why linked leaf pages make ordered    |
|    scans efficient.                                                           |
|                                                                              |
| 5. Explain page splits, right-growing indexes, fillfactor, HOT updates,        |
|    visibility maps, TOAST, and index bloat as physical mechanisms.             |
|                                                                              |
| 6. Compare B-Trees and LSM-Trees using write amplification, read amplification,|
|    space amplification, range-scan behavior, and maintenance work.             |
|                                                                              |
| 7. Diagnose realistic SRE incidents involving cache churn, non-HOT updates,    |
|    index bloat, rightmost-page contention, broken index-only scans, and wide   |
|    TOAST-heavy rows.                                                          |
|                                                                              |
| 8. Choose safe mitigations: throttling, query cancellation, chunking, index    |
|    review, fillfactor changes, REINDEX planning, and maintenance windows.      |
|                                                                              |
+------------------------------------------------------------------------------+
```

---

## 2. The Mental Model: Rows Are a Lie, Pages Are Real

Application developers talk about rows.

Storage engines move pages.

That is the first serious database-internals lesson.

When you run this query:

```sql
SELECT *
FROM orders
WHERE id = 42;
```

The database does not politely pluck one tiny row out of the disk like a librarian pulling a card from a drawer.

It traverses index pages, finds a tuple identifier, reads a heap or data page, checks tuple visibility, and then returns a logical row.

The page is the physical unit of work.

PostgreSQL commonly uses 8KB pages.

InnoDB commonly uses 16KB pages.

Exact sizes differ by engine, but the operational truth is the same: the engine pays in pages, not wishes.

```text
+------------------------------------------------------------------------------+
| LOGICAL QUERY                                                                 |
+------------------------------------------------------------------------------+
|                                                                              |
|   SELECT * FROM orders WHERE id = 42;                                         |
|                                                                              |
+--------------------------------------+---------------------------------------+
                                       |
                                       v
+------------------------------------------------------------------------------+
| PHYSICAL WORK                                                                 |
+------------------------------------------------------------------------------+
|                                                                              |
|   1. Read B+Tree root page.                                                   |
|   2. Read B+Tree internal page if tree depth requires it.                     |
|   3. Read B+Tree leaf page.                                                   |
|   4. Find key 42 and its tuple identifier.                                    |
|   5. Read heap/data page containing the tuple.                                |
|   6. Check whether the tuple version is visible to this transaction.          |
|   7. Return logical row.                                                      |
|                                                                              |
+------------------------------------------------------------------------------+
```

A 50-byte row can require an 8KB heap page read.

A 10-byte update can dirty an 8KB heap page.

An index entry can require another page read.

A visibility check can defeat an index-only scan.

A wide JSON field can trigger out-of-line storage reads and decompression.

A random UUID can scatter writes across many B+Tree leaf pages.

A sequential ID can concentrate writes on the rightmost leaf page.

This is the physics behind the pager.

Principal SRE questions:

```text
+------------------------------------------------------------------------------+
| PAGE-LEVEL QUESTIONS DURING A DATABASE INCIDENT                              |
+------------------------------------------------------------------------------+
|                                                                              |
| Which pages are being read?                                                   |
| Which pages are being dirtied?                                                |
| Which pages are hot in memory?                                                |
| Which pages were evicted from memory?                                         |
| Which index pages are bloated?                                                |
| Which heap pages contain dead versions?                                       |
| Which index pages are being split?                                            |
| Which page or latch is contended?                                             |
| Which pages cannot be cleaned because old snapshots still need them?          |
|                                                                              |
+------------------------------------------------------------------------------+
```

A database incident often looks like CPU, disk, network, or connection pool trouble.

Under the hood, many of those incidents are page incidents.

---

## 3. The Slotted Page

Rows vary in length.

A row can contain fixed-width integers, timestamps, nullable fields, strings, JSON, arrays, compressed values, and pointers to out-of-line data.

If the engine stored variable-length rows without indirection, changing a row length could force large byte ranges to move.

The slotted page solves this with a clean trick: stable slots point to movable tuple bytes.

```text
+------------------------------------------------------------------------------+
| 8KB SLOTTED PAGE, CONCEPTUAL LAYOUT                                           |
+------------------------------------------------------------------------------+
| PAGE HEADER                                                                  |
|   pd_lsn       last WAL position that modified this page                      |
|   pd_checksum  page corruption detection                                      |
|   pd_lower     end of line-pointer area                                       |
|   pd_upper     start of tuple-data area                                       |
+------------------------------------------------------------------------------+
| LINE POINTER ARRAY                                                            |
|   slot 1 -> offset, length, flags                                             |
|   slot 2 -> offset, length, flags                                             |
|   slot 3 -> offset, length, flags                                             |
|   slot 4 -> offset, length, flags                                             |
+------------------------------------------------------------------------------+
|                                                                              |
|                            FREE SPACE                                        |
|                                                                              |
|                pd_upper - pd_lower = available bytes                         |
|                                                                              |
+------------------------------------------------------------------------------+
| tuple bytes for slot 4                                                        |
+------------------------------------------------------------------------------+
| tuple bytes for slot 3                                                        |
+------------------------------------------------------------------------------+
| tuple bytes for slot 2                                                        |
+------------------------------------------------------------------------------+
| tuple bytes for slot 1                                                        |
+------------------------------------------------------------------------------+

Growth direction:

  header and line pointers grow forward
  tuple bytes grow backward
  free space shrinks in the middle
```

The index usually stores a tuple identifier, not a direct byte offset.

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
|     1. Read heap page 42.                                                     |
|     2. Look at line pointer slot 3.                                           |
|     3. Follow the slot to the tuple bytes.                                    |
|                                                                              |
+------------------------------------------------------------------------------+
```

Why this indirection matters:

```text
+------------------------------------------------------------------------------+
| TUPLE MOVEMENT INSIDE ONE PAGE                                                |
+------------------------------------------------------------------------------+
|                                                                              |
| Before compaction:                                                            |
|                                                                              |
|   index entry key=42 -> TID(page=42, slot=3)                                  |
|   page 42 slot 3 -> byte offset 7810                                          |
|                                                                              |
| After compaction:                                                             |
|                                                                              |
|   index entry key=42 -> TID(page=42, slot=3)                                  |
|   page 42 slot 3 -> byte offset 7600                                          |
|                                                                              |
| Result:                                                                      |
|   Tuple bytes moved.                                                          |
|   Slot stayed stable.                                                         |
|   Index entry did not need to change.                                         |
|                                                                              |
+------------------------------------------------------------------------------+
```

This is the first physical design pattern of page storage: stable logical references hide local byte movement.

Without that trick, small updates would constantly force index churn.

---

## 4. Tuple Headers and Page-Level MVCC Clues

A tuple is not just user data.

A tuple also contains visibility metadata.

Full MVCC belongs in Topic 5, but page storage already shows the shape of the truth.

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
|   customer_id                                                                 |
|   status                                                                      |
|   amount_cents                                                                |
|   created_at                                                                  |
+------------------------------------------------------------------------------+
```

A normal UPDATE in an append-style MVCC engine creates a new tuple version.

It does not simply overwrite the old one in place.

```text
+------------------------------------------------------------------------------+
| BEFORE UPDATE                                                                 |
+------------------------------------------------------------------------------+
| page 10                                                                       |
|                                                                              |
|   slot 1 -> tuple A                                                           |
|             xmin = 100                                                        |
|             xmax = 0                                                          |
|             status = 'pending'                                                |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| AFTER UPDATE status = 'paid' BY TRANSACTION 200                               |
+------------------------------------------------------------------------------+
| page 10                                                                       |
|                                                                              |
|   slot 1 -> old tuple A                                                       |
|             xmin = 100                                                        |
|             xmax = 200                                                        |
|             status = 'pending'                                                |
|                                                                              |
|   slot 2 -> new tuple B                                                       |
|             xmin = 200                                                        |
|             xmax = 0                                                          |
|             status = 'paid'                                                   |
+------------------------------------------------------------------------------+
```

Why keep the old tuple?

Because old transactions may still need the old version.

```text
+------------------------------------------------------------------------------+
| SNAPSHOT CONSEQUENCE                                                          |
+------------------------------------------------------------------------------+
|                                                                              |
| Transaction T_old started before transaction 200 committed.                   |
| T_old may still need to see status='pending'.                                 |
|                                                                              |
| Transaction T_new started after transaction 200 committed.                    |
| T_new should see status='paid'.                                               |
|                                                                              |
+------------------------------------------------------------------------------+
```

That means a page can contain old versions, new versions, dead versions, and free space at the same time.

SRE consequences:

```text
+------------------------------------------------------------------------------+
| PAGE-LEVEL CONSEQUENCES OF UPDATE/DELETE WORKLOADS                            |
+------------------------------------------------------------------------------+
|                                                                              |
| High UPDATE rate creates old tuple versions.                                  |
| High DELETE rate creates dead tuple versions.                                 |
| Dead versions consume page space until vacuum can reclaim them.               |
| Less free space means fewer HOT updates.                                      |
| Fewer HOT updates means more index writes.                                    |
| More index writes means more bloat, more WAL, and more cache pressure.        |
| Long-running transactions can prevent cleanup.                                |
|                                                                              |
+------------------------------------------------------------------------------+
```

This is why a database can be slow even when the number of live rows looks reasonable.

The physical question is not only how many live rows exist.

The physical question is how many page versions, dead tuples, and index entries must be carried around to serve those rows.

---

## 5. B+Tree Shape

A B+Tree index is a tree of pages.

Most database indexes described as B-Trees are practically B+Trees: internal pages guide the search, leaf pages contain the ordered entries, and leaf pages are linked for range scans.

A clean B+Tree picture should show levels without diagonal spaghetti.

```text
+------------------------------------------------------------------------------+
| B+TREE STRUCTURE                                                              |
+------------------------------------------------------------------------------+
|                                                                              |
| Level 0: Root                                                                 |
|                                                                              |
|   +------------------------------+                                           |
|   | root page                    |                                           |
|   | separator keys: 100, 500     |                                           |
|   +---------------+--------------+                                           |
|                   |                                                          |
|       +-----------+-----------+                                              |
|       |                       |                                              |
|       v                       v                                              |
|                                                                              |
| Level 1: Internal pages                                                       |
|                                                                              |
|   +------------------+     +------------------+                              |
|   | internal page A  |     | internal page B  |                              |
|   | keys: 10..99     |     | keys: 100..999   |                              |
|   +--------+---------+     +--------+---------+                              |
|            |                        |                                        |
|            v                        v                                        |
|                                                                              |
| Level 2: Leaf pages                                                           |
|                                                                              |
|   +----------+     +----------+     +----------+     +----------+             |
|   | leaf 01  | --> | leaf 02  | --> | leaf 03  | --> | leaf 04  |             |
|   | keys ... |     | keys ... |     | keys ... |     | keys ... |             |
|   +----------+     +----------+     +----------+     +----------+             |
|                                                                              |
+------------------------------------------------------------------------------+
```

Point lookup:

```text
+------------------------------------------------------------------------------+
| POINT LOOKUP: SELECT * FROM orders WHERE id = 42                              |
+------------------------------------------------------------------------------+
|                                                                              |
|   [root page]                                                                 |
|        |                                                                      |
|        v                                                                      |
|   [internal page covering key 42]                                             |
|        |                                                                      |
|        v                                                                      |
|   [leaf page containing key 42]                                               |
|        |                                                                      |
|        v                                                                      |
|   [TID = heap page + slot]                                                    |
|        |                                                                      |
|        v                                                                      |
|   [heap page] -> [tuple visibility check] -> [row returned]                   |
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
|   leaf 12          leaf 13          leaf 14          leaf 15                  |
| +----------+ --> +----------+ --> +----------+ --> +----------+               |
| | 1000..   |     | ...      |     | ...      |     | ..2000   |               |
| +----------+     +----------+     +----------+     +----------+               |
|                                                                              |
+------------------------------------------------------------------------------+
```

Why B+Trees are strong:

```text
+------------------------------------------------------------------------------+
| WHY B+TREES WORK WELL FOR OLTP                                                |
+------------------------------------------------------------------------------+
|                                                                              |
| Root and upper internal pages are usually hot in memory.                      |
| Tree depth is small because fanout is high.                                   |
| Leaf pages are ordered, so range scans are natural.                           |
| Point lookups touch a small number of pages.                                  |
| Secondary indexes can support many access paths.                              |
|                                                                              |
+------------------------------------------------------------------------------+
```

Fanout intuition:

```text
+------------------------------------------------------------------------------+
| B+TREE FANOUT EXAMPLE                                                         |
+------------------------------------------------------------------------------+
|                                                                              |
| Assume one 8KB index page holds about 400 key/pointer entries.                |
|                                                                              |
| Depth 1: root only                                                            |
|   400 keys                                                                    |
|                                                                              |
| Depth 2: root + leaves                                                        |
|   400 * 400 = 160,000 keys                                                    |
|                                                                              |
| Depth 3: root + internal + leaves                                             |
|   400 * 400 * 400 = 64,000,000 keys                                           |
|                                                                              |
| Depth 4:                                                                      |
|   25,600,000,000 keys                                                         |
|                                                                              |
+------------------------------------------------------------------------------+
```

Small depth does not guarantee low latency.

If pages are cold, bloated, contended, or repeatedly split, a shallow tree can still hurt.

---

## 6. Page Splits

A B+Tree leaf page has finite room.

When it is full and a new key belongs on that page, the engine must split the page.

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

A page split is not only a logical rearrangement.

It is physical work.

```text
+------------------------------------------------------------------------------+
| PAGE SPLIT COST                                                               |
+------------------------------------------------------------------------------+
|                                                                              |
| 1. Allocate or reuse another page.                                            |
| 2. Move roughly half of entries.                                              |
| 3. Write old leaf page.                                                       |
| 4. Write new leaf page.                                                       |
| 5. Insert separator into parent page.                                         |
| 6. Split parent too if parent is full.                                        |
| 7. Generate WAL records for structural changes.                              |
| 8. Hold latches while tree structure is made safe.                            |
|                                                                              |
+------------------------------------------------------------------------------+
```

Insert pattern matters.

```text
+------------------------------------------------------------------------------+
| RANDOM KEY INSERTS                                                            |
+------------------------------------------------------------------------------+
|                                                                              |
|   UUIDv4-like keys scatter across many leaf pages.                            |
|                                                                              |
|   Benefit:                                                                    |
|     less single-page hot spot                                                 |
|                                                                              |
|   Cost:                                                                       |
|     more random page access                                                   |
|     more cache churn                                                          |
|     more splits across the tree                                               |
|     worse locality for range scans by insertion time                          |
|                                                                              |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| SEQUENTIAL KEY INSERTS                                                        |
+------------------------------------------------------------------------------+
|                                                                              |
|   BIGSERIAL-like keys grow at the right edge of the tree.                     |
|                                                                              |
|   Benefit:                                                                    |
|     excellent locality                                                        |
|     hot rightmost leaf often stays in cache                                   |
|                                                                              |
|   Cost:                                                                       |
|     high concurrency can concentrate on one rightmost page                    |
|     page latch waits can appear                                               |
|                                                                              |
+------------------------------------------------------------------------------+
```

Good key design is not a slogan.

It is choosing the failure mode you can live with.

---

## 7. Right-Growing Index Contention

Sequential keys create a right-growing B+Tree.

That is usually good.

At extreme concurrency, it can become a latch bottleneck.

```text
+------------------------------------------------------------------------------+
| RIGHT-GROWING PRIMARY KEY INDEX                                               |
+------------------------------------------------------------------------------+
|                                                                              |
| Root and internal pages                                                       |
|        |                                                                      |
|        v                                                                      |
| +--------------+                                                              |
| | rightmost    | <---- insert worker 1                                        |
| | leaf page    | <---- insert worker 2                                        |
| | newest keys  | <---- insert worker 3                                        |
| +--------------+ <---- insert worker 4                                        |
|                                                                              |
+------------------------------------------------------------------------------+
```

The wait may look like a lock, but it is often a latch.

A lock protects logical concurrency.

A latch protects physical in-memory structures.

SREs must distinguish them.

```text
+------------------------------------------------------------------------------+
| LOCK VS LATCH                                                                 |
+----------------------+-------------------------------------------------------+
| Lock                 | Protects logical data correctness.                    |
|                      | Example: two transactions updating same account row.   |
+----------------------+-------------------------------------------------------+
| Latch                | Protects in-memory structure during mutation.          |
|                      | Example: many inserts modifying same B+Tree leaf page. |
+----------------------+-------------------------------------------------------+
```

Symptoms:

```text
+------------------------------------------------------------------------------+
| RIGHTMOST-PAGE CONTENTION SYMPTOMS                                            |
+------------------------------------------------------------------------------+
|                                                                              |
| INSERT throughput plateaus.                                                   |
| CPU may be below saturation.                                                  |
| Disk may not be the first obvious bottleneck.                                 |
| Wait events show buffer-content, page latch, or engine-specific latch waits.  |
| Primary key index is sequential and very hot.                                 |
| Adding more application workers does not help.                                |
|                                                                              |
+------------------------------------------------------------------------------+
```

Mitigation choices:

```text
+------------------------------------------------------------------------------+
| MITIGATION OPTIONS                                                            |
+-------------------------------+----------------------------------------------+
| Reduce unnecessary indexes    | Every insert updates fewer trees.             |
| Batch inserts                 | Fewer round trips and less overhead.          |
| Time-partition hot tables     | Smaller active indexes per partition.         |
| Use UUIDv7 or ULID carefully  | Keeps time locality with some spread.         |
| Review sequence hotspots      | Avoid one page absorbing all write pressure.  |
+-------------------------------+----------------------------------------------+
```

Do not blindly replace every sequential key with UUIDv4.

That can trade latch contention for random I/O, worse cache locality, larger indexes, and uglier range scans.

---

## 8. Fillfactor and HOT Updates

Fillfactor controls how full pages are packed.

A fillfactor of 100 means pack tightly.

A fillfactor of 80 means leave about 20 percent room for future updates.

```text
+------------------------------------------------------------------------------+
| PAGE PACKED TOO TIGHTLY                                                       |
+------------------------------------------------------------------------------+
|                                                                              |
| +----------+----------+----------+----------+----------+                     |
| | tuple 1  | tuple 2  | tuple 3  | tuple 4  | tuple 5  |                     |
| +----------+----------+----------+----------+----------+                     |
|                                                                              |
| Free space: almost none                                                       |
|                                                                              |
| UPDATE needs new tuple version.                                               |
| New version cannot fit on this page.                                          |
| Indexes may need new entries.                                                 |
|                                                                              |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| PAGE WITH UPDATE ROOM                                                         |
+------------------------------------------------------------------------------+
|                                                                              |
| +----------+----------+----------+----------------------+                     |
| | tuple 1  | tuple 2  | tuple 3  | free space           |                     |
| +----------+----------+----------+----------------------+                     |
|                                                                              |
| UPDATE needs new tuple version.                                               |
| New version can fit on this page.                                             |
| HOT update may be possible.                                                   |
|                                                                              |
+------------------------------------------------------------------------------+
```

HOT means Heap-Only Tuple.

It avoids new index entries when an update changes only non-indexed columns and the new tuple version fits on the same heap page.

```text
+------------------------------------------------------------------------------+
| HOT UPDATE CHAIN                                                              |
+------------------------------------------------------------------------------+
|                                                                              |
| B+Tree index entry                                                            |
|   key = order_id 42                                                           |
|   TID = page 10, slot 1                                                       |
|            |                                                                 |
|            v                                                                 |
| +--------------------------------------------------------------------------+ |
| | heap page 10                                                             | |
| |                                                                          | |
| | slot 1 -> old tuple                                                      | |
| |           status='pending'                                                | |
| |           xmax=200                                                        | |
| |           HOT next -> slot 2                                              | |
| |                                                                          | |
| | slot 2 -> new tuple                                                       | |
| |           status='paid'                                                   | |
| |           xmax=0                                                          | |
| |                                                                          | |
| +--------------------------------------------------------------------------+ |
|                                                                              |
+------------------------------------------------------------------------------+
```

Without HOT:

```text
+------------------------------------------------------------------------------+
| NON-HOT UPDATE WITH FIVE INDEXES                                              |
+------------------------------------------------------------------------------+
|                                                                              |
|   logical operation: UPDATE status='paid' WHERE order_id=42                   |
|                                                                              |
|   physical work:                                                              |
|     write heap page                                                           |
|     write primary key index page                                              |
|     write customer_id index page                                              |
|     write status index page                                                   |
|     write created_at index page                                               |
|     write merchant_id index page                                              |
|     generate WAL for heap and index changes                                   |
|                                                                              |
+------------------------------------------------------------------------------+
```

With HOT:

```text
+------------------------------------------------------------------------------+
| HOT UPDATE                                                                    |
+------------------------------------------------------------------------------+
|                                                                              |
|   logical operation: UPDATE non-indexed field                                 |
|                                                                              |
|   physical work:                                                              |
|     write heap page                                                           |
|     keep existing index entry                                                 |
|     follow HOT chain during lookup                                            |
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
| Long HOT chains are not pruned because vacuum is behind.                      |
| Long-running snapshots prevent cleanup.                                       |
|                                                                              |
+------------------------------------------------------------------------------+
```

Fillfactor is not magic.

Changing it affects future page packing.

It does not magically rewrite old pages into a better shape.

```text
+------------------------------------------------------------------------------+
| FILLFACTOR WARNING                                                            |
+------------------------------------------------------------------------------+
|                                                                              |
| ALTER TABLE orders SET (fillfactor = 80);                                     |
|                                                                              |
| This changes future page behavior.                                            |
| It does not repack all existing pages.                                        |
| Applying the new shape to old data usually requires rewrite/repack/reindex.   |
| That maintenance can be heavy enough to cause an incident if run casually.    |
|                                                                              |
+------------------------------------------------------------------------------+
```

---

## 9. Index-Only Scans and Visibility Map

A covering index contains all columns needed by a query.

That does not automatically mean the heap can be skipped.

The executor still needs to know whether the tuple version is visible to the current transaction.

PostgreSQL uses the visibility map for this.

```text
+------------------------------------------------------------------------------+
| INDEX-ONLY SCAN FAST PATH                                                     |
+------------------------------------------------------------------------------+
|                                                                              |
| Query:                                                                        |
|   SELECT order_id, status                                                     |
|   FROM orders                                                                 |
|   WHERE customer_id = 123;                                                    |
|                                                                              |
| Covering index:                                                               |
|   (customer_id, order_id, status)                                             |
|                                                                              |
| Flow:                                                                         |
|                                                                              |
|   B+Tree leaf entry                                                           |
|        |                                                                      |
|        v                                                                      |
|   visibility map bit for heap page                                            |
|        |                                                                      |
|        v                                                                      |
|   bit = all-visible                                                           |
|        |                                                                      |
|        v                                                                      |
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
|        |                                                                      |
|        v                                                                      |
|   visibility map bit for heap page                                            |
|        |                                                                      |
|        v                                                                      |
|   bit = not all-visible                                                       |
|        |                                                                      |
|        v                                                                      |
|   fetch heap page                                                             |
|        |                                                                      |
|        v                                                                      |
|   inspect tuple visibility                                                    |
|        |                                                                      |
|        v                                                                      |
|   return row if visible                                                       |
|                                                                              |
+------------------------------------------------------------------------------+
```

Visibility map shape:

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

What breaks:

```text
+------------------------------------------------------------------------------+
| BROKEN INDEX-ONLY SCAN                                                        |
+------------------------------------------------------------------------------+
|                                                                              |
| Plan name:        Index Only Scan                                             |
| Actual behavior:  many heap fetches                                           |
| Cause:            visibility map bits are not all-visible                     |
| Root reasons:     recent writes, vacuum lag, long transactions                |
|                                                                              |
+------------------------------------------------------------------------------+
```

SRE proof:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, status
FROM orders
WHERE customer_id = 123;
```

Look for:

```text
Index Only Scan using orders_customer_covering_idx
  Heap Fetches: 281943
  Buffers: shared hit=12044 read=92211
```

Translation:

```text
The optimizer used an index-only scan node.
The engine still had to visit the heap many times.
The physical scan was not heap-free.
Fixing vacuum/snapshot pressure may matter more than adding another index.
```

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
| Main heap table: user_events                                                  |
|                                                                              |
| +------------+------------+------------------------------------------------+ |
| | id         | status     | payload                                        | |
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
FROM user_events
WHERE id = 42;
```

The engine can often ignore the large payload.

Dangerous query:

```sql
SELECT *
FROM user_events
WHERE status = 'failed';
```

This can force the engine and application to pay for large values that the business path did not truly need.

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
| The WHERE clause may look selective, but SELECT * is the trap.                |
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
| Split very large payloads into side tables when common queries do not need    |
| them.                                                                         |
| Store blobs in object storage when relational filtering is not needed.        |
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
| +------------+  +------------+  +------------+                               |
| | page 1     |  | page 2     |  | page 3     |                               |
| | 85% full   |  | 88% full   |  | 82% full   |                               |
| +------------+  +------------+  +------------+                               |
|                                                                              |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| BLOATED INDEX                                                                 |
+------------------------------------------------------------------------------+
|                                                                              |
| +------------+  +------------+  +------------+  +------------+  +------------+|
| | page 1     |  | page 2     |  | page 3     |  | page 4     |  | page 5     ||
| | 12% full   |  | 18% full   |  | 09% full   |  | 22% full   |  | 15% full   ||
| +------------+  +------------+  +------------+  +------------+  +------------+|
|                                                                              |
| Same logical key count. More pages. More cache pressure.                     |
|                                                                              |
+------------------------------------------------------------------------------+
```

Consequences:

```text
+------------------------------------------------------------------------------+
| WHY INDEX BLOAT HURTS                                                         |
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

Principal SRE rule:

```text
Do not treat CONCURRENTLY as meaning cheap.
It means reduced blocking, not reduced physics.
```

---

## 12. B-Tree vs LSM-Tree

B-Trees and LSM-Trees optimize different physical realities.

A B-Tree performs in-place page-oriented maintenance.

An LSM-Tree converts many writes into append and later compaction.

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
| Logical operation:                                                            |
|   UPDATE payments SET status='captured' WHERE id=123;                         |
|                                                                              |
| Physical possibilities:                                                       |
|   dirty heap page                                                             |
|   write new tuple version                                                     |
|   update primary key index if needed                                          |
|   update status index if status is indexed                                    |
|   update merchant/status index if status is indexed there                     |
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
| Immediate path:                                                               |
|   append commitlog                                                            |
|   update memtable                                                             |
|                                                                              |
| Later path:                                                                   |
|   flush immutable SSTable                                                     |
|   compact SSTables                                                            |
|   discard overwritten/deleted versions when safe                              |
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
|   INSERT throughput plateaus. Waits show page latch or buffer-content waits.  |
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
|   The updated column is indexed, or page free space is exhausted, so HOT       |
|   updates are impossible.                                                     |
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
|   Visibility map bits are not all-visible, usually due to recent changes,      |
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
|                                                                              |
| Heap pages contain line pointers and tuple data.                              |
| UPDATE creates another tuple version.                                         |
| Old tuple version can have xmax set.                                          |
| Dead tuple percentage can rise.                                               |
| Heap size and index size are separate physical costs.                         |
|                                                                              |
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

Look for:

```text
Index Only Scan
Heap Fetches
shared hit/read buffers
```

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
|                                                                              |
| MegaPay processes card payments for merchants.                                |
| The payments service is a tier-0 system.                                      |
| Every accepted payment must be durable, auditable, and reconcilable.          |
|                                                                              |
+------------------------------------------------------------------------------+
```

```text
+------------------------------------------------------------------------------+
| DATABASE                                                                      |
+------------------------------------------------------------------------------+
|                                                                              |
| Engine:             PostgreSQL 16                                             |
| Deployment:         primary plus two async replicas                           |
| Primary instance:   96 vCPU, 768GB RAM                                        |
| Storage:            cloud block volume with provisioned IOPS and throughput   |
| Pooling:            PgBouncer transaction pooling                             |
| Normal API p99:     18ms                                                      |
| Normal WAL rate:    120MB/s                                                   |
| Normal replica lag: less than 200ms                                           |
|                                                                              |
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

Indexes before incident:

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
+------------------------------------------------------------------------------+
|                                                                              |
| Partition size:                9.4TB                                          |
| Row count:                     8.1 billion                                    |
| Insert rate normal:            14,000 rows/sec                                |
| Read rate normal:              38,000 queries/sec                             |
| metadata column:               often TOASTed for failed payment attempts      |
| status updates:                authorized -> captured -> settled              |
| hot rows:                      newest 48 hours                                |
|                                                                              |
+------------------------------------------------------------------------------+
```

Important design flaw:

```text
status is updated frequently.
status is also indexed.
updated_at is updated frequently.
updated_at appears in several application query patterns.

This means many status transitions are not HOT updates.
```

### Change that triggered the incident

Finance wants merchant settlement to close faster.

A new cron job is deployed.

It runs at 02:00 after the nightly checkpoint window.

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

The job is unbounded.

It matches 67 million rows scattered across many merchants and many heap pages.

It updates an indexed column.

It updates `updated_at`.

Many rows contain TOASTed metadata.

It runs on the primary.

No rate limit.

No statement timeout.

No replica-lag guard.

No WAL budget.

No batch size.

No kill switch.

The gremlin is wearing a finance badge.

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
| 02:04:20 | DB wait events show buffer_content and WALWrite.                  |
| 02:05:00 | Replica lag reaches 84s.                                          |
| 02:05:15 | Fraud service starts reading stale replica data.                  |
| 02:06:00 | API gateway begins returning 503s.                                |
+----------+-------------------------------------------------------------------+
```

### Observed signals

```text
+------------------------------------------------------------------------------+
| DASHBOARD SNAPSHOT                                                            |
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
| DataFileRead              | cold heap/index page reads                       |
| BufferContent             | page-level latch contention                      |
| ClientRead                | app clients slow or backed up                    |
| Lock: transactionid       | secondary symptom from long update visibility    |
+---------------------------+--------------------------------------------------+
```

Red herrings:

```text
+------------------------------------------------------------------------------+
| RED HERRINGS                                                                  |
+-----------------------------+------------------------------------------------+
| Redis timeout logs          | caused by network and app thread starvation    |
| CPU not fully saturated     | page/I/O/latch problem, not pure CPU problem   |
| Replicas still accepting    | data is stale, not safe for correctness reads  |
| Query plan uses index       | index access still touches many pages          |
+-----------------------------+------------------------------------------------+
```

### What actually happened

```text
+------------------------------------------------------------------------------+
| ROOT CAUSE CHAIN                                                              |
+------------------------------------------------------------------------------+
|                                                                              |
| 1. Unbounded settlement UPDATE matched 67 million rows.                       |
|                                                                              |
| 2. Rows were scattered across many heap pages.                                |
|    The job pulled cold pages into shared buffers.                             |
|                                                                              |
| 3. Hot checkout pages were evicted.                                           |
|    Live API reads became physical reads.                                      |
|                                                                              |
| 4. status was indexed, so updates were non-HOT.                               |
|    Each logical update wrote heap plus multiple index entries.                |
|                                                                              |
| 5. updated_at changed, causing more index maintenance in dependent patterns.  |
|                                                                              |
| 6. The job started soon after checkpoint.                                     |
|    First modifications to many pages generated full-page write pressure.      |
|                                                                              |
| 7. BIGSERIAL primary key still received live inserts.                         |
|    New inserts contended on hot rightmost B+Tree leaf pages.                  |
|                                                                              |
| 8. WAL and storage throughput saturated.                                      |
|    Commit latency rose.                                                       |
|                                                                              |
| 9. PgBouncer filled because database sessions held connections longer.        |
|                                                                              |
| 10. API gateway returned 503s because database access became slow and scarce. |
|                                                                              |
+------------------------------------------------------------------------------+
```

This is not one incident.

It is several page-level mechanisms colliding.

```text
+------------------------------------------------------------------------------+
| COLLISION MAP                                                                 |
+-------------------------+----------------------------------------------------+
| Mechanism               | How it hurt                                       |
+-------------------------+----------------------------------------------------+
| Slotted pages           | many tuple versions and dead space                |
| B+Tree indexes          | every non-HOT update touched multiple indexes     |
| Page splits/latches     | live inserts fought over hot leaf pages           |
| Visibility              | old and new versions increased visibility work    |
| Buffer pool             | cold scan evicted hot checkout pages              |
| Full-page writes        | post-checkpoint page changes amplified WAL        |
| Replication             | replicas could not replay WAL fast enough         |
+-------------------------+----------------------------------------------------+
```

---

## 16. Incident Response: What a Principal SRE Does

### Minute 0 to 2: Establish command and stop guessing

Say this clearly in incident chat:

```text
We have a database-primary saturation event. Redis errors are secondary until proven otherwise. Do not restart services. Do not fail over yet. I am identifying the top database writers and blockers now.
```

Run:

```sql
SELECT pid,
       now() - query_start AS age,
       state,
       wait_event_type,
       wait_event,
       left(query, 160) AS query
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

### Minute 2 to 4: Check whether cancellation will create rollback debt

The job may have already changed many rows inside one transaction.

Killing it is still often correct, but recovery is not instant.

Stakeholder message:

```text
I am stopping the settlement UPDATE. The database may continue doing cleanup and rollback-related work afterward. We should expect lag and I/O pressure to fall gradually, not immediately. Do not restart the primary. A restart can lengthen recovery and increase uncertainty.
```

Cancel first:

```sql
SELECT pg_cancel_backend(<pid>);
```

If it does not stop and customer impact is severe:

```sql
SELECT pg_terminate_backend(<pid>);
```

### Minute 4 to 8: Prevent automatic re-entry

```text
Disable the finance cron.
Disable retrying job scheduler task.
Pause non-critical batch jobs touching payment_events_2026_05.
Stop ad hoc merchant-report exports.
Freeze schema/index maintenance.
```

### Minute 8 to 15: Protect correctness

```text
Do not route payment correctness reads to replicas with 84s lag.
Fraud and ledger workflows must use primary or freshness-checked paths.
Merchant dashboards can degrade to stale-with-banner if product approves.
Checkout should degrade non-essential reads before rejecting authorizations.
```

### Minute 15 to 30: Watch recovery shape

```sql
SELECT now() - pg_last_xact_replay_timestamp() AS replica_lag;
```

```sql
SELECT checkpoints_timed,
       checkpoints_req,
       buffers_checkpoint,
       buffers_clean,
       buffers_backend
FROM pg_stat_bgwriter;
```

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
HOT ratio staying low confirms the schema/index design problem.
Dead tuples rising means vacuum debt must be handled later.
```

### What not to do

```text
+------------------------------------------------------------------------------+
| DANGEROUS ACTIONS                                                             |
+--------------------------------+---------------------------------------------+
| Restart primary                | can extend recovery and add uncertainty      |
| Fail over to stale replica     | can lose correctness or create split brain   |
| Run VACUUM FULL                | heavy rewrite, high lock/resource risk       |
| Run REINDEX immediately        | adds I/O and WAL during saturation           |
| Add another index              | worsens write amplification                  |
| Route all reads to replica     | stale data can corrupt payment decisions     |
| Retry settlement job           | repeats the incident                         |
+--------------------------------+---------------------------------------------+
```

---

## 17. Prevention: Architecture and Operations

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
|                                                                              |
| 1. Run one batch of 2,500 rows.                                               |
| 2. Commit.                                                                    |
| 3. Measure WAL rate.                                                          |
| 4. Measure replica lag.                                                       |
| 5. Measure API p99.                                                           |
| 6. Sleep 100ms to 500ms.                                                      |
| 7. Continue only if safety thresholds are green.                              |
| 8. Stop automatically if lag or p99 crosses guardrail.                        |
|                                                                              |
+------------------------------------------------------------------------------+
```

### Review indexes on hot mutable columns

```text
+------------------------------------------------------------------------------+
| INDEX REVIEW                                                                  |
+------------------------------------------------------------------------------+
|                                                                              |
| Ask these before indexing a frequently updated column:                        |
|                                                                              |
| 1. Is this column part of hot state transitions?                              |
| 2. Does the query really need this exact index?                               |
| 3. Can a partial index reduce write cost?                                     |
| 4. Can the query use created_at partition pruning instead?                    |
| 5. Can the state transition be represented in a separate narrow table?        |
| 6. What is the write amplification per business update?                       |
|                                                                              |
+------------------------------------------------------------------------------+
```

Possible partial index:

```sql
CREATE INDEX CONCURRENTLY payev_captured_old_idx
ON payment_events_2026_05 (created_at, merchant_id)
WHERE status = 'captured';
```

This may help the batch find candidates, but it still has write cost when status changes in or out of the predicate.

Partial indexes are not free confetti.

### Use fillfactor for update-heavy partitions

```sql
ALTER TABLE payment_events_2026_06 SET (fillfactor = 80);
```

Use it before data lands.

For existing huge partitions, plan rewrite or repack carefully.

```text
+------------------------------------------------------------------------------+
| FILLFACTOR ROLLOUT RULE                                                       |
+------------------------------------------------------------------------------+
|                                                                              |
| New partitions:        easy to set before writes                              |
| Existing partitions:   requires rewrite/repack for full benefit               |
| During incident:       do not rewrite                                         |
| During maintenance:    one partition at a time with disk and WAL budget       |
|                                                                              |
+------------------------------------------------------------------------------+
```

### Separate hot mutable state from immutable event history

For payment systems, consider separating append-only event history from current mutable state.

```text
+------------------------------------------------------------------------------+
| BETTER PHYSICAL MODEL                                                         |
+------------------------------------------------------------------------------+
|                                                                              |
| payment_events                                                                |
|   append-only facts                                                           |
|   fewer updates                                                               |
|   audit-friendly                                                              |
|                                                                              |
| payment_current_state                                                         |
|   one row per payment                                                         |
|   small narrow row                                                            |
|   status updated here                                                         |
|   fewer wide TOAST columns                                                    |
|                                                                              |
+------------------------------------------------------------------------------+
```

This is not event sourcing hype.

It is physical damage control.

Do not repeatedly update a 9TB wide event table if a narrow current-state table can absorb the mutation.

### Add guardrails

```text
+------------------------------------------------------------------------------+
| REQUIRED GUARDRAILS                                                           |
+-----------------------------+------------------------------------------------+
| Guardrail                   | Why it exists                                  |
+-----------------------------+------------------------------------------------+
| statement_timeout           | stops unbounded damage                         |
| lock_timeout                | avoids waiting behind dangerous locks          |
| WAL rate budget             | protects replicas and storage                  |
| replica lag budget          | protects read correctness                      |
| API p99 guard               | protects user-facing workload                  |
| batch kill switch           | stops scheduler retry storms                   |
| maintenance calendar        | prevents REINDEX/VACUUM collisions             |
+-----------------------------+------------------------------------------------+
```

---

## 18. Scenario Questions

```text
Q1. Why did a status update create so much I/O if status is only a small text field?

Q2. Why did HOT updates fail for this workload?

Q3. Why was Redis a red herring?

Q4. Why is failing over to a replica dangerous when replica lag is 84 seconds?

Q5. Why is REINDEX CONCURRENTLY a bad immediate mitigation during saturation?

Q6. What physical change would reduce future update amplification?

Q7. What product-facing degradation is safe, and what is unsafe?

Q8. How would you redesign the table layout for the next quarter?
```

---

## 19. Scenario Answers

### A1. Small logical update, large physical write

The logical field is small, but the physical update touches pages.

The update creates a new tuple version.

Because `status` is indexed, the change is not HOT.

The engine must update heap pages and index pages.

Because the update starts just after checkpoint, first modifications to many pages can create full-page write pressure.

The small business field rides inside large physical units.

### A2. HOT failed because index and page conditions were wrong

HOT requires the updated columns not to be indexed and the new tuple version to fit on the same heap page.

This workload changed `status`, which is indexed.

It also changed `updated_at`, which participates in common query patterns.

Many old pages were tightly packed.

That means the engine could not use the cheap heap-only path.

### A3. Redis was a red herring

Redis timeout logs appeared because the application and network were under pressure.

The database saturated storage throughput and instance network bandwidth.

Application threads waited longer on database calls.

Connection pools backed up.

Redis was visible in logs, but the root cause was the database page and write path storm.

### A4. Failover to lagged replica is dangerous

A replica that is 84 seconds behind is not a safe authority for payment correctness.

Failover can expose stale data.

Payment systems can double-process, miss settlements, or make fraud decisions on old state.

Failover is for primary failure, not for escaping a bad query while creating correctness risk.

### A5. REINDEX CONCURRENTLY is not an emergency brake

REINDEX CONCURRENTLY reduces blocking, but it still builds another index.

It reads data.

It writes data.

It generates WAL.

It needs disk headroom.

During an I/O saturation event, it can make the system worse.

Schedule it later after measuring bloat and capacity.

### A6. Physical changes to reduce future amplification

Use chunked updates.

Review indexes on mutable columns.

Use lower fillfactor for future update-heavy partitions.

Separate immutable event history from narrow current state.

Use partial indexes carefully.

Reduce SELECT * over TOAST-heavy rows.

### A7. Safe and unsafe degradation

Safe:

```text
Merchant dashboard can show stale settlement state with timestamp banner.
Analytics exports can pause.
Non-critical reconciliation views can degrade.
```

Unsafe:

```text
Payment authorization cannot rely on stale replica state.
Ledger correctness cannot be approximated.
Fraud decisions cannot silently use old data without policy approval.
```

### A8. Next-quarter redesign

```text
+------------------------------------------------------------------------------+
| NEXT-QUARTER DESIGN                                                           |
+------------------------------------------------------------------------------+
|                                                                              |
| payment_events_YYYY_MM                                                        |
|   append-only facts                                                           |
|   partitioned by month or day depending volume                                |
|   minimal updates                                                             |
|   metadata access controlled and not fetched by default                       |
|                                                                              |
| payment_current_state                                                         |
|   narrow mutable table                                                        |
|   one row per payment                                                         |
|   fillfactor tuned before data lands                                          |
|   indexes only for real serving queries                                       |
|                                                                              |
| settlement_jobs                                                               |
|   chunked controller                                                          |
|   WAL and replica-lag guardrails                                              |
|   kill switch                                                                 |
|   progress table                                                              |
|                                                                              |
+------------------------------------------------------------------------------+
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
|                                                                              |
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
|                                                                              |
+------------------------------------------------------------------------------+
```
