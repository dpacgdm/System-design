--- START OF FILE Paste April 24, 2026 - 9:57PM ---

# Week 5, Topic 2: Database Scaling Patterns

---

## Learning Objectives

```text
After this topic, you will be able to:

1. Design a multi-tier connection pooling architecture 
   that survives flash sales, failovers, and connection 
   storms — with exact PgBouncer/ProxySQL configurations

2. Implement read/write splitting at the application 
   layer with replication-lag-aware routing, and know 
   exactly when it's safe vs. dangerous

3. Design application-level sharding with shard routing, 
   cross-shard queries, and shard rebalancing — and 
   explain why this is the hardest scaling pattern to 
   undo

4. Implement CQRS (Command Query Responsibility 
   Segregation) and explain why it's the architectural 
   pattern that makes all other scaling patterns compose

5. Choose between database-per-service, shared database, 
   and polyglot persistence for microservices — with 
   precise tradeoff analysis, not dogma

6. Diagnose database scaling bottlenecks using connection 
   metrics, query patterns, and capacity math — and 
   choose the RIGHT scaling pattern for the bottleneck
```

---

## Core Teaching

### Part 1: The Scaling Decision Framework

Before any pattern, you need to know **what bottleneck you're solving**. Every database scaling pattern addresses a specific constraint. Applying the wrong pattern wastes engineering time and creates new problems.

```text
THE FIVE DATABASE BOTTLENECKS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────────────────┬───────────────────────────────────┐
│ BOTTLENECK           │ PATTERN THAT SOLVES IT            │
├──────────────────────┼───────────────────────────────────┤
│ 1. CONNECTION LIMIT  │ Connection pooling                │
│    (too many clients │ (PgBouncer, ProxySQL, pgpool-II)  │
│    for max_connections)│                                 │
├──────────────────────┼───────────────────────────────────┤
│ 2. READ THROUGHPUT   │ Read replicas + read/write split  │
│    (CPU saturated on │ (application-level routing)       │
│    SELECT queries)   │                                   │
├──────────────────────┼───────────────────────────────────┤
│ 3. WRITE THROUGHPUT  │ Sharding / partitioning           │
│    (single writer    │ (Citus, Vitess, app-level shards) │
│    bottleneck)       │                                   │
├──────────────────────┼───────────────────────────────────┤
│ 4. DATA SIZE         │ Sharding / archival / tiering     │
│    (data exceeds     │ (range partitioning, cold storage)│
│    single-node disk/ │                                   │
│    memory)           │                                   │
├──────────────────────┼───────────────────────────────────┤
│ 5. QUERY COMPLEXITY  │ CQRS + materialized views         │
│    (reads and writes │ (separate read/write models)      │
│    need different    │                                   │
│    data models)      │                                   │
└──────────────────────┴───────────────────────────────────┘

THE CRITICAL RULE:

  Bottleneck 1 → Try pooling FIRST (days to implement)
  Bottleneck 2 → Try read replicas (weeks to implement)
  Bottleneck 3 → Try sharding (months to implement)
  Bottleneck 5 → Try CQRS (weeks to months)
  
  ALWAYS start with the cheapest pattern that addresses 
  the actual bottleneck. The number of teams that jump 
  straight to sharding when connection pooling would 
  have solved the problem is staggering.

  ┌──────────────────────────────────────────────────┐
  │ DIAGNOSTIC CHECKLIST:                            │
  │                                                  │
  │ □ Are connections exhausted?                     │
  │   → SHOW max_connections; vs active count        │
  │   → pg_stat_activity: many idle connections?     │
  │   → FIX: connection pooling                      │
  │                                                  │
  │ □ Is CPU saturated by reads?                     │
  │   → Top queries: pg_stat_statements              │
  │   → Read/write ratio: if >80% reads → replicas   │
  │   → FIX: read replicas + routing                 │
  │                                                  │
  │ □ Is CPU saturated by writes?                    │
  │   → WAL generation rate: pg_stat_wal             │
  │   → Write TPS at single-core limit?              │
  │   → FIX: sharding (only option for writes)       │
  │                                                  │
  │ □ Is disk full or index too large for memory?    │
  │   → Table sizes: pg_total_relation_size()        │
  │   → Index-to-memory ratio                        │
  │   → FIX: sharding or archival                    │
  │                                                  │
  │ □ Are queries too complex for a single model?    │
  │   → Analytics queries blocking OLTP?             │
  │   → Denormalized reads fighting normalized       │
  │     writes?                                      │
  │   → FIX: CQRS / materialized views               │
  └──────────────────────────────────────────────────┘
```

This framework connects directly to everything you've learned:
- Connection pooling: Week 2 T1 (PgBouncer), Week 4 T1 (flash sale PgBouncer saturation)
- Read replicas: Week 4 T1 (replication strategies), Week 4 retention (stale margin read)
- Sharding: Week 4 T2 (partitioning), Week 3 T3 (consistent hashing)
- CQRS: new pattern that *composes* with all the above

---

### Part 2: Connection Pooling — Deep Architecture

You know PgBouncer basics from Week 2. Now the full production architecture.

```text
WHY CONNECTION POOLING IS THE #1 SCALING PATTERN:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PostgreSQL forks a NEW OS PROCESS per connection.
Each process:
  → ~10MB RSS (resident memory)
  → Has its own PGPROC entry in shared memory
  → Competes for CPU scheduler time
  → Holds lightweight locks during transaction

PostgreSQL max_connections default: 100.
Setting it to 10,000 would consume ~100GB RAM in 
backend processes alone. And context-switching across 
10,000 processes destroys throughput.

THE PARADOX:
  → Modern apps have hundreds of microservice instances
  → Each instance wants 10-50 connections
  → 200 instances × 25 connections = 5,000 connections
  → PostgreSQL performs best at 2-4× CPU core count
  → A 16-core server: optimal at ~32-64 active queries
  → 5,000 connections with 64 optimal: 98.7% of 
    connections should be IDLE at any moment

CONNECTION POOLING solves this by multiplexing 
thousands of client connections onto dozens of 
server connections.
```

