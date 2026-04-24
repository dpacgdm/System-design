# Week 5, Topic 1: Cassandra Architecture — Deep Dive

---

## Learning Objectives

```
After this topic, you will be able to:

1. Trace a Cassandra write from client TCP socket through 
   coordinator → commitlog fsync → memtable → flush → 
   SSTable on disk, naming every I/O operation

2. Trace a Cassandra read through bloom filter → partition 
   index → compression offset map → data block → merge, 
   and calculate the exact number of disk seeks per read

3. Calculate bloom filter false positive rates and explain 
   why Cassandra uses ~10 bits per key with 12 hash functions

4. Compare STCS, LCS, and TWCS compaction strategies — 
   knowing when each causes production failures and why

5. Explain why tombstones are the #1 operational pain point 
   in Cassandra, what gc_grace_seconds controls, and how 
   zombie data resurrects from the dead

6. Design a repair strategy that prevents data loss without 
   causing production incidents

7. Diagnose Cassandra performance problems from first 
   principles using nodetool, JMX metrics, and sstable 
   metadata
```

---

## Core Teaching

### Part 1: The Storage Engine — LSM-Tree Architecture

Cassandra's storage engine is a **Log-Structured Merge-tree (LSM-tree)**. This is fundamentally different from PostgreSQL's B-tree + heap architecture. Understanding the LSM-tree explains almost every Cassandra behavior — performance characteristics, compaction needs, tombstone problems, and read amplification.

```
LSM-TREE vs B-TREE — THE CORE TRADEOFF:

╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   B-TREE (PostgreSQL):                                       ║
║   → Write: find page, modify in place, fsync                 ║
║   → Read: traverse tree, read page (1 seek)                  ║
║   → Write amplification: HIGH (random I/O)                   ║
║   → Read amplification: LOW (single lookup)                  ║
║   → Space amplification: LOW (one copy of data)              ║
║                                                              ║
║   LSM-TREE (Cassandra):                                      ║
║   → Write: append to log + memtable (sequential I/O)         ║
║   → Read: check memtable + N SSTables (multiple seeks)       ║
║   → Write amplification: LOW (sequential writes)             ║
║   → Read amplification: HIGH (merge multiple files)          ║
║   → Space amplification: MEDIUM (multiple copies             ║
║     until compaction merges them)                            ║
║                                                              ║
║   LSM-trees TRADE read performance for write                 ║
║   performance. Cassandra is write-optimized.                 ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

This tradeoff explains why:
- Cassandra excels at high write throughput (append-only, sequential I/O)
- Cassandra reads get slower as data ages (more SSTables to check)
- Compaction exists (to reduce read amplification by merging SSTables)
- Bloom filters exist (to avoid checking SSTables that don't contain a key)

Every operational problem in Cassandra traces back to managing this fundamental tension.

---

### Part 2: The Write Path — Deep I/O Level

You learned the high-level write path in Week 2. Now we go to the I/O level.

```
CLIENT WRITE REQUEST:
━━━━━━━━━━━━━━━━━━━━

  Client
    │
    │ CQL: INSERT INTO orders (order_id, customer_id, amount)
    │      VALUES (uuid, 42, 99.99)
    │
    ▼
  Coordinator Node (any node — determined by client driver)
    │
    │ Step 1: Determine partition
    │   → hash(partition_key) via Murmur3 → token
    │   → Token maps to replica set via token ring
    │   → RF=3: three replica nodes identified
    │
    │ Step 2: Send write to RF replicas simultaneously
    │   → Does NOT write locally unless it's a replica
    │   → Parallel dispatch to all 3 replicas
    │   → Waits for CL acknowledgments (e.g., QUORUM=2)
    │
    ▼
  Each Replica Node (simultaneously on all 3):
```

Here's what happens on each replica node, at the I/O level:

```
REPLICA NODE — WRITE EXECUTION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────────────────────────┐
  │                                                  │
  │  Step A: COMMITLOG APPEND                        │
  │                                                  │
  │  The mutation is serialized and APPENDED to the  │
  │  commitlog file. This is SEQUENTIAL I/O (append  │
  │  to end of file). The commitlog is shared across │
  │  ALL tables on the node — not per-table.         │
  │                                                  │
  │  Commitlog sync modes:                           │
  │  ┌────────────────┬────────────────────────────┐ │
  │  │ periodic (def) │ Batch-fsync every           │ │
  │  │                │ commitlog_sync_period_in_ms │ │
  │  │                │ (default: 10000ms = 10s)    │ │
  │  │                │ → Data loss window: 10s     │ │
  │  ├────────────────┼────────────────────────────┤ │
  │  │ batch          │ fsync on every write        │ │
  │  │                │ (groups writes within a     │ │
  │  │                │ window, fsyncs the batch)   │ │
  │  │                │ → commitlog_sync_period     │ │
  │  │                │   controls batch window     │ │
  │  │                │ → Higher durability, higher │ │
  │  │                │   latency                   │ │
  │  ├────────────────┼────────────────────────────┤ │
  │  │ group          │ Similar to batch but waits  │ │
  │  │ (Cassandra 4+) │ for multiple concurrent     │ │
  │  │                │ writers to batch together    │ │
  │  └────────────────┴────────────────────────────┘ │
  │                                                  │
  │  CRITICAL: The commitlog is the ONLY durability  │
  │  guarantee before memtable flush. If the node    │
  │  crashes between commitlog write and memtable    │
  │  flush, the commitlog is replayed on restart.    │
  │                                                  │
  │  Commitlog segment files:                        │
  │  /var/lib/cassandra/commitlog/                   │
  │  CommitLog-7-1234567890.log  (32MB default)      │
  │  CommitLog-7-1234567891.log                      │
  │  CommitLog-7-1234567892.log                      │
  │                                                  │
  │  Segments are recycled after ALL mutations in    │
  │  the segment have been flushed to SSTables.      │
  │                                                  │
  └──────────────────────────────────────────────────┘
           │
           ▼
  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Step B: MEMTABLE INSERT                                    ║
  ╟══════════════════════════════════════════════════════════════╢
  ║                                                              ║
  ║   The mutation is written into the MEMTABLE —                ║
  ║   an in-memory sorted data structure (skip list              ║
  ║   in older versions, tries in newer versions).               ║
  ║                                                              ║
  ║   Each TABLE has its own memtable.                           ║
  ║   (vs commitlog which is shared across tables)               ║
  ║                                                              ║
  ║   Memtable structure:                                        ║
  ║   ┌─────────────────────────────────────────┐                ║
  ║   │ Partition Key A:                        │                ║
  ║   │   ├── clustering_key_1 → columns/values │                ║
  ║   │   ├── clustering_key_2 → columns/values │                ║
  ║   │   └── clustering_key_3 → columns/values │                ║
  ║   │ Partition Key B:                        │                ║
  ║   │   ├── clustering_key_1 → columns/values │                ║
  ║   │   └── clustering_key_2 → columns/values │                ║
  ║   │ Partition Key C:                        │                ║
  ║   │   └── clustering_key_1 → columns/values │                ║
  ╚══════════════════════════════════════════════════════════════╝
  │                                                  │
  │  Data is sorted by partition key, then by        │
  │  clustering key within each partition.            │
  │  This sort order is maintained when flushed to   │
  │  SSTable — enabling efficient range scans        │
  │  within a partition.                              │
  │                                                  │
  │  Memory allocation:                              │
  │  → memtable_heap_space_in_mb (default: 1/4 heap) │
  │  → memtable_offheap_space_in_mb                  │
  │  → memtable_allocation_type: heap_buffers |      │
  │    offheap_buffers | offheap_objects               │
  │                                                  │
  └──────────────────────────────────────────────────┘
           │
           ▼
  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Step C: ACKNOWLEDGE TO COORDINATOR                         ║
  ╟══════════════════════════════════════════════════════════════╢
  ║                                                              ║
  ║   After commitlog append + memtable insert:                  ║
  ║   → The replica sends ACK to the coordinator                 ║
  ║   → The coordinator counts ACKs                              ║
  ║   → Once CL is met (e.g., 2 for QUORUM):                     ║
  ║     → Respond SUCCESS to client                              ║
  ║   → Remaining replicas ACK asynchronously                    ║
  ║                                                              ║
  ║   TOTAL WRITE LATENCY (typical):                             ║
  ║   → Commitlog fsync: 0.1–2ms (sequential I/O)                ║
  ║   → Memtable insert: 0.01–0.1ms (in-memory)                  ║
  ║   → Network RTT: 0.1–1ms (within datacenter)                 ║
  ║   → Total: ~1–5ms per write at QUORUM                        ║
  ║                                                              ║
  ║   NO DISK SEEK. NO INDEX UPDATE. NO PAGE SPLIT.              ║
  ║   This is why Cassandra writes are fast.                     ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝
