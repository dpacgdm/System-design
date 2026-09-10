# Week 14, Topic 3: Design Real-Time Collaborative Canvas and Comments

---

## Learning Objectives
```
╔═════════════════════════════════════════════════════════════════════════════════════╗
║   AFTER THIS MODULE, YOU WILL BE ABLE TO:                                           ║
╟─────────────────────────────────────────────────────────────────────────────────────╢
║                                                                                     ║
║   1. Formulate latency, bandwidth, and consistency requirements for a multi-user    ║
║      collaborative 2D canvas editing platform (Figma / Miro style)                  ║
║                                                                                     ║
║   2. Architect a hierarchical Scene Graph Tree using CRDTs (Conflict-free Replicated║
║      Data Types) and Fractional Indexing for conflict-free concurrent editing       ║
║                                                                                     ║
║   3. Master high-frequency ephemeral state distribution: 60Hz live cursor tracking, ║
║      selection bounding boxes, and camera viewports over WebSockets                 ║
║                                                                                     ║
║   4. Design selective local undo/redo systems that invert user-specific changes     ║
║      without clobbering concurrent edits made by collaborating peers                ║
║                                                                                     ║
║   5. Construct spatial pin comment threads with @mentions parsing, parent object    ║
║      anchor tracking, and asynchronous notification fan-out pipelines               ║
╚═════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 2: Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Use standard text Operational Transformation (OT) for canvas shapes"    ║
╟─────────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. OT is designed for 1D linear strings of text characters. A 2D canvas               ║
║   is an acyclic scene graph of independent geometric objects (rectangles, vectors,          ║
║   frames). CRDTs (LWW-Element-Set / Yjs) or centralized command trees are vastly            ║
║   simpler, faster, and avoid exponential OT transformation matrix complexity.               ║
╠═════════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Persist live cursor movements directly into the database"               ║
╟─────────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. 50 users moving mice at 60 fps produce 3,000 events/second per canvas.             ║
║   Writing ephemeral mouse coordinates to a database will collapse connection pools          ║
║   and disk I/O. Cursors are transient, loss-tolerant UDP/WebSocket broadcasts routed in RAM.║
╠═════════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Collaborative undo simply rolls back canvas state to T - 1"             ║
╟─────────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. A global rollback undoes operations performed by all collaborators!                ║
║   Collaborative undo must be selective: it inverts only the acting user's specific          ║
║   prior operation while preserving all concurrent operations from peers.                    ║
╠═════════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Send the entire canvas document JSON on every modification"             ║
╟─────────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Canvases with 50,000 vector shapes reach 20MB-100MB in memory. Serializing         ║
║   and sending the full state on every mouse drag chokes client CPU and network bandwidth.   ║
║   Production platforms broadcast compact binary property deltas (e.g. {id, dx, dy}).        ║
╠═════════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Store comment pins as static (X, Y) canvas root coordinates"            ║
╟─────────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. When a designer drags a group or frame to a new position, static root (X, Y)       ║
║   comments stay behind floating in empty space. Comments must anchor to the parent          ║
║   object ID with relative offsets (dx, dy) within the object coordinate space.              ║
╚═════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 3: Requirements & Sizing Calculations

### 1. Functional Requirements

```
FUNCTIONAL REQUIREMENTS (Interview Scope):
  P0 — Core Requirements:
    → Real-Time 2D Canvas Editing: Multiple users concurrently create, move, resize, and style shapes.
    → Ephemeral Cursor Presence: Broadcast live user cursors, selection boxes, and names at 30-60 Hz.
    → Conflict-Free Convergence: All clients deterministically converge to the exact same scene graph.
    → Selective Local Undo/Redo: Reverting an action affects only the acting user's edits.
    → Spatial Pin Comments: Users click anywhere on canvas/shapes to start threaded discussions with @mentions.

  P1 — Desirable Features:
    → Offline Editing & Reconnect: Apply local edits while disconnected and merge seamlessly upon reconnection.
    → Real-Time Notification Fan-Out: Instantly notify mentioned users via in-app alerts and push notifications.