#### PgBouncer Deep Configuration

```text
PgBouncer ARCHITECTURE:
━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────────────────────────┐
  │                                                  │
  │  Microservice Instances (200 pods)               │
  │  ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐         │
  │  │ Pod 1 │ │ Pod 2 │ │ Pod 3 │ │ ...   │         │
  │  │ 25con │ │ 25con │ │ 25con │ │ 25con │         │
  │  └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘         │
  │      │         │         │         │             │
  │      └─────────┴────┬────┴─────────┘             │
  │                     │                            │
  │                     │ 5,000 client connections   │
  │                     ▼                            │
  │  ┌────────────────────────────────────────────┐  │
  │  │                 PgBouncer                  │  │
  │  │                                            │  │
  │  │  Client connections: 5,000                 │  │
  │  │  Server connections: 100                   │  │
  │  │                                            │  │
  │  │  Pool mode: transaction                    │  │
  │  │  (release server connection                │  │
  │  │   after each transaction)                  │  │
  │  └──────────────────┬─────────────────────────┘  │
  │                     │                            │
  │                     │ 100 server connections     │
  │                     ▼                            │
  │  ┌────────────────────────────────────────────┐  │
  │  │                PostgreSQL                  │  │
  │  │            max_connections: 120            │  │
  │  │          (100 pool + 20 reserved)          │  │
  │  └────────────────────────────────────────────┘  │
  │                                                  │
  └──────────────────────────────────────────────────┘

  MULTIPLEXING RATIO: 5,000 : 100 = 50:1
  98% of client connections are idle, waiting in 
  PgBouncer's queue. Only active transactions hold 
  a server connection.


PgBouncer POOL MODES:
━━━━━━━━━━━━━━━━━━━━

  ┌───────────────┬───────────────────────────────────────┐
  │ session       │ Server connection held for entire     │
  │               │ client session (connect → disconnect) │
  │               │ WORST multiplexing (1:1)              │
  │               │ USE: legacy apps needing session      │
  │               │ features (temp tables, SET vars)      │
  ├───────────────┼───────────────────────────────────────┤
  │ transaction   │ Server connection held for one        │
  │ (recommended) │ transaction (BEGIN → COMMIT/ROLLBACK) │
  │               │ Released between transactions         │
  │               │ BEST multiplexing for most apps       │
  │               │ LIMITATION: no cross-TX session state │
  │               │ (no LISTEN/NOTIFY, no SET, no         │
  │               │  prepared statements unless named,    │
  │               │  no temp tables)                      │
  ├───────────────┼───────────────────────────────────────┤
  │ statement     │ Server connection held for one        │
  │               │ statement only                        │
  │               │ MOST aggressive multiplexing          │
  │               │ BREAKS multi-statement transactions   │
  │               │ USE: only for autocommit workloads    │
  └───────────────┴───────────────────────────────────────┘


PgBouncer CONFIGURATION — PRODUCTION TEMPLATE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [databases]
  mydb = host=primary.internal port=5432 dbname=mydb

  [pgbouncer]
  ; Pool sizing
  default_pool_size = 25          ; server conns per user/db pair
  min_pool_size = 5               ; keep warm connections
  reserve_pool_size = 5           ; emergency overflow pool
  reserve_pool_timeout = 3        ; seconds before using reserve

  ; Client limits
  max_client_conn = 10000         ; total client connections
  max_db_connections = 100        ; total server connections per DB
  max_user_connections = 100      ; total server connections per user

  ; Timeouts
  server_idle_timeout = 300       ; close idle server conns after 5m
  client_idle_timeout = 0         ; don't close idle clients (app manages)
  server_connect_timeout = 3      ; fail fast if PG unreachable
  server_login_retry = 1          ; retry after 1s on connect failure
  query_timeout = 30              ; kill queries running > 30s
  query_wait_timeout = 120        ; max time client waits for server conn

  ; Mode
  pool_mode = transaction

  ; Connection handling
  server_reset_query = DISCARD ALL  ; clean state between clients
  server_check_query = SELECT 1     ; health check
  server_check_delay = 30           ; health check interval

  ; Logging
  log_connections = 0               ; disable per-conn logging (noisy)
  log_disconnections = 0
  stats_period = 60                 ; stats every 60s


CRITICAL SETTINGS EXPLAINED:

  max_db_connections vs default_pool_size:
  ─────────────────────────────────────────
  max_db_connections: HARD CEILING on server connections
    to PostgreSQL. This is the "never exceed" number.
    Set to: PostgreSQL max_connections - 
            superuser_reserved_connections - 
            replication connections - margin
    
    Example: max_connections=150, 
             superuser_reserved=5,
             replication=5
    → max_db_connections = 150 - 5 - 5 - 10 = 130
    
  default_pool_size: connections PER user/database PAIR.
    If you have 3 database users each connecting to 1 DB:
    → 3 × default_pool_size = total server connections
    → Must be ≤ max_db_connections / num_user_db_pairs

  reserve_pool:
  ─────────────
  When all default pool connections are in use AND 
  a client has waited > reserve_pool_timeout seconds:
  → PgBouncer opens connections from the reserve pool
  → This handles burst traffic without immediately 
    failing clients
  → But it means PostgreSQL sees more connections 
    than default_pool_size — ensure max_db_connections 
    accounts for this

  query_wait_timeout:
  ───────────────────
  If a client request can't get a server connection 
  within this many seconds, PgBouncer returns an error.
  This PREVENTS the queue from growing unboundedly.
  
  Set to: your application's HTTP request timeout 
  minus some margin. If your HTTP timeout is 30s, 
  set query_wait_timeout to 20s — no point waiting 
  longer than the client will wait.
```

#### Multi-Tier Pooling

For large deployments, a single PgBouncer becomes a bottleneck or single point of failure:

