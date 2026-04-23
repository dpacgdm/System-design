# Week 2, Topic 2: NoSQL Taxonomy — When to Use What

---

## Step 1: Learning Objectives

```
┌──────────────────────────────────────────────────────────────┐
│  AFTER THIS TOPIC, YOU WILL BE ABLE TO:                      │
│                                                              │
│  1. Name the four NoSQL categories and explain the           │
│     data model, access pattern, and tradeoff of each         │
│                                                              │
│  2. Given a system requirement, choose SQL vs NoSQL          │
│     AND which NoSQL type — with justified reasoning          │
│                                                              │
│  3. Explain WHY Cassandra is write-optimized and             │
│     MongoDB is document-optimized at the storage             │
│     engine level (not just "it's designed for writes")       │
│                                                              │
│  4. Identify when a team chose the WRONG database            │
│     for their workload and explain what breaks               │
│                                                              │
│  5. Design the data model differently for the same           │
│     application depending on which database you choose       │
│     (query-driven modeling vs normalized modeling)           │
│                                                              │
│  6. Explain the consistency, availability, and partition     │
│     tolerance tradeoffs of each NoSQL type                   │
│     (this sets up Week 3's CAP theorem deep dive)            │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 2: Core Teaching

### The Fundamental Shift: Why NoSQL Exists

```
SQL databases dominated for 40 years because they're 
GENERAL PURPOSE. They handle most workloads well.

NoSQL didn't emerge because SQL was "bad."
It emerged because three things changed simultaneously 
in the 2000s:

  1. DATA VOLUME exploded
     → Terabytes → Petabytes
     → Single-server SQL can't hold it all
     → SQL sharding is painful (application-level routing,
       cross-shard joins are expensive or impossible)

  2. WRITE THROUGHPUT demands exploded
     → Social media: millions of writes/sec
     → IoT: sensors streaming continuously
     → SQL's ACID overhead per write becomes a bottleneck

  3. DATA MODELS diversified
     → Not everything fits neatly into rows and columns
     → JSON documents, graph relationships, time series
     → Forcing these into SQL tables requires complex 
       JOINs and impedance mismatch with application objects

NoSQL databases make DIFFERENT TRADEOFFS than SQL:
  → They sacrifice some SQL features (joins, ACID, 
    flexible queries) to gain something specific 
    (scale, write speed, flexible schema, etc.)

THE KEY INSIGHT:
  NoSQL is not "better" than SQL.
  Each NoSQL type is OPTIMIZED for a specific 
  access pattern at the cost of everything else.
  
  Choose based on your PRIMARY access pattern.
  If you don't know your access pattern yet, 
  use PostgreSQL. Seriously.
```

### The Four Categories

```
┌─────────────────────────────────────────────────────────────┐
│                     NoSQL TAXONOMY                          │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │  KEY-VALUE   │  │   DOCUMENT   │                         │
│  │              │  │              │                         │
│  │  Redis       │  │  MongoDB     │                         │
│  │  DynamoDB    │  │  CouchDB     │                         │
│  │  Memcached   │  │  Firestore   │                         │
│  │              │  │              │                         │
│  │  "Simple,    │  │  "Flexible   │                         │
│  │   blazing    │  │   schema,    │                         │
│  │   fast"      │  │   rich       │                         │
│  │              │  │   queries"   │                         │
│  └──────────────┘  └──────────────┘                         │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │ WIDE-COLUMN  │  │    GRAPH     │                         │
│  │              │  │              │                         │
│  │  Cassandra   │  │  Neo4j       │                         │
│  │  HBase       │  │  Amazon      │                         │
│  │  ScyllaDB    │  │  Neptune     │                         │
│  │              │  │  Dgraph      │                         │
│  │  "Massive    │  │              │                         │
│  │   write      │  │  "Relation-  │                         │
│  │   scale"     │  │   ship       │                         │
│  │              │  │   traversal" │                         │
│  └──────────────┘  └──────────────┘                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### Category 1: Key-Value Stores

```
DATA MODEL:
  The simplest possible model. It's a hash map.
  
  KEY (string) → VALUE (blob/string/any)
  
  "user:1234"        → "{name: 'Alice', age: 30}"
  "session:abc-def"  → "{userId: 1234, expiry: ...}"
  "cart:1234"        → "{items: [{id: 42, qty: 2}]}"

  The database treats the VALUE as OPAQUE.
  It doesn't know or care what's inside.
  You can't query BY value contents.
  You can ONLY retrieve by exact key.

ACCESS PATTERNS:
  ✅ GET by exact key         → O(1)
  ✅ SET key to value          → O(1)
  ✅ DELETE by key             → O(1)
  ✅ TTL-based expiration      → automatic
  ❌ Query by value fields     → impossible
  ❌ Range queries             → mostly impossible*
  ❌ JOINs                     → impossible
  ❌ Aggregations              → impossible

  * DynamoDB supports range queries on sort key within 
    a partition key. Redis supports sorted sets. These 
    are extensions beyond pure key-value.

WHEN TO USE:
  → Caching (most common use case)
  → Session storage
  → Shopping carts
  → Rate limiting counters
  → Feature flags
  → Any "lookup by ID" pattern where you don't need 
    to query the data in complex ways
```

#### Redis Deep Dive

```
Redis is the most widely used key-value store.
But calling it "just key-value" undersells it.

REDIS DATA STRUCTURES:
  ┌───────────────────────────────────────────────┐
  │  Strings   → Simple K/V, counters, bitmaps    │
  │  Lists     → Queues, recent items, timelines  │
  │  Sets      → Unique collections, intersections│
  │  Sorted    → Leaderboards, priority queues,   │
  │   Sets       range queries by score           │
  │  Hashes    → Object fields (like a mini-row)  │
  │  Streams   → Event log, like a mini-Kafka     │
  │  HyperLog  → Cardinality estimation           │
  │   Log        (count unique visitors)          │
  │  Geo        → Geospatial queries              │
  └───────────────────────────────────────────────┘

REDIS ARCHITECTURE:
  
  ┌──────────────────────────────────────────────┐
  │  SINGLE-THREADED EVENT LOOP                  │
  │                                              │
  │  All operations are processed sequentially   │
  │  by ONE thread. This means:                  │
  │                                              │
  │  ✅ No locks needed (no concurrency)         │
  │  ✅ Every operation is atomic                │
  │  ✅ Extremely predictable latency            │
  │  ❌ Can't use multiple CPU cores             │
  │     (for command processing)                 │
  │  ❌ One slow command blocks everything       │
  │     (KEYS *, FLUSHALL, large SORT)           │
  │                                              │
  │  Network I/O is multiplexed (epoll/kqueue).  │
  │  Redis 6+ uses I/O threads for network       │
  │  read/write, but command execution is still  │
  │  single-threaded.                            │
  └──────────────────────────────────────────────┘

  Performance:
  → 100,000-500,000 operations/second on a single node
  → Sub-millisecond latency (typically <1ms)
  → All data in MEMORY (this is why it's fast)

REDIS PERSISTENCE (how it survives restarts):

  Option 1: RDB Snapshots
    → Periodic full dump of memory to disk
    → fork() a child process → child writes snapshot
    → Fast recovery (load entire snapshot)
    → DATA LOSS: everything since last snapshot
    → Configured: save 60 10000 
      (snapshot every 60s if 10000+ writes)

  Option 2: AOF (Append-Only File)
    → Every write command appended to a log file
    → On restart: replay all commands
    → Less data loss (configurable: every write, 
      every second, or OS-controlled)
    → Slower recovery (replay millions of commands)
    → File grows large → needs periodic rewrite/compaction

  Option 3: RDB + AOF (recommended for production)
    → AOF for durability (minimal data loss)
    → RDB for fast restarts (load snapshot, then 
      replay AOF entries since snapshot)

  ┌──────────────────────────────────────────────┐
  │  IMPORTANT PRODUCTION GOTCHA:                │
  │                                              │
  │  Redis fork() for RDB snapshots copies the   │
  │  entire memory space (copy-on-write).        │
  │                                              │
  │  If Redis uses 30GB RAM and you have heavy   │
  │  writes during snapshot:                     │
  │  → Copy-on-write triggers on every modified  │
  │    page                                      │
  │  → Memory usage can temporarily DOUBLE       │
  │  → 30GB Redis might need 60GB of available   │
  │    RAM during snapshot                       │
  │  → If the server runs out: OOM killer.       │
  │                                              │
  │  ALWAYS provision 2x the Redis data size     │
  │  in available memory. Always.                │
  └──────────────────────────────────────────────┘

REDIS SCALING:

  Single node: Up to ~25GB practical (memory limit)
  
  Redis Cluster:
  → Automatic sharding across multiple nodes
  → 16,384 hash slots distributed across nodes
  → Key → CRC16(key) mod 16384 → slot → node
  → No cross-slot operations for multi-key commands
    (MGET across different slots fails)
  
  ┌─────────┐  ┌─────────┐  ┌─────────┐
  │ Node A  │  │ Node B  │  │ Node C  │
  │ Slots   │  │ Slots   │  │ Slots   │
  │ 0-5460  │  │ 5461-   │  │ 10923-  │
  │         │  │ 10922   │  │ 16383   │
  │ +Replica│  │ +Replica│  │ +Replica│
  └─────────┘  └─────────┘  └─────────┘
  
  Each master has one or more replicas for failover.
  If a master dies → replica promoted automatically.
```

#### DynamoDB

```
DynamoDB is AWS's managed key-value / document hybrid.

KEY DIFFERENCE FROM REDIS:
  → Persistent by default (not in-memory)
  → Automatically distributed across partitions
  → Pay-per-request or provisioned capacity
  → Designed for web-scale operational workloads

DATA MODEL:
  ┌──────────────────────────────────────────────┐
  │  Table: Orders                               │
  │                                              │
  │  Partition Key: user_id    (REQUIRED)        │
  │  Sort Key:      order_id   (OPTIONAL)        │
  │                                              │
  │  user_id=123, order_id=001 → {item: "book"}  │
  │  user_id=123, order_id=002 → {item: "pen"}   │
  │  user_id=456, order_id=001 → {item: "desk"}  │
  │                                              │
  │  Access patterns:                            │
  │  ✅ Get exact item: PK=123, SK=001           │
  │  ✅ Get all orders for user: PK=123          │
  │  ✅ Get user's recent orders: PK=123,        │
  │     SK > "2024-01-01"                        │
  │  ❌ Get all orders for item "book"           │
  │     (requires scan or GSI)                   │
  └──────────────────────────────────────────────┘

  GSI (Global Secondary Index):
    → Creates a NEW copy of the data with a different 
      partition key / sort key
    → Enables different access patterns
    → Eventually consistent (not strongly consistent)
    → Costs additional write capacity (every write to 
      the table also writes to each GSI)

DYNAMO'S KEY DESIGN PRINCIPLE:
  → You model your data based on your ACCESS PATTERNS
  → NOT based on entities and relationships
  → You might denormalize aggressively
  → You might duplicate data across multiple GSIs
  → This is the OPPOSITE of SQL normalization
  
  Example: In SQL, you'd have separate tables for 
  users, orders, and items with JOINs.
  In DynamoDB, you might store everything about 
  an order (user info, item info, payment info) 
  in ONE item to avoid "joins" (which don't exist).

WHEN TO USE:
  → Known, finite access patterns that you can design for
  → Need automatic scaling to massive throughput
  → AWS-native infrastructure
  → Don't need complex queries, JOINs, or aggregations
  → Serverless applications (pairs well with Lambda)
```

---

### Category 2: Document Stores

