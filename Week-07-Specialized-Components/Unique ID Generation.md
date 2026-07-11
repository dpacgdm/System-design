# Topic: Unique ID Generation

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Explain why distributed systems need globally unique    ║
║      identifiers and what properties (uniqueness,            ║
║      sortability, density, coordination cost) matter         ║
║      for different workloads                                 ║
║                                                              ║
║   2. Compare UUID v4, UUID v7, ULID, Snowflake, Sonyflake,   ║
║      database sequences, and DynamoDB counter patterns —     ║
║      including bit layouts, throughput limits, and           ║
║      coordination requirements                               ║
║                                                              ║
║   3. Design a K-sortable ID scheme for a given system        ║
║      (e-commerce orders, social posts, financial ledger      ║
║      entries) with correct clock-drift handling              ║
║                                                              ║
║   4. Diagnose production ID failures: duplicate IDs,         ║
║      clock rollback, sequence exhaustion, hot-spot           ║
║      writes on monotonic keys, and shard ID collisions       ║
║                                                              ║
║   5. Choose between coordination-free and coordination-      ║
║      heavy ID generation based on scale, consistency         ║
║      requirements, and operational complexity                ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "UUIDs are always the right answer"              ║
╟─────────────────────────────────────────────────────────────────────╢
║   WRONG. UUID v4 is random — great for uniqueness without           ║
║   coordination, terrible for B-tree index locality. Inserting       ║
║   random UUIDs into a clustered index causes page splits on         ║
║   every insert. At 10K inserts/sec, your database I/O               ║
║   explodes. UUID v4 solves coordination; it creates a               ║
║   write-amplification problem.                                      ║
╠═════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Snowflake guarantees global ordering"           ║
╟─────────────────────────────────────────────────────────────────────╢
║   WRONG. Snowflake guarantees K-sortable IDs *within a              ║
║   single machine's clock* (roughly time-ordered). Clock drift,      ║
║   NTP step corrections, and multi-datacenter deployment             ║
║   break strict global ordering. IDs from a clock that jumped        ║
║   backward can sort BEFORE older IDs.                               ║
╠═════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Database sequences scale infinitely"            ║
╟─────────────────────────────────────────────────────────────────────╢
║   WRONG. A single Postgres sequence or MySQL AUTO_INCREMENT         ║
║   is a single coordination point. At high insert rates it           ║
║   becomes a bottleneck AND a single point of failure.               ║
║   Sequences also leak information (competitors can estimate         ║
║   your growth rate from order IDs).                                 ║
╠═════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "More bits = safer uniqueness"                   ║
╟─────────────────────────────────────────────────────────────────────╢
║   WRONG. Uniqueness comes from the GENERATION ALGORITHM, not        ║
║   bit count alone. A 64-bit Snowflake with proper worker ID         ║
║   assignment is safer than a 128-bit UUID v4 generated with         ║
║   a broken PRNG. Collision probability depends on entropy           ║
║   source quality AND namespace partitioning.                        ║
╠═════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Coordination-free = free"                       ║
╟─────────────────────────────────────────────────────────────────────╢
║   WRONG. Coordination-free ID generation (UUID v4, local            ║
║   Snowflake) pushes complexity elsewhere: index fragmentation,      ║
║   clock synchronization, worker ID assignment at deploy time,       ║
║   and duplicate detection on collision. There is no free            ║
║   lunch — only a tradeoff between coordination latency              ║
║   and downstream costs.                                             ║
╚═════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching — Why Unique IDs Exist

```
THE FUNDAMENTAL PROBLEM: IDENTITY IN A DISTRIBUTED SYSTEM

In a single-server application, identity is trivial:

  INSERT INTO orders (customer_id, total) VALUES (42, 99.99);
  → Database assigns id = 1000001 via AUTO_INCREMENT
  → Done. One writer. One sequence. No ambiguity.

In a distributed system, identity is HARD:

  Service A (us-east-1)     Service B (eu-west-1)
       │                           │
       │  "Create order"           │  "Create order"
       │                           │
       ▼                           ▼
  Database shard 1            Database shard 2

  Questions that did not exist before:
    → Who assigns the ID? Central service? Each node locally?
    → How do we guarantee two nodes never produce the same ID?
    → Do IDs need to be sortable by creation time?
    → Do IDs need to be opaque (no information leakage)?
    → What happens when the ID generator fails?

WITHOUT A STRATEGY, YOU GET:

  1. DUPLICATE IDs
     Two services generate id=5500123 simultaneously.
     Primary key violation. One insert fails. Data loss or retry storm.

  2. HOT SPOTS
     Monotonic IDs (1, 2, 3, 4...) on a distributed database
     → All new writes hit the SAME partition/range
     → One shard at 100% CPU, others idle

  3. INFORMATION LEAKAGE
     Order ID 847291 → competitor knows you have ~847K orders
     User ID 1523 → attacker knows you have ~1500 users

  4. ORDERING AMBIGUITY
     Event A created at 10:00:01.003 in Virginia
     Event B created at 10:00:01.001 in Tokyo
     Which happened first? (Clocks lie. Network delays lie.)

THE ID IS NOT JUST A NUMBER.
It is a contract about:
  → Uniqueness (never collide within your namespace)
  → Availability (can I get an ID when I need one?)
  → Sortability (can I range-scan by creation time?)
  → Opacity (does it reveal business metrics?)
  → Size (128-bit UUID vs 64-bit int — index size matters)
  → Coordination cost (network round-trip per ID?)
```

### The Property Matrix — What Your ID Must Do

```
Every ID scheme optimizes for some properties and sacrifices others.

┌────────────────────┬─────────┬──────────┬──────────┬──────────────┐
│ Property           │ UUID v4 │ UUID v7  │ Snowflake│ DB Sequence  │
├────────────────────┼─────────┼──────────┼──────────┼──────────────┤
│ Globally unique    │   ✓     │    ✓     │    ✓     │  ✓ (single)  │
│ Coordination-free  │   ✓     │    ✓     │  partial │      ✗       │
│ Time-sortable      │   ✗     │    ✓     │    ✓     │      ✓       │
│ Index-friendly     │   ✗     │    ✓     │    ✓     │      ✓       │
│ Opaque             │   ✓     │  partial │  partial │      ✗       │
│ Compact (64-bit)   │   ✗     │    ✗     │    ✓     │      ✓       │
│ High throughput    │   ✓     │    ✓     │    ✓     │  bottleneck  │
│ Survives partition │   ✓     │    ✓     │    ✓     │      ✗       │
└────────────────────┴─────────┴──────────┴──────────┴──────────────┘

"Index-friendly" = inserts append to the right side of a B-tree,
  minimizing page splits and write amplification.

There is NO universal winner. The right choice depends on:
  → Insert rate
  → Whether you need time-ordering in queries
  → Whether IDs are exposed to users/APIs
  → Your database engine (Postgres B-tree vs Cassandra LSM)
  → Whether you can tolerate coordination latency (~1-5ms)
```

---

## UUID — Universally Unique Identifiers

```
UUID = 128-bit identifier, standardized in RFC 9562 (formerly RFC 4122)

FORMAT (canonical string representation):
  xxxxxxxx-xxxx-Mxxx-Nxxx-xxxxxxxxxxxx
  8-4-4-4-12 hex digits = 32 hex chars + 4 hyphens = 36 chars

  Example: 550e8400-e29b-41d4-a716-446655440000
           └─32 bits─┘ └16┘ └16┘ └16┘ └───48 bits────┘

The "M" nibble (version field, bits 48-51 of the UUID):
  1 = time-based (deprecated)
  2 = DCE Security
  3 = name-based (MD5 hash)
  4 = random (UUID v4)
  5 = name-based (SHA-1 hash)
  6 = reordered time (draft, superseded)
  7 = Unix timestamp (UUID v7) ← NEW in RFC 9562
  8 = custom

The "N" nibble (variant field):
  10xx = RFC 9562 variant (most common)
```

### UUID v4 — Pure Randomness

```
UUID v4: 122 bits of randomness + 6 bits of version/variant metadata

BIT LAYOUT:
  0                   1                   2                   3
  0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |                          random                             |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |          random             |  ver |     random            |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |ver|       random              |  var|       random          |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |var|                        random                           |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

  ver = 0100 (version 4)
  var = 10xx (RFC variant)

GENERATION (pseudocode):
  uuid = random_bytes(16)
  uuid[6] = (uuid[6] & 0x0F) | 0x40   // set version 4
  uuid[8] = (uuid[8] & 0x3F) | 0x80   // set variant

COLLISION PROBABILITY (birthday paradox):
  With n IDs generated, probability of at least one collision:

    P(collision) ≈ n² / (2 × 2^122)
                 ≈ n² / (2 × 5.3 × 10^36)

  Practical numbers:
    1 billion IDs (10^9):     P ≈ 10^-19  (effectively zero)
    1 trillion IDs (10^12):  P ≈ 10^-13  (still negligible)
    1 quadrillion (10^15):   P ≈ 10^-7   (still tiny)

  You will die of hardware failure before UUID v4 collides.
  BUT: broken PRNGs, seed reuse, and VM cloning CAN cause collisions.
  Never assume "UUID = safe" without verifying your entropy source.

STRENGTHS:
  ✓ Zero coordination — generate locally, anywhere, offline
  ✓ 128-bit namespace — collision probability is astronomical
  ✓ Standard library support in every language
  ✓ Opaque — reveals nothing about creation time or origin

WEAKNESSES:
  ✗ NOT sortable — random distribution, no time component
  ✗ TERRIBLE for B-tree indexes — every insert is random
  ✗ 128 bits — 2x storage vs 64-bit int, larger indexes
  ✗ String representation is 36 bytes (vs 8 bytes for int64)

WHEN TO USE UUID v4:
  → Public-facing IDs where opacity matters (API resource IDs)
  → Low-to-medium insert rates (< 1K/sec sustained)
  → Systems where coordination is impossible (offline-first apps)
  → When sortability is NOT required
  → Security tokens, session IDs, file names in object storage

WHEN NOT TO USE UUID v4:
  → High insert rate into B-tree indexes (Postgres, MySQL InnoDB)
  → When you need time-ordered range scans without a separate column
  → When 128-bit storage cost matters at billions of rows
```

