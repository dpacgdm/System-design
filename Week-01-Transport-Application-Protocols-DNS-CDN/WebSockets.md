# Topic 4: WebSockets vs Server-Sent Events vs Long Polling

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Explain WHY standard HTTP is insufficient for           ║
║      real-time communication and what each solution          ║
║      does differently at the protocol level                  ║
║                                                              ║
║   2. Choose the correct real-time technology for a           ║
║      given system design (chat, notifications, live          ║
║      dashboards, collaborative editing, gaming)              ║
║      and DEFEND the choice                                   ║
║                                                              ║
║   3. Diagnose real-time connection failures in               ║
║      production using specific tools and metrics             ║
║                                                              ║
║   4. Identify and fix common production failures:            ║
║      connection leaks, thundering herd on reconnect,         ║
║      proxy/LB misconfigurations, memory exhaustion           ║
║                                                              ║
║   5. Calculate connection capacity for a real-time           ║
║      system and know when you're hitting limits              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

### Foundation

> Progress through Foundation → Staff → Principal stretch. Staff is the mastery gate.


```
╔═════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "WebSockets replace HTTP entirely"                   ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. WebSockets start as an HTTP Upgrade handshake, then            ║
║   switch protocols. Initial page load, auth, and REST calls             ║
║   still use HTTP. WebSockets handle persistent bidirectional            ║
║   streams — not general-purpose request/response.                       ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "One WebSocket = one free persistent channel"        ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Each connection holds server memory, file descriptors,         ║
║   and LB state. At 100K concurrent connections, heartbeat               ║
║   traffic alone can saturate CPU. Capacity planning is mandatory.       ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Always use WebSockets for real-time"                ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Server-Sent Events (SSE) is simpler for server→client          ║
║   push (notifications, live feeds). Long polling works through          ║
║   corporate proxies that block WebSocket upgrades. Match the            ║
║   directionality and infrastructure constraints.                        ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Load balancers handle WebSockets automatically"     ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. WebSockets require sticky sessions or shared pub/sub           ║
║   backplanes. Without them, reconnects land on different nodes          ║
║   and lose in-memory state. Idle timeout and proxy buffering            ║
║   silently kill connections.                                            ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "TCP keepalive is enough — no app heartbeat"         ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. NAT gateways and L4 load balancers drop idle TCP               ║
║   connections in 30–600s without sending RST. Application-level         ║
║   ping/pong detects dead peers and triggers clean reconnect.            ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Reconnect storms are rare edge cases"               ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Deployments and network blips disconnect thousands at          ║
║   once. Without jittered exponential backoff and server-side            ║
║   rate limiting, thundering herd reconnects take down the               ║
║   service you were trying to keep real-time.                            ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## The Problem: HTTP's Request-Response Limitation

Everything we've learned so far — REST, GraphQL, gRPC unary — follows one pattern:

```
CLIENT INITIATES. SERVER RESPONDS. DONE.

Client ──── Request ────► Server
Client ◄─── Response ──── Server
       (connection idle or closed)

The client ALWAYS speaks first.
The server can NEVER send data unprompted.

This is fine for:
  - Loading a web page
  - Submitting a form
  - Fetching search results

This is TERRIBLE for:
  - Chat messages (need instant delivery)
  - Stock prices (change every millisecond)
  - Notifications (server needs to push)
  - Live sports scores
  - Collaborative editing (see others' cursors)
  - Multiplayer games (continuous state updates)

The fundamental question:
  "How does the server send data to the client
   WITHOUT the client asking for it?"
```

There are exactly three mainstream solutions to this problem. Let's go through each one deeply, starting with the oldest and simplest.

---

## Solution 1: Long Polling (The Clever Hack)

### The Idea

```
Normal polling (TERRIBLE):

  Client: "Any new messages?"    Server: "No."
  (wait 1 second)
  Client: "Any new messages?"    Server: "No."
  (wait 1 second)
  Client: "Any new messages?"    Server: "No."
  (wait 1 second)
  Client: "Any new messages?"    Server: "Yes! Here."

  Problems:
  → 75% of requests are wasted (no new data)
  → If you poll every 1s: 86,400 requests/day per client
  → 1 million users × 86,400 = 86.4 BILLION requests/day
  → Plus: up to 1 second delay before seeing new data
  → More frequent polling = less delay but MORE waste


Long polling (THE FIX):

  Client: "Any new messages?"
  Server: (holds the connection open)
  Server: (waits...)
  Server: (waits... 10 seconds... 20 seconds...)
  Server: "Yes! Here's a message." (responds after 25 seconds)
  Client: (immediately sends another request)
  Client: "Any new messages?"
  Server: (holds again...)

  The key insight: The server DELAYS its response
  until it actually has something to say.
```

### How Long Polling Works — Protocol Level

```
STEP BY STEP:

1. Client sends normal HTTP request
   GET /api/messages?since=timestamp_123 HTTP/1.1
   Host: chat.example.com

2. Server receives request
   → Checks: any new messages since timestamp_123?
   → If YES: respond immediately with new messages
   → If NO: HOLD the connection open. Don't respond yet.

3. Server holds the connection
   → Keeps the HTTP connection open
   → Waits for one of two things:
     a) New data arrives → respond with data
     b) Timeout (e.g., 30 seconds) → respond with
        empty body (204 No Content or empty array)

4. Client receives response
   → Processes any new data
   → IMMEDIATELY sends a new long-poll request
   → Back to step 1

TIMING DIAGRAM:

Client                              Server
  │                                    │
  │── GET /messages?since=100 ────────►│
  │                                    │ (holds connection)
  │         (waiting...)               │ (no new messages)
  │         (25 seconds pass)          │
  │                                    │ New message arrives!
  │◄── 200 OK [{msg: "hello"}] ────────│
  │                                    │
  │── GET /messages?since=101 ────────►│  (immediate reconnect)
  │                                    │ (holds connection)
  │         (waiting...)               │
  │         (30 second timeout)        │
  │◄── 204 No Content ─────────────────│  (timeout, no data)
  │                                    │
  │── GET /messages?since=101 ────────►│  (immediate reconnect)
  │                                    │