```
DATA MODEL:
  KEY → STRUCTURED DOCUMENT (JSON/BSON)
  
  Unlike key-value, the database UNDERSTANDS the 
  document structure. You can query, index, and 
  filter on ANY field within the document.

  {
    "_id": "order_12345",
    "user": {
      "id": 123,
      "name": "Alice",
      "email": "alice@example.com"
    },
    "items": [
      {"product_id": 42, "name": "Book", "qty": 2, "price": 15.99},
      {"product_id": 99, "name": "Pen", "qty": 5, "price": 1.99}
    ],
    "total": 41.93,
    "status": "shipped",
    "created_at": "2024-01-15T10:30:00Z"
  }

KEY DIFFERENCE FROM KEY-VALUE:
  Key-Value:  GET("order_12345") → entire blob
  Document:   db.orders.find({"user.id": 123, status: "shipped"})
              → query INSIDE the document structure

ACCESS PATTERNS:
  ✅ Get by ID                              → O(1)
  ✅ Query by any field                     → uses indexes
  ✅ Query nested fields                    → "user.name"
  ✅ Query array elements                   → "items.product_id"
  ✅ Aggregation pipeline                   → GROUP BY equivalent
  ✅ Text search                            → built-in
  ✅ Flexible schema (add fields anytime)   → no ALTER TABLE
  ❌ JOINs across collections              → limited ($lookup)
  ❌ Multi-document ACID transactions      → added in v4.0+
     (but expensive — design to avoid them)
```

#### MongoDB Deep Dive

```
MongoDB is the dominant document store.

STORAGE ENGINE: WiredTiger (since MongoDB 3.2)

  ┌──────────────────────────────────────────────┐
  │  WiredTiger internals:                       │
  │                                              │
  │  → B-tree for indexes (like PostgreSQL)      │
  │  → Document-level locking (not collection)   │
  │  → Compression: snappy (fast) or zlib (small)│
  │  → MVCC for read isolation                   │
  │  → Journal (WAL equivalent) for durability   │
  │                                              │
  │  Write path:                                 │
  │  Write → Journal (WAL) → In-memory cache     │
  │  → Checkpoint to disk every 60s              │
  │                                              │
  │  Read path:                                  │
  │  Query → Check in-memory cache → Disk if miss│
  └──────────────────────────────────────────────┘

MONGODB SHARDING:

  ┌───────────┐
  │  mongos   │ ← Router (doesn't store data)
  │  (router) │   Application connects here
  └────┬──────┘
       │ Routes queries to correct shard
       │
  ┌────┴──────────────────────────────────┐
  │                                       │
  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │ Shard 1  │  │ Shard 2  │  │ Shard 3  │
  │(replica  │  │(replica  │  │(replica  │
  │  set)    │  │  set)    │  │  set)    │
  └──────────┘  └──────────┘  └──────────┘
  
  Each shard is a REPLICA SET (primary + secondaries).
  Sharding is by a SHARD KEY (chosen by you).
  
  Config servers store metadata: which shard has 
  which range of shard key values.

SHARD KEY SELECTION IS CRITICAL:

  ❌ BAD shard key: created_at (timestamp)
    → All new writes go to ONE shard (the latest range)
    → "Hot shard" problem — one shard overwhelmed, 
      others idle
    → Same problem as auto-increment IDs

  ❌ BAD shard key: status (low cardinality)
    → Only a few values: "pending", "shipped", "delivered"
    → All "pending" orders on one shard
    → "Jumbo chunks" that can't be split further

  ✅ GOOD shard key: user_id (hashed)
    → Evenly distributed across shards
    → Each user's data on one shard (locality)
    → Range queries on user_id don't work well (hashed)
    → BUT point lookups by user_id are efficient

  ✅ GOOD shard key: compound {user_id, created_at}
    → User's data mostly on same shard (locality)
    → Range queries within a user work (sorted by date)
    → Good distribution across users

THE MONGODB TRAP:
  
  MongoDB is EASY to start with:
  → No schema definition needed
  → Just insert JSON documents
  → Feels like "no rules" development
  
  This leads to:
  → Documents growing unboundedly (arrays with 1M elements)
  → No consistency in field names across documents
  → Queries that scan entire collections (no indexes)
  → "Everything in one collection" anti-pattern
  
  MongoDB requires DISCIPLINE:
  → Define schema in application code (Mongoose, etc.)
  → Create indexes for your query patterns
  → Set document size limits (16MB hard limit exists)
  → Plan your data model BEFORE writing code
  → Think about shard key BEFORE you have too much data
    (changing shard key later requires full data migration)
```

#### Document vs SQL — The Modeling Difference

```
SCENARIO: E-commerce with users, orders, and products.

SQL APPROACH (normalized):
  
  ┌──────────┐     ┌──────────────┐     ┌──────────┐
  │  users   │     │   orders     │     │ products │
  ├──────────┤     ├──────────────┤     ├──────────┤
  │ id       │◄────│ user_id (FK) │     │ id       │
  │ name     │     │ id           │     │ name     │
  │ email    │     │ total        │     │ price    │
  └──────────┘     │ status       │     └────┬─────┘
                   └──────┬───────┘          │
                          │                  │
                   ┌──────┴───────┐          │
                   │ order_items  │          │
                   ├──────────────┤          │
                   │ order_id (FK)│──────────┘
                   │ product_id   │(FK)
                   │ quantity     │
                   │ price        │
                   └──────────────┘
  
  To get "Alice's orders with items":
    SELECT o.*, oi.*, p.name 
    FROM orders o
    JOIN order_items oi ON o.id = oi.order_id
    JOIN products p ON oi.product_id = p.id
    WHERE o.user_id = 123;
  
  → 3-table JOIN. Clean. No duplicated data.
  → Product price changes? Update ONE row in products.

DOCUMENT APPROACH (denormalized):

  // One document = one complete order
  {
    "_id": "order_789",
    "user": {"id": 123, "name": "Alice"},  // embedded, duplicated
    "items": [
      {
        "product_id": 42,
        "name": "Book",          // duplicated from products
        "price_at_purchase": 15.99, // snapshot, not reference
        "quantity": 2
      }
    ],
    "total": 31.98,
    "status": "shipped"
  }

  To get "Alice's orders with items":
    db.orders.find({"user.id": 123})
  
  → ONE query. No joins. Everything in the document.
  → Product price changes? Doesn't affect existing orders
    (we stored price_at_purchase, not a reference).
  → But: if Alice changes her name, you'd need to update 
    it across ALL her order documents (denormalization cost).

WHEN DOCUMENT MODEL WINS:
  → Data is naturally hierarchical (order → items)
  → You almost always read the ENTIRE aggregate together
  → Relationships are ONE-TO-FEW (order has 1-20 items)
  → Schema changes frequently (startup, evolving product)
  → Read performance matters more than write consistency

WHEN SQL MODEL WINS:
  → Many-to-many relationships (users ↔ roles ↔ permissions)
  → Data referenced from many places (product shown in 
    orders, carts, wishlists, recommendations)
  → Transactions span multiple entities
  → Need ad-hoc queries you haven't predicted
  → Data integrity is critical (financial, healthcare)
```

---

### Category 3: Wide-Column Stores

```
DATA MODEL:
  This is the most confusing category name.
  "Wide-column" does NOT mean "SQL table with many columns."

  Think of it as: a two-level map.
  
  Row Key → { Column Family → { Column Name: Value } }

  It's like a nested hash map where:
  → Row key identifies the row (like a primary key)
  → Each row can have DIFFERENT columns (sparse)
  → Columns are grouped into Column Families

VISUAL:

  ┌──────────────────────────────────────────────────┐
  │  Row Key: "user:alice"                           │
  │  ┌──────────────────────┬────────────────────┐   │
  │  │ Column Family:       │ Column Family:     │   │
  │  │ "profile"            │ "activity"         │   │
  │  ├──────────────────────┼────────────────────┤   │
  │  │ name: "Alice"        │ login:2024-01-15   │   │
  │  │ email: "a@b.com"     │ login:2024-01-14   │   │
  │  │ age: 30              │ post:2024-01-13    │   │
  │  │                      │ post:2024-01-10    │   │
  │  └──────────────────────┴────────────────────┘   │
  ├──────────────────────────────────────────────────┤
  │  Row Key: "user:bob"                             │
  │  ┌──────────────────────┬────────────────────┐   │
  │  │ Column Family:       │ Column Family:     │   │
  │  │ "profile"            │ "activity"         │   │
  │  ├──────────────────────┼────────────────────┤   │
  │  │ name: "Bob"          │ login:2024-01-15   │   │
  │  │ phone: "555-1234"    │                    │   │
  │  │ (no email or age!)   │ (only one login!)  │   │
  │  └──────────────────────┴────────────────────┘   │
  └──────────────────────────────────────────────────┘

  Notice:
  → Alice has email+age. Bob has phone. DIFFERENT columns.
  → Each row is sparse — no NULLs, just absent columns.
  → Columns within a family are stored together on disk.
  → Column families must be declared upfront.
  → Individual columns within a family are dynamic.
```

#### Cassandra Deep Dive

