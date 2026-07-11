# Week 2, Topic 2: NoSQL Taxonomy — When to Use What

---

## Learning Objectives
```
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Name the four NoSQL categories and explain the          ║
║      data model, access pattern, and tradeoff of each        ║
║                                                              ║
║   2. Given a system requirement, choose SQL vs NoSQL         ║
║      AND which NoSQL type — with justified reasoning         ║
║                                                              ║
║   3. Explain WHY Cassandra is write-optimized and            ║
║      MongoDB is document-optimized at the storage            ║
║      engine level (not just "it's designed for writes")      ║
║                                                              ║
║   4. Identify when a team chose the WRONG database           ║
║      for their workload and explain what breaks              ║
║                                                              ║
║   5. Design the data model differently for the same          ║
║      application depending on which database you choose      ║
║      (query-driven modeling vs normalized modeling)          ║
║                                                              ║
║   6. Explain the consistency, availability, and partition    ║
║      tolerance tradeoffs of each NoSQL type                  ║
║      (this sets up Week 3's CAP theorem deep dive)           ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "NoSQL means no schema"                              ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Document stores have implicit schemas that evolve              ║
║   chaotically. Cassandra requires schema design upfront (partition      ║
║   key, clustering columns). "Schemaless" means schema enforcement       ║
║   moves to application code — often worse.                              ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "MongoDB is web scale, SQL isn't"                    ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. PostgreSQL handles terabytes and 100K+ TPS with proper         ║
║   indexing, partitioning, and read replicas. "Web scale" is a           ║
║   workload question, not a SQL vs NoSQL label. Most teams hit           ║
║   application bugs before database limits.                              ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Pick Cassandra for any write-heavy workload"        ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Cassandra optimizes for append-heavy, partition-key            ║
║   lookups with tunable consistency. Ad-hoc analytics, multi-key         ║
║   transactions, and secondary-index-heavy queries perform               ║
║   terribly. Match the access pattern, not the marketing.                ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "NoSQL doesn't need data modeling"                   ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. NoSQL requires query-driven modeling — harder than             ║
║   normalized SQL because you design for access patterns upfront.        ║
║   Wrong partition keys cause hot spots that no amount of                ║
║   horizontal scaling fixes.                                             ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Eventual consistency means data is lost"            ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Eventual consistency guarantees convergence given no           ║
║   new writes — not data loss. The risk is stale reads and               ║
║   conflict resolution (LWW, vector clocks), not silent deletion.        ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "One polyglot database per microservice = free"      ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Each new database type adds operational expertise,             ║
║   backup tooling, monitoring, and cross-service query pain.             ║
║   Polyglot persistence is a deliberate tradeoff, not a default.         ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching
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
╔══════════════════════════════════════════════════════════════╗
║                      NoSQL TAXONOMY                          ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   ╭──────────────╮  ╭──────────────╮                         ║
║   │  KEY-VALUE   │  │   DOCUMENT   │                         ║
║   │              │  │              │                         ║
║   │  Redis       │  │  MongoDB     │                         ║
║   │  DynamoDB    │  │  CouchDB     │                         ║
║   │  Memcached   │  │  Firestore   │                         ║
║   │              │  │              │                         ║
║   │  "Simple,    │  │  "Flexible   │                         ║
║   │   blazing    │  │   schema,    │                         ║
║   │   fast"      │  │   rich       │                         ║
║   │              │  │   queries"   │                         ║
╚══════════════════════════════════════════════════════════════╝
│                                                             │
│  ╔══════════════════════════════════════════════════════════════╗
│  ║   │ WIDE-COLUMN  │  │    GRAPH     │                         ║
│  ║   │              │  │              │                         ║
│  ║   │  Cassandra   │  │  Neo4j       │                         ║
│  ║   │  HBase       │  │  Amazon      │                         ║
│  ║   │  ScyllaDB    │  │  Neptune     │                         ║
│  ║   │              │  │  Dgraph      │                         ║
│  ║   │  "Massive    │  │              │                         ║
│  ║   │   write      │  │  "Relation-  │                         ║
│  ║   │   scale"     │  │   ship       │                         ║
│  ║   │              │  │   traversal" │                         ║
│  ╚══════════════════════════════════════════════════════════════╝
│                                                             │
╰─────────────────────────────────────────────────────────────╯
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
  ✓ GET by exact key         → O(1)
  ✓ SET key to value          → O(1)
  ✓ DELETE by key             → O(1)
  ✓ TTL-based expiration      → automatic
  ✗ Query by value fields     → impossible
  ✗ Range queries             → mostly impossible*
  ✗ JOINs                     → impossible
  ✗ Aggregations              → impossible

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
  ╔══════════════════════════════════════════════════════════════╗
  ║   Strings   → Simple K/V, counters, bitmaps                  ║
  ║   Lists     → Queues, recent items, timelines                ║
  ║   Sets      → Unique collections, intersections              ║
  ║   Sorted    → Leaderboards, priority queues,                 ║
  ║    Sets       range queries by score                         ║
  ║   Hashes    → Object fields (like a mini-row)                ║
  ║   Streams   → Event log, like a mini-Kafka                   ║
  ║   HyperLog  → Cardinality estimation                         ║
  ║    Log        (count unique visitors)                        ║
  ║   Geo        → Geospatial queries                            ║
  ╚══════════════════════════════════════════════════════════════╝

REDIS ARCHITECTURE:

  ╔══════════════════════════════════════════════════════════════╗
  ║   SINGLE-THREADED EVENT LOOP                                 ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   All operations are processed sequentially                  ║
  ║   by ONE thread. This means:                                 ║
  ║                                                              ║
  ║   ✓ No locks needed (no concurrency)                         ║
  ║   ✓ Every operation is atomic                                ║
  ║   ✓ Extremely predictable latency                            ║
  ║   ✗ Can't use multiple CPU cores                             ║
  ║      (for command processing)                                ║
  ║   ✗ One slow command blocks everything                       ║
  ║      (KEYS *, FLUSHALL, large SORT)                          ║
  ║                                                              ║
  ║   Network I/O is multiplexed (epoll/kqueue).                 ║
  ║   Redis 6+ uses I/O threads for network                      ║
  ║   read/write, but command execution is still                 ║
  ║   single-threaded.                                           ║
  ╚══════════════════════════════════════════════════════════════╝

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

  ╔══════════════════════════════════════════════════════════════╗
  ║   IMPORTANT PRODUCTION GOTCHA:                               ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Redis fork() for RDB snapshots copies the                  ║
  ║   entire memory space (copy-on-write).                       ║
  ║                                                              ║
  ║   If Redis uses 30GB RAM and you have heavy                  ║
  ║   writes during snapshot:                                    ║
  ║   → Copy-on-write triggers on every modified                 ║
  ║     page                                                     ║
  ║   → Memory usage can temporarily DOUBLE                      ║
  ║   → 30GB Redis might need 60GB of available                  ║
  ║     RAM during snapshot                                      ║
  ║   → If the server runs out: OOM killer.                      ║
  ║                                                              ║
  ║   ALWAYS provision 2x the Redis data size                    ║
  ║   in available memory. Always.                               ║
  ╚══════════════════════════════════════════════════════════════╝

REDIS SCALING:

  Single node: Up to ~25GB practical (memory limit)

  Redis Cluster:
  → Automatic sharding across multiple nodes
  → 16,384 hash slots distributed across nodes
  → Key → CRC16(key) mod 16384 → slot → node
  → No cross-slot operations for multi-key commands
    (MGET across different slots fails)

  ╔══════════════════════════════════════════════════════════════╗
  ║  Node A  │  │ Node B  │  │ Node C                            ║
  ║  Slots   │  │ Slots   │  │ Slots                             ║
  ║  0-5460  │  │ 5461-   │  │ 10923-                            ║
  ║          │  │ 10922   │  │ 16383                             ║
  ║  +Replica│  │ +Replica│  │ +Replica                          ║
  ╚══════════════════════════════════════════════════════════════╝

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
  ╔══════════════════════════════════════════════════════════════╗
  ║   Table: Orders                                              ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Partition Key: user_id    (REQUIRED)                       ║
  ║   Sort Key:      order_id   (OPTIONAL)                       ║
  ║                                                              ║
  ║   user_id=123, order_id=001 → {item: "book"}                 ║
  ║   user_id=123, order_id=002 → {item: "pen"}                  ║
  ║   user_id=456, order_id=001 → {item: "desk"}                 ║
  ║                                                              ║
  ║   Access patterns:                                           ║
  ║   ✓ Get exact item: PK=123, SK=001                           ║
  ║   ✓ Get all orders for user: PK=123                          ║
  ║   ✓ Get user's recent orders: PK=123,                        ║
  ║      SK > "2024-01-01"                                       ║
  ║   ✗ Get all orders for item "book"                           ║
  ║      (requires scan or GSI)                                  ║
  ╚══════════════════════════════════════════════════════════════╝

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
  ✓ Get by ID                              → O(1)
  ✓ Query by any field                     → uses indexes
  ✓ Query nested fields                    → "user.name"
  ✓ Query array elements                   → "items.product_id"
  ✓ Aggregation pipeline                   → GROUP BY equivalent
  ✓ Text search                            → built-in
  ✓ Flexible schema (add fields anytime)   → no ALTER TABLE
  ✗ JOINs across collections              → limited ($lookup)
  ✗ Multi-document ACID transactions      → added in v4.0+
     (but expensive — design to avoid them)
```