```

### 2. Capacity Sizing (Back-of-the-Envelope)

| Factor | Metric | Baseline / Average | Peak Load (Collab Rush) | Daily / Scale Volume |
| :--- | :--- | :--- | :--- | :--- |
| **1. Active Canvases** | Concurrent Active Rooms| ~20,000 active rooms | ~50,000 active rooms | ~250,000 daily rooms |
| **2. Connected Users** | Concurrent Collab Users| ~100,000 active users| ~500,000 active users| ~10 users / room avg |
| **3. Cursor Traffic** | Presence Updates (30Hz)| 30 pkts/s * 64B = ~2KB/s| 50 users = 100 KB/s/room| 5 GB/s aggregate egress |
| **4. Mutation Ops** | Shape Property Changes | 5 mutations/s / room | 25 mutations/s / room | ~1.25M mutations/s peak |
| **5. Scene Graph Storage**| Snapshot Document Size | ~5 MB avg / canvas | ~50 MB complex canvas | S3 + RocksDB snapshots |

---

## Section 4: High-Level Design (HLD) Box-and-Arrow

```
               REAL-TIME COLLABORATIVE CANVAS & COMMENTS — ARCHITECTURE
               ═════════════════════════════════════════════════════════

   ┌────────────────────┐          ┌────────────────────┐
   │ Client A (WebGL/Wasm)         │ Client B (WebGL/Wasm)
   └─────────┬──────────┘          └─────────┬──────────┘
             │                               │
             └───────────────┬───────────────┘
                             │ WebSocket (Bidirectional: Cursors + Mutations + Comments)
                             ▼
   ┌────────────────────────────────────────────────────────┐
   │ Global Anycast Edge & WebSocket Gateway Fleet          │
   │ - Terminates TLS & authenticates session tokens        │
   │ - Maintains persistent stateful socket connections     │
   │ - Routes requests to Canvas Room Controller by room_id │
   └─────────────────────────┬──────────────────────────────┘
                             │
            ┌────────────────┴───────────────────────────────┐
            │ (1) Ephemeral (Cursors & Presence)            │ (2) Persistent (Mutations & Comments)
            ▼                                               ▼
   ┌─────────────────────────────────┐             ┌─────────────────────────────────┐
   │ Ephemeral Presence Broker       │             │ Canvas Room Coordinator Cluster │
   │ (Redis Pub/Sub / Cluster RAM)   │             │ - Centralized Room Authority    │
   │ - Tracks cursor X, Y, viewport  │             │ - Orders incoming CRDT deltas   │
   │ - Drops dropped/stale ticks     │             │ - Maintains live in-memory tree │
   │ - Low-latency broadcast (<20ms) │             └───────────────┬─────────────────┘
   └─────────────────────────────────┘                             │
                                                   ┌───────────────┴─────────────────┐
                                                   │                                 │
                                                   ▼ (Debounced Document Flush)      ▼ (Transactional Events)
                                    ┌─────────────────────────────┐   ┌─────────────────────────────┐
                                    │ Document Snapshot Store     │   │ Comments & Mentions Service │
                                    │ (S3 + RocksDB LSM-Tree)     │   │ - Stores pinned threads     │
                                    │ - Periodic full scene graph │   │ - Parses `@username` tokens │
                                    │ - WAL of ordered operations │   │ - Writes to PostgreSQL DB   │
                                    └─────────────────────────────┘   └──────────────┬──────────────┘
                                                                                     │
                                                                                     ▼ (Kafka Event Bus)
                                                                      ┌─────────────────────────────┐
                                                                      │ Notification Fan-Out Engine │
                                                                      │ - Pushes in-app toasts (WS) │
                                                                      │ - Triggers emails / WebPush │
                                                                      └─────────────────────────────┘
```

### End-to-End Execution Flow

```
STEP 1: ROOM CONNECTION & INITIAL HYDRATION
  1. Client connects via WebSocket: `WS /canvas/{room_id}`.
  2. Room Coordinator returns latest Scene Graph snapshot from RocksDB memory cache.
  3. Client renders shapes locally in WebGL/Canvas; initializes local CRDT document model.

STEP 2: EPHEMERAL CURSOR & SELECTION STREAMING (30-60 Hz)
  1. As Client A moves mouse, client throttles to 30 updates/sec.
  2. Sends lightweight binary payload: `{type: "CURSOR", x: 1420.5, y: 812.0, selection: ["rect_4"]}`.
  3. Gateway forwards directly to Redis Pub/Sub channel `room:{id}:presence`.
  4. Room subscribers receive cursor update; client animates cursor smoothly using linear interpolation (LERP).
  5. Zero database disk I/O is performed.

STEP 3: SHAPE MUTATION & CRDT CONVERGENCE
  1. Client A drags a rectangle: generates operation `{op: "MOVE", id: "rect_4", x: 200, y: 150, ts: 17260012, v: 5}`.
  2. Room Coordinator validates permissions, stamps monotonic sequence number, updates local tree, and broadcasts to room.
  3. Peer clients apply delta to their local CRDT model. In case of concurrent drag by Client B, Last-Write-Wins (LWW)
     or property-level merging resolves conflict deterministically.