```
Cassandra is the most widely deployed wide-column store.
Used by Netflix, Apple, Instagram, Discord.

WHY CASSANDRA EXISTS:
  → Designed for MASSIVE WRITE throughput
  → Designed for MULTI-DATACENTER replication
  → Designed for HIGH AVAILABILITY (no single point of failure)
  → Sacrifices: read flexibility, consistency, ad-hoc queries

ARCHITECTURE — NO MASTER NODE:

  ┌──────────────────────────────────────────────────┐
  │                                                  │
  │         ┌─────┐                                  │
  │    ┌────│Node1│────┐                             │
  │    │    └─────┘    │                             │
  │ ┌─────┐         ┌─────┐                          │
  │ │Node6│         │Node2│                          │
  │ └─────┘         └─────┘                          │
  │    │               │     THE RING                │
  │ ┌─────┐         ┌─────┐                          │
  │ │Node5│         │Node3│  Every node is EQUAL.    │
  │ └─────┘         └─────┘  No master. No leader.   │
  │    │    ┌─────┐    │     Any node can serve      │
  │    └────│Node4│────┘     any request.            │
  │         └─────┘                                  │
  │                                                  │
  │  Data distributed via CONSISTENT HASHING:        │
  │  → hash(partition_key) → position on ring        │
  │  → Data stored on N consecutive nodes            │
  │    (N = replication factor, typically 3)         │
  │                                                  │
  └──────────────────────────────────────────────────┘

  No master = no single point of failure.
  Any node goes down? Others serve the request.
  This is why Cassandra targets AVAILABILITY.

CASSANDRA WRITE PATH (why writes are fast):

  ┌───────────────────────────────────────────────────┐
  │                                                   │
  │  Client Write Request                             │
  │       │                                           │
  │       ▼                                           │
  │  ┌──────────────┐                                 │
  │  │ Commit Log   │  1. Append to commit log        │
  │  │ (on disk,    │     (sequential write, FAST)    │
  │  │  append-only)│     This is the durability      │
  │  └──────┬───────┘     guarantee.                  │
  │         │                                         │
  │         ▼                                         │
  │  ┌──────────────┐  2. Write to Memtable           │
  │  │  Memtable    │     (in-memory sorted structure)│
  │  │  (in memory) │     This is fast — just memory. │
  │  └──────┬───────┘                                 │
  │         │                                         │
  │         │  3. Return "write successful" to client │
  │         │     ← DONE. This is why writes are      │
  │         │       sub-millisecond.                  │
  │         │                                         │
  │         ▼  (later, asynchronously)                │
  │  ┌──────────────┐  4. When Memtable is full,      │
  │  │   SSTable    │     flush to SSTable on disk.   │
  │  │ (on disk,    │     SSTable = Sorted String     │
  │  │  immutable)  │     Table. Immutable once       │
  │  └──────────────┘     written. Never modified.    │
  │                                                   │
  │  5. Compaction (background):                      │
  │     Merge multiple SSTables into fewer, larger    │
  │     SSTables. Remove tombstones (deleted data).   │
  │     Reclaim disk space.                           │
  │                                                   │
  └───────────────────────────────────────────────────┘

WHY THIS IS FAST:
  → Commit log: SEQUENTIAL write (fastest disk I/O pattern)
  → Memtable: MEMORY write (fastest possible)
  → No read-before-write (unlike B-tree UPDATE which 
    must find the row first, then modify)
  → No locking (each write is independent)
  → Compaction happens in background (doesn't block writes)

COMPARE TO POSTGRESQL WRITE:
  PostgreSQL UPDATE:
    1. Find row via index (random I/O read)
    2. Check constraints
    3. Acquire row lock
    4. Write WAL (sequential)
    5. Modify heap page (random I/O write)
    6. Update all indexes (random I/O writes)
    7. Release lock
    → Multiple random I/O operations + locking

  Cassandra INSERT:
    1. Append to commit log (sequential)
    2. Write to memtable (memory)
    → Done. Two operations. No random I/O. No locks.

  This is why Cassandra can handle 10-100x more writes/sec 
  than PostgreSQL on equivalent hardware.

CASSANDRA READ PATH (why reads are slower):

  ┌─────────────────────────────────────────────────┐
  │  Client Read Request                            │
  │       │                                         │
  │       ▼                                         │
  │  Check Memtable (in memory)                     │
  │       │ Not found or partial?                   │
  │       ▼                                         │
  │  Check Bloom Filter for each SSTable            │
  │  (probabilistic: "definitely not here" or       │
  │   "probably here")                              │
  │       │ Bloom filter says "probably here"?      │
  │       ▼                                         │
  │  Read SSTable index → find data block           │
  │       │                                         │
  │       ▼                                         │
  │  Read data block from disk                      │
  │       │                                         │
  │       ▼                                         │
  │  Merge results from multiple SSTables           │
  │  (latest timestamp wins)                        │
  │       │                                         │
  │       ▼                                         │
  │  Return to client                               │
  └─────────────────────────────────────────────────┘

  Reads may need to check MULTIPLE SSTables 
  (data for one row might be spread across SSTables 
  written at different times).
  
  This is why reads are slower than writes in Cassandra.
  Compaction helps by merging SSTables, but it's a 
  constant background trade-off.

TUNABLE CONSISTENCY:

  Cassandra lets you choose consistency PER QUERY.
  With replication factor = 3 (data on 3 nodes):

  ┌──────────────────────────────────────────────────┐
  │  Write Consistency:                              │
  │  ONE     → Write to 1 node, return success       │
  │            (fastest, least durable)              │
  │  QUORUM  → Write to 2/3 nodes, return success    │
  │            (balanced)                            │
  │  ALL     → Write to 3/3 nodes, return success    │
  │            (slowest, most durable)               │
  │                                                  │
  │  Read Consistency:                               │
  │  ONE     → Read from 1 node                      │
  │            (fastest, might be stale)             │
  │  QUORUM  → Read from 2/3 nodes, return latest    │
  │            (balanced)                            │
  │  ALL     → Read from 3/3 nodes                   │
  │            (slowest, guaranteed latest)          │
  │                                                  │
  │  STRONG CONSISTENCY FORMULA:                     │
  │  R + W > N  (where N = replication factor)       │
  │                                                  │
  │  If R=QUORUM(2) + W=QUORUM(2) > N(3):            │
  │    → At least 1 node overlaps between read set   │
  │      and write set                               │
  │    → That node has the latest data               │
  │    → Read is guaranteed to see latest write      │
  │    → This is how you get "strong consistency"    │
  │      in an eventually consistent system          │
  │                                                  │
  │  If R=ONE(1) + W=ONE(1) = 2 < N(3):              │
  │    → No guaranteed overlap                       │
  │    → You might read stale data                   │
  │    → Eventually consistent                       │
  └──────────────────────────────────────────────────┘

CASSANDRA DATA MODELING:

  THE #1 RULE: Model your tables around your QUERIES.
  Not around your entities.

  In SQL, you start with entities:
    "I have users, orders, and products"
    → Normalize → 3 tables with foreign keys
    → Query however you want with JOINs

  In Cassandra, you start with queries:
    "I need to get a user's recent orders"
    "I need to get all orders for a product"
    "I need to get an order by ID"
    → Each query might be its OWN table
    → Yes, you duplicate data across tables
    → This is intentional, not a mistake

  Example:
  
  Query 1: Get user's orders → 
    CREATE TABLE orders_by_user (
      user_id UUID,
      order_date TIMESTAMP,
      order_id UUID,
      total DECIMAL,
      PRIMARY KEY (user_id, order_date)
    ) WITH CLUSTERING ORDER BY (order_date DESC);
  
  Query 2: Get order details →
    CREATE TABLE orders_by_id (
      order_id UUID PRIMARY KEY,
      user_id UUID,
      items LIST<FROZEN<item_type>>,
      total DECIMAL,
      status TEXT
    );

  SAME data, TWO tables, optimized for DIFFERENT queries.
  When you write an order, you write to BOTH tables.
  Consistency between tables is YOUR responsibility.

ANTI-PATTERNS (things that break Cassandra):

  ❌ SELECT * FROM orders; 
     (full table scan — Cassandra doesn't do this well)
  
  ❌ Secondary indexes on high-cardinality columns
     (creates a distributed index that must query ALL nodes)
  
  ❌ Large partitions (>100MB)
     (single partition key with millions of rows — causes 
      hot nodes and read timeouts)
  
  ❌ Frequent deletes 
     (creates tombstones that slow down reads until 
      compaction clears them — "tombstone storm")
  
  ❌ Using Cassandra for data you need to JOIN or aggregate
     (it's not a relational database — stop trying)
```

---

### Category 4: Graph Databases

```
DATA MODEL:
  Everything is NODES and EDGES (relationships).

  ┌──────┐    ──FRIENDS──►    ┌──────┐
  │Alice │                    │ Bob  │
  └──┬───┘                    └──┬───┘
     │                           │
     │──PURCHASED──►┌──────┐    │
     │              │Book A│◄───┘──REVIEWED
     │              └──────┘
     │
     │──LIVES_IN──►┌──────────┐
                   │  NYC     │◄──LIVES_IN──┌──────┐
                   └──────────┘             │Carol │
                                            └──────┘

  NODES: Alice, Bob, Carol, Book A, NYC
  EDGES: FRIENDS, PURCHASED, REVIEWED, LIVES_IN
  Each node and edge can have PROPERTIES (key-value pairs)

WHY GRAPH DATABASES EXIST:

  SQL CAN model relationships. But it's expensive for 
  DEEP or VARIABLE-DEPTH traversals.

  "Find friends of friends of Alice who also bought Book A"

  SQL approach:
    SELECT DISTINCT u3.name
    FROM friendships f1
    JOIN friendships f2 ON f1.friend_id = f2.user_id
    JOIN purchases p ON f2.friend_id = p.user_id
    WHERE f1.user_id = 'alice'
    AND p.product_id = 'book_a';
    
    → 3-way JOIN. Gets worse at depth 3, 4, 5...
    → At depth 6: 6 JOINs, query planner gives up
    → Performance degrades EXPONENTIALLY with depth

  Graph approach (Cypher — Neo4j query language):
    MATCH (alice:User {name: "Alice"})
          -[:FRIENDS*1..3]->(fof)
          -[:PURCHASED]->(book:Product {name: "Book A"})
    RETURN DISTINCT fof.name

    → Reads naturally: "Start at Alice, traverse up to 
      3 friendship hops, find anyone who purchased Book A"
    → Performance is proportional to the LOCAL 
      subgraph traversed, NOT the total database size
    → This is called "index-free adjacency" — each node 
      directly points to its neighbors in memory

INDEX-FREE ADJACENCY:

  In SQL (with JOIN):
    To find Alice's friends:
    1. Look up Alice in users table (index lookup)
    2. Scan friendships table for user_id = alice (index lookup)
    3. For each friend_id, look up users table (index lookup)
    → Each step is an index lookup — O(log n)
    → Depth 3 traversal: O(k³ × log n) where k = avg friends

  In Graph DB:
    To find Alice's friends:
    1. Go to Alice's node in memory
    2. Follow FRIENDS pointers directly to neighbor nodes
    → Each hop is a POINTER DEREFERENCE — O(1)
    → Depth 3 traversal: O(k³) — no log n factor
    → For small k (avg friends = 100), this is massively 
      faster at depth > 2

ACCESS PATTERNS:
  ✅ Traverse relationships (any depth)     → O(k^d)
  ✅ Shortest path between nodes            → BFS/Dijkstra
  ✅ Pattern matching (find subgraphs)      → native
  ✅ Recommendation (friends who also...)   → efficient
  ✅ Fraud detection (circular transactions)→ cycle detection
  ❌ Bulk aggregations                      → slow
  ❌ Full-table scans                       → very slow
  ❌ Simple key-value lookups               → overkill
  ❌ High write throughput                  → not optimized

WHEN TO USE:
  → Social networks (friends, followers, connections)
  → Fraud detection (suspicious transaction patterns)
  → Recommendation engines (people who liked X also...)
  → Knowledge graphs (entity relationships)
  → Network topology (servers, routers, dependencies)
  → Access control (user → role → permission → resource)

WHEN NOT TO USE:
  → Simple CRUD applications (overkill)
  → High write throughput (not optimized)
  → Data without meaningful relationships
  → Aggregations (SUM, COUNT, AVG over all rows)
  → Time series data
```

---

### The Decision Framework

```
┌──────────────────────────────────────────────────────────────┐
│              WHICH DATABASE DO I USE?                        │
│                                                              │
│  START HERE: Do you have complex relationships               │
│  between entities that need deep traversal?                  │
│      │                                                       │
│      ├── YES → GRAPH DATABASE (Neo4j)                        │
│      │         Only if traversal depth > 2 is common         │
│      │                                                       │
│      └── NO → Continue...                                    │
│                                                              │
│  Do you need ACID transactions across multiple entities?     │
│      │                                                       │
│      ├── YES → SQL (PostgreSQL)                              │
│      │         Financial, inventory, user accounts           │
│      │                                                       │
│      └── NO → Continue...                                    │
│                                                              │
│  What is your PRIMARY access pattern?                        │
│      │                                                       │
│      ├── Simple GET/SET by key                               │
│      │   → KEY-VALUE (Redis for cache, DynamoDB for durable) │
│      │                                                       │
│      ├── Read whole objects, flexible schema                 │
│      │   → DOCUMENT (MongoDB)                                │
│      │                                                       │
│      ├── Massive write throughput, time-series-like          │
│      │   → WIDE-COLUMN (Cassandra)                           │
│      │                                                       │
│      └── Ad-hoc queries, complex joins, reports              │
│          → SQL (PostgreSQL)                                  │
│                                                              │
│  STILL NOT SURE?                                             │
│  → Use PostgreSQL. Seriously.                                │
│  → It handles 80% of workloads well.                         │
│  → JSONB column gives you document-store-like flexibility.   │
│  → It's the safest default until you KNOW you need           │
│    something specialized.                                    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

```
THE "USE CASE → DATABASE" CHEAT SHEET:

