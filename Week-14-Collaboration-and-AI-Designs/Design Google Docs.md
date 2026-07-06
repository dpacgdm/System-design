# Design Google Docs: Real-Time Collaborative Editing

---

## Learning Objectives

╔══════════════════════════════════════════════════════════════╗
║ AFTER THIS MODULE, YOU WILL BE ABLE TO:                      ║
╠══════════════════════════════════════════════════════════════╣
║ 1. Design a real-time collaborative document editor          ║
║ end-to-end:                                                  ║
║ document model, sync protocol, persistence, and presence.    ║
║ 2. Choose between Operational Transformation (OT) and CRDTs  ║
║ for a given product constraint and defend the tradeoff.      ║
║ 3. Explain how Google Docs-style systems achieve low-latency ║
║ multi-user editing over WebSockets at scale.                 ║
║ 4. Diagnose collaboration outages: split-brain edits, cursor ║
║ storms, reconnect thundering herds, and version divergence.  ║
║ 5. Size collaboration infrastructure: connections per node,  ║
║ operation throughput, and storage for revision history.      ║
╚══════════════════════════════════════════════════════════════╝
---

## Wrong Mental Models (Destroy These First)

╔══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "Just use WebSockets and broadcast edits"   ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. Naive broadcast creates ordering conflicts when two   ║
║ users edit the same region simultaneously. Without OT or     ║
║ CRDTs you get lost keystrokes, divergent copies, or          ║
║ last-write                                                   ║
║ wins that silently deletes user work.                        ║
╚══════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #2: "CRDTs always beat OT"                      ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. CRDTs simplify server logic but inflate metadata      ║
║ (tombstones, unique IDs) and complicate rich-text            ║
║ structures.                                                  ║
║ Google Docs uses OT variants; Figma and Notion use CRDTs.    ║
║ The choice depends on document model complexity and offline  ║
║ requirements — not Twitter consensus.                        ║
╚══════════════════════════════════════════════════════════════╝

╔════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #3: "The server is source of truth for document text" ║
╠════════════════════════════════════════════════════════════════════╣
║ WRONG. In OT systems the server transforms and orders              ║
║ operations; clients hold optimistic local state. In CRDT           ║
║ systems every replica is a valid partial view that merges.         ║
║ Persistence stores operations or state snapshots — not a           ║
║ single mutable string row you UPDATE on every keystroke.           ║
╚════════════════════════════════════════════════════════════════════╝

╔═══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #4: "Save button = database write per keystroke" ║
╠═══════════════════════════════════════════════════════════════╣
║ WRONG. Keystrokes generate operations buffered in memory.     ║
║ Persistence is batched (every N seconds or M operations).     ║
║ Writing every keystroke to RDS would melt IOPS and create     ║
║ unusable latency. Autosave is a durability policy, not sync.  ║
╚═══════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #5: "WebSocket = one connection per document"   ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. Large products multiplex: one WebSocket carries       ║
║ presence, cursors, comments, and multiple document channels. ║
║ Connection routing uses sticky sessions on NLB/ALB and       ║
║ shard-aware collaboration servers — not naive round-robin.   ║
╚══════════════════════════════════════════════════════════════╝
---

## Core Teaching

### 3.1 The Problem: Concurrent Editing Without Locks

```
THE USER EXPERIENCE YOU ARE BUILDING:

  Alice and Bob edit the same Google Doc simultaneously.
  Alice types "Hello" at position 0.
  Bob types "Hi" at position 0 at the same instant.

  Without a concurrency protocol:
    Alice's client: "Hello"
    Bob's client: "Hi"
    Server receives both. Which wins?
    Last-write-wins → one person's work vanishes.

  With locks (Word track-changes style):
    Bob waits until Alice releases the paragraph.
    Latency spikes. Mobile users rage-quit.

  With OT or CRDTs:
    Both edits merge deterministically.
    Result might be "HiHello" or "HelloHi" — but BOTH edits survive.

THE NON-NEGOTIABLE REQUIREMENTS:

  1. Low latency: local keystroke appears instantly (<16ms paint).
  2. Convergence: all clients reach identical document state.
  3. Intent preservation: edits should land where users meant them.
  4. Offline tolerance (optional but product-defining for mobile).
  5. Scale: millions of concurrent editors, billions of documents.
```

### 3.2 Document Model: Not a String in Postgres

```
RICH TEXT IS A TREE, NOT A STRING:

  Document
    ├── Paragraph (id=p1)
    │     ├── TextRun "Hello" (bold=false)
    │     └── TextRun " world" (bold=true)
    ├── Paragraph (id=p2)
    │     └── TextRun "Second line"
    └── Table (id=t1)
          └── Row → Cell → Paragraph ...

OPERATIONS TARGET STRUCTURAL UNITS:

  insert_text(doc_id, parent_id, offset, text, attrs)
  delete_range(doc_id, parent_id, start, end)
  split_paragraph(paragraph_id, offset)
  set_mark(start, end, mark_type, value)  // bold, link, comment

WHY THIS MATTERS FOR OT/CRDT:

  Plain-text OT algorithms (classic Google Wave papers) assume a
  linear sequence. Rich-text editors compose OT/CRDT per block or
  use a tree CRDT (Yjs Y.Xml, Automerge).

STORAGE REPRESENTATIONS:

  A. Operation log (event sourcing)
     Store ordered/transformed ops. Rebuild doc by replay.
     Pros: audit trail, time travel, compact over snapshots.
     Cons: replay cost grows; need periodic compaction snapshots.

  B. Snapshot + tail log
     S3: snapshot_v482.json + ops since revision 482.
     Pros: fast load (snapshot) + incremental sync (tail).
     Cons: snapshot generation job; schema migration on snapshots.

  C. CRDT state blob
     Store merged CRDT binary (Yjs update vector).
     Pros: no central transform server strictly required.
     Cons: blob size; garbage collection of tombstones.

AWS PATTERN (production):

  DynamoDB: document metadata (owner, ACL, latest_revision)
  S3: periodic snapshots (gzip JSON or CRDT binary)
  DynamoDB Streams / Kinesis: operation fan-out to analytics
  ElastiCache Redis: hot revision counters, presence, session routing
```

### 3.3 Operational Transformation (OT) — Mechanism

#### OT Worked Example 1: Basic insert/delete on single line

```
INITIAL DOCUMENT: "Hello"

Client A (revision 5): insert "Wor" at offset 0
Client B (revision 5): insert "ld" at offset 5

SERVER RECEIVES A FIRST:
  Apply A → doc becomes "WorHello"
  Transform B against A:
    B intended offset 5; A inserted 3 chars at 0
    B' offset = 5 + 3 = 8
  Apply B' → final "WorHellold"

IF SERVER RECEIVED B FIRST (order matters for intermediate states):
  OT guarantees CONVERGENCE regardless of receive order
  because transform(a,b) and transform(b,a) preserve intent.

KEY OT FUNCTIONS (conceptual):

  transform(op_a, op_b) → (op_a', op_b')
    Both ops were created against same base revision.
    Returns adjusted ops valid against each other's effects.

  compose(op_a, op_b) → op_c
    Sequential application collapsed (used in compaction).

SERVER RESPONSIBILITIES IN OT:

  1. Assign monotonic revision numbers per document.
  2. Buffer ops until all prior revisions acknowledged (causal order).
  3. Transform incoming op against concurrent ops since client's base.
  4. Broadcast transformed op to all connected clients.
  5. Reject or buffer ops with revision gap (client must catch up).

CLIENT RESPONSIBILITIES:

  1. Apply local ops optimistically (zero perceived latency).
  2. Track buffer of unacknowledged local ops.
  3. On ack: mark op confirmed, slide revision forward.
  4. On remote op: transform pending local ops against remote op.
  5. On revision gap: fetch missing ops from server/history API.
```
#### OT Worked Example 2: Concurrent inserts at same index

