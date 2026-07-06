# Design WhatsApp

## 1. Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS MODULE, YOU WILL BE ABLE TO:                      ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Design a real-time messaging system for 2B+ users         ║
║      with correct fan-out strategy (write vs read path)        ║
║      based on group size and message type                      ║
║                                                                ║
║   2. Explain the full message lifecycle: client send →         ║
║      gateway → storage → fan-out → delivery → receipts,        ║
║      including idempotency and ordering guarantees             ║
║                                                                ║
║   3. Choose and justify message storage (Cassandra /           ║
║      DynamoDB / Keyspaces) with partition key = chat_id,       ║
║      clustering key = message timestamp, and tombstone         ║
║      strategy for deletes                                      ║
║                                                                ║
║   4. Design presence, typing indicators, and delivery          ║
║      receipts at scale without melting Redis or the            ║
║      WebSocket layer                                           ║
║                                                                ║
║   5. Explain E2E encryption (Signal Protocol overview)         ║
║      and why it constrains server-side search, backup,         ║
║      and multi-device sync architecture                        ║
║                                                                ║
║   6. Size WebSocket connection pools, Kafka partitions,        ║
║      and Cassandra nodes using production-grade capacity       ║
║      math — not interview hand-waving                          ║
║                                                                ║
║   7. Map the design to AWS (NLB, MSK, Keyspaces, ElastiCache,  ║
║      S3, CloudFront) and diagnose a multi-symptom              ║
║      messaging outage like a principal engineer                ║
╚════════════════════════════════════════════════════════════════╝
```

---

## 2. Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Store messages in PostgreSQL"                    ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG for WhatsApp scale. A single chat is a write-heavy           ║
║   time-series stream. PostgreSQL can handle chat for a               ║
║   startup; at 2B users × 50B messages/day, you need                  ║
║   partition-first storage (Cassandra/DynamoDB) where                 ║
║   chat_id is the partition key and all messages for one              ║
║   chat co-locate on one node. SQL is fine for user                   ║
║   profiles and billing — not the hot message path.                   ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Fan-out on write for everything"                 ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Fan-out on write means: when Alice sends to a               ║
║   500-person group, write 500 inbox rows immediately.                ║
║   Works for 1:1 and small groups (≤256 members).                     ║
║   Breaks for broadcast channels (millions of followers).             ║
║   WhatsApp uses HYBRID: write fan-out for small chats,               ║
║   read fan-out (pull on open) for large groups and                   ║
║   status broadcasts.                                                 ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "WebSockets = the database"                       ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. WebSockets are the DELIVERY RAIL — ephemeral                ║
║   pipes from server to online clients. Messages MUST be              ║
║   persisted BEFORE fan-out. If the recipient is offline,             ║
║   the message lives in storage until they reconnect and              ║
║   pull/sync. Never assume a live connection exists.                  ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "E2E encryption is just TLS"                      ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. TLS encrypts client↔server. E2E (Signal Protocol)           ║
║   encrypts client↔client — the server stores ciphertext              ║
║   blobs it cannot read. This eliminates server-side search,          ║
║   content moderation without client cooperation, and                 ║
║   changes backup/multi-device key distribution fundamentally.        ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Presence is cheap — just use Redis SET"          ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG at 500M concurrent connections. Naive presence =             ║
║   one Redis key per user × heartbeat every 30s = write               ║
║   storm. Production presence uses: connection registry               ║
║   on the gateway itself, lazy presence (compute on query),           ║
║   bloom-filter approximations, and TTL with graceful                 ║
║   degradation to "last seen" timestamps.                             ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Delivery receipt = one database update"          ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. A group message to 256 members generates up to              ║
║   256 delivery receipts × read receipts × typing events.             ║
║   Treat receipts as a SEPARATE, lower-priority event stream          ║
║   (Kafka topic) with aggregation — not synchronous writes            ║
║   on the critical message path.                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #7: "One Kafka topic for all messages"                ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Partition by chat_id (or recipient_id hash) so              ║
║   ordering within a conversation is preserved per                    ║
║   partition. A single partition becomes a hot spot for               ║
║   celebrity group chats — use keyed partitioning +                   ║
║   separate topics for fan-out workers vs receipt workers.            ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## 3. Core Teaching

### 3.1 Problem Framing — What Are We Building?

```
WHATSAPP AT A GLANCE (production-scale reference points):

  Users:           ~2 billion monthly active
  Messages/day:    ~100 billion (order of magnitude)
  Peak concurrent: ~500 million connections (estimated)
  Group size:      up to 1,024 members (2023+)
  Media:           photos, video, voice notes, documents
  E2E encryption:  default for all 1:1 and group chats
  Multi-device:    phone + web + tablet linked to one account

FUNCTIONAL REQUIREMENTS:

  FR-1:  Send/receive text messages in 1:1 and group chats
  FR-2:  Send/receive media (image, video, audio, document)
  FR-3:  Delivery receipts (single check = server received,
         double check = delivered to device, blue = read)
  FR-4:  Online/last-seen presence (user-configurable privacy)
  FR-5:  Typing indicators
  FR-6:  Message ordering within a chat (per-device clock skew)
  FR-7:  Offline message delivery on reconnect
  FR-8:  Multi-device sync (same account, multiple endpoints)
  FR-9:  E2E encryption — server cannot read message content
  FR-10: Group admin, invite links, member management
  FR-11: Voice/video calls (out of scope for message path,
         but shares connection infrastructure)

NON-FUNCTIONAL REQUIREMENTS:

  NFR-1:  Message delivery latency p99 < 500ms (online recipient)
  NFR-2:  Availability 99.99% for message send/receive
  NFR-3:  Durability: no acknowledged message loss (RPO ≈ 0)
  NFR-4:  Support 100B+ messages/day write throughput
  NFR-5:  Horizontal scale — no single bottleneck node
  NFR-6:  Privacy: E2E default; metadata minimization
  NFR-7:  Multi-region: users globally, data locality laws
  NFR-8:  Cost-efficient at billions of messages/day
```

### 3.2 Capacity Estimation — The Math You Must Show

```
ASSUMPTIONS (interview + production planning):

  DAU:                    1 billion (50% of MAU)
  Messages per DAU/day:   50 messages sent (mix 1:1 + groups)
  Total sends/day:        50 billion
  Sends per second avg:   50B / 86,400 ≈ 580,000 msg/sec
  Peak factor:            3× average (timezone overlap, evenings)
  Peak send rate:         ~1.75 million msg/sec

READ TRAFFIC (fan-out multiplier):

  Average recipients per message:
    → 70% are 1:1 (1 recipient) = 0.7 × 1 = 0.7
    → 25% are small groups (avg 8 members) = 0.25 × 8 = 2.0
    → 5% are large groups (avg 100 members) = 0.05 × 100 = 5.0
    → Weighted avg recipients: ~7.7 recipients/message

  Fan-out writes (for write-fan-out path):
    50B sends × 7.7 recipients ≈ 385 billion inbox writes/day
    ≈ 4.5 million inbox writes/sec average
    ≈ 13.5 million inbox writes/sec peak

  NOTE: Large groups switch to read-fan-out — reduces writes
  dramatically. Without hybrid strategy, write fan-out alone
  would be unsustainable.

STORAGE GROWTH:

  Average message size (encrypted payload + metadata): 500 bytes
  Daily storage: 50B × 500B = 25 TB/day raw
  With RF=3 replication: 75 TB/day
  Annual: ~27 PB replicated (before compaction/tombstone GC)

  Media is separate (S3): avg 200 KB per media message,
  ~30% of messages have media → 15B × 200KB = 3 PB/day media
  (deduplicated by hash — same image forwarded ≠ new upload)

CONNECTION COUNT:

  500M concurrent connections (peak)
  Connections per server (tuned, Week 1 WebSockets module):
    → Conservative: 100K per gateway node
    → Aggressive (Erlang/Go): 500K-1M per node
  Gateway fleet at 100K/server: 5,000 gateway instances
  Gateway fleet at 500K/server: 1,000 gateway instances

BANDWIDTH (gateway egress):

  Avg push notification payload: 200 bytes (metadata only,
  E2E ciphertext delivered over WS)
  1.75M msg/sec × 200B × 7.7 recipients ≈ 2.7 GB/sec egress
  (only to ONLINE recipients; offline stored, not pushed)

  Per gateway (5000 nodes): ~550 MB/sec — manageable with
  10 Gbps NICs if fan-out is regionalized
```

### 3.3 High-Level Architecture

```
+------------------------------------------------------------------+
|                        CLIENT LAYER                               |
|  Mobile (iOS/Android)  |  Web (WhatsApp Web)  |  Desktop         |
|  Signal Protocol E2E   |  QR-linked session   |  linked device   |
+------------------------------------------------------------------+
          |                    |                      |
          |  HTTPS (REST)      |  WSS (WebSocket)     |
          v                    v                      v
+------------------------------------------------------------------+
|                     EDGE / LOAD BALANCER LAYER                    |
|  Route 53 (latency-based DNS) → Regional NLB (WebSocket, 350s)   |
|  Regional ALB (HTTP API: profile, media upload, registration)   |
|  AWS WAF + Shield (DDoS)                                          |
+------------------------------------------------------------------+
          |
          v
+------------------------------------------------------------------+
|                     CONNECTION GATEWAY LAYER                      |
|  Stateful WebSocket servers (Go/Erlang/custom)                    |
|  - Maintain connection registry: user_id → {device_id, conn}      |
|  - Heartbeat ping/pong (30s), idle timeout aligned with NLB       |
|  - Push inbound messages to connected devices                     |
|  - NO business logic — thin pipe                                  |
|  Connection registry: ElastiCache Redis (ephemeral, TTL 120s)       |
+------------------------------------------------------------------+
          |
          v
+------------------------------------------------------------------+
|                     API / MESSAGE SERVICE LAYER                   |
|  Message Ingress Service:                                        |
|    - Validate auth (JWT/device token)                             |
|    - Assign server_message_id (Snowflake / ULID)                 |
|    - Idempotency check (client_message_id dedup)                  |
|    - Write to message store (Cassandra/Keyspaces)                 |
|    - Publish to Kafka fan-out topic                               |
|  Message Sync Service (offline pull, history pagination)          |
|  Group Service (membership, roles, invite links)                  |
|  Device Service (multi-device registration, pre-keys)             |
|  Receipt Aggregator (batch delivery/read receipts)                |
+------------------------------------------------------------------+
          |
    +-----+-----+------------------+
    v           v                  v
+--------+  +----------+    +-------------+
| Kafka  |  | Cassandra|    | S3 + CF     |
| (MSK)  |  | Keyspaces|    | (media)     |
| fan-out|  | messages |    |             |
| topics |  | + inbox  |    |             |
+--------+  +----------+    +-------------+
    |
    v
+------------------------------------------------------------------+
|                     FAN-OUT WORKER LAYER                          |
|  Consumer groups per region                                       |
|  - Resolve recipients (1:1, group membership cache)               |
|  - Write-fan-out: insert into recipient inbox tables              |
|  - Lookup connection registry → push via gateway RPC              |
|  - Offline: skip push, message waits in inbox                     |
+------------------------------------------------------------------+
```

### 3.4 The Message Lifecycle — End to End

```
SEND PATH (Alice → Bob, both online, 1:1 chat):

  Step 1: CLIENT ENCRYPTION (E2E — see Section 3.10)
    Alice's app encrypts plaintext with Signal Protocol
    using session key derived from Bob's pre-key bundle.
    Produces: ciphertext + message header (ratchet info)

  Step 2: CLIENT SEND
    Alice's device → WebSocket gateway (persistent connection)
    Frame: {
      type: "SEND_MESSAGE",
      client_message_id: "uuid-alice-local",  // idempotency
      chat_id: "chat_alice_bob",
      ciphertext: <bytes>,
      timestamp_client: 1717680000,
      device_id: "alice_phone_1"
    }

  Step 3: GATEWAY → MESSAGE INGRESS
    Gateway forwards to Message Ingress (gRPC internal)
    Gateway does NOT decrypt — passes ciphertext through

  Step 4: INGRESS PROCESSING
    a) Auth: verify device token, check not revoked
    b) Idempotency: check client_message_id in dedup store
       (Redis SET, TTL 24h, or Cassandra side table)
       → If duplicate: return existing server_message_id
    c) Assign server_message_id (time-ordered, globally unique)
       Snowflake: 41-bit timestamp + 10-bit machine + 12-bit seq
    d) Persist to Cassandra (chat partition):
       INSERT INTO messages (chat_id, msg_ts, server_msg_id,
         sender_id, ciphertext, metadata) VALUES (...)
    e) Publish to Kafka:
       Topic: message-fanout
       Key: chat_id (preserves per-chat ordering)
       Value: {server_msg_id, chat_id, sender_id, recipients[],
               ciphertext_ref, timestamp}

  Step 5: FAN-OUT WORKER
    Consumes from message-fanout partition
    Resolves recipients: [bob_phone, bob_web] (multi-device)
    For each recipient device:
      a) Write to recipient inbox (if write-fan-out enabled):
         INSERT INTO inbox (user_id, inbox_ts, chat_id,
           server_msg_id, preview_metadata)
      b) Query connection registry: is bob_web online?
         → YES: RPC to gateway: PUSH {ciphertext, server_msg_id}
         → NO:  skip push; inbox row waits for sync

  Step 6: GATEWAY DELIVERY
    Gateway pushes WebSocket frame to Bob's connection
    Bob's client decrypts with Signal Protocol

  Step 7: DELIVERY RECEIPT (async, batched)
    Bob's client → gateway → Receipt Service
    Publishes to receipt-events Kafka topic
    Aggregator batches receipts per sender
    Alice sees: ✓✓ (delivered)

  Step 8: READ RECEIPT (optional, privacy-controlled)
    Bob opens chat → client sends READ_RECEIPT
    Same async path → Alice sees blue ✓✓