#### MongoDB Deep Dive

```
MongoDB is the dominant document store.

STORAGE ENGINE: WiredTiger (since MongoDB 3.2)

  ╔══════════════════════════════════════════════════════════════╗
  ║   WiredTiger internals:                                      ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   → B-tree for indexes (like PostgreSQL)                     ║
  ║   → Document-level locking (not collection)                  ║
  ║   → Compression: snappy (fast) or zlib (small)               ║
  ║   → MVCC for read isolation                                  ║
  ║   → Journal (WAL equivalent) for durability                  ║
  ║                                                              ║
  ║   Write path:                                                ║
  ║   Write → Journal (WAL) → In-memory cache                    ║
  ║   → Checkpoint to disk every 60s                             ║
  ║                                                              ║
  ║   Read path:                                                 ║
  ║   Query → Check in-memory cache → Disk if miss               ║
  ╚══════════════════════════════════════════════════════════════╝

MONGODB SHARDING:

  ╭───────────╮
  │  mongos   │ ← Router (doesn't store data)
  │  (router) │   Application connects here
  ╰────┬──────╯
       │ Routes queries to correct shard
       │
  ╭────┴──────────────────────────────────╮
  │                                       │
  ╔══════════════════════════════════════════════════════════════╗
  ║  Shard 1  │  │ Shard 2  │  │ Shard 3                         ║
  ║ (replica  │  │(replica  │  │(replica                         ║
  ║   set)    │  │  set)    │  │  set)                           ║
  ╚══════════════════════════════════════════════════════════════╝

  Each shard is a REPLICA SET (primary + secondaries).
  Sharding is by a SHARD KEY (chosen by you).

  Config servers store metadata: which shard has
  which range of shard key values.

SHARD KEY SELECTION IS CRITICAL:

  ✗ BAD shard key: created_at (timestamp)
    → All new writes go to ONE shard (the latest range)
    → "Hot shard" problem — one shard overwhelmed,
      others idle
    → Same problem as auto-increment IDs

  ✗ BAD shard key: status (low cardinality)
    → Only a few values: "pending", "shipped", "delivered"
    → All "pending" orders on one shard
    → "Jumbo chunks" that can't be split further

  ✓ GOOD shard key: user_id (hashed)
    → Evenly distributed across shards
    → Each user's data on one shard (locality)
    → Range queries on user_id don't work well (hashed)
    → BUT point lookups by user_id are efficient

  ✓ GOOD shard key: compound {user_id, created_at}
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

  ╔══════════════════════════════════════════════════════════════╗
  ║   users   │     │   orders     │     │ products              ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  id       │◄────│ user_id (FK) │     │ id                    ║
  ║  name     │     │ id           │     │ name                  ║
  ║  email    │     │ total        │     │ price                 ║
  ╚══════════════════════════════════════════════════════════════╝
                   ╰──────┬───────╯          │
                          │                  │
                   ╭──────┴───────╮          │
                   │ order_items  │          │
                   ├──────────────┤          │
                   │ order_id (FK)│──────────╯
                   │ product_id   │(FK)
                   │ quantity     │
                   │ price        │
                   ╰──────────────╯

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

  ╔══════════════════════════════════════════════════════════════╗
  ║   Row Key: "user:alice"                                      ║
  ║   ╭──────────────────────┬────────────────────╮              ║
  ║   │ Column Family:       │ Column Family:     │              ║
  ║   │ "profile"            │ "activity"         │              ║
  ║   ├──────────────────────┼────────────────────┤              ║
  ║   │ name: "Alice"        │ login:2024-01-15   │              ║
  ║   │ email: "a@b.com"     │ login:2024-01-14   │              ║
  ║   │ age: 30              │ post:2024-01-13    │              ║
  ║   │                      │ post:2024-01-10    │              ║
  ╚══════════════════════════════════════════════════════════════╝
  ├──────────────────────────────────────────────────┤
  │  Row Key: "user:bob"                             │
  │  ╔══════════════════════════════════════════════════════════════╗
  │  ║   │ Column Family:       │ Column Family:     │              ║
  │  ║   │ "profile"            │ "activity"         │              ║
  │  ║   ├──────────────────────┼────────────────────┤              ║
  │  ║   │ name: "Bob"          │ login:2024-01-15   │              ║
  │  ║   │ phone: "555-1234"    │                    │              ║
  │  ║   │ (no email or age!)   │ (only one login!)  │              ║
  │  ╚══════════════════════════════════════════════════════════════╝
  ╰──────────────────────────────────────────────────╯

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

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║          ╭─────╮                                             ║
  ║     ╭────│Node1│────╮                                        ║
  ╚══════════════════════════════════════════════════════════════╝
  │ ╔══════════════════════════════════════════════════════════════╗
  │ ║  │Node6│         │Node2│                                     ║
  │ ╚══════════════════════════════════════════════════════════════╝
  │    │               │     THE RING                │
  │ ╔══════════════════════════════════════════════════════════════╗
  │ ║  │Node5│         │Node3│  Every node is EQUAL.               ║
  │ ╚══════════════════════════════════════════════════════════════╝
  │    │    ╔══════════════════════════════════════════════════════════════╗
  │    │    ╚══════════════════════════════════════════════════════════════╝
  │         ╰─────╯                                  │
  │                                                  │
  │  Data distributed via CONSISTENT HASHING:        │
  │  → hash(partition_key) → position on ring        │
  │  → Data stored on N consecutive nodes            │
  │    (N = replication factor, typically 3)         │
  │                                                  │
  ╰──────────────────────────────────────────────────╯

  No master = no single point of failure.
  Any node goes down? Others serve the request.
  This is why Cassandra targets AVAILABILITY.

CASSANDRA WRITE PATH (why writes are fast):

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Client Write Request                                       ║
  ║        │                                                     ║
  ║        ▼                                                     ║
  ║   ╭──────────────╮                                           ║
  ║   │ Commit Log   │  1. Append to commit log                  ║
  ║   │ (on disk,    │     (sequential write, FAST)              ║
  ║   │  append-only)│     This is the durability                ║
  ╚══════════════════════════════════════════════════════════════╝
  │         │                                         │
  │         ▼                                         │
  │  ╔══════════════════════════════════════════════════════════════╗
  │  ║   │  Memtable    │     (in-memory sorted structure)          ║
  │  ║   │  (in memory) │     This is fast — just memory.           ║
  │  ╚══════════════════════════════════════════════════════════════╝
  │         │                                         │
  │         │  3. Return "write successful" to client │
  │         │     ← DONE. This is why writes are      │
  │         │       sub-millisecond.                  │
  │         │                                         │
  │         ▼  (later, asynchronously)                │
  │  ╔══════════════════════════════════════════════════════════════╗
  │  ║   │   SSTable    │     flush to SSTable on disk.             ║
  │  ║   │ (on disk,    │     SSTable = Sorted String               ║
  │  ║   │  immutable)  │     Table. Immutable once                 ║
  │  ╚══════════════════════════════════════════════════════════════╝
  │                                                   │
  │  5. Compaction (background):                      │
  │     Merge multiple SSTables into fewer, larger    │
  │     SSTables. Remove tombstones (deleted data).   │
  │     Reclaim disk space.                           │
  │                                                   │
  ╰───────────────────────────────────────────────────╯

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

  ╔══════════════════════════════════════════════════════════════╗
  ║   Client Read Request                                        ║
  ║        │                                                     ║
  ║        ▼                                                     ║
  ║   Check Memtable (in memory)                                 ║
  ║        │ Not found or partial?                               ║
  ║        ▼                                                     ║
  ║   Check Bloom Filter for each SSTable                        ║
  ║   (probabilistic: "definitely not here" or                   ║
  ║    "probably here")                                          ║
  ║        │ Bloom filter says "probably here"?                  ║
  ║        ▼                                                     ║
  ║   Read SSTable index → find data block                       ║
  ║        │                                                     ║
  ║        ▼                                                     ║
  ║   Read data block from disk                                  ║
  ║        │                                                     ║
  ║        ▼                                                     ║
  ║   Merge results from multiple SSTables                       ║
  ║   (latest timestamp wins)                                    ║
  ║        │                                                     ║
  ║        ▼                                                     ║
  ║   Return to client                                           ║
  ╚══════════════════════════════════════════════════════════════╝

  Reads may need to check MULTIPLE SSTables
  (data for one row might be spread across SSTables
  written at different times).

  This is why reads are slower than writes in Cassandra.
  Compaction helps by merging SSTables, but it's a
  constant background trade-off.

TUNABLE CONSISTENCY:

  Cassandra lets you choose consistency PER QUERY.
  With replication factor = 3 (data on 3 nodes):

  ╔══════════════════════════════════════════════════════════════╗
  ║   Write Consistency:                                         ║
  ║   ONE     → Write to 1 node, return success                  ║
  ║             (fastest, least durable)                         ║
  ║   QUORUM  → Write to 2/3 nodes, return success               ║
  ║             (balanced)                                       ║
  ║   ALL     → Write to 3/3 nodes, return success               ║
  ║             (slowest, most durable)                          ║
  ║                                                              ║
  ║   Read Consistency:                                          ║
  ║   ONE     → Read from 1 node                                 ║
  ║             (fastest, might be stale)                        ║
  ║   QUORUM  → Read from 2/3 nodes, return latest               ║
  ║             (balanced)                                       ║
  ║   ALL     → Read from 3/3 nodes                              ║
  ║             (slowest, guaranteed latest)                     ║
  ║                                                              ║
  ║   STRONG CONSISTENCY FORMULA:                                ║
  ║   R + W > N  (where N = replication factor)                  ║
  ║                                                              ║
  ║   If R=QUORUM(2) + W=QUORUM(2) > N(3):                       ║
  ║     → At least 1 node overlaps between read set              ║
  ║       and write set                                          ║
  ║     → That node has the latest data                          ║
  ║     → Read is guaranteed to see latest write                 ║
  ║     → This is how you get "strong consistency"               ║
  ║       in an eventually consistent system                     ║
  ║                                                              ║
  ║   If R=ONE(1) + W=ONE(1) = 2 < N(3):                         ║
  ║     → No guaranteed overlap                                  ║
  ║     → You might read stale data                              ║
  ║     → Eventually consistent                                  ║
  ╚══════════════════════════════════════════════════════════════╝

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

  ✗ SELECT * FROM orders;
     (full table scan — Cassandra doesn't do this well)

  ✗ Secondary indexes on high-cardinality columns
     (creates a distributed index that must query ALL nodes)

  ✗ Large partitions (>100MB)
     (single partition key with millions of rows — causes
      hot nodes and read timeouts)

  ✗ Frequent deletes
     (creates tombstones that slow down reads until
      compaction clears them — "tombstone storm")

  ✗ Using Cassandra for data you need to JOIN or aggregate
     (it's not a relational database — stop trying)
```