```text
MULTI-TIER POOLING ARCHITECTURE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌─────────────────────────────────────────────────┐
  │                                                 │
  │  TIER 1: Application-Side Pool (per pod)        │
  │                                                 │
  │  Each microservice pod has its own connection   │
  │  pool (HikariCP for Java, pgx pool for Go,      │
  │  asyncpg pool for Python).                      │
  │                                                 │
  │  Purpose: reuse connections within the pod,     │
  │  avoid TCP handshake per query.                 │
  │                                                 │
  │  Settings:                                      │
  │    minimumIdle: 2                               │
  │    maximumPoolSize: 10                          │
  │    connectionTimeout: 5000ms                    │
  │    idleTimeout: 300000ms                        │
  │    maxLifetime: 1800000ms (30 min — rotate to   │
  │      avoid PgBouncer idle disconnect)           │
  │                                                 │
  │  ┌───────┐ ┌───────┐ ┌───────┐                  │
  │  │ Pod 1 │ │ Pod 2 │ │ Pod 3 │                  │
  │  │pool:10│ │pool:10│ │pool:10│                  │
  │  └───┬───┘ └───┬───┘ └───┬───┘                  │
  │      │         │         │                      │
  │      └─────────┴────┬────┘                      │
  │                     │                           │
  │                     ▼                           │
  │  TIER 2: PgBouncer (centralized proxy)          │
  │                                                 │
  │  Multiplexes all pod connections onto a smaller │
  │  set of PostgreSQL connections.                 │
  │                                                 │
  │  Multiple PgBouncer instances behind a TCP LB   │
  │  (HAProxy or NLB) for HA.                       │
  │                                                 │
  │        ┌─────────────┐   ┌─────────────┐        │
  │        │ PgBouncer 1 │   │ PgBouncer 2 │        │
  │        │  pool: 50   │   │  pool: 50   │        │
  │        └──────┬──────┘   └──────┬──────┘        │
  │               │                 │               │
  │               └────────┬────────┘               │
  │                        │                        │
  │                        ▼                        │
  │  TIER 3: PostgreSQL                             │
  │  max_connections: 120                           │
  │  (50 + 50 from two PgBouncers + 20 reserved)    │
  │                                                 │
  └─────────────────────────────────────────────────┘

  MATH:
  200 pods × 10 connections/pod = 2,000 app connections
  → 2 PgBouncers × 50 server conns = 100 PG connections
  → Multiplexing ratio: 2,000:100 = 20:1
  → PostgreSQL sees 100 active connections (optimal 
    for 16-core server)

  WHY TWO TIERS OF POOLING:
  
  App pool (Tier 1): handles connection reuse within 
  a pod. Without this, each HTTP request would open 
  a new TCP connection to PgBouncer, adding ~1ms 
  per request.
  
  PgBouncer (Tier 2): handles multiplexing ACROSS 
  pods. Without this, 200 pods × 10 connections = 
  2,000 connections directly to PostgreSQL.
  
  BOTH are needed. App pool alone doesn't reduce 
  total connection count. PgBouncer alone adds TCP 
  overhead per query.
```

#### ProxySQL — The MySQL Equivalent + More

```text
ProxySQL (for MySQL/MariaDB):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ProxySQL provides everything PgBouncer does PLUS:
  → Query routing (read/write split at proxy level)
  → Query caching (in-proxy result caching)
  → Query rewriting (automatic regex-based rewrites)
  → Query firewall (block dangerous queries)
  → Multiple backend pools (primary + replicas)

For PostgreSQL: pgpool-II provides similar features 
but is heavier. PgBouncer + application-level routing 
is generally preferred over pgpool-II.

ProxySQL read/write split:
  
  mysql_servers:
    - hostgroup: 10   # writer
      hostname: primary.db
      port: 3306
      max_connections: 100
    - hostgroup: 20   # reader
      hostname: replica1.db
      port: 3306
      max_connections: 200
    - hostgroup: 20   # reader
      hostname: replica2.db
      port: 3306
      max_connections: 200

  mysql_query_rules:
    - match_pattern: "^SELECT.*FOR UPDATE"
      destination_hostgroup: 10   # writes!
    - match_pattern: "^SELECT"
      destination_hostgroup: 20   # reads
    - match_pattern: ".*"
      destination_hostgroup: 10   # default: writer
```

---

### Part 3: Read/Write Splitting — Application-Level Routing

This connects directly to Week 4 T1 (replication) and the Week 4 retention scenario (stale margin read). Read replicas scale reads, but routing decisions have consistency consequences.