TOTAL LATENCY BUDGET (online recipient, same region):

  Client encrypt:        1-5 ms
  WS send → gateway:     1-10 ms (network)
  Gateway → ingress:     1-5 ms (internal gRPC)
  Cassandra write:       5-15 ms (LOCAL_QUORUM)
  Kafka publish:         2-10 ms (acks=1 for fan-out trigger)
  Fan-out worker:        5-20 ms (consumer lag near zero)
  Registry lookup:       1-3 ms (Redis)
  Gateway push:          1-10 ms
  Client decrypt:        1-5 ms
  ─────────────────────────────
  Total p50:             ~30-80 ms
  Total p99:             ~200-500 ms (tail: GC, consumer lag)
```

### 3.5 Fan-Out Strategies — The Central Design Decision

```
TWO FAN-OUT MODELS:

  FAN-OUT ON WRITE (push model):
    At send time, write a copy to EACH recipient's inbox.
    
    Send "Hello" to group of 50:
      → 1 write to messages table (chat partition)
      → 50 writes to inbox tables (one per member)
    
    Pros:
      → Read is O(1) — just scan your inbox
      → Offline sync is fast — inbox is pre-built
      → No hot read on send for large groups
    
    Cons:
      → Write amplification: N recipients = N inbox writes
      → Celebrity group (10K members) = 10K writes per message
      → Storage duplication (metadata per inbox row)

  FAN-OUT ON READ (pull model):
    At send time, write ONCE to the group's message log.
    Recipients pull when they open the chat.
    
    Send "Hello" to group of 10,000:
      → 1 write to messages table
      → 0 inbox writes at send time
      → Each member reads group log when app opens
    
    Pros:
      → Constant write cost regardless of group size
      → No write amplification
    
    Cons:
      → Read is O(M) where M = messages since last visit
      → Hot partition: popular group chat = one Cassandra
        partition gets all reads
      → Slow "unread count" — must scan or maintain counter

WHATSAPP HYBRID (what you should propose in interviews):

  +------------------+------------------------------------------+
  | Chat type        | Fan-out strategy                         |
  +------------------+------------------------------------------+
  | 1:1 chat         | Write fan-out (1 inbox write)            |
  | Small group ≤256 | Write fan-out (N inbox writes)           |
  | Large group >256 | Read fan-out (pull from group log)       |
  | Broadcast/status | Read fan-out only                        |
  | Channels (future)| Read fan-out + CDN for static segments   |
  +------------------+------------------------------------------+

  Threshold selection:
    Break-even: when N inbox writes cost > 1 hot read cost
    At 256 members with 50B msgs/day:
      Write fan-out: 256 × write latency per message
      Read fan-out: 1 write + occasional group log scan
    256 is WhatsApp's historical sweet spot (configurable
    via feature flag per group tier).

KAFKA'S ROLE IN FAN-OUT:

  Kafka decouples "message accepted" from "message delivered"
  
  Without Kafka:
    Ingress must synchronously fan-out to all recipients
    → Tail latency = slowest recipient
    → Ingress blocked if fan-out worker dies
  
  With Kafka:
    Ingress: persist + publish (fast, ~20ms)
    Fan-out workers: consume async, scale independently
    → Ingress never blocked by delivery failures
    → Consumer lag = backlog metric (alert if > 5s)

  Topic design:
    message-fanout-{region}     — keyed by chat_id
    receipt-events-{region}     — keyed by sender_id
    presence-events-{region}    — keyed by user_id (low volume)
    group-membership-changes    — compacted topic (CDC)

  Partition count:
    Peak 1.75M msg/sec, target 10K msg/sec/partition
    → 175 partitions minimum per region
    → Round to 256 partitions (headroom)
    → Celebrity chat hot partition: accept it; single chat
      cannot exceed ~1K msg/sec in practice
```

### 3.6 WebSocket Connection Layer (Week 1 Integration)

```
WHY WEBSOCKETS (not polling, not SSE):

  From Week 1 WebSockets module:
    → Full-duplex: client sends AND receives on same connection
    → Low overhead per frame after upgrade (2-14 byte header)
    → Server-initiated push (critical for incoming messages)
    → SSE is server→client only; long-polling has 2× latency

  WhatsApp uses persistent WebSocket (or custom protocol over
  TCP/TLS — functionally equivalent to WSS for design purposes)

CONNECTION ESTABLISHMENT:

  1. Client → NLB (TLS termination or pass-through)
  2. HTTP Upgrade: GET /ws HTTP/1.1
     Upgrade: websocket
     Connection: Upgrade
     Sec-WebSocket-Key: ...
     Authorization: Bearer <device_token>
  3. Gateway validates token, registers connection:
     Redis HSET conn_registry:{user_id} {device_id} {gateway_id, conn_id}
     EXPIRE conn_registry:{user_id} 120
  4. Bidirectional frames: binary protobuf (not JSON — size)

HEARTBEAT (Week 1 — NLB idle timeout):

  AWS NLB idle timeout: 350 seconds (FIXED, cannot change)
  AWS ALB idle timeout: 60 seconds (configurable, max 4000s)
  
  WhatsApp uses NLB for WebSocket (Layer 4, no HTTP inspection)
  
  Client sends PING every 30 seconds
  Server responds PONG
  If no PONG within 60s → client reconnects (exponential backoff
  + jitter from Week 1 — prevents thundering herd on deploy)

CONNECTION REGISTRY DESIGN:

  Problem: Fan-out worker needs to find which gateway holds
  Bob's WebSocket connection.
  
  Naive: scan all 5000 gateways → impossible
  
  Solution: Redis registry
    Key:   conn:{user_id}:{device_id}
    Value: {gateway_host, connection_id, region, last_ping}
    TTL:   120s (refreshed on every heartbeat)
  
  Fan-out worker lookup:
    1. SMEMBERS devices:{user_id}  → [phone, web, tablet]
    2. MGET conn:{user_id}:phone, conn:{user_id}:web, ...
    3. For each live connection: gRPC PushToConnection(gateway, conn_id, payload)
  
  Gateway crash:
    TTL expires in 120s → registry auto-cleans
    Client detects disconnect → reconnects to another gateway
    → new registry entry

RECONNECT STORM (Week 1 failure pattern):

  Deploy kills 100K connections on one gateway
  100K clients reconnect simultaneously
  
  Fix (client): exponential backoff + jitter
  Fix (server): NLB connection rate limit (new connections/sec)
  Fix (ops): rolling deploy — drain connections before kill
    → Send GOAWAY frame
    → Wait 30s for clients to migrate
    → Then terminate

SCALING MATH (from Week 1):

  500M connections, 100K per gateway = 5,000 gateways
  Memory per gateway: 100K × 50KB = 5 GB (connection state)
  + 2 GB application overhead = 7 GB per instance
  Instance: c6gn.4xlarge (32 GB) — comfortable headroom
  
  Regional distribution:
    India: 150M connections → 1,500 gateways
    LATAM: 80M connections → 800 gateways
    EU: 100M connections → 1,000 gateways
    (fan-out workers co-located per region — no cross-region push)
```

### 3.7 Message Storage — Cassandra / DynamoDB / Keyspaces

```
WHY NOT SQL:

  Message access pattern:
    → Write: append to chat (always)
    → Read: "give me messages in chat X since timestamp T"
    → Read: "give me my inbox" (list of chats with previews)
    → Delete: tombstone individual messages (GDPR, unsend)
    → NO joins, NO transactions across chats
  
  This is a partition-key-driven workload — Cassandra's sweet spot
  (Week 2 NoSQL Taxonomy, Week 5 Cassandra Architecture)

SCHEMA — MESSAGES TABLE (Cassandra / Keyspaces):

  CREATE TABLE messages (
    chat_id         text,       -- PARTITION KEY
    msg_ts          timeuuid,   -- CLUSTERING KEY (desc)
    server_msg_id   text,
    sender_id       text,
    sender_device   text,
    ciphertext      blob,       -- E2E encrypted payload
    content_type    text,       -- text|image|video|audio|doc
    media_ref       text,       -- S3 key if media
    client_msg_id   text,
    reply_to_id     text,
    deleted         boolean,
    PRIMARY KEY ((chat_id), msg_ts)
  ) WITH CLUSTERING ORDER BY (msg_ts DESC)
    AND compaction = {'class': 'TimeWindowCompactionStrategy',
                      'compaction_window_size': 1,
                      'compaction_window_unit': 'DAYS'}
    AND gc_grace_seconds = 864000;  -- 10 days (tombstone safety)

  PARTITION KEY = chat_id:
    All messages in one chat live on the same Cassandra node
    (plus replicas). Range query within partition is efficient.
    (Week 4 Sharding: compound key design)

  CLUSTERING KEY = msg_ts (TimeUUID):
    TimeUUID is time-ordered + unique — no collision
    DESC order: "latest messages first" matches UI
    Pagination: SELECT ... WHERE chat_id = ? AND msg_ts < ? 
                LIMIT 50

  TWCS (Time-Window Compaction Strategy):
    Compaction windows of 1 day — old SSTables compact separately
    Matches "messages are mostly append-only, old data cold"
    (Week 5 Cassandra Architecture: TWCS for time-series)

SCHEMA — INBOX TABLE (write fan-out path):

  CREATE TABLE inbox (
    user_id         text,       -- PARTITION KEY
    inbox_ts        timeuuid,   -- CLUSTERING KEY (desc)
    chat_id         text,
    server_msg_id   text,
    sender_id       text,
    preview         text,       -- encrypted preview or "📷 Photo"
    unread          boolean,
    PRIMARY KEY ((user_id), inbox_ts)
  ) WITH CLUSTERING ORDER BY (inbox_ts DESC);

  One partition per user — their inbox feed
  Hot key risk: celebrity with 10M followers sending to inbox
    → Mitigated by read-fan-out for large groups (no inbox write)

SCHEMA — USER_CHAT_INDEX (for "list my chats"):

  CREATE TABLE user_chats (
    user_id         text,
    chat_id         text,
    last_msg_ts     timeuuid,
    last_preview    text,
    unread_count    counter,    -- or separate counter table
    PRIMARY KEY ((user_id), chat_id)
  );

DYNAMODB EQUIVALENT (AWS-native):

  Table: Messages
    PK: CHAT#{chat_id}
    SK: MSG#{reverse_timestamp}#{server_msg_id}
    Attributes: sender_id, ciphertext (binary), content_type, ...
  
  Reverse timestamp in SK: enables "latest first" Query
    reverse_ts = MAX_TIMESTAMP - actual_ts
  
  GSI: none needed for primary path (chat_id is always known)
  
  DynamoDB advantage: auto-scaling, on-demand capacity
  Keyspaces advantage: Cassandra-compatible, TWCS, tunable consistency
  Choice: Keyspaces if team knows Cassandra; DynamoDB if AWS-native

CONSISTENCY LEVEL:

  Message write: LOCAL_QUORUM (RF=3, W=2)
    Survives 1 node failure, ~10ms in-region
    (Week 2: QUORUM math R+W>N → 2+2>3)
  
  Message read (sync): LOCAL_QUORUM (R=2)
    Monotonic reads within session: use same coordinator
  
  Inbox write (fan-out): LOCAL_ONE acceptable
    Inbox is derived data — can be rebuilt from messages table
    Eventual consistency OK for inbox ordering (seconds)
  
  NEVER use ANY/ONE for message persistence — durability risk

SHARDING BY chat_id — DEEP DIVE:

  chat_id format: hash of sorted participant IDs (1:1) or group UUID
  
  Murmur3(chat_id) → token ring → Cassandra node assignment
  (Week 3 Consistent Hashing, Week 4 Sharding)
  
  Hot partition scenario:
    Group "World Cup Final Watch Party" — 50K members, 5K msg/sec
    ALL writes go to ONE partition
    
    Mitigations:
      L1: Rate limit messages per group (client-side + server)
      L2: Partition splitting — NOT possible in Cassandra after creation
          → Design chat_id to include sub-shard: group_id + shard_num
          → sender_id hash % 16 → 16 sub-partitions per large group
      L3: Read-fan-out for this group tier (no inbox writes)
      L4: Dedicated "megagroup" Cassandra cluster (blast radius)
  
  Cross-chat queries (admin, search):
    NOT supported efficiently — E2E encryption prevents server search
    Metadata search (chat list) uses user_chats table only