---

### Category 4: Graph Databases

```
DATA MODEL:
  Everything is NODES and EDGES (relationships).

  ╔══════════════════════════════════════════════════════════════╗
  ║ Alice │                    │ Bob                             ║
  ╚══════════════════════════════════════════════════════════════╝
     │                           │
     │──PURCHASED──►╭──────╮    │
     │              │Book A│◄───╯──REVIEWED
     │              ╰──────╯
     │
     │──LIVES_IN──►╭──────────╮
                   │  NYC     │◄──LIVES_IN──╔══════════════════════════════════════════════════════════════╗
                   │  NYC     │◄──LIVES_IN──╚══════════════════════════════════════════════════════════════╝
                                            ╰──────╯

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
  ✓ Traverse relationships (any depth)     → O(k^d)
  ✓ Shortest path between nodes            → BFS/Dijkstra
  ✓ Pattern matching (find subgraphs)      → native
  ✓ Recommendation (friends who also...)   → efficient
  ✓ Fraud detection (circular transactions)→ cycle detection
  ✗ Bulk aggregations                      → slow
  ✗ Full-table scans                       → very slow
  ✗ Simple key-value lookups               → overkill
  ✗ High write throughput                  → not optimized

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
╔═══════════════════════════════════════════════════════════════╗
║               WHICH DATABASE DO I USE?                        ║
╟───────────────────────────────────────────────────────────────╢
║                                                               ║
║   START HERE: Do you have complex relationships               ║
║   between entities that need deep traversal?                  ║
║       │                                                       ║
║       ├── YES → GRAPH DATABASE (Neo4j)                        ║
║       │         Only if traversal depth > 2 is common         ║
║       │                                                       ║
║       ╰── NO → Continue...                                    ║
║                                                               ║
║   Do you need ACID transactions across multiple entities?     ║
║       │                                                       ║
║       ├── YES → SQL (PostgreSQL)                              ║
║       │         Financial, inventory, user accounts           ║
║       │                                                       ║
║       ╰── NO → Continue...                                    ║
║                                                               ║
║   What is your PRIMARY access pattern?                        ║
║       │                                                       ║
║       ├── Simple GET/SET by key                               ║
║       │   → KEY-VALUE (Redis for cache, DynamoDB for durable) ║
║       │                                                       ║
║       ├── Read whole objects, flexible schema                 ║
║       │   → DOCUMENT (MongoDB)                                ║
║       │                                                       ║
║       ├── Massive write throughput, time-series-like          ║
║       │   → WIDE-COLUMN (Cassandra)                           ║
║       │                                                       ║
║       ╰── Ad-hoc queries, complex joins, reports              ║
║           → SQL (PostgreSQL)                                  ║
║                                                               ║
║   STILL NOT SURE?                                             ║
║   → Use PostgreSQL. Seriously.                                ║
║   → It handles 80% of workloads well.                         ║
║   → JSONB column gives you document-store-like flexibility.   ║
║   → It's the safest default until you KNOW you need           ║
║     something specialized.                                    ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
```