STEP 4: PINNED COMMENT CREATION & @MENTION NOTIFICATION
  1. Client leaves comment on shape: `POST /comments {object_id: "rect_4", rel_x: 20, rel_y: 15, text: "Review @alice"}`.
  2. Service stores comment linked to `object_id`.
  3. Regex extracts `@alice`, resolves `alice_user_id`, and emits event `CommentMentionCreated` to Kafka.
  4. Notification Worker consumes Kafka event, persists notification, and sends real-time alert to Alice's WebSocket.
```

---

## Section 5: Core Technical Deep Dives (Interview Focus)

### Deep Dive 1: Canvas Scene Graph Modeling: Tree CRDT vs LWW-Element-Set

```
HIERARCHICAL CANVAS SCENE GRAPH TOPOLOGY:

               CANVAS ROOT (Room ID)
                     │
       ┌─────────────┴─────────────┐
       ▼                           ▼
  [Frame 1: Homepage]       [Frame 2: Checkout]
       │                           │
  ┌────┴────┐                      ▼
  ▼         ▼                 [Button: Pay]
[Hero]   [Navbar]                  │
  │                           [Text: "Submit"]
[Title Text]

WHY NAIVE TREE MUTATIONS FAIL IN DISTRIBUTED SYSTEMS:
  If User A moves [Navbar] under [Frame 2], while User B moves [Frame 2] under [Navbar]:
  → A cycle is created! The scene graph ceases to be a tree and crashes the renderer!

SENIOR INTERVIEW SOLUTION:
  1. Flat Object Map + Parent Pointers:
     Store canvas as a flat hash map of objects: `Map<ObjectID, CanvasObject>`.
     Each object contains: `{id, type, parent_id, properties, z_index}`.
  2. Property-Level LWW-Element-Set:
     Decompose mutations into independent properties (x, y, width, height, fill_color).
     If User A changes `fill_color` while User B changes `width`, BOTH changes apply cleanly!
  3. Cycle Detection via Monotonic Clocks:
     Reparenting operations require checking ancestor chains against Lamport timestamps;
     conflicting reparents reject the later timestamp to strictly preserve acyclicity.
```

### Deep Dive 2: Ephemeral Cursor Pipeline & Interpolation (LERP)

```
HIGH-FREQUENCY PRESENCE OPTIMIZATION:

  Client Mouse Events (120 Hz)
            │
            ▼ (Client Throttling: Cap at 30 fps)
  Outbound WebSocket Packet (Packed Binary Struct, 32 bytes):
  ┌──────────────────────────────────────────────────────────────┐
  │ user_id (16B UUID) │ x (4B float) │ y (4B float) │ state (8B)│
  └──────────────────────────────────────────────────────────────┘
            │
            ▼ (Redis Pub/Sub Memory Channel: < 5ms fanout)
  Receiving Peers (WebSocket)
            │
            ▼ (Client Rendering via Linear Interpolation - LERP)
  Smooth visual rendering at 60 fps on peer screens!

LINEAR INTERPOLATION FORMULA:
  Instead of teleporting cursor abruptly to new coordinates:
  $$P(t) = P_{\text{start}} + t \times (P_{\text{target}} - P_{\text{start}})$$
  where $t \in [0, 1]$ represents rendering delta time. Cursors glide smoothly even if
  network jitter drops 20% of intermediate presence packets.