┌────────────────────────┬──────────────────┬──────────────────┐
│ USE CASE               │ BEST FIT         │ WHY              │
├────────────────────────┼──────────────────┼──────────────────┤
│ User accounts, billing │ PostgreSQL       │ ACID, relations  │
│ Inventory management   │ PostgreSQL       │ ACID, constraints│
│ Financial transactions │ PostgreSQL       │ ACID, auditing   │
│ Content management     │ MongoDB          │ Flexible schema  │
│ Product catalog        │ MongoDB / PG     │ Varies by needs  │
│ Session storage        │ Redis            │ Fast, TTL-based  │
│ Caching layer          │ Redis            │ Sub-ms latency   │
│ Rate limiting          │ Redis            │ Atomic counters  │
│ IoT sensor data        │ Cassandra        │ Write throughput │
│ Time series metrics    │ Cassandra / TS*  │ Append-heavy     │
│ Chat messages          │ Cassandra        │ Write-heavy, geo │
│ Social graph           │ Neo4j            │ Traversal depth  │
│ Fraud detection        │ Neo4j            │ Pattern matching │
│ Recommendation engine  │ Neo4j + Redis    │ Graph + cache    │
│ Search / full-text     │ Elasticsearch**  │ Inverted index   │
│ Leaderboards           │ Redis sorted set │ Sorted, fast     │
│ Shopping cart           │ Redis / DynamoDB │ Fast, ephemeral │
│ Message queue          │ Kafka***         │ Not a DB         │
│ Analytics / OLAP       │ ClickHouse****   │ Columnar         │
├────────────────────────┴──────────────────┴──────────────────┤
│ * TimescaleDB (PostgreSQL extension) for time series         │
│ ** Elasticsearch isn't strictly NoSQL but fits here          │
│ *** Kafka is a log, not a database, but often compared       │
│ **** ClickHouse / BigQuery / Redshift for analytics          │
└──────────────────────────────────────────────────────────────┘

MOST REAL SYSTEMS USE MULTIPLE DATABASES:

  Example: E-commerce platform
  ┌──────────────────────────────────────────────┐
  │                                              │
  │  PostgreSQL → Users, Orders, Payments        │
  │  MongoDB    → Product catalog, reviews       │
  │  Redis      → Sessions, cache, cart          │
  │  Elasticsearch → Product search              │
  │  Cassandra  → Event tracking, click stream   │
  │                                              │
  │  This is called POLYGLOT PERSISTENCE.        │
  │  Each database handles what it's best at.    │
  │  The application layer orchestrates.         │
  └──────────────────────────────────────────────┘
```

---

## Step 3: Production Patterns & Failure Modes

```
┌──────────────────────────────────────────────────────────────┐
│  FAILURE MODE #1: WRONG DATABASE CHOICE                      │
│                                                              │
│  Scenario: Team uses MongoDB for a financial ledger.         │
│                                                              │
│  What breaks:                                                │
│  → Multi-document transactions are slow and limited          │
│  → No enforced foreign keys → orphaned records               │
│  → Flexible schema → inconsistent data sneaks in             │
│  → "Transfer $500 from A to B" requires multi-doc txn        │
│    across accounts collection → performance tanks            │
│  → Auditors ask for constraint guarantees → can't provide    │
│                                                              │
│  Should have used: PostgreSQL                                │
│  The team chose MongoDB because "it's modern" and            │
│  "schema flexibility." Neither matters for a ledger.         │
│                                                              │
│  LESSON: Choose database based on ACCESS PATTERN and         │
│  CONSISTENCY REQUIREMENTS, never based on "what's trendy."   │
├──────────────────────────────────────────────────────────────┤
│  FAILURE MODE #2: CASSANDRA TOMBSTONE STORM                  │
│                                                              │
│  Scenario: Team stores user sessions in Cassandra with TTL.  │
│  Sessions expire after 30 minutes (TTL = 1800).              │
│  System handles 500K sessions/day.                           │
│                                                              │
│  What breaks:                                                │
│  → Each TTL expiration creates a TOMBSTONE marker            │
│  → Tombstones are NOT immediately removed from disk          │
│  → They persist until compaction runs (gc_grace_seconds,     │
│    default 10 days)                                          │
│  → After a week: millions of tombstones accumulated          │
│  → Reads must scan through tombstones to find live data      │
│  → Read latency goes from 5ms → 800ms → timeouts             │
│  → "Tombstone threshold exceeded" warnings in logs           │
│                                                              │
│  Fix:                                                        │
│  → Reduce gc_grace_seconds for this table                    │
│    (from 10 days to 4 hours — but understand the             │
│     consistency implications: if a node was down for         │
│     >4 hours, it might miss the delete and resurrect         │
│     the data when it comes back)                             │
│  → Run manual compaction: nodetool compact keyspace table    │
│  → Consider: is Cassandra the right choice for sessions?     │
│    Redis with native TTL might be better.                    │
│                                                              │
│  LESSON: Cassandra is write-optimized. Deletes are           │
│  "writes" (tombstone markers). Heavy delete workloads        │
│  degrade read performance over time.                         │
├──────────────────────────────────────────────────────────────┤
│  FAILURE MODE #3: REDIS OOM DURING PEAK                      │
│                                                              │
│  Scenario: Redis used for session cache. 8GB instance.       │
│  Black Friday traffic. Sessions piling up.                   │
│                                                              │
│  What breaks:                                                │
│  → maxmemory = 8GB, but no eviction policy configured        │
│  → Default: maxmemory-policy = noeviction                    │
│  → Redis is full → all SET commands return OOM error         │
│  → New users can't create sessions → can't log in            │
│  → Existing sessions work (GET still succeeds)               │
│  → But no new sessions = site effectively down for           │
│    new visitors                                              │
│                                                              │
│  Fix (immediate):                                            │
│  redis-cli CONFIG SET maxmemory-policy allkeys-lru           │
│  (evict least recently used keys when memory is full)        │
│                                                              │
│  Fix (proper):                                               │
│  → Always set an eviction policy in production               │
│  → For sessions: volatile-ttl (evict keys with               │
│    nearest expiration first)                                 │
│  → For cache: allkeys-lru (evict least recently used)        │
│  → Monitor: redis-cli INFO memory → used_memory_peak         │
│  → Alert at 80% of maxmemory                                 │
│                                                              │
│  EVICTION POLICIES:                                          │
│  noeviction    → return error when full (BAD for cache)      │
│  allkeys-lru   → evict ANY key by LRU (good for cache)       │
│  volatile-lru  → evict only keys WITH TTL by LRU             │
│  allkeys-random→ evict random key (simple but wasteful)      │
│  volatile-ttl  → evict keys nearest to expiration            │
│  allkeys-lfu   → evict least FREQUENTLY used (Redis 4.0+)    │
│                                                              │
│  LESSON: Redis without an eviction policy is a ticking       │
│  time bomb. Configure it BEFORE you need it.                 │
├──────────────────────────────────────────────────────────────┤
│  FAILURE MODE #4: MONGODB UNBOUNDED ARRAY GROWTH             │
│                                                              │
│  Scenario: Chat application stores messages as an array      │
│  inside a conversation document.                             │
│                                                              │
│  {                                                           │
│    "_id": "conv_123",                                        │
│    "participants": ["alice", "bob"],                         │
│    "messages": [                                             │
│      {"from": "alice", "text": "hi", "ts": "..."},           │
│      {"from": "bob", "text": "hello", "ts": "..."},          │
│      ... 500,000 more messages ...                           │
│    ]                                                         │
│  }                                                           │
│                                                              │
│  What breaks:                                                │
│  → MongoDB document max size: 16MB                           │
│  → 500K messages exceed 16MB → writes FAIL                   │
│  → Even before 16MB: reading the entire document to          │
│    show "last 20 messages" loads the full array into         │
│    memory → slow, wasteful                                   │
│  → $push to append creates write amplification               │
│    (document might relocate on disk if it grows beyond       │
│    its allocated space)                                      │
│                                                              │
│  Fix:                                                        │
│  → BUCKET PATTERN: Store messages in time-based buckets      │
│    {                                                         │
│      "_id": "conv_123_2024-01-15",                           │
│      "messages": [ ... max 200 messages ... ],               │
│      "count": 187                                            │
│    }                                                         │
│  → Or: ONE DOCUMENT PER MESSAGE (like you would in SQL)      │
│    { "_id": "msg_abc", "conv_id": "123",                     │
│      "from": "alice", "text": "hi" }                         │
│    With index on (conv_id, timestamp)                        │
│                                                              │
│  LESSON: Document databases don't mean "put everything       │
│  in one document." Model based on access pattern and         │
│  growth bounds.                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 4: Hands-On Exercises