```text
READ/WRITE SPLIT ARCHITECTURE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────────────────────────┐
  │  Application                                     │
  │  ┌────────────────────────────────────────────┐  │
  │  │  Read/Write Router                         │  │
  │  │                                            │  │
  │  │  WRITE:                                    │  │
  │  │  → INSERT, UPDATE, DELETE, SELECT FOR UPDATE│  │
  │  │  → Always go to PRIMARY                    │  │
  │  │                                            │  │
  │  │  READ:                                     │  │
  │  │  → SELECT (without FOR UPDATE)             │  │
  │  │  → Route based on CONSISTENCY REQUIREMENT  │  │
  │  │                                            │  │
  │  │  ┌─────────────────────────────────────┐   │  │
  │  │  │ Safety-critical read?               │   │  │
  │  │  │ (margin check, allergy check,       │   │  │
  │  │  │  balance verification, inventory    │   │  │
  │  │  │  check for purchase)                │   │  │
  │  │  │ → YES: PRIMARY                      │   │  │
  │  │  │                                     │   │  │
  │  │  │ Read-your-writes required?          │   │  │
  │  │  │ (user just edited, viewing own      │   │  │
  │  │  │  profile, order confirmation page)  │   │  │
  │  │  │ → YES: PRIMARY or LAG-BOUNDED       │   │  │
  │  │  │        REPLICA                      │   │  │
  │  │  │                                     │   │  │
  │  │  │ Eventual consistency acceptable?    │   │  │
  │  │  │ (dashboard, search results, feed,   │   │  │
  │  │  │  product catalog browsing)          │   │  │
  │  │  │ → YES: ANY REPLICA                  │   │  │
  │  │  └─────────────────────────────────────┘   │  │
  │  └────────────────────────────────────────────┘  │
  │         │              │              │          │
  │         ▼              ▼              ▼          │
  │    ┌─────────┐  ┌───────────┐  ┌───────────┐     │
  │    │ PRIMARY │  │ REPLICA 1 │  │ REPLICA 2 │     │
  │    │ (write) │  │ (read)    │  │ (read)    │     │
  │    └─────────┘  └───────────┘  └───────────┘     │
  └──────────────────────────────────────────────────┘


APPLICATION-LEVEL IMPLEMENTATION (pseudocode):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  class DatabaseRouter:
    def __init__(self):
      self.primary_pool = ConnectionPool("primary:5432")
      self.replica_pools =[
        ConnectionPool("replica1:5432"),
        ConnectionPool("replica2:5432"),
      ]
      self.recent_writes = {}  # user_id → write_timestamp
    
    def get_connection(self, query_type, user_id=None, 
                       consistency="eventual"):
      
      # ALL writes go to primary
      if query_type == "write":
        self.recent_writes[user_id] = now()
        return self.primary_pool.get()
      
      # Safety-critical reads: always primary
      if consistency == "strong":
        return self.primary_pool.get()
      
      # Read-your-writes: check if user recently wrote
      if consistency == "read-your-writes":
        last_write = self.recent_writes.get(user_id)
        if last_write and (now() - last_write) < 5_seconds:
          return self.primary_pool.get()
        # User hasn't written recently → replica is safe
      
      # Lag-bounded replica selection
      for pool in self.replica_pools:
        if pool.replication_lag() < MAX_ACCEPTABLE_LAG:
          return pool.get()
      
      # All replicas too laggy → fallback to primary
      return self.primary_pool.get()


REPLICATION LAG MONITORING FOR ROUTING:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PostgreSQL: check pg_stat_replication on the primary
  or pg_stat_wal_receiver on the replica.

  # On replica: seconds of replication lag
  SELECT CASE 
    WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn()
    THEN 0
    ELSE EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp())
  END AS replication_lag_seconds;

  # More precise: LSN-based lag (from primary)
  SELECT client_addr,
         pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) 
           AS replay_lag_bytes,
         replay_lag
  FROM pg_stat_replication;

  ROUTING THRESHOLDS:
  ┌────────────────────────┬───────────────────────────┐
  │ Lag < 1 second         │ Route reads normally      │
  │ Lag 1-5 seconds        │ Route non-critical reads  │
  │ Lag 5-30 seconds       │ Only eventual reads       │
  │ Lag > 30 seconds       │ Remove from pool entirely │
  └────────────────────────┴───────────────────────────┘

  HEALTH CHECK INTERVAL: every 1-5 seconds.
  Don't check per-query (adds latency). Cache the lag 
  value and refresh periodically.
```

#### The Read-Your-Writes Problem at Scale

```text
READ-YOUR-WRITES — THREE IMPLEMENTATIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  APPROACH 1: TIME-BASED PRIMARY WINDOW
  
  After a write, route all of that user's reads to the 
  primary for N seconds (e.g., 5 seconds).
  
  Pros: Simple. No replica coordination.
  Cons: Wastes primary capacity (user might only read 
        once after writing). N must be longer than 
        worst-case replication lag — but lag varies.
  
  Implementation: in-memory map of user_id → last_write_time.
  For stateless services: store in Redis or a cookie.

  
  APPROACH 2: LSN TRACKING (CAUSAL TOKEN)
  
  After a write, the primary returns its current WAL LSN.
  The application stores this LSN as a "causal token" 
  (in the session, cookie, or response header).
  
  On the next read, the application sends the causal token 
  to the read router. The router checks: has this replica 
  applied up to this LSN?
  
  # On replica:
  SELECT pg_last_wal_replay_lsn() >= '<causal_token_lsn>';
  
  If yes → route to this replica (it has the user's writes).
  If no → try another replica, or fall back to primary.
  
  Pros: PRECISE. No wasted primary reads. Works regardless 
        of how long replication takes.
  Cons: Requires passing causal tokens through the stack 
        (headers, session, etc.). More complex.
  
  This is how CockroachDB, Vitess, and advanced PG setups 
  implement read-your-writes.


  APPROACH 3: SESSION STICKINESS
  
  Pin a user's session to a specific replica. That replica 
  always serves their reads.
  
  Pros: Guarantees monotonic reads (no bouncing between 
        replicas at different lag levels).
  Cons: Does NOT guarantee read-your-writes (the pinned 
        replica may still lag behind the primary). Uneven 
        load distribution. Hot replicas.
  
  Session stickiness provides MONOTONIC READS only.
  It requires combination with Approach 1 or 2 for 
  read-your-writes.
```

---

### Part 4: Application-Level Sharding

This connects directly to Week 4 T2 (partitioning strategies). Now: how the **application** implements sharding when the database doesn't do it natively.