```

### 3.8 Kafka Fan-Out Pipeline (Week 6 Integration)

```
WHY KAFKA BETWEEN INGRESS AND DELIVERY:

  From Week 6 Message Queues and Kafka:
    → Durability: message persisted to Kafka before fan-out
    → Decoupling: ingress rate ≠ delivery rate
    → Replay: re-process fan-out after bug fix
    → Backpressure: consumer lag absorbs spikes
    → Multiple consumers: fan-out, analytics, moderation metadata

PRODUCER (Message Ingress → Kafka):

  Properties:
    acks=1                    # leader ack (fast; message already in Cassandra)
    compression.type=lz4        # ciphertext doesn't compress well, but
                                # metadata/headers do
    partitioner=chat_id hash    # ordering per chat
    enable.idempotence=true     # no duplicate Kafka records
    linger.ms=5                 # micro-batch for throughput
    batch.size=65536

  Record:
    Topic:   msg-fanout-use1
    Key:     chat_id (byte[])
    Value:   FanoutEvent {
               server_msg_id, chat_id, sender_id,
               recipient_ids: [user_id...],
               ciphertext_ref,  // pointer to Cassandra row
               fanout_mode: WRITE | READ,
               timestamp
             }

CONSUMER (Fan-out Worker):

  Consumer group: fanout-workers-use1
  Partition assignment: 256 partitions / 64 workers = 4 each
  
  Processing (per record):
    1. Deserialize FanoutEvent
    2. If fanout_mode == WRITE:
         For each recipient_id (batched, 50 per Cassandra UNLOGGED BATCH):
           INSERT INTO inbox (user_id, inbox_ts, chat_id, ...)
           INSERT INTO user_chats (user_id, chat_id, last_msg_ts, ...)
    3. For each recipient device (from device registry):
         Lookup conn registry (Redis)
         If online: gRPC push to gateway
         If offline: done (inbox row is sufficient)
    4. Commit offset (at-least-once delivery)
  
  Idempotency:
    Dedup key: (server_msg_id, recipient_id) in Redis SET, TTL 1h
    Prevents double-delivery on consumer rebalance
    (Week 6: consumer rebalance causes duplicate processing)