```
THE "USE CASE → DATABASE" CHEAT SHEET:

╔════════════════════════════════════════════════════════════════╗
║  USE CASE               │ BEST FIT         │ WHY               ║
╠════════════════════════════════════════════════════════════════╣
║  User accounts, billing │ PostgreSQL       │ ACID, relations   ║
║  Inventory management   │ PostgreSQL       │ ACID, constraints ║
║  Financial transactions │ PostgreSQL       │ ACID, auditing    ║
║  Content management     │ MongoDB          │ Flexible schema   ║
║  Product catalog        │ MongoDB / PG     │ Varies by needs   ║
║  Session storage        │ Redis            │ Fast, TTL-based   ║
║  Caching layer          │ Redis            │ Sub-ms latency    ║
║  Rate limiting          │ Redis            │ Atomic counters   ║
║  IoT sensor data        │ Cassandra        │ Write throughput  ║
║  Time series metrics    │ Cassandra / TS*  │ Append-heavy      ║
║  Chat messages          │ Cassandra        │ Write-heavy, geo  ║
║  Social graph           │ Neo4j            │ Traversal depth   ║
║  Fraud detection        │ Neo4j            │ Pattern matching  ║
║  Recommendation engine  │ Neo4j + Redis    │ Graph + cache     ║
║  Search / full-text     │ Elasticsearch**  │ Inverted index    ║
║  Leaderboards           │ Redis sorted set │ Sorted, fast      ║
║  Shopping cart           │ Redis / DynamoDB │ Fast, ephemeral  ║
║  Message queue          │ Kafka***         │ Not a DB          ║
║  Analytics / OLAP       │ ClickHouse****   │ Columnar          ║
╠════════════════════════════════════════════════════════════════╣
║  * TimescaleDB (PostgreSQL extension) for time series          ║
║  ** Elasticsearch isn't strictly NoSQL but fits here           ║
║  *** Kafka is a log, not a database, but often compared        ║
║  **** ClickHouse / BigQuery / Redshift for analytics           ║
╚════════════════════════════════════════════════════════════════╝

MOST REAL SYSTEMS USE MULTIPLE DATABASES:

  Example: E-commerce platform
  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   PostgreSQL → Users, Orders, Payments                       ║
  ║   MongoDB    → Product catalog, reviews                      ║
  ║   Redis      → Sessions, cache, cart                         ║
  ║   Elasticsearch → Product search                             ║
  ║   Cassandra  → Event tracking, click stream                  ║
  ║                                                              ║
  ║   This is called POLYGLOT PERSISTENCE.                       ║
  ║   Each database handles what it's best at.                   ║
  ║   The application layer orchestrates.                        ║
  ╚══════════════════════════════════════════════════════════════╝
```

---