```

#### Memtable Flush — When and How

The memtable eventually fills up and must be written to disk as an SSTable:

```
FLUSH TRIGGERS:
━━━━━━━━━━━━━━

  1. Memory pressure: memtable reaches memtable_cleanup_threshold
     (default: 1/(1 + memtable_flush_writers) ≈ 0.33 of 
     memtable space). Largest memtable is flushed first.

  2. Commitlog space: commitlog segments can't be recycled
     because they contain unflushed mutations. When total 
     commitlog size exceeds commitlog_total_space_in_mb,
     the oldest commitlog segment's corresponding memtable
     is flushed.

  3. Manual: nodetool flush <keyspace> <table>

  4. Node shutdown: all memtables flushed on graceful shutdown.
     On crash: memtables lost, replayed from commitlog.


FLUSH PROCESS:
━━━━━━━━━━━━━

  Active Memtable ──┐
  (accepting writes) │   Flush triggered
                     │
                     ▼
  ╔══════════════════════════════════════════════════════════════╗
  ║   1. Current memtable becomes IMMUTABLE                      ║
  ║      (new memtable created for new writes)                   ║
  ║                                                              ║
  ║   2. Immutable memtable written to disk                      ║
  ║      as a NEW SSTable:                                       ║
  ║      → Data sorted by partition key +                        ║
  ║        clustering key                                        ║
  ║      → Written SEQUENTIALLY (no seeks)                       ║
  ║      → Multiple files created per SSTable                    ║
  ║                                                              ║
  ║   3. Once SSTable is fully written:                          ║
  ║      → Commitlog segments containing only                    ║
  ║        flushed mutations are RECYCLED                        ║
  ║      → Immutable memtable is freed                           ║
  ╚══════════════════════════════════════════════════════════════╝

  KEY INSIGHT: Writes NEVER modify existing files.
  Each flush creates a NEW SSTable. Old SSTables are
  never modified in place. This is the "immutable" 
  property of LSM-trees. Modifications (updates, 
  deletes) create NEW entries, not in-place changes.
```

---

### Part 3: SSTable Anatomy — The File Format

An SSTable is not a single file. It's a set of files that work together:

```
SSTable Components (for one SSTable, e.g., mc-5-big):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  mc-5-big-Data.db          ← Actual row data (the big file)
  mc-5-big-Index.db         ← Partition index (partition key → offset)
  mc-5-big-Summary.db       ← Sampled index (every Nth partition → Index offset)
  mc-5-big-Filter.db        ← Bloom filter (is this key MAYBE in this SSTable?)
  mc-5-big-CompressionInfo.db ← Compression chunk offsets
  mc-5-big-Statistics.db    ← Min/max clustering values, tombstone counts, etc.
  mc-5-big-TOC.txt          ← Table of contents (lists all component files)
  mc-5-big-Digest.crc32     ← Checksum for data integrity


THE DATA FILE (Data.db) — Internal Structure:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ╔══════════════════════════════════════════════════════════════╗
  ║   Partition A (token: 0x003A...)                             ║
  ║   ┌─────────────────────────────────────────┐                ║
  ║   │ Partition header:                       │                ║
  ║   │   key bytes, deletion info, static cols │                ║
  ║   ├─────────────────────────────────────────┤                ║
  ║   │ Row 1 (clustering_key_1):               │                ║
  ║   │   column1=value, column2=value, ts, ttl │                ║
  ║   ├─────────────────────────────────────────┤                ║
  ║   │ Row 2 (clustering_key_2):               │                ║
  ║   │   column1=value, column2=value, ts, ttl │                ║
  ║   ├─────────────────────────────────────────┤                ║
  ║   │ Row 3 (clustering_key_3):               │                ║
  ║   │   column1=value, column2=value, ts, ttl │                ║
  ╚══════════════════════════════════════════════════════════════╝
  ├─────────────────────────────────────────────┤
  │  Partition B (token: 0x00A7...)              │
  │  ╔══════════════════════════════════════════════════════════════╗
  │  ║   │ Partition header                        │                ║
  │  ║   ├─────────────────────────────────────────┤                ║
  │  ║   │ Row 1 ...                               │                ║
  │  ╚══════════════════════════════════════════════════════════════╝
  ├─────────────────────────────────────────────┤
  │  Partition C (token: 0x01F2...)              │
  │  │ ...                                      │
  └─────────────────────────────────────────────┘

  Partitions are sorted by TOKEN (Murmur3 hash of partition key).
  Within each partition, rows are sorted by CLUSTERING KEY.
  
  Each cell stores:
  → Column value
  → Timestamp (microseconds since epoch — for conflict resolution)
  → Optional TTL (time-to-live) and local deletion time
  → Tombstone marker (if deleted)


THE INDEX FILE (Index.db):
━━━━━━━━━━━━━━━━━━━━━━━━

  Maps partition keys to byte offsets in Data.db.

  ╔══════════════════════════════════════════════════════════════╗
  ║  Partition Key A  → offset 0                                 ║
  ║  Partition Key B  → offset 4,892                             ║
  ║  Partition Key C  → offset 12,304                            ║
  ║  Partition Key D  → offset 18,776                            ║
  ║  ...                                                         ║
  ║  (one entry per partition in the SSTable)                    ║
  ╚══════════════════════════════════════════════════════════════╝

  For large SSTables (millions of partitions), scanning
  the full Index.db is expensive. That's why Summary.db 
  exists.