```

### Long Polling Characteristics

```
ADVANTAGES:
  ✓ Works EVERYWHERE
    → Standard HTTP. No special protocol.
    → Works through every proxy, firewall, CDN
    → Works with HTTP/1.1 (no HTTP/2 needed)
    → Works in ancient browsers
    → Works behind corporate firewalls that block
      non-HTTP traffic

  ✓ Simple to implement
    → Client: just make HTTP requests in a loop
    → Server: hold the response, respond when ready
    → No special libraries needed

  ✓ Reliable message delivery
    → Each response is a standard HTTP response
    → Client can track "last seen" timestamp/ID
    → If connection drops, client reconnects with
      last seen ID → no missed messages

  ✓ Naturally works with REST infrastructure
    → Load balancers, API gateways, monitoring
    → All existing HTTP tooling works

DISADVANTAGES:
  ✗ LATENCY
    → Minimum delay = network RTT after event occurs
    → Must complete response + new request cycle
    → Typically 50-200ms delay per message
    → Worse than WebSockets (which are instant)

  ✗ OVERHEAD
    → Every reconnect sends FULL HTTP headers
    → Cookies, auth tokens, user-agent, etc.
    → 500+ bytes of headers for each reconnect
    → At scale: significant bandwidth waste

  ✗ SERVER RESOURCE CONSUMPTION
    → Each waiting client = one held HTTP connection
    → Each connection = a thread or file descriptor
    → 100,000 concurrent users = 100,000 open connections
    → Traditional thread-per-connection servers (Apache)
      CANNOT handle this
    → Need async/event-driven servers (Node.js, Nginx, Go)

  ✗ UNIDIRECTIONAL
    → Server can push to client ✓
    → But client must still use separate POST requests
      to send data TO the server
    → Not a bidirectional channel

  ✗ TIMEOUT COMPLEXITY
    → Must handle: server timeout, proxy timeout,
      LB timeout, client timeout
    → Proxy/LB typically kills idle connections at 60s
    → Server timeout must be SHORTER than proxy timeout
    → Or the proxy kills the connection before the
      server can respond
```

### Server Implementation Pattern

```
# Python/Flask-style pseudocode

@app.route('/api/messages')
def long_poll(request):
    last_seen = request.args.get('since')
    timeout = 30  # seconds
    start = time.now()

    while time.now() - start < timeout:
        messages = db.get_new_messages(since=last_seen)

        if messages:
            return Response(
                json.dumps(messages),
                status=200,
                content_type='application/json'
            )

        # No messages yet — wait a bit and check again
        # DON'T busy-loop! Use event/notification system
        await message_event.wait(timeout=1)

    # Timeout reached, no new messages
    return Response(status=204)


# BETTER implementation using pub/sub:
@app.route('/api/messages')
async def long_poll(request):
    last_seen = request.args.get('since')

    # Check for already-available messages first
    messages = db.get_new_messages(since=last_seen)
    if messages:
        return Response(json.dumps(messages), status=200)

    # No messages — subscribe and wait
    future = asyncio.Future()

    def on_new_message(msg):
        if not future.done():
            future.set_result(msg)

    pubsub.subscribe(f'user:{user_id}:messages', on_new_message)

    try:
        result = await asyncio.wait_for(future, timeout=30)
        return Response(json.dumps(result), status=200)
    except asyncio.TimeoutError:
        return Response(status=204)
    finally:
        pubsub.unsubscribe(f'user:{user_id}:messages',
                           on_new_message)
```

---

## Solution 2: Server-Sent Events (SSE)

### The Idea

```
Long polling: Client reconnects after every response
SSE: Server keeps ONE connection open and streams
     data continuously over it

It's a PERSISTENT one-way channel from server to client.
```

### How SSE Works — Protocol Level

```
SSE uses standard HTTP. The magic is in the
Content-Type and the response format.

REQUEST (standard HTTP):
  GET /api/stream/notifications HTTP/1.1
  Host: example.com
  Accept: text/event-stream        ← Key header

RESPONSE (never-ending):
  HTTP/1.1 200 OK
  Content-Type: text/event-stream  ← Key header
  Cache-Control: no-cache
  Connection: keep-alive

  data: {"type": "notification", "msg": "New follower"}

  data: {"type": "notification", "msg": "Someone liked your post"}

  event: price-update
  data: {"symbol": "AAPL", "price": 178.50}

  event: price-update
  data: {"symbol": "GOOGL", "price": 141.20}

  id: 12345
  event: message
  data: {"from": "alice", "text": "hello"}

  : this is a comment (heartbeat/keepalive)

  (connection stays open, more events sent as they occur)

FORMAT RULES:
  → Each message is a block of text
  → Fields: data, event, id, retry
  → Messages separated by blank lines (\n\n)
  → data: contains the payload (can be multi-line)
  → event: names the event type (optional)
  → id: unique ID for last-event-id tracking
  → retry: tells client how long to wait before reconnecting
  → Lines starting with : are comments (used as heartbeats)
```

### SSE's Built-In Reconnection (This Is Huge)

```
SSE has AUTOMATIC reconnection built into the browser API.

The EventSource API handles:
  1. Connection drops → auto-reconnect
  2. Sends Last-Event-ID header on reconnect
  3. Server can resume from where it left off

CLIENT CODE (JavaScript — this is the entire implementation):

  const source = new EventSource('/api/stream/notifications');

  source.onmessage = (event) => {
    console.log('New data:', event.data);
  };

  source.addEventListener('price-update', (event) => {
    const data = JSON.parse(event.data);
    updatePrice(data.symbol, data.price);
  });

  source.onerror = (error) => {
    // Browser AUTOMATICALLY reconnects!
    // You don't have to do anything!
    // It sends Last-Event-ID header on reconnect
    console.log('Connection lost, auto-reconnecting...');
  };

  That's it. 10 lines of code.
  Compare to WebSocket implementation (shown later).

RECONNECTION FLOW:

  Client                              Server
    │                                    │
    │── GET /stream                      │
    │   Accept: text/event-stream ──────►│
    │                                    │
    │◄── id: 100                         │
    │    data: message 1 ────────────────│
    │                                    │
    │◄── id: 101                         │
    │    data: message 2 ────────────────│
    │                                    │
    │     ✗ CONNECTION DROPS ✗          │
    │                                    │
    │  (browser waits 3 seconds)         │
    │                                    │
    │── GET /stream                      │
    │   Accept: text/event-stream        │
    │   Last-Event-ID: 101 ─────────────►│  ← Auto-sent!
    │                                    │
    │◄── id: 102                         │
    │    data: message 3 ────────────────│  ← Resumes!
    │                                    │

  No messages lost. No client-side reconnection logic.
  The browser handles it all.