## Production Patterns
```
╔══════════════════════════════════════════════════════════════╗
║   FAILURE MODE #1: WRONG DATABASE CHOICE                     ║
║                                                              ║
║   Scenario: Team uses MongoDB for a financial ledger.        ║
║                                                              ║
║   What breaks:                                               ║
║   → Multi-document transactions are slow and limited         ║
║   → No enforced foreign keys → orphaned records              ║
║   → Flexible schema → inconsistent data sneaks in            ║
║   → "Transfer $500 from A to B" requires multi-doc txn       ║
║     across accounts collection → performance tanks           ║
║   → Auditors ask for constraint guarantees → can't provide   ║
║                                                              ║
║   Should have used: PostgreSQL                               ║
║   The team chose MongoDB because "it's modern" and           ║
║   "schema flexibility." Neither matters for a ledger.        ║
║                                                              ║
║   LESSON: Choose database based on ACCESS PATTERN and        ║
║   CONSISTENCY REQUIREMENTS, never based on "what's trendy."  ║
╠══════════════════════════════════════════════════════════════╣
║   FAILURE MODE #2: CASSANDRA TOMBSTONE STORM                 ║
║                                                              ║
║   Scenario: Team stores user sessions in Cassandra with TTL. ║
║   Sessions expire after 30 minutes (TTL = 1800).             ║
║   System handles 500K sessions/day.                          ║
║                                                              ║
║   What breaks:                                               ║
║   → Each TTL expiration creates a TOMBSTONE marker           ║
║   → Tombstones are NOT immediately removed from disk         ║
║   → They persist until compaction runs (gc_grace_seconds,    ║
║     default 10 days)                                         ║
║   → After a week: millions of tombstones accumulated         ║
║   → Reads must scan through tombstones to find live data     ║
║   → Read latency goes from 5ms → 800ms → timeouts            ║
║   → "Tombstone threshold exceeded" warnings in logs          ║
║                                                              ║
║   Fix:                                                       ║
║   → Reduce gc_grace_seconds for this table                   ║
║     (from 10 days to 4 hours — but understand the            ║
║      consistency implications: if a node was down for        ║
║      >4 hours, it might miss the delete and resurrect        ║
║      the data when it comes back)                            ║
║   → Run manual compaction: nodetool compact keyspace table   ║
║   → Consider: is Cassandra the right choice for sessions?    ║
║     Redis with native TTL might be better.                   ║
║                                                              ║
║   LESSON: Cassandra is write-optimized. Deletes are          ║
║   "writes" (tombstone markers). Heavy delete workloads       ║
║   degrade read performance over time.                        ║
╠══════════════════════════════════════════════════════════════╣
║   FAILURE MODE #3: REDIS OOM DURING PEAK                     ║
║                                                              ║
║   Scenario: Redis used for session cache. 8GB instance.      ║
║   Black Friday traffic. Sessions piling up.                  ║
║                                                              ║
║   What breaks:                                               ║
║   → maxmemory = 8GB, but no eviction policy configured       ║
║   → Default: maxmemory-policy = noeviction                   ║
║   → Redis is full → all SET commands return OOM error        ║
║   → New users can't create sessions → can't log in           ║
║   → Existing sessions work (GET still succeeds)              ║
║   → But no new sessions = site effectively down for          ║
║     new visitors                                             ║
║                                                              ║
║   Fix (immediate):                                           ║
║   redis-cli CONFIG SET maxmemory-policy allkeys-lru          ║
║   (evict least recently used keys when memory is full)       ║
║                                                              ║
║   Fix (proper):                                              ║
║   → Always set an eviction policy in production              ║
║   → For sessions: volatile-ttl (evict keys with              ║
║     nearest expiration first)                                ║
║   → For cache: allkeys-lru (evict least recently used)       ║
║   → Monitor: redis-cli INFO memory → used_memory_peak        ║
║   → Alert at 80% of maxmemory                                ║
║                                                              ║
║   EVICTION POLICIES:                                         ║
║   noeviction    → return error when full (BAD for cache)     ║
║   allkeys-lru   → evict ANY key by LRU (good for cache)      ║
║   volatile-lru  → evict only keys WITH TTL by LRU            ║
║   allkeys-random→ evict random key (simple but wasteful)     ║
║   volatile-ttl  → evict keys nearest to expiration           ║
║   allkeys-lfu   → evict least FREQUENTLY used (Redis 4.0+)   ║
║                                                              ║
║   LESSON: Redis without an eviction policy is a ticking      ║
║   time bomb. Configure it BEFORE you need it.                ║
╠══════════════════════════════════════════════════════════════╣
║   FAILURE MODE #4: MONGODB UNBOUNDED ARRAY GROWTH            ║
║                                                              ║
║   Scenario: Chat application stores messages as an array     ║
║   inside a conversation document.                            ║
║                                                              ║
║   {                                                          ║
║     "_id": "conv_123",                                       ║
║     "participants": ["alice", "bob"],                        ║
║     "messages": [                                            ║
║       {"from": "alice", "text": "hi", "ts": "..."},          ║
║       {"from": "bob", "text": "hello", "ts": "..."},         ║
║       ... 500,000 more messages ...                          ║
║     ]                                                        ║
║   }                                                          ║
║                                                              ║
║   What breaks:                                               ║
║   → MongoDB document max size: 16MB                          ║
║   → 500K messages exceed 16MB → writes FAIL                  ║
║   → Even before 16MB: reading the entire document to         ║
║     show "last 20 messages" loads the full array into        ║
║     memory → slow, wasteful                                  ║
║   → $push to append creates write amplification              ║
║     (document might relocate on disk if it grows beyond      ║
║     its allocated space)                                     ║
║                                                              ║
║   Fix:                                                       ║
║   → BUCKET PATTERN: Store messages in time-based buckets     ║
║     {                                                        ║
║       "_id": "conv_123_2024-01-15",                          ║
║       "messages": [ ... max 200 messages ... ],              ║
║       "count": 187                                           ║
║     }                                                        ║
║   → Or: ONE DOCUMENT PER MESSAGE (like you would in SQL)     ║
║     { "_id": "msg_abc", "conv_id": "123",                    ║
║       "from": "alice", "text": "hi" }                        ║
║     With index on (conv_id, timestamp)                       ║
║                                                              ║
║   LESSON: Document databases don't mean "put everything      ║
║   in one document." Model based on access pattern and        ║
║   growth bounds.                                             ║
╚══════════════════════════════════════════════════════════════╝
```

---

## SRE Diagnostic Toolkit

```
WHAT TO WATCH (per NoSQL family)

  CASSANDRA / SCYLLA (wide-column)
    Metrics:
      org.apache.cassandra.metrics.ClientRequest.Unavailable.{Read,Write}
      org.apache.cassandra.metrics.ClientRequest.Timeout.{Read,Write}
      Table.LiveSSTableCount, PendingCompactions, TombstoneScannedHistogram
      Storage.Load (per node), DroppedMessages (MUTATION, READ_REPAIR)
    Commands:
      nodetool status              # UN/DN state, ownership %, load skew
      nodetool tpstats             # dropped mutations, blocked flush writers
      nodetool tablehistograms ks tbl   # p99 read/write, SSTables per read
      nodetool compactionstats     # backlog; growing = write pressure
    Signatures:
      Unavailable spikes with 2/3 nodes UP  -> R+W<=N misconfig or RF wrong
      TombstoneScanned p99 in thousands     -> queue/delete anti-pattern
      One node 3x Load                      -> hot partition (unbounded key)

  REDIS (KV / cache)
    Metrics: evicted_keys, keyspace_hits/misses, used_memory vs maxmemory,
             connected_clients, instantaneous_ops_per_sec, blocked_clients
    Commands:
      redis-cli INFO stats | egrep 'hit|miss|evict|expired'
      redis-cli --bigkeys              # find hot/large keys
      redis-cli --latency-history -i 1 # p99 latency over time
      redis-cli SLOWLOG GET 20
    Signatures:
      evicted_keys climbing + latency spike -> memory pressure, wrong maxmemory-policy
      one slot/key dominating ops           -> hot key; need client-side cache or shard

  MONGODB (document)
    Metrics: replication lag (optime diff), WT cache dirty %, page faults,
             opcounters, scanAndOrder, queued readers/writers
    Commands:
      rs.status()                     # member health, optimeDate lag
      db.serverStatus().wiredTiger.cache
      db.currentOp({ secs_running: { $gt: 5 } })
      db.collection.explain('executionStats').find({...})
    Signatures:
      COLLSCAN in explain             -> missing index
      replication lag growing         -> secondary IO-bound or primary write storm

  DYNAMODB (managed KV/document)
    Metrics: ThrottledRequests, ConsumedRead/WriteCapacityUnits, hot-partition
             (CloudWatch Contributor Insights), SuccessfulRequestLatency
    Signatures:
      Throttling with capacity headroom -> hot partition key (low cardinality PK)

LOG PATTERNS:
  "Operation timed out - received only N responses"  (Cassandra CL not met)
  "OOM command not allowed when used memory > maxmemory" (Redis)
  "not master and slaveOk=false"                       (Mongo read routing)
```

