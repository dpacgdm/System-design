# Answer Key - WebSockets

> Open only after attempting the learner file Ops Sim.

## Ops Sim: Northstar Live Auction Reconnect Storm

### Q1 - Layer & root cause

The disconnect trigger is the edge timeout mismatch: CloudFront origin response timeout is 60s while clients heartbeat every 75s. Idle WebSocket connections are closed before the heartbeat proves liveness.

The amplifier is client behavior plus Redis fan-out:
- Fixed 1s reconnect creates synchronized retry waves.
- Each reconnect refreshes auth/session state and resubscribes to many channels.
- Redis node-4 becomes hot on auction channel fan-out/replay.

### Q2 - Evidence

Reconnect storm evidence:
- Sawtooth concurrent connections every 60s.
- `ws_reconnect_attempts` jumps to 390k/min.
- Close code 1006 with idle timeout.
- NLB target resets spike.

Not a bid-write outage:
- Accepted bid write p99 is 38ms.
- Bid ordering service error rate is 0.02%.
- Symptom is delivery lag and reconnect bursts, not failed bid acceptance.

### Q3 - First 15 minutes

1. Declare P1 and separate "bid acceptance healthy" from "bid display stale" in comms.
2. Revert or raise CloudFront/NLB idle timeout above heartbeat interval, or lower heartbeat to <30s if server capacity allows.
3. Flip client/server config to jittered exponential backoff where controllable.
4. Temporarily reduce optional channel subscriptions and replay depth.
5. Protect Redis: shard hot auction channels, enable local per-gateway coalescing, or serve stale snapshot while live stream recovers.
6. Watch delivery lag, reconnect attempts, Redis CPU, auth/session QPS, and accepted bid order.

### Q4 - Bad fixes

Doubling WebSocket pods may accept more sockets but does not stop synchronized disconnects or Redis/auth amplification.

Disabling reconnects strands users after legitimate network drops. Safer: jittered backoff, token refresh budgets, and server-side resume cursors.

### Q5 - Capacity / blast radius

```text
260,000 reconnecting clients/min ~= 4,333 reconnects/sec
Auth/session lookups ~= 4,333/sec if one per reconnect
Channel subscriptions = 260,000 x 36 = 9.36M subscriptions/min
```

That load can overload Redis, auth/session Redis, and gateway CPU even if bid writes are healthy.

### Q6 - Durable fix

- Heartbeat interval must be less than half the lowest idle timeout on the path.
- Clients use exponential backoff with full jitter and resume tokens.
- Gateways coalesce subscriptions per auction and fan out locally.
- Hot auctions are partitioned by audience segment or channel shard.
- Load tests include 50% reconnect waves and assert delivery lag <500ms p99.

### Q7 - Org / runbook

Inform incident commander, auction operations/legal, support, edge owner, Redis owner, and bidding service owner.

Allowed degradation: pause animations, show "live updates delayed" banner, lower replay depth for non-winning bid history. Not allowed: reorder accepted bids client-side or close the auction based on stale client state.

---

# Incident Deep-Dive: WebSocket Broadcast OOM Cascade

---

## Question 1: Root Cause & The OOM Math

### The Root Cause: Per-Connection Message Buffering with No Backpressure Control

When a goal event fires, the server must send a 6KB message to every connected client. The server **copies the message into each connection's individual write buffer**. It cannot flush all connections simultaneously — the kernel TCP send buffer has finite capacity. Messages queue in application-level write buffers waiting to be flushed, and there is **no backpressure mechanism** to drop or defer messages for slow clients.

### The Memory Math

**Baseline memory consumption (pre-goal, steady state):**
```
Assume 4 WebSocket servers, 1.2M total connections.
Even distribution would be 300K connections per server.

Per-connection memory overhead:
  - Socket file descriptor + kernel buffers: ~4KB
  - Application-level connection state
    (session metadata, headers, user context): ~10KB
  - Application-level write buffer (idle): ~1KB
  Total per connection: ~15KB

Server baseline memory:
  300,000 connections × 15KB = 4.5GB

Assume each server has 8GB RAM allocated
  (container limit or physical).
  Available headroom: 8GB - 4.5GB = 3.5GB
```