```
INITIAL DOCUMENT: "abc"

Client A (revision 5): insert "XY" at offset 0
Client B (revision 5): insert "Z" at offset 3

SERVER RECEIVES A FIRST:
  Apply A → doc becomes "XYabc"
  Transform B against A:
    B intended offset 3; A inserted 2 chars at 0
    B' offset = 3 + 2 = 5
  Apply B' → final "XYabcZ"

IF SERVER RECEIVED B FIRST (order matters for intermediate states):
  OT guarantees CONVERGENCE regardless of receive order
  because transform(a,b) and transform(b,a) preserve intent.

KEY OT FUNCTIONS (conceptual):

  transform(op_a, op_b) → (op_a', op_b')
    Both ops were created against same base revision.
    Returns adjusted ops valid against each other's effects.

  compose(op_a, op_b) → op_c
    Sequential application collapsed (used in compaction).

SERVER RESPONSIBILITIES IN OT:

  1. Assign monotonic revision numbers per document.
  2. Buffer ops until all prior revisions acknowledged (causal order).
  3. Transform incoming op against concurrent ops since client's base.
  4. Broadcast transformed op to all connected clients.
  5. Reject or buffer ops with revision gap (client must catch up).

CLIENT RESPONSIBILITIES:

  1. Apply local ops optimistically (zero perceived latency).
  2. Track buffer of unacknowledged local ops.
  3. On ack: mark op confirmed, slide revision forward.
  4. On remote op: transform pending local ops against remote op.
  5. On revision gap: fetch missing ops from server/history API.
```
#### OT Worked Example 3: Concurrent insert + delete overlap

```
INITIAL DOCUMENT: "quick brown fox"

Client A (revision 5): insert "slo" at offset 0
Client B (revision 5): insert "w" at offset 15

SERVER RECEIVES A FIRST:
  Apply A → doc becomes "sloquick brown fox"
  Transform B against A:
    B intended offset 15; A inserted 3 chars at 0
    B' offset = 15 + 3 = 18
  Apply B' → final "sloquick brown foxw"

IF SERVER RECEIVED B FIRST (order matters for intermediate states):
  OT guarantees CONVERGENCE regardless of receive order
  because transform(a,b) and transform(b,a) preserve intent.

KEY OT FUNCTIONS (conceptual):

  transform(op_a, op_b) → (op_a', op_b')
    Both ops were created against same base revision.
    Returns adjusted ops valid against each other's effects.

  compose(op_a, op_b) → op_c
    Sequential application collapsed (used in compaction).

SERVER RESPONSIBILITIES IN OT:

  1. Assign monotonic revision numbers per document.
  2. Buffer ops until all prior revisions acknowledged (causal order).
  3. Transform incoming op against concurrent ops since client's base.
  4. Broadcast transformed op to all connected clients.
  5. Reject or buffer ops with revision gap (client must catch up).

CLIENT RESPONSIBILITIES:

  1. Apply local ops optimistically (zero perceived latency).
  2. Track buffer of unacknowledged local ops.
  3. On ack: mark op confirmed, slide revision forward.
  4. On remote op: transform pending local ops against remote op.
  5. On revision gap: fetch missing ops from server/history API.
```
#### OT Worked Example 4: Split paragraph then edit

```
INITIAL DOCUMENT: "para1|para2"

Client A (revision 5): insert "mer" at offset 0
Client B (revision 5): insert "ge" at offset 11

SERVER RECEIVES A FIRST:
  Apply A → doc becomes "merpara1|para2"
  Transform B against A:
    B intended offset 11; A inserted 3 chars at 0
    B' offset = 11 + 3 = 14
  Apply B' → final "merpara1|para2ge"

IF SERVER RECEIVED B FIRST (order matters for intermediate states):
  OT guarantees CONVERGENCE regardless of receive order
  because transform(a,b) and transform(b,a) preserve intent.

KEY OT FUNCTIONS (conceptual):

  transform(op_a, op_b) → (op_a', op_b')
    Both ops were created against same base revision.
    Returns adjusted ops valid against each other's effects.

  compose(op_a, op_b) → op_c
    Sequential application collapsed (used in compaction).

SERVER RESPONSIBILITIES IN OT:

  1. Assign monotonic revision numbers per document.
  2. Buffer ops until all prior revisions acknowledged (causal order).
  3. Transform incoming op against concurrent ops since client's base.
  4. Broadcast transformed op to all connected clients.
  5. Reject or buffer ops with revision gap (client must catch up).

CLIENT RESPONSIBILITIES:

  1. Apply local ops optimistically (zero perceived latency).
  2. Track buffer of unacknowledged local ops.
  3. On ack: mark op confirmed, slide revision forward.
  4. On remote op: transform pending local ops against remote op.
  5. On revision gap: fetch missing ops from server/history API.
```

### 3.4 CRDTs — Mechanism (Week 8 Integration)

```
CRDT = Conflict-free Replicated Data Type

MATHEMATICAL GUARANTEE:
  Merge is commutative, associative, idempotent.
  Any order of applying updates → same final state.

TWO FAMILIES:

  1. State-based (CvRDT): merge(full_state_a, full_state_b)
  2. Operation-based (CmRDT): apply(op) without transform if
     delivery is exactly-once causal broadcast

TEXT CRDT APPROACHES:

  RGA (Replicated Growable Array):
    Each character has unique ID (site_id, counter).
    Tombstone on delete (never physically remove immediately).
    Insert position determined by ID ordering + parent reference.

  LSEQ / Logoot:
    Fractional positions between IDs — less metadata than linked list.

  YATA (used in Yjs):
    Optimized for text editing; handles concurrent inserts at same
    spot with deterministic tie-break (client_id).

EXAMPLE — TWO INSERTS AT POSITION 0:

  Site A inserts 'X' → ID (A,1)
  Site B inserts 'Y' → ID (B,1)

  Merge order by ID: (A,1) before (B,1) if A < B lexicographically
  Result: "XY" + rest of document on ALL replicas.

  NO SERVER TRANSFORM REQUIRED for convergence.
  Server may still exist for auth, persistence, indexing.

GARBAGE COLLECTION:

  Tombstones accumulate. Production systems run GC after quiescent
  period (no concurrent editors) or compact on snapshot save.

WHEN CRDT WINS:

  - Offline-first mobile (ops queue locally, merge on reconnect)
  - Peer-to-peer or edge-heavy (serverless sync)
  - Simpler mental model for engineers (no transform matrix hell)

WHEN OT WINS:

  - Strict central ordering needed for compliance audit
  - Smaller metadata for long-lived enterprise documents
  - Mature tooling in Google Docs / Microsoft 365 stacks
```