---

## Decision Framework

```
STEP 1 — DOES THE WORKLOAD ACTUALLY NEED NoSQL?
  Relational + <10TB + joins + ad-hoc queries  -> stay on Postgres/Aurora.
  Reach for NoSQL when a SPECIFIC access pattern or scale axis breaks SQL:
    - write throughput beyond a single primary       -> wide-column
    - unbounded horizontal scale on a known key      -> KV / wide-column
    - deeply nested aggregates read/written together -> document
    - relationship traversal is the query            -> graph
    - relevance-ranked full-text search              -> search engine

STEP 2 — PICK THE FAMILY BY ACCESS PATTERN (not by hype)

  ┌───────────────┬────────────────────────────┬────────────────────────────┐
  │ Family        │ Choose when                │ Do NOT choose when         │
  ├───────────────┼────────────────────────────┼────────────────────────────┤
  │ Wide-column   │ Massive writes, time-      │ Ad-hoc queries, joins,     │
  │ (Cassandra)   │ series, known partition    │ strong multi-key txns      │
  │               │ key, tunable consistency   │                            │
  ├───────────────┼────────────────────────────┼────────────────────────────┤
  │ Document      │ Aggregate read/write as a  │ Many-to-many joins,        │
  │ (Mongo/Dynamo)│ unit, flexible schema      │ cross-document txns hot    │
  ├───────────────┼────────────────────────────┼────────────────────────────┤
  │ KV            │ Session, cache, feature    │ Range scans, secondary     │
  │ (Redis/Dynamo)│ flags, sub-ms lookups      │ query dimensions           │
  ├───────────────┼────────────────────────────┼────────────────────────────┤
  │ Graph         │ Traversals, recommendation │ OLTP at web scale,         │
  │ (Neo4j)       │ social graph, fraud rings  │ high write throughput      │
  ├───────────────┼────────────────────────────┼────────────────────────────┤
  │ Search        │ Full-text, relevance,      │ Source of truth, ACID      │
  │ (Elastic)     │ aggregations, facets       │ writes, financial data     │
  └───────────────┴────────────────────────────┴────────────────────────────┘

STEP 3 — MODEL FOR THE QUERY, NOT THE ENTITY
  Wide-column/KV: design the partition key from the read path first.
    Good PK: high cardinality + even access (user_id, device_id#day).
    Bad PK:  status, country, boolean -> hot partitions.

STEP 4 — CONSISTENCY BUDGET (ties to Week 3)
  Need read-your-writes on a key -> R+W>N (QUORUM/QUORUM) in Cassandra,
  strong reads in Dynamo, primary reads in Mongo.
  Tolerate staleness -> CL=ONE reads, eventually consistent Dynamo reads.

RULE: ONE primary store per bounded context. Add a second store only behind
an event stream (CDC/outbox, Week 6) with a documented rebuild procedure.
Every extra store is a dual-write consistency bug waiting to happen.
```

---