```

### SSE Characteristics

```
ADVANTAGES:
  ✓ SIMPLE
    → Standard HTTP. No protocol upgrade.
    → Built-in browser API (EventSource)
    → 10 lines of client code
    → Automatic reconnection with last-event-id

  ✓ WORKS WITH HTTP/2
    → Multiplexed with other requests
    → No connection limit issues
    → One TCP connection can carry SSE + regular requests

  ✓ WORKS THROUGH PROXIES/FIREWALLS
    → Standard HTTP response
    → Most proxies pass it through
    → Some proxies buffer (we'll cover this in failures)

  ✓ AUTOMATIC RESUME
    → Last-Event-ID sent on reconnect
    → Server can resume from exact point of disconnection
    → No message loss (if server implements ID tracking)

  ✓ TEXT-BASED (debuggable)
    → Can see events in browser DevTools
    → Can curl the endpoint and watch events stream
    → Easy to debug

  ✓ NATIVE TO BROWSERS
    → No library needed
    → EventSource API built into every modern browser

DISADVANTAGES:
  ✗ UNIDIRECTIONAL (server → client ONLY)
    → Client CANNOT send data over the SSE connection
    → Must use separate HTTP requests to send data to server
    → Fine for notifications, stock prices, dashboards
    → NOT suitable for chat (need bidirectional)

  ✗ TEXT ONLY
    → Cannot send binary data natively
    → Must base64-encode binary (33% overhead)
    → WebSockets can send binary frames natively

  ✗ CONNECTION LIMIT (HTTP/1.1)
    → Browsers limit to 6 connections per origin on HTTP/1.1
    → SSE holds one of those 6 permanently
    → Only 5 left for other requests
    → SOLVED by HTTP/2 (multiplexing, no limit)

  ✗ NO NATIVE MOBILE SUPPORT
    → EventSource exists in browsers
    → iOS/Android don't have built-in EventSource
    → Need a library (OkHttp SSE for Android, etc.)
    → WebSockets have better native mobile support

  ✗ PROXY BUFFERING
    → Some reverse proxies buffer the response
    → They wait for the "complete" response before forwarding
    → SSE response NEVER completes (it's a stream)
    → Result: client sees nothing until proxy times out
    → Must configure proxies to disable buffering:
      Nginx: proxy_buffering off;
      Apache: ProxyPass with flushpackets=on
```

---

## Solution 3: WebSockets

### The Idea

```
Long Polling: Hack on top of HTTP (repeated connections)
SSE: One-way stream over HTTP
WebSockets: FULL-DUPLEX, BIDIRECTIONAL channel that is
            NOT HTTP (after the initial handshake)

WebSockets REPLACE HTTP with a different protocol
on the same TCP connection.
```

### How WebSockets Work — Protocol Level

```
STEP 1: HTTP Upgrade Handshake

  Client sends a NORMAL HTTP request with special headers:

  GET /chat HTTP/1.1
  Host: chat.example.com
  Upgrade: websocket              ← "I want to upgrade"
  Connection: Upgrade             ← "Switch protocols"
  Sec-WebSocket-Key: dGhlIHNhb... ← Random base64 key
  Sec-WebSocket-Version: 13       ← Protocol version

  Server responds:

  HTTP/1.1 101 Switching Protocols  ← "OK, upgrading"
  Upgrade: websocket
  Connection: Upgrade
  Sec-WebSocket-Accept: s3pPLM... ← Hash of client's key
                                     (proves server
                                      understood the request)

  After this handshake, the HTTP protocol is GONE.
  The TCP connection is now a WebSocket connection.
  Both sides can send data AT ANY TIME.

STEP 2: Bidirectional Communication

  Client ◄──────────────────────── Server
  Client ────────────────────────► Server

  Either side can send at any time.
  No request/response pattern.
  No headers repeated.
  Minimal framing overhead.
```

### WebSocket Frame Format

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
├─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┤
│F│R│R│R│ Opcode │M│  Payload  │  Extended payload length    │
│I│S│S│S│  (4)   │A│  length   │  (if payload len == 126)    │
│N│V│V│V│        │S│   (7)     │                             │
│ │1│2│3│        │K│           │                             │
├─┴─┴─┴─┴────────┼─┴───────────┴─────────────────────────────┤
│                 │  Extended payload length continued       │
│                 │  (if payload len == 127)                 │
├─────────────────┴──────────────────────────────────────────┤
│  Masking key (if MASK bit set — required client → server)  │
├────────────────────────────────────────────────────────────┤
│  Payload data                                              │
╰────────────────────────────────────────────────────────────╯

KEY POINTS:
  FIN bit: Is this the final fragment? (for large messages)
  Opcode:
    0x1 = text frame
    0x2 = binary frame
    0x8 = connection close
    0x9 = ping
    0xA = pong
  MASK: Client-to-server frames MUST be masked
        Server-to-client frames MUST NOT be masked
        (security: prevents cache poisoning attacks)

OVERHEAD COMPARISON:
  HTTP request:  ~500-2000 bytes of headers PER message
  WebSocket frame: 2-14 bytes of framing PER message

  For a chat app sending "hello" (5 bytes):
    HTTP: 500 bytes headers + 5 bytes data = 505 bytes
    WS:   6 bytes framing + 5 bytes data = 11 bytes

    WebSocket is 45x more efficient per message.
    At millions of messages, this is massive.
```

### WebSocket Ping/Pong (Keep-Alive)

```
WebSocket connections are long-lived.
How to detect dead connections?

PING/PONG mechanism (built into the protocol):

  Server ── PING frame ──► Client
  Server ◄── PONG frame ── Client  (automatic, browser handles it)

  If PONG doesn't arrive within timeout → connection dead.
  Close it, free resources.

APPLICATION-LEVEL HEARTBEAT (more common in practice):

  Many implementations don't use protocol-level ping/pong.
  Instead, they send application-level heartbeat messages:

  Server ── {"type": "ping"} ──► Client
  Server ◄── {"type": "pong"} ── Client

  WHY application-level?
  → More control over timing
  → Can include useful data (server timestamp, queue depth)
  → Some proxies/LBs don't pass through WS ping/pong
  → Easier to monitor and log

TYPICAL CONFIGURATION:
  → Send ping every 30 seconds
  → If no pong within 10 seconds → close connection
  → This detects dead connections within 40 seconds

  Trade-off:
    More frequent pings → faster detection, more overhead
    Less frequent pings → slower detection, less overhead
```

### WebSocket Subprotocols

```
WebSockets transport raw messages. They have no
opinion on message FORMAT. You must define your own.

Common patterns:

1. RAW JSON (simple, most common):
   {"type": "message", "from": "alice", "text": "hello"}
   {"type": "typing", "user": "bob"}
   {"type": "presence", "user": "alice", "status": "online"}

2. STOMP (Simple Text Oriented Messaging Protocol):
   SEND
   destination:/topic/chat/room-123
   content-type:application/json

   {"text": "hello"}
   ^@

   Used with: RabbitMQ WebSocket adapter, Spring

3. Socket.IO protocol:
   Custom binary protocol with rooms, namespaces,
   automatic reconnection, fallback to long polling.

   NOT standard WebSocket — it's a layer on top.
   A Socket.IO client CANNOT talk to a plain WS server.
   A plain WS client CANNOT talk to a Socket.IO server.

   Common mistake: Using Socket.IO when plain WebSocket
   would suffice. Socket.IO adds overhead and complexity.
```

### WebSocket Characteristics

```
ADVANTAGES:
  ✓ FULL DUPLEX
    → Both sides send simultaneously
    → No request/response overhead
    → True bidirectional communication
    → THE choice for chat, gaming, collaboration

  ✓ LOW OVERHEAD
    → 2-14 bytes per frame (vs 500+ bytes for HTTP)
    → No headers repeated per message
    → Massive bandwidth savings at scale

  ✓ LOW LATENCY
    → No HTTP round-trip per message
    → No polling delay
    → Data sent INSTANTLY when available
    → Sub-millisecond delivery on LAN
    → Critical for gaming, trading, collaboration

  ✓ BINARY SUPPORT
    → Can send binary frames natively
    → No base64 encoding needed
    → Efficient for images, audio, files

  ✓ BROAD SUPPORT
    → Every modern browser
    → Every modern language/framework
    → iOS, Android native support
    → Well-supported by load balancers (now)

DISADVANTAGES:
  ✗ COMPLEXITY
    → Must handle connection lifecycle:
      - Connection establishment
      - Authentication (no cookies per-message)
      - Heartbeats
      - Reconnection with state recovery
      - Graceful shutdown
    → SSE gives you reconnection FREE
    → WebSocket: you build it all yourself

  ✗ NOT HTTP (after handshake)
    → HTTP middleware doesn't apply
    → HTTP caching doesn't work
    → HTTP authentication (per-request) doesn't work
    → Must implement auth at WebSocket level
    → Monitoring tools that understand HTTP may not
      understand WebSocket frames

  ✗ STATEFUL
    → Each WebSocket connection is STATEFUL
    → Server must track each connection
    → If server restarts → ALL connections drop
    → Clients must reconnect → thundering herd
    → Load balancing is harder (can't just round-robin
      requests — connections are sticky)

  ✗ PROXY/FIREWALL ISSUES
    → Some corporate proxies don't understand
      the Upgrade header
    → Some proxies drop idle connections aggressively
    → HTTP/2 proxies may not proxy WebSocket correctly
    → TLS (wss://) helps: proxies can't inspect or
      interfere with encrypted upgrade

  ✗ SCALABILITY CHALLENGES
    → Each connection = memory on the server
    → 1 million connections = significant RAM
    → Must route messages to the RIGHT connection
    → Need pub/sub infrastructure (Redis, Kafka)
      to route messages across server instances
    → More complex than stateless HTTP scaling
```

### WebSocket Connection State Management

```
THIS IS THE HARD PART that most tutorials skip.

In a real system with multiple WebSocket servers:

  User Alice → connected to Server 1
  User Bob   → connected to Server 3

  Alice sends a message to Bob.
  Server 1 receives it.
  But Bob is on Server 3!

  How does Server 1 get the message to Server 3?

SOLUTION: Pub/Sub backbone

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Server 1  ─────►  Redis Pub/Sub  ◄─────  Server 3          ║
  ║   (Alice)   ◄─────                 ─────►  (Bob)             ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

  1. Alice sends message to Server 1
  2. Server 1 publishes to Redis channel "user:bob:messages"
  3. Server 3 is subscribed to "user:bob:messages"
  4. Server 3 receives the message
  5. Server 3 pushes it to Bob's WebSocket connection

  This is how WhatsApp, Slack, Discord work at scale.
  The WebSocket servers are just "delivery endpoints."
  The real message routing happens in the pub/sub layer.


CONNECTION REGISTRY:

  You need to track: "Which server holds which user's connection?"

  Option A: Redis hash
    HSET connections user:alice server:1
    HSET connections user:bob server:3

    When message for Bob arrives:
    server = HGET connections user:bob  → server:3
    Publish to server:3's channel

  Option B: Consistent hashing
    Route users to servers deterministically:
    hash(alice) → server 1
    hash(bob) → server 3
    Client connects directly to the "right" server
    No registry needed, but less flexible
```

---

## Complete Comparison

```
Feature              │ Long Polling    │ SSE             │ WebSocket
─────────────────────┼─────────────────┼─────────────────┼─────────────
Direction            │ Server→Client   │ Server→Client   │ Bidirectional
Protocol             │ HTTP            │ HTTP            │ WS (after upgrade)
Connection           │ Repeated        │ Persistent      │ Persistent
Overhead per msg     │ High (headers)  │ Low (text)      │ Very low (2-14B)
Latency              │ Medium (RTT)    │ Low             │ Very low
Binary support       │ Yes (HTTP body) │ No (text only)  │ Yes (native)
Auto-reconnect       │ Manual          │ Built-in        │ Manual
Resume after drop    │ Manual (offset) │ Built-in (ID)   │ Manual
Browser API          │ fetch/XHR       │ EventSource     │ WebSocket
HTTP/2 compatible    │ Yes             │ Yes             │ Separate connection
Proxy-friendly       │ Very            │ Mostly          │ Less
Max connections      │ No limit*       │ 6 per origin**  │ No limit*
                     │                 │ (HTTP/1.1)      │
Scalability          │ Moderate        │ Good            │ Complex

* Subject to server resource limits
** Solved by HTTP/2

DECISION FRAMEWORK:

╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   Need bidirectional? (chat, gaming, collaboration)          ║
║     → WebSocket. No alternative.                             ║
║                                                              ║
║   Server-to-client only? (notifications, feeds, prices)      ║
║     → SSE. Simpler, auto-reconnect, sufficient.              ║
║                                                              ║
║   Must work EVERYWHERE? (corporate, old browsers, IoT)       ║
║     → Long Polling. Universal compatibility.                 ║
║                                                              ║
║   Best practice for production:                              ║
║     → Try WebSocket (or SSE)                                 ║
║     → Fall back to Long Polling if connection fails          ║
║     → This is what Socket.IO does automatically              ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Real-World Usage

```
WHATSAPP / SLACK / DISCORD:
  → WebSockets for message delivery
  → Redis pub/sub for cross-server message routing
  → Long polling as fallback
  → Separate HTTPS API for sending messages
    (Discord actually sends via HTTP POST, receives via WS)

UBER / LYFT:
  → WebSockets for real-time driver location updates
  → Server-side: Kafka + custom routing
  → Fallback to long polling on unreliable networks

STOCK TRADING (Bloomberg, Robinhood):
  → WebSockets for real-time price feeds
  → Binary frames for efficiency
  → Custom reconnection with order book snapshot on resume

LIVE DASHBOARDS (Grafana, Datadog):
  → SSE for metric streams (server → dashboard only)
  → No need for bidirectional — dashboard just displays
  → Simple, reliable, auto-reconnect

NOTIFICATIONS (Twitter/X, Facebook):
  → SSE or WebSocket depending on platform
  → Mobile: push notifications (APNs/FCM) instead
  → Web: SSE or WebSocket for in-app notifications

COLLABORATIVE EDITING (Google Docs, Figma):
  → WebSockets for bidirectional operation streaming
  → Each keystroke/operation sent immediately
  → Operations from others received immediately
  → Operational Transformation or CRDTs for conflict resolution
  → Requires extremely low latency
```

---

## Connection Scaling Math (You Need This For System Design)

```
MEMORY PER CONNECTION:

  Each WebSocket/SSE/long-poll connection consumes:

  OS level:
    → TCP socket buffer: ~87KB default
      (43KB send + 43KB receive on Linux)
    → Can tune down: net.ipv4.tcp_rmem / tcp_wmem
    → Minimum practical: ~8KB per connection
    → File descriptor: ~1KB kernel overhead

  Application level:
    → Connection object: ~2-5KB (varies by framework)
    → User state (auth, subscriptions): ~1-10KB
    → Message buffers: ~1-10KB

  TOTAL: ~10-100KB per connection (tuned vs default)

SCALING MATH:

  Server with 16GB RAM dedicated to connections:

  Conservative (100KB/conn):
    16GB / 100KB = 160,000 connections per server

  Aggressive tuning (10KB/conn):
    16GB / 10KB = 1,600,000 connections per server

  File descriptor limit:
    Default: ulimit -n = 1024 (MUST increase)
    Production: ulimit -n = 1000000

  Port limit:
    Server listening on port 443
    Each client connection uses the CLIENT's ephemeral port
    Server side: one port (443), unlimited connections
    (connections identified by client IP + client port)
    Theoretical max: ~2 billion (all IP:port combos)
    Practical max: limited by memory

REAL-WORLD BENCHMARKS:

  WhatsApp (2012): 2 million connections per server
    → Erlang/FreeBSD, heavily tuned
    → ~10KB per connection

  Phoenix framework (Elixir): 2 million connections
    → Single server demo, 2015

  Node.js (Socket.IO): ~50,000-100,000 connections
    → Without significant tuning
    → V8 garbage collection becomes an issue at scale

  Go (gorilla/websocket): ~500,000-1,000,000
    → Goroutines are lightweight (~8KB stack)
    → Very efficient for connection-heavy workloads

FOR SYSTEM DESIGN INTERVIEWS:
  → Use 100K connections per server as a safe default
  → Mention you can tune to 500K-1M with engineering effort
  → 10 million online users ÷ 100K per server = 100 servers
```

---

## Decision Framework

```
WebSocket vs ALTERNATIVES:

  Server push, bidirectional, low latency chat  → WebSocket (or HTTP/2 SSE for one-way)
  Fire-and-forget events to browser             → SSE (simpler, HTTP/2 friendly)
  Request/response only                           → HTTP/2/3 polling or long-poll (last resort)
  Mobile background unreliable                  → push notifications + REST sync on foreground

LB / PROXY:
  ALB supports WebSocket                        → ensure idle timeout > heartbeat interval
  CloudFront                                    → WebSocket only on specific behaviors
  API Gateway                                   → $connect route + Lambda or HTTP integration
```

---

---

## Production Failure Patterns

### Failure 1: Thundering Herd on Reconnect

```
SCENARIO:
  Server has 200,000 WebSocket connections.
  Server restarts (deploy, crash, OOM kill).
  ALL 200,000 clients detect disconnect.
  ALL 200,000 clients attempt to reconnect.
  SIMULTANEOUSLY.

WHAT HAPPENS:
  → New server starts up
  → 200,000 TCP handshakes arrive within seconds
  → 200,000 WebSocket upgrade requests
  → 200,000 authentication checks (DB/cache queries)
  → Server immediately overwhelmed
  → Most connections fail
  → Clients retry → WORSE thundering herd
  → Server can never recover

  ╔══════════════════════════════════════════════════════════════╗
  ║   Connection attempts over time:                             ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Normal:    ─────────────────────────                       ║
  ║   Restart:   ─────────╱╲───────────────                      ║
  ║                      spike                                   ║
  ║   Thundering:─────────╱ ╲╱ ╲╱ ╲╱ ╲────                       ║
  ║                      repeated spikes                         ║
  ║                      (retry storms)                          ║
  ╚══════════════════════════════════════════════════════════════╝

HOW TO DETECT:
  → Connection rate metric spikes 100x
  → CPU/memory spike on server start
  → Auth service overwhelmed
  → High connection failure rate immediately after deploy

FIX — EXPONENTIAL BACKOFF WITH JITTER:

  Client-side reconnection logic:

  function reconnect(attempt) {
    // Exponential backoff
    const baseDelay = Math.min(1000 * Math.pow(2, attempt), 30000);

    // JITTER — this is the critical part
    // Without jitter: all clients wait 1s, 2s, 4s, 8s...
    //   → They're still synchronized!
    // With jitter: each client waits a RANDOM time
    const jitter = Math.random() * baseDelay;
    const delay = baseDelay / 2 + jitter;

    setTimeout(() => {
      connect();
    }, delay);
  }

  // Attempt 1: wait 0-1000ms   (random per client)
  // Attempt 2: wait 0-2000ms   (random per client)
  // Attempt 3: wait 0-4000ms   (random per client)
  // Attempt 4: wait 0-8000ms   (random per client)

  Result: 200,000 reconnections spread over 30+ seconds
  instead of all hitting at once.

SERVER-SIDE FIX:
  → Connection rate limiting at the load balancer
  → Accept max N new connections per second
  → Excess connections queued or rejected with
    "retry-after" header
```

### Failure 2: Connection Memory Leak

```
SCENARIO:
  WebSocket server in production for 2 weeks.
  Memory usage climbing steadily: 4GB → 8GB → 12GB → OOM.
  Connection count is stable at ~80,000.

  Why? Dead connections not being cleaned up.

ROOT CAUSES:

  A) Client disconnects without sending Close frame
     → Client crashes, network dies, phone loses signal
     → Server doesn't know the connection is dead
     → Connection object stays in memory forever
     → TCP keepalive might detect it (after 2 HOURS default!)

  B) Application-level state not cleaned on disconnect
     → User subscribes to 50 channels on connect
     → Disconnect happens but subscription cleanup fails
     → Subscription objects accumulate
     → Each holds references to callbacks, buffers, etc.

  C) Message queues per connection grow unbounded
     → Slow client can't consume messages fast enough
     → Server buffers messages for that client
     → Buffer grows without limit → memory exhaustion