### 3.5 Real-Time Transport: WebSockets Architecture

```
WHY WEBSOCKETS FOR COLLABORATION:

  Keystroke → op generated every 50-200ms during active typing.
  HTTP polling at 100ms = 10 req/s/user × 100K users = 1M RPS waste.
  WebSocket: full-duplex, ~2 bytes frame overhead per message.

CONNECTION LIFECYCLE:

  Client                    ALB/NLB                  Collab Server
    │                          │                          │
    │── HTTPS GET /doc/ws ────►│                          │
    │   Upgrade: websocket     │── sticky route ─────────►│
    │◄── 101 Switching ────────│◄─────────────────────────│
    │                          │                          │
    │── auth JWT in 1st frame ─►│─────────────────────────►│
    │◄── session_id + rev 482 ─│◄─────────────────────────│
    │                          │                          │
    │── op(insert, ...) ──────►│─────────────────────────►│
    │◄── ack(rev 483) ─────────│◄─────────────────────────│
    │◄── broadcast(op B) ──────│◄─────────────────────────│

AWS DEPLOYMENT PATTERN:

  Route 53 → CloudFront (static) + ALB (WebSocket API)
  ALB:
    - idle timeout: 3600s (default 60s kills long edits)
    - stickiness: duration-based cookie (lb_cookie)
    - target: ECS/Fargate collab service (NOT Lambda for WS)

  NLB alternative:
    - Preserves source IP, lower latency
    - You implement stickiness in app layer (consistent hash on doc_id)

MESSAGE PROTOCOL (JSON or protobuf):

  {
    "type": "op",
    "doc_id": "d_8f3a",
    "base_rev": 482,
    "op": {"kind":"insert","parent":"p1","offset":12,"text":"a"},
    "client_id": "c_991",
    "op_id": "o_local_44"
  }

  {
    "type": "ack",
    "doc_id": "d_8f3a",
    "rev": 483,
    "op_id": "o_local_44"
  }

  {
    "type": "presence",
    "user_id": "u_12",
    "cursor": {"parent":"p1","offset":12},
    "color": "#4285f4",
    "selection": {"start":10,"end":15}
  }

BACKPRESSURE:

  Fast typist: 10 ops/sec. Server must not block event loop.
  Pattern: per-connection outbound queue (max 1000 msgs).
  Drop presence before dropping ops. Disconnect if op queue full.

RECONNECT STORM:

  Region blip → 50K clients reconnect in 5 seconds.
  Mitigation:
    - Jittered exponential backoff (100ms + random 0-500ms)
    - Server-side rate limit on auth/handshake per IP
    - Sync via HTTP catch-up API before resuming live stream
```

### 3.6 Presence, Cursors, and Ephemeral State

```
PRESENCE IS NOT DOCUMENT STATE:

  Cursors update 10-30 times/sec during mouse movement.
  NEVER persist cursors to S3/DynamoDB per update.
  Store in Redis with TTL 30s: HSET presence:{doc_id} {user_id} {json}

BROADCAST STRATEGY:

  Option A: Server fan-out to all doc subscribers (simple, O(n) per move)
  Option B: Interest management — only send to users viewing same page
  Option C: Throttle cursor updates to 5/sec; interpolate on client

AWS IMPLEMENTATION:

  ElastiCache Redis Cluster:
    Key: presence:{doc_id}
    Value: hash of user_id → {cursor, color, last_seen}
  Pub/Sub channel: doc:{doc_id}:presence for cross-server fan-out
  When collab server A receives cursor, publishes to Redis;
  server B subscribers push to their local WS connections.

COMMENT THREADS VS LIVE EDITS:

  Comments are semi-static — REST API + occasional WS notify.
  Live edits are high-frequency — WS only.
  Mixing both on same channel requires priority queues.

```

### 3.7 Persistence, Revision History, and Compaction

```
REVISION HISTORY USER STORY:

  "Version history → see edits from Tuesday 3pm → restore"

  Requires immutable operation log with timestamps and author IDs.

STORAGE LAYOUT ON S3:

  s3://docs-snapshots/{doc_id}/rev_0000500.snapshot.gz
  s3://docs-ops/{doc_id}/rev_0000501_0000600.ops.gz

  Load path:
    1. Fetch latest snapshot <= target revision
    2. Replay ops until target revision
    3. Render or fork new document from that point

COMPACTION JOB (EventBridge every 5 min):

  For docs with >1000 ops since last snapshot:
    - Load snapshot + ops
    - Apply to build new snapshot at head revision
    - Delete op segments older than retention (unless legal hold)

DYNAMODB METADATA TABLE:

  PK: DOC#{doc_id}
  SK: META
  Attributes: owner_id, head_revision, snapshot_rev, acl, updated_at

  GSI: user_id → list of owned/shared docs

LEGAL HOLD / eDISCOVERY:

  Ops log in S3 Object Lock (WORM mode).
  Never compact held documents.
  Separate Glacier tier for docs inactive >1 year.

```

### 3.8 Authorization, Sharing, and Multi-Tenant Isolation

```
PER-DOCUMENT ACL:

  Roles: owner, editor, commenter, viewer
  Enforced at:
    1. WebSocket handshake (JWT contains doc_id + role claim)
    2. Every op application (server rejects insert if viewer)
    3. History API (viewer cannot fetch op log)

SHARE LINK MODEL:

  link_token → scoped role (commenter)
  Token in URL fragment (#) not query — avoids log leakage
  Rotate token on role change; invalidate active sessions

TENANT ISOLATION:

  Large enterprise: dedicated collab shard per tenant
  Consumer scale: doc_id hash → collab cluster partition
  No cross-tenant Redis keys — prefix all keys with tenant_id

AWS IAM + KMS:

  S3 bucket per tenant class (free vs enterprise)
  CMK per enterprise customer for snapshot encryption
  CloudTrail on all GetObject for compliance exports

```

### 3.9 Scaling Collaboration Servers

```
BOTTLENECK MATH:

  1 collab server (8 vCPU, 16GB):
    ~20K idle WebSocket connections (memory ~500KB each = 10GB)
    ~2K actively typing docs × 5 ops/sec = 10K ops/sec aggregate
    CPU bound on transform/JSON encode before memory bound

SHARDING BY DOCUMENT ID:

  consistent_hash(doc_id) → server pool member
  Client discovers shard via HTTP redirect on first connect:
    GET /docs/{id}/session → { "ws_url": "wss://collab-7.example.com" }

  Migration: dual-write presence during rebalance; drain old shard.

CROSS-SHARD OPERATIONS (rare):

  Linked docs, embeds — treat as separate doc_ids; client multiplexes WS.

GLOBAL DEPLOYMENT:

  User in Tokyo edits doc owned in us-east-1:
    Option A: Home region authority (Tokyo ops RTT 150ms — bad UX)
    Option B: Geo-routed collab replica with async cross-region log merge
    Option C: CRDT edge replicas (Figma-style) — complex

  Google Docs pattern: document has home region; geo routing sends
  you to nearest edge that proxies to home (still latency on op ack).

AUTO SCALING TRIGGERS:

  Custom metric: connections_per_task > 15000 → scale out
  Custom metric: op_processing_lag_p99 > 100ms → scale out
  NOT CPU alone — WS idle connections burn memory not CPU.

```