**Memory spike during goal broadcast:**
```
Goal event → broadcast 6KB message to ALL connections on this server.

The server iterates through 300,000 connections and
writes the message to each connection's send buffer.

CRITICAL PROBLEM: The server cannot flush 300K sockets
simultaneously. The kernel TCP send buffer per socket is
typically 64KB-256KB. When it's full, the write blocks
or is queued at the application layer.

For a fast client (broadband, low latency):
  Message writes to kernel buffer immediately → flushed → 0 queued
  Additional memory per connection: ~0KB

For a slow client (mobile, congested network, high RTT):
  Kernel TCP send buffer is FULL (receiver hasn't ACK'd)
  Message is queued in the APPLICATION-level write buffer
  Additional memory per connection: 6KB (the full message copy)

What percentage of clients are "slow" at any given moment?
  Sports streaming audience: heavily mobile, global distribution
  Conservative estimate: 40-60% of clients are slow during peak

Memory spike calculation (50% slow clients):
  Fast clients: 150,000 × 0KB = 0GB (flushed immediately)
  Slow clients: 150,000 × 6KB = 900MB queued in app buffers

  Total memory during broadcast:
    Baseline 4.5GB + 900MB spike = 5.4GB
    Headroom remaining: 8GB - 5.4GB = 2.6GB
    → Tight but survivable... IF this were the whole story.
```

**But it's NOT just one message. The goal event triggers a burst:**
```
Real-world goal event generates MULTIPLE near-simultaneous messages:
  1. Goal notification:          6KB  (the primary event)
  2. Score update:               2KB  (updated scoreboard state)
  3. Goal replay trigger:        4KB  (replay metadata/URL)
  4. Commentary update:          3KB  (text update)
  5. Stats refresh:              5KB  (player/match statistics)
  Total per-connection payload: ~20KB across multiple messages

For slow clients, ALL of these queue up because the
kernel buffer was already full from message 1:

  Slow clients: 150,000 × 20KB = 3GB queued in app buffers

  Total memory during goal burst:
    Baseline 4.5GB + 3GB spike = 7.5GB
    Headroom remaining: 8GB - 7.5GB = 0.5GB
    → On the razor's edge. Any variance kills you.
```

### Why Server 3 Died First

```
Server 3 did NOT have an even 300K connections.
WebSocket connections are long-lived and established
over time. Load balancer distribution is never perfectly
even because:

  1. Connection timing: Users connect at different times.
     Round-robin or least-connections LB was roughly even
     at connection time, but churn creates drift.

  2. Geographic clustering: If Server 3 was assigned more
     mobile users (e.g., geographic region with more cellular
     connections), it has a HIGHER percentage of slow clients.

  3. GC pressure: Server 3 may have had more accumulated
     garbage from prior events, leaving less actual free heap.

Likely scenario:
  Server 3: 330K connections (10% over average)
             55% slow clients (slightly worse audience mix)

  Memory calculation for Server 3:
    Baseline: 330,000 × 15KB = 4.95GB
    Spike:    181,500 slow × 20KB = 3.63GB
    TOTAL:    4.95GB + 3.63GB = 8.58GB

    8.58GB > 8GB container limit → OOM KILL

  Meanwhile, Server 1 with 280K connections:
    Baseline: 280,000 × 15KB = 4.2GB
    Spike:    140,000 slow × 20KB = 2.8GB
    TOTAL:    4.2GB + 2.8GB = 7.0GB → SURVIVES (barely)

Server 3 hits the OOM threshold first because of the
combination of slightly more connections AND slightly
more slow clients. It's not dramatic — maybe 10-15%
more load than average. But when you're operating at
94% memory utilization baseline, 10% more is fatal.
```

---

## Question 2: The Cascade Chain

### The Exact Sequence

```
TIME    EVENT                           SYSTEM STATE
─────   ─────────────────────────────   ──────────────────────────
14:47   Goal scored. Broadcast begins.  4 servers, 1.2M connections
        All servers spike memory.       All servers at 88-94% memory

14:47   Server 3 OOM killed.            3 servers, 870K connections
        +03s                            330K connections DROPPED

14:47   330K clients begin reconnecting  3 servers absorbing reconnections
        +05s  to the 3 surviving servers

14:47   Reconnections complete.          3 servers, ~1.2M connections
        +15s  Servers now have ~400K     Servers at 93-97% memory
              connections each.          (baseline alone is near limit)

14:48   Commentary update message sent.  Another broadcast to all connections
        Even a 3KB message now fatal.
        400K × 3KB slow-client queue
        = 1.2GB spike on servers
        already at 97% memory.

14:48   Server 1 OOM killed.            2 servers, ~800K connections
        +08s  (had received most of
              Server 3's reconnections
              due to LB round-robin)

14:48   400K connections reconnect to    2 servers, 600K each
        +20s  Servers 2 and 4.           Memory: catastrophically oversubscribed
              Just the CONNECTION STATE
              alone: 600K × 15KB = 9GB
              EXCEEDS 8GB CONTAINER LIMIT
              Servers OOM on connection
              acceptance — don't even
              need a broadcast event.

14:48   Servers 2 and 4 OOM killed.     0 servers. Complete outage.
        +25s                            1.2M users see "Connection Lost"
```