```
┌──────────────────────────────────────────────────────────────┐
│  EXERCISE 1: Redis Data Structures                           │
│                                                              │
│  docker run -p 6379:6379 redis:7                             │
│  docker exec -it <container> redis-cli                       │
│                                                              │
│  # Strings — basic key-value                                 │
│  SET user:1:name "Alice"                                     │
│  GET user:1:name                                             │
│                                                              │
│  # Atomic counter (used in rate limiting)                    │
│  SET api:hits:user:1 0                                       │
│  INCR api:hits:user:1    # returns 1                         │
│  INCR api:hits:user:1    # returns 2                         │
│  INCR api:hits:user:1    # returns 3                         │
│  # This is ATOMIC — safe under concurrency                   │
│                                                              │
│  # TTL (key expires automatically)                           │
│  SET session:abc "user:1" EX 30   # expires in 30 seconds    │
│  TTL session:abc                   # see remaining time      │
│  # Wait 30 seconds...                                        │
│  GET session:abc                   # returns (nil)           │
│                                                              │
│  # Sorted Set (leaderboard)                                  │
│  ZADD leaderboard 100 "alice"                                │
│  ZADD leaderboard 250 "bob"                                  │
│  ZADD leaderboard 175 "carol"                                │
│  ZREVRANGE leaderboard 0 2 WITHSCORES                        │
│  # Returns: bob(250), carol(175), alice(100)                 │
│  # Top 3 leaderboard in ONE command, O(log n)                │
│                                                              │
│  # See memory usage                                          │
│  INFO memory                                                 │
│  # Note: used_memory, used_memory_peak                       │
│                                                              │
│  # DANGEROUS COMMAND — feel the pain                         │
│  DEBUG SLEEP 5                                               │
│  # Redis is FROZEN for 5 seconds. Single-threaded.           │
│  # In production, this is what happens with KEYS *           │
│  # on a large database. Everything blocks.                   │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 2: MongoDB vs SQL Query Comparison                 │
│                                                              │
│  docker run -p 27017:27017 mongo:7                           │
│  docker exec -it <container> mongosh                         │
│                                                              │
│  // Insert documents with nested structure                   │
│  db.orders.insertMany([                                      │
│    {                                                         │
│      user: {id: 1, name: "Alice"},                           │
│      items: [{product: "Book", qty: 2, price: 15.99}],       │
│      total: 31.98,                                           │
│      status: "shipped",                                      │
│      created_at: new Date("2024-01-15")                      │
│    },                                                        │
│    {                                                         │
│      user: {id: 1, name: "Alice"},                           │
│      items: [{product: "Pen", qty: 5, price: 1.99}],         │
│      total: 9.95,                                            │
│      status: "pending",                                      │
│      created_at: new Date("2024-01-20")                      │
│    },                                                        │
│    {                                                         │
│      user: {id: 2, name: "Bob"},                             │
│      items: [{product: "Desk", qty: 1, price: 299.99}],      │
│      total: 299.99,                                          │
│      status: "shipped",                                      │
│      created_at: new Date("2024-01-18")                      │
│    }                                                         │
│  ]);                                                         │
│                                                              │
│  // Query nested fields (no JOIN needed!)                    │
│  db.orders.find({"user.id": 1})                              │
│                                                              │
│  // Query with conditions                                    │
│  db.orders.find({status: "shipped", total: {$gt: 20}})       │
│                                                              │
│  // Aggregation (GROUP BY equivalent)                        │
│  db.orders.aggregate([                                       │
│    {$group: {_id: "$status", count: {$sum: 1},               │
│              avg_total: {$avg: "$total"}}}                   │
│  ])                                                          │
│                                                              │
│  // Check query execution plan                               │
│  db.orders.find({"user.id": 1}).explain("executionStats")    │
│  // Notice: COLLSCAN (collection scan — no index!)           │
│                                                              │
│  // Add an index                                             │
│  db.orders.createIndex({"user.id": 1, "created_at": -1})     │
│                                                              │
│  // Run explain again                                        │
│  db.orders.find({"user.id": 1}).explain("executionStats")    │
│  // Now: IXSCAN (index scan — much faster!)                  │
│                                                              │
│  // OBSERVE: MongoDB uses the same B-tree indexing           │
│  // concepts as PostgreSQL. The fundamentals are the same.   │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 3: See Redis Memory Behavior                       │
│                                                              │
│  # Fill Redis with data                                      │
│  redis-cli                                                   │
│  CONFIG SET maxmemory 10mb                                   │
│  CONFIG SET maxmemory-policy noeviction                      │
│                                                              │
│  # Run a script to fill memory:                              │
│  # (in bash)                                                 │
│  for i in $(seq 1 100000); do                                │
│    redis-cli SET "key:$i" "$(head -c 100 /dev/urandom |      │
│    base64)"                                                  │
│  done                                                        │
│                                                              │
│  # At some point you'll see:                                 │
│  # (error) OOM command not allowed when used memory > ...    │
│  # This is what happens in production without eviction!      │
│                                                              │
│  # Now enable eviction:                                      │
│  redis-cli CONFIG SET maxmemory-policy allkeys-lru           │
│                                                              │
│  # Continue writing — old keys get evicted silently          │
│  redis-cli SET "newkey" "value"  # succeeds!                 │
│  redis-cli GET "key:1"           # might be gone (evicted)   │
│                                                              │
│  # OBSERVE: The difference between noeviction and            │
│  # allkeys-lru. In production, one crashes your app,         │
│  # the other gracefully degrades.                            │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 5: SRE Scenario

```
┌──────────────────────────────────────────────────────────────┐
│  SCENARIO: Social Media Platform — Multi-Database Incident   │
│                                                              │
│  You're the on-call SRE for a social media platform.         │
│  Stack:                                                      │
│  → PostgreSQL: User accounts, friendships, auth              │
│  → MongoDB: Posts, comments (document store)                 │
│  → Cassandra: Activity feed, notifications (3-node cluster,  │
│    replication factor 3, read/write at QUORUM)               │
│  → Redis: Timeline cache, session storage,                   │
│    rate limiting (Redis Cluster, 3 masters)                  │
│  → Neo4j: Friend recommendations                             │
│  → 50 application servers behind an ALB                      │
│  → 2M daily active users                                     │
│                                                              │
│  ALERT TIMELINE:                                             │
│                                                              │
│  14:00 — Cassandra node 2 goes down (hardware failure).      │
│          Cluster is now 2 nodes out of 3.                    │
│                                                              │
│  14:01 — Activity feed writes: latency spike from 5ms        │
│          to 45ms but still succeeding.                       │
│          Activity feed reads: some succeed, some fail with   │
│          "ConsistencyLevel QUORUM not achieved,              │
│           only 2 of 3 replicas responded"                    │
│                                                              │
│  14:03 — Redis: MEMORY usage at 92% of maxmemory.            │
│          Eviction rate: 4,200 keys/second.                   │
│          Cache hit rate dropped from 94% → 67%.              │
│                                                              │
│  14:05 — MongoDB: Read latency up 3x (from 12ms to 38ms).    │
│          Write latency normal.                               │
│          Connections to MongoDB: 1,847 (normally ~400).      │
│                                                              │
│  14:07 — PostgreSQL: Connection count: normal.               │
│          Query latency: normal.                              │
│          CPU: normal.                                        │
│                                                              │
│  14:08 — Neo4j: "Friend suggestions" feature returning     m │
│          empty results for ~30% of users.                    │
│          No errors in Neo4j logs. Query latency normal.      │
│                                                              │
│  14:10 — Application logs:                                   │
│          "TimeoutError: Redis command timed out after 500ms" │
│          Rate: 340/minute (normally 0)                       │
│          All timeouts from Redis Cluster node 2 (master).    │
│                                                              │
│  14:12 — Customer complaints:                                │
│          "My feed is empty"                                  │
│          "I can't see friend suggestions"                    │
│          "The app is slow"                                   │
│          "I posted something but it disappeared"             │
│                                                              │
│  14:14 — Monitoring dashboard:                               │
│          Redis node 2 INFO output:                           │
│            used_memory: 14.1GB                               │
│            maxmemory: 15GB                                   │
│            maxmemory_policy: volatile-lru                    │
│            evicted_keys (last 5 min): 21,000                 │
│            expired_keys (last 5 min): 890                    │
│            connected_clients: 12,400                         │
│            blocked_clients: 247                              │
│            instantaneous_ops_per_sec: 89,000                 │
│            keyspace_hits: 340,000                            │
│            keyspace_misses: 170,000                          │
│                                                              │
│          Cassandra nodetool status:                          │
│            Node 1: UN (Up Normal) — owns 33.3%               │
│            Node 2: DN (Down Normal) — owns 33.3%             │
│            Node 3: UN (Up Normal) — owns 33.3%               │
│                                                              │
│          MongoDB rs.status():                                │
│            Primary: healthy                                  │
│            Secondary 1: healthy, lag 0.2s                    │
│            Secondary 2: healthy, lag 0.1s                    │
│                                                              │
│  14:15 — Application metric:                                 │
│          Feed rendering service: cache miss → falls back     │
│          to Cassandra read → falls back to MongoDB read      │
│          (full reconstruction from posts collection).        │
│          This fallback path takes 180-400ms per request.     │
│          Currently 34% of feed requests hitting this path.   │
│                                                              │
└──────────────────────────────────────────────────────────────┘

QUESTIONS:

Q1: Identify ALL the problems. For each, specify which 
    database/component is affected, the root cause, and 
    the evidence from the alerts.

Q2: Trace the CASCADE. The Cassandra node failure at 14:00 
    triggered a chain reaction. Map the exact causal chain 
    from that initial failure through every subsequent 
    symptom. Which problems are CAUSED by the cascade, 
    and which (if any) are INDEPENDENT?

Q3: The Cassandra reads are failing with "QUORUM not 
    achieved, only 2 of 3 replicas responded." 
    
    Wait — there are 2 nodes alive out of 3, and 
    QUORUM of 3 is 2. So 2 of 3 should satisfy QUORUM.
    Why are some reads STILL failing? Give the precise 
    technical explanation.

Q4: The Redis eviction policy is volatile-lru, and 
    21,000 keys were evicted in 5 minutes. But the 
    cache hit rate dropped from 94% to 67%. 
    
    Explain why volatile-lru specifically is making 
    this problem WORSE than it needs to be. What 
    policy would be better and why?

Q5: The Neo4j "friend suggestions" returning empty for 
    30% of users — Neo4j itself is healthy (normal 
    latency, no errors). What's causing this? 
    (Hint: think about where Neo4j gets its input data.)

Q6: Give your prioritized mitigation plan with exact 
    commands. Remember the principle: one change, 
    verify, next change.
```

---

## Step 6: Targeted Reading

```
┌──────────────────────────────────────────────────────────────┐
│  READ AFTER THIS LESSON:                                     │
│                                                              │
│  DDIA Chapter 2: "Data Models and Query Languages"           │
│  → Pages 27-42 (full chapter)                                │
│  → Focus on: "Relational Model vs Document Model" section    │
│  → Focus on: "Are Document Databases Repeating History?"     │
│  → This connects directly to the SQL vs Document modeling    │
│    comparison we covered                                     │
│                                                              │
│  DDIA Chapter 3: "Storage and Retrieval"                     │
│  → Pages 69-79 (Hash indexes → SSTables → LSM-Trees)         │
│    THIS explains the storage engine behind Cassandra.        │
│    After reading, you'll understand WHY the write path       │
│    (commit log → memtable → SSTable) is structured           │
│    that way. It's the LSM-Tree architecture.                 │
│  → Pages 79-85 (B-Trees — you already know this from         │
│    the SQL topic. Read to reinforce.)                        │
│  → Pages 85-90 (Comparing B-Trees and LSM-Trees)             │
│    KEY SECTION: This is the write-optimized vs               │
│    read-optimized tradeoff in one comparison.                │
│                                                              │
│  TOTAL: ~35 pages. You already know the concepts.            │
│  The book provides the theoretical foundation for WHY        │
│  these storage engines make the tradeoffs they do.           │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 7: Key Takeaways

```
┌──────────────────────────────────────────────────────────────┐
│  5 THINGS TO REMEMBER IF YOU FORGET EVERYTHING ELSE          │
│                                                              │
│  1. NoSQL is not "better" than SQL. Each NoSQL type          │
│     is OPTIMIZED for ONE access pattern at the cost          │
│     of everything else. Choose based on your PRIMARY         │
│     access pattern. If unsure, use PostgreSQL.               │
│                                                              │
│  2. Cassandra's write path (commit log → memtable →          │
│     SSTable) is why it's write-optimized: sequential I/O,    │
│     no read-before-write, no locks. Reads pay the price      │
│     (multiple SSTable merges). This is the LSM-Tree          │
│     tradeoff.                                                │
│                                                              │
│  3. Redis is single-threaded. One slow command blocks        │
│     everything. ALWAYS configure maxmemory-policy            │
│     (never noeviction for cache workloads). Provision 2x     │
│     RAM for fork/snapshot safety.                            │
│                                                              │
│  4. Document databases (MongoDB) require the SAME            │
│     discipline as SQL: define schemas in code, create        │
│     indexes for query patterns, bound array growth.          │
│     "Schemaless" doesn't mean "no rules."                    │
│                                                              │
│  5. Most production systems use POLYGLOT PERSISTENCE:        │
│     multiple databases, each handling what it's best at.     │
│     This means understanding failure cascades ACROSS         │
│     databases is critical — one database failing can         │
│     overload another through fallback paths.                 │
└──────────────────────────────────────────────────────────────┘
```

---

Take your time with this scenario. Six questions this time — the cascade tracing (Q2) and the Cassandra QUORUM puzzle (Q3) are designed to test deep understanding. The Redis eviction question (Q4) and Neo4j question (Q5) test whether you can reason about non-obvious cross-system interactions.

# Incident Deep-Dive: Multi-Database Cascade Failure

---

## Question 1: All Problems — Root Cause and Evidence

### Problem 1: Cassandra Quorum Degradation (The Trigger)

**Component:** Cassandra (Activity feed / notifications)

**Root cause:** Node 2 hardware failure reduces the 3-node cluster to 2 nodes. With RF=3 and QUORUM consistency, the system has **zero margin** — it needs exactly 2 responses and has exactly 2 nodes available. Any additional latency or timeout on either surviving node causes quorum failures.

**Evidence:**
```
→ nodetool status: Node 2 DN (Down Normal), owns 33.3%
→ Feed writes: 5ms → 45ms (9x increase — surviving nodes 
  absorbing 50% more coordinator + replica work)
→ Feed reads: some fail with "ConsistencyLevel QUORUM 
  not achieved, only 2 of 3 replicas responded"
→ Failure starts immediately at 14:01, 1 minute after 
  node 2 death — directly correlated
```

### Problem 2: Redis Memory Pressure and Eviction Storm

**Component:** Redis Cluster (Timeline cache, sessions, rate limiting)

**Root cause:** Cache miss rate increased because Cassandra feed reads are failing, driving more fallback traffic through Redis for timeline cache lookups. Redis node 2 is at 92% of maxmemory (14.1GB / 15GB). The eviction policy (`volatile-lru`) is aggressively evicting keys with TTLs to stay under the memory limit — but it's evicting HOT timeline cache keys that are immediately re-requested, creating a **churn cycle** where evicted keys are re-fetched, re-cached, and re-evicted.

**Evidence:**
```
→ Memory: 14.1GB / 15GB (94% — critically close to limit)
→ Eviction rate: 4,200 keys/sec (21,000 in 5 minutes)
→ Cache hit rate: 94% → 67% (27-point drop)
→ keyspace_hits: 340,000 vs keyspace_misses: 170,000
  → Hit ratio: 340K / (340K+170K) = 66.7% ← MATCHES the 67%
→ connected_clients: 12,400 (massive — 50 app servers × 
  ~250 connections each is plausible under retry pressure)
→ instantaneous_ops_per_sec: 89,000 (high throughput demand)
→ expired_keys: only 890 in 5 min (natural TTL expiry is LOW — 
  the 21,000 evictions are FORCED evictions, not organic expiry)
```