### 3.10 Offline Editing and Sync on Reconnect

```
OFFLINE QUEUE (mobile / flaky WiFi):

  Client stores pending ops in IndexedDB with base_rev at disconnect.
  On reconnect:
    1. HTTP GET /docs/{id}/ops?since_rev=482
    2. Apply remote ops to local doc
    3. Transform or merge local pending ops against remote
    4. Resubmit pending ops with updated base_rev
    5. Resume WebSocket

CRDT PATH:

  Merge remote update vector with local — no transform step.
  May need conflict UI for semantic conflicts (two titles edited).

OT PATH:

  Client sends catch-up request; server returns transformed ops.
  Client rebases local queue: for each pending op, transform against
  each incoming remote op since base_rev.

DUPLICATE SUBMISSION IDEMPOTENCY:

  op_id UUID on every op.
  Server dedup table (Redis SET doc:{id}:op_ids TTL 24h).
  Retry after timeout must not double-apply insert.

```

### 3.11 Deep Dive Topic 1: Production Edge Cases

```
EDGE CASE 1: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 1100 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.12 Deep Dive Topic 2: Production Edge Cases

```
EDGE CASE 2: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 1200 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.13 Deep Dive Topic 3: Production Edge Cases

```
EDGE CASE 3: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 1300 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.14 Deep Dive Topic 4: Production Edge Cases

```
EDGE CASE 4: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 1400 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.15 Deep Dive Topic 5: Production Edge Cases

```
EDGE CASE 5: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 1500 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.16 Deep Dive Topic 6: Production Edge Cases

```
EDGE CASE 6: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 1600 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.17 Deep Dive Topic 7: Production Edge Cases

```
EDGE CASE 7: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 1700 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.18 Deep Dive Topic 8: Production Edge Cases

```
EDGE CASE 8: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 1800 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.19 Deep Dive Topic 9: Production Edge Cases

```
EDGE CASE 9: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 1900 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.20 Deep Dive Topic 10: Production Edge Cases

```
EDGE CASE 10: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 2000 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.21 Deep Dive Topic 11: Production Edge Cases

```
EDGE CASE 11: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 2100 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.22 Deep Dive Topic 12: Production Edge Cases

```
EDGE CASE 12: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 2200 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.23 Deep Dive Topic 13: Production Edge Cases

```
EDGE CASE 13: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 2300 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.24 Deep Dive Topic 14: Production Edge Cases

```
EDGE CASE 14: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 2400 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.25 Deep Dive Topic 15: Production Edge Cases

```
EDGE CASE 15: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 2500 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.26 Deep Dive Topic 16: Production Edge Cases

```
EDGE CASE 16: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 2600 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.27 Deep Dive Topic 17: Production Edge Cases

```
EDGE CASE 17: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 2700 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.28 Deep Dive Topic 18: Production Edge Cases

```
EDGE CASE 18: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 2800 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.29 Deep Dive Topic 19: Production Edge Cases

```
EDGE CASE 19: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 2900 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.30 Deep Dive Topic 20: Production Edge Cases

```
EDGE CASE 20: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 3000 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.31 Deep Dive Topic 21: Production Edge Cases

```
EDGE CASE 21: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 3100 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.32 Deep Dive Topic 22: Production Edge Cases

```
EDGE CASE 22: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 3200 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.33 Deep Dive Topic 23: Production Edge Cases

```
EDGE CASE 23: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 3300 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.34 Deep Dive Topic 24: Production Edge Cases

```
EDGE CASE 24: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 3400 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.35 Deep Dive Topic 25: Production Edge Cases

```
EDGE CASE 25: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 3500 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.36 Deep Dive Topic 26: Production Edge Cases

```
EDGE CASE 26: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 3600 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.37 Deep Dive Topic 27: Production Edge Cases

```
EDGE CASE 27: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 3700 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.38 Deep Dive Topic 28: Production Edge Cases

```
EDGE CASE 28: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 3800 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.39 Deep Dive Topic 29: Production Edge Cases

```
EDGE CASE 29: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 3900 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

### 3.40 Deep Dive Topic 30: Production Edge Cases

```
EDGE CASE 30: Concurrent structural operations

  Scenario: User A splits paragraph while User B bolds across the split point.

  OT approach:
    Transform split_paragraph op against set_mark op.
    Mark range may need splitting across two new paragraph IDs.
    Server assigns new paragraph ID; broadcast ID mapping event.

  CRDT approach:
    Tree CRDT moves mark anchors with structure changes automatically
    if marks attach to character IDs not positional offsets.

  Test matrix: generate 10K random interleaved structural + text ops;
  property test: replay all permutations → identical canonical JSON.

METRICS TO TRACK:
  transform_latency_ms{doc_size_bucket}
  pending_ops_queue_depth{client_id}
  revision_gap_fetch_count (indicates network partition recovery)

INTERVIEW TALKING POINT:
  "We property-test convergence nightly with QuickCheck-style op
   sequences up to 4000 operations per document model."

AWS CONFIG SNIPPET — ALB WebSocket health check:
  Health check path: /healthz (HTTP 200 on collab server)
  Matcher: 200
  Interval: 30s
  Unhealthy threshold: 2
  Stickiness: enabled, duration 86400 seconds

  Common misconfig: health check hits wrong port → all targets drained
  → every reconnect hits origin storm → P1 incident.
```

---

## Concrete Examples

### Example: Google Docs (OT + central server)

```
Central transformation server orders all operations. Clients optimistic. Proprietary rich-text OT. Home-region document authority.

ARCHITECTURE SKETCH:

  +--------+     +-----+     +-------------+     +----------+
  | Client |---->| ALB |---->| Collab Svc  |---->| DynamoDB |
  +--------+     +-----+     +------+------+     +----------+
                                   |
                    +--------------+--------------+
                    |              |              |
               +----v----+   +-----v-----+  +-----v-----+
               | Redis   |   | S3 snaps  |  | Kinesis   |
               | presence|   | + op logs |  | analytics |
               +---------+   +-----------+  +-----------+
```

DETAIL LAYER 1 — Google Docs (OT + central server):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 2 — Google Docs (OT + central server):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 3 — Google Docs (OT + central server):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 4 — Google Docs (OT + central server):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 5 — Google Docs (OT + central server):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)
### Example: Notion (block CRDT)

```
Each block is CRDT-synchronized unit. Offline edits merge on sync. Block IDs are stable UUIDs — moves are reparent operations.

ARCHITECTURE SKETCH:

  +--------+     +-----+     +-------------+     +----------+
  | Client |---->| ALB |---->| Collab Svc  |---->| DynamoDB |
  +--------+     +-----+     +------+------+     +----------+
                                   |
                    +--------------+--------------+
                    |              |              |
               +----v----+   +-----v-----+  +-----v-----+
               | Redis   |   | S3 snaps  |  | Kinesis   |
               | presence|   | + op logs |  | analytics |
               +---------+   +-----------+  +-----------+