### UUID v4 Index Fragmentation — The Hidden Cost

```
POSTGRES EXAMPLE: orders table with UUID v4 primary key

  CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id BIGINT NOT NULL,
    total DECIMAL(10,2),
    created_at TIMESTAMPTZ DEFAULT now()
  );

WHAT HAPPENS ON INSERT (B-tree internals):

  B-tree pages hold ~100-200 index entries per page (depends on row size).
  New UUID v4 inserts land at RANDOM positions in the tree.

  Sequential int insert (id=1, 2, 3...):
    Page 1: [1, 2, 3, ..., 200]  ← append here, always
    Page 2: [201, 202, ...]      ← only when page 1 fills
    → Minimal page splits. Cache-friendly. Sequential I/O.

  Random UUID insert:
    Page 1: [uuid_a, uuid_m, uuid_z, ...]  ← insert uuid_k in middle
    → PAGE SPLIT required (page full, insert in middle)
    → Two pages written to disk instead of one
    → Old page stays in buffer pool (cache pollution)
    → Random I/O pattern (slow on HDD, acceptable on NVMe)

  MEASURED IMPACT (Postgres, 10M row insert benchmark):
    BIGINT serial PK:     ~45,000 inserts/sec
    UUID v4 PK:           ~12,000 inserts/sec  (3.75x slower)
    UUID v7 PK:           ~38,000 inserts/sec  (near serial speed)

  The 3.75x penalty is NOT from UUID size alone.
  It is from RANDOM INSERT POSITION causing page splits.

MITIGATIONS FOR UUID v4 INDEX PAIN:
  1. Use UUID v7 instead (time-ordered, see below)
  2. Use UUID v4 as secondary identifier, BIGINT as PK
  3. Use BRIN index on created_at for time-range queries
  4. Partition table by time range (monthly partitions)
  5. Use LSM-tree databases (Cassandra, RocksDB) — random writes OK
```

---

## UUID v7 — Time-Ordered UUIDs (RFC 9562)

```
UUID v7: Unix timestamp in milliseconds + random bits
         The "successor" to UUID v1, designed for modern systems.

BIT LAYOUT (RFC 9562):
  0                   1                   2                   3
  0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |                       unix_ts_ms (48 bits)                    |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |unix_ts_ms |  ver |       rand_a (12 bits)                     |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |var|    rand_b (62 bits)                                       |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |                       rand_b (continued)                      |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

  unix_ts_ms = 48-bit Unix timestamp in milliseconds
               Range: ~1089 CE to ~10,897 CE (plenty of headroom)
  ver = 0111 (version 7)
  var = 10xx (RFC variant)
  rand_a = 12 bits random (4096 IDs per millisecond per generator)
  rand_b = 62 bits random (additional entropy)

EXAMPLE:
  Timestamp: 2026-07-06 14:30:00.123 UTC
  unix_ts_ms = 1751812200123 (0x0197F2A8B07B in hex)

  UUID v7: 0197f2a8-b07b-7xxx-yxxx-xxxxxxxxxxxx
           └─ timestamp ─┘ └random┘

GENERATION (pseudocode):
  function generate_uuid_v7():
    ms = current_unix_timestamp_millis()
    rand_a = random_12_bits()
    rand_b = random_62_bits()

    uuid = pack(
      timestamp_ms: ms,      // 48 bits
      version: 7,             // 4 bits
      rand_a: rand_a,         // 12 bits
      variant: RFC,            // 2 bits
      rand_b: rand_b          // 62 bits
    )
    return uuid

SORTABILITY:
  UUID v7 strings sort lexicographically by creation time
  (within a single generator, monotonic clock assumed).

  SELECT * FROM orders WHERE id > '0197f2a8-b07b-7000-0000-000000000000'
                        AND id < '0197f2a8-b07b-7fff-ffff-ffffffffffff'
  → Returns all orders created in that millisecond window.

  B-tree inserts append to the right → same locality as serial IDs.

THROUGHPUT LIMIT:
  12 bits of rand_a = 4096 unique IDs per millisecond per generator
  = 4,096,000 IDs/sec per generator (theoretical max)
  In practice: millions/sec is achievable.

  Multiple generators (multiple app servers) each produce
  independent streams. Collision requires same millisecond AND
  same rand_a AND same rand_b — astronomically unlikely.

STRENGTHS vs UUID v4:
  ✓ Time-sortable (K-sortable within generator)
  ✓ B-tree friendly (append-mostly inserts)
  ✓ Still coordination-free
  ✓ Still 128-bit (same storage as v4)
  ✓ Standardized (RFC 9562, library support growing)

WEAKNESSES:
  ✗ Still 128 bits (2x int64 storage)
  ✗ Timestamp is visible (partial opacity loss vs v4)
  ✗ Clock dependency (same drift issues as Snowflake)
  ✗ Not strictly globally ordered across generators
    (Generator A at T+0ms, Generator B at T+0ms — order undefined)

LIBRARY SUPPORT (2026):
  Go:         github.com/gofrs/uuid (v7 support)
  Python:     uuid7 package, uuid-utils
  Java:       uuid-creator library
  Postgres:   pg_uuidv7 extension
  JavaScript:  uuid package (v9+ includes v7)

WHEN TO USE UUID v7:
  → You want UUID format (API compatibility, existing tooling)
  → You need time-sortable IDs without coordination
  → Insert rate is high enough that v4 index fragmentation hurts
  → You are starting a new project (greenfield — no migration cost)

WHEN NOT TO USE UUID v7:
  → You need 64-bit compact IDs (use Snowflake/Sonyflake)
  → Strict global ordering across datacenters is required
  → You cannot trust system clocks (use DB sequences or coordination)
```

---

## ULID — Universally Unique Lexicographically Sortable Identifier

```
ULID = 128-bit identifier, optimized for lexicographic sortability
       Spec: https://github.com/ulid/spec

FORMAT:
  01AN4Z07BY      79KA1307SR9V4MD3V5
  |----------|    |----------------|
   Timestamp        Randomness
   (48 bits)        (80 bits)
   Crockford's      Cryptographically secure
   Base32           random

  Total: 26 characters (vs 36 for UUID string)
  Case-insensitive, no special chars, URL-safe

BIT LAYOUT:
  0                   1                   2                   3
  0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |                      timestamp (48 bits)                      |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |     timestamp (cont.)         |      random (80 bits)       |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |                       random (continued)                      |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |                       random (continued)                      |
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

  Very similar to UUID v7 structurally.
  Key difference: Base32 encoding, 80 bits random (vs 74 in v7).

GENERATION (pseudocode):
  function generate_ulid():
    ms = current_unix_timestamp_millis()
    entropy = crypto_random_bytes(10)  // 80 bits

    // Monotonic ULID: if same millisecond, increment random portion
    if ms == last_timestamp:
      entropy = increment(entropy)  // ensures sort order within ms
    last_timestamp = ms

    return base32_encode(timestamp_ms + entropy)  // 26 chars

MONOTONIC ULID (critical feature):
  Standard ULID: two IDs in the same millisecond may sort randomly
  (random portion is random).

  Monotonic ULID: if generated in the same millisecond, the random
  portion is INCREMENTED instead of re-randomized.
  → Guarantees strict sort order even within the same millisecond.
  → Required for high-throughput single-process generators.

  Throughput with monotonic ULID:
    80 bits of random = 2^80 ≈ 1.2 × 10^24 IDs per millisecond
    (practically unlimited for any real system)

COMPARISON: ULID vs UUID v7

┌─────────────────────┬──────────────┬──────────────┐
│                     │ ULID         │ UUID v7      │
├─────────────────────┼──────────────┼──────────────┤
│ Size (binary)       │ 128 bits     │ 128 bits     │
│ Size (string)       │ 26 chars     │ 36 chars     │
│ Encoding            │ Crockford B32│ Hex + hyphens│
│ Timestamp precision │ ms           │ ms           │
│ Random bits         │ 80           │ 74           │
│ Monotonic option    │ ✓ (built-in) │ manual       │
│ RFC standard        │ ✗ (spec)     │ ✓ (RFC 9562) │
│ DB native type      │ ✗ (TEXT/BYTEA│ ✓ (UUID type)│
│ Case sensitivity    │ insensitive  │ insensitive  │
└─────────────────────┴──────────────┴──────────────┘

WHEN TO USE ULID:
  → Log correlation IDs (compact, sortable, URL-safe)
  → Object storage keys (S3 paths sort by time)
  → Message queue IDs (Kafka keys that preserve order)
  → When 26-char string is preferable to 36-char UUID
  → Application-level IDs not stored in UUID-typed DB columns

WHEN NOT TO USE ULID:
  → Database has native UUID column type (use v7 instead)
  → You need RFC-standard identifiers for compliance
  → Ecosystem tooling expects UUID format
```