### Problem 3: Redis Node 2 Timeout / Overload

**Component:** Redis Cluster node 2 (specific master)

**Root cause:** Redis node 2 specifically is overwhelmed. At 89,000 ops/sec with 12,400 connected clients and 247 blocked clients, the single-threaded Redis event loop cannot process commands fast enough. Memory management overhead from constant evictions (scanning for LRU candidates) adds CPU pressure to every operation.

**Evidence:**
```
→ "TimeoutError: Redis command timed out after 500ms" — 340/minute
→ "All timeouts from Redis Cluster node 2 (master)" — isolated 
  to one node
→ blocked_clients: 247 — clients waiting on blocking operations 
  (BLPOP, BRPOP, or just queued behind slow operations)
→ 89,000 ops/sec with LRU eviction scanning on every write = 
  CPU saturation on single-threaded Redis
```

### Problem 4: MongoDB Connection Spike / Read Latency

**Component:** MongoDB (Posts, comments)

**Root cause:** When the feed cache misses in Redis AND the Cassandra feed read fails, the application falls back to **full feed reconstruction from MongoDB** — querying the posts collection directly. This fallback path takes 180-400ms per request and is hitting 34% of feed requests. Each reconstruction holds a MongoDB connection for the duration, causing connection accumulation. MongoDB read latency is up 3x because of connection overhead and increased query volume, NOT because MongoDB itself is unhealthy.

**Evidence:**
```
→ Connections: 1,847 (normally ~400) — 4.6x increase
→ Read latency: 12ms → 38ms (3.2x increase)
→ Write latency: normal (writes aren't affected — 
  this is purely a read-side load issue)
→ MongoDB rs.status(): all members healthy, lag <0.2s
  (MongoDB itself is fine — it's being OVERLOADED by 
  traffic it was never designed to handle at this volume)
→ Feed rendering service: 34% of requests hitting the 
  full reconstruction path (180-400ms each)
```

### Problem 5: Neo4j Empty Friend Suggestions

**Component:** Neo4j (Friend recommendations) — but the root cause is UPSTREAM, not in Neo4j.