HOW TO DETECT:
  → Memory growth doesn't correlate with connection count
  → Or: connection count in your app doesn't match
    actual TCP connections:

    # Compare application connection count vs OS connection count
    App says: 80,000 connections
    OS says:  ss -tn state established | grep :443 | wc -l
              → 45,000 connections

    Difference: 35,000 GHOST connections in your app
    that don't exist at the TCP level anymore

FIX:
  → Application-level heartbeat (ping/pong every 30s)
  → If no pong received → force-close connection,
    clean up ALL state
  → Bound per-connection message buffers
    → Max buffer size = 1MB
    → If buffer full → drop oldest messages OR
      close the slow client
  → Periodic reconciliation:
    → Every 5 minutes: compare app connection list
      vs actual TCP sockets
    → Clean up any mismatches
```

### Failure 3: Proxy/Load Balancer Kills Connections

```
SCENARIO:
  WebSocket connections drop every 60 seconds.
  Client reconnects, works for 60 seconds, drops again.
  Like clockwork.

ROOT CAUSE:
  A reverse proxy or load balancer has an IDLE TIMEOUT
  set to 60 seconds.

  WebSocket connections are often idle (waiting for
  the next message). The proxy sees no data flowing
  and kills the "idle" connection.

  ╔══════════════════════════════════════════════════════════════╗
  ║   Client   ◄──WS──►   Nginx   ◄──WS──►   Server              ║
  ╚══════════════════════════════════════════════════════════════╝
                       │
                       ╰── proxy_read_timeout 60s;
                           "No data for 60s? Kill it."