---

## K-Sortable IDs — The Concept That Unifies Everything

```
K-SORTABLE ID (K-sorted ID):
  An identifier where IDs generated within time window K of each other
  are guaranteed to sort in generation order.

  Formally: if ID_a was generated before ID_b, and
  timestamp(ID_b) - timestamp(ID_a) < K,
  then ID_a < ID_b (lexicographically or numerically).

  K = the "sortability window" — depends on clock precision and drift tolerance.

WHY K-SORTABLE MATTERS:

  Without K-sortable IDs:
    SELECT * FROM events ORDER BY id LIMIT 100;
    → Random order. Useless for "recent events" queries.
    → Must add created_at column + index. Extra storage, extra index.

  With K-sortable IDs:
    SELECT * FROM events WHERE id > last_seen_id ORDER BY id LIMIT 100;
    → Approximate time order from ID alone.
    → Pagination: "give me events after this ID" — no offset/limit pain.
    → CDC/replication: process events in ID order ≈ time order.

THE K-SORTABLE FAMILY:

  ┌─────────────────┬──────────┬─────────────────────────────┐
  │ Scheme          │ K window │ Sort key                    │
  ├─────────────────┼──────────┼─────────────────────────────┤
  │ DB sequence     │ exact    │ monotonic integer           │
  │ Snowflake       │ ~1-2 sec │ timestamp + sequence        │
  │ Sonyflake       │ ~1-2 sec │ timestamp + sequence        │
  │ UUID v7         │ ~1 ms    │ timestamp ms + random       │
  │ ULID (monotonic)│ ~1 ms    │ timestamp ms + increment    │
  │ UUID v4         │ N/A      │ not sortable                │
  └─────────────────┴──────────┴─────────────────────────────┘

  "K window" = maximum clock skew between generators before
  ordering breaks. Snowflake tolerates ~2 seconds of skew
  (configurable wait time). UUID v7 breaks ordering if clocks
  differ by more than 1ms AND random portions collide in sort.

K-SORTABLE ≠ GLOBALLY ORDERED:

  This distinction kills people in interviews and in production.

  K-sortable: IDs from ONE generator sort by time.
  Globally ordered: IDs from ALL generators sort by time.

  Snowflake is K-sortable, NOT globally ordered:
    Machine A (clock T):     ...0197f2a8b07b001
    Machine B (clock T-500ms): ...0197f2a8b07a001
    → B's ID sorts BEFORE A's ID even though A generated later
    → Because B's clock is 500ms behind

  For global ordering you need:
    → TrueTime (Google Spanner — GPS + atomic clocks)
    → Centralized ID service (single coordination point)
    → Hybrid Logical Clocks (HLC — Lamport + physical time)
    → Accept approximate ordering (good enough for most apps)
```

---

## Twitter Snowflake — The Industry Standard for 64-bit IDs

```
Snowflake was invented at Twitter (~2010) to generate unique 64-bit IDs
at scale without coordination per request. It powers Twitter's tweet IDs,
Discord's snowflakes, Instagram's media IDs, and countless startups.

THE 64-BIT LAYOUT:

  0                   1                   2                   3
  0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  |0| timestamp (41 bits)         | datacenter | worker | sequence|
  | |                               |  (5 bits)  |(5 bits)|(12 bits)|
  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   1   41 bits = ~69 years           5+5=10    12 bits
   sign  from custom epoch            bits      = 4096 IDs/ms
   (unused)                           = 1024    per worker
                                      workers

FIELD BREAKDOWN:

  Sign bit (1 bit): Always 0. Reserved. Keeps IDs positive as int64.

  Timestamp (41 bits):
    Milliseconds since custom epoch (Twitter: 2010-11-04 01:42:54 UTC)
    2^41 ms = 69 years of IDs
    At 1 ID/ms: 2^41 IDs total capacity

  Datacenter ID (5 bits): 0-31 (32 datacenters)
  Worker/Machine ID (5 bits): 0-31 per datacenter (32 machines each)
    Total: 32 × 32 = 1,024 unique worker slots

  Sequence (12 bits): 0-4095 per millisecond per worker
    → 4,096 IDs per ms per worker
    → 4,096,000 IDs/sec per worker (theoretical)
    → Twitter peak: ~6,000 tweets/sec (massive headroom)

GENERATION ALGORITHM (pseudocode):

  class SnowflakeGenerator:
    EPOCH = 1288834974657  // Twitter epoch ms
    MAX_SEQUENCE = 4095

    def next_id(self):
      timestamp = current_time_millis()

      if timestamp < self.last_timestamp:
        raise ClockMovedBackwardsException()

      if timestamp == self.last_timestamp:
        self.sequence = (self.sequence + 1) & MAX_SEQUENCE
        if self.sequence == 0:
          timestamp = wait_next_millis(self.last_timestamp)
      else:
        self.sequence = 0

      self.last_timestamp = timestamp

      return (
        ((timestamp - EPOCH) << 22) |
        (self.datacenter_id << 17) |
        (self.worker_id << 12) |
        self.sequence
      )

WORKER ID ASSIGNMENT (coordination you cannot avoid):

  1. STATIC CONFIG: hash(hostname) % 32 — collision if > 32 machines
  2. ZOOKEEPER/ETCD LEASE: ephemeral node on startup
  3. KUBERNETES STATEFULSET: pod ordinal = worker_id
  4. DATABASE TABLE: INSERT RETURNING worker_id — ironic coordination

  Snowflake is "coordination-free per request" but NOT per deployment.
```

---

## Sonyflake — Snowflake Optimized for Go

```
Sonyflake bit layout (64 bits):

  |0| timestamp (39 bits, 10ms units) | sequence (8) | machine (16) |

  39 bits @ 10ms = ~17 years
  8-bit sequence = 256 IDs per 10ms = 25,600 IDs/sec per machine
  16-bit machine ID = 65,536 machines (no DC/worker split)

COMPARISON:

  ┌─────────────────────┬──────────────┬──────────────┐
  │ Field               │ Snowflake    │ Sonyflake    │
  ├─────────────────────┼──────────────┼──────────────┤
  │ Timestamp bits      │ 41 (~69 yr)  │ 39 (~17 yr)  │
  │ Timestamp unit      │ milliseconds │ 10 ms units  │
  │ Sequence bits       │ 12 (4096/ms) │ 8 (256/10ms) │
  │ Machine ID bits     │ 10 (1024)    │ 16 (65536)   │
  │ IDs/sec per machine │ 4,096,000    │ 25,600       │
  └─────────────────────┴──────────────┴──────────────┘

KUBERNETES PAIN: default machine_id = private_ip & 0xFFFF
  All pods on same node → same machine_id → COLLISION
  Fix: StatefulSet ordinal or pod UID hash as MachineID override
```

---

## Database Sequences — The Original ID Generator

```
MYSQL AUTO_INCREMENT / POSTGRES SERIAL:

  INSERT INTO orders (customer_id, total) VALUES (42, 99.99);
  → Database assigns id atomically via internal counter

POSTGRES INTERNALS:
  Sequence row in pg_catalog: last_value, increment_by, cache
  nextval(): RowExclusiveLock → increment → return
  CACHE N: pre-allocate N values per session (gaps on crash)

STRENGTHS: monotonic, compact (8 bytes), B-tree optimal, ACID
WEAKNESSES: single coordination point, not distributed, info leakage
```

---

## Postgres Sequences at Scale

```
BOTTLENECK: CACHE=1 → lock per insert → ~15K inserts/sec ceiling

MITIGATIONS:
  ALTER SEQUENCE orders_id_seq CACHE 10000;     → ~120K/sec
  Batch allocation (1000 IDs per DB call)       → ~200K/sec
  Sequence per shard with high-bit prefix       → distributed
  Switch to UUID v7 / app Snowflake             → coordination-free

FAILOVER TRAP:
  Async replica promoted → sequence last_value may lag actual MAX(id)
  Fix after failover:
    SELECT setval('orders_id_seq', (SELECT MAX(id) FROM orders) + 1000);

BENCHMARK (Postgres 16, m5.2xlarge):
  SERIAL CACHE 1:        ~15,000 inserts/sec
  SERIAL CACHE 10000:      ~120,000 inserts/sec
  UUID v4 PK:              ~12,000 inserts/sec
  UUID v7 PK:              ~38,000 inserts/sec
  BIGINT Snowflake PK:     ~45,000 inserts/sec
```