```text
WHEN TO SHARD:
━━━━━━━━━━━━━

  Sharding is the LAST RESORT for relational databases.

  Before sharding, try everything else:
  1. Query optimization (EXPLAIN ANALYZE, indexes)
  2. Connection pooling
  3. Read replicas (for read-heavy workloads)
  4. Vertical scaling (bigger hardware)
  5. Table partitioning (PostgreSQL native partitioning 
     — stays on one server but improves query performance 
     and maintenance)

  Shard when:
  → Write throughput exceeds a single server's capacity
  → Data size exceeds a single server's disk/memory
  → AND you've exhausted all simpler approaches

  COST OF SHARDING:
  → Cross-shard queries become expensive (scatter-gather)
  → Cross-shard transactions require 2PC or saga
  → Schema changes must be coordinated across shards
  → Resharding (adding/removing shards) is operationally 
    dangerous and slow
  → Application complexity increases dramatically
  → Operational complexity: N databases to monitor, 
    backup, upgrade, patch
  → THE MOST EXPENSIVE SCALING DECISION TO REVERSE


SHARDING ARCHITECTURE:
━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────────────────────────┐
  │  Application Layer                               │
  │  ┌────────────────────────────────────────────┐  │
  │  │  Shard Router                              │  │
  │  │                                            │  │
  │  │  Input: query + shard key                  │  │
  │  │  Logic: shard_id = route(shard_key)        │  │
  │  │  Output: connection to correct shard       │  │
  │  │                                            │  │
  │  │  Routing strategies:                       │  │
  │  │  → Hash: shard = hash(key) % num_shards    │  │
  │  │  → Range: shard = lookup(key_range_table)  │  │
  │  │  → Directory: shard = lookup(key → shard)  │  │
  │  └──────────┬──────────┬──────────┬───────────┘  │
  │             │          │          │              │
  │             ▼          ▼          ▼              │
  │  ┌─────────────┐ ┌──────────┐ ┌──────────┐       │
  │  │ Shard 0     │ │ Shard 1  │ │ Shard 2  │       │  
  │  │ users 0-N   │ │ users    │ │ users    │       │
  │  │ PG primary  │ │ N+1-2N   │ │ 2N+1-3N  │       │
  │  │ + replicas  │ │ PG + rep │ │ PG + rep │       │
  │  └─────────────┘ └──────────┘ └──────────┘       │
  └──────────────────────────────────────────────────┘


SHARD KEY SELECTION — THE MOST IMPORTANT DECISION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  The shard key determines which shard stores each row.
  Get it wrong → full data migration to fix.
  (Exactly Week 4 T2: "partition key = most important 
  distributed DB decision")

  GOOD SHARD KEY PROPERTIES:
  → High cardinality (many unique values → even distribution)
  → Aligned with access pattern (most queries include the key)
  → Stable (doesn't change — moving a row between shards 
    is extremely expensive)
  → Avoids hotspots (no "celebrity user" concentration)

  EXAMPLES:
  ┌──────────────┬────────────┬───────────────────────┐
  │ System       │ Shard Key  │ Reasoning             │
  ├──────────────┼────────────┼───────────────────────┤
  │ E-commerce   │ customer_id│ All orders, cart,     │
  │              │            │ profile on one shard  │
  ├──────────────┼────────────┼───────────────────────┤
  │ SaaS         │ tenant_id  │ Tenant isolation,     │
  │              │            │ all tenant data co-   │
  │              │            │ located               │
  ├──────────────┼────────────┼───────────────────────┤
  │ Social media │ user_id    │ User's posts, follows │
  │              │            │ on one shard          │
  ├──────────────┼────────────┼───────────────────────┤
  │ Time-series  │ device_id  │ Device's readings co- │
  │              │            │ located for queries   │
  ├──────────────┼────────────┼───────────────────────┤
  │ Gaming       │ game_id    │ All game state co-    │
  │              │            │ located for real-time │
  └──────────────┴────────────┴───────────────────────┘

  BAD SHARD KEYS:
  → order_id: unique per order, but querying "all orders 
    for customer X" requires scatter-gather across ALL shards
  → timestamp: all recent data on one shard (hotspot)
  → country: low cardinality, massive skew (US shard = 50×
    Luxembourg shard)
```

#### Sharding Middleware: Vitess and Citus

```text
VITESS (MySQL sharding middleware):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────────────────────┐
  │  Application                                 │
  │       │                                      │
  │       ▼                                      │
  │  VTGate (proxy — looks like a MySQL server)  │
  │  │  Parses queries                           │
  │  │  Routes to correct shard(s)               │
  │  │  Aggregates cross-shard results           │
  │  │  Handles scatter-gather                   │
  │       │          │          │                │
  │       ▼          ▼          ▼                │
  │  VTTablet    VTTablet    VTTablet            │
  │  (Shard 0)   (Shard 1)   (Shard 2)           │
  │  │            │            │                 │
  │  ▼            ▼            ▼                 │
  │  MySQL       MySQL       MySQL               │
  └──────────────────────────────────────────────┘

  VTGate: application connects here. Queries look 
  like normal MySQL queries. Vitess handles routing.
  
  VTTablet: per-shard proxy. Manages connection pooling, 
  query rewriting, health checking for each MySQL instance.
  
  Topology Service: etcd or ZooKeeper stores shard map.
  
  Used by: YouTube, Slack, HubSpot, Square.
  
  KEY FEATURE: Online resharding. Vitess can split 
  or merge shards with zero downtime using a copy + 
  switch approach (like the Redis Cluster reshard 
  from Week 3 T3, but automated).


CITUS (PostgreSQL sharding extension):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────────────────────┐
  │  Application                                 │
  │       │                                      │
  │       ▼                                      │
  │  Citus Coordinator                           │
  │  (regular PostgreSQL + Citus extension)      │
  │  │  Receives queries                         │
  │  │  Plans distributed execution              │
  │  │  Routes to workers                        │
  │  │  Aggregates results                       │
  │       │          │          │                │
  │       ▼          ▼          ▼                │
  │  Worker 0    Worker 1    Worker 2            │
  │  (PG+Citus)  (PG+Citus)  (PG+Citus)          │
  │  Shards:     Shards:     Shards:             │
  │  0,3,6       1,4,7       2,5,8               │
  └──────────────────────────────────────────────┘

  Citus distributes tables across workers:
  
  SELECT create_distributed_table('orders', 'customer_id');
  
  → Hashes customer_id to assign rows to shards
  → Shards distributed across worker nodes
  → Queries with customer_id in WHERE: routed to one shard
  → Queries without customer_id: scatter-gather

  CO-LOCATION: tables sharded on the same key are 
  co-located on the same worker:
  
  SELECT create_distributed_table('orders', 'customer_id');
  SELECT create_distributed_table('order_items', 'customer_id');
  
  → A JOIN between orders and order_items for one customer 
    is a LOCAL join on one worker (no network)
  → A JOIN without customer_id filter: distributed join 
    across all workers (expensive)

  REFERENCE TABLES: small tables replicated to all workers:
  
  SELECT create_reference_table('countries');
  
  → Full copy on every worker
  → JOINs with reference tables are always local
  → Use for: lookup tables, configs, small dimensions
```

#### Cross-Shard Operations