```

### Deep Dive 3: Selective Local Undo/Redo in Multi-User Environments

```
THE COLLABORATIVE UNDO PARADOX:
  1. User A moves Rectangle to (100, 100).
  2. User B changes Rectangle color to RED.
  3. User A presses Ctrl+Z (Undo).
  What should happen?
  - WRONG: Roll back entire object to state before (1). (Wipes out User B's red color!)
  - CORRECT: Selective Inversion. Invert ONLY User A's move operation!

SELECTIVE UNDO ARCHITECTURE:
  1. Per-User Operation History Stack:
     Each user maintains a local stack of their own applied mutations:
     `Stack = [Op1: {prop: "x", old: 50, new: 100}, Op2: ...]`
  2. Generating the Inverse Delta:
     When User A hits Undo:
     - Pop Op1 from local stack.
     - Generate Inverse Op: `{prop: "x", set: 50}`.
     - Check if target object still exists. If object was deleted by User B, discard inverse op.
     - Apply inverse op as a BRAND NEW forward operation with current timestamp $T_{\text{now}}$.
  3. Redo Stack:
     Pushes inverted op onto Redo stack; re-applying creates another forward delta.
```

### Deep Dive 4: Spatial Pin Comments & Dynamic Anchor Re-positioning

```
ANCHORING ALGORITHM: OBJECT-RELATIVE VS CANVAS-ROOT COORDINATES

  CASE 1: Canvas Root Pin (Pinned on blank canvas background)
    Store: `{canvas_id, anchor_type: "CANVAS", pos_x: 1850.0, pos_y: 420.0}`
    Behavior: Always remains at absolute coordinates (1850, 420).

  CASE 2: Object-Relative Pin (Pinned on a specific UI Button)
    Store: `{canvas_id, anchor_type: "OBJECT", target_id: "btn_submit", rel_x: 0.85, rel_y: 0.50}`
    Behavior:
      Screen X = Object.X + (rel_x * Object.Width)
      Screen Y = Object.Y + (rel_y * Object.Height)
    → When the designer moves, scales, or rotates the button, the comment pin moves
      proportionately and stays visually attached to the button's right edge!

MENTION EXTRACTION & FAN-OUT:
  1. Ingestion: Regex `/@([a-zA-Z0-9_]+)/g` parses usernames.
  2. Deduplication: Set of mentioned usernames mapped to `user_id`s in PostgreSQL.
  3. Transactional Outbox Pattern:
     Inserts comment row + outbox event row in a single atomic SQL transaction.
  4. Outbox Worker relays events to Kafka topic `notifications.mentions`.
  5. Multi-channel dispatchers deliver:
     - Real-time in-app toast banner via WebSocket.
     - Push notification if user is mobile/offline.
     - Email summary if unread after 5 minutes.
```

---

## Section 6: API Design & Data Models

### 1. WebSocket Protocol & REST APIs

```json
// WS Client -> Server: Cursor Move
{
  "action": "presence.cursor",
  "room_id": "cnv_77182a",
  "x": 450.2,
  "y": 890.1,
  "selected_ids": ["shape_102"]
}

// WS Client -> Server: Object Mutation (CRDT Delta)
{
  "action": "mutation.patch",
  "room_id": "cnv_77182a",
  "object_id": "shape_102",
  "properties": { "x": 510.0, "fill": "#FF5733" },
  "client_seq": 84,
  "timestamp": 1726002918451
}
```

```http
POST /api/v1/canvases/{canvas_id}/comments
Content-Type: application/json
Authorization: Bearer <token>

{
  "anchor_type": "OBJECT",
  "target_object_id": "shape_102",
  "rel_x": 0.50,
  "rel_y": 0.25,
  "content": "Can we change this to primary blue? @sarah please verify."
}
Response: 201 Created
{
  "comment_id": "cmt_9918ab",
  "mentions": ["usr_sarah42"],
  "created_at": "2026-09-10T22:15:00Z"
}
```

### 2. Database Schema (PostgreSQL)

```sql
CREATE TABLE canvas_documents (
    canvas_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    title VARCHAR(255) NOT NULL,
    snapshot_s3_url VARCHAR(512),
    version BIGINT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE canvas_comments (
    comment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canvas_id UUID NOT NULL REFERENCES canvas_documents(canvas_id) ON DELETE CASCADE,
    author_id UUID NOT NULL,
    parent_comment_id UUID REFERENCES canvas_comments(comment_id), -- Thread support
    anchor_type VARCHAR(16) NOT NULL,                             -- CANVAS, OBJECT
    target_object_id VARCHAR(64),
    rel_x DOUBLE PRECISION NOT NULL,
    rel_y DOUBLE PRECISION NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'OPEN',                   -- OPEN, RESOLVED
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_canvas_comments ON canvas_comments (canvas_id, status);
CREATE INDEX idx_parent_threads ON canvas_comments (parent_comment_id);

CREATE TABLE comment_mentions (
    mention_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    comment_id UUID NOT NULL REFERENCES canvas_comments(comment_id) ON DELETE CASCADE,
    mentioned_user_id UUID NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_user_mentions ON comment_mentions (mentioned_user_id, is_read);
```

---

## Section 7: Failure Modes & Self-Healing Resilience

```
╔═══════════════════════════════════════════════════════════════════════════════════════════╗
║ FAILURE SCENARIO         │ DETECTION                   │ MITIGATION & RECOVERY            ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Client Disconnects During│ Heartbeat ping timeout      │ Client buffers local mutations;  ║
║ Live Drag Operation      │ (missed WS ping > 5s)       │ reconciles via CRDT vector clock ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Concurrent Edit Conflict │ Simultaneous property update│ Last-Write-Wins (LWW) timestamp  ║
║ (Two users change color) │ detected on shape property  │ with client UUID tie-breaker wins║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Parent Shape Deleted     │ Comment references non-     │ Tombstone shape metadata or      ║
║ While Comment Active     │ existent object_id          │ re-anchor pin to canvas root X, Y║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Redis Pub/Sub Node Crash │ Gateway connection dropped  │ Consistent hash room reallocation║
║ (Presence Broker Down)   │ to Redis cursor broker      │ reconnects to healthy Redis node ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Undo Operation On An     │ Local undo references shape │ Undo fails gracefully; notifies  ║
║ Object Deleted By Peer   │ deleted by another user     │ user: 'Object was deleted by Bob'║
╚═══════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 8: Interview Tradeoffs & Architecture Matrix

```
┌────────────────────────┬──────────────────────────┬───────────────────────────────┐
│ Design Area            │ Architectural Options    │ Production Decision           │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Conflict Resolution    │ Operational Transform vs │ Property-level CRDT (LWW-Set).│
│ Engine                 │ CRDT (LWW-Element-Set)   │ 2D canvas is non-linear graph.│
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Presence Distribution  │ Polling vs WebRTC P2P vs │ WebSocket + Redis Pub/Sub.    │
│                        │ Centralized WS + Redis   │ WebRTC mesh fails past 6 peers│
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Collaborative Undo     │ Global State Snapshot vs │ Selective Operation Inversion │
│                        │ Selective Op Inversion   │ isolates acting user's edits. │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Comment Positioning    │ Static Canvas Pixels vs  │ Relative Object Anchor (rel_x,│
│                        │ Relative Object Anchor   │ rel_y) keeps pin tied to shape│
└────────────────────────┴──────────────────────────┴───────────────────────────────┘
```

---

## Section 9: Interview Scenario Practice (Test Yourself)

```
Q1: "Why is CRDT preferred over Operational Transformation (OT) for a 2D collaborative canvas?"
TALKING POINTS:
  → Dimensionality: OT requires transforming operations against an ordered 1D sequence of characters.
    A 2D canvas consists of independent geometric objects in an acyclic scene tree.
  → Commutativity: CRDT property mutations (color, size, position) commute naturally:
    Setting `fill_color = red` and `width = 200` yields the identical visual state regardless of arrival order.
  → Offline support: CRDTs allow offline clients to merge hundreds of edits without central server locking.

Q2: "How do you broadcast 60Hz live cursor movements for 50 users in a room without network saturation?"
TALKING POINTS:
  → Client throttling: Clamp outbound cursor emissions to 30 fps (sufficient for human perception).
  → Ephemeral routing: Send packets directly over WebSocket into in-memory Redis Pub/Sub; bypass database disk.
  → Compact binary serialization: Use Protocol Buffers or raw ArrayBuffers (32 bytes) instead of verbose JSON.
  → Client interpolation: Client uses linear interpolation (LERP) to render 60fps smooth movement from 30Hz packets.

Q3: "How does Collaborative Undo handle the case where User A undos a move on a shape that User B deleted?"
TALKING POINTS:
  → Local Selective Undo: User A's undo pops the previous move delta and generates an inverse move operation.
  → Conflict Check: Before applying the inverse delta, the engine verifies if the target shape exists.
  → Graceful Degradation: Because User B deleted the shape (or marked it tombstoned), the move cannot apply.
    The inverse operation is discarded, and the UI displays an informative toast: 'Cannot undo: object was deleted'.

Q4: "How do you guarantee comment pins don't get displaced when a shape is resized or dragged across the screen?"
TALKING POINTS:
  → Relative normalized coordinates: Store position as percentages of the shape: `rel_x = 0.5, rel_y = 0.5` (center).
  → Client render-time calculation: `Absolute_X = Shape.X + (rel_x * Shape.Width)`.
  → Grouping and nesting: If the shape is inside a Frame or Group, coordinates resolve hierarchically up the tree.

Q5: "How do you implement reliable @mention notifications without slowing down comment submission?"
TALKING POINTS:
  → Asynchronous fan-out: The comment API performs a quick regex extraction and commits to DB in < 20ms.
  → Transactional Outbox Pattern: Writes the mention event to an `outbox` table in the same DB transaction.
  → Message Broker: A Debezium CDC worker or tailing daemon publishes the event to Apache Kafka.
  → Consumer workers handle push notification formatting, email rate-limiting, and WebSocket toast alerts.
```