---

## DynamoDB Counter Patterns

```
PATTERN 1 — ATOMIC COUNTER (simple, ~1K IDs/sec max):
  UpdateItem: SET counter_value = counter_value + 1
  Single partition key limit: 1000 WCU/sec

PATTERN 2 — BLOCK ALLOCATION (recommended):
  UpdateItem: SET counter_value = counter_value + 1000
  App serves 1000 IDs from memory → ~1M IDs/sec

PATTERN 3 — TIME-BASED / ULID / UUID v7 (no counter table):
  Unlimited throughput, K-sortable, coordination-free

PATTERN 4 — SHARDED COUNTERS:
  PK: counter_name#shard_id (64 shards × 1K WCU = 64K/sec)

PATTERN 5 — APP SNOWFLAKE AS PK:
  Skip DynamoDB counter entirely; Snowflake in application layer

HOT PARTITION WARNING:
  Sequential IDs as DynamoDB PK → ALL writes hit ONE partition
  Fix: PK = customer_id (high cardinality), SK = Snowflake order_id
```

---

## Coordination-Free vs Coordination-Heavy

```
SPECTRUM:

  COORDINATION-FREE ◄────────────────────────► COORDINATION-HEAVY
  UUID v4/v7/ULID     Snowflake (worker at deploy)   DB sequence   ID service

COORDINATION-FREE:
  ✓ No network per ID, no SPOF, survives partitions
  ✗ Worker ID assignment, clock dependency, approximate ordering

COORDINATION-HEAVY:
  ✓ Strict order, zero collision risk, simple model
  ✗ Latency per ID, throughput ceiling, SPOF on coordinator

HYBRID (production):
  BIGSERIAL internal PK + UUID v4 public API
  Block allocation (1 DB call per 10,000 IDs)
  Region prefix + Snowflake local ID

HEURISTICS:
  Collision catastrophic? → coordination-heavy
  Need strict global order? → coordination-heavy or TrueTime
  Peak rate > 50K/sec? → Snowflake/UUID v7
  Peak rate < 1K/sec? → database sequence is fine
```

---

## Clock Drift — The Hidden Enemy

```
PROBLEM: K-sortable IDs embed timestamps. Clocks drift, step, leap.

Machine B clock 2 seconds behind → IDs sort BEFORE older IDs from A
NTP step backward → Snowflake throws ClockMovedBackwardsException

CAUSES: crystal drift (0.5-2.5 sec/day), NTP stepping, leap seconds,
        VM live migration, container pause/resume

MITIGATIONS:
  1. wait_next_millis() on same-ms collision
  2. Tolerate small backward drift (use last_timestamp if offset <= 5ms)
  3. Logical increment: timestamp = last_timestamp + 1 on drift
  4. TrueTime (Spanner) — GPS + atomic clocks, 7ms uncertainty
  5. Hybrid Logical Clocks (CockroachDB)
  6. Monitor chronyc tracking; alert if |offset| > 100ms

PRODUCTION RULE:
  Implement backward-clock handling. Monitor clock offset. Chaos-test NTP steps.
```

---
## Concrete Examples — Real Systems, Real Choices

```
This section walks through four production architectures and explains
WHY each team chose their ID strategy — not just what they use.
```

### Example 1: E-Commerce Order IDs (Shopify-scale)

```
REQUIREMENTS:
  → 50,000+ orders/minute peak (Black Friday)
  → Order ID visible to customers ("Your order #104829103")
  → Must sort roughly by creation time (support tools, analytics)
  → Multi-region (US, EU, APAC active-active)
  → Cannot leak exact order volume to competitors

ARCHITECTURE CHOICE: Snowflake-style 64-bit integer

  Internal representation: BIGINT (8 bytes)
  Customer-facing: formatted string "ORD-104829103" (prefix + zero-pad)

  Bit layout (Shopify-inspired, simplified):
    | timestamp (41 bits) | shard_id (10 bits) | sequence (12 bits) |

  shard_id = hash(shop_id) % 1024  (spread across DB shards)
  Generated in application layer — no DB round-trip per order

WHY NOT UUID v4:
  → 50K orders/min = 833/sec sustained, spikes to 5K/sec
  → UUID v4 PK caused 3.2x write amplification on their MySQL shards
  → Customer support tools need "orders after X" — random UUID useless

WHY NOT DB SEQUENCE:
  → Sharded MySQL — no global sequence across 1024 shards
  → Per-shard sequence leaks shard assignment
  → Sequence hot spot on single-shard shops (large merchants)

WHY NOT UUID v7:
  → Valid choice today; Shopify predates v7 standardization
  → 64-bit int is more compact than 128-bit UUID for index size
  → Existing customer-facing format expects numeric order numbers

DEPLOYMENT:
  worker_id assigned via Kubernetes StatefulSet ordinal
  datacenter_id from AWS region config map
  Clock drift: tolerate 5ms backward, alert on > 100ms
  Duplicate detection: unique constraint on order_id (belt and suspenders)

LESSON: At e-commerce scale with sharded DB, app-generated K-sortable
  64-bit IDs beat both UUID v4 and DB sequences.
```

### Example 2: Financial Ledger (Bank Transfer System)

```
REQUIREMENTS:
  → Every transaction ID must be STRICTLY unique (regulatory)
  → Strict monotonic ordering within account (audit trail)
  → Duplicate ID = potential double-spend = catastrophic
  → Moderate volume: ~2,000 transactions/sec peak
  → Single primary region (regulatory data residency)

ARCHITECTURE CHOICE: Postgres BIGSERIAL + application validation

  CREATE TABLE ledger_entries (
    id          BIGSERIAL PRIMARY KEY,
    account_id  BIGINT NOT NULL,
    amount      DECIMAL(18,2) NOT NULL,
    entry_type  TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now() NOT NULL,
    idempotency_key UUID UNIQUE  -- client-supplied dedup key
  );

  ALTER SEQUENCE ledger_entries_id_seq CACHE 1000;

WHY NOT SNOWFLAKE:
  → Regulatory audit requires "database-assigned sequential ID"
  → Auditors understand sequences; explaining Snowflake worker IDs is painful
  → 2K/sec is well within Postgres sequence capacity with CACHE 1000

WHY NOT UUID v4:
  → Auditors want sequential audit trail: entry 100001 before 100002
  → Random IDs make forensic reconstruction harder

IDEMPOTENCY LAYER:
  Client sends idempotency_key (UUID v4) with each transfer request
  UNIQUE constraint on idempotency_key prevents duplicate processing
  If retry with same key → return existing entry, don't create new one

  This separates two concerns:
    id (BIGSERIAL) = authoritative audit sequence
    idempotency_key (UUID v4) = client-side deduplication

FAILOVER PROCEDURE (documented in runbook):
  After primary failover:
    SELECT setval('ledger_entries_id_seq',
      (SELECT MAX(id) FROM ledger_entries) + 10000);
  +10000 buffer accounts for CACHE 1000 × multiple connections

LESSON: When regulatory/audit requirements demand strict sequential
  ordering and volume is moderate, DB sequences + idempotency keys
  beat distributed ID generators.
```

### Example 3: Social Media Post IDs (Twitter/X Architecture)

```
REQUIREMENTS:
  → 6,000+ tweets/sec peak (historical Twitter peak)
  → Tweet ID in every URL: twitter.com/user/status/1742812200123008001
  → Must be unique globally, sortable by time (timeline reconstruction)
  → Multi-datacenter, coordination-free per tweet
  → 64-bit integer (JavaScript safe: Number.MAX_SAFE_INTEGER = 2^53-1)

ARCHITECTURE: Original Twitter Snowflake (2010, Scala)

  64-bit layout as documented above
  ~1024 worker slots across all datacenters
  Zookeeper for worker ID lease management

TIMELINE URL ENCODING:
  Tweet ID 1742812200123008001 embeds:
    → Approximate creation time (decode timestamp bits)
    → Datacenter origin
    → Sequence within millisecond

  This is why you can sort tweets by ID ≈ sort by time
  (within clock skew tolerance).

MIGRATION NOTE (post-2022):
  Twitter migrated infrastructure; Snowflake-compatible IDs maintained
  for backward compatibility (URLs, API contracts).
  Changing ID format = breaking every tweet URL ever created.
  ID format is a PERMANENT architectural decision.

JAVASCRIPT SAFE INTEGER PROBLEM:
  Snowflake IDs exceed Number.MAX_SAFE_INTEGER (9007199254740991)
  JavaScript clients MUST use BigInt or string representation

  // WRONG in JavaScript:
  const tweetId = 1742812200123008001;  // precision loss!

  // RIGHT:
  const tweetId = BigInt("1742812200123008001");
  // Or always treat as string in JSON APIs

LESSON: Snowflake is the reference design for high-throughput,
  time-sortable, coordination-free 64-bit IDs. Once chosen and
  exposed in URLs, you cannot change the format.
```

### Example 4: Multi-Tenant SaaS on DynamoDB