```text
THE FUNDAMENTAL SHARDING PROBLEM:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Once data is sharded, any operation that spans 
  multiple shards is expensive and complex.

  CROSS-SHARD QUERIES:
  ────────────────────
  
  SELECT COUNT(*) FROM orders WHERE status = 'pending';
  
  If sharded by customer_id, "status" is on ALL shards.
  → Scatter to all N shards
  → Each shard counts locally
  → Coordinator aggregates
  → Latency = max(shard latencies) (tail-at-scale)
  → With 16 shards: p99 of one shard becomes EXPECTED
  
  SELECT * FROM orders 
  WHERE customer_id = 42 
  ORDER BY created_at DESC LIMIT 10;
  
  Sharded by customer_id → single-shard query.
  → Direct route to one shard. Fast.
  
  THE RULE: Design your shard key so that 90%+ of 
  queries include the shard key. The remaining 10% 
  must tolerate scatter-gather latency.


  CROSS-SHARD TRANSACTIONS:
  ─────────────────────────
  
  Transfer $100 from user A (shard 0) to user B (shard 1):
  
  This requires an ATOMIC operation across two shards.
  Three approaches:

  1. TWO-PHASE COMMIT (2PC):
     ┌────────────────────────────────────────┐
     │ Coordinator:                           │
     │   Phase 1 (Prepare):                   │
     │     → Shard 0: PREPARE debit $100      │
     │     → Shard 1: PREPARE credit $100     │
     │     → Both respond: PREPARED           │
     │   Phase 2 (Commit):                    │
     │     → Shard 0: COMMIT                  │
     │     → Shard 1: COMMIT                  │
     │                                        │
     │ PROBLEM: If coordinator crashes between│
     │ Phase 1 and Phase 2: both shards are   │
     │ LOCKED (holding row locks, waiting for │
     │ coordinator). This can last minutes to │
     │ hours until manual recovery.           │
     │                                        │
     │ PostgreSQL supports 2PC natively:      │
     │ PREPARE TRANSACTION 'txn_id';          │
     │ COMMIT PREPARED 'txn_id';              │
     │                                        │
     │ Used by: Citus (for cross-shard writes)│
     └────────────────────────────────────────┘

  2. SAGA PATTERN (eventual consistency):
     ┌────────────────────────────────────────┐
     │ Step 1: Debit $100 from user A(shard 0)│
     │   → Local transaction, committed       │
     │   → Publish event: "debited A $100"    │
     │                                        │
     │ Step 2: Credit $100 to user B(shard 1) │
     │   → Local transaction, committed       │
     │   → Publish event: "credited B $100"   │
     │                                        │
     │ If Step 2 FAILS:                       │
     │   → Compensating transaction:          │
     │     Credit $100 BACK to user A(shard 0)│
     │   → Publish: "transfer reversed"       │
     │                                        │
     │ PROPERTIES:                            │
     │ → No distributed locks held            │
     │ → Each step is a local transaction     │
     │ → Eventually consistent (brief window  │
     │   where A is debited but B not credited)│
     │ → Compensating actions MUST be         │
     │   idempotent                           │
     │                                        │
     │ Used by: most microservice setups      │
     │ Connects to: Week 6 (saga pattern deep │
     │ dive, event-driven architecture)       │
     └────────────────────────────────────────┘

  3. CO-LOCATION (avoid cross-shard entirely):
     ┌────────────────────────────────────────┐
     │ Design the shard key so that related   │
     │ data lives on the SAME shard.          │
     │                                        │
     │ Example: instead of sharding by user_id,│
     │ shard by "transfer_group_id" — both    │
     │ sides of a transfer share a group.     │
     │                                        │
     │ This is often IMPOSSIBLE for arbitrary │
     │ cross-entity operations (any user can  │
     │ transfer to any other user).           │
     │                                        │
     │ But it works well for HIERARCHICAL data:│
     │ → SaaS: all tenant data on one shard   │
     │ → E-commerce: customer + their orders  │
     │ → Gaming: all game state on one shard  │
     └────────────────────────────────────────┘
```

---

### Part 5: CQRS — Command Query Responsibility Segregation

CQRS is the architectural pattern that makes all other scaling patterns **compose**. It's the bridge between normalized write models and denormalized read models.

```text
THE PROBLEM CQRS SOLVES:
━━━━━━━━━━━━━━━━━━━━━━━━

  In a traditional application:
  
  SAME DATABASE serves both:
  → WRITES (normalized, 3NF, optimized for consistency)
  → READS (need joins, aggregations, denormalized views)
  
  Tension:
  → Writes want normalized tables (no update anomalies)
  → Reads want denormalized views (no expensive JOINs)
  → Heavy analytics queries compete with OLTP writes 
    for CPU, I/O, and locks
  → Index requirements conflict: writes want fewer 
    indexes (faster inserts), reads want more indexes 
    (faster selects)
  → You can't optimize for both simultaneously on 
    one database

  EXAMPLE: E-commerce product page
  → Write model: orders (normalized)
    ├── orders (order_id, customer_id, status, total)
    ├── order_items (item_id, order_id, product_id, qty)
    ├── products (product_id, name, price, inventory)
    └── customers (customer_id, name, email)
  
  → Read model: product page (denormalized)
    → Product name, price, inventory count
    → Average rating (from reviews table)
    → "Frequently bought together" (from order_items)
    → "X in stock" (from inventory across warehouses)
    → All of this in ONE read, not 5 JOINs


CQRS ARCHITECTURE:
━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────────────────────────┐
  │                                                  │
  │  COMMAND SIDE (Writes)      QUERY SIDE (Reads)   │
  │                                                  │
  │  ┌──────────────┐          ┌──────────────────┐  │
  │  │ Command      │          │ Query            │  │
  │  │ Handlers     │          │ Handlers         │  │
  │  │ (validate,   │          │ (simple lookups  │  │
  │  │  enforce     │          │  on pre-built    │  │
  │  │  business    │          │  read models)    │  │
  │  │  rules)      │          │                  │  │
  │  └──────┬───────┘          └───────┬──────────┘  │
  │         │                          │             │
  │         ▼                          ▼             │
  │  ┌──────────────┐          ┌──────────────────┐  │
  │  │ Write DB     │          │ Read Store(s)    │  │
  │  │ (PostgreSQL  │ ──CDC──→ │ (Elasticsearch,  │  │
  │  │  normalized) │          │  Redis, Mongo,   │  │
  │  │              │          │  denormalized    │  │
  │  │              │          │  PostgreSQL      │  │
  │  │              │          │  materialized    │  │
  │  │              │          │  views)          │  │
  │  └──────────────┘          └──────────────────┘  │
  │                                                  │
  │  WRITE MODEL:               READ MODEL:          │
  │  → Normalized (3NF)         → Denormalized       │
  │  → Optimized for            → Optimized for      │
  │    consistency                specific queries   │
  │  → Minimal indexes          → Heavy indexes      │
  │  → Source of truth          → Derived (can be    │
  │                               rebuilt from write │
  │                               model at any time) │
  │                                                  │
  └──────────────────────────────────────────────────┘


HOW DATA FLOWS — THE CDC BRIDGE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Write to PostgreSQL 
    │
    ▼
  WAL (Write-Ahead Log)
    │
    ▼
  Debezium CDC connector (reads WAL)
    │
    ▼
  Kafka topic: "orders.changes"
    │
    ├──→ Consumer 1: Update Elasticsearch 
    │    (for search/analytics)
    │
    ├──→ Consumer 2: Update Redis cache
    │    (for product page read model)
    │
    ├──→ Consumer 3: Update materialized views
    │    (for dashboard aggregations)
    │
    └──→ Consumer 4: Update recommendation engine
         (for "frequently bought together")

  EACH CONSUMER builds its own READ MODEL optimized 
  for its specific query pattern.

  The write DB is the SOURCE OF TRUTH.
  Read models are DERIVED and EVENTUALLY CONSISTENT.
  Read models can be REBUILT at any time from the 
  write DB (or by replaying Kafka from the beginning).

  THIS IS THE KEY INSIGHT:
  Read models are DISPOSABLE. If one gets corrupted, 
  rebuild it. The write model is the only thing that 
  must be protected.
```