```

DETAIL LAYER 1 — Notion (block CRDT):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 2 — Notion (block CRDT):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 3 — Notion (block CRDT):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 4 — Notion (block CRDT):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 5 — Notion (block CRDT):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)
### Example: Figma (multiplayer CRDT)

```
Custom CRDT for scene graph. Sub-millisecond local updates. AWS-hosted; geo-distributed replicas.

ARCHITECTURE SKETCH:

  +--------+     +-----+     +-------------+     +----------+
  | Client |---->| ALB |---->| Collab Svc  |---->| DynamoDB |
  +--------+     +-----+     +------+------+     +----------+
                                   |
                    +--------------+--------------+
                    |              |              |
               +----v----+   +-----v-----+  +-----v-----+
               | Redis   |   | S3 snaps  |  | Kinesis   |
               | presence|   | + op logs |  | analytics |
               +---------+   +-----------+  +-----------+
```

DETAIL LAYER 1 — Figma (multiplayer CRDT):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 2 — Figma (multiplayer CRDT):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 3 — Figma (multiplayer CRDT):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 4 — Figma (multiplayer CRDT):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 5 — Figma (multiplayer CRDT):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)
### Example: Confluence (OT with lock fallback)

```
Page-level edit lock for legacy; real-time comments separate channel.

ARCHITECTURE SKETCH:

  +--------+     +-----+     +-------------+     +----------+
  | Client |---->| ALB |---->| Collab Svc  |---->| DynamoDB |
  +--------+     +-----+     +------+------+     +----------+
                                   |
                    +--------------+--------------+
                    |              |              |
               +----v----+   +-----v-----+  +-----v-----+
               | Redis   |   | S3 snaps  |  | Kinesis   |
               | presence|   | + op logs |  | analytics |
               +---------+   +-----------+  +-----------+
```

DETAIL LAYER 1 — Confluence (OT with lock fallback):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 2 — Confluence (OT with lock fallback):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 3 — Confluence (OT with lock fallback):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 4 — Confluence (OT with lock fallback):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 5 — Confluence (OT with lock fallback):

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)
### Example: AWS Architecture — hypothetical Docs clone

```
Route53 + ALB + ECS collab fleet + DynamoDB metadata + S3 snapshots + Redis presence.

ARCHITECTURE SKETCH:

  +--------+     +-----+     +-------------+     +----------+
  | Client |---->| ALB |---->| Collab Svc  |---->| DynamoDB |
  +--------+     +-----+     +------+------+     +----------+
                                   |
                    +--------------+--------------+
                    |              |              |
               +----v----+   +-----v-----+  +-----v-----+
               | Redis   |   | S3 snaps  |  | Kinesis   |
               | presence|   | + op logs |  | analytics |
               +---------+   +-----------+  +-----------+
```

DETAIL LAYER 1 — AWS Architecture — hypothetical Docs clone:

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 2 — AWS Architecture — hypothetical Docs clone:

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 3 — AWS Architecture — hypothetical Docs clone:

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 4 — AWS Architecture — hypothetical Docs clone:

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

DETAIL LAYER 5 — AWS Architecture — hypothetical Docs clone:

  Latency budget breakdown (p95):
    Local optimistic apply:     1 ms
    WS round-trip to ack:      30-80 ms (same region)
    Cross-region ack:         120-200 ms
    History restore (500 rev): 800 ms (snapshot + replay)

  Failure isolation:
    Presence channel down → editing continues, cursors stale.
    Op log write fail → buffer ops, block ack, show "saving..." banner.
    Transform error → quarantine doc, force read-only, page on-call.

  Cost drivers (10M MAU, 1M DAU editing):
    Collab ECS: ~$45K/mo (80 tasks r6g.xlarge)
    ElastiCache: ~$12K/mo (cluster mode, 3 shards)
    S3 + DynamoDB: ~$8K/mo (ops + snapshots)
    Data transfer: ~$15K/mo (WS egress dominates)

---

## Production Patterns

### Pattern: Optimistic UI with shadow revision tracking

```
WHY TEAMS USE THIS:
  Optimistic UI with shadow revision tracking addresses a specific production pain discovered after MVP.

IMPLEMENTATION CHECKLIST:
  [ ] Metric emitted before feature flag enable
  [ ] Rollback documented (one CLI command)
  [ ] Load test scenario in CI (k6 or Locust WS plugin)
  [ ] Runbook linked from alert annotation

ROLLBACK TRIGGERS:
  p99 op ack latency > 500ms for 5 minutes
  revision_gap_fetch_rate > 10/sec per doc (indicates transform bug)
  error_rate(transform) > 0.01%

CODE REVIEW GATE:
  Any change to transform merge logic requires dual approval +
  property test run in CI (min 30 minute job).
```

OPERATIONAL NOTE 1:
  On-call runbook entry for "Optimistic UI with shadow revision tracking" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 2:
  On-call runbook entry for "Optimistic UI with shadow revision tracking" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 3:
  On-call runbook entry for "Optimistic UI with shadow revision tracking" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.
### Pattern: Periodic snapshot + tail op log (never full replay on open)

```
WHY TEAMS USE THIS:
  Periodic snapshot + tail op log (never full replay on open) addresses a specific production pain discovered after MVP.

IMPLEMENTATION CHECKLIST:
  [ ] Metric emitted before feature flag enable
  [ ] Rollback documented (one CLI command)
  [ ] Load test scenario in CI (k6 or Locust WS plugin)
  [ ] Runbook linked from alert annotation

ROLLBACK TRIGGERS:
  p99 op ack latency > 500ms for 5 minutes
  revision_gap_fetch_rate > 10/sec per doc (indicates transform bug)
  error_rate(transform) > 0.01%

CODE REVIEW GATE:
  Any change to transform merge logic requires dual approval +
  property test run in CI (min 30 minute job).
```

OPERATIONAL NOTE 1:
  On-call runbook entry for "Periodic snapshot + tail op log (never full replay on open)" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 2:
  On-call runbook entry for "Periodic snapshot + tail op log (never full replay on open)" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 3:
  On-call runbook entry for "Periodic snapshot + tail op log (never full replay on open)" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.
### Pattern: Idempotent op submission with client-generated op_id

```
WHY TEAMS USE THIS:
  Idempotent op submission with client-generated op_id addresses a specific production pain discovered after MVP.

IMPLEMENTATION CHECKLIST:
  [ ] Metric emitted before feature flag enable
  [ ] Rollback documented (one CLI command)
  [ ] Load test scenario in CI (k6 or Locust WS plugin)
  [ ] Runbook linked from alert annotation

ROLLBACK TRIGGERS:
  p99 op ack latency > 500ms for 5 minutes
  revision_gap_fetch_rate > 10/sec per doc (indicates transform bug)
  error_rate(transform) > 0.01%

CODE REVIEW GATE:
  Any change to transform merge logic requires dual approval +
  property test run in CI (min 30 minute job).
```

OPERATIONAL NOTE 1:
  On-call runbook entry for "Idempotent op submission with client-generated op_id" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 2:
  On-call runbook entry for "Idempotent op submission with client-generated op_id" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 3:
  On-call runbook entry for "Idempotent op submission with client-generated op_id" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.
### Pattern: Sticky WebSocket routing with graceful connection migration

```
WHY TEAMS USE THIS:
  Sticky WebSocket routing with graceful connection migration addresses a specific production pain discovered after MVP.