```
REQUIREMENTS:
  → 500 tenants, variable load (10-10,000 events/sec per tenant)
  → Event IDs for audit log, searchable by time range
  → DynamoDB single-table design
  → No Postgres/RDS in the architecture
  → Cost-sensitive (avoid hot partitions)

ARCHITECTURE CHOICE: UUID v7 as string sort key

  Table: tenant_events
    PK: tenant_id (String)       ← spreads writes across partitions
    SK: event_id (String, UUID v7) ← K-sortable within tenant
    GSI1PK: tenant_id
    GSI1SK: created_at           ← explicit timestamp for range queries

  event_id = generate_uuid_v7()  // application layer, no DynamoDB counter

QUERY PATTERNS:

  Recent events for tenant:
    Query PK=tenant_123, SK > uuid_v7_from_24h_ago, ScanIndexForward=true

  Event by exact ID:
    GetItem PK=tenant_123, SK=event_id

WHY NOT DYNAMODB COUNTER:
  → 500 tenants × counter table = operational overhead
  → Hot partition on high-volume tenants
  → Counter adds latency (~5ms UpdateItem per event)

WHY NOT SNOWFLAKE AS PK:
  → Snowflake as PK without tenant prefix = time-based hot partition
  → All recent writes hit partition for "current millisecond"
  → tenant_id as PK + UUID v7 as SK spreads load correctly

WHY UUID v7 OVER ULID:
  → DynamoDB SK is String type — both work
  → UUID v7 has growing library support
  → Team already uses UUID type in other services

LESSON: In DynamoDB, partition key design dominates ID choice.
  High-cardinality PK (tenant_id) + K-sortable SK (UUID v7) beats
  any counter-based or sequential PK pattern.
```

---

## Production Patterns — How Teams Actually Ship This

### Pattern 1: Dual-ID Column Strategy

```
The most common production pattern at scale:

  CREATE TABLE resources (
    id            BIGSERIAL PRIMARY KEY,        -- internal, sequential
    public_id     UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),  -- API
    created_at    TIMESTAMPTZ DEFAULT now()
  );

  Internal joins, FKs, analytics: use `id` (BIGINT, fast)
  Public API responses: use `public_id` (UUID, opaque)
  External URLs: /api/v1/resources/{public_id}

WHY BOTH:
  → BIGINT PK: B-tree optimal, compact FKs, fast joins
  → UUID public: opaque, no enumeration attacks, safe in URLs
  → Sequential internal ID never exposed = no volume leakage

VARIANT (Snowflake public ID):
  public_id BIGINT NOT NULL UNIQUE  -- Snowflake, customer-facing numeric ID
  Used when: "order number" UX requires numeric ID (e-commerce)
```

### Pattern 2: ID Generation Sidecar

```
For teams that want centralized ID generation without DB bottleneck:

  ┌─────────────┐     gRPC      ┌──────────────────┐
  │  Service A  │──────────────►│  ID Service      │
  └─────────────┘   batch(1000) │  (Leaf / custom) │
  ┌─────────────┐──────────────►│                  │
  │  Service B  │               │  Zookeeper/etcd  │
  └─────────────┘               │  worker registry │
                                └──────────────────┘

  Meituan Leaf architecture:
    Segment mode: DB allocates ID ranges (10K at a time) — CP, high perf
    Snowflake mode: local generation with ZK worker ID — AP, highest perf

  Request pattern:
    Client: "Give me 1000 IDs"
    ID Service: returns [1000001..1001000] from pre-allocated segment
    Client: serves from memory for next 1000 operations

  When to use:
    → Many services need IDs (centralize worker ID management)
    → Want Snowflake benefits without per-service ZK integration
    → Need to switch ID strategies without redeploying all services
```

### Pattern 3: Embedded Shard ID in Snowflake

```
For sharded databases, embed shard ID in the Snowflake layout:

  Custom layout (example):
    | timestamp (41) | shard_id (10) | sequence (12) |

  shard_id = consistent_hash(tenant_id) % 1024

  Routing:
    Given ID → extract shard_id from bits → route query to correct shard
    Given new record → compute shard from tenant → generate ID on that shard's worker

  Benefit: ID alone tells you which shard holds the record
  Used by: Instagram (shard_id in media ID), Discord (internal shard routing)

  Decode shard from ID (Python):
    def shard_from_id(snowflake_id):
        return (snowflake_id >> 12) & 0x3FF  # 10 bits
```

### Pattern 4: Client-Generated IDs (Offline-First)

```
Mobile apps, collaborative editors, offline-capable systems:

  Client generates UUID v4 or UUID v7 locally BEFORE sync
  Syncs to server with client-generated ID as PK

  CREATE TABLE documents (
    id UUID PRIMARY KEY,  -- client-supplied, NOT DEFAULT
    user_id BIGINT,
    content JSONB,
    synced_at TIMESTAMPTZ
  );

  INSERT ... ON CONFLICT (id) DO NOTHING  -- idempotent sync

  Why UUID v4/v7:
    → Client cannot call server for ID while offline
    → Must generate locally with negligible collision risk
    → v7 preferred when client needs to sort local changes by time

  Conflict handling:
    Same UUID from two offline clients = same document (CRDT merge)
    Or: last-write-wins with vector clock on separate column
```

### Pattern 5: Observability Correlation IDs

```
Not primary keys — but ID generation patterns apply:

  Request enters API gateway → generate ULID → attach to all logs/traces

  X-Request-ID: 01JXYZ1234567890ABCDEFGHJK
  X-Trace-ID:    (same or derived)

  Why ULID for correlation:
    → 26 chars (compact in log lines)
    → Sortable → grep logs chronologically without parsing timestamp
    → URL-safe → safe in HTTP headers

  Implementation (middleware):
    request_id = request.headers.get('X-Request-ID') or generate_ulid()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response.headers['X-Request-ID'] = request_id
```

---

## Production Failure Patterns

### Failure 1: Snowflake Worker ID Collision

```
SCENARIO:
  E-commerce platform, 40 Kubernetes pods, Snowflake ID generator.
  worker_id = hash(hostname) % 32

  Two pods hash to same worker_id (birthday paradox at scale):
    pod-order-api-7f8a9b  → hash % 32 = 17
    pod-order-api-3c2d1e  → hash % 32 = 17  ← COLLISION

  Both pods generate IDs with worker_id=17, datacenter_id=1.
  Same millisecond + same sequence counter state = DUPLICATE ID.

SYMPTOMS:
  → Primary key violations spike (duplicate key errors in logs)
  → Intermittent — only when both pods generate in same ms
  → Affects ~0.01% of orders (hard to reproduce)
  → Error: "duplicate key value violates unique constraint orders_pkey"

HOW TO DETECT:
  → Monitor duplicate key error rate on orders table
  → Decode conflicting IDs — same worker_id + datacenter_id?
  → Audit worker_id assignment across all pods:
    kubectl exec -it pod -- curl localhost:8080/debug/worker-id

FIX:
  Immediate: switch to StatefulSet ordinals (guaranteed unique 0-39)
  Long-term: Zookeeper/etcd lease for worker ID assignment
  Belt: UNIQUE constraint catches collisions (already have this)

PREVENTION:
  → Never use hash(hostname) % N without collision detection
  → Startup self-test: register worker_id, fail if already claimed
  → Alert on duplicate key rate > 0
```

### Failure 2: Clock Step Backward — ID Generation Halt

```
SCENARIO:
  NTP daemon on production server detects 3-second clock drift.
  Executes step correction: clock jumps BACK 3 seconds.

  Snowflake generator:
    last_timestamp = 1751812205500
    current_time  = 1751812202500  (3 seconds earlier)

    → ClockMovedBackwardsException thrown
    → ALL ID generation stops on this machine
    → Orders fail with 500 Internal Server Error

  12 pods affected simultaneously (same NTP correction window).
  Order creation error rate: 100% for 30 seconds until NTP re-syncs.

SYMPTOMS:
  → Sudden 500 errors on create endpoints
  → Logs: "Clock moved backwards. Refusing to generate id"
  → Correlated across multiple pods (same NTP event)
  → Self-heals when clock catches up (or doesn't — stuck if drift persists)

HOW TO DETECT:
  → Alert on ClockMovedBackwardsException in logs
  → Monitor chrony offset: alert if step detected
  → Metric: id_generation_errors_total{reason="clock_drift"}

FIX (code change):
  # Instead of throwing, tolerate small backward drift:
  MAX_DRIFT_MS = 5000

  if timestamp < last_timestamp:
      offset = last_timestamp - timestamp
      if offset <= MAX_DRIFT_MS:
          timestamp = last_timestamp  # use logical time
          log.warn("clock_drift", offset_ms=offset)
      else:
          raise ClockMovedBackwardsException(offset)

  This keeps generating IDs during small NTP corrections.
  IDs may have slightly "future" timestamps — acceptable for K-sortable.

PREVENTION:
  → Use chrony with slew-only mode in containers (disable stepping)
  → Monitor clock offset as first-class metric
  → Load test ID generator with simulated clock jumps
```

### Failure 3: Postgres Sequence Out of Sync After Failover