THE SUMMARY FILE (Summary.db):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  A SAMPLED index of the Index.db. Every Nth partition 
  key is stored (controlled by index_interval, default 128
  in older versions, min/max_index_interval in newer).

  ┌───────────────────────────────────────┐
  │ Partition Key A    → Index offset 0   │  (sample 1)
  │ Partition Key #128 → Index offset 892 │  (sample 2)
  │ Partition Key #256 → Index offset 1784│  (sample 3)
  │ ...                                   │
  └───────────────────────────────────────┘

  Purpose: Binary search on Summary.db finds the 
  approximate location in Index.db. Then a short 
  scan of Index.db finds the exact Data.db offset.

  Summary.db is kept IN MEMORY (it's small).
  Index.db is read from DISK (but only a small range).
```

---

### Part 4: The Bloom Filter — Avoiding Unnecessary Reads

This is the single most important read optimization in Cassandra.

```
THE PROBLEM:
  A read for partition key K must check EVERY SSTable 
  that could contain K. With 20 SSTables on a node, 
  that's 20 disk seeks per read. This is catastrophic.

THE SOLUTION:
  Before checking an SSTable, ask the bloom filter:
  "Does this SSTable POSSIBLY contain key K?"
  
  → If the bloom filter says NO: skip this SSTable 
    entirely. ZERO disk I/O.
  → If the bloom filter says MAYBE: check the SSTable 
    (could be a false positive).
  → Bloom filters NEVER say "no" when the key IS present.
    They can say "yes" when the key is NOT present 
    (false positive), but never the reverse (no false 
    negatives).


BLOOM FILTER MECHANICS:
━━━━━━━━━━━━━━━━━━━━━━

  A bit array of m bits, initialized to all zeros.
  k independent hash functions.

  INSERT key K:
    hash1(K) mod m → set bit position to 1
    hash2(K) mod m → set bit position to 1
    ...
    hashk(K) mod m → set bit position to 1

  QUERY key K:
    hash1(K) mod m → check bit. If 0 → DEFINITELY NOT PRESENT
    hash2(K) mod m → check bit. If 0 → DEFINITELY NOT PRESENT
    ...
    hashk(K) mod m → check bit.
    If ALL k bits are 1 → POSSIBLY PRESENT (could be 
    false positive from other keys' bits overlapping)


FALSE POSITIVE RATE MATH:
━━━━━━━━━━━━━━━━━━━━━━━━

  FPR ≈ (1 - e^(-kn/m))^k

  Where:
    m = number of bits in the filter
    n = number of keys inserted
    k = number of hash functions

  Optimal k (minimizes FPR): k = (m/n) × ln(2)

  CASSANDRA DEFAULTS:
  → bloom_filter_fp_chance = 0.01 (1% false positive rate)
  → This requires ~10 bits per key (m/n ≈ 9.6)
  → Optimal hash functions: k ≈ 9.6 × ln(2) ≈ 6.7 → 7

  EXAMPLE: SSTable with 1,000,000 partitions
  → Bloom filter size: 1M × 10 bits = 10 Mbit ≈ 1.2 MB
  → Fits in memory easily
  → 99% of unnecessary SSTable reads are avoided

  TUNING:
  ╔══════════════════════════════════════════════════════════════╗
  ║  fp_chance        │ Bits/key │ Memory/1M                     ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  0.1  (10%)       │ ~5       │ 0.6 MB                        ║
  ║  0.01 (1%)        │ ~10      │ 1.2 MB                        ║
  ║  0.001 (0.1%)     │ ~15      │ 1.8 MB                        ║
  ║  0.0001 (0.01%)   │ ~20      │ 2.4 MB                        ║
  ╚══════════════════════════════════════════════════════════════╝

  Halving fp_chance costs ~5 additional bits per key.
  
  SET PER TABLE:
  ALTER TABLE orders WITH bloom_filter_fp_chance = 0.001;
  
  → Point-lookup tables: lower fp_chance (0.001)
  → Rarely-queried tables: higher fp_chance (0.1) saves memory
  → NEVER set to 1.0 (disabled) unless you only do 
    full-partition scans
```

The bloom filter is kept **in memory**. This is critical — the filter is loaded when an SSTable is opened and stays resident. The memory cost is:

```
BLOOM FILTER MEMORY BUDGET:
  
  1 billion partitions across all SSTables on a node:
  → At 10 bits/key: 10 Gbit = 1.25 GB of heap
  → At 20 bits/key: 2.5 GB of heap
  
  This is a significant chunk of the JVM heap.
  Nodes with many small SSTables (poor compaction) 
  accumulate more bloom filter memory than nodes 
  with fewer large SSTables (good compaction).
```

---

### Part 5: The Read Path — Deep I/O Level

```
CLIENT READ REQUEST:
━━━━━━━━━━━━━━━━━━━

  CQL: SELECT * FROM orders WHERE order_id = <uuid>
    │
    ▼
  Coordinator Node
    │
    │ Step 1: Determine replicas (same as write)
    │ Step 2: Send read to CL replicas
    │   → QUORUM: send to 2 of 3 replicas
    │   → Also send digest request to 3rd replica
    │     (for read repair — compare digests)
    │
    ▼
  Replica Node — READ EXECUTION:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Check the active memtable for partition key K.             ║
  ║   This is an in-memory lookup: O(log n) on the               ║
  ║   skip list / trie. ~microseconds.                           ║
  ║                                                              ║
  ║   Also check any immutable memtables (being                  ║
  ║   flushed but not yet on disk).                              ║
  ║                                                              ║
  ║   Result: possibly some cells for key K.                     ║
  ║   But K might also have older versions in SSTables.          ║
  ║   Must check SSTables too.                                   ║
  ╚══════════════════════════════════════════════════════════════╝
           │
           ▼
  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   For each SSTable on this node for this table:              ║
  ╟══════════════════════════════════════════════════════════════╢
  ║                                                              ║
  ║   Step 2a: Check token range                                 ║
  ║     → SSTable's min_token / max_token                        ║
  ║     → If K's token is outside range → SKIP                   ║
  ║                                                              ║
  ║   Step 2b: Check BLOOM FILTER                                ║
  ║     → If bloom filter says NO → SKIP (no disk I/O)           ║
  ║     → If bloom filter says MAYBE → continue                  ║
  ║                                                              ║
  ║   Step 2c: Check min/max clustering key bounds               ║
  ║     (from Statistics.db, kept in memory)                     ║
  ║     → If query's clustering range doesn't overlap            ║
  ║       → SKIP                                                 ║
  ║                                                              ║
  ║   Surviving SSTables: the ones we MUST read.                 ║
  ║                                                              ║
  ║   EXAMPLE:                                                   ║
  ║   20 SSTables for this table on this node                    ║
  ║   → 4 eliminated by token range                              ║
  ║   → 14 eliminated by bloom filter                            ║
  ║   → 1 eliminated by clustering bounds                        ║
  ║   → 1 SSTable remaining: must read from disk                 ║
  ║                                                              ║
  ║   Without bloom filters: 20 disk reads                       ║
  ║   With bloom filters: 1 disk read                            ║
  ║   (+ ~0.01 × 14 ≈ 0.14 false positives on avg)               ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝
           │
           ▼
  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   For each candidate SSTable:                                ║
  ╟══════════════════════════════════════════════════════════════╢
  ║                                                              ║
  ║   Step 3a: Summary.db (IN MEMORY)                            ║
  ║     → Binary search for partition key K                      ║
  ║     → Finds the Index.db byte range to scan                  ║
  ║     → Cost: 0 disk I/O (in memory)                           ║
  ║                                                              ║
  ║   Step 3b: Index.db (DISK READ)                              ║
  ║     → Seek to the byte range from Summary.db                 ║
  ║     → Scan forward to find K's exact entry                   ║
  ║     → Read K's Data.db offset                                ║
  ║     → Cost: 1 disk seek + short sequential read              ║
  ║                                                              ║
  ║   Step 3c: Data.db (DISK READ)                               ║
  ║     → Seek to the offset from Index.db                       ║
  ║     → Read the partition's data                              ║
  ║     → Decompress the compression chunk                       ║
  ║       (using CompressionInfo.db offsets)                     ║
  ║     → Cost: 1 disk seek + decompression                      ║
  ║                                                              ║
  ║   TOTAL DISK SEEKS PER SSTABLE: 2                            ║
  ║   (1 for Index.db + 1 for Data.db)                           ║
  ║                                                              ║
  ║   With OS page cache warm: often 0 seeks                     ║
  ║   (Index.db and hot Data.db blocks cached by OS)             ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝
           │
           ▼
  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Merge results from memtable + all candidate                ║
  ║   SSTables. For each cell:                                   ║
  ║                                                              ║
  ║   → Compare TIMESTAMPS across all sources                    ║
  ║   → Highest timestamp WINS (last-writer-wins)                ║
  ║   → Tombstones (deletes) with higher timestamp               ║
  ║     override values with lower timestamp                     ║
  ║   → TTL-expired cells are treated as tombstones              ║
  ║                                                              ║
  ║   The merge produces the CURRENT state of the                ║
  ║   partition as of the read timestamp.                        ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝
           │
           ▼
  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Coordinator compares full response from read               ║
  ║   replica with DIGEST from digest replica(s).                ║
  ║                                                              ║
  ║   → If digests match: done.                                  ║
  ║   → If digests differ: full data requested from              ║
  ║     all replicas, merged by timestamp, most recent           ║
  ║     version written back to stale replicas.                  ║
  ║                                                              ║
  ║   This is ASYNCHRONOUS — doesn't block the read              ║
  ║   response to the client (since Cassandra 4.0,               ║
  ║   blocking read repair was removed by default).              ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝
```

The total read cost depends on how many SSTables survive filtering:

```
READ AMPLIFICATION FORMULA:

  Disk seeks = 2 × (number of candidate SSTables)
  
  With 20 SSTables and 1% bloom filter FPR:
  → Expected candidates = 1 (actual) + 0.01 × 19 ≈ 1.19
  → Expected disk seeks ≈ 2.38
  
  With 200 SSTables and 1% bloom filter FPR:
  → Expected candidates = 1 + 0.01 × 199 ≈ 2.99
  → Expected disk seeks ≈ 5.98
  
  THIS IS WHY COMPACTION MATTERS.
  Too many SSTables → more candidates → more disk seeks
  → higher read latency.
```

---

### Part 6: Compaction Strategies — The Heart of LSM-Tree Operations

Compaction merges multiple SSTables into fewer, larger ones. It's the most operationally significant process in Cassandra.

```
WHY COMPACT:
  1. Reduce read amplification (fewer SSTables to check)
  2. Reclaim space from overwritten/deleted data
  3. Remove expired tombstones (after gc_grace_seconds)
  4. Improve bloom filter effectiveness (fewer files = fewer 
     false positives in aggregate)

THE COMPACTION PROCESS:
  1. Select candidate SSTables (strategy-dependent)
  2. Read all selected SSTables in merged sorted order
  3. Write a new SSTable with merged data
     → Drop shadowed (overwritten) values
     → Drop expired tombstones (if past gc_grace_seconds)
     → Keep non-expired tombstones (still needed!)
  4. Atomically swap: new SSTable replaces old ones
  5. Delete old SSTables

COST:
  → Read amplification (read all selected SSTables)
  → Write amplification (write new merged SSTable)
  → Temporary 2× disk space (old + new coexist briefly)
  → CPU for decompression + recompression
  → I/O bandwidth competes with live reads/writes
```

#### Strategy 1: Size-Tiered Compaction (STCS) — Default

```
SIZE-TIERED COMPACTION STRATEGY (STCS):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PRINCIPLE: Group SSTables of similar size. When a 
  group reaches min_threshold (default: 4), compact 
  them into one larger SSTable.

  LIFECYCLE:
  
  Memtable flush → small SSTables (e.g., 50MB each)
  
  Tier 0:  [50MB] [50MB] [50MB] [50MB]  → compact
           ────────────┬────────────
                       ▼
  Tier 1:         [200MB]
                  [200MB] [200MB] [200MB]  → compact
                  ──────────┬──────────
                            ▼
  Tier 2:              [800MB]
                       [800MB] [800MB] [800MB]  → compact
                       ──────────┬──────────
                                 ▼
  Tier 3:                   [3.2GB]
                            ...and so on

  PROPERTIES:
  ╔══════════════════════════════════════════════════════════════╗
  ║  Write amplification: LOW                                    ║
  ║    → Each byte is rewritten ~log4(N) times                   ║
  ║    → A 1TB dataset: ~5 levels of compaction                  ║
  ║    → Total write amp: ~5×                                    ║
  ║                                                              ║
  ║  Read amplification: MEDIUM-HIGH                             ║
  ║    → One SSTable per size tier → ~5 SSTables                 ║
  ║    → But between compactions: up to                          ║
  ║      4 × number_of_tiers SSTables                            ║
  ║    → Worst case: 20 SSTables                                 ║
  ║                                                              ║
  ║  Space amplification: HIGH                                   ║
  ║    → During compaction: old + new SSTables coexist           ║
  ║    → Temporary space: up to 2× the size of the               ║
  ║      largest tier being compacted                            ║
  ║    → For a 1TB dataset: need ~2TB total disk                 ║
  ║                                                              ║
  ║  BEST FOR: Write-heavy workloads, time-series data           ║
  ║  WORST FOR: Read-heavy with many updates (overwrites)        ║
  ╚══════════════════════════════════════════════════════════════╝

  THE STCS SPACE PROBLEM:
  Compacting the largest tier requires reading ALL 
  SSTables in that tier + writing one new one.
  
  Example: 4 × 250GB SSTables → 1 × 1TB SSTable
  → Need 1TB free space during compaction
  → Disk usage peaks at: 1TB (existing) + 1TB (new) = 2TB
  → If disk is >50% full: compaction may not run!
  → SSTables pile up → reads get slower → death spiral
```

#### Strategy 2: Leveled Compaction (LCS)

```
LEVELED COMPACTION STRATEGY (LCS):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PRINCIPLE: Organize SSTables into LEVELS. Each level 
  is 10× the size of the previous. Within each level 
  (except L0), SSTables have NON-OVERLAPPING key ranges.

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   L0: [SSTable] [SSTable] [SSTable] [SSTable]                ║
  ║       (flushed from memtable, MAY overlap)                   ║
  ║       Size limit: 4 SSTables                                 ║
  ║                                                              ║
  ║   L1: [A-D] [E-H] [I-L] [M-P] [Q-T] [U-Z]                    ║
  ║       (non-overlapping, each ~160MB)                         ║
  ║       Size limit: 10 × sstable_size_in_mb                    ║
  ║       (default: 10 × 160MB = 1.6 GB)                         ║
  ║                                                              ║
  ║   L2: [A-B] [C-D] [E-F] ... [Y-Z]                            ║
  ║       (non-overlapping, each ~160MB)                         ║
  ║       Size limit: 10 × L1 = 16 GB                            ║
  ║                                                              ║
  ║   L3: Size limit: 160 GB                                     ║
  ║   L4: Size limit: 1.6 TB                                     ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

  COMPACTION PROCESS:
  1. When L0 fills (4 SSTables), compact into L1
  2. When L1 exceeds its size limit, pick one SSTable
     from L1, find OVERLAPPING SSTables in L2, merge them
  3. Result: updated L2 SSTables (still non-overlapping)
  4. Repeat upward if L2 exceeds its limit

  PROPERTIES:
  ╔══════════════════════════════════════════════════════════════╗
  ║  Write amplification: HIGH                                   ║
  ║    → Each byte rewritten ~10× per level                      ║
  ║    → With 4 levels: ~40× total write amplification           ║
  ║    → This is STCS's ~5× versus LCS's ~40×                    ║
  ║    → 8× MORE write I/O than STCS                             ║
  ║                                                              ║
  ║  Read amplification: LOW (best of all strategies)            ║
  ║    → L0: up to 4 SSTables (overlapping)                      ║
  ║    → L1+: exactly 1 SSTable per level (non-overlap)          ║
  ║    → Total: ~4 + num_levels ≈ 8 SSTables max                 ║
  ║    → But bloom filters eliminate most → ~1-2 reads           ║
  ║                                                              ║
  ║  Space amplification: LOW                                    ║
  ║    → Compaction merges ONE SSTable at a time                 ║
  ║    → Temp space: ~10× sstable_size (160MB × 10               ║
  ║      overlapping files) ≈ 1.6 GB                             ║
  ║    → Can run compaction at 90%+ disk utilization             ║
  ║                                                              ║
  ║  BEST FOR: Read-heavy workloads, many updates                ║
  ║  WORST FOR: Write-heavy workloads (40× write amp!)           ║
  ╚══════════════════════════════════════════════════════════════╝

  THE LCS WRITE AMPLIFICATION PROBLEM:
  If your workload is 90% writes, LCS amplifies every 
  write ~40×. A node receiving 10K writes/sec generates 
  400K writes/sec of compaction I/O. This can saturate 
  disk bandwidth and CPU, causing:
  → Compaction falling behind (pending compaction backlog)
  → Read latency spiking (compaction I/O steals bandwidth)
  → Write latency spiking (compaction can't keep up)
```

#### Strategy 3: Time-Window Compaction (TWCS)

```
TIME-WINDOW COMPACTION STRATEGY (TWCS):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PRINCIPLE: Group SSTables by TIME WINDOW. SSTables 
  within the same window are compacted together (using 
  STCS). SSTables from DIFFERENT windows are NEVER 
  compacted together.

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Window: 2024-01-01                                         ║
  ║   [SSTable] [SSTable] → compact → [SSTable]                  ║
  ║                                                              ║
  ║   Window: 2024-01-02                                         ║
  ║   [SSTable] [SSTable] [SSTable] → compact →                  ║
  ║   [SSTable]                                                  ║
  ║                                                              ║
  ║   Window: 2024-01-03 (current, still accumulating)           ║
  ║   [SSTable] [SSTable] [SSTable] [SSTable]                    ║
  ║                                                              ║
  ║   Cross-window compaction: NEVER                             ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

  Configure:
  compaction_window_unit: 'DAYS'
  compaction_window_size: 1
  → Each day is a separate compaction window.

  PROPERTIES:
  ╔══════════════════════════════════════════════════════════════╗
  ║  Write amplification: LOWEST of all strategies               ║
  ║    → Each window compacts once, then never touched           ║
  ║    → Old data is never re-compacted                          ║
  ║                                                              ║
  ║  Read amplification: LOW for time-bounded queries            ║
  ║    → "Last 24 hours": check only current window              ║
  ║    → "Last 7 days": check 7 windows                          ║
  ║                                                              ║
  ║  Space amplification: LOW (once compacted)                   ║
  ║    → Each window eventually has 1 SSTable                    ║
  ║                                                              ║
  ║  BEST FOR: Time-series data with TTL, append-only            ║
  ║            metrics, logs, IoT sensor data                    ║
  ║                                                              ║
  ║  WORST FOR: Data with out-of-order timestamps,               ║
  ║            updates to historical records, deletes            ║
  ║            of specific keys across windows                   ║
  ╚══════════════════════════════════════════════════════════════╝

  THE TWCS CRITICAL CONSTRAINT:
  
  NEVER UPDATE OR DELETE DATA ACROSS WINDOWS.
  
  If you delete a key in today's window that exists in 
  last week's window:
  → The tombstone is in today's SSTable
  → The data is in last week's SSTable
  → TWCS NEVER compacts across windows
  → The tombstone and the data are NEVER merged
  → The tombstone must be kept FOREVER (or until 
    gc_grace_seconds expires AND repair runs)
  → Tombstone accumulation → read performance degrades
  → Eventually: "tombstone threshold exceeded" errors
```

#### Compaction Strategy Comparison

```
╔════════════════════════════════════════════════════════════════╗
║           │ Write Amp  │ Read Amp   │ Space Amp  │ Best For    ║
╠════════════════════════════════════════════════════════════════╣
║  STCS     │ ~5×        │ 10-20      │ 2× (peak)  │ Write-heavy ║
║           │ (LOW)      │ SSTables   │ (HIGH)     │ General     ║
║           │            │ (HIGH)     │            │             ║
╠════════════════════════════════════════════════════════════════╣
║  LCS      │ ~40×       │ 1-4        │ ~10%       │ Read-heavy  ║
║           │ (HIGH)     │ SSTables   │ (LOW)      │ Many        ║
║           │            │ (LOW)      │            │ updates     ║
╠════════════════════════════════════════════════════════════════╣
║  TWCS     │ ~2×        │ 1 per      │ ~10%       │ Time-series ║
║           │ (LOWEST)   │ window     │ (LOW)      │ Append-only ║
║           │            │ (LOW)      │            │ with TTL    ║
╚════════════════════════════════════════════════════════════════╝
```

---

### Part 7: Tombstones — The #1 Operational Pain Point

Cassandra is an append-only LSM-tree. You cannot modify or delete data in place. So how does Cassandra delete data?

```
TOMBSTONES: THE "ANTI-DATA"
━━━━━━━━━━━━━━━━━━━━━━━━━━

  When you DELETE in Cassandra, it writes a TOMBSTONE — 
  a special marker that says "this data is deleted."

  Types of tombstones:
  ╔══════════════════════════════════════════════════════════════╗
  ║  Cell tombstone     │ DELETE one column of one row           ║
  ║  Row tombstone      │ DELETE entire row                      ║
  ║  Range tombstone    │ DELETE rows in clustering range        ║
  ║  Partition tombstone│ DELETE entire partition                ║
  ║  TTL tombstone      │ Automatic when TTL expires             ║
  ╚══════════════════════════════════════════════════════════════╝

  Each tombstone carries a TIMESTAMP. During reads, the 
  merge phase compares timestamps: if a tombstone's 
  timestamp > data's timestamp → data is suppressed.


WHY TOMBSTONES CAN'T BE IMMEDIATELY REMOVED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  The SAME data exists on MULTIPLE replicas (RF=3).
  If we remove the tombstone on replica A before 
  replica B has seen the delete:

  1. User deletes key K (tombstone written to replicas A, B)
  2. Replica C was down, missed the delete
  3. Compaction on replica A removes the tombstone
  4. Replica C comes back online
  5. Read repair or anti-entropy runs
  6. Repair sees: A has nothing, C has key K
  7. Repair thinks A is MISSING data → copies K back to A
  8. KEY K IS RESURRECTED FROM THE DEAD 🧟

  This is ZOMBIE DATA — deleted data that comes back.


gc_grace_seconds: THE ZOMBIE PREVENTION WINDOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  gc_grace_seconds (default: 864000 = 10 days)

  RULE: A tombstone is ONLY removed during compaction 
  if its age > gc_grace_seconds.

  THE CONTRACT:
  "You MUST run anti-entropy repair on every node 
  at least once every gc_grace_seconds. If you don't, 
  zombie data WILL appear."

  ╔══════════════════════════════════════════════════════════════╗
  ║   TIMELINE:                                                  ║
  ╟══════════════════════════════════════════════════════════════╢
  ║                                                              ║
  ║   Day 0: Delete key K (tombstone created)                    ║
  ║   Day 1-9: Tombstone retained in SSTables                    ║
  ║            Repair MUST run before day 10                     ║
  ║   Day 10+: Tombstone eligible for removal                    ║
  ║            during compaction                                 ║
  ║                                                              ║
  ║   If repair ran before day 10:                               ║
  ║   → All replicas have the tombstone                          ║
  ║   → Compaction removes it safely                             ║
  ║   → No zombie risk                                           ║
  ║                                                              ║
  ║   If repair did NOT run before day 10:                       ║
  ║   → Some replica might not have the tombstone                ║
  ║   → Compaction removes tombstone on other nodes              ║
  ║   → That replica's copy of key K = zombie                    ║
  ║   → Read repair resurrects key K everywhere                  ║
  ║   → DATA CORRUPTION (from the user's perspective)            ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝


TOMBSTONE ACCUMULATION — THE PERFORMANCE KILLER:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Read path must process tombstones during merge:
  → Scan through ALL tombstones in the partition
  → Even if the live data is small, thousands of 
    tombstones must be checked and discarded

  EXAMPLE: A partition with 1 million rows, 999,990 
  deleted. Reading this partition requires scanning 
  999,990 tombstones to find 10 live rows.

  Cassandra protects itself:
  → tombstone_warn_threshold (default: 1000)
    → WARN log when a read scans > 1000 tombstones
  → tombstone_failure_threshold (default: 100,000)
    → ABORTS the read when > 100,000 tombstones scanned
    → Client receives ReadFailureException
    → THE READ SIMPLY FAILS

  COMMON TOMBSTONE ACCUMULATION PATTERNS:
  
  1. "Delete and re-insert" pattern
     → INSERT 1000 rows, DELETE all, INSERT 1000 new
     → Each cycle adds 1000 tombstones to the partition
     → Over time: millions of tombstones, reads fail
  
  2. "Queue anti-pattern" 
     → Use Cassandra as a queue: insert at tail, delete 
       from head. Each dequeue creates a tombstone.
     → Partition fills with tombstones.
     → THIS IS THE #1 CASSANDRA ANTI-PATTERN.
  
  3. "Sparse columns with TTL"
     → Wide rows with many columns, most with short TTL
     → Expired TTLs become tombstones
     → Column scans hit massive tombstone ranges
  
  4. "Null columns"
     → INSERT with null values: Cassandra stores nothing
     → But UPDATE a column TO null: creates a tombstone
     → Schema with many optional columns → tombstone soup
```

---

### Part 8: Repair — Keeping Replicas Consistent

```
REPAIR TYPES:
━━━━━━━━━━━━

  FULL REPAIR:
  → Compares ALL data between replicas using Merkle trees
  → Streams differing data to bring replicas into sync
  → MUST complete within gc_grace_seconds window
  → CPU and I/O intensive (reads all data to build tree)
  → Duration: hours to days on large datasets

  INCREMENTAL REPAIR (Cassandra 2.1+):
  → Tracks which SSTables have been repaired
  → Only compares UNrepaired SSTables
  → Much faster than full repair (less data to compare)
  → SSTables marked as "repaired" after repair completes
  → CAVEAT: Incremental repair had significant bugs 
    before Cassandra 4.0. Use with caution on older versions.

  SUB-RANGE REPAIR:
  → Repairs a subset of the token range
  → Run multiple sub-range repairs in parallel or 
    sequentially to cover the full range
  → Better control over I/O impact
  → Tools: cassandra-reaper automates sub-range scheduling


MERKLE TREE COMPARISON:
━━━━━━━━━━━━━━━━━━━━━━

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Each replica builds a Merkle tree of its data:             ║
  ╟══════════════════════════════════════════════════════════════╢
  ║                                                              ║
  ║          ROOT HASH                                           ║
  ║          /       \                                           ║
  ║       H(A-M)    H(N-Z)                                       ║
  ║       /    \    /    \                                       ║
  ║    H(A-F) H(G-M) H(N-S) H(T-Z)                               ║
  ║    / \    / \    / \     / \                                 ║
  ║   ... ... ... ... ... ... ... ...                            ║
  ║   (leaf nodes = hashes of actual data ranges)                ║
  ║                                                              ║
  ║   COMPARISON PROCESS:                                        ║
  ║   1. Replica A sends its Merkle tree to Replica B            ║
  ║   2. Compare root hashes                                     ║
  ║      → If equal: ALL data matches. Done.                     ║
  ║      → If different: traverse down                           ║
  ║   3. Compare child hashes                                    ║
  ║      → Find the SPECIFIC ranges that differ                  ║
  ║   4. Stream only the differing ranges                        ║
  ║                                                              ║
  ║   This is O(log N) comparisons to find diffs                 ║
  ║   instead of O(N) full comparison. Efficient                 ║
  ║   for small numbers of differences.                          ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝


REPAIR SCHEDULING — PRODUCTION RULES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  RULE 1: Repair MUST complete within gc_grace_seconds.
    → Default gc_grace_seconds = 10 days
    → Repair must finish a full cycle in < 10 days
    → Schedule: run repair weekly with a 3-day buffer

  RULE 2: Don't repair during peak traffic.
    → Repair competes for disk I/O and CPU
    → Schedule during off-peak hours
    → Use -j 1 (sequential) to limit parallel compaction

  RULE 3: Use cassandra-reaper for production clusters.
    → Automates sub-range scheduling
    → Distributes repair load over time
    → Monitors repair progress and handles failures
    → Configurable intensity (% of cluster resources)

  nodetool repair COMMANDS:
  
  # Full repair of a keyspace:
  nodetool repair <keyspace>
  
  # Full repair of a specific table:
  nodetool repair <keyspace> <table>
  
  # Incremental repair (only unrepaired SSTables):
  nodetool repair -inc <keyspace>
  
  # Sub-range repair:
  nodetool repair -st <start_token> -et <end_token> <keyspace>
  
  # Parallel repair (repairs multiple ranges simultaneously):
  nodetool repair -par <keyspace>
  
  # Check repair status:
  nodetool netstats  # Shows streaming / repair progress
```

---

### Part 9: Gossip Protocol and Failure Detection — Production Details

You encountered the gossip protocol and phi accrual failure detector in Week 4 T2. Now the internals:

```
GOSSIP PROTOCOL:
━━━━━━━━━━━━━━━

  Every second, each node:
  1. Picks a RANDOM live node → sends gossip
  2. Picks a RANDOM unreachable node → sends gossip 
     (attempts recovery)
  3. With probability 1/(num_nodes), gossips with a 
     SEED node (ensures information flows even in 
     partitioned scenarios)

  Gossip message contains:
  → Node's own state (heartbeat generation, heartbeat 
    version, schema version, tokens, load, data center,
    rack, severity, host ID)
  → Digests of other nodes' states (version numbers)
  → The receiver compares versions and requests full 
    state for any that are out of date

  CONVERGENCE: With N nodes, gossip converges in 
  O(log N) rounds. A 100-node cluster: ~7 seconds 
  for all nodes to know about a state change.


PHI ACCRUAL FAILURE DETECTOR:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Instead of binary "alive/dead," computes a continuous 
  suspicion level (φ):

  φ = -log10(1 - F(time_since_last_heartbeat))

  Where F is the CDF of the normal distribution fitted 
  to the historical inter-arrival times of heartbeats.

  ┌─────────────────────────────────────────────────┐
  │  φ value  │ Interpretation                      │
  │───────────┼─────────────────────────────────────│
  │  0-4      │ Almost certainly alive               │
  │  5-7      │ Suspicious                           │
  │  8+       │ Almost certainly dead                 │
  │  (default threshold: φ = 8)                      │
  │                                                 │
  │  At φ = 8: probability of false positive ≈ 10^-8│
  │  (one in 100 million heartbeat intervals)        │
  │                                                 │
  │  Tunable: phi_convict_threshold in cassandra.yaml│
  │  → Higher = more tolerant (fewer false positives) │
  │  → Lower = faster detection (more false positives)│
  └─────────────────────────────────────────────────┘

  WHY ADAPTIVE:
  The detector LEARNS the normal heartbeat pattern.
  → Same-rack nodes: tight distribution, fast detection
  → Cross-DC nodes: wider distribution, slower detection
  → During GC pauses: distribution widens automatically
  → No manual tuning needed per network environment
```

---

## Production Patterns & Failure Modes

```
FAILURE MODE 1: COMPACTION FALLING BEHIND
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: nodetool compactionstats shows growing 
  "pending compactions" count. Read latency increasing.

  Root causes:
  → Write rate exceeds compaction I/O capacity
  → Wrong compaction strategy (LCS on write-heavy table)
  → Disk I/O saturated (compaction + reads + writes)
  → Large partitions slow down compaction (must read 
    entire partition to compact)

  Detection:
  nodetool compactionstats
  # Pending compactions > 50 → warning
  # Pending compactions > 200 → critical
  
  JMX: org.apache.cassandra.metrics:
    type=Compaction,name=PendingTasks

  Fix:
  → Short-term: nodetool setcompactionthroughput 256
    (increase MB/s available for compaction, default: 64)
  → Long-term: switch to appropriate compaction strategy
  → If disk-bound: add more nodes or upgrade disks


FAILURE MODE 2: TOMBSTONE OVERLOAD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: Reads failing with TombstoneOverwhelmingException.
  ReadTimeoutExceptions increasing. WARN logs about 
  "Read X live rows and Y tombstone cells."

  Root causes:
  → Delete-heavy workload without compaction
  → Queue anti-pattern (insert/delete/insert/delete)
  → TTL-heavy columns with wide partitions
  → TWCS with cross-window deletes

  Detection:
  nodetool cfstats <keyspace>.<table>
  # Look at: "Average tombstones per read"
  # > 100 → investigate
  # > 1000 → urgent
  
  # Per-SSTable tombstone stats:
  nodetool tablestats <keyspace>.<table>

  Fix:
  → Run manual compaction: nodetool compact <ks> <table>
    WARNING: resource-intensive, may degrade production
  → Redesign data model to avoid the anti-pattern
  → If urgent: increase tombstone_failure_threshold 
    (buys time, doesn't fix root cause)


FAILURE MODE 3: LARGE PARTITIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: Slow reads on specific partition keys. 
  OOM errors during compaction. GC pressure.

  Root cause: Partition grows unbounded.
  
  GUIDELINES:
  → Target: < 100MB per partition
  → Warning: 100MB - 1GB
  → Danger: > 1GB (compaction will struggle, reads will 
    timeout, repair will be slow)
  → Hard limit: ~2 billion cells per partition 
    (Cassandra internal limit)

  Detection:
  nodetool tablehistograms <keyspace>.<table>
  # Look at "Partition Size" percentiles
  # p99 > 100MB → redesign partition key
  

  # Find large partitions:
  nodetool cfstats <keyspace>.<table>
  # Or use sstablepartitions tool (Cassandra 4.0+):
  sstablepartitions --min-size 100000000 \
    /var/lib/cassandra/data/<ks>/<table>/*.db

  Fix:
  → Redesign partition key with a BUCKETING strategy:
    
    BEFORE (unbounded):
    PRIMARY KEY ((user_id), timestamp)
    → All events for a user in one partition
    → Active users: partition grows forever
    
    AFTER (bucketed):
    PRIMARY KEY ((user_id, month), timestamp)
    → Each month gets its own partition
    → Partition size bounded by monthly volume
    → Query "last month": single partition
    → Query "last year": 12 partitions (scatter)
    
    TRADEOFF: Bounded partitions vs. multi-partition 
    queries for longer time ranges. Almost always 
    worth it.


FAILURE MODE 4: ZOMBIE DATA RESURRECTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: Deleted data reappears. Users report seeing 
  records they deleted weeks ago. Data inconsistency 
  across reads (sometimes the deleted data shows, 
  sometimes it doesn't — depends on which replica 
  is queried).

  Root cause: Repair did not complete within 
  gc_grace_seconds. Tombstone was purged on some 
  replicas while at least one replica never received 
  the tombstone. Read repair or anti-entropy then 
  copies the un-tombstoned data back.

  Detection:
  → Monitor repair completion: cassandra-reaper dashboard
  → Alert if repair hasn't completed a full cycle in 
    (gc_grace_seconds - 3 days)
  → Check for "GC-able tombstones" metric rising faster 
    than compaction can process them

  Fix:
  → Immediate: run nodetool repair on the affected table
    to propagate the current state across all replicas
  → If data is already resurrected: manually delete again
    with a NEW tombstone (higher timestamp)
  → Prevention: automated repair scheduling with 
    cassandra-reaper, alerts on repair lag

  NUCLEAR OPTION: If zombie data is widespread:
  → nodetool repair -full <keyspace> (full repair, 
    all data, all replicas)
  → WARNING: this is expensive. Schedule during off-peak.


FAILURE MODE 5: GOSSIP STORM / FALSE DOWN DETECTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  (Connected to Week 4 T2 scenario — Cassandra 
  gossip false-down cascade)

  Symptom: Nodes marked DOWN that are actually alive.
  Coordinator starts treating live nodes as dead, 
  shifting load to remaining nodes → cascading overload.

  Root cause: GC pause, disk I/O spike, or network 
  micro-partition causes heartbeat delays > phi 
  threshold.

  Detection:
  → nodetool gossipinfo  (show gossip state per node)
  → Check STATUS=NORMAL, HEARTBEAT generation/version 
    incrementing
  → JMX: org.apache.cassandra.net:type=FailureDetector
    → getPhiValues() shows per-node phi scores

  Fix:
  → Short-term: increase phi_convict_threshold from 8 
    to 12 (more tolerant of delayed heartbeats)
  → Investigate root cause: GC logs, disk latency, 
    network stats
  → If GC: tune heap, check for large partition reads 
    causing GC pressure
  → If disk: check compaction pressure, consider 
    separate disks for commitlog vs data


FAILURE MODE 6: HOTSPOT FROM WRONG PARTITION KEY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: One node at 95% CPU/disk while others are 
  at 20%. nodetool cfstats shows highly uneven read/
  write latencies across nodes.

  Root cause: Partition key doesn't distribute evenly.
  Common mistakes:
  → Using a boolean as partition key (2 partitions)
  → Using a low-cardinality column (country, status)
  → Using a timestamp as partition key for time-series
    (all writes go to "now" partition)

  Detection:
  nodetool toppartitions <keyspace> <table> 1000
  # Shows the top partitions by read/write count 
  # over a 1000ms sampling period
  
  nodetool tablehistograms <keyspace>.<table>
  # Skewed partition sizes indicate uneven distribution

  Fix:
  → Redesign partition key (requires data migration)
  → Add a bucketing component to the key
  → Use a synthetic shard prefix for extreme cases:
    
    PRIMARY KEY ((instrument_id, shard_id), timestamp)
    
    shard_id = hash(some_attribute) % 8
    → Spreads one logical partition across 8 physical
    → Reads must scatter-gather across 8 partitions
    → Same pattern as Redis hot key sharding (Week 3 T3)
```

---

## Hands-On Exercise

```
EXERCISE: Explore Cassandra Storage Engine Internals
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If you have a Cassandra instance (local Docker, CCM, 
or test cluster):

# 1. Create a test table and insert data
cqlsh> CREATE KEYSPACE test WITH replication = 
  {'class': 'SimpleStrategy', 'replication_factor': 1};

cqlsh> CREATE TABLE test.events (
  sensor_id text,
  event_time timestamp,
  reading double,
  PRIMARY KEY ((sensor_id), event_time)
) WITH compaction = {'class': 'SizeTieredCompactionStrategy'}
  AND gc_grace_seconds = 864000
  AND bloom_filter_fp_chance = 0.01;

# 2. Insert 10,000 rows across 100 sensors
# (use a script or COPY command)

# 3. Flush memtable to disk
nodetool flush test events

# 4. Examine the SSTable files
ls -la /var/lib/cassandra/data/test/events-<uuid>/
# You'll see: Data.db, Index.db, Summary.db, Filter.db, etc.

# 5. Use sstableutil to list SSTables
sstableutil test events

# 6. Use sstabledump to inspect SSTable contents (JSON)
sstabledump /var/lib/cassandra/data/test/events-<uuid>/mc-1-big-Data.db | head -50
# Shows partition keys, clustering keys, cells with timestamps

# 7. Check bloom filter stats
nodetool cfstats test.events
# Look at: "Bloom filter false positives"
#          "Bloom filter false ratio"
#          "Bloom filter space used"

# 8. Insert more data and flush again (creates second SSTable)
# Then check compaction:
nodetool compactionstats
nodetool compactionhistory

# 9. Create tombstones
cqlsh> DELETE FROM test.events WHERE sensor_id = 'sensor-1' 
  AND event_time > '2024-01-01';
nodetool flush test events

# 10. Check tombstone stats
nodetool tablestats test.events
# "Average tombstones per slice (five minutes)"

# 11. Force compaction and observe tombstone handling
nodetool compact test events
# If tombstones are younger than gc_grace_seconds, 
# they'll be RETAINED even after compaction
```

---

## SRE Scenario: IoT Analytics Platform — Cassandra Storage Engine Meltdown

```
SETUP:
━━━━━━

You are the SRE for an IoT analytics platform. 3,000 
industrial sensors report readings every 5 seconds. 
Data is stored in Cassandra (12 nodes, RF=3, STCS).

Table schema:
  CREATE TABLE iot.readings (
    sensor_id text,
    day text,
    event_time timestamp,
    temperature double,
    pressure double,
    vibration double,
    alert_status text,
    PRIMARY KEY ((sensor_id, day), event_time)
  ) WITH compaction = {'class': 'SizeTieredCompactionStrategy'}
    AND gc_grace_seconds = 864000
    AND default_time_to_live = 7776000;  -- 90 days TTL

Current state:
  → 3,000 sensors × 17,280 readings/day = 51.8M writes/day
  → Data retained for 90 days (TTL)
  → Each node: ~400GB data, 2TB disk (20% utilized)
  → Read pattern: "Last 24 hours for sensor X" (dashboard)
  → Read pattern: "Alert history for sensor X" (on-demand)
  → Cluster has been running for 14 months


THE INCIDENT:
━━━━━━━━━━━━

Monday 08:00 — Operations team reports the analytics 
dashboard is "slow." P99 read latency has increased 
from 12ms to 340ms over the past 3 weeks.

Monday 08:15 — You check nodetool cfstats:
  Read Latency (p99): 340ms (was 12ms three weeks ago)
  Write Latency (p99): 3ms (unchanged — writes are fine)
  SSTable count: 87 per node (was 12 three weeks ago)
  Pending compactions: 847 per node (was 0)
  Bloom filter false positive ratio: 0.18 (was 0.01)

Monday 08:30 — You check nodetool tablestats more closely:
  Average tombstones per read: 14,200
  Maximum partition size: 2.4GB
  Bloom filter space used: 3.1GB per node (of 8GB heap)

Monday 08:45 — You notice in the Cassandra logs from 
3 weeks ago (when the problem started):
  WARN: "Compaction interrupted due to 
  java.io.IOException: No space left on device"
  
And in subsequent days:
  WARN: "Read 14,200 live rows and 89,400 tombstone 
  cells for query SELECT * FROM iot.readings WHERE 
  sensor_id = 'sensor-42' AND day = '2024-10-15'"

Monday 09:00 — An alert fires:
  "TombstoneOverwhelmingException: scanned over 100,000 
  tombstones for query on partition (sensor-2847, 2024-09-15)"

Monday 09:15 — You check disk usage:
  Node 7: 1.89TB / 2TB (94.5% utilized)
  Node 3: 1.82TB / 2TB (91% utilized)
  Other nodes: 1.1-1.4TB (55-70% utilized)
  
  The two large nodes host the most token ranges 
  (vnode distribution imbalance from a past topology 
  change that was never rebalanced).

Monday 09:30 — You check repair history:
  Last successful full repair: 11 weeks ago.
  gc_grace_seconds: 864000 (10 days).
  Repair has not completed a cycle in 11 WEEKS.
  That's 77 days past the gc_grace_seconds window.
```

### Questions

**Q1: Root Cause Analysis [Cascading Failures]**
Trace the complete chain from the initial compaction failure to the current state (87 SSTables, 14,200 tombstones per read, bloom filter degradation, and 340ms reads). Identify EVERY link in the chain. Which failure is the ROOT cause, and which are CONSEQUENCES? What is the specific STCS behavior that turned a disk space problem into a read performance catastrophe?

**Q2: The Zombie Data Time Bomb**
Repair has not completed in 11 weeks. gc_grace_seconds is 10 days. TTL is 90 days. Explain PRECISELY what has happened to the tombstones from TTL-expired data over the past 11 weeks. Is there zombie data in the cluster RIGHT NOW? Calculate the scope: how many days of data are potentially affected by zombie resurrection? What is the specific sequence of events that would trigger resurrection?

**Q3: The STCS Space Trap**
Node 7 is at 94.5% disk utilization. STCS needs temporary space to compact (old + new SSTables coexist). Calculate: can STCS run compaction on Node 7? What is the minimum free disk space STCS needs? Why are Nodes 7 and 3 disproportionately large? Propose a fix that doesn't involve adding hardware immediately.

**Q4: Immediate Mitigation Plan**
It's Monday 09:30. Dashboard reads are at 340ms (SLA: 50ms). Some reads are failing entirely (TombstoneOverwhelmingException). Design your prioritized mitigation plan for the next 4 hours. For each action: state what it fixes, what it doesn't fix, what you must verify before executing, and the operational risk.

**Q5: Architecture Redesign**
After stabilizing the cluster, design the architecture changes that prevent ALL of these problems from recurring. Address: compaction strategy choice, partition key design, tombstone management, repair automation, disk capacity planning, and monitoring. For each change, state which failure mode it prevents and what defense layer (L1/L2/L3) it represents.

---

Take your time. This scenario has multiple interacting storage engine failures — compaction, tombstones, bloom filters, disk space, and repair all feeding into each other. 