IMPLEMENTATION CHECKLIST:
  [ ] Metric emitted before feature flag enable
  [ ] Rollback documented (one CLI command)
  [ ] Load test scenario in CI (k6 or Locust WS plugin)
  [ ] Runbook linked from alert annotation

ROLLBACK TRIGGERS:
  p99 op ack latency > 500ms for 5 minutes
  revision_gap_fetch_rate > 10/sec per doc (indicates transform bug)
  error_rate(transform) > 0.01%

CODE REVIEW GATE:
  Any change to transform merge logic requires dual approval +
  property test run in CI (min 30 minute job).
```

OPERATIONAL NOTE 1:
  On-call runbook entry for "Sticky WebSocket routing with graceful connection migration" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 2:
  On-call runbook entry for "Sticky WebSocket routing with graceful connection migration" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 3:
  On-call runbook entry for "Sticky WebSocket routing with graceful connection migration" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.
### Pattern: Separate hot path (ops) from cold path (comments, exports)

```
WHY TEAMS USE THIS:
  Separate hot path (ops) from cold path (comments, exports) addresses a specific production pain discovered after MVP.

IMPLEMENTATION CHECKLIST:
  [ ] Metric emitted before feature flag enable
  [ ] Rollback documented (one CLI command)
  [ ] Load test scenario in CI (k6 or Locust WS plugin)
  [ ] Runbook linked from alert annotation

ROLLBACK TRIGGERS:
  p99 op ack latency > 500ms for 5 minutes
  revision_gap_fetch_rate > 10/sec per doc (indicates transform bug)
  error_rate(transform) > 0.01%

CODE REVIEW GATE:
  Any change to transform merge logic requires dual approval +
  property test run in CI (min 30 minute job).
```

OPERATIONAL NOTE 1:
  On-call runbook entry for "Separate hot path (ops) from cold path (comments, exports)" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 2:
  On-call runbook entry for "Separate hot path (ops) from cold path (comments, exports)" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 3:
  On-call runbook entry for "Separate hot path (ops) from cold path (comments, exports)" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.
### Pattern: Feature flag: CRDT mode per tenant for gradual rollout

```
WHY TEAMS USE THIS:
  Feature flag: CRDT mode per tenant for gradual rollout addresses a specific production pain discovered after MVP.

IMPLEMENTATION CHECKLIST:
  [ ] Metric emitted before feature flag enable
  [ ] Rollback documented (one CLI command)
  [ ] Load test scenario in CI (k6 or Locust WS plugin)
  [ ] Runbook linked from alert annotation

ROLLBACK TRIGGERS:
  p99 op ack latency > 500ms for 5 minutes
  revision_gap_fetch_rate > 10/sec per doc (indicates transform bug)
  error_rate(transform) > 0.01%

CODE REVIEW GATE:
  Any change to transform merge logic requires dual approval +
  property test run in CI (min 30 minute job).
```

OPERATIONAL NOTE 1:
  On-call runbook entry for "Feature flag: CRDT mode per tenant for gradual rollout" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 2:
  On-call runbook entry for "Feature flag: CRDT mode per tenant for gradual rollout" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 3:
  On-call runbook entry for "Feature flag: CRDT mode per tenant for gradual rollout" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.
### Pattern: Load test with synthetic typing models (not constant ping)

```
WHY TEAMS USE THIS:
  Load test with synthetic typing models (not constant ping) addresses a specific production pain discovered after MVP.

IMPLEMENTATION CHECKLIST:
  [ ] Metric emitted before feature flag enable
  [ ] Rollback documented (one CLI command)
  [ ] Load test scenario in CI (k6 or Locust WS plugin)
  [ ] Runbook linked from alert annotation

ROLLBACK TRIGGERS:
  p99 op ack latency > 500ms for 5 minutes
  revision_gap_fetch_rate > 10/sec per doc (indicates transform bug)
  error_rate(transform) > 0.01%

CODE REVIEW GATE:
  Any change to transform merge logic requires dual approval +
  property test run in CI (min 30 minute job).
```

OPERATIONAL NOTE 1:
  On-call runbook entry for "Load test with synthetic typing models (not constant ping)" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 2:
  On-call runbook entry for "Load test with synthetic typing models (not constant ping)" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 3:
  On-call runbook entry for "Load test with synthetic typing models (not constant ping)" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.
### Pattern: Dark launch: mirror production ops to shadow cluster

```
WHY TEAMS USE THIS:
  Dark launch: mirror production ops to shadow cluster addresses a specific production pain discovered after MVP.

IMPLEMENTATION CHECKLIST:
  [ ] Metric emitted before feature flag enable
  [ ] Rollback documented (one CLI command)
  [ ] Load test scenario in CI (k6 or Locust WS plugin)
  [ ] Runbook linked from alert annotation

ROLLBACK TRIGGERS:
  p99 op ack latency > 500ms for 5 minutes
  revision_gap_fetch_rate > 10/sec per doc (indicates transform bug)
  error_rate(transform) > 0.01%

CODE REVIEW GATE:
  Any change to transform merge logic requires dual approval +
  property test run in CI (min 30 minute job).
```

OPERATIONAL NOTE 1:
  On-call runbook entry for "Dark launch: mirror production ops to shadow cluster" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 2:
  On-call runbook entry for "Dark launch: mirror production ops to shadow cluster" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

OPERATIONAL NOTE 3:
  On-call runbook entry for "Dark launch: mirror production ops to shadow cluster" — verify Redis memory pressure,
  ALB target health, and Kinesis iterator age if analytics path
  shares collab event bus. Document last incident date and fix PR.

---

## Failure Modes

### Failure: Split-brain document state

```
TRIGGER: Two servers both accept ops for same doc after partition

SYMPTOMS:
  Users report "Split-brain document state" — support tickets cluster on one doc_id or region.

ROOT CAUSE CHAIN (typical):
  1. Initial trigger event (deploy, network, overload)
  2. Secondary effect (queue depth, wrong routing)
  3. User-visible corruption or latency

DETECTION:
  Alert: document_convergence_check_failed{doc_id}
  Synthetic bot: two clients edit same doc every 60s; compare checksums.

MITIGATION:
  Immediate: mark doc read-only; serve last known good snapshot.
  Short-term: replay ops from log with fixed transform library.
  Long-term: add convergence property tests; canary deploy.

POSTMORTEM QUESTIONS:
  Did we have an op_id dedup window wide enough?
  Was ALB stickiness cookie expired mid-session?
  Did compaction delete ops still needed for lagging replica?
```
### Failure: Lost local edits on reconnect

```
TRIGGER: Client rebasing bug drops unacknowledged ops

SYMPTOMS:
  Users report "Lost local edits on reconnect" — support tickets cluster on one doc_id or region.

ROOT CAUSE CHAIN (typical):
  1. Initial trigger event (deploy, network, overload)
  2. Secondary effect (queue depth, wrong routing)
  3. User-visible corruption or latency

DETECTION:
  Alert: document_convergence_check_failed{doc_id}
  Synthetic bot: two clients edit same doc every 60s; compare checksums.