```
SCENARIO:
  Primary Postgres: orders_id_seq last_value = 5,000,000
  Actual MAX(id) in orders table = 5,000,050
  (50 IDs cached in application connections, not yet inserted)

  Primary crashes. Standby promoted.
  Standby sequence last_value = 4,999,900 (replication lag on sequence)

  New inserts on promoted standby:
    nextval() returns 4,999,901, 4,999,902, ...
    But rows 4,999,901 through 5,000,050 ALREADY EXIST

    → Duplicate key violations on every insert
    → Application appears "broken" after "successful" failover

SYMPTOMS:
  → Failover completes successfully (Patroni green)
  → Immediate duplicate key errors on INSERT
  → MAX(id) >> sequence last_value
  → Only affects write path; reads work fine

HOW TO DETECT:
  Post-failover automated check (runbook step 1):
    SELECT
      last_value AS seq_value,
      (SELECT MAX(id) FROM orders) AS max_id,
      last_value - (SELECT MAX(id) FROM orders) AS gap
    FROM orders_id_seq;

    If gap < 0: SEQUENCE IS BEHIND — run setval immediately

FIX (immediate, in failover runbook):
  SELECT setval('orders_id_seq',
    (SELECT MAX(id) FROM orders) + 10000);

  +10000 buffer for cached IDs across all app connections

PREVENTION:
  → Automate sequence sync in failover script (Patroni callback)
  → pg_logical replication: replicate sequences explicitly
  → Use application Snowflake — eliminates sequence failover issue entirely
```

### Failure 4: UUID v4 Index Bloat — Silent Performance Degradation

```
SCENARIO:
  Startup uses UUID v4 PK "because it's best practice."
  50M rows over 18 months. Insert rate: 200/sec (moderate).

  Symptoms emerge gradually:
    → Insert latency p99: 5ms → 45ms over 6 months
    → Table size: 8 GB data, 22 GB indexes
    → Autovacuum constantly running on orders table
    → Buffer cache hit ratio drops (index pages churn)

  Root cause analysis:
    EXPLAIN INSERT INTO orders ... ;
    → Random UUID inserts cause page splits on EVERY insert
    → Index bloat: 60% of index pages are half-full from splits
    → No sequential locality — every insert touches different pages

HOW TO DETECT:
  → Track insert latency p99 trend (gradual degradation)
  → pgstattuple on index:
    SELECT * FROM pgstatindex('orders_pkey');
    -- avg_leaf_density < 70% = significant bloat
  → Compare insert benchmark: UUID v4 vs BIGINT on staging

FIX (painful migration):
  Option A: Add BIGINT column, backfill, swap PK (online migration)
  Option B: pg_repack index rebuild (temporary relief, not permanent)
  Option C: Switch to UUID v7 (still 128-bit but append-mostly)

  Online migration pattern (gh-ost / pg-osc):
    1. ADD COLUMN id_v7 UUID
    2. Backfill id_v7 for existing rows (any v7 value)
    3. New inserts use UUID v7
    4. Swap PK constraint during maintenance window

PREVENTION:
  → Load test with expected row count BEFORE choosing UUID v4 PK
  → Default to UUID v7 or BIGINT Snowflake for high-volume tables
  → Monitor index bloat metrics from day one
```

### Failure 5: DynamoDB Hot Partition from Sequential Counter

```
SCENARIO:
  Serverless app uses DynamoDB atomic counter for order IDs.

  Table: counters, PK: "global_order_id"
  Every order: UpdateItem on "global_order_id" (+1)

  Black Friday: 5,000 orders/sec
  DynamoDB limit: 1,000 WCU/sec per partition key

  → Throttling: ProvisionedThroughputExceededException
  → Orders fail intermittently (retry storm makes it worse)
  → CloudWatch: ConsumedWriteCapacityUnits pegged at 1000

SYMPTOMS:
  → 503 errors on checkout endpoint
  → DynamoDB metrics: ThrottledRequests > 0 on counters table
  → Latency spike on UpdateItem (retries with exponential backoff)
  → Error rate correlates with traffic spike

HOW TO DETECT:
  → CloudWatch: ThrottledRequests metric on counters table
  → Alert: ThrottledRequests > 0 for 1 minute
  → X-Ray trace: UpdateItem on counters table taking > 100ms

FIX (immediate):
  Switch to block allocation (if not already):
    Pre-allocate 10,000 IDs per UpdateItem
    Reduces write rate by 10,000x

FIX (architectural):
  Remove counter table entirely.
  Generate UUID v7 in Lambda/application.
  Use as SK with tenant_id as PK.

PREVENTION:
  → Never use single-item counter above 500 ops/sec
  → Load test counter pattern at expected peak before launch
  → Architecture review: "where is the hot partition?"
```

### Failure 6: Sonyflake Machine ID Collision in Kubernetes

```
SCENARIO:
  Go microservice uses Sonyflake with default MachineID (private IP & 0xFFFF).
  Deployed as Deployment (not StatefulSet) with 20 replicas on 4 nodes.

  5 pods per node → all share same private IP → same machine_id

  Each 10ms window: 256 IDs max per machine_id
  5 pods × 256 = need 1280 IDs per 10ms
  → Sequence exhaustion → pods spin-wait → latency spike
  → Worse: if sequences overlap timing, DUPLICATE IDs

SYMPTOMS:
  → Duplicate key errors under load
  → p99 latency spikes every 10ms (sequence reset cycle)
  → Errors correlate with pod count increase

FIX:
  settings := sonyflake.Settings{
    MachineID: func() (uint16, error) {
      ordinal := os.Getenv("POD_ORDINAL")  // from StatefulSet
      return uint16(ordinal), nil
    },
  }

  Change Deployment → StatefulSet for guaranteed ordinals.

PREVENTION:
  → Never use default IP-based MachineID in Kubernetes
  → Integration test: deploy N replicas, generate 1M IDs, assert unique
  → Document MachineID assignment in service README
```

---

## SRE Diagnostic Toolkit

```
ID GENERATION DEBUGGING:
━━━━━━━━━━━━━━━━━━━━━━━

# ── POSTGRES SEQUENCE HEALTH ──

# Check sequence vs max ID (run after ANY failover)
psql -c "
  SELECT
    seq.relname AS sequence_name,
    seq.last_value,
    t.max_id,
    seq.last_value - t.max_id AS headroom
  FROM (
    SELECT last_value FROM orders_id_seq
  ) seq,
  (
    SELECT MAX(id) AS max_id FROM orders
  ) t;
"
# headroom < 0 → SEQUENCE BEHIND TABLE — run setval NOW
# headroom < 1000 → low buffer, increase CACHE or setval

# Fix sequence after failover:
psql -c "
  SELECT setval('orders_id_seq',
    (SELECT COALESCE(MAX(id), 0) FROM orders) + 10000);
"

# Check sequence cache setting:
psql -c "SELECT * FROM pg_sequences WHERE sequencename = 'orders_id_seq';"

# Find gaps in sequence (expected with CACHE > 1):
psql -c "
  SELECT id, id - LAG(id) OVER (ORDER BY id) AS gap
  FROM orders
  WHERE id - LAG(id) OVER (ORDER BY id) > 1
  LIMIT 20;
"


# ── SNOWFLAKE ID DECODE ──

# Python one-liner to decode Snowflake ID:
python3 -c "
id = 1742812200123008001
epoch = 1288834974657
ts = ((id >> 22) + epoch) / 1000
dc = (id >> 17) & 0x1F
worker = (id >> 12) & 0x1F
seq = id & 0xFFF
import datetime
print(f'timestamp: {datetime.datetime.utcfromtimestamp(ts)}')
print(f'datacenter: {dc}, worker: {worker}, sequence: {seq}')
"

# Check if two duplicate IDs have same worker (collision signature):
# Same dc + worker + timestamp + sequence = definite worker collision


# ── UUID ANALYSIS ──

# Identify UUID version:
python3 -c "
import uuid
u = uuid.UUID('550e8400-e29b-41d4-a716-446655440000')
print(f'version: {u.version}')  # 4 = random, 7 = time-based
"

# Decode UUID v7 timestamp:
python3 -c "
import uuid
u = uuid.UUID('0197f2a8-b07b-7000-8000-000000000000')
if u.version == 7:
    ts_ms = (u.int >> 80) & 0xFFFFFFFFFFFF
    import datetime
    print(datetime.datetime.utcfromtimestamp(ts_ms / 1000))
"


# ── CLOCK DRIFT MONITORING ──

# Check NTP sync status:
timedatectl status

# Chrony tracking (preferred on modern Linux):
chronyc tracking
chronyc sources -v

# Alert threshold check:
chronyc tracking | awk '
  /Last offset/ {
    offset = ($3 < 0) ? -$3 : $3
    if (offset > 0.1) print "ALERT: clock offset " $3 " seconds"
  }'

# Simulate clock step (CHAOS TEST — staging only):
# sudo date -s "-3 seconds"  # step backward 3 sec
# Watch ID generator behavior — should tolerate or alert, not silent duplicate


# ── DYNAMODB COUNTER HEALTH ──

# Check throttling on counter table:
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name ThrottledRequests \
  --dimensions Name=TableName,Value=id_counters \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum

# Check consumed capacity vs provisioned:
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name ConsumedWriteCapacityUnits \
  --dimensions Name=TableName,Value=id_counters \
  --period 60 --statistics Maximum \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S)


# ── DUPLICATE ID DETECTION ──

# Postgres: find duplicate primary keys (should return 0 rows):
psql -c "
  SELECT id, COUNT(*) FROM orders GROUP BY id HAVING COUNT(*) > 1;
"

# Application log grep for duplicate key errors:
grep -i "duplicate key\|unique constraint\|DuplicateEntry" \
  /var/log/app/*.log | tail -50

# Rate of duplicate errors (CloudWatch Logs Insights):
# fields @timestamp, @message
# | filter @message like /duplicate key/
# | stats count() by bin(1m)


# ── WORKER ID AUDIT (KUBERNETES) ──

# Check worker IDs across all pods:
for pod in $(kubectl get pods -l app=order-api -o name); do
  worker=$(kubectl exec $pod -- \
    curl -s localhost:8080/debug/worker-id 2>/dev/null)
  echo "$pod → worker_id=$worker"
done | sort -t= -k2 | uniq -f1 -D
# uniq -D shows duplicates — any duplicate = collision risk


COMMON "WHY ARE MY IDS COLLIDING?" CHECKLIST:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  □ Same worker_id assigned to multiple processes?
  □ Clock stepped backward without tolerance logic?
  □ Sequence exhausted and wraparound not handled?
  □ Postgres sequence behind MAX(id) after failover?
  □ DynamoDB counter hot partition throttling + retry dupes?
  □ UUID v4 with broken PRNG (same seed on VM clone)?
  □ Sonyflake default MachineID in Kubernetes Deployment?
  □ Two services writing to same ID namespace without coordination?
```