### Why Each Death Made Things Worse — The Positive Feedback Loop

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   Server dies                                                ║
║     │                                                        ║
║     ▼                                                        ║
║   Connections redistribute to survivors                      ║
║     │                                                        ║
║     ▼                                                        ║
║   Each survivor now has MORE connections                     ║
║     │                                                        ║
║     ├──► More baseline memory consumed (connection state)    ║
║     │                                                        ║
║     ├──► More write buffers to fill on next broadcast        ║
║     │                                                        ║
║     ├──► More slow clients in the mix                        ║
║     │                                                        ║
║     ╰──► Less headroom for ANY memory spike                  ║
║            │                                                 ║
║            ▼                                                 ║
║          Next broadcast (or even next small message)         ║
║          triggers OOM on the weakest survivor                ║
║            │                                                 ║
║            ▼                                                 ║
║          Server dies ──────► LOOP REPEATS                    ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

**The critical insight: each server death doesn't just redistribute load — it REDUCES the system's total memory capacity while INCREASING per-server memory demand.**

```
QUANTIFIED DEGRADATION:

4 servers: Total capacity = 32GB, 300K conn/server
  Per-server headroom: 3.5GB → CAN survive a broadcast

3 servers: Total capacity = 24GB, 400K conn/server
  Per-server baseline: 400K × 15KB = 6.0GB
  Per-server headroom: 2.0GB → CANNOT survive a full broadcast
  Even a SMALL message kills the weakest server

2 servers: Total capacity = 16GB, 600K conn/server
  Per-server baseline: 600K × 15KB = 9.0GB
  9.0GB > 8.0GB container limit
  → OOM on CONNECTION STATE ALONE
  → Servers die WITHOUT any broadcast
  → The cascade becomes SELF-SUSTAINING

This is why the cascade accelerates:
  First death:  took ~3 seconds (broadcast-triggered)
  Second death: took ~8 seconds (small message triggered)
  Third+Fourth: took ~5 seconds (connection state alone)

  Total time from first failure to complete outage: ~25 seconds
  Too fast for any human to intervene.
```

### Why Reconnection Makes It Worse (The Thundering Herd)

```
When Server 3 dies, 330K clients don't reconnect gracefully.
They ALL attempt to reconnect SIMULTANEOUSLY.

WebSocket reconnection handshake is MORE expensive than
a steady-state connection:

  Steady-state connection: ~15KB memory
  Reconnection handshake:  ~30-50KB memory (temporarily)
    - TLS handshake state
    - HTTP upgrade negotiation buffers
    - Session restoration/rehydration
    - Initial state sync message (catch up on missed events)

So 330K simultaneous reconnections hitting 3 servers:
  110K reconnections per server × 40KB = 4.4GB SPIKE
  ON TOP of existing 4.5GB baseline
  = 8.9GB → OOM even BEFORE the connection is fully established

The reconnection storm itself can trigger OOM
before any subsequent broadcast even happens.
```

---

## Question 3: Immediate Mitigation — Going Back to 14:46

If I have **one minute** before the goal event, here's what I do:

### Action 1: Enable Per-Connection Write Buffer Limits (Seconds 0-20)

```bash
# The DIRECT cause of OOM is unbounded write buffer growth.
# Cap the per-connection application-level write buffer.
# If the buffer exceeds this limit, DROP the connection
# (client will reconnect and catch up via state sync).

# If using a configurable WebSocket framework:
kubectl set env deployment/ws-server \
  MAX_WRITE_BUFFER_PER_CONNECTION=64KB \
  SLOW_CLIENT_TIMEOUT_MS=2000

# Translation:
#   If a client's write buffer exceeds 64KB → disconnect it
#   If a write doesn't flush within 2 seconds → disconnect it
#
# Memory impact:
#   WORST CASE per server: 300K × 64KB = 19.2GB... still too high
#   BUT: most connections flush quickly. The 64KB limit only
#   applies to the slowest 5-10% of clients.
#   Realistic worst case: 30K slow × 64KB = 1.92GB (manageable)
#   + 270K fast × ~0KB = 0GB
#   Total spike: ~2GB within 3.5GB headroom ✓
```