MITIGATION:
  Immediate: mark doc read-only; serve last known good snapshot.
  Short-term: replay ops from log with fixed transform library.
  Long-term: add convergence property tests; canary deploy.

POSTMORTEM QUESTIONS:
  Did we have an op_id dedup window wide enough?
  Was ALB stickiness cookie expired mid-session?
  Did compaction delete ops still needed for lagging replica?
```
### Failure: Cursor storm

```
TRIGGER: Presence flood saturates WS outbound bandwidth

SYMPTOMS:
  Users report "Cursor storm" — support tickets cluster on one doc_id or region.

ROOT CAUSE CHAIN (typical):
  1. Initial trigger event (deploy, network, overload)
  2. Secondary effect (queue depth, wrong routing)
  3. User-visible corruption or latency

DETECTION:
  Alert: document_convergence_check_failed{doc_id}
  Synthetic bot: two clients edit same doc every 60s; compare checksums.

MITIGATION:
  Immediate: mark doc read-only; serve last known good snapshot.
  Short-term: replay ops from log with fixed transform library.
  Long-term: add convergence property tests; canary deploy.

POSTMORTEM QUESTIONS:
  Did we have an op_id dedup window wide enough?
  Was ALB stickiness cookie expired mid-session?
  Did compaction delete ops still needed for lagging replica?
```
### Failure: Transform non-convergence

```
TRIGGER: OT bug → clients show different text

SYMPTOMS:
  Users report "Transform non-convergence" — support tickets cluster on one doc_id or region.

ROOT CAUSE CHAIN (typical):
  1. Initial trigger event (deploy, network, overload)
  2. Secondary effect (queue depth, wrong routing)
  3. User-visible corruption or latency

DETECTION:
  Alert: document_convergence_check_failed{doc_id}
  Synthetic bot: two clients edit same doc every 60s; compare checksums.

MITIGATION:
  Immediate: mark doc read-only; serve last known good snapshot.
  Short-term: replay ops from log with fixed transform library.
  Long-term: add convergence property tests; canary deploy.

POSTMORTEM QUESTIONS:
  Did we have an op_id dedup window wide enough?
  Was ALB stickiness cookie expired mid-session?
  Did compaction delete ops still needed for lagging replica?
```
### Failure: Snapshot/op log divergence

```
TRIGGER: Compaction job crashes mid-write

SYMPTOMS:
  Users report "Snapshot/op log divergence" — support tickets cluster on one doc_id or region.

ROOT CAUSE CHAIN (typical):
  1. Initial trigger event (deploy, network, overload)
  2. Secondary effect (queue depth, wrong routing)
  3. User-visible corruption or latency

DETECTION:
  Alert: document_convergence_check_failed{doc_id}
  Synthetic bot: two clients edit same doc every 60s; compare checksums.

MITIGATION:
  Immediate: mark doc read-only; serve last known good snapshot.
  Short-term: replay ops from log with fixed transform library.
  Long-term: add convergence property tests; canary deploy.

POSTMORTEM QUESTIONS:
  Did we have an op_id dedup window wide enough?
  Was ALB stickiness cookie expired mid-session?
  Did compaction delete ops still needed for lagging replica?
```
### Failure: Sticky session trap

```
TRIGGER: Draining server never empties — deploy stuck

SYMPTOMS:
  Users report "Sticky session trap" — support tickets cluster on one doc_id or region.

ROOT CAUSE CHAIN (typical):
  1. Initial trigger event (deploy, network, overload)
  2. Secondary effect (queue depth, wrong routing)
  3. User-visible corruption or latency

DETECTION:
  Alert: document_convergence_check_failed{doc_id}
  Synthetic bot: two clients edit same doc every 60s; compare checksums.

MITIGATION:
  Immediate: mark doc read-only; serve last known good snapshot.
  Short-term: replay ops from log with fixed transform library.
  Long-term: add convergence property tests; canary deploy.

POSTMORTEM QUESTIONS:
  Did we have an op_id dedup window wide enough?
  Was ALB stickiness cookie expired mid-session?
  Did compaction delete ops still needed for lagging replica?
```
### Failure: Revision gap avalanche

```
TRIGGER: Slow client triggers O(n^2) catch-up fetches

SYMPTOMS:
  Users report "Revision gap avalanche" — support tickets cluster on one doc_id or region.

ROOT CAUSE CHAIN (typical):
  1. Initial trigger event (deploy, network, overload)
  2. Secondary effect (queue depth, wrong routing)
  3. User-visible corruption or latency

DETECTION:
  Alert: document_convergence_check_failed{doc_id}
  Synthetic bot: two clients edit same doc every 60s; compare checksums.

MITIGATION:
  Immediate: mark doc read-only; serve last known good snapshot.
  Short-term: replay ops from log with fixed transform library.
  Long-term: add convergence property tests; canary deploy.

POSTMORTEM QUESTIONS:
  Did we have an op_id dedup window wide enough?
  Was ALB stickiness cookie expired mid-session?
  Did compaction delete ops still needed for lagging replica?
```
### Failure: Tombstone bloat (CRDT)

```
TRIGGER: Document size grows 10x over months

SYMPTOMS:
  Users report "Tombstone bloat (CRDT)" — support tickets cluster on one doc_id or region.

ROOT CAUSE CHAIN (typical):
  1. Initial trigger event (deploy, network, overload)
  2. Secondary effect (queue depth, wrong routing)
  3. User-visible corruption or latency

DETECTION:
  Alert: document_convergence_check_failed{doc_id}
  Synthetic bot: two clients edit same doc every 60s; compare checksums.

MITIGATION:
  Immediate: mark doc read-only; serve last known good snapshot.
  Short-term: replay ops from log with fixed transform library.
  Long-term: add convergence property tests; canary deploy.

POSTMORTEM QUESTIONS:
  Did we have an op_id dedup window wide enough?
  Was ALB stickiness cookie expired mid-session?
  Did compaction delete ops still needed for lagging replica?
```

---

## SRE Diagnostic Toolkit

```
WEBSOCKET CONNECTION CHECK (from client machine):

  wscat -c "wss://collab.example.com/ws?doc_id=d_test" \
    -H "Authorization: Bearer $JWT"

  Expected: 101 Switching Protocols, then auth_ok frame within 2s.

ALB TARGET HEALTH:

  aws elbv2 describe-target-health \
    --target-group-arn arn:aws:elasticloadbalancing:...:targetgroup/collab/abc

  Look for: unhealthy targets during deploy; "Target.FailedHealthChecks"

COLLAB SERVER METRICS (Prometheus / CloudWatch):

  collab_ws_connections_active
  collab_ops_inflight
  collab_transform_duration_seconds_bucket
  collab_revision_gap_fetch_total
  collab_ack_latency_seconds (histogram — alert p99 > 0.25)

REDIS PRESENCE:

  redis-cli -h presence.cache.amazonaws.com
  > HGETALL presence:doc_8f3a
  > PUBSUB NUMSUB doc:doc_8f3a:presence

  Empty hash + active editors = presence pipeline broken.

DOCUMENT CHECKSUM AUDIT:

  curl -H "Authorization: Bearer $JWT" \
    https://api.example.com/docs/d_8f3a/checksum

  Run from two regions; mismatch → convergence failure.