---

## Decision Framework

```
WHICH ID STRATEGY FOR YOUR SYSTEM?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1: What is your peak ID generation rate?

  < 1,000/sec     → Database sequence (SERIAL + CACHE 1000)
  1K - 50K/sec    → Sequence with CACHE 10000 OR block allocation
  50K - 500K/sec  → Snowflake / UUID v7 in application layer
  > 500K/sec      → Snowflake cluster + audit worker ID capacity

STEP 2: Do IDs need to be sortable by creation time?

  Strict global order     → DB sequence OR centralized ID service
  Approximate time order  → Snowflake / UUID v7 / ULID
  No ordering needed      → UUID v4

STEP 3: Are IDs exposed externally?

  Public API / URLs       → Opaque (UUID v4/v7, not sequential int)
  Internal only           → BIGINT serial or Snowflake OK
  Customer-facing numeric → Snowflake with formatted prefix (ORD-xxx)

STEP 4: Single region or multi-region active-active?

  Single region           → DB sequence works fine
  Multi-region            → Coordination-free (Snowflake/UUID v7)
                            Worker ID per region/DC required

STEP 5: What database?

  Postgres/MySQL (B-tree) → Avoid UUID v4 PK; prefer BIGINT or UUID v7
  DynamoDB                → Never sequential PK; tenant_id + UUID v7 SK
  Cassandra (LSM)           → UUID v4 OK (LSM handles random writes)
  CockroachDB               → Uses HLC internally; UUID v4 or v7 both fine

QUICK REFERENCE TABLE:

  ┌─────────────────────┬──────────┬─────────┬──────────┬───────────┐
  │ Requirement         │ UUID v4  │ UUID v7 │ Snowflake│ DB Seq    │
  ├─────────────────────┼──────────┼─────────┼──────────┼───────────┤
  │ < 1K/sec            │ ✓        │ ✓       │ ✓        │ ✓ BEST    │
  │ > 50K/sec           │ ✗        │ ✓       │ ✓ BEST   │ ✗         │
  │ Time-sortable       │ ✗        │ ✓       │ ✓        │ ✓         │
  │ Public API opaque   │ ✓ BEST   │ ✓       │ partial  │ ✗         │
  │ Multi-region        │ ✓        │ ✓       │ ✓        │ ✗         │
  │ B-tree index        │ ✗        │ ✓       │ ✓        │ ✓ BEST    │
  │ 64-bit compact      │ ✗        │ ✗       │ ✓ BEST   │ ✓         │
  │ Zero coordination   │ ✓ BEST   │ ✓       │ partial  │ ✗         │
  │ Audit/sequential    │ ✗        │ partial │ partial  │ ✓ BEST    │
  │ DynamoDB PK         │ ✗        │ ✓ SK    │ ✓ SK     │ ✗         │
  └─────────────────────┴──────────┴─────────┴──────────┴───────────┘

WHEN IN DOUBT:
  New project, Postgres, public API → UUID v7 (public) + BIGSERIAL (internal)
  New project, DynamoDB → tenant_id PK + UUID v7 SK
  New project, high scale, numeric IDs → Snowflake 64-bit
  Legacy system with sequences → keep sequences, add UUID public_id column
```

---

## Hands-On Exercises

```
EXERCISE 1: Decode a Snowflake ID
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Given tweet ID: 1742812200123008001

  Write the decode steps:
    1. Convert to binary
    2. Extract timestamp, datacenter, worker, sequence
    3. Convert timestamp to human-readable UTC

  Verify with Python:
    id = 1742812200123008001
    epoch = 1288834974657
    print(f'ts_ms: {(id >> 22) + epoch}')
    print(f'dc: {(id >> 17) & 0x1F}')
    print(f'worker: {(id >> 12) & 0x1F}')
    print(f'seq: {id & 0xFFF}')


EXERCISE 2: Compare Insert Performance (Postgres)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Create three identical tables, different PK types:
    orders_serial (BIGSERIAL PK)
    orders_uuid4  (UUID PK DEFAULT gen_random_uuid())
    orders_uuid7  (UUID PK — use pg_uuidv7 or app-generated)

  Insert 1M rows each, measure:
    time INSERT 1000000 rows
    pg_table_size('orders_*') for index size
    pgstatindex('orders_*_pkey') for leaf density

  Expected: serial ≈ uuid7 >> uuid4


EXERCISE 3: Simulate Clock Drift
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  In a Snowflake generator implementation:
    1. Generate 100 IDs normally
    2. Manually set last_timestamp 5 seconds ahead
    3. Generate 100 more IDs
    4. Observe: exception thrown? IDs still unique? IDs still monotonic?

  Questions:
    → Does your implementation throw or tolerate?
    → Are IDs still unique after tolerance?
    → Do IDs have "future" timestamps?


EXERCISE 4: DynamoDB Hot Partition Demo
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Create counter table with single PK "test_counter"
  Run 50 concurrent Lambda functions, each doing 100 UpdateItem +1
  Observe ThrottledRequests in CloudWatch

  Then: switch to block allocation (increment by 100)
  Re-run. Compare throttling.


EXERCISE 5: Worker ID Collision Detection
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Deploy 10 instances with worker_id = hash(uuid4()) % 32
  Each generates 10,000 IDs
  Collect all IDs in a set — check len(set) == len(all_ids)

  Repeat 10 times. How often do you see collisions?
  (Birthday paradox: collision probability rises faster than intuition suggests)
```

---

## Ops Sim: Northstar Snowflake Duplicate Burst

**Time box:** 45 minutes
**Severity:** P0
**Service / domain:** ID service, Kubernetes deployment, order IDs, Kafka keys, database uniqueness
**Northstar system:** Northstar Commerce

### Rules

1. Answer from memory of the Unique ID Generation teaching section; do not re-read mid-drill.
2. Write decisions in order (T+0 -> T+60).
3. Name evidence (metric, log line, trace, or config key) for every claim.
4. Do not open `answers/` until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  - Checkout returns order already exists for new purchases.
  - Some payment ledger events share order IDs.
  - Support tickets mention retries, stale state, or inconsistent checkout behavior.

WHAT ON-CALL SEES:
  - Two pods run with the same worker_id after autoscaler reuse.
  - NTP stepped clocks backward by 1.8 seconds.
  - A well-meaning mitigation is already making one dependency hotter.

BUSINESS CONSTRAINT:
  Preserve checkout correctness and money/inventory invariants. Degrade freshness, dashboards,
  recommendations, or noncritical notifications before risking duplicate effects.
```

### 2. Telemetry pack

```text
METRICS:
  duplicate_key_errors orders: 0 -> 11k/min
  id_worker_id_cardinality expected=256 observed=211
  clock_rollback_detected_total: +4800
  snowflake_sequence_exhausted_total: +780
  kafka_compacted_order_events: +3200
  payment_ledger_id_conflicts: 220
  checkout_success_rate: 99.3% -> 81%
  id_service_p99_ms: 4 -> 520

LOG LINES:
  id-service: worker_id=77 assigned to pod-a and pod-r
  id-service: clock moved backwards 1832ms; continuing anyway
  orders-db: duplicate key violates orders_pkey
  kafka: compacted duplicate key order_id=7819

TRACES / LAG / EXPLAIN:
  critical request -> suspect dependency -> queue/retry/lag -> user-visible symptom
  compare hot slice vs fleet average before deciding to scale or fail over