**This single change prevents the OOM.** Slow clients get disconnected and reconnect after the burst. They miss one goal notification but don't bring down the entire system.

### Action 2: Scale Up Horizontally — Add Memory Headroom (Seconds 10-40)

```bash
# Double the server count to halve per-server connection density
kubectl scale deployment/ws-server --replicas=8

# BUT — WebSocket connections are LONG-LIVED and STICKY.
# New replicas won't receive existing connections.
# They'll only receive NEW connections and reconnections.
#
# This alone does NOT help for the 14:47 goal.
# It helps for the CASCADE — if Server 3 dies,
# reconnections spread across 7 servers instead of 3.
```

### Action 3: Increase Container Memory Limits (Seconds 20-45)

```bash
# Buy headroom by increasing the OOM kill threshold
kubectl patch deployment ws-server -p '{
  "spec": {"template": {"spec": {"containers": [{
    "name": "ws-server",
    "resources": {
      "limits": {"memory": "12Gi"},
      "requests": {"memory": "10Gi"}
    }
  }]}}}
}'

# This changes the OOM kill threshold from 8GB to 12GB
# Server 3's spike of 8.58GB now has room to breathe
#
# CAVEAT: Requires available memory on the nodes.
# If nodes are fully committed, this causes evictions.
# Check node allocatable memory FIRST:
kubectl describe nodes | grep -A5 "Allocated resources"
```

### Action 4: Pre-Position a Circuit Breaker on the Event Pipeline (Seconds 30-55)

```bash
# If the broadcast system supports message coalescing or
# rate limiting, enable it NOW:

# Limit broadcast rate to stagger message delivery
kubectl set env deployment/ws-server \
  BROADCAST_RATE_LIMIT=50000/sec \
  BROADCAST_COALESCE_WINDOW_MS=500

# Instead of blasting 300K messages simultaneously,
# stagger delivery over 6 seconds (300K / 50K per sec).
#
# At any given moment, only 50K write buffers are active.
# Memory spike: 25K slow × 20KB = 500MB (trivially safe)
#
# Trade-off: some users see the goal 1-5 seconds later.
# For a live sports broadcast, this is acceptable.
# (TV broadcast delay is already 5-30 seconds.)
```

### Priority If I Can Only Do ONE Thing:

```
╔══════════════════════════════════════════════════════════════╗
║   IF I HAVE 60 SECONDS AND CAN DO ONLY ONE:                  ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   ► ENABLE WRITE BUFFER LIMITS                               ║
║     (Action 1)                                               ║
║                                                              ║
║   This is the ONLY action that directly prevents             ║
║   the OOM on ALL servers for THIS specific event.            ║
║                                                              ║
║   Scaling (Action 2) doesn't help existing conns.            ║
║   Memory increase (Action 3) might not have room.            ║
║   Rate limiting (Action 4) is ideal but may not              ║
║   be supported by current code.                              ║
║                                                              ║
║   Write buffer limits are a CONFIG CHANGE that               ║
║   turns an OOM into a "5% of users briefly                   ║
║   disconnected" — a graceful degradation.                    ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 4: Long-Term Redesign — Surviving 1.2M × 6KB with Zero OOM

### A. The Core Problem: Per-Connection Message Copying

The fundamental architectural flaw is that the broadcast path **copies the message into every connection's write buffer independently**. This means memory scales as `O(connections × message_size)` during broadcast.

**The fix: Shared message buffers with reference counting.**

```
✗ CURRENT ARCHITECTURE (O(N) memory):

  Goal Event
    │
    ▼
  Server receives 6KB message
    │
    ├─► Copy 6KB → Connection 1's write buffer
    ├─► Copy 6KB → Connection 2's write buffer
    ├─► Copy 6KB → Connection 3's write buffer
    │   ... 300,000 times ...
    ╰─► Copy 6KB → Connection 300K's write buffer

  Memory: 300,000 × 6KB = 1.8GB of DUPLICATE data
  All 300,000 copies contain the IDENTICAL bytes.