DELIVERY SEMANTICS (Week 6):

  Kafka → Fan-out: at-least-once
  Fan-out → Gateway push: at-least-once
  Client: dedup by server_msg_id (idempotent display)
  
  Effective: exactly-once display (client-side idempotency)
  NOT exactly-once end-to-end (and that's OK for messaging)

CONSUMER LAG — THE CRITICAL METRIC:

  lag = latest_offset - committed_offset per partition
  
  Healthy: < 1000 messages (< 1 second at peak)
  Degraded: 10K-100K (delivery delay seconds)
  Incident: > 1M (minutes of delay — users see late messages)
  
  Causes of lag:
    → Fan-out worker OOM / crash loop
    → Cassandra write slowdown (hot partition)
    → Redis registry timeout (push path blocked)
    → Consumer rebalance storm (deploy without cooperative-sticky)
    → Under-provisioned consumers

KAFKA TOPIC SIZING (MSK on AWS):

  msg-fanout-use1:
    Partitions: 256
    Replication: 3
    Retention: 24 hours (fan-out is real-time; replay window only)
    Instance: kafka.m5.2xlarge × 6 brokers
    Throughput: ~250 MB/sec cluster capacity (well above needs)

  receipt-events-use1:
    Partitions: 128
    Retention: 6 hours
    Lower priority — batch processed every 500ms
```

### 3.9 Presence and Typing Indicators

```
PRESENCE REQUIREMENTS:

  States: ONLINE | OFFLINE | LAST_SEEN(timestamp)
  Privacy: user can hide last seen, hide online, hide read receipts
  Scale: 500M concurrent, presence queries per chat open

NAIVE DESIGN (breaks at scale):

  Every user heartbeat → Redis SET user:123:status "online" every 30s
  500M users / 30s = 16.7M Redis writes/sec → impossible

PRODUCTION PRESENCE — CONNECTION-DERIVED:

  Presence is a DERIVED property of the connection registry,
  not a separate heartbeat system.
  
  User is ONLINE iff:
    EXISTS conn:{user_id}:* with TTL not expired in Redis
  
  Last seen:
    On disconnect: SET last_seen:{user_id} = now() (one write)
    Persists in Cassandra user_profile table (cold storage)
  
  Query "is Bob online?":
    EXISTS conn:bob_phone OR conn:bob_web → online
    Cost: 1-2 Redis lookups, no heartbeat infrastructure

TYPING INDICATORS:

  High churn, ephemeral, lossy — OK to drop
  
  Client sends TYPING_START → gateway → Kafka presence-events
  Typing state: Redis SET typing:{chat_id} {user_id} EX 5
  Fan-out to other chat members via gateway push
  Rate limit: max 1 typing event per 3 seconds per user
  
  If typing event drops: no user impact (UI timeout clears indicator)

PRESENCE BROADCAST (privacy-aware):

  Alice opens chat with Bob:
    → Query Bob's online status (Redis lookup)
    → Subscribe to presence changes for Bob (gateway subscription map)
  
  Bob comes online:
    → Gateway updates registry
    → Publishes presence-change to subscribed gateways only
    → NOT broadcast to all 500M users
  
  Subscription map:
    Redis: SUBSCRIBERS:{user_id} → SET of {subscriber_gateway_ids}
    Bounded: max 500 subscribers per user (realistic friend graph)
```

### 3.10 Delivery Receipts — Design Without Melting the System

```
RECEIPT TYPES:

  SENT (✓):       Server acknowledged (ingress persisted)
  DELIVERED (✓✓): Recipient device received (WS push ACK)
  READ (blue ✓✓): Recipient opened chat (client event)

VOLUME MATH:

  50B messages/day × 2 receipts avg (delivered + some read)
  = 100B receipt events/day
  = 1.16M receipt events/sec average
  = 3.5M/sec peak
  
  If each receipt = 1 Cassandra write:
    3.5M writes/sec just for receipts → unsustainable

SOLUTION — RECEIPT AGGREGATION:

  1. Client sends receipt → gateway → Kafka receipt-events
  2. Receipt Aggregator (separate consumer group):
     Batches receipts per (chat_id, sender_id) every 500ms
     Produces aggregated frame:
       {chat_id, server_msg_ids: [id1, id2, ...], 
        status: DELIVERED, recipient_id: bob}
  3. ONE push to sender per batch (not per message)
  4. Cassandra receipt state (optional, for offline sender):
     UPDATE messages SET delivered_to = delivered_to + {bob}
     Using SET collection type — or separate receipts table
     Write frequency: batched every 500ms per chat

RECEIPT FOR GROUPS:

  256-member group → 256 delivery receipts per message
  Aggregator collects all 256 → single GROUP_DELIVERED event
  Sender sees: "Delivered to 256 members" (not 256 notifications)
  
  Read receipts in groups: typically suppressed or shown as count
  ("Read by 42 of 256") — privacy + volume control

OFFLINE SENDER:

  Sender offline when receipts generated:
    Store aggregated receipt in sender's inbox or receipt table
    On reconnect: sync pending receipts with message history
```

### 3.11 E2E Encryption — Signal Protocol Overview

```
WHY E2E CHANGES THE ARCHITECTURE:

  Server stores CIPHERTEXT ONLY.
  Server CANNOT:
    → Search message content
    → Moderate content server-side
    → Generate server-side previews (client sends encrypted preview)
    → Deduplicate by content hash (only by ciphertext hash)
  
  Server CAN:
    → Route ciphertext blobs
    → Store ciphertext blobs
    → Deliver metadata (sender, timestamp, chat_id, content_type)
    → Enforce rate limits, block accounts (metadata-level)

SIGNAL PROTOCOL — SIMPLIFIED (Double Ratchet):

  Key agreement: X3DH (Extended Triple Diffie-Hellman)
    Uses: Curve25519 (elliptic curve), AES-256, HMAC-SHA256
    
  Session: Double Ratchet Algorithm
    → Each message derives new encryption key (forward secrecy)
    → Compromised key exposes ONE message, not history
    → Out-of-order message handling via ratchet state

  KEY COMPONENTS:

  Identity Key (long-term):
    Generated at registration, tied to phone number
    Stored on device secure enclave (iOS) / Keystore (Android)

  Signed Pre-Key (medium-term):
    Rotated weekly, signed by identity key
    Uploaded to server (Key Directory Service)

  One-Time Pre-Keys (single use):
    Batch of 100 uploaded to server
    Consumed on first message from new contact
    Server notifies when count low → client uploads more

  KEY DIRECTORY SERVICE (server-side, NOT E2E):

  Table: device_prekeys
    user_id, device_id, signed_prekey, signed_prekey_sig,
    one_time_prekeys: [key_id → public_key, ...]
  
  When Alice messages Bob for first time:
    1. Alice fetches Bob's pre-key bundle from server (HTTPS)
    2. Alice runs X3DH → establishes shared secret (client-side)
    3. Alice encrypts message with Double Ratchet
    4. Server stores/transmits ciphertext — never sees plaintext

  GROUP E2E (Sender Keys):

    Each member has a "sender key" for the group
    Message encrypted once with sender key, not per-recipient
    Server fans out same ciphertext to all members
    Key rotation on member add/remove (security requirement)

MULTI-DEVICE E2E:

  Each device has separate identity key
  "Linked device" (WhatsApp Web): QR code scan exchanges
  session keys via local channel (phone signs for web)
  Server routes to correct device ciphertext
  Message sent from phone encrypted for ALL linked devices
  (device-specific session within Signal framework)

WHAT YOU SAY IN INTERVIEWS:

  "E2E is client-side. Server is a dumb relay for ciphertext.
   This constrains search, moderation, and backup — tradeoffs
   accepted for privacy. Key directory is the only server-side
   crypto infrastructure."
```

### 3.12 Multi-Device Sync

```
PROBLEM:

  Alice has: iPhone (primary), Mac (linked), iPad (linked)
  Bob sends message → must arrive on ALL Alice's active devices
  Alice sends from Mac → must appear on iPhone and iPad too
  Read on iPhone → read receipt, Mac marks as read

DEVICE REGISTRY:

  Table: user_devices
    user_id, device_id, device_type, push_token,
    identity_key_pub, registration_ts, last_active

  Primary device: phone (registered with SMS verification)
  Linked devices: QR scan → primary approves → session established

MESSAGE ROUTING (multi-device):

  Fan-out worker resolves ALL devices for recipient:
    devices:alice = [iphone, mac, ipad]
  
  For each device:
    Separate ciphertext in messages table (device-specific encryption)
    OR same sender-key ciphertext if devices share session (group)
  
  Push to all online devices simultaneously

  SENT FROM LINKED DEVICE:

  Mac sends message → encrypted on Mac with Mac's session keys
  Fan-out to Bob's devices (normal)
  ALSO sync to Alice's iPhone and iPad:
    → Write to Alice's other devices' inbox (self-sync path)
    → Push if online, else inbox on sync

SYNC PROTOCOL (offline devices):

  Device reconnects → sends last_synced_msg_ts per chat
  Server returns: SELECT * FROM messages 
    WHERE chat_id IN (user's chats) AND msg_ts > last_synced
  Client merges into local store (conflict: server_msg_id wins)

READ SYNC:

  Alice reads on iPhone → READ_RECEIPT generated
  Receipt service → push READ state to Mac and iPad
  All devices show blue checkmarks

DELETED / UNSEND:

  Alice unsends message → tombstone in messages table
  Sync event pushed to all devices + recipients
  48-hour unsend window (WhatsApp policy) — client enforces
  Server stores deleted=true flag (metadata, not content)
```

### 3.13 Media Messages

```
MEDIA PATH (photo example):

  1. Client encrypts image bytes locally (AES-256 key random)
  2. Encrypted blob uploaded to S3 via pre-signed URL (HTTPS)
     → ALB → Media Upload Service → S3 PUT
  3. Message frame contains: media_ref (S3 key), encryption key
     (encrypted with Signal session — inside ciphertext)
  4. Text message with content_type=image sent via normal path
  5. Recipient downloads from S3/CloudFront via pre-signed URL
  6. Client decrypts locally

WHY S3 + CLOUDFRONT (Week 1 CDN):

  Media is large (200 KB - 16 MB) — never through WebSocket
  S3: durable, cheap storage ($0.023/GB/month)
  CloudFront: edge delivery for popular media (forwarded images)
  
  Pre-signed URL: time-limited (1 hour), no auth cookie needed
  CDN cache key: media hash (content-addressed)
  → Same image forwarded 1000 times = 1 S3 object, CDN hit

CAPACITY:

  30% of 50B messages = 15B media uploads/day
  Avg 200 KB → 3 PB/day raw
  Dedup by SHA-256 hash: ~40% unique → 1.2 PB/day actual
  S3 multipart for > 5 MB (video messages)
```

### 3.14 Group Chat Mechanics

```
GROUP DATA MODEL:

  Table: groups
    group_id, name, created_by, created_ts, avatar_ref,
    max_members, fanout_mode (WRITE|READ)

  Table: group_members (Cassandra — partition by group_id)
    group_id, user_id, role (admin|member), joined_ts

  Membership cache: Redis SET group_members:{group_id}
    Refreshed on change via Kafka compacted topic
    Fan-out worker reads cache (not Cassandra per message)

GROUP OPERATIONS:

  Create group:
    INSERT groups, INSERT group_members (founder = admin)
    Publish GROUP_CREATED to membership topic

  Add member:
    INSERT group_members
    Invalidate Redis cache
    Publish GROUP_MEMBER_ADDED
    E2E: sender key redistribution required (client-side)
    Server sends "keys changed" signal to all members

  Remove member:
    DELETE from group_members (tombstone)
    Sender key rotation (client)
    Recent messages: member can still see (WhatsApp policy)
    Future messages: not delivered to removed member

  Message to group:
    chat_id = group_id
    Recipients = SMEMBERS group_members:{group_id}
    Fan-out mode from groups.fanout_mode field
```

### 3.15 AWS Architecture — Full Regional Deployment

```
REGION: us-east-1 (primary) + eu-west-1, ap-south-1, sa-east-1

DNS:
  Route 53 latency-based routing
  ws.whatsapp.example.com → nearest regional NLB
  api.whatsapp.example.com → nearest regional ALB

WEBSOCKET TIER:
  NLB (TCP 443 pass-through TLS) → Gateway ASG (c6gn.4xlarge)
  ASG: 1,000 instances per large region (auto-scale on conn count)
  Health check: TCP 8080 + /health (active WS count metric)

API TIER:
  ALB (HTTPS) → API Service ASG (m6g.2xlarge)
  Endpoints: /v1/register, /v1/keys, /v1/media/upload, /v1/sync

MESSAGE INGRESS:
  EKS or ECS (stateless, gRPC)
  HPA on CPU + custom metric (ingress QPS)

FAN-OUT WORKERS:
  EKS (Kafka consumer deployments)
  KEDA autoscaling on Kafka consumer lag

KAFKA:
  Amazon MSK (6 brokers, kafka.m5.2xlarge, 256 partitions)
  Cluster per region (no cross-region Kafka)

MESSAGE STORE:
  Amazon Keyspaces (multi-region capable, but start single-region)
  OR self-managed Cassandra on EC2 i3.2xlarge (if cost-sensitive)
  RF=3, LOCAL_QUORUM, TWCS

CACHE:
  ElastiCache Redis Cluster (r6g.2xlarge, 10 shards)
  Connection registry + group membership cache + typing state

MEDIA:
  S3 (Intelligent-Tiering after 30 days)
  CloudFront distribution (media.whatsapp.example.com)
  Pre-signed URLs generated by Media Service

OBSERVABILITY:
  CloudWatch metrics (custom: conn_count, fanout_lag, ingress_qps)
  X-Ray tracing on ingress → Kafka → fan-out path
  MSK Open Monitoring (consumer lag per partition)

CROSS-REGION:
  Users homed to nearest region (phone number prefix + GeoDNS)
  Messages do NOT cross regions in hot path
  Multi-region Cassandra (optional DR — async replication)
```

---

## 4. Concrete Examples

### 4.1 AWS Keyspaces Table Creation

```cql
-- Messages table (production DDL)
CREATE TABLE whatsapp_messages (
  chat_id         text,
  msg_ts          timeuuid,
  server_msg_id   text,
  sender_id       text,
  sender_device   text,
  ciphertext      blob,
  content_type    text,
  media_ref       text,
  client_msg_id   text,
  deleted         boolean,
  PRIMARY KEY ((chat_id), msg_ts)
) WITH CLUSTERING ORDER BY (msg_ts DESC)
  AND default_time_to_live = 0
  AND compaction = {
    'class': 'org.apache.cassandra.db.compaction.TimeWindowCompactionStrategy',
    'compaction_window_size': '1',
    'compaction_window_unit': 'DAYS'
  };
```

### 4.2 Kafka Producer Configuration (Message Ingress)

```properties
# MSK producer — message ingress service
bootstrap.servers=broker1.msk.use1:9092,broker2.msk.use1:9092
acks=1
compression.type=lz4
enable.idempotence=true
max.in.flight.requests.per.connection=5
linger.ms=5
batch.size=65536
key.serializer=org.apache.kafka.common.serialization.StringSerializer
value.serializer=com.whatsapp.FanoutEventSerializer
```

### 4.3 Redis Connection Registry Operations

```bash
# Register connection on gateway (called after WS upgrade)
redis-cli HSET "conn:usr_bob:device_web" \
  gateway "gw-use1-0042.internal" \
  conn_id "ws-sess-8f3a2b" \
  region "use1" \
  registered_at "1717680000"

redis-cli EXPIRE "conn:usr_bob:device_web" 120

# Fan-out worker lookup
redis-cli HGETALL "conn:usr_bob:device_web"
# → gateway gw-use1-0042.internal, conn_id ws-sess-8f3a2b

# List all devices for user
redis-cli SMEMBERS "devices:usr_bob"
# → device_phone, device_web, device_ipad
```

### 4.4 NLB WebSocket Health Check

```yaml
# Terraform snippet — NLB target group for WebSocket gateways
resource "aws_lb_target_group" "ws_gateway" {
  name        = "ws-gateway-tg-use1"
  port        = 8080
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    protocol            = "HTTP"
    path                = "/health"
    port                = "8080"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
  }

  # Connection draining for rolling deploys
  deregistration_delay = 60
}
```

### 4.5 Snowflake ID Generation

```python
# Server message ID — time-ordered, globally unique
# 41-bit timestamp | 10-bit machine | 12-bit sequence
import time
import threading

class SnowflakeGenerator:
    EPOCH_MS = 1609459200000  # 2021-01-01

    def __init__(self, machine_id: int):
        self.machine_id = machine_id & 0x3FF
        self.sequence = 0
        self.last_ts = -1
        self.lock = threading.Lock()

    def next_id(self) -> str:
        with self.lock:
            ts = int(time.time() * 1000) - self.EPOCH_MS
            if ts == self.last_ts:
                self.sequence = (self.sequence + 1) & 0xFFF
                if self.sequence == 0:
                    while ts <= self.last_ts:
                        ts = int(time.time() * 1000) - self.EPOCH_MS
            else:
                self.sequence = 0
            self.last_ts = ts
            val = (ts << 22) | (self.machine_id << 12) | self.sequence
            return str(val)
```

---

## 5. Production Patterns

```
╔════════════════════════════════════════════════════════════════╗
║   PATTERN 1: HYBRID FAN-OUT WITH FEATURE FLAG                  ║
╟────────────────────────────────────────────────────────────────╢
║   fanout_mode stored per group in groups table.                ║
║   Default: WRITE for ≤256 members. Auto-switch to READ         ║
║   when member count exceeds threshold. Migration: existing     ║
║   inbox rows stay; new messages use read path only.            ║
║   Feature flag: fanout.read_mode.enabled (per group tier).     ║
╠════════════════════════════════════════════════════════════════╣
║   PATTERN 2: IDEMPOTENCY AT EVERY BOUNDARY                     ║
╟────────────────────────────────────────────────────────────────╢
║   Client: client_message_id (UUID, generated offline)          ║
║   Ingress: dedup table (client_msg_id → server_msg_id)         ║
║   Kafka: enable.idempotence=true (producer)                    ║
║   Fan-out: (server_msg_id, recipient_id) dedup in Redis        ║
║   Client display: dedup by server_msg_id                       ║
║   Result: safe retries at every layer                          ║
╠════════════════════════════════════════════════════════════════╣
║   PATTERN 3: ROLLING DEPLOY WITH CONNECTION DRAIN              ║
╟────────────────────────────────────────────────────────────────╢
║   1. Mark gateway as "draining" (stop accepting new WS)        ║
║   2. Send GOAWAY to existing connections                       ║
║   3. Wait 60s (NLB deregistration delay)                       ║
║   4. Terminate instance                                        ║
║   Clients reconnect to healthy gateways with jitter backoff    ║
╠════════════════════════════════════════════════════════════════╣
║   PATTERN 4: RECEIPT BATCHING (500ms windows)                  ║
╟────────────────────────────────────────────────────────────────╢
║   Separate Kafka consumer aggregates receipts per chat         ║
║   Reduces push events 50-100× for active conversations         ║
║   Tradeoff: 500ms delay on receipt display (acceptable)        ║
╠════════════════════════════════════════════════════════════════╣
║   PATTERN 5: CASSANDRA REPAIR SCHEDULING                       ║
╟────────────────────────────────────────────────────────────────╢
║   Messages RF=3 — node loss without repair = data at risk      ║
║   nodetool repair weekly per DC (off-peak, throttle 50 MB/s)   ║
║   Monitor: nodetool compactionstats, pending compactions       ║
║   gc_grace_seconds=864000 (10 days) before tombstone purge     ║
╠════════════════════════════════════════════════════════════════╣
║   PATTERN 6: REGIONAL ISOLATION (BLAST RADIUS)                 ║
╟────────────────────────────────────────────────────────────────╢
║   Each region: own gateways, Kafka, Cassandra, Redis           ║
║   Cross-region only for: account migration, DR failover        ║
║   User homed to region by phone prefix at registration         ║
║   Prevents: EU outage affecting India message delivery         ║
╠════════════════════════════════════════════════════════════════╣
║   PATTERN 7: OUTBOX FOR INGRESS → KAFKA (Week 6)               ║
╟────────────────────────────────────────────────────────────────╢
║   Dual-write risk: Cassandra OK but Kafka publish fails        ║
║   Outbox table: INSERT message + INSERT outbox in BATCH        ║
║   CDC (Debezium) or polling worker publishes to Kafka          ║
║   Guarantees: message always fan-outs even if producer fails   ║
╚════════════════════════════════════════════════════════════════╝
```

---

## 6. Failure Modes

```
FAILURE MODE 1: KAFKA CONSUMER LAG SPIKE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: Messages arrive minutes late. Users report "delayed chat."
  Cause: Fan-out workers underscaled; Cassandra hot partition;
         consumer rebalance during deploy.
  Mechanism: Lag grows linearly — ingress 1.75M/sec, consumers 800K/sec
  Detection: kafka.consumer.lag.max > 10000 per partition
  Mitigation: KEDA scale consumers; identify hot chat_id partition;
              temporary rate limit on hot group
  Prevention: Autoscale on lag; cooperative-sticky assignor;
              canary deploy (10% consumers first)

FAILURE MODE 2: CASSANDRA HOT PARTITION (MEGAGROUP)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: One group chat extremely slow; p99 write latency 2s+
  Cause: 50K-member group, read-fanout not enabled, all writes
         to single chat_id partition on one node
  Mechanism: Single Cassandra coordinator overwhelmed; compaction
             backlog on hot SSTable
  Detection: nodetool tablestats → high write latency per partition;
              metric: cassandra_write_latency_p99 by partition
  Mitigation: Enable read-fanout for group; sub-shard chat_id;
              rate limit messages to group (10/sec)
  Prevention: Auto-switch fanout_mode at 256 members; monitor
               partition write rate

FAILURE MODE 3: REDIS REGISTRY OUTAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: Messages saved but not delivered to online users until
           reconnect. "I was online but didn't get messages."
  Cause: ElastiCache failover (30s); network partition; memory eviction
  Mechanism: Fan-out worker cannot find gateway → skips push;
             inbox write still succeeds (offline path works)
  Detection: redis.connected_clients drop; push_success_rate < 90%
  Mitigation: Redis replica promotion (automatic); fan-out fallback
              to broadcast-scoped gateway lookup (slower)
  Prevention: Redis Cluster with 2 replicas; local gateway cache
              (30s TTL) as L2 fallback

FAILURE MODE 4: WEBSOCKET RECONNECT THUNDERING HERD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: Gateway fleet CPU 100%; new connections timeout;
           existing users disconnected
  Cause: Regional NLB target drain during full fleet deploy
  Mechanism: 150M connections × simultaneous reconnect = auth +
             registry write storm (Week 1 WebSockets failure pattern)
  Detection: connection_rate spike 100×; auth_service 5xx
  Mitigation: Pause deploy; enable connection rate limit on NLB;
              client backoff (if app version supports)
  Prevention: Rolling deploy max 5% fleet; drain before kill;
              GOAWAY frame with 30s warning

FAILURE MODE 5: E2E KEY DIRECTORY EXHAUSTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: New conversations fail with "Unable to send — waiting
           for security info"
  Cause: Bob's one-time pre-keys depleted; client not uploading new batch
  Mechanism: Alice cannot complete X3DH → no session key → no encrypt
  Detection: prekey_count < 10 for device; metric alert
  Mitigation: Server sends PUSH notification to Bob: "Open app to
              refresh security keys"; fallback to signed pre-key only
  Prevention: Client uploads 100 one-time keys at registration;
              server alerts at count < 20; weekly rotation reminder

FAILURE MODE 6: MULTI-DEVICE SYNC GAP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: Message on phone not appearing on linked web client
  Cause: Self-sync fan-out path failed; web device marked offline
         in registry but user sees web app open (stale registry)
  Mechanism: Fan-out only pushed to devices with valid conn registry
  Detection: sync_completeness metric < 99.9% per device pair
  Mitigation: Web client polls /v1/sync every 30s as fallback;
              force registry refresh on web focus event
  Prevention: Page Visibility API triggers re-registration;
              separate sync Kafka topic with higher priority

FAILURE MODE 7: TOMBSTONE EXPLOSION (MASS UNSEND)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: Cassandra read latency degrades cluster-wide 48h after
           viral "unsend" event
  Cause: 10M messages unsent → 10M tombstones in overlapping TWCS
         windows; gc_grace not elapsed; read must merge tombstones
  Mechanism: Week 5 Cassandra: tombstones cause read amplification
  Detection: nodetool tablestats → high tombstone count per read
  Mitigation: Force compaction on affected tables; temporary
              raise gc_grace; read repair throttle
  Prevention: Unsend = metadata flag (deleted=true) not DELETE;
              batch unsend operations off-peak

FAILURE MODE 8: CROSS-SYSTEM CAPACITY CASCADE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: Fixing Kafka lag by scaling consumers makes Cassandra
           WORSE — write latency doubles, lag grows further
  Cause: Added 64 fan-out workers → 64× more Cassandra inbox writes
         without checking Cassandra headroom
  Mechanism: Cross-system capacity gap (Handoff Doc growth area)
  Detection: Cassandra write latency correlates with consumer count
  Mitigation: Scale Cassandra BEFORE consumers; rate-limit fan-out
              writes; enable LOCAL_ONE for inbox (derived data)
  Prevention: Capacity checklist: "Can downstream handle 2× fan-out?"
```

---

## 7. SRE Diagnostic Toolkit

```
METRICS TO WATCH (CloudWatch / Prometheus):

  Connection layer:
    ws_connections_active{region, gateway}
    ws_connection_rate{region}           # alert: > 50K/sec spike
    ws_push_success_rate                 # alert: < 99%
    ws_push_latency_p99                  # alert: > 200ms

  Message ingress:
    ingress_qps{region}
    ingress_latency_p99                  # alert: > 100ms
    ingress_dedup_hit_rate               # retries indicator
    ingress_cassandra_write_latency_p99

  Kafka:
    kafka_consumer_lag{topic, partition}  # alert: > 10000
    kafka_consumer_lag_sum{group="fanout-workers"}
    kafka_broker_disk_usage                 # alert: > 80%

  Cassandra / Keyspaces:
    cassandra_write_latency_p99{table}
    cassandra_read_latency_p99{table}
    cassandra_pending_compactions           # alert: > 100
    cassandra_tombstones_per_read           # alert: > 1000

  Redis:
    redis_memory_usage_percent              # alert: > 85%
    redis_connected_clients
    redis_evicted_keys_per_sec              # alert: > 0

  Receipts:
    receipt_batch_size_avg
    receipt_push_rate

LOG PATTERNS (grep commands):

  # Fan-out failures
  kubectl logs -l app=fanout-worker --since=10m | \
    grep -E "PUSH_FAILED|CASSANDRA_TIMEOUT|lag="

  # Hot partition hints
  kubectl logs -l app=message-ingress --since=5m | \
    grep "write_latency_ms" | awk '$NF > 500' | \
    cut -d' ' -f3 | sort | uniq -c | sort -rn | head -20

  # Consumer rebalance storms
  kubectl logs -l app=fanout-worker | grep -c "Revoke previously"

  # Redis registry misses
  kubectl logs -l app=fanout-worker --since=5m | \
    grep "conn_registry_miss" | wc -l

CASSANDRA COMMANDS:

  # Partition write rate (hot partition detection)
  nodetool tablestats whatsapp.messages | grep -A5 "Write Rate"
  nodetool proxyhistograms | grep -i write

  # Compaction backlog
  nodetool compactionstats
  nodetool tpstats | grep -i compaction

  # Tombstone warning
  grep -i tombstone /var/log/cassandra/system.log | tail -50

KAFKA COMMANDS (MSK):

  # Consumer lag per partition
  kafka-consumer-groups.sh --bootstrap-server $BROKER \
    --describe --group fanout-workers-use1

  # Under-replicated partitions
  kafka-topics.sh --bootstrap-server $BROKER \
    --describe --under-replicated-partitions

REDIS COMMANDS:

  # Memory pressure
  redis-cli INFO memory | grep used_memory_human
  redis-cli INFO stats | grep evicted_keys

  # Connection registry sample
  redis-cli --scan --pattern "conn:*" | head -20 | \
    xargs -I{} redis-cli TTL {}

  # Hot key (single user with many devices)
  redis-cli CLUSTER KEYSLOT "conn:usr_celebrity:device_phone"

LOAD TEST BASELINES:

  # Ingress sustained write
  k6 run --vus 5000 --duration 10m ingress_load_test.js
  # Target: p99 < 100ms at 500K QPS per region

  # Fan-out lag under spike
  # Inject 3× normal rate for 5 minutes
  # Assert: lag recovers to < 1000 within 2 min of spike end

ON-CALL RUNBOOK SNIPPET:

  IF kafka_consumer_lag > 100K AND ingress_latency normal:
    → Fan-out bottleneck (NOT ingress)
    → Check Cassandra write latency first (cross-system capacity)
    → Scale consumers only if Cassandra p99 < 50ms
    → Check for hot chat_id in lagging partitions

  IF ws_push_success_rate < 95%:
    → Check Redis registry health
    → Check gateway fleet CPU/memory
    → Check for deploy in progress (reconnect storm)
```

---

## 8. Decision Framework

```
FAN-OUT STRATEGY SELECTION:

  START
    │
    ├─ Recipients ≤ 256? ──YES──► Fan-out on WRITE
    │                              (inbox table per recipient)
    │
    NO (large group / broadcast)
    │
    ├─ Members need offline inbox? ──YES──► Fan-out on READ
    │                                        + pull sync on open
    │
    NO (live-only channel)
    │
    └─► Fan-out on READ + ephemeral delivery (no inbox)

MESSAGE STORE SELECTION:

  +------------------+---------------+------------------+
  | Requirement      | Cassandra/    | DynamoDB         |
  |                  | Keyspaces     |                  |
  +------------------+---------------+------------------+
  | Time-series chat | Excellent     | Good (SK design) |
  | TWCS compaction  | Native        | N/A (automatic)  |
  | Tunable QUORUM   | Full control  | Limited          |
  | Ops burden       | Higher        | Lower (managed)  |
  | Cost at 27PB/yr  | Lower (i3)    | Higher on-demand |
  | Team expertise   | Need C* ops   | AWS-native       |
  +------------------+---------------+------------------+
  Recommendation: Keyspaces if AWS-managed; Cassandra on i3 if cost-critical

REAL-TIME DELIVERY SELECTION:

  +------------------+-------------+----------+-------------+
  | Mechanism        | Latency     | Duplex   | Scale       |
  +------------------+-------------+----------+-------------+
  | WebSocket        | < 50ms      | Yes      | Excellent   |
  | SSE              | < 100ms     | No       | Good        |
  | Long polling     | 100-500ms   | No       | Moderate    |
  | FCM/APNs push    | 1-30s       | No       | Excellent   |
  +------------------+-------------+----------+-------------+
  Online: WebSocket. Offline: FCM/APNs (metadata only, E2E in payload)

RECEIPT HANDLING:

  Volume < 100K/sec region ──► Synchronous receipt write (simple)
  Volume > 100K/sec region ──► Kafka + batch aggregator (required)
  Group size > 50            ──► Aggregate to count, not per-user

E2E ENCRYPTION:

  Privacy-critical (WhatsApp, Signal) ──► Signal Protocol, server blind
  Enterprise compliance (audit)       ──► Server-side encryption + audit log
  Internal chat (Slack-like)          ──► TLS + server-readable (search OK)

MULTI-DEVICE:

  Devices ≤ 3 per user  ──► Full fan-out to all devices (WhatsApp model)
  Devices > 5             ──► Primary + lazy sync (pull on open)
```

### 3.16 Ordering, Duplicates, and Clock Skew

```
MESSAGE ORDERING GUARANTEE:

  WhatsApp guarantees: messages within a chat appear in send order
  NOT global ordering across chats (impossible at scale)

  Enforcement:
    server_msg_id = Snowflake (time-ordered)
    Cassandra clustering key = TimeUUID (time-ordered)
    Kafka partition keyed by chat_id → ordered delivery per chat

  CLOCK SKEW SCENARIO:

  Alice's phone clock: 2 minutes behind
  Alice sends msg A (client_ts=T-120), then msg B (client_ts=T-60)

  Server receives B first (wall clock), then A:
    server_msg_id_B < server_msg_id_A (Snowflake uses server time)
    Display order: B, then A — CORRECT (server is source of truth)

  Client reconciliation:
    Display sorted by server_msg_id, NOT client_ts
    client_ts used only for "sent from device at..." metadata

DUPLICATE HANDLING:

  Layer 1 — Client offline retry:
    Same client_message_id resent → ingress dedup → same server_msg_id

  Layer 2 — Kafka redelivery:
    Fan-out worker processes same event twice
    Dedup: SETNX fanout:{server_msg_id}:{recipient_id} TTL 1h

  Layer 3 — WebSocket redelivery:
    Gateway push without ACK → retry push (max 3)
    Client dedup by server_msg_id in local SQLite

  Layer 4 — Multi-device sync:
    Same message synced to 3 devices — each gets same server_msg_id
    No duplicate in UI (idempotent merge)

GAP MESSAGES (out-of-order E2E):

  Signal Protocol handles out-of-order ciphertext
  Double Ratchet: skipped message keys cached in session
  Client buffers out-of-order until gap filled
  Server unaware ( ciphertext is opaque )
```

### 3.17 Offline Sync and Message History Pagination

```
OFFLINE USER RECONNECT SEQUENCE:

  1. Client opens WebSocket → gateway registers conn
  2. Client sends SYNC_REQUEST:
     {last_synced_per_chat: {chat_id: last_msg_ts, ...},
      device_id, user_id}
  3. Sync Service queries:
     For each chat where server has newer messages:
       SELECT * FROM messages
       WHERE chat_id = ? AND msg_ts > ? 
       ORDER BY msg_ts ASC LIMIT 1000
  4. Batch response over WebSocket (or HTTPS if payload huge)
  5. Client ACKs highest server_msg_id per chat
  6. Resume real-time push path

PAGINATION (scroll up in chat):

  Initial load: latest 50 messages
    SELECT * FROM messages WHERE chat_id = ?
    ORDER BY msg_ts DESC LIMIT 50

  Load more: cursor = oldest msg_ts from current batch
    SELECT * FROM messages WHERE chat_id = ?
    AND msg_ts < ? ORDER BY msg_ts DESC LIMIT 50

  Cassandra efficiency:
    Single partition scan — O(log n) with clustering index
    No scatter-gather (chat_id known)

INBOX SYNC (chat list view):

  SELECT * FROM inbox WHERE user_id = ?
  ORDER BY inbox_ts DESC LIMIT 50

  Unread count:
    Option A: counter table (Cassandra COUNTER — expensive writes)
    Option B: client-side count from inbox unread flag
    Option C: periodic aggregate job (eventual, 30s delay)
    WhatsApp-style: Option B for display, server authoritative on open

SYNC BANDWIDTH MATH:

  User offline 8 hours, 200 active chats, 20 new messages avg:
    4,000 messages × 500 bytes = 2 MB sync payload
    Acceptable on mobile reconnect (WiFi or LTE)
  Heavy user: 50 chats × 500 messages = 25,000 messages
    Cap initial sync: 1000 most recent across all chats
    Lazy load per chat on open
```

### 3.18 Push Notifications (FCM/APNs) — Offline Path

```
WHEN WEBSOCKET PUSH FAILS (user offline):

  Fan-out worker: conn_registry_miss → enqueue push notification
  Push Service:
    FCM (Android) / APNs (iOS)
    Payload: {type: "new_message", chat_id, sender_name, 
              encrypted_preview, server_msg_id}
    NO plaintext content (E2E — preview is encrypted blob or generic)

  Client receives push → opens app → WebSocket connect → full sync

PUSH RATE LIMITS:

  FCM: ~1M messages/sec per project (batch API)
  APNs: HTTP/2 multiplexed, ~undisclosed but millions/sec

  Per-user rate limit:
    Max 10 push notifications per minute per user
    Aggregate: "5 new messages in 3 chats" (not 5 separate pushes)

  Cricket scenario: 18K members offline
    8K msg/sec × push = impossible
    Only push for 1:1 and small groups
    Large groups: pull on next app open (no per-message push)

AWS IMPLEMENTATION:

  SNS → FCM/APNs platform applications
  Or: direct FCM HTTP v1 API from Push Service
  DynamoDB: device_push_tokens table
  SQS buffer between fan-out and push service (decouple)
```

### 3.19 Security, Abuse, and Metadata Privacy

```
SERVER-SIDE SECURITY (non-E2E layer):

  Rate limiting (per user, per chat, per IP):
    Token bucket: 60 msg/min per user (1:1)
    Group: 30 msg/min per user in groups > 100
    Implementation: Redis INCR + EXPIRE per minute window

  Spam detection (metadata only):
    Velocity: > 100 new chats started per hour → flag
    Report count: > 5 unique reports in 24h → auto-restrict
    ML on metadata features (not content — E2E)

  Block list:
    user_blocks table: (blocker_id, blocked_id)
    Fan-out worker: filter blocked recipients before delivery
    Check on hot path (Redis cache of block lists)

  Account ban:
    Device token revoked → ingress rejects
    Gateway disconnects active WS
    Messages in flight: delivered; new sends blocked

METADATA MINIMIZATION:

  Server knows: who messaged whom, when, how often, group membership
  Server does NOT know: message content, media content
  Last seen / online: user-configurable hide
  Read receipts: user-configurable disable

GDPR / DELETION:

  User requests account deletion:
    1. Tombstone all messages (sender_id = deleted_user)
    2. Delete inbox rows (user_id partition)
    3. Delete pre-keys, device registry
    4. S3 media: lifecycle delete after 30 days
    5. Kafka: no deletion (retention expires naturally)
  Challenge: messages in OTHER users' chats (as sender)
    → Replace ciphertext with "Message from deleted user" placeholder
    → Or tombstone + client handles display
```

### 3.20 Observability and SLO Design

```
SLIs (Service Level Indicators):

  SLI-1: Message send success rate
    = successful ingress acks / total send attempts
    Target: 99.99%

  SLI-2: Message delivery latency (online recipient)
    = time(ingress_persist) to time(gateway_push_ack)
    Target: p99 < 500ms

  SLI-3: Offline sync completeness
    = messages delivered within 60s of reconnect / total pending
    Target: 99.9%

  SLI-4: WebSocket connection availability
    = successful WS upgrades / total attempts
    Target: 99.95%

SLO ERROR BUDGET:

  99.99% monthly = 4.3 minutes downtime/month
  Burn rate alert: 14.4× normal error rate for 5 min → page

DASHBOARD LAYOUT (Grafana):

  Row 1: Golden signals per region
    Traffic: ingress_qps, ws_connections
    Errors: ingress_5xx, push_failures
    Latency: ingress_p99, fanout_e2e_p99
    Saturation: cassandra_write_p99, kafka_lag

  Row 2: Fan-out health
    Consumer lag heatmap (partition × lag)
    Fan-out mode distribution (WRITE vs READ groups)
    Hot chat_id top 10 by write rate

  Row 3: Infrastructure
    Redis memory, eviction rate
    Gateway CPU, connection count per instance
    MSK broker disk, under-replicated partitions

TRACING (X-Ray / Jaeger):

  Trace ID propagated: client → gateway → ingress → Kafka → fan-out → gateway
  Span: cassandra_write, kafka_publish, redis_lookup, ws_push
  Alert: span cassandra_write > 200ms → annotation with chat_id
```

### 3.21 Cost Model (AWS, Order of Magnitude)

```
MONTHLY COST ESTIMATE (single large region, ap-south-1):

  Gateway fleet: 1,200 × c6gn.4xlarge ($0.68/hr) × 730 hr
    = ~$595,000/month (largest line item)

  EKS (ingress + fan-out): 200 pods × m6g.2xlarge equivalent
    = ~$80,000/month

  MSK: 6 × kafka.m5.2xlarge
    = ~$35,000/month

  Keyspaces: ~500K RCU/WCU sustained (on-demand estimate)
    = ~$120,000/month (high — Cassandra on i3 cheaper at PB scale)

  ElastiCache Redis: 8 shards r6g.2xlarge
    = ~$25,000/month

  S3 media: 30 PB stored (with dedup) × $0.023/GB
    = ~$700,000/month (media dominates storage cost)

  CloudFront: 10 PB egress × $0.02/GB (India pricing)
    = ~$200,000/month

  NLB: LCU charges for 500M connections
    = ~$50,000/month

  TOTAL (rough): ~$1.8M/month per large region
  Global (4 regions): ~$5-7M/month infrastructure
  Per message cost: $5-7M / (50B × 30) = ~$0.000003/msg
  Revenue model: free messaging — cost center; business value in data/ads elsewhere

COST OPTIMIZATION LEVERS:

  1. TWCS + S3 Intelligent-Tiering for old media (60% media cost cut)
  2. Spot instances for fan-out workers (stateless, Kafka-offset safe)
  3. Read fan-out for all groups > 100 (40% Cassandra write reduction)
  4. Connection pooling to Cassandra (reduce coordinator overhead)
  5. Message compression for metadata (not ciphertext — ineffective)
```

### 3.22 Interview Walkthrough — 45-Minute Script

```
MINUTES 0-5: CLARIFY REQUIREMENTS
  "2B users, 100B msg/day, E2E encryption, groups up to 1024,
   multi-device, delivery receipts. Media out of scope for first pass?"

MINUTES 5-10: CAPACITY ESTIMATES
  Show: 580K msg/sec avg, 1.75M peak
  Show: fan-out multiplier 7.7× → inbox write rate
  State: hybrid fan-out avoids 144M writes/sec for large groups

MINUTES 10-20: HIGH-LEVEL DIAGRAM
  Draw: Client → NLB → Gateway (WS) → Ingress → Cassandra + Kafka
  Draw: Fan-out workers → Redis registry → Gateway push
  Mention: S3 for media, Signal Protocol client-side

MINUTES 20-30: DEEP DIVE (interviewer picks one)
  Storage: chat_id partition, TimeUUID clustering, TWCS
  Fan-out: write vs read threshold at 256
  E2E: pre-key directory, server stores ciphertext
  Multi-device: fan-out to all device_ids

MINUTES 30-38: SCALE & FAILURE
  Hot partition: megagroup mitigation
  Kafka lag: consumer scaling WITH Cassandra headroom check
  Reconnect storm: jitter backoff, rolling deploy

MINUTES 38-45: TRADE-OFFS & WRAP
  Keyspaces vs DynamoDB
  Why not PostgreSQL
  What you'd monitor in production
  "Any area you'd like me to go deeper?"
```

---

## 4. Concrete Examples (Extended)

### 4.6 Cassandra UNLOGGED BATCH for Inbox Fan-Out

```cql
-- Fan-out worker: batch inbox writes for one message to 50 recipients
-- UNLOGGED: no atomicity across partitions (OK — independent rows)
BEGIN UNLOGGED BATCH
  INSERT INTO inbox (user_id, inbox_ts, chat_id, server_msg_id, sender_id, preview, unread)
    VALUES ('usr_bob',   6f8e3a20-a1b2-11f0-8000-000000000001, 'chat_alice_bob', 'msg_001', 'usr_alice', '📷 Photo', true);
  INSERT INTO inbox (user_id, inbox_ts, chat_id, server_msg_id, sender_id, preview, unread)
    VALUES ('usr_carol', 6f8e3a20-a1b2-11f0-8000-000000000002, 'grp_team',       'msg_001', 'usr_alice', '📷 Photo', true);
  -- ... up to 50 statements per batch (Cassandra limit: 50KB batch size)
APPLY BATCH;
```

### 4.7 Fan-Out Worker Kafka Consumer (Pseudocode)

```python
# Fan-out worker — production structure
class FanoutConsumer:
    def process(self, event: FanoutEvent):
        # Idempotency guard
        for recipient_id in event.recipient_ids:
            dedup_key = f"fanout:{event.server_msg_id}:{recipient_id}"
            if not self.redis.setnx(dedup_key, "1", ex=3600):
                continue  # already processed

            if event.fanout_mode == "WRITE":
                self.write_inbox(recipient_id, event)

            devices = self.redis.smembers(f"devices:{recipient_id}")
            for device_id in devices:
                conn = self.redis.hgetall(f"conn:{recipient_id}:{device_id}")
                if conn:
                    self.gateway_client.push(
                        gateway=conn["gateway"],
                        conn_id=conn["conn_id"],
                        payload=event.ciphertext_ref,
                    )
                elif self.should_push_notification(recipient_id, event):
                    self.push_queue.enqueue(recipient_id, event)

        self.commit_offset()
```

### 4.8 Ingress Idempotency Table

```cql
CREATE TABLE message_dedup (
  client_msg_id   text,       -- PARTITION KEY
  device_id       text,
  server_msg_id   text,
  created_ts      timestamp,
  PRIMARY KEY ((client_msg_id), device_id)
) WITH default_time_to_live = 86400;  -- 24 hour TTL
```

### 4.9 Group Membership Cache Invalidation

```python
# On GROUP_MEMBER_ADDED Kafka event
def on_member_added(event):
    redis.delete(f"group_members:{event.group_id}")
    # Lazy reload on next fan-out (or warm cache)
    members = cassandra.execute(
        "SELECT user_id FROM group_members WHERE group_id = ?",
        [event.group_id]
    )
    redis.sadd(f"group_members:{event.group_id}", *[m.user_id for m in members])
    redis.expire(f"group_members:{event.group_id}", 3600)

    # E2E: notify all clients to rotate sender keys
    for member_id in members:
        gateway_service.send_control_message(member_id, "KEYS_ROTATION_REQUIRED")
```

### 4.10 MSK Topic Creation

```bash
kafka-topics.sh --bootstrap-server $MSK_BROKER \
  --create \
  --topic msg-fanout-aps1 \
  --partitions 256 \
  --replication-factor 3 \
  --config retention.ms=86400000 \
  --config compression.type=lz4 \
  --config min.insync.replicas=2
```

### 4.11 Gateway Health Endpoint

```go
// GET /health — used by NLB target group
func (g *Gateway) HealthHandler(w http.ResponseWriter, r *http.Request) {
    conns := g.ConnectionCount()
    if conns > g.MaxConnections * 95 / 100 {
        w.WriteHeader(http.StatusServiceUnavailable) // stop new connections
        return
    }
    if g.Draining {
        w.WriteHeader(http.StatusServiceUnavailable)
        return
    }
    w.WriteHeader(http.StatusOK)
    json.NewEncoder(w).Encode(map[string]int{"connections": conns})
}
```

### 4.12 Client Reconnect with Jitter (Week 1 Pattern)

```javascript
// Mobile client — WebSocket reconnect
class WSClient {
  constructor() {
    this.attempt = 0;
  }

  reconnect() {
    const base = Math.min(1000 * Math.pow(2, this.attempt), 30000);
    const jitter = Math.random() * base;
    const delay = base / 2 + jitter;
    this.attempt++;

    setTimeout(() => {
      this.connect();
    }, delay);
  }

  onOpen() {
    this.attempt = 0;  // reset on success
    this.sendSyncRequest();
  }
}
```

---

## 5. Production Patterns (Extended)

```
╔════════════════════════════════════════════════════════════════╗
║   PATTERN 8: CANARY DEPLOY ON FAN-OUT WORKERS                  ║
╟────────────────────────────────────────────────────────────────╢
║   Deploy v2.14.0 to 10% consumers → monitor lag 15 min         ║
║   Compare: batch_write_latency, cassandra_timeout_rate         ║
║   Full fleet only if lag derivative flat and p99 stable        ║
║   Cricket incident: full deploy at 8:45 skipped canary check   ║
╠════════════════════════════════════════════════════════════════╣
║   PATTERN 9: CIRCUIT BREAKER ON CASSANDRA WRITE (Week 6)       ║
╟────────────────────────────────────────────────────────────────╢
║   If cassandra_write_p99 > 500ms for 30s:                      ║
║     Open circuit → pause fan-out consumption (lag grows)       ║
║     BUT ingress still accepts (messages safe in Cassandra)     ║
║     Better: lag than cascade failure to Redis/gateway          ║
║   Half-open: probe 1% traffic after 60s                        ║
╠════════════════════════════════════════════════════════════════╣
║   PATTERN 10: BULKHEAD — SEPARATE CONSUMER GROUPS              ║
╟────────────────────────────────────────────────────────────────╢
║   fanout-workers-1to1: handles 1:1 chats (SLA-critical)        ║
║   fanout-workers-groups: handles group chats (noisy)           ║
║   Separate topics or header routing by chat_type               ║
║   Cricket group cannot starve 1:1 message delivery             ║
╠════════════════════════════════════════════════════════════════╣
║   PATTERN 11: BACKPRESSURE ON INGRESS (Week 6)                 ║
╟────────────────────────────────────────────────────────────────╢
║   If kafka_consumer_lag_sum > 1M:                              ║
║     Ingress returns 503 + Retry-After: 5 for NEW sends         ║
║     Existing messages safe (already in Cassandra)              ║
║     Client queues offline (Signal works offline for encrypt)   ║
║   Per-group rate limit before global throttle                  ║
╠════════════════════════════════════════════════════════════════╣
║   PATTERN 12: PRE-KEY ROTATION CRON                            ║
╟────────────────────────────────────────────────────────────────╢
║   Weekly: rotate signed pre-keys for all active devices        ║
║   Daily: check one_time_prekey_count < 20 → push notification  ║
║   Prevents: "unable to start conversation" during viral growth ║
╚════════════════════════════════════════════════════════════════╝
```

---

## 6. Failure Modes (Extended)

```
FAILURE MODE 9: KAFKA BROKER DISK FULL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: Producer errors; ingress 5xx on Kafka publish
  Cause: Retention 24h × 256 partitions × high volume; broker disk 90%
  Mechanism: acks=1 fails if no ISR broker accepts
  Mitigation: Increase retention cleanup; add brokers; reduce retention
  Prevention: Alert broker disk > 70%; tiered storage (MSK feature)

FAILURE MODE 10: NLB CONNECTION LIMIT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: New users cannot connect; existing OK
  Cause: Gateway fleet at max connections; health check flapping
  Mechanism: NLB routes to "healthy" targets all at capacity
  Mitigation: ASG scale out; enable draining targets at 90% capacity
  Prevention: /health returns 503 at 95% conn count (stop new WS)

FAILURE MODE 11: SPLIT BRAIN CONNECTION REGISTRY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: Message delivered to wrong device or duplicate push
  Cause: Redis Cluster network partition; two gateways register same device
  Mechanism: Fan-out pushes to stale gateway; old connection half-open
  Mitigation: Connection epoch in registry; gateway rejects stale epoch
  Prevention: Redis Cluster min 3 AZ; connection takeover protocol

FAILURE MODE 12: CASSANDRA GC GRACE VIOLATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: Deleted messages reappear; "zombie messages" support tickets
  Cause: Node down > gc_grace_seconds (10 days); tombstone collected
         on live nodes but not repaired node; node rejoins with old data
  Mechanism: Week 5 Cassandra anti-entropy gap
  Mitigation: nodetool repair before rejoin; replace node don't rejoin
  Prevention: Monitor node downtime; auto-replace after 7 days down

FAILURE MODE 13: SNOWFLAKE CLOCK ROLLBACK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: Duplicate server_msg_id collision (extremely rare)
  Cause: NTP step backward on ingress host
  Mechanism: Snowflake sequence resets; same (ts, machine, seq)
  Mitigation: Wait for clock catch-up; fallback to UUID v7
  Prevention: chrony slew not step; monitor clock offset < 1ms

FAILURE MODE 14: MEDIA PRE-SIGNED URL EXPIRY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: "Tap to download" fails; image never loads
  Cause: User offline 2 hours; URL expired (1h TTL); sync retries fail
  Mechanism: Client cached expired URL from message metadata
  Mitigation: Sync service regenerates pre-signed URL on media fetch
  Prevention: Client always requests fresh URL via /v1/media/url API

FAILURE MODE 15: GLOBAL INGRESS THROTTLE DURING REGIONAL INCIDENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Symptom: India cricket incident → engineer throttles ALL ingress
  Cause: Panic response; wrong blast radius
  Mechanism: US and EU users cannot send (unnecessary)
  Mitigation: Per-group or per-region throttle ONLY
  Prevention: Throttle policy scoped by group_id prefix or region tag
```

---

## 7. SRE Diagnostic Toolkit (Extended)

```
ADDITIONAL METRICS:

  fanout_inbox_writes_per_sec{fanout_mode}
  cassandra_partition_write_rate{chat_id}   # top-N cardinality limit
  prekey_count_histogram{device_id}
  sync_payload_bytes_p99
  ws_reconnect_rate{region}
  thundering_herd_indicator = ws_reconnect_rate / ws_connection_rate

ALERT RULES (Prometheus format):

  - alert: KafkaFanoutLagCritical
    expr: kafka_consumer_lag_sum{group="fanout-workers"} > 100000
    for: 2m
    labels: {severity: P1}

  - alert: CassandraWriteLatencyHigh
    expr: cassandra_write_latency_p99 > 200
    for: 1m
    labels: {severity: P1}
    annotations:
      summary: "Check hot partition before scaling consumers"

  - alert: FanoutModeMismatch
    expr: group_member_count > 256 AND fanout_mode == "WRITE"
    for: 0m
    labels: {severity: P2}
    annotations:
      summary: "Group {{ $labels.group_id }} has WRITE fanout with >256 members"

  - alert: RedisEvictingConnRegistry
    expr: rate(redis_evicted_keys[1m]) > 0
    for: 30s
    labels: {severity: P1}

CQL DIAGNOSTIC QUERIES:

  -- Message count for suspected hot chat (from ingress logs)
  SELECT COUNT(*) FROM messages
  WHERE chat_id = 'grp_cricket_2026'
  AND msg_ts > maxTimeuuid('2026-07-06 20:47:00+0000');

  -- Check fanout mode
  SELECT group_id, member_count, fanout_mode FROM groups
  WHERE group_id = 'grp_cricket_2026';

KUBECTL DIAGNOSTICS:

  # Fan-out pod restarts (rebalance storm indicator)
  kubectl get pods -l app=fanout-worker -o json | \
    jq '[.items[] | select(.status.containerStatuses[0].restartCount > 2)]'

  # Ingress error budget burn
  kubectl logs -l app=message-ingress --since=1h | \
    grep -c "cassandra_write_timeout"

  # Gateway draining state
  kubectl exec gw-use1-0042 -- curl -s localhost:8080/health | jq .

NETWORK DIAGNOSTICS:

  # NLB target health
  aws elbv2 describe-target-health \
    --target-group-arn $WS_TARGET_GROUP_ARN \
    --query 'TargetHealthDescriptions[?TargetHealth.State!=`healthy`]'

  # MSK broker connectivity from fan-out pod
  kubectl exec -it fanout-worker-0 -- \
    kafka-broker-api-versions.sh --bootstrap-server $MSK_BROKER

RUNBOOK: KAFKA LAG WITHOUT INGRESS DEGRADATION

  Step 1: kafka-consumer-groups.sh --describe (find hot partitions)
  Step 2: Map partition → chat_id (custom partitioner logs)
  Step 3: Check cassandra_write_latency (NOT consumer CPU)
  Step 4: If hot chat: rate limit + READ fanout switch
  Step 5: If Cassandra healthy + CPU > 70%: scale consumers 25%
  Step 6: Wait 3 min, verify lag derivative negative
  Step 7: NEVER scale consumers 2× in single action during incident

RUNBOOK: WEBSOCKET MASS DISCONNECT

  Step 1: Check for deploy in progress (ArgoCD / rollout status)
  Step 2: Pause deploy if mid-rollout
  Step 3: Verify NLB target health (unhealthy drain)
  Step 4: Enable connection rate limit (WAF or NLB)
  Step 5: Monitor auth service — if 5xx, scale auth first
  Step 6: Client backoff depends on app version — check release %
```

---

## 8. Decision Framework (Extended)

```
STORAGE ENGINE COMPACTION:

  TWCS (Cassandra): time-series messages, predictable TTL
  STCS: avoid — compaction storms on write-heavy
  LCS: media metadata tables only (low write volume)
  DynamoDB: automatic — less control, less ops

CONNECTION GATEWAY LANGUAGE:

  +-------------+-----------+----------+------------------+
  | Language    | Conns/srv | Memory   | Notes            |
  +-------------+-----------+----------+------------------+
  | Erlang/OTP  | 2M        | 10KB/conn| WhatsApp history |
  | Go          | 500K-1M   | 20KB/conn| Production sweet |
  | Rust        | 500K-1M   | 15KB/conn| Memory safety    |
  | Node.js     | 50-100K   | 50KB/conn| GC pauses at scale|
  +-------------+-----------+----------+------------------+
  Interview answer: Go or Erlang for gateway; stateless ingress in any

KAFKA PARTITION KEY:

  chat_id: preserves per-chat ordering (REQUIRED for messaging)
  recipient_id: better load balance but LOSES ordering
  NEVER partition randomly — ordering violation in groups

ID GENERATION:

  Snowflake: time-ordered, sortable, 64-bit (WhatsApp-scale)
  UUID v4: random, no ordering (requires separate sort key)
  UUID v7: time-ordered UUID (modern alternative to Snowflake)
  ULID: lexicographically sortable, 128-bit

PUSH vs PULL SYNC FOR LINKED DEVICES:

  Phone sends message:
    L1: Real-time push to linked devices (if online)
    L2: Inbox self-sync row (if offline)
    L3: Full sync on next WebSocket connect
  Linked device MUST NOT require phone online (except initial QR link)
```

---

## 9. Incident Scenario

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: WhatsApp Messaging (ap-south-1 region)
Time: 8:47 PM IST (peak evening traffic)
Region impact: India (180M DAU homed here)

ARCHITECTURE (ap-south-1):
  Gateway fleet: 1,200 instances (c6gn.4xlarge), NLB fronted
  Message ingress: 80 pods (EKS)
  Fan-out workers: 48 pods, consumer group fanout-workers-aps1
  Kafka MSK: 6 brokers, msg-fanout-aps1 (256 partitions)
  Keyspaces: RF=3, 12 nodes equivalent capacity
  Redis Cluster: 8 shards, r6g.2xlarge
  Peak normal: 420K msg/sec ingress, consumer lag < 500

TIMELINE:

  8:47 PM — PagerDuty: kafka_consumer_lag_sum > 500K (threshold 10K)
            ws_push_success_rate drops to 72% (threshold 99%)
            #whatsapp-down trending on Twitter (cricket match night)

  8:49 PM — On-call checks Grafana:
            • ingress_qps: 420K/sec (NORMAL — not a traffic spike)
            • ingress_latency_p99: 45ms (NORMAL)
            • kafka_consumer_lag: 500K and climbing 50K/min
            • cassandra_write_latency_p99: 890ms (NORMAL is 15ms)
            • fanout_worker_cpu: 38% (NOT CPU bound)
            • redis_memory: 71% (NORMAL)

  8:51 PM — Support escalates: "Messages taking 5+ minutes to arrive"
            Cricket fan group "IND vs AUS Live Chat" (group_id: grp_cricket_2026)
            has 18,000 members — normally 2K msg/sec, now 8K msg/sec
            (India scoring — goal celebration flood)

  8:53 PM — Engineer runs:
            kafka-consumer-groups.sh --describe --group fanout-workers-aps1
            → Partition 147: lag 480,000 (HIGHEST)
            → Partition 147 key owner: chat_id hash = grp_cricket_2026

  8:54 PM — nodetool tablestats on Keyspaces coordinator:
            Partition grp_cricket_2026: write rate 8,200/sec
            Write latency p99: 1,200ms (80× normal)
            Pending compactions: 47 (cluster avg: 3)

  8:55 PM — Secondary symptom: Redis conn registry evictions begin
            redis_evicted_keys: 1,200/sec (memory spike from
            18K members × presence subscriptions = 2.1M extra keys
            created by fan-out worker debugging retry loops)

  8:56 PM — Engineer scales fan-out workers 48 → 96 pods
            (instinctive response)

  8:58 PM — Cassandra write latency WORSENS to 2,100ms p99
            Consumer lag accelerates: now 900K, growth 120K/min
            ws_push_success_rate: 54%

  9:01 PM — Incident commander declares SEV-1
            VP WhatsApp asks for ETA in #exec-war-room
            Cricket board partner calling account team

ADDITIONAL CONTEXT:
  • grp_cricket_2026 was migrated to fanout_mode=WRITE last week
    (bug: migration script missed groups > 10K members)
  • Tonight's match was on marketing calendar — no runbook triggered
  • 8:30 PM deploy: fan-out worker v2.14.0 (canary 10% → full at 8:45)
    Changelog: "optimize inbox batch size 50 → 200"
  • India gateway fleet had rolling deploy 7:00-8:00 PM (completed)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** Draw the cascade chain — trigger, amplifiers, victims. Which system is the ACTIVE cascade (still worsening) vs contained? Quantify the amplification where possible.

**Question 2:** The engineer scaled fan-out workers 48 → 96 at 8:56 PM. Evaluate this decision. What should have been checked FIRST? What is the correct immediate mitigation sequence for minutes 8:56–9:10?

**Question 3:** Cross-system capacity check: Redis started evicting keys at 8:55 PM. Is this a cause, amplifier, or victim in the cascade? What is the blast radius if Redis evicts conn registry keys? State the L1/L2/L3 defense for registry resilience.

**Question 4:** Operational prerequisites: what commands might FAIL right now due to system state? What must you verify before executing Cassandra nodetool or scaling actions?

**Question 5:** Post-mortem deliverables — technical root cause, immediate fix, and three long-term architecture changes. Include stakeholder communication plan and pre-event runbook for scheduled viral events (cricket, elections, New Year).

---

## 10. Expert Analysis

### Question 1: Cascade Chain

```
TRIGGER:
  Cricket goal → grp_cricket_2026 message rate 2K → 8K msg/sec
  Combined with: fanout_mode=WRITE (bug — should be READ for 18K group)
  → Each message = 18,000 inbox writes (write amplification)

AMPLIFIER 1 — WRITE AMPLIFICATION (the force multiplier):
  8K msg/sec × 18,000 inbox writes = 144M Cassandra writes/sec
  (theoretical; batched to ~2.8M actual batch writes/sec)
  Single partition grp_cricket_2026 + 18K inbox partitions
  Cassandra p99: 15ms → 890ms → 2,100ms

AMPLIFIER 2 — FAN-OUT WORKER v2.14.0 DEPLOY:
  Batch size 50 → 200: fewer, larger Cassandra batches
  Larger batches → longer coordinator hold time on hot partition
  Consumer rebalance at 8:45 (full fleet on new version)
  Brief lag spike during rebalance + larger batches hit hot node

AMPLIFIER 3 — SCALE CONSUMERS 48 → 96 (8:56 PM):
  2× consumers = 2× Cassandra write pressure
  Cross-system capacity violation (Handoff Doc growth area)
  Cassandra p99: 890ms → 2,100ms
  Lag growth: 50K/min → 120K/min

VICTIM 1 — KAFKA CONSUMER LAG (ACTIVE CASCADE):
  Consumers cannot commit fast enough
  Lag 500K → 900K and accelerating
  Messages persist in Cassandra (ingress OK) but delivery delayed
  STATUS: ACTIVE — still worsening until write pressure reduced

VICTIM 2 — WS PUSH SUCCESS RATE (ACTIVE CASCADE):
  Fan-out workers timeout on Cassandra writes
  Skip push → fall back to inbox-only path
  Online users not receiving real-time delivery
  STATUS: ACTIVE — coupled to lag

VICTIM 3 — REDIS EVICTIONS (AMPLIFIER → becoming ACTIVE):
  Fan-out retry loops + debugging queries created 2.1M ephemeral keys
  Memory 71% → eviction under pressure
  conn registry keys evicted → push path broken even when Cassandra recovers
  STATUS: CONTAINED if evictions stop; ACTIVE if eviction continues

CONTAINED:
  Ingress (45ms p99 — not affected, AP path healthy)
  Gateway fleet (CPU normal, connections stable)
  Media/S3 (not in this path)

QUANTIFIED AMPLIFICATION:
  Normal group (256 members, WRITE fan-out): 8K msg × 256 = 2M writes/sec
  Actual bug (18K members): 8K × 18,000 = 144M writes/sec
  Amplification factor: 72× vs intended max group size
  Consumer scale mistake: 2× additional pressure on already 80× degraded Cassandra
```

### Question 2: Evaluate Scaling Decision + Correct Mitigation

```
SCALING 48 → 96 WAS WRONG:

  Fan-out workers were at 38% CPU — NOT compute bound
  Lag caused by Cassandra write latency (890ms), not consumer throughput
  Doubling consumers doubled write load on degraded Cassandra
  Classic cross-system capacity failure

SHOULD HAVE CHECKED FIRST:
  1. Cassandra write latency (was 890ms — RED FLAG)
  2. Which partition is hot (partition 147 = grp_cricket_2026)
  3. fanout_mode for that group (WRITE for 18K = bug)
  4. "If I add consumers, can Cassandra handle 2× writes?" → NO

CORRECT MITIGATION SEQUENCE (8:56–9:10):

  MINUTE 0 (8:56): STOP consumer scale-up
    Roll back fan-out worker deploy v2.14.0 → v2.13.0
    (rebalance storm + batch size regression)

  MINUTE 1 (8:57): EMERGENCY — switch grp_cricket_2026 to READ fanout
    UPDATE groups SET fanout_mode='READ' WHERE group_id='grp_cricket_2026'
    Invalidate Redis group cache
    Effect: inbox writes drop from 18K to 0 per message
    Cassandra write pressure drops ~95% within 60 seconds

  MINUTE 2 (8:58): RATE LIMIT grp_cricket_2026
    Server-side: max 50 msg/sec to this group_id
    Client-side push: "High traffic — messages may be delayed"
    Reduces remaining group log writes from 8K to 50/sec

  MINUTE 3 (8:59): DO NOT scale consumers yet
    Wait for Cassandra p99 < 100ms (monitor 2 min)

  MINUTE 5 (9:01): Verify Redis eviction stopped
    If still evicting: redis-cli CONFIG SET maxmemory-policy volatile-lru
    Pin conn registry keys ( separate Redis instance or no-eviction policy)

  MINUTE 7 (9:03): IF lag still growing AND cassandra p99 < 100ms:
    Scale consumers 48 → 64 (modest 33%, NOT 100%)
    Verify lag derivative turns negative within 3 min

  MINUTE 10 (9:06): Stakeholder comms
    Status page: "Delayed message delivery in India region — investigating"
    VP message: "Root cause identified (fan group config), fix deploying,
                 ETA 15 min to clear backlog"
    Cricket partner: direct call — NOT public speculation

  MINUTE 14 (9:10): Lag should be decreasing
    If not: throttle ingress for grp_cricket ONLY (drop to 10 msg/sec)
    NEVER throttle global ingress (cricket is the problem, not 420K/sec normal)
```

### Question 3: Redis Eviction Analysis + Defense Layers

```
REDIS EVICTION: AMPLIFIER (not root cause)

  Root cause: Cassandra slow → fan-out retries → extra Redis lookups
  + engineers running --scan --pattern "conn:*" debugging
  + 18K member presence subscriptions (grp_cricket)
  = memory pressure → eviction of conn registry keys

BLAST RADIUS IF REGISTRY EVICTED:
  Fan-out worker: conn_registry_miss → skip push
  Online users appear offline → messages inbox-only
  ws_push_success_rate: 72% → 54% (observed)
  Users who ARE online don't get real-time delivery
  Data NOT lost (Cassandra inbox has messages)
  User experience: "app shows delivered when I open chat but
                   no notification while online"

L1 (PRIMARY): Separate Redis cluster for conn registry
  Memory: 32 GB dedicated, no eviction policy (noeviction)
  Capacity: 500M keys × 200 bytes = 100 GB → 4-shard cluster
  Handles: conn:*, devices:* only

L2 (FALLBACK): Local gateway cache
  Each gateway caches conn lookups for 30s (in-memory LRU)
  If Redis miss: check peer gateways via gossip (expensive)
  Capacity: 100K connections × 200B = 20 MB per gateway

L3 (LAST RESORT): FCM/APNs push for online-fallback
  If WS push fails after 3 retries → push notification
  "You have a new message" (no content — E2E)
  Latency: 1-30 seconds (worse than WS but better than nothing)
  Capacity: FCM handles 1M/sec globally
```

### Question 4: Operational Prerequisites

```
COMMANDS THAT MIGHT FAIL:

  nodetool tablestats:
    → May timeout if Cassandra coordinators overloaded (p99 2s)
    → Use -Dcom.sun.jmx.remote.port=7199 with 30s timeout
    → Alternative: Grafana cassandra_write_latency (already have data)

  kafka-consumer-groups.sh --describe:
    → Works (Kafka healthy, lag is consumer-side)
    → BUT: resetting offsets is DANGEROUS — do NOT reset to latest
      (would drop 900K undelivered fan-out events)

  kubectl scale deployment fanout-worker --replicas=96:
    → Already executed (the mistake)
    → Rolling pods causes ANOTHER rebalance storm
    → Rollback to 48 requires careful coordination

  redis-cli --scan --pattern "conn:*":
    → BLOCKS Redis (O(N) scan) — engineers may have CAUSED eviction
    → NEVER run SCAN on production Redis during incident
    → Use: redis-cli INFO keyspace + sampled HGETALL instead

VERIFY BEFORE CASSANDRA ACTIONS:

  □ Coordinator reachable: cqlsh -e "SELECT now() FROM system.local"
  □ Not in repair/compaction storm: nodetool compactionstats (timeout OK)
  □ Identify node owning hot partition:
    nodetool ring | grep token_for_grp_cricket_2026
  □ Check disk: df -h on that node (compaction needs disk headroom)

VERIFY BEFORE SCALING CONSUMERS:

  □ Cassandra write p99 < 100ms (MANDATORY)
  □ Redis eviction rate = 0
  □ Consumer CPU > 70% (actually compute bound — was 38%, so NO)
  □ Lag derivative negative (already recovering — don't disturb)
```

### Question 5: Post-Mortem

```
ROOT CAUSE:
  Migration script set fanout_mode=WRITE for grp_cricket_2026
  (18K members) — threshold should enforce READ at > 256 members
  Cricket event + WRITE fan-out = 72× write amplification →
  Cassandra hot partition → fan-out lag → delivery delay

IMMEDIATE FIX:
  1. grp_cricket_2026 → fanout_mode=READ (done during incident)
  2. Audit all groups > 256 members for incorrect fanout_mode
  3. Roll back fan-out v2.14.0 batch size change

LONG-TERM ARCHITECTURE CHANGES:

  1. AUTOMATIC FANOUT MODE ENFORCEMENT
     Trigger: member_count > 256 → fanout_mode=READ (immutable)
     Implementation: Group Service check on MEMBER_ADDED event
     Prevent: migration scripts from overriding without override flag
     Alert: fanout_mode=WRITE AND member_count > 256 → P2 page

  2. HOT PARTITION CIRCUIT BREAKER
     Monitor: cassandra write rate per chat_id partition
     Threshold: > 1000 writes/sec per partition
     Action: auto rate-limit + auto-switch to READ fanout
     L1: rate limit 50/sec, L2: READ fanout, L3: pause group

  3. CROSS-SYSTEM CAPACITY GATE ON AUTOSCALE
     KEDA fan-out scaler: add precondition
     "cassandra_write_p99 < 50ms" before allowing scale-up
     Prevents consumer scale from amplifying storage bottleneck

STAKEHOLDER COMMUNICATION:
  T+0:  Status page + internal war room
  T+15: "Fix deployed, backlog clearing, ETA 30 min normal"
  T+60: "Resolved. India region fully recovered."
  T+24h: Customer blog post (transparency — cricket group config error)
  Cricket partner: direct account manager call at T+15

PRE-EVENT RUNBOOK (viral events):
  7 days before: marketing calendar → engineering review
  3 days before: identify affected groups, verify fanout_mode
  24 hours before: scale Cassandra compaction headroom +20%
  2 hours before: pre-warm Redis, confirm consumer count at 1.5×
  During event: dedicated dashboard for event group_ids
  On-call: assign cricket-specific engineer (not general on-call)
```

---

## 11. Key Takeaways

```
╔════════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:               ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. HYBRID FAN-OUT: write for ≤256 recipients, read for       ║
║      large groups. Wrong mode at 18K members = 72× write       ║
║      amplification — the #1 WhatsApp-scale design decision.    ║
║                                                                ║
║   2. WebSockets deliver; Cassandra stores. Never assume a      ║
║      live connection — persist first, fan-out via Kafka        ║
║      async, push if online else inbox sync on reconnect.       ║
║                                                                ║
║   3. Partition key = chat_id. All messages in a chat           ║
║      co-locate. Hot partition = hot group — sub-shard or       ║
║      read-fan-out. Wrong partition key is a full migration.    ║
║                                                                ║
║   4. E2E (Signal Protocol) means server stores ciphertext —    ║
║      constrains search, moderation, previews. Key directory    ║
║      is the only server-side crypto infrastructure.            ║
║                                                                ║
║   5. Before scaling consumers, verify Cassandra can handle     ║
║      the additional write load. Cross-system capacity is       ║
║      the difference between fixing an incident and making      ║
║      it worse.                                                 ║
╚════════════════════════════════════════════════════════════════╝
```

---

## 12. Targeted Reading

```
REQUIRED:

  1. DDIA Chapter 1, pp 1-10 — "Reliable, Scalable, Maintainable"
     → Three pillars applied to messaging: reliability = no message
     loss after ack; scalability = fan-out math; maintainable = hybrid

  2. DDIA Chapter 11, pp 439-452 — "Stream Processing"
     → Kafka as fan-out backbone; consumer groups; event time vs
     processing time (receipt batching windows)

  3. Signal Protocol Specification — X3DH Key Agreement (Sections 2-3)
     https://signal.org/docs/specifications/x3dh/
     → 30 minute read — enough to explain E2E in interviews
     → Focus: pre-key bundle, Double Ratchet overview (Section 5)

  4. Meta Engineering Blog — "Scaling the WhatsApp Server Stack"
     Search: engineering.fb.com WhatsApp Erlang
     → FreeBSD + Erlang historical architecture; 2M connections/server
     → Understand principles even if stack differs from your AWS design

  5. Week 1 Module: WebSockets.md — Connection Scaling Math section
     → NLB 350s idle timeout; reconnect thundering herd; 100K conn/server

  6. Week 6 Module: Message Queues and Kafka.md — Parts 3-5
     → Partition key design; consumer rebalance; idempotent producer

OPTIONAL:

  7. Amazon Keyspaces Developer Guide — "How it works" + TWCS
     https://docs.aws.amazon.com/keyspaces/latest/devguide/
     → TWCS not available in Keyspaces — use default compaction;
       note this gap if proposing Keyspaces for time-series

  8. AWS MSK Best Practices — Consumer lag monitoring
     https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices.html

  9. "The WhatsApp Architecture" — High Scalability (2012, dated but
     foundational fan-out on write vs read discussion)
     http://highscalability.com/blog/2014/2/26/
     the-whatsapp-architecture-facebook-bought-for-19-billion-dollars.html
```