```

### 3. Config pack

```yaml
worker_id_source: env_static
on_clock_rollback: continue
sequence_bits: 12
pod_template_worker_id: 77
unique_order_id_required: true
```

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | Page fires: Checkout returns order already exists for new purchases. | |
| T+5 | Someone proposes: ignore duplicate inserts. | |
| T+15 | Evidence confirms: Snowflake uniqueness was broken by duplicate worker IDs and unsafe clock-rollback behavior. | |
| T+30 | Product asks to preserve the launch/revenue path despite risk. | |
| T+60 | New traffic is stable; old ambiguous records still need repair. | |

### 5. Questions

**Q1 - Layer & root cause:** Which layer owns the primary symptom? What is the exact mechanism?

**Q2 - Trigger vs amplifier:** What started the incident, and what made it worse after T+0?

**Q3 - Evidence:** Pick three metrics, two log lines, and one config key that prove your diagnosis.

**Q4 - Red herring:** Which fleet average, healthy check, or scary downstream metric could mislead the room?

**Q5 - First 5 minutes:** What do you announce, freeze, disable, or rate-limit immediately?

**Q6 - First 15 minutes:** Write the ordered mitigation sequence. Include rollback and verification after each step.

**Q7 - Bad fix gallery:** Reject these proposals and name the failure mode:
- ignore duplicate inserts
- continue on clock rollback
- reuse worker IDs manually
- trust compacted Kafka as complete history

**Q8 - Capacity / blast radius:** Estimate scarce resources before scaling or failover:
- queue depth or lag derivative
- connection/thread/pool headroom
- disk/WAL/compaction/ingest time-to-fill where relevant
- affected orders, users, tenants, or events requiring reconciliation

**Q9 - Correctness invariant:** What must remain true even while experience degrades?

**Q10 - Data repair:** Which source of truth defines the affected set? How do you replay without duplicate side effects?

**Q11 - Durable fix:** Propose architecture/config changes and acceptance criteria for:
- central worker lease/fencing
- monotonic clock handling
- halt on rollback beyond threshold
- database uniqueness plus audit log

**Q12 - Alerting:** Which symptom alert should have paged earlier? Which noisy alert should be demoted?

**Q13 - Org / runbook:** Who joins by T+10, what is pre-authorized, and what needs senior approval?

### 6. Self-score (after answer key)

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Knowledge gap | | |
| Misread / wrong layer | | |
| Sequencing error | | |
| Capacity miss | | |
| Consistency/invariant miss | | |
| Org/runbook miss | | |

**Answer key:** [../answers/Week-07-Specialized-Components/Unique ID Generation Answers.md](../answers/Week-07-Specialized-Components/Unique%20ID%20Generation%20Answers.md)

---
## Key Takeaways

```
╔════════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:               ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. ID choice is a PERMANENT architectural decision.          ║
║      Twitter tweet URLs, Shopify order numbers, and API        ║
║      contracts embed your ID format forever. Choose once,      ║
║      choose carefully. Migration is extremely painful.         ║
║                                                                ║
║   2. UUID v4 is coordination-free but index-hostile.           ║
║      Never use UUID v4 as PK on high-volume B-tree tables.     ║
║      Use UUID v7, Snowflake, or BIGINT instead.                ║
║                                                                ║
║   3. Snowflake/Sonyflake = coordination-free per request,      ║
║      NOT coordination-free per deployment. Worker ID           ║
║      assignment is the hidden coordination cost. Plan it.      ║
║                                                                ║
║   4. Clock drift breaks K-sortable IDs silently. Monitor       ║
║      NTP offset. Implement backward-clock tolerance.           ║
║      Test with intentional clock steps in staging.             ║
║                                                                ║
║   5. The dual-ID pattern (BIGSERIAL internal + UUID public)    ║
║      solves 80% of production ID problems: fast joins,         ║
║      opaque APIs, no volume leakage, B-tree friendly.          ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading

```
REQUIRED:
  1. RFC 9562 — UUID Version 7
     https://www.rfc-editor.org/rfc/rfc9562.html
     → Sections 5.7 (UUID v7) and 6.2 (UUID v4)
     → 15 minute read — the authoritative spec

  2. Twitter Snowflake blog post (archived)
     https://blog.twitter.com/engineering/en_us/a/2010/announcing-snowflake
     → Original Snowflake announcement with bit layout
     → 5 minute read — historical context

  3. ULID Specification
     https://github.com/ulid/spec
     → Bit layout, monotonic generation, Crockford Base32
     → 10 minute read

OPTIONAL:
  4. Meituan Leaf — Distributed ID Generator
     https://tech.meituan.com/2017/04/21/mt-leaf.html
     → Segment mode vs Snowflake mode tradeoffs
     → Production ID service at Chinese e-commerce scale

  5. Postgres Documentation: Sequences
     https://www.postgresql.org/docs/current/functions-sequence.html
     → CACHE behavior, setval, gaps — essential for sequence ops

  6. DynamoDB Best Practices: Partition Keys
     https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html
     → Hot partition section — directly applies to counter patterns

  7. "Why UUIDs Are Not the Answer" — various engineering blogs
     → Search: "uuid primary key performance postgres"
     → Empirical benchmarks on UUID v4 index fragmentation
```

---

# 🔥 SRE SCENARIO — Unique ID Generation

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1 (DATA INTEGRITY)
Service: Global payment platform — transaction service
Time: 2:47 AM UTC (Black Friday, peak load)

ARCHITECTURE:
  60 Kubernetes pods (order-api Deployment)
  Snowflake ID generator (Go, sonyflake library)
  MachineID: default (private IP & 0xFFFF)
  Postgres RDS (primary + 2 read replicas, us-east-1)
  DynamoDB (transaction audit log, us-east-1)

  Table: transactions
    id BIGINT PRIMARY KEY          ← Snowflake ID
    merchant_id BIGINT NOT NULL
    amount DECIMAL(18,2) NOT NULL
    status TEXT NOT NULL
    created_at TIMESTAMPTZ DEFAULT now()

  Peak load: 8,000 transactions/sec (normal: 800/sec)

INCIDENT TIMELINE:

  2:30 AM — Traffic ramp begins (Black Friday early access)
  2:41 AM — PagerDuty: "duplicate key violation rate > 0.1%"
  2:43 AM — Error rate climbs to 3.2% on POST /v1/transactions
  2:45 AM — Customer support: "Payment failed but money was debited"
  2:47 AM — Incident declared P1

SYMPTOMS:
  Application logs:
    ERROR: duplicate key value violates unique constraint "transactions_pkey"
    Key (id)=(1847291038472918016) already exists.

  Duplicate IDs decode to:
    timestamp: 2026-11-28 02:41:33.120 UTC
    machine_id: 48291 (0xBCB3)
    sequence: 0

  Two different transaction records, same merchant, same amount,
  SAME Snowflake ID — one succeeded, one failed with duplicate key.

  CloudWatch:
    order-api pod count: 60 (auto-scaled from 20 at 2:30 AM)
    NTP offset on 3 nodes: -2.7 seconds (chrony step in progress)
    DynamoDB audit table: ThrottledRequests = 0 (not the bottleneck)

  Postgres:
    SELECT id, COUNT(*) FROM transactions
    WHERE created_at > '2026-11-28 02:30:00'
    GROUP BY id HAVING COUNT(*) > 1;
    → 847 duplicate ID attempts in 17 minutes
    → 0 duplicate rows actually stored (PK constraint saved you)
    → But 847 FAILED transactions = 847 angry customers

  kubectl worker ID audit:
    60 pods across 12 nodes (5 pods per node)
    12 unique machine_ids (one per node, not per pod)
    12 nodes × 5 pods = 60 generators sharing 12 machine IDs
    Each machine_id: 256 IDs per 10ms window
    5 pods sharing machine_id 48291 → 5 × 256 = 1280 IDs needed per 10ms
    At 8,000 tx/sec / 60 pods = 133 tx/sec per pod
    Per machine_id group (5 pods): 665 tx/sec = 6.65 per 10ms ← seems OK?

  BUT: burst traffic + retry storm:
    Failed tx → client retry → 3x attempt rate
    665 × 3 = 1,995 IDs per 10ms needed per machine_id group
    Capacity: 256 per 10ms
    → SEQUENCE EXHAUSTION → spin-wait → timing overlap → COLLISION

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** Trace the exact failure chain from the deployment architecture to duplicate Snowflake IDs. Why did the problem only appear at 2:41 AM and not during normal traffic?

**Question 2:** What is the immediate mitigation priority order? 847 customers have failed payments during peak revenue window. Every minute costs ~$120K in GMV.

**Question 3:** The Postgres PRIMARY KEY constraint prevented duplicate rows from being stored. Is this "the system working correctly"? What is the business impact of the constraint doing its job?

**Question 4:** Design the long-term fix with defense-in-depth. What changes at the code, infrastructure, and process levels ensure this class of failure cannot recur?

---

> **Answer key (do not open until you attempt the Ops Sim / questions):**
> [`../answers/Week-07-Specialized-Components/Unique ID Generation Answers.md`](../answers/Week-07-Specialized-Components/Unique%20ID%20Generation%20Answers.md)