✓ FIXED ARCHITECTURE (O(1) memory for message storage):

  Goal Event
    │
    ▼
  Server receives 6KB message
    │
    ▼
  Store ONE copy in shared, reference-counted buffer
  refcount = 300,000
    │
    ├─► Connection 1's write buffer: pointer → shared buffer
    ├─► Connection 2's write buffer: pointer → shared buffer
    ├─► Connection 3's write buffer: pointer → shared buffer
    │   ... 300,000 times ...
    ╰─► Connection 300K's write buffer: pointer → shared buffer

  Memory: 6KB (one copy) + 300,000 × 8 bytes (pointers) = 6KB + 2.4MB

  When a connection flushes, it reads from the shared buffer.
  When refcount hits 0, the shared buffer is freed.

  Memory reduction: 1.8GB → 2.4MB (750x improvement)
```

**Implementation pattern — using Go as an example (common for WebSocket servers):**

```go
// Shared broadcast message with reference counting
type BroadcastMessage struct {
    data    []byte       // ONE copy of the 6KB payload
    refCount atomic.Int64
}

func (s *Server) broadcast(msg []byte) {
    shared := &BroadcastMessage{
        data: msg,  // Single allocation: 6KB
    }
    shared.refCount.Store(int64(len(s.connections)))

    for _, conn := range s.connections {
        conn.enqueueBroadcast(shared)  // Enqueues a POINTER, not a copy
    }
}

func (c *Connection) writePump() {
    for msg := range c.broadcastQueue {
        err := c.ws.WriteMessage(websocket.TextMessage, msg.data)
        if remaining := msg.refCount.Add(-1); remaining == 0 {
            // Last connection to flush — free the shared buffer
            pool.Put(msg.data)
        }
        if err != nil {
            // Slow client failed to receive — connection is dead
            c.close()
            return
        }
    }
}
```

### B. Slow Client Handling: Backpressure Policy

**The second critical fix: define an explicit policy for slow clients.**

```go
type SlowClientPolicy struct {
    MaxBufferedMessages int           // Max queued messages before action
    MaxBufferAge        time.Duration // Max age of oldest undelivered message
    Action              string        // "drop_oldest" | "drop_newest" | "disconnect"
}

// Recommended production configuration:
var policy = SlowClientPolicy{
    MaxBufferedMessages: 10,          // If 10+ messages queued, client is too slow
    MaxBufferAge:        5 * time.Second, // If oldest message is 5s old, client is too slow
    Action:              "disconnect",    // Boot them — they'll reconnect and resync
}

func (c *Connection) enqueueBroadcast(msg *BroadcastMessage) {
    if len(c.broadcastQueue) >= c.policy.MaxBufferedMessages {
        switch c.policy.Action {
        case "disconnect":
            // Release references for all queued messages
            for _, queued := range c.broadcastQueue {
                queued.refCount.Add(-1)
            }
            c.close() // Client reconnects, resyncs from last known state
            return
        case "drop_oldest":
            oldest := c.broadcastQueue[0]
            oldest.refCount.Add(-1)
            c.broadcastQueue = c.broadcastQueue[1:]
        }
    }
    c.broadcastQueue = append(c.broadcastQueue, msg)
}
```

**Memory guarantee with this policy:**
```
Max memory per connection from broadcast buffers:
  10 messages × 8 bytes (pointer) = 80 bytes
  (The actual message data is shared — ONE copy total)

Max broadcast memory for 300K connections:
  Shared buffers: 10 × 6KB = 60KB (10 messages in flight)
  Per-connection pointers: 300K × 80B = 24MB
  TOTAL: ~24MB

  Compare to original: 1.8GB - 9.9GB
  That's a 75x-400x reduction.

  OOM is now STRUCTURALLY IMPOSSIBLE from broadcast alone.