## Hands-On Exercises
```
╔══════════════════════════════════════════════════════════════╗
║   EXERCISE 1: Redis Data Structures                          ║
║                                                              ║
║   docker run -p 6379:6379 redis:7                            ║
║   docker exec -it <container> redis-cli                      ║
║                                                              ║
║   # Strings — basic key-value                                ║
║   SET user:1:name "Alice"                                    ║
║   GET user:1:name                                            ║
║                                                              ║
║   # Atomic counter (used in rate limiting)                   ║
║   SET api:hits:user:1 0                                      ║
║   INCR api:hits:user:1    # returns 1                        ║
║   INCR api:hits:user:1    # returns 2                        ║
║   INCR api:hits:user:1    # returns 3                        ║
║   # This is ATOMIC — safe under concurrency                  ║
║                                                              ║
║   # TTL (key expires automatically)                          ║
║   SET session:abc "user:1" EX 30   # expires in 30 seconds   ║
║   TTL session:abc                   # see remaining time     ║
║   # Wait 30 seconds...                                       ║
║   GET session:abc                   # returns (nil)          ║
║                                                              ║
║   # Sorted Set (leaderboard)                                 ║
║   ZADD leaderboard 100 "alice"                               ║
║   ZADD leaderboard 250 "bob"                                 ║
║   ZADD leaderboard 175 "carol"                               ║
║   ZREVRANGE leaderboard 0 2 WITHSCORES                       ║
║   # Returns: bob(250), carol(175), alice(100)                ║
║   # Top 3 leaderboard in ONE command, O(log n)               ║
║                                                              ║
║   # See memory usage                                         ║
║   INFO memory                                                ║
║   # Note: used_memory, used_memory_peak                      ║
║                                                              ║
║   # DANGEROUS COMMAND — feel the pain                        ║
║   DEBUG SLEEP 5                                              ║
║   # Redis is FROZEN for 5 seconds. Single-threaded.          ║
║   # In production, this is what happens with KEYS *          ║
║   # on a large database. Everything blocks.                  ║
╠══════════════════════════════════════════════════════════════╣
║   EXERCISE 2: MongoDB vs SQL Query Comparison                ║
║                                                              ║
║   docker run -p 27017:27017 mongo:7                          ║
║   docker exec -it <container> mongosh                        ║
║                                                              ║
║   // Insert documents with nested structure                  ║
║   db.orders.insertMany([                                     ║
║     {                                                        ║
║       user: {id: 1, name: "Alice"},                          ║
║       items: [{product: "Book", qty: 2, price: 15.99}],      ║
║       total: 31.98,                                          ║
║       status: "shipped",                                     ║
║       created_at: new Date("2024-01-15")                     ║
║     },                                                       ║
║     {                                                        ║
║       user: {id: 1, name: "Alice"},                          ║
║       items: [{product: "Pen", qty: 5, price: 1.99}],        ║
║       total: 9.95,                                           ║
║       status: "pending",                                     ║
║       created_at: new Date("2024-01-20")                     ║
║     },                                                       ║
║     {                                                        ║
║       user: {id: 2, name: "Bob"},                            ║
║       items: [{product: "Desk", qty: 1, price: 299.99}],     ║
║       total: 299.99,                                         ║
║       status: "shipped",                                     ║
║       created_at: new Date("2024-01-18")                     ║
║     }                                                        ║
║   ]);                                                        ║
║                                                              ║
║   // Query nested fields (no JOIN needed!)                   ║
║   db.orders.find({"user.id": 1})                             ║
║                                                              ║
║   // Query with conditions                                   ║
║   db.orders.find({status: "shipped", total: {$gt: 20}})      ║
║                                                              ║
║   // Aggregation (GROUP BY equivalent)                       ║
║   db.orders.aggregate([                                      ║
║     {$group: {_id: "$status", count: {$sum: 1},              ║
║               avg_total: {$avg: "$total"}}}                  ║
║   ])                                                         ║
║                                                              ║
║   // Check query execution plan                              ║
║   db.orders.find({"user.id": 1}).explain("executionStats")   ║
║   // Notice: COLLSCAN (collection scan — no index!)          ║
║                                                              ║
║   // Add an index                                            ║
║   db.orders.createIndex({"user.id": 1, "created_at": -1})    ║
║                                                              ║
║   // Run explain again                                       ║
║   db.orders.find({"user.id": 1}).explain("executionStats")   ║
║   // Now: IXSCAN (index scan — much faster!)                 ║
║                                                              ║
║   // OBSERVE: MongoDB uses the same B-tree indexing          ║
║   // concepts as PostgreSQL. The fundamentals are the same.  ║
╠══════════════════════════════════════════════════════════════╣
║   EXERCISE 3: See Redis Memory Behavior                      ║
║                                                              ║
║   # Fill Redis with data                                     ║
║   redis-cli                                                  ║
║   CONFIG SET maxmemory 10mb                                  ║
║   CONFIG SET maxmemory-policy noeviction                     ║
║                                                              ║
║   # Run a script to fill memory:                             ║
║   # (in bash)                                                ║
║   for i in $(seq 1 100000); do                               ║
║     redis-cli SET "key:$i" "$(head -c 100 /dev/urandom |     ║
║     base64)"                                                 ║
║   done                                                       ║
║                                                              ║
║   # At some point you'll see:                                ║
║   # (error) OOM command not allowed when used memory > ...   ║
║   # This is what happens in production without eviction!     ║
║                                                              ║
║   # Now enable eviction:                                     ║
║   redis-cli CONFIG SET maxmemory-policy allkeys-lru          ║
║                                                              ║
║   # Continue writing — old keys get evicted silently         ║
║   redis-cli SET "newkey" "value"  # succeeds!                ║
║   redis-cli GET "key:1"           # might be gone (evicted)  ║
║                                                              ║
║   # OBSERVE: The difference between noeviction and           ║
║   # allkeys-lru. In production, one crashes your app,        ║
║   # the other gracefully degrades.                           ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Incident Scenario
```
╔═══════════════════════════════════════════════════════════════╗
║   SCENARIO: Social Media Platform — Multi-Database Incident   ║
╟───────────────────────────────────────────────────────────────╢
║                                                               ║
║   You're the on-call SRE for a social media platform.         ║
║   Stack:                                                      ║
║   → PostgreSQL: User accounts, friendships, auth              ║
║   → MongoDB: Posts, comments (document store)                 ║
║   → Cassandra: Activity feed, notifications (3-node cluster,  ║
║     replication factor 3, read/write at QUORUM)               ║
║   → Redis: Timeline cache, session storage,                   ║
║     rate limiting (Redis Cluster, 3 masters)                  ║
║   → Neo4j: Friend recommendations                             ║
║   → 50 application servers behind an ALB                      ║
║   → 2M daily active users                                     ║
║                                                               ║
║   ALERT TIMELINE:                                             ║
║                                                               ║
║   14:00 — Cassandra node 2 goes down (hardware failure).      ║
║           Cluster is now 2 nodes out of 3.                    ║
║                                                               ║
║   14:01 — Activity feed writes: latency spike from 5ms        ║
║           to 45ms but still succeeding.                       ║
║           Activity feed reads: some succeed, some fail with   ║
║           "ConsistencyLevel QUORUM not achieved,              ║
║            only 2 of 3 replicas responded"                    ║
║                                                               ║
║   14:03 — Redis: MEMORY usage at 92% of maxmemory.            ║
║           Eviction rate: 4,200 keys/second.                   ║
║           Cache hit rate dropped from 94% → 67%.              ║
║                                                               ║
║   14:05 — MongoDB: Read latency up 3x (from 12ms to 38ms).    ║
║           Write latency normal.                               ║
║           Connections to MongoDB: 1,847 (normally ~400).      ║
║                                                               ║
║   14:07 — PostgreSQL: Connection count: normal.               ║
║           Query latency: normal.                              ║
║           CPU: normal.                                        ║
║                                                               ║
║   14:08 — Neo4j: "Friend suggestions" feature returning     m ║
║           empty results for ~30% of users.                    ║
║           No errors in Neo4j logs. Query latency normal.      ║
║                                                               ║
║   14:10 — Application logs:                                   ║
║           "TimeoutError: Redis command timed out after 500ms" ║
║           Rate: 340/minute (normally 0)                       ║
║           All timeouts from Redis Cluster node 2 (master).    ║
║                                                               ║
║   14:12 — Customer complaints:                                ║
║           "My feed is empty"                                  ║
║           "I can't see friend suggestions"                    ║
║           "The app is slow"                                   ║
║           "I posted something but it disappeared"             ║
║                                                               ║
║   14:14 — Monitoring dashboard:                               ║
║           Redis node 2 INFO output:                           ║
║             used_memory: 14.1GB                               ║
║             maxmemory: 15GB                                   ║
║             maxmemory_policy: volatile-lru                    ║
║             evicted_keys (last 5 min): 21,000                 ║
║             expired_keys (last 5 min): 890                    ║
║             connected_clients: 12,400                         ║
║             blocked_clients: 247                              ║
║             instantaneous_ops_per_sec: 89,000                 ║
║             keyspace_hits: 340,000                            ║
║             keyspace_misses: 170,000                          ║
║                                                               ║
║           Cassandra nodetool status:                          ║
║             Node 1: UN (Up Normal) — owns 33.3%               ║
║             Node 2: DN (Down Normal) — owns 33.3%             ║
║             Node 3: UN (Up Normal) — owns 33.3%               ║
║                                                               ║
║           MongoDB rs.status():                                ║
║             Primary: healthy                                  ║
║             Secondary 1: healthy, lag 0.2s                    ║
║             Secondary 2: healthy, lag 0.1s                    ║
║                                                               ║
║   14:15 — Application metric:                                 ║
║           Feed rendering service: cache miss → falls back     ║
║           to Cassandra read → falls back to MongoDB read      ║
║           (full reconstruction from posts collection).        ║
║           This fallback path takes 180-400ms per request.     ║
║           Currently 34% of feed requests hitting this path.   ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝

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