#### CQRS + Event Sourcing (Brief Introduction)

```text
EVENT SOURCING (advanced — full coverage in Week 6):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Instead of storing CURRENT STATE in the write DB,
  store EVENTS (immutable facts):

  Traditional:
    orders table: {id: 1, status: "shipped", total: $99}
    → Current state. History lost.

  Event sourced:
    events table:
    {order_id: 1, event: "OrderCreated", total: $99}
    {order_id: 1, event: "PaymentReceived", amount: $99}
    {order_id: 1, event: "ItemShipped", tracking: "XYZ"}
    → Full history. Current state derived by replaying events.

  CQRS + Event Sourcing:
  → Write side: append events to event log
  → Read side: project events into read models
  → Read models can compute ANY view of the data by 
    replaying events (total flexibility)
  → Audit trail is built-in (every change is an event)

  Used by: financial systems (ledgers), banking, 
  compliance-heavy domains. Connects forward to 
  Week 6 (event-driven architecture).
```

#### Materialized Views — The Lightweight CQRS

```text
MATERIALIZED VIEWS (PostgreSQL):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  If full CQRS is too heavyweight, PostgreSQL 
  materialized views provide a simpler read model:

  CREATE MATERIALIZED VIEW product_dashboard AS
  SELECT 
    p.product_id,
    p.name,
    p.price,
    COUNT(r.review_id) AS review_count,
    AVG(r.rating) AS avg_rating,
    SUM(i.quantity) AS total_inventory
  FROM products p
  LEFT JOIN reviews r ON r.product_id = p.product_id
  LEFT JOIN inventory i ON i.product_id = p.product_id
  GROUP BY p.product_id, p.name, p.price;

  -- Refresh periodically:
  REFRESH MATERIALIZED VIEW CONCURRENTLY product_dashboard;
  -- CONCURRENTLY allows reads during refresh (requires 
  -- unique index on the matview)

  PROPERTIES:
  → Stored as a real table (fast reads, no JOINs at query time)
  → Stale until refreshed (not real-time)
  → CONCURRENTLY refresh: no lock on readers, but slower refresh
  → Non-concurrent refresh: exclusive lock (blocks reads)
  → No automatic refresh — must be triggered (cron, CDC, or app)

  WHEN TO USE:
  → Dashboard queries that tolerate 1-60 second staleness
  → Aggregate queries (COUNT, AVG, SUM) that are expensive 
    to compute per-request
  → When full CQRS (CDC + separate store) is overkill

  WHEN NOT TO USE:
  → Real-time requirements (use CDC-based read model instead)
  → Write-heavy data (refresh costs dominate)
  → Very large datasets (refresh scans entire source tables)

  REFRESH STRATEGIES:
  ┌────────────────┬───────────────────────────────────┐
  │ Cron schedule  │ REFRESH every N minutes. Simple.  │
  │                │ Staleness = N minutes worst case. │
  ├────────────────┼───────────────────────────────────┤
  │ Trigger-based  │ PG trigger on write tables fires  │
  │                │ REFRESH. Real-time but expensive  │
  │                │ if writes are frequent.           │
  ├────────────────┼───────────────────────────────────┤
  │ CDC-driven     │ Debezium detects changes, consumer│
  │                │ calls REFRESH. Near-real-time,    │
  │                │ decoupled from write path.        │
  └────────────────┴───────────────────────────────────┘
```

---

### Part 6: Database-Per-Service vs. Shared Database