```

### C. Staggered Broadcast with Rate Limiting

Even with shared buffers, flushing 300K sockets simultaneously creates CPU and I/O pressure. Stagger the delivery:

```go
func (s *Server) broadcastStaggered(msg *BroadcastMessage) {
    // Deliver in batches of 10,000 with 50ms gaps
    batchSize := 10_000
    batchDelay := 50 * time.Millisecond

    for i := 0; i < len(s.connections); i += batchSize {
        end := min(i+batchSize, len(s.connections))
        batch := s.connections[i:end]

        for _, conn := range batch {
            conn.enqueueBroadcast(msg)
        }

        if end < len(s.connections) {
            time.Sleep(batchDelay)
        }
    }
    // 300K connections / 10K per batch = 30 batches
    // 30 × 50ms = 1.5 seconds total delivery time
    // Users receive goal notification within 0-1.5 seconds
    // Well within acceptable latency for live sports
}
```

### D. Connection-Aware Autoscaling with Memory-Based Limits

**Don't scale on CPU — scale on connection count and memory:**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ws-server-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ws-server
  minReplicas: 6
  maxReplicas: 20
  metrics:
    # Scale on MEMORY utilization — the actual bottleneck
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 60    # ← Scale up at 60%, not 80%
                                     # Leaves 40% headroom for broadcast spikes
    # Scale on custom metric: connection count per pod
    - type: Pods
      pods:
        metric:
          name: websocket_active_connections
        target:
          type: AverageValue
          averageValue: "150000"    # ← Max 150K connections per pod
                                    # At 15KB each = 2.25GB baseline
                                    # On 8GB pod = 72% headroom for spikes
```

### E. Cascade Prevention: Reconnection Backoff and Admission Control

**The cascade was caused by thundering herd reconnection. Fix it at two levels:**

**Client-side: Exponential backoff with jitter on reconnection:**
```javascript
// Client-side WebSocket reconnection logic
function reconnect(attempt = 0) {
    // Exponential backoff: 1s, 2s, 4s, 8s... capped at 30s
    const baseDelay = Math.min(1000 * Math.pow(2, attempt), 30000);

    // Jitter: randomize within ±50% of base delay
    // This SPREADS 330K reconnections over time instead of
    // all hitting at once
    const jitter = baseDelay * (0.5 + Math.random());

    setTimeout(() => {
        const ws = new WebSocket(url);
        ws.onerror = () => reconnect(attempt + 1);
    }, jitter);
}

// 330K clients with jittered backoff:
//   First attempt spread over 0.5s - 1.5s (uniform random)
//   Instead of 330K simultaneous SYNs → ~220K/sec spread evenly
//   Much more survivable for remaining servers
```

**Server-side: Admission control — refuse connections when memory is high:**
```go
func (s *Server) handleNewConnection(w http.ResponseWriter, r *http.Request) {
    // Check memory before accepting ANY new connection
    var memStats runtime.MemStats
    runtime.ReadMemStats(&memStats)

    memoryUsagePercent := float64(memStats.Alloc) / float64(s.memoryLimit)

    if memoryUsagePercent > 0.75 {
        // Server is too hot — reject the connection
        // Client will retry with backoff and hit a different server
        w.Header().Set("Retry-After", "5")
        http.Error(w, "Server at capacity", http.StatusServiceUnavailable)
        return
    }

    if s.connectionCount.Load() >= s.maxConnections {
        http.Error(w, "Connection limit reached", http.StatusServiceUnavailable)
        return
    }

    // Accept the connection
    upgrader.Upgrade(w, r, nil)
}
```

**This makes the cascade structurally impossible:**
```
Server 3 dies → 330K clients reconnect with jittered backoff
  → Reconnections arrive gradually over 1-2 seconds
  → Each surviving server checks memory before accepting
  → At 75% memory, server REJECTS new connections
  → Rejected clients retry with backoff, hit other servers
  → No single server is overwhelmed
  → Cluster stabilizes at reduced but FUNCTIONING capacity
  → New replicas scale up and gradually absorb connections
```

### F. Infrastructure: Dedicated Broadcast Tier (Pub/Sub Decoupling)

**For true planet-scale (1M+ connections), decouple connection management from message routing:**

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   Event Source (Goal Scored)                                 ║
║     │                                                        ║
║     ▼                                                        ║
║   Message Bus (Redis Pub/Sub / NATS / Kafka)                 ║
║     │                                                        ║
║     ├──► WS Edge Server 1 (150K connections)                 ║
║     ├──► WS Edge Server 2 (150K connections)                 ║
║     ├──► WS Edge Server 3 (150K connections)                 ║
║     ├──► WS Edge Server 4 (150K connections)                 ║
║     ├──► WS Edge Server 5 (150K connections)                 ║
║     ├──► WS Edge Server 6 (150K connections)                 ║
║     ├──► WS Edge Server 7 (150K connections)                 ║
║     ╰──► WS Edge Server 8 (150K connections)                 ║
║                                                              ║
║   Each edge server:                                          ║
║     - Receives ONE copy of the message from the bus          ║
║     - Stores it in a shared buffer (6KB)                     ║
║     - Delivers to its 150K connections with                  ║
║       staggered broadcast + slow client policy               ║
║     - Max broadcast memory: ~12MB per server                 ║
║                                                              ║
║   If any edge server dies:                                   ║
║     - Its 150K clients reconnect to OTHER edge servers       ║
║     - 150K / 7 remaining = 21K additional per server         ║
║     - 171K × 15KB = 2.57GB baseline (on 8GB server)          ║
║     - MASSIVE headroom — cascade is impossible               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