## Targeted Reading
```
╔══════════════════════════════════════════════════════════════╗
║   READ AFTER THIS LESSON:                                    ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   DDIA Chapter 2: "Data Models and Query Languages"          ║
║   → Pages 27-42 (full chapter)                               ║
║   → Focus on: "Relational Model vs Document Model" section   ║
║   → Focus on: "Are Document Databases Repeating History?"    ║
║   → This connects directly to the SQL vs Document modeling   ║
║     comparison we covered                                    ║
║                                                              ║
║   DDIA Chapter 3: "Storage and Retrieval"                    ║
║   → Pages 69-79 (Hash indexes → SSTables → LSM-Trees)        ║
║     THIS explains the storage engine behind Cassandra.       ║
║     After reading, you'll understand WHY the write path      ║
║     (commit log → memtable → SSTable) is structured          ║
║     that way. It's the LSM-Tree architecture.                ║
║   → Pages 79-85 (B-Trees — you already know this from        ║
║     the SQL topic. Read to reinforce.)                       ║
║   → Pages 85-90 (Comparing B-Trees and LSM-Trees)            ║
║     KEY SECTION: This is the write-optimized vs              ║
║     read-optimized tradeoff in one comparison.               ║
║                                                              ║
║   TOTAL: ~35 pages. You already know the concepts.           ║
║   The book provides the theoretical foundation for WHY       ║
║   these storage engines make the tradeoffs they do.          ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Ops Sim: Northstar Polyglot Store Cascade

**Time box:** 35 minutes
**Severity:** P1
**Service / domain:** Cassandra inventory, Mongo seller content, Redis cache
**Northstar system:** Inventory (`inv-cas`), Session Redis, seller analytics

### Rules

1. Answer from memory; do not re-read the NoSQL taxonomy section mid-drill.
2. Write decisions in order (T+0 -> T+60).
3. Name the storage model evidence behind every claim.
4. Do not open the answer key until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  Inventory badges flicker between "sold out" and "3 left"; seller pages are slow.
  Checkout for affected SKUs sometimes refuses valid orders.

WHAT ON-CALL SEES:
  Cassandra `inv-cas` lost one node during a regional auction spike.
  Redis cache hit rate falls; MongoDB seller-content reads triple.

BUSINESS CONSTRAINT:
  Avoid oversells. It is acceptable to pessimistically show "checking stock" for
  affected SKUs while preserving checkout correctness.
```

### 2. Telemetry pack

```text
METRICS:
  Cassandra RF=3, CL reads=LOCAL_QUORUM, writes=LOCAL_QUORUM
  inv-cas node i-2 down; read timeout rate 0.1% -> 12%
  cassandra coordinator read latency p99 18ms -> 480ms
  Redis inventory cache hit rate 93% -> 58%; evictions 31k/5min
  Mongo seller-content connections 420 -> 1,980; p95 22ms -> 130ms
  checkout stock refusal false-positive alerts: 0 -> 240/min

LOG LINES:
  Cassandra: ReadTimeoutException received only 1 responses from 2 required
  inventory-api: fallback read from mongo_sku_snapshot stale_age=17m
  Redis: maxmemory_policy=volatile-lru evicted inventory:sku:* keys

TRACE:
  inventory-api -> Redis miss -> Cassandra LOCAL_QUORUM timeout -> Mongo snapshot fallback
```

### 3. Config pack

```yaml
cassandra:
  replication_factor: 3
  read_consistency: LOCAL_QUORUM
  write_consistency: LOCAL_QUORUM
  speculative_retry: "99PERCENTILE"
redis:
  maxmemory_policy: volatile-lru
  inventory_ttl_seconds: 60

# wrong/dangerous fallback
inventory_api:
  fallback_to_mongo_snapshot: true
  allow_checkout_on_snapshot: true
  snapshot_max_age_minutes: 30
```

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | P1: stock correctness alerts and Cassandra read timeouts. | |
| T+5 | Fallback path serves 17-minute-old Mongo snapshots. | |
| T+15 | Team proposes lowering Cassandra reads to CL=ONE for all inventory. | |
| T+60 | Cassandra node replacement is in progress; Redis still evicting. | |

### 5. Questions

**Q1 - Layer & root cause:** Which store is source of truth, which stores are derived, and where did the cascade start?

**Q2 - Evidence:** Which signals show Cassandra quorum trouble, Redis eviction, and unsafe Mongo fallback?

**Q3 - Sequencing:** What do you do first to protect checkout correctness?

**Q4 - Bad fix gallery:** Why is global CL=ONE dangerous? Why is allowing checkout on 30-minute snapshots dangerous?

**Q5 - Capacity / blast radius:** With RF=3 and LOCAL_QUORUM=2, why can reads fail when one node is down? What extra load does fallback place on Mongo?

**Q6 - Durable fix:** Which data-model and fallback-contract changes prevent recurrence?

**Q7 - Org / runbook:** Who is informed during this P1 and what user-facing degradation is allowed?

**Answer key:** [`../answers/Week-02-Storage-Fundamentals/NoSQL Taxonomy Answers.md`](../answers/Week-02-Storage-Fundamentals/NoSQL%20Taxonomy%20Answers.md)

---

## Key Takeaways
```
╔══════════════════════════════════════════════════════════════╗
║   5 THINGS TO REMEMBER IF YOU FORGET EVERYTHING ELSE         ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. NoSQL is not "better" than SQL. Each NoSQL type         ║
║      is OPTIMIZED for ONE access pattern at the cost         ║
║      of everything else. Choose based on your PRIMARY        ║
║      access pattern. If unsure, use PostgreSQL.              ║
║                                                              ║
║   2. Cassandra's write path (commit log → memtable →         ║
║      SSTable) is why it's write-optimized: sequential I/O,   ║
║      no read-before-write, no locks. Reads pay the price     ║
║      (multiple SSTable merges). This is the LSM-Tree         ║
║      tradeoff.                                               ║
║                                                              ║
║   3. Redis is single-threaded. One slow command blocks       ║
║      everything. ALWAYS configure maxmemory-policy           ║
║      (never noeviction for cache workloads). Provision 2x    ║
║      RAM for fork/snapshot safety.                           ║
║                                                              ║
║   4. Document databases (MongoDB) require the SAME           ║
║      discipline as SQL: define schemas in code, create       ║
║      indexes for query patterns, bound array growth.         ║
║      "Schemaless" doesn't mean "no rules."                   ║
║                                                              ║
║   5. Most production systems use POLYGLOT PERSISTENCE:       ║
║      multiple databases, each handling what it's best at.    ║
║      This means understanding failure cascades ACROSS        ║
║      databases is critical — one database failing can        ║
║      overload another through fallback paths.                ║
╚══════════════════════════════════════════════════════════════╝
```

---

Take your time with this scenario. Six questions this time — the cascade tracing (Q2) and the Cassandra QUORUM puzzle (Q3) are designed to test deep understanding. The Redis eviction question (Q4) and Neo4j question (Q5) test whether you can reason about non-obvious cross-system interactions.
> **Answer key (do not open until you attempt the scenario questions):**
> [`../answers/Week-02-Storage-Fundamentals/NoSQL%20Taxonomy%20Answers.md`](../answers/Week-02-Storage-Fundamentals/NoSQL%20Taxonomy%20Answers.md)