```text
THE MICROSERVICE DATABASE QUESTION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Microservices architecture raises a fundamental 
  question: should each service own its database, 
  or should services share a database?

  ┌─────────────────────────────────────────────────┐
  │  SHARED DATABASE                                │
  │                                                 │
  │  Service A ──┐                                  │
  │  Service B ──┼──→ PostgreSQL (shared)           │
  │  Service C ──┘                                  │
  │                                                 │
  │  ✓ Simple cross-service queries (JOINs)         │
  │  ✓ ACID transactions across services            │
  │  ✓ Single backup/restore                        │
  │  ✓ Lower operational cost                       │
  │                                                 │
  │  ✗ Schema coupling (Service A's migration can   │
  │    break Service B)                             │
  │  ✗ Scaling coupling (one service's load affects │
  │    all others)                                  │
  │  ✗ Deployment coupling (can't upgrade services  │
  │    independently)                               │
  │  ✗ Technology coupling (all services must use   │
  │    the same DB)                                 │
  │                                                 │
  ├─────────────────────────────────────────────────┤
  │  DATABASE-PER-SERVICE                           │
  │                                                 │
  │  Service A ──→ PostgreSQL A                     │
  │  Service B ──→ PostgreSQL B                     │
  │  Service C ──→ MongoDB C                        │
  │                                                 │
  │  ✓ Independent scaling per service              │
  │  ✓ Independent schema evolution                 │
  │  ✓ Technology freedom (polyglot persistence)    │
  │  ✓ Blast radius isolation                       │
  │  ✓ Independent deployment                       │
  │                                                 │
  │  ✗ Cross-service queries: scatter-gather or API │
  │  ✗ Cross-service transactions: saga pattern     │
  │  ✗ Data duplication (services cache each other's│
  │    data)                                        │
  │  ✗ N databases to operate (N× backup, monitoring│
  │    patching, on-call)                           │
  │  ✗ Data consistency: eventually consistent across│
  │    services                                     │
  │                                                 │
  └─────────────────────────────────────────────────┘


THE PRAGMATIC MIDDLE GROUND:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Don't be dogmatic. Use the right pattern per boundary.

  SCHEMA-PER-SERVICE (shared instance, separate schemas):
  
  ┌──────────────────────────────────────────────────┐
  │                                                  │
  │  PostgreSQL Instance                             │
  │  ┌────────────┐ ┌────────────┐ ┌────────────┐    │
  │  │ Schema:    │ │ Schema:    │ │ Schema:    │    │
  │  │ orders     │ │ inventory  │ │ users      │    │
  │  │            │ │            │ │            │    │
  │  │ (Service A │ │ (Service B │ │ (Service C │    │
  │  │  only)     │ │  only)     │ │  only)     │    │
  │  └────────────┘ └────────────┘ └────────────┘    │
  │                                                  │
  │  RULE: Each service only accesses its own schema.│
  │  Cross-service access goes through APIs, not SQL.│
  │                                                  │
  └──────────────────────────────────────────────────┘

  BENEFITS:
  → Schema isolation (Service A can't accidentally 
    reference Service B's tables)
  → Shared connection pool (one PgBouncer)
  → Single backup and point-in-time recovery
  → Can evolve to separate instances later 
    (pg_dump schema A → new instance)
  → Lower ops cost than N separate databases

  TRADE-OFFS:
  → Still shares CPU, memory, disk I/O
  → One service's bad query can affect others
  → One database's failure affects all services
  → Can't use different database technologies

  WHEN TO CHOOSE:
  → Schema-per-service: start here. Good for teams 
    < 20 engineers, < 10 services.
  → Database-per-service: when you need independent 
    scaling, technology freedom, or blast radius 
    isolation. For large orgs with dedicated DB teams.
  → Shared database: only for tightly coupled services 
    that TRULY share a domain (e.g., order + order_items 
    are one bounded context, not two services).
```

#### Polyglot Persistence

```text
POLYGLOT PERSISTENCE:
━━━━━━━━━━━━━━━━━━━━

  Use the RIGHT database for each service's access pattern.

  ┌──────────────────────────────────────────────────┐
  │                                                  │
  │  User Service                                    │
  │  → PostgreSQL (structured data, ACID, relations) │
  │                                                  │
  │  Product Catalog                                 │
  │  → MongoDB (flexible schema, nested docs)        │
  │                                                  │
  │  Search Service                                  │
  │  → Elasticsearch (full-text, inverted index)     │
  │                                                  │
  │  Session Store                                   │
  │  → Redis (sub-ms latency, TTL expiry)            │
  │                                                  │
  │  Activity Feed                                   │
  │  → Cassandra (write-heavy, time-series)          │
  │                                                  │
  │  Recommendation Engine                           │
  │  → Neo4j (graph relationships)                   │
  │                                                  │
  │  Analytics                                       │
  │  → ClickHouse (columnar, aggregations)           │
  │                                                  │
  └──────────────────────────────────────────────────┘

  HOW DATA FLOWS BETWEEN SERVICES:
  
  Service A writes to PostgreSQL
    │
    ▼ (CDC via Debezium → Kafka)
    │
    ├──→ Service B consumes event, writes to MongoDB
    ├──→ Search Service indexes to Elasticsearch
    ├──→ Analytics Service writes to ClickHouse
    └──→ Recommendation Engine updates Neo4j graph

  KAFKA IS THE CENTRAL NERVOUS SYSTEM.
  CDC bridges the polyglot world. Each service 
  consumes events and builds its own data store 
  in its own format. This is CQRS at the 
  organizational level.

  OPERATIONAL COST:
  → 7 different database technologies = 7 different:
    - Backup strategies
    - Monitoring dashboards
    - Failure modes
    - Upgrade procedures
    - On-call expertise requirements
  → Don't go polyglot unless you have the team to 
    operate it. Start with PostgreSQL for everything, 
    extract only when a specific bottleneck demands 
    a specialized store.
```

---

### Part 7: Putting It All Together — The Scaling Ladder

```text
THE DATABASE SCALING LADDER:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  Each rung solves the bottleneck revealed by the 
  previous rung. Climb only as high as needed.

  ┌────────────────────────────────────────────────┐
  │                                                │
  │  Rung 0: SINGLE DATABASE                       │
  │  PostgreSQL, one server, maybe 10K QPS         │
  │  Bottleneck: connections or query optimization │
  │                                                │
  │  ↓ (connection limit hit)                      │
  │                                                │
  │  Rung 1: CONNECTION POOLING                    │
  │  Add PgBouncer. 10K → 50K QPS.                 │
  │  Cost: 1 day. Zero app changes.                │
  │  Bottleneck: read throughput (CPU saturated)   │
  │                                                │
  │  ↓ (CPU maxed on reads)                        │
  │                                                │
  │  Rung 2: READ REPLICAS                         │
  │  Add 2-3 
```