**Tools:**

```
╔══════════════════════════════════════════════════════════════════╗
║  COMPONENT    │ TOOL                              │ WHY          ║
╠══════════════════════════════════════════════════════════════════╣
║  Message bus  │ NATS or Redis Pub/Sub             │ Sub-ms fan-  ║
║               │                                   │ out; millions║
║               │                                   │ msg/sec      ║
╠══════════════════════════════════════════════════════════════════╣
║  Edge servers │ Go + nhooyr/websocket or          │ Low per-conn ║
║               │ Rust + tokio-tungstenite          │ overhead;    ║
║               │                                   │ zero-copy    ║
╠══════════════════════════════════════════════════════════════════╣
║  Autoscaling  │ KEDA (K8s Event Driven Autoscaler)│ Scale on conn║
║               │                                   │ count, not   ║
║               │                                   │ just CPU     ║
╠══════════════════════════════════════════════════════════════════╣
║  Observability│ Prometheus + Grafana              │ Per-server   ║
║               │                                   │ memory, conn ║
║               │                                   │ count, buffer║
╚══════════════════════════════════════════════════════════════════╝
```

### G. Complete Fix Matrix

```
╔═══════════════════════════════════════════════════════════════════════════════════╗
║  LAYER                │ FIX                              │ TOOL / PATTERN         ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║  Message memory       │ Shared buffer, reference counted │ Zero-copy broadcast    ║
║                       │ One copy per message, not per    │ pattern                ║
║                       │ connection                       │                        ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║  Slow clients         │ Bounded write queue + disconnect │ Backpressure policy    ║
║                       │ policy (max 10 msgs or 5s age)   │                        ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║  Broadcast delivery   │ Staggered batch delivery         │ Rate-limited fan-out   ║
║                       │ (10K/batch, 50ms gap)            │                        ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║  Cascade prevention   │ Client: exponential backoff      │ Jittered backoff       ║
║                       │ + jitter on reconnection         │                        ║
║                       │ Server: admission control at     │ Connection admission   ║
║                       │ 75% memory, reject new conns     │ control                ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║  Autoscaling          │ Scale on memory (60% target) AND │ KEDA + custom          ║
║                       │ connection count (150K max/pod)  │ Prometheus metrics     ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║  Architecture         │ Decouple: Message bus → Edge     │ NATS / Redis PubSub    ║
║                       │ servers. Each edge manages its   │ + Go/Rust edge tier    ║
║                       │ own connection pool.             │                        ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║  Connection density   │ 8 servers × 150K = 1.2M          │ More servers, fewer    ║
║                       │ (not 4 × 300K)                   │ connections each       ║
║                       │ Lose one = absorb 21K each       │                        ║
║                       │ (not 100K each)                  │                        ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║  Observability        │ Alert on: per-server memory >70% │ Prometheus + PagerDuty ║
║                       │ write buffer depth > 5           │                        ║
║                       │ slow client disconnect rate >1%  │                        ║
║                       │ connection count skew >20%       │                        ║
╚═══════════════════════════════════════════════════════════════════════════════════╝
```

### The Layered Defense:

```
Shared buffers eliminate O(N) MEMORY MULTIPLICATION.
Backpressure policy eliminates UNBOUNDED BUFFER GROWTH.
Staggered broadcast eliminates SIMULTANEOUS I/O PRESSURE.
Admission control eliminates CASCADE PROPAGATION.
Jittered backoff eliminates THUNDERING HERD RECONNECTION.
Lower connection density eliminates SINGLE-SERVER CRITICALITY.
Pub/Sub decoupling eliminates BROADCAST AS A SINGLE POINT OF FAILURE.

Each layer defends against a different failure mode.
Together, they make 1.2M × 6KB broadcast structurally safe
with memory headroom to spare.
```