**Root cause:** Neo4j is healthy — normal latency, no errors. The friend suggestion feature depends on **input data from an upstream source** (likely the user's friend list cached in Redis or activity data from Cassandra). With Redis evicting cached friend-list keys and timing out, the friend suggestions endpoint cannot retrieve the input parameters needed to query Neo4j. The application's error handling catches the upstream failure and returns empty results instead of an error.

**Evidence:**
```
→ Neo4j logs: no errors (Neo4j itself is perfectly healthy)
→ Neo4j query latency: normal (when queries ARE made, they're fast)
→ ~30% of users affected — correlates with Redis cache miss 
  rate (33% miss rate ≈ 30% empty suggestions)
→ The 30% matches the percentage of users whose friend-list 
  cache keys were evicted by volatile-lru or whose requests 
  route to the overloaded Redis node 2
→ Timing: 14:08 (8 minutes into incident, after Redis 
  degradation is established)
```

### Problem Map

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  Cassandra Node 2 Dies (14:00) ← TRIGGER                │
│    │                                                    │
│    ├─► Feed reads fail / slow                           │
│    │                                                    │
│    ▼                                                    │
│  Redis Cache Pressure (14:03)                           │
│    │  (misses increase → evictions → more misses)       │
│    │                                                    │
│    ├─► Redis Node 2 Overload (14:10)                    │
│    │     (timeouts → retries → more load)               │
│    │                                                    │
│    ├─► MongoDB Overload (14:05)                         │
│    │     (fallback reads → connection spike)            │
│    │                                                    │
│    └─► Neo4j Empty Results (14:08)                      │
│          (missing input data from Redis)                │
│                                                         │
│  PostgreSQL: UNAFFECTED ✅ (independent workload)      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Question 2: The Cascade Chain

### Exact Causal Chain

```
STEP 1 (14:00): Cassandra node 2 dies
  → Immediate: cluster loses 1/3 of its capacity
  → Surviving nodes 1 and 3 absorb ALL coordinator 
    and replica duties
  → Write latency: 5ms → 45ms (nodes working harder)
  → Some reads fail QUORUM (explained in Q3)

         │
         ▼

STEP 2 (14:01-14:03): Feed read failures cascade to Redis
  → Application flow for "load user feed":
    1. Check Redis timeline cache → MISS (or HIT with stale data)
    2. Read from Cassandra activity feed → FAIL (quorum not met)
    3. Fall back to MongoDB full reconstruction
  
  → When Cassandra reads fail, the application cannot 
    POPULATE the Redis cache with fresh feed data
  → Existing cached timelines expire naturally (TTL)
  → New cache entries can't be written (source data unavailable)
  → Cache hit rate begins dropping: 94% → declining

         │
         ▼

STEP 3 (14:03): Redis memory pressure triggers eviction storm
  → Redis is already at 92% memory (14.1GB / 15GB)
  → Increased request volume (more cache checks from 
    failing Cassandra reads) pushes memory higher
  → volatile-lru kicks in: evicts 4,200 keys/sec
  → CRITICAL: evicted keys include HOT timeline caches 
    that are immediately re-requested
  → Evict → miss → reconstruct → re-cache → evict again
  → POSITIVE FEEDBACK LOOP:
  
    ┌─────────────────────────────────────────┐
    │  Evict key → cache miss → app queries   │
    │  Cassandra/MongoDB → tries to re-cache  │
    │  → memory still full → evict again      │
    │  → miss again → query again → ...       │
    │                                         │
    │  This is CACHE THRASHING                │
    └─────────────────────────────────────────┘

         │
         ▼

STEP 4 (14:03-14:05): Cache misses flood MongoDB
  → 34% of feed requests now hit the full reconstruction 
    path: Redis miss → Cassandra fail → MongoDB query
  → Each reconstruction: 180-400ms, holds a MongoDB 
    connection for the entire duration
  → MongoDB connections: 400 → 1,847 (4.6x)
  → MongoDB read latency: 12ms → 38ms 
    (connection management overhead + query queue depth)
  → MongoDB is a VICTIM, not a cause — it's healthy 
    but being hammered by traffic it wasn't sized for

         │
         ▼

STEP 5 (14:05-14:10): Redis node 2 becomes overwhelmed
  → 89,000 ops/sec + constant LRU eviction scanning
  → 12,400 connected clients (retries from app servers)
  → Single-threaded Redis can't keep up
  → Commands start timing out: 340 timeouts/minute
  → 247 blocked clients queued behind slow operations
  → Timeouts trigger APPLICATION-LEVEL RETRIES
  → Retries generate MORE Redis commands → more load
  → SECOND POSITIVE FEEDBACK LOOP:

    ┌─────────────────────────────────────────┐
    │  Redis slow → timeout → app retries     │
    │  → more Redis commands → Redis slower   │
    │  → more timeouts → more retries → ...   │
    └─────────────────────────────────────────┘

         │
         ▼

STEP 6 (14:08): Neo4j friend suggestions break
  → Friend suggestions endpoint needs user's current 
    friend list as INPUT (to compute friends-of-friends)
  → Friend list is cached in Redis
  → Redis either: evicted the key (cache miss) OR 
    timed out on node 2 (500ms timeout)
  → Without input data, application cannot formulate 
    the Neo4j query properly
  → Error handling returns empty results (not an error)
  → 30% affected ≈ 33% Redis miss rate — CORRELATED

         │
         ▼

STEP 7 (14:10-14:15): All symptoms compound
  → "My feed is empty" — Cassandra fail + Redis miss + 
    MongoDB fallback too slow
  → "I can't see friend suggestions" — Redis eviction/timeout 
    → Neo4j gets no input
  → "The app is slow" — everything takes 180-400ms 
    instead of 5-50ms
  → "I posted but it disappeared" — post saved to MongoDB 
    (write is fine) but feed in Cassandra wasn't updated 
    (write slow/failed) and Redis cache shows stale feed 
    without the new post
```

### Cascade vs Independent

```
┌──────────────────────┬──────────────────────────────────┐
│ CAUSED BY CASCADE    │ REASON                           │
├──────────────────────┼──────────────────────────────────┤
│ Redis eviction storm │ Cassandra failures → more cache  │
│                      │ checks + inability to repopulate │
├──────────────────────┼──────────────────────────────────┤
│ Redis node 2 timeout │ Increased ops from cache misses  │
│                      │ + eviction CPU overhead          │
├──────────────────────┼──────────────────────────────────┤
│ MongoDB overload     │ Fallback path from Redis miss +  │
│                      │ Cassandra fail → full reconstruct│
├──────────────────────┼──────────────────────────────────┤
│ Neo4j empty results  │ Redis eviction/timeout removes   │
│                      │ upstream input data              │
├──────────────────────┼──────────────────────────────────┤
│                      │                                  │
│ INDEPENDENT          │ REASON                           │
├──────────────────────┼──────────────────────────────────┤
│ PostgreSQL: healthy  │ User accounts/auth/friendships   │
│                      │ are a separate workload. Not in  │
│                      │ the feed read/write path.        │
│                      │ Connection count, latency, CPU   │
│                      │ all normal at 14:07.             │
├──────────────────────┼──────────────────────────────────┤
│ Redis memory at 92%  │ Redis was ALREADY near capacity  │
│ pre-incident         │ before Cassandra died. This is a │
│ (PARTIALLY           │ pre-existing condition that made │
│  INDEPENDENT)        │ the cascade MUCH worse. If Redis │
│                      │ had been at 60% memory, evictions│
│                      │ wouldn't have started and the    │
│                      │ cascade would have been contained│
│                      │ to just Cassandra degradation.   │
└──────────────────────┴──────────────────────────────────┘
```

### The Key Insight: Redis Was the Amplifier

```
The Cassandra failure alone would have caused:
  → Feed reads: some failures, some slow
  → Impact: moderate, limited to activity feed

But Redis at 92% memory turned a MODERATE incident 
into a PLATFORM-WIDE CASCADE:
  → The eviction storm destroyed cache effectiveness
  → Every cache miss created downstream load on 
    Cassandra (making it worse) and MongoDB (dragging 
    a healthy system into the incident)
  → Redis itself became a bottleneck (timeouts)
  → Neo4j — a completely unrelated feature — broke 
    because its input data was evicted from Redis

If Redis had headroom, the incident would have been:
  "Some feed reads are slow, Cassandra is degraded"
Instead it became:
  "Everything is broken"

Redis was the FORCE MULTIPLIER.
```

---

## Question 3: Why QUORUM Fails with 2 of 3 Nodes Alive

### The Math That Seems Like It Should Work

```
Replication Factor (RF) = 3
Nodes in cluster = 3
QUORUM = floor(RF / 2) + 1 = floor(3/2) + 1 = 2

Node 2 is down. Nodes 1 and 3 are up.
Available replicas for ANY token range = 2
Required for QUORUM = 2

2 available ≥ 2 required → SHOULD WORK

So why do some reads fail?
```

### The Precise Technical Explanation

**With RF=3 across exactly 3 nodes, every piece of data is replicated to ALL 3 nodes. When one node dies, you have exactly 2 replicas available for every token range. QUORUM requires exactly 2 responses. This means you have ZERO MARGIN — you need both surviving nodes to respond for every single read.**

```
WHAT'S ACTUALLY HAPPENING:

The coordinator (say Node 1) receives a read at QUORUM:

  SUCCESSFUL READ:
    Node 1 (coordinator): reads locally → responds ✅
    Node 2: DOWN ❌ (known dead, not contacted)
    Node 3: contacted → responds within timeout ✅
    Responses: 2 ≥ 2 (QUORUM) → SUCCESS

  FAILED READ:
    Node 1 (coordinator): reads locally → responds ✅
    Node 2: DOWN ❌
    Node 3: contacted → DOES NOT RESPOND IN TIME ❌
    Responses: 1 < 2 (QUORUM) → FAILURE

  "Why doesn't Node 3 respond in time?"

  Node 3 is handling 1.5x its normal load:
    → All reads that would have gone to Node 2 now 
      hit Nodes 1 and 3
    → All coordinator duties formerly on Node 2 are 
      redistributed
    → Hinted handoff writes (storing hints for Node 2's 
      data) consume disk I/O
    → The cascade from 14:03+ is driving ADDITIONAL 
      read traffic to Cassandra (Redis cache misses 
      falling through to Cassandra)

  Under this load:
    → JVM garbage collection pauses (10-200ms stalls)
    → Compaction I/O spikes (Cassandra background 
      process merging SSTables)
    → Thread pool exhaustion (read thread pool queue 
      backing up)
    → Disk I/O contention (reads competing with 
      hinted handoff writes and compaction)

  Any of these can cause Node 3 to miss the 
  read_request_timeout (default: 5000ms).
  When it misses timeout, coordinator gets only 
  1 response → QUORUM NOT MET.
```

### Why "Some Succeed, Some Fail"

```
The failures are INTERMITTENT because they depend on 
TRANSIENT conditions on the surviving nodes:

  Request at T=0.000s: Node 3 is idle → responds 
                        in 3ms → QUORUM MET ✅
  
  Request at T=0.001s: Node 3 is in GC pause → 
                        responds in 6,200ms → 
                        TIMEOUT → QUORUM NOT MET ❌
  
  Request at T=0.002s: Node 3 is post-GC → responds 
                        in 8ms → QUORUM MET ✅

The reads that fail are the ones that happen to arrive 
when one of the two surviving nodes is momentarily 
unable to respond — GC pause, compaction, disk flush, 
thread pool full.

With 3 healthy nodes and QUORUM=2:
  → You can tolerate 1 slow response 
    (any 2 of 3 can satisfy QUORUM)
  → Probability of 2 nodes being simultaneously 
    slow is LOW

With 2 healthy nodes and QUORUM=2:
  → You can tolerate ZERO slow responses
  → Probability of 1 node being transiently slow 
    is HIGH under load
  → Hence: intermittent failures

┌──────────────────────────────────────────────┐
│                                              │
│  3 nodes, QUORUM=2: TOLERATES 1 slow node    │
│  2 nodes, QUORUM=2: TOLERATES 0 slow nodes   │
│                                              │
│  This is the difference between SURVIVING    │
│  and BARELY SURVIVING.                       │
│                                              │
│  RF=3 with QUORUM on 3 nodes can tolerate    │
│  1 node FAILURE. But it cannot tolerate      │
│  1 node failure + DEGRADATION of a survivor. │
│                                              │
└──────────────────────────────────────────────┘
```

---

## Question 4: Why volatile-lru Makes This Worse

### What volatile-lru Does

```
Redis eviction policies:
  
  volatile-lru:  Evicts the Least Recently Used key 
                 AMONG keys that have a TTL set.
                 Keys WITHOUT a TTL are NEVER evicted.
  
  allkeys-lru:   Evicts the Least Recently Used key 
                 among ALL keys, regardless of TTL.
```

### The Problem: volatile-lru Protects the WRONG Keys

```
Redis is storing multiple types of data:

  TYPE 1: Timeline caches (feed data)
    → These HAVE TTLs (e.g., TTL=300s, cache for 5 minutes)
    → These are HOT — accessed on every feed load
    → These are RECONSTRUCTABLE (can be rebuilt from 
      Cassandra/MongoDB, expensively)
    → volatile-lru: ELIGIBLE for eviction ← BEING EVICTED

  TYPE 2: Session storage
    → These HAVE TTLs (e.g., TTL=86400, 24-hour sessions)
    → These are WARM — accessed on every request for auth
    → volatile-lru: ELIGIBLE for eviction ← AT RISK

  TYPE 3: Rate limiting counters
    → These HAVE TTLs (e.g., TTL=60, per-minute rate windows)
    → These are SMALL but numerous
    → volatile-lru: ELIGIBLE for eviction ← BEING EVICTED

  TYPE 4: Internal application data without TTL
    → Feature flags, configuration caches, etc.
    → These may have NO TTL set
    → These might be STALE or COLD — rarely accessed
    → volatile-lru: IMMUNE FROM EVICTION ← PROTECTED

THE INVERSION:
  volatile-lru is evicting HOT, CRITICAL, FREQUENTLY 
  ACCESSED keys (timeline caches with TTL) while 
  PROTECTING potentially COLD, STALE, LESS IMPORTANT 
  keys (anything without a TTL).

  The eviction policy is BACKWARDS for this workload.
```

### The Thrashing Effect

```
Timeline cache key "feed:user:12345" has TTL=300s.
It's accessed 50 times per minute (hot user).

  T=0:    Key exists, TTL=300s. Cache HIT ✅
  T=1:    Memory pressure → volatile-lru evicts this key
          (it has a TTL, so it's eligible)
  T=1.2:  User refreshes feed → cache MISS ❌
          → Application queries Cassandra → may fail
          → Falls back to MongoDB → 180-400ms reconstruction
          → Re-caches the result: SET feed:user:12345 ... EX 300
  T=1.3:  Memory is still at 92% → new key pushes memory up
          → volatile-lru evicts ANOTHER hot key with TTL
  T=2:    Another user's feed key evicted → same cycle
  
  This is CACHE THRASHING:
    Evict hot key → miss → expensive rebuild → re-cache 
    → memory still full → evict another hot key → ...
  
  Every eviction CREATES a cache miss.
  Every cache miss CREATES downstream load.
  Every downstream response CREATES a new cache entry.
  Every new cache entry TRIGGERS another eviction.
  
  Net result: Redis is doing maximum WORK (evict + write 
  + evict + write) with minimum BENEFIT (67% hit rate 
  instead of 94%).

  Meanwhile, keys WITHOUT TTL sit untouched, consuming 
  memory that could be serving hot timeline data.
```

### The Better Policy: allkeys-lru

```
allkeys-lru evicts the Least Recently Used key across 
ALL keys — TTL or not.

WITH allkeys-lru:
  → A cold configuration key last accessed 3 hours ago 
    (no TTL) would be evicted BEFORE a hot timeline 
    cache last accessed 200ms ago (with TTL)
  → Eviction decisions are based purely on ACCESS 
    RECENCY, not on whether someone happened to set 
    a TTL on the key
  → Hot, frequently-accessed keys survive eviction 
    regardless of their TTL status
  → Cold, rarely-accessed keys get evicted regardless 
    of their TTL status

THIS MATCHES THE ACTUAL IMPORTANCE OF THE DATA.

The key that was accessed 200ms ago is almost certainly 
more valuable to keep cached than the key that hasn't 
been touched in 3 hours — regardless of their TTL 
configuration.

┌──────────────────────────────────────────────┐
│                                              │
│  volatile-lru: "Evict based on TTL + LRU"    │
│    → Penalizes well-designed keys (those     │
│      with proper TTLs) while protecting      │
│      poorly-designed keys (no TTL)           │
│                                              │
│  allkeys-lru: "Evict based on LRU only"      │
│    → The most recently useful data survives  │
│    → Regardless of TTL configuration         │
│    → This is almost always what you want     │
│      under memory pressure                   │
│                                              │
└──────────────────────────────────────────────┘

CAVEAT: If you have keys that MUST NEVER be evicted 
(like distributed locks), allkeys-lru is dangerous.
Those keys should be in a SEPARATE Redis instance.
Mixing "evictable cache" and "non-evictable state" 
in the same Redis instance is an anti-pattern.
```

---

## Question 5: Neo4j Empty Friend Suggestions

### Neo4j Is Healthy — So the Problem Is Upstream

```
Evidence that CONFIRMS Neo4j is not the problem:
  → No errors in Neo4j logs
  → Query latency: normal
  → 70% of users DO get suggestions (Neo4j CAN serve them)
  → Only 30% get empty results

If Neo4j itself were broken:
  → ALL users would be affected, not 30%
  → There would be errors in the logs
  → Latency would be elevated

The 30% number is the critical clue.
It correlates almost exactly with the Redis cache 
miss rate: 33% (170K misses / (340K hits + 170K misses)).
```

### The Exact Mechanism

```
The friend suggestions endpoint does this:

  STEP 1: Get the user's current friend list
    → Check Redis cache: GET friends:user:{userId}
    → This key has a TTL (it's a cache)
    → Under volatile-lru evictions, many of these 
      keys have been evicted

  STEP 2: If cache hit → use friend list as INPUT to Neo4j
    → Query Neo4j: "Find friends-of-friends of these 
      users, excluding users already in the friend list"
    → Neo4j returns recommendations
    → User sees suggestions ✅

  STEP 2 (alternate): If cache MISS → ???
    → The application COULD fall back to PostgreSQL 
      to get the friend list
    → But with 14.1GB memory pressure on Redis and 
      500ms timeouts on node 2, the application may:
      
      a) Get a TIMEOUT from Redis (not a miss, a TIMEOUT)
         → Application catches TimeoutError
         → Error handler returns empty results
         → Doesn't even attempt PostgreSQL fallback
      
      OR
      
      b) Get a cache miss, attempt PostgreSQL fallback,
         but the fallback has a timeout that's being 
         exceeded because the overall request budget 
         is consumed by the Redis timeout wait
      
      OR
      
      c) Get a cache miss, but the error handling is 
         written as:
         
         try:
             friends = redis.get(f"friends:{user_id}")
             if friends is None:
                 return []  # ← Returns empty instead 
                             #   of falling back
         except TimeoutError:
             return []      # ← Same result
         
         suggestions = neo4j.query(
             "MATCH (u)-[:FRIEND]->(f)-[:FRIEND]->(rec)...",
             friend_ids=friends
         )

  In any case: Redis failure → no input for Neo4j 
  → empty results returned to user

WHY 30% AND NOT 33%:
  The 33% is the overall Redis miss rate.
  The friend suggestions endpoint may access a 
  different key distribution than the average.
  Some friend-list keys may be smaller (less likely 
  to be evicted by LRU) or more recently accessed.
  30% ≈ 33% is close enough to confirm the correlation.
```

### The Diagnostic Proof

```
TO VERIFY THIS HYPOTHESIS:

  1. Check if friend-list keys exist in Redis:
     redis-cli --scan --pattern "friends:user:*" | wc -l
     Compare to total active users — if significantly 
     fewer keys than expected, confirms eviction.

  2. Check one of the affected users:
     redis-cli EXISTS friends:user:12345
     → 0 (key doesn't exist — evicted)
     
     redis-cli EXISTS friends:user:67890
     → 1 (key exists — this user gets suggestions)

  3. Check application logs for the friend suggestions 
     endpoint specifically:
     → Look for TimeoutError or cache miss logs 
       correlated with empty responses

THIS IS THE PATTERN:
  A "healthy" system returning wrong results because 
  its UPSTREAM DEPENDENCY is degraded. Neo4j can't 
  know it's returning empty results for the wrong 
  reason — it never even received a query for those 
  30% of users. The failure is INVISIBLE from Neo4j's 
  perspective.
```

---

## Question 6: Prioritized Mitigation Plan

### Priority Ranking

```
┌──────┬──────────────────────────┬────────────────────────────────┐
│ RANK │ ACTION                   │ JUSTIFICATION                  │
├──────┼──────────────────────────┼────────────────────────────────┤
│  1   │ Downgrade Cassandra      │ STOPS THE TRIGGER. Quorum      │
│      │ consistency level        │ failures are the root cause    │
│      │                          │ of the entire cascade.         │
├──────┼──────────────────────────┼────────────────────────────────┤
│  2   │ Fix Redis memory +       │ STOPS THE AMPLIFIER. Redis     │
│      │ eviction policy          │ evictions are turning a single │
│      │                          │ Cassandra issue into platform- │
│      │                          │ wide degradation.              │
├──────┼──────────────────────────┼────────────────────────────────┤
│  3   │ Restore Cassandra        │ FIXES ROOT CAUSE permanently.  │
│      │ capacity (replace node)  │ Until node 2 is back, zero     │
│      │                          │ margin on quorum.              │
├──────┼──────────────────────────┼────────────────────────────────┤
│  4   │ MongoDB connection       │ PROTECT VICTIM. MongoDB is     │
│      │ limiting                 │ being dragged into the cascade.│
│      │                          │ Prevent it from becoming       │
│      │                          │ another failure point.         │
├──────┼──────────────────────────┼────────────────────────────────┤
│  5   │ Neo4j input fallback     │ RESTORE FEATURE. Add fallback  │
│      │                          │ to PostgreSQL for friend list  │
│      │                          │ when Redis unavailable.        │
└──────┴──────────────────────────┴────────────────────────────────┘
```

### Step 1: Downgrade Cassandra Reads to ONE (Minute 0-3)

```bash
# With only 2 nodes alive and QUORUM=2, we have zero margin.
# Downgrade READ consistency to ONE.
# This means only 1 replica needs to respond for a read to succeed.
# With 2 nodes alive, reads will almost always succeed.

# Trade-off: possible stale reads (no read-repair at CL=ONE).
# For an activity feed, slightly stale data is acceptable.
# Much better than FAILED reads causing the entire cascade.

# APPLICATION-LEVEL CHANGE (in the Cassandra client config):
# If configurable at runtime (feature flag or config service):
```

```python
# In the activity feed service's Cassandra client:
# BEFORE:
cluster = Cluster(contact_points=['cass1', 'cass3'])
session = cluster.connect('activity')
session.default_consistency_level = ConsistencyLevel.QUORUM

# AFTER:
session.default_consistency_level = ConsistencyLevel.ONE

# Keep WRITES at QUORUM (or LOCAL_QUORUM) to maintain 
# write durability — we can tolerate stale reads but 
# not lost writes.
```

```bash
# If the application needs redeployment for this change:
kubectl set env deployment/feed-service \
  CASSANDRA_READ_CONSISTENCY=ONE

# VERIFY:
# → Feed read errors should drop to near zero immediately
# → "ConsistencyLevel QUORUM not achieved" errors stop
# → Feed write latency should remain at ~45ms (still slow 
#   but succeeding at QUORUM with 2 nodes)
# → Watch for 60 seconds before proceeding
```

**VERIFY before proceeding:**
```
→ Cassandra read errors: 0
→ Feed reads succeeding at CL=ONE
→ Feed read latency: should drop to 5-15ms 
  (only need 1 node to respond)
→ Application feed-related error rate dropping
```

### Step 2: Fix Redis Memory Pressure (Minute 3-8)

```bash
# TWO ACTIONS: change eviction policy + free memory

# ACTION 2A: Change eviction policy from volatile-lru to allkeys-lru
redis-cli -h redis-node-2 CONFIG SET maxmemory-policy allkeys-lru

# This immediately changes eviction behavior:
# → Cold keys without TTL are now eligible for eviction
# → Hot timeline caches with TTL are less likely to be evicted
# → Eviction decisions based on ACCESS RECENCY, not TTL existence

# Repeat for all Redis cluster masters:
redis-cli -h redis-node-1 CONFIG SET maxmemory-policy allkeys-lru
redis-cli -h redis-node-3 CONFIG SET maxmemory-policy allkeys-lru

# ACTION 2B: Increase maxmemory if possible (buys immediate headroom)
# Check available system memory first:
redis-cli -h redis-node-2 INFO memory
# Look at: used_memory_rss vs total_system_memory

# If system has headroom:
redis-cli -h redis-node-2 CONFIG SET maxmemory 18gb
# Gives 4GB more headroom — stops the eviction storm entirely

# If system memory is tight, DON'T increase — allkeys-lru 
# alone will improve hit rate by evicting cold keys.

# ACTION 2C: Persist the config change
redis-cli -h redis-node-2 CONFIG REWRITE
```

**VERIFY before proceeding:**
```
→ Eviction rate should drop (redis-cli INFO stats | grep evicted)
→ Cache hit rate should start climbing back toward 90%+
→ Watch: keyspace_hits / (keyspace_hits + keyspace_misses)
→ Redis node 2 timeouts should decrease 
  (less eviction CPU overhead)
→ MongoDB connection count should start declining 
  (fewer fallback reads needed)
→ Wait 60-90 seconds — cache needs time to warm back up
```

### Step 3: Replace Cassandra Node 2 (Minute 8-20)

```bash
# This is the permanent fix — restore the cluster to 3 nodes.
# Until node 2 is back, we're running on zero margin.

# OPTION A: If node 2's hardware can be recovered/replaced
# Start the node — it will automatically rejoin and stream 
# data from nodes 1 and 3:
# (on new/repaired hardware with Cassandra installed)
sudo systemctl start cassandra

# Monitor bootstrap/streaming progress:
nodetool netstats
# Look for: "Receiving" streams — data being copied 
# from existing nodes

# OPTION B: If node 2 is dead, add a completely new node
# On new hardware:
# 1. Install Cassandra with same cluster_name and seeds
# 2. Set auto_bootstrap: true in cassandra.yaml
# 3. Start Cassandra — it will join and stream data

# Monitor:
nodetool status
# Wait until new node shows UN (Up Normal)
# Streaming can take 10-60 minutes depending on data volume

# OPTION C (fastest): If this is Kubernetes/containerized
kubectl delete pod cassandra-2 
# StatefulSet will recreate it with persistent volume
# OR if the PV is lost:
kubectl delete pvc cassandra-data-2
kubectl delete pod cassandra-2
# New pod will bootstrap from scratch
```

```bash
# VERIFY:
nodetool status
# Should show all 3 nodes as UN
# Once 3 nodes are healthy:

# Restore QUORUM consistency for reads:
kubectl set env deployment/feed-service \
  CASSANDRA_READ_CONSISTENCY=QUORUM

# VERIFY: reads still succeeding at QUORUM with 3 nodes
```

### Step 4: Protect MongoDB (Minute 8-12, parallel with Step 3)

```bash
# MongoDB connections spiked from 400 to 1,847.
# Even though Steps 1-2 should reduce the fallback traffic,
# add protection so MongoDB doesn't become the next victim.

# Set a connection limit on the MongoDB connection pool 
# in the application:
kubectl set env deployment/feed-service \
  MONGODB_MAX_POOL_SIZE=200 \
  MONGODB_WAIT_QUEUE_TIMEOUT_MS=2000

# This means:
# → Max 200 connections to MongoDB from feed service
# → If all 200 are busy, new requests wait up to 2 seconds
# → After 2 seconds, return an error (fail fast instead 
#   of accumulating unlimited connections)

# Also: if feed reconstruction is still happening at high rate,
# add a circuit breaker to the fallback path:
kubectl set env deployment/feed-service \
  FEED_RECONSTRUCTION_CIRCUIT_BREAKER=true \
  FEED_RECONSTRUCTION_MAX_CONCURRENT=50

# Only allow 50 concurrent full-reconstruction requests.
# Beyond that, return a degraded "feed temporarily unavailable" 
# response instead of overloading MongoDB.
```

**VERIFY:**
```
→ MongoDB connections declining toward 400
→ MongoDB read latency declining toward 12ms
→ No new MongoDB-related errors
```

### Step 5: Fix Neo4j Input Path (Minute 12-15)

```python
# The friend suggestions endpoint needs a fallback for when 
# Redis doesn't have the friend list.

# BEFORE (pseudocode):
async def get_friend_suggestions(user_id):
    try:
        friends = await redis.get(f"friends:{user_id}")
        if friends is None:
            return []  # ← BUG: returns empty on cache miss
    except TimeoutError:
        return []      # ← BUG: returns empty on timeout
    
    return await neo4j.query(SUGGESTIONS_QUERY, friends=friends)

# AFTER:
async def get_friend_suggestions(user_id):
    friends = None
    
    # Try Redis first
    try:
        friends = await redis.get(f"friends:{user_id}")
    except (TimeoutError, ConnectionError):
        pass  # Fall through to PostgreSQL
    
    # Fallback to PostgreSQL if Redis miss/timeout
    if friends is None:
        friends = await postgres.fetch(
            "SELECT friend_id FROM friendships "
            "WHERE user_id = $1", user_id
        )
        # Re-cache for next time (async, don't block)
        asyncio.create_task(
            redis.set(f"friends:{user_id}", 
                      serialize(friends), ex=3600)
        )
    
    if not friends:
        return []  # User genuinely has no friends
    
    return await neo4j.query(SUGGESTIONS_QUERY, friends=friends)
```

```bash
# Deploy:
kubectl rollout restart deployment/friend-suggestions-service

# VERIFY:
# → Empty friend suggestions rate should drop from 30% to ~0%
# → PostgreSQL connection count may increase slightly 
#   (but PostgreSQL is healthy at 14:07 — plenty of headroom)
# → Neo4j query volume should increase (now receiving the 
#   queries it was missing)
```

### Mitigation Timeline Summary

```
┌──────────┬────────────────────────────────────────────────┐
│ MINUTE   │ ACTION                                         │
├──────────┼────────────────────────────────────────────────┤
│ 0-3      │ Downgrade Cassandra reads to CL=ONE            │
│          │ VERIFY: feed read errors → 0                   │
│          │ EFFECT: stops the cascade trigger              │
├──────────┼────────────────────────────────────────────────┤
│ 3-8      │ Change Redis to allkeys-lru + increase memory  │
│          │ VERIFY: eviction rate dropping, hit rate rising│
│          │ EFFECT: stops the amplification loop           │
├──────────┼────────────────────────────────────────────────┤
│ 8-12     │ Protect MongoDB (connection limits + circuit   │
│          │ breaker on reconstruction path)                │
│          │ VERIFY: MongoDB connections declining          │
│          │ EFFECT: protects healthy system from overload  │
├──────────┼────────────────────────────────────────────────┤
│ 8-20     │ Replace Cassandra node 2 (parallel with above) │
│ (parallel)│ VERIFY: nodetool shows 3 UN nodes             │
│          │ EFFECT: restores quorum margin permanently     │
│          │ → Restore CL=QUORUM after node is healthy      │
├──────────┼────────────────────────────────────────────────┤
│ 12-15    │ Deploy Neo4j input fallback to PostgreSQL      │
│          │ VERIFY: empty suggestions → 0%                 │
│          │ EFFECT: restores friend suggestions feature    │
├──────────┼────────────────────────────────────────────────┤
│ 15+      │ Monitor stability across all systems           │
│          │ Confirm:                                       │
│          │   → Cassandra reads: 0 errors, <10ms latency   │
│          │   → Redis: hit rate >90%, evictions near 0     │
│          │   → MongoDB: connections ~400, latency ~12ms   │
│          │   → Neo4j: suggestions working for >99% users  │
│          │   → All customer complaints resolved           │
│          │                                                │
│          │ Write post-incident review                     │
└──────────┴────────────────────────────────────────────────┘

PRINCIPLE FOLLOWED:
  1. Stop the TRIGGER (Cassandra consistency)     → Verify
  2. Stop the AMPLIFIER (Redis eviction)          → Verify
  3. Protect VICTIMS (MongoDB, Neo4j)             → Verify
  4. Fix ROOT CAUSE permanently (replace node)    → Verify
  
  One change at a time. Verify. Then next change.
  Except Step 3 and Cassandra node replacement can 
  run in parallel — they're independent infrastructure 
  actions on different systems.
```