KINESIS LAG (analytics path):

  aws cloudwatch get-metric-statistics \
    --namespace AWS/Kinesis \
    --metric-name GetRecords.IteratorAgeMilliseconds \
    --dimensions Name=StreamName,Value=collab-ops \
    --start-time $(date -u -d '15 min ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 60 --statistics Maximum

LOG PATTERNS (CloudWatch Logs Insights):

  fields @timestamp, doc_id, op_id, error
  | filter @message like /transform_failed/
  | stats count() by doc_id
  | sort count desc
  | limit 20
```

# Diagnostic playbook step 1: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 2: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 3: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 4: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 5: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 6: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 7: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 8: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 9: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 10: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 11: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 12: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 13: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 14: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 15: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 16: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 17: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 18: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 19: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

# Diagnostic playbook step 20: correlate WS disconnect reason codes
# ALB access log field: connection_logs.reason (if enabled)
# Common: "client reset", "target reset", "idle timeout"
# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \
#   --load-balancer-arn $ARN --attributes Key=idle_timeout.timeout_seconds,Value=3600

---

## Decision Framework

```
┌─────────────────────────────────────────────────────────────────┐
│ START: Building collaborative editing                           │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────▼──────────────┐
              │ Need offline-first mobile?  │
              └──────┬───────────────┬──────┘
                    YES              NO
                     │               │
         ┌───────────▼──────┐   ┌────▼─────────────────┐
         │ Prefer CRDT      │   │ Rich-text complexity │
         │ (Yjs/Automerge)  │   │ tree vs linear?      │
         └───────────┬──────┘   └────┬─────────┬───────┘
                     │              Tree      Linear
                     │               │          │
                     │          ┌────▼────┐  ┌──▼──────────┐
                     │          │Tree CRDT│  │ OT + central│
                     │          │         │  │ server      │
                     │          └─────────┘  └─────────────┘

TRANSPORT CHOICE:
  Real-time ops + presence → WebSockets (not SSE — need client→server ops)
  Comments only → SSE or long poll acceptable
  Export/render → REST + S3 presigned URLs

PERSISTENCE CHOICE:
  <1K ops/day/doc → snapshot on every save acceptable
  >1K ops/day/doc → snapshot + op log mandatory
  Compliance → S3 Object Lock on op logs

SCALE TIER:
  <10K concurrent editors → single collab cluster + Redis
  >100K → shard by doc_id, dedicated presence Redis cluster
  >1M → multi-region home regions + cross-region log replication
```

| Criterion | OT + Central Server | CRDT (Yjs-style) |
|-----------|--------------------|------------------|
| Offline merge | Harder (rebase queue) | Native |
| Server CPU | Higher (transform) | Lower (relay/merge) |
| Metadata size | Smaller | Larger (tombstones) |
| Audit ordering | Strict total order | DAG merge order |
| Maturity for rich text | Google/M365 path | Notion/Figma path |
| Property test burden | Transform pairs | Merge associativity |

---

## Incident Scenario: Real-Time Collaboration Outage

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: Docs product (10M DAU)
Time: 2:47 PM UTC

ARCHITECTURE:
  Users → CloudFront (static) → ALB → ECS collab (40 tasks)
  DynamoDB metadata, S3 snapshots, ElastiCache Redis presence
  OT-based sync, WebSocket stickiness enabled

SYMPTOMS (all started within 90 seconds):
  - Support: "Edits not sticking — I type and text reverts"
  - Grafana: collab_ack_latency_p99 spiked 80ms → 4200ms
  - Grafana: collab_revision_gap_fetch_total +800%
  - PagerDuty: 15% of WebSocket connections resetting/sec
  - One doc_id appears in 60% of transform_failed logs

TIMELINE:
  2:40 PM — Deploy collab v2.14.0 (transform optimization)
  2:47 PM — Alerts fire
  2:51 PM — Rollback initiated
  2:55 PM — Rollback complete but some docs still diverged

YOUR TASK (no hand-holding):
  Q1: What is the most likely bug class in v2.14.0 transform change?
  Q2: Immediate mitigation steps in priority order?
  Q3: How do you find all diverged documents?
  Q4: How do you repair diverged docs without losing edits?
  Q5: What gates prevent shipping transform regressions again?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Expert Analysis

### Q1: Most Likely Bug Class

```
Transform optimization likely skipped edge case in concurrent
insert+delete at same offset (classic OT pitfall).

Evidence:
  - Single doc_id dominating errors → deterministic repro
  - revision_gap_fetch spike → clients detecting revision mismatch
  - Text "reverting" → server acked transformed op client couldn't apply

The optimization probably memoized transform results by op TYPE pair
(insert, delete) without including context (offset overlap class).
```

### Q2: Worked Answer

```
ANSWER Q2:

  Priority 2: Rollback deploy first
  Enable read-only mode flag for hot doc_ids
  
  
  

  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
```

### Q3: Worked Answer

```
ANSWER Q3:

  Priority 3: Isolate affected doc_ids via log query
  
  Run checksum bot against top 1000 active docs
  
  

  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
```

### Q4: Worked Answer

```
ANSWER Q4:

  Priority 4: Isolate affected doc_ids via log query
  
  
  Replay ops from immutable log with v2.13.0 transform library
  

  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
```

### Q5: Worked Answer

```
ANSWER Q5:

  Priority 5: Isolate affected doc_ids via log query
  
  
  
  Mandatory 1M-op property test in CI + 24h canary at 1% traffic

  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
```

---

## Key Takeaways

╔══════════════════════════════════════════════════════════════╗
║ IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:               ║
╠══════════════════════════════════════════════════════════════╣
║ 1. Collaborative editing is a CONCURRENCY problem first;     ║
║ WebSockets are just transport.                               ║
║ 2. OT gives central ordering; CRDTs give merge without       ║
║ transform — pick based on offline + document model.          ║
║ 3. Never persist every keystroke — snapshot + op log +       ║
║ periodic compaction is the production pattern.               ║
║ 4. Presence is ephemeral (Redis TTL), edits are durable      ║
║ (S3/DynamoDB) — do not mix the data paths.                   ║
║ 5. Property-test transform/merge logic — one bug = data      ║
║ loss for every user on affected documents.                   ║
╚══════════════════════════════════════════════════════════════╝
---

## Targeted Reading

```
REQUIRED:
  1. "Operational Transformation in Real-Time Group Editors"
     — Ellis & Gibbs, 1989 (foundational OT paper)
  2. Shapiro et al., "Conflict-free Replicated Data Types" (2011)
     — Sections 1-3 for state-based vs op-based CRDTs
  3. Kleppmann, "Making CRDTs Code" (blog + talk)
     — Practical implementation pitfalls
  4. Yjs documentation: "Document Updates" chapter
     — https://docs.yjs.dev/api/document-updates

OPTIONAL:
  5. Google Wave Federation Protocol (historical OT at scale)
  6. Figma multiplayer blog posts (CRDT + custom invariants)
  7. Martin Kleppmann, DDIA Chapter 5 (replication) + Ch 9 (consistency)

AWS:
  8. ALB WebSocket support docs — idle timeout and stickiness
  9. ElastiCache best practices for Pub/Sub fan-out
```