HOW TO DETECT:
  → Connections drop at EXACT intervals (60s, 90s, 120s)
  → Not random — suspiciously regular
  → Check proxy/LB timeout configs

FIX:
  → Send heartbeat SHORTER than proxy timeout:
    If proxy timeout = 60s → heartbeat every 30s
    Proxy sees data flowing → doesn't kill connection

  → Increase proxy timeout:
    Nginx:
      proxy_read_timeout 3600s;    # 1 hour
      proxy_send_timeout 3600s;

    HAProxy:
      timeout tunnel 3600s

    AWS ALB:
      idle_timeout.timeout_seconds = 3600

    AWS NLB:
      TCP idle timeout = 350s (max, not configurable higher)
      → MUST use heartbeats if you need longer

  → Use TLS (wss://)
    → Some proxies are less aggressive with
      encrypted connections
    → They can't inspect the traffic to determine
      if it's "idle"
```

### Failure 4: Single Server Bottleneck (Sticky Sessions)

```
SCENARIO:
  5 WebSocket servers behind a load balancer.
  Server 3 has 2x the connections of others.
  Can't rebalance — connections are STATEFUL.

WHY:
  WebSocket connections are long-lived and sticky.
  Once a client connects to Server 3, it stays there
  until disconnect.

  If Server 3 happened to receive more connections
  during a traffic spike, those connections PERSIST
  long after the spike ends.

  Unlike HTTP where load naturally redistributes
  (each request goes to any server), WebSocket
  connections create permanent imbalances.

HOW TO DETECT:
  → Monitor connection count per server
  → Alert on: max(connections) / avg(connections) > 1.5
  → Check after every deploy or scaling event

FIX:
  → Consistent hashing for connection assignment
    → When new server added, only K/N connections
      need to move (not all of them)
  → Graceful connection draining:
    → When rebalancing: server sends "reconnect"
      message to excess clients
    → Clients reconnect → LB assigns them to
      less-loaded servers
    → Drain slowly (10% at a time) to avoid
      thundering herd
  → Connection-aware load balancing:
    → LB tracks connection count per backend
    → New connections → route to LEAST-CONNECTED server
    → Not round-robin (which ignores existing connections)
```

---

### Staff

## SRE Diagnostic Toolkit

```
WEBSOCKET DEBUGGING:
━━━━━━━━━━━━━━━━━━━

# Test WebSocket connection from command line
# (install: pip install websocket-client)
python3 -c "
import websocket
ws = websocket.create_connection('wss://chat.example.com/ws')
print('Connected')
ws.send('{\"type\": \"ping\"}')
print('Received:', ws.recv())
ws.close()
"

# OR use websocat (like curl for WebSockets)
# install: brew install websocat
websocat wss://chat.example.com/ws
# Type messages, see responses interactively

# Monitor active WebSocket connections on a server
ss -tn state established | grep :443 | wc -l

# Watch connection count over time
watch -n 5 "ss -tn state established | grep :443 | wc -l"

# Check for connection leaks (ghost connections)
# Compare app-level count vs OS-level count:
echo "App connections: $(curl -s localhost:9090/metrics | \
  grep ws_active_connections)"
echo "OS connections: $(ss -tn state established | \
  grep :443 | wc -l)"

# Monitor WebSocket frames in Chrome DevTools:
# Network tab → select WS connection → "Messages" tab
# Shows every frame sent and received with timestamps

# Check file descriptor usage (approaching limit?)
ls /proc/$(pgrep your-app)/fd | wc -l
# Compare to: ulimit -n


SSE DEBUGGING:
━━━━━━━━━━━━━

# Test SSE endpoint with curl (you see events live)
curl -N -H "Accept: text/event-stream" \
  https://example.com/api/stream/events
# -N disables buffering (critical for SSE!)

# Without -N, curl buffers and you see nothing!

# Test SSE with Last-Event-ID (resume)
curl -N -H "Accept: text/event-stream" \
  -H "Last-Event-ID: 12345" \
  https://example.com/api/stream/events

# Check if proxy is buffering SSE
# If you see nothing with curl, but the server
# logs show events being sent → proxy is buffering
# Fix: Add response header:
#   X-Accel-Buffering: no    (Nginx)
#   Cache-Control: no-cache


LONG POLLING DEBUGGING:
━━━━━━━━━━━━━━━━━━━━━━

# Test long poll endpoint
curl -v --max-time 35 \
  "https://example.com/api/poll?since=0"
# --max-time: client-side timeout (must be > server hold time)

# Check if requests are being held (not returning immediately)
# In access logs, look for response times of 20-30s
# That's NORMAL for long polling (means it's working)
# 0ms response time → server isn't holding (broken)

# Count held connections on server
ss -tn state established | grep :443 | wc -l
# High number during low traffic = working correctly
# (connections are being held open)


CAPACITY PLANNING:
━━━━━━━━━━━━━━━━━

# Check current file descriptor limits
ulimit -n           # soft limit
ulimit -Hn          # hard limit
cat /proc/sys/fs/file-max  # system-wide limit

# Check current file descriptor usage
cat /proc/sys/fs/file-nr
# Output: <allocated>  <free>  <max>

# Check memory per connection
# Total RSS of process ÷ connection count
ps -o rss= -p $(pgrep your-app)
# RSS in KB. Divide by connection count.
# If growing over time → likely a leak.

# Check TCP buffer memory
cat /proc/sys/net/ipv4/tcp_rmem  # min default max
cat /proc/sys/net/ipv4/tcp_wmem  # min default max
# Tune down for many connections:
sysctl -w net.ipv4.tcp_rmem="4096 8192 16384"
sysctl -w net.ipv4.tcp_wmem="4096 8192 16384"
```

---

## Hands-On Exercises

```
EXERCISE 1: See SSE In Action
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Terminal 1: Start a simple SSE server
  python3 -c "
from http.server import HTTPServer, BaseHTTPRequestHandler
import time, json

class SSEHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        count = 0
        while True:
            count += 1
            data = json.dumps({'count': count, 'time': time.time()})
            self.wfile.write(f'id: {count}\ndata: {data}\n\n'.encode())
            self.wfile.flush()
            time.sleep(2)

HTTPServer(('localhost', 8080), SSEHandler).serve_forever()
  "

  # Terminal 2: Connect and watch events
  curl -N http://localhost:8080/

  # You'll see events arriving every 2 seconds.
  # Ctrl+C to disconnect.
  # Reconnect with Last-Event-ID:
  curl -N -H "Last-Event-ID: 5" http://localhost:8080/


EXERCISE 2: See WebSocket Connection Count
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # If you have a WebSocket service running:

  # Watch connection count grow
  watch -n 2 "ss -tn state established | grep :YOUR_PORT | wc -l"

  # Open multiple browser tabs to your WebSocket endpoint
  # Watch the count increase with each tab
  # Close tabs — watch it decrease
  #
  # If count DOESN'T decrease → you have a connection leak!


EXERCISE 3: See Proxy Timeout Kill WebSocket
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # If you have Nginx proxying WebSocket:

  # Set a short timeout for testing:
  # proxy_read_timeout 10s;

  # Connect via websocat:
  websocat ws://your-server/ws

  # Don't send anything. Wait.
  # At exactly 10 seconds → connection drops.
  #
  # Now send a message every 5 seconds.
  # Connection stays alive!
  # (Proxy sees activity, resets timeout)
```

---

## Targeted Reading

```
REQUIRED:
  DDIA Chapter 11: "Stream Processing"
  → Pages 440-449 specifically
  → Section on "Messaging Systems"
  → Covers pub/sub concepts that underpin WebSocket
    message routing at scale
  → Skip the Kafka-specific details for now
    (we'll cover that in Week 6)

OPTIONAL:
  RFC 6455 (WebSocket Protocol) — Sections 1-4 only
  → 20 minute read
  → Gives you precise understanding of the handshake
  → Good for "I read the actual RFC" interview cred
```

---

### Principal stretch

## Ops Sim: Northstar Live Auction Reconnect Storm

**Time box:** 30 minutes
**Severity:** P1
**Service / domain:** Bid WebSocket gateway and Redis pub/sub
**Northstar system:** Bid WebSocket, Edge, Session Redis

### Rules

1. Answer from memory; do not re-read the WebSocket section mid-drill.
2. Write decisions in order (T+0 -> T+60).
3. Name evidence for every claim.
4. Do not open the answer key until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  During a luxury-watch auction, bid updates freeze for 20-40s, then arrive in bursts.
  Some clients show "reconnecting..." repeatedly.

WHAT ON-CALL SEES:
  Bid write API is healthy; WebSocket delivery lag p99 is 8.7s.
  NLB target resets increased after an edge config rollout.

BUSINESS CONSTRAINT:
  Closing the auction with stale bid displays creates legal/dispute risk. You may
  pause bid display animations, but accepted bid ordering must remain server-side.
```

### 2. Telemetry pack

```text
METRICS:
  concurrent_ws_connections: 780k -> 510k -> 770k sawtooth every 60s
  ws_reconnect_attempts: 4k/min -> 390k/min
  bid_delivery_lag_p99: 420ms -> 8.7s
  Redis pubsub ops: 180k/s -> 610k/s; Redis CPU node-4=97%
  NLB TCP_Target_Reset_Count: 120/min -> 44k/min
  accepted bid write p99: 38ms; bid ordering service error rate: 0.02%

LOG LINES:
  ws-gateway: close code=1006 idle_timeout client=mobile/7.9.1
  ws-gateway: reconnect token refresh failed; retry_in_ms=1000
  CloudFront: origin-response-timeout changed from 300s to 60s

TRACE:
  client reconnect -> auth session lookup -> subscribe 36 auction channels -> Redis fan-out replay
```

### 3. Config pack

```yaml
# wrong/dangerous rollout
cloudfront:
  origin_response_timeout_seconds: 60
ws_client:
  heartbeat_interval_seconds: 75
  reconnect_backoff: fixed
  reconnect_delay_ms: 1000
redis:
  pubsub_shards: 6
  auction_channel_key: "auction:{auction_id}:bids"
```

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | P1: WebSocket delivery lag exceeds SLO; bid writes remain healthy. | |
| T+5 | Connections drop and reconnect in synchronized 60s waves. | |
| T+15 | Someone proposes doubling WebSocket pods only. | |
| T+60 | Auction close is 10 minutes away; Redis node-4 remains hot. | |

### 5. Questions

**Q1 - Layer & root cause:** Which layer caused the disconnects, and which layer amplified them?

**Q2 - Evidence:** Which signals prove reconnect storm vs bid-write outage?

**Q3 - Sequencing:** What is your first 15-minute mitigation plan?

**Q4 - Bad fix gallery:** Why is "double WebSocket pods" incomplete? Why is "disable all reconnects" unsafe?

**Q5 - Capacity / blast radius:** Estimate auth/session lookups if 260k clients reconnect in one minute and each subscribes to 36 channels.

**Q6 - Durable fix:** What heartbeat, backoff, and channel-sharding changes prevent recurrence?

**Q7 - Org / runbook:** Who must be informed before auction close, and what user-visible degradation is allowed?

**Answer key:** [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/WebSockets Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/WebSockets%20Answers.md)

---

## Key Takeaways

```
╔══════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:             ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. WebSocket = bidirectional, lowest latency,              ║
║      lowest overhead. Use for chat, gaming,                  ║
║      collaboration. But you handle EVERYTHING                ║
║      yourself (reconnect, auth, state management).           ║
║                                                              ║
║   2. SSE = server-to-client only, but with FREE              ║
║      auto-reconnect and resume. Use for                      ║
║      notifications, live feeds, dashboards.                  ║
║      Simpler than WebSocket when you don't need              ║
║      bidirectional.                                          ║
║                                                              ║
║   3. Long Polling = works everywhere, zero special           ║
║      protocol requirements. Use as FALLBACK or when          ║
║      universal compatibility is required.                    ║
║                                                              ║
║   4. WebSocket scaling requires a PUB/SUB backbone           ║
║      (Redis, Kafka) to route messages across                 ║
║      servers. The WebSocket server is just a                 ║
║      delivery endpoint, not the message router.              ║
║                                                              ║
║   5. The #1 production killer for WebSockets is              ║
║      THUNDERING HERD on reconnect. Always implement          ║
║      exponential backoff with JITTER. Without jitter,        ║
║      backoff alone doesn't prevent synchronized              ║
║      retry storms.                                           ║
╚══════════════════════════════════════════════════════════════╝
```

---

# 🔥 SRE SCENARIO — Real-Time Systems

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: Live sports scores platform
  (think ESPN live scores / World Cup tracker)

ARCHITECTURE:
  Mobile/Web clients ──WSS──► 8 WebSocket servers
  (behind AWS NLB, layer 4)

  WebSocket servers ← Redis Pub/Sub ← Score Ingestion
  Service

  Normal operation: 400,000 concurrent WebSocket
  connections across 8 servers (~50K per server)

INCIDENT TIMELINE:
  14:00 — World Cup semifinal kicks off
  14:00-14:45 — Connections climb from 400K to 1.2M
               (expected, provisioned for this)
  14:47 — GOAL SCORED
  14:47:01 — Score Ingestion publishes goal event
             to Redis
  14:47:01 — All 8 WS servers receive the event
             and begin broadcasting to 1.2M clients
  14:47:03 — WebSocket Server 3 goes OOM, crashes
  14:47:04 — Server 3's ~150,000 clients disconnect
  14:47:05 — 150,000 clients begin reconnecting
  14:47:06 — Reconnections hit Servers 1,2,4,5,6,7,8
             (NLB round-robins new TCP connections)
  14:47:08 — Server 7 goes OOM, crashes
             (it received 30K extra connections on
              top of its existing 150K)
  14:47:10 — Server 7's clients start reconnecting
  14:47:12 — Servers 1 and 5 go OOM
  14:47:15 — CASCADING FAILURE across all 8 servers
  14:47:30 — Total platform outage
             1.2 million users see "Connection lost"

MONITORING DATA (captured before servers died):
  → Per-server memory before incident: 12GB / 16GB
  → Message being broadcast:
    {"type":"goal","match":"ARG-FRA",
     "scorer":"Mbappe","minute":47,"score":"1-0",
     "reactions": [...4KB of reaction data...],
     "highlights_url":"...","stats":{...}}
    Total message size: ~6KB
  → Send buffer per connection at crash: ~2MB average
  → Server 3 log just before OOM:
    "WARN: 43,291 connections with send buffer > 1MB"
    "ERROR: Out of memory allocating send buffer"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** Root cause — what specifically caused the OOM? Calculate the math. Why did Server 3 die first while others survived briefly?

**Question 2:** Why did this cascade? Trace the exact cascade chain and explain why each subsequent server failure made things worse.

**Question 3:** Immediate mitigation — if you could go back to 14:46 (1 minute before the goal), what would you change to survive the goal event?

**Question 4:** Long-term redesign — how do you architect this system so it can handle 1.2M connections broadcasting a 6KB message simultaneously without ANY server going OOM? Give specific patterns and configuration changes.
> **Answer key (do not open until you attempt the scenario questions):**
> [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/WebSockets%20Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/WebSockets%20Answers.md)
