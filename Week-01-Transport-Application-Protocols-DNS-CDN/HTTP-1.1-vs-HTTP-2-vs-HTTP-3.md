# Topic 2: HTTP/1.1 vs HTTP/2 vs HTTP/3

> **Prerequisite:** [TCP vs UDP](./TCP%20vs%20UDP.md) — especially TCP HOL blocking,
> congestion control, and connection lifecycle. HTTP/3's design only makes sense once
> you understand why TCP cannot fix stream-level blocking.

---

## Learning Objectives

```
╔═════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                        ║
╟─────────────────────────────────────────────────────────────────╢
║                                                                 ║
║   1. Explain HTTP evolution from 1.0 → 1.1 → 2 → 3 and          ║
║      WHY each version was created (not just feature lists)      ║
║                                                                 ║
║   2. Distinguish HTTP-layer HOL blocking from TCP-layer         ║
║      HOL blocking — and explain why HTTP/2 did NOT fix TCP      ║
║                                                                 ║
║   3. Trace a request through binary framing, streams, HPACK,    ║
║      and explain multiplexing on a single TCP connection        ║
║                                                                 ║
║   4. Explain QUIC's design: UDP encapsulation, per-stream       ║
║      delivery, 0-RTT, connection migration, mandatory TLS       ║
║                                                                 ║
║   5. Diagnose production incidents caused by protocol           ║
║      downgrade (HTTP/2 front, HTTP/1.1 back), request           ║
║      amplification, and QUIC firewall blocking                  ║
║                                                                 ║
║   6. Choose the right HTTP version for a workload and           ║
║      configure load balancers/CDNs without silent regressions   ║
╚═════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "HTTP/2 fixed head-of-line blocking"        ║
╟────────────────────────────────────────────────────────────────╢
║   WRONG. HTTP/2 fixed APPLICATION-LAYER HOL blocking.          ║
║   TCP-layer HOL blocking remains. One lost packet on the       ║
║   single TCP connection stalls ALL HTTP/2 streams.             ║
║   On lossy networks, HTTP/2 can be SLOWER than HTTP/1.1        ║
║   with 6 parallel TCP connections.                             ║
╠════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "HTTP/3 is just HTTP/2 over UDP"            ║
╟────────────────────────────────────────────────────────────────╢
║   WRONG. HTTP/3 replaces TCP with QUIC — a new transport       ║
║   with native streams, integrated TLS 1.3, connection IDs,     ║
║   and userspace deployment. HTTP semantics stay; the           ║
║   transport contract is completely different.                  ║
╠════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "If my ALB supports HTTP/2, backends        ║
║   get HTTP/2 benefits"                                         ║
╟────────────────────────────────────────────────────────────────╢
║   WRONG. Most L7 load balancers TERMINATE HTTP/2 from the      ║
║   client and speak HTTP/1.1 to backends. Multiplexing ends     ║
║   at the LB. Request amplification after a refactor can        ║
║   turn a fast HTTP/2 edge into a serial HTTP/1.1 backend       ║
║   queue — with normal per-request latency metrics.             ║
╠════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "0-RTT is free performance"                 ║
╟────────────────────────────────────────────────────────────────╢
║   WRONG. 0-RTT replays the first flight of data before the     ║
║   handshake completes. It is replayable by attackers. Use      ║
║   only for idempotent operations (GET), never for POST that    ║
║   mutates state.                                               ║
╠════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Enabling HTTP/3 always improves p99"       ║
╟────────────────────────────────────────────────────────────────╢
║   WRONG. Corporate firewalls often block UDP/443. First        ║
║   connection attempts QUIC, waits for timeout (5-8s), then     ║
║   falls back to TCP. p50 may improve; p99 can catastrophically ║
║   worsen for the minority on blocked networks.                 ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

This builds **DIRECTLY** on what you just learned about TCP and UDP. The HOL blocking you explained perfectly in Question 2? That's the **entire reason** HTTP evolved.

---

### First — What IS HTTP?

HTTP (HyperText Transfer Protocol) is an **application-layer** protocol that runs ON TOP of a transport protocol (TCP or UDP). It defines how clients request resources and servers respond.

```text
THE NETWORK STACK:

╭─────────────────────────╮
│ Application Layer       │ ← HTTP lives here
│ (HTTP, DNS, SMTP...)    │
├─────────────────────────┤
│ Transport Layer         │ ← TCP or UDP
│ (TCP, UDP, QUIC)        │
├─────────────────────────┤
│ Network Layer           │ ← IP (routing)
│ (IP, ICMP)              │
├─────────────────────────┤
│ Link Layer              │ ← Ethernet, WiFi
│ (Ethernet, WiFi)        │
╰─────────────────────────╯

HTTP doesn't care about bits on a wire.
It cares about: "GET me this resource" and
"Here's the response."
```

---

### 🕰️ HTTP/1.0 — The Beginning (1996)

The original. Simple. And painfully inefficient.

```text
HTTP/1.0 — One Request Per Connection

Client                              Server
  │                                    │
  │── TCP Handshake (SYN/SYN-ACK/ACK)─►│  ~1 RTT
  │── GET /index.html ────────────────►│
  │◄── 200 OK <html>... ───────────────│
  │── TCP Close (FIN/ACK) ────────────►│  ~1 RTT
  │                                    │
  │── TCP Handshake ──────────────────►│  ~1 RTT
  │── GET /style.css ─────────────────►│  (AGAIN!)
  │◄── 200 OK body{...} ───────────────│
  │── TCP Close ──────────────────────►│  ~1 RTT
  │                                    │
  │── TCP Handshake ──────────────────►│  ~1 RTT
  │── GET /app.js ────────────────────►│  (AGAIN!!)
  │◄── 200 OK function(){...} ─────────│
  │── TCP Close ──────────────────────►│  ~1 RTT

A modern webpage has 50-100 resources.
Each needs a TCP handshake + teardown.
That's 50-100 handshakes × 1 RTT each.

If RTT = 50ms → 2.5-5 seconds JUST for handshakes
Before a single byte of content is transferred.
```

---

### 🔄 HTTP/1.1 — Keep-Alive & Pipelining (1997)

HTTP/1.1 introduced **persistent connections**:

```text
HTTP/1.1 — Connection Reuse (Keep-Alive)

Client                              Server
  │                                    │
  │── TCP Handshake ──────────────────►│  1 RTT (once)
  │                                    │
  │── GET /index.html ────────────────►│
  │◄── 200 OK <html>... ───────────────│
  │                                    │  Same connection!
  │── GET /style.css ─────────────────►│  No new handshake!
  │◄── 200 OK body{...} ───────────────│
  │                                    │
  │── GET /app.js ────────────────────►│
  │◄── 200 OK function(){...} ─────────│
  │                                    │
  │── TCP Close (when done) ──────────►│

  Saved: N-1 handshakes for N requests
```

But there's a massive problem...

#### ✗ HTTP/1.1's Fatal Flaw: Head-of-Line Blocking (Application Layer)

```text
THE PROBLEM:

HTTP/1.1 requests on a single connection are SEQUENTIAL.
You must wait for the response to Request 1 before
sending Request 2.

Client                              Server
  │── GET /huge-image.jpg ───────────►│
  │                                   │ Server is slowly
  │          (waiting...)             │ reading from disk,
  │          (still waiting...)       │ compressing,
  │          (STILL waiting...)       │ sending 5MB...
  │◄── 200 OK [5MB of data] ──────────│
  │                                   │
  │── GET /tiny-icon.png ────────────►│  THIS waited for
  │◄── 200 OK [2KB] ──────────────────│  the whole 5MB!

Even though the icon is 2KB and could be served
instantly, it's BLOCKED behind the huge image.

This is HEAD-OF-LINE BLOCKING at the HTTP layer.
(Different from TCP HOL blocking, but same concept!)
```

**HTTP/1.1 attempted a fix: Pipelining**

```text
HTTP PIPELINING (mostly abandoned):

Client                              Server
  │── GET /index.html ────────────────►│
  │── GET /style.css ─────────────────►│  Send requests
  │── GET /app.js ────────────────────►│  without waiting!
  │                                    │
  │◄── 200 OK (index.html) ────────────│  But responses
  │◄── 200 OK (style.css) ─────────────│  MUST come back
  │◄── 200 OK (app.js) ────────────────│  IN ORDER!

Why "in order"? Because HTTP/1.1 has NO WAY to
identify which response belongs to which request.
There are no request IDs or stream identifiers.

So if the server is slow generating style.css,
app.js is STILL blocked even though it's ready.

Result: Most browsers NEVER implemented pipelining.
It was too fragile, too many broken proxies, and
it didn't actually solve HOL blocking.
```

#### 🛠️ The Browser's Workaround: Multiple Connections

```text
Since HTTP/1.1 can only do one request-response at a
time per connection, browsers open MULTIPLE connections:

Browser → Server:
  Connection 1: GET /image1.jpg
  Connection 2: GET /image2.jpg
  Connection 3: GET /style.css
  Connection 4: GET /app.js
  Connection 5: GET /font.woff
  Connection 6: GET /image3.jpg

Most browsers open 6-8 connections per origin.

PROBLEMS:
  1. Each connection = separate TCP handshake (latency)
  2. Each connection = separate TLS handshake (more latency)
  3. Each connection has independent congestion control
     → Each starts with slow start
     → None of them reach full throughput quickly
  4. Server must manage 6-8× more connections
  5. Memory overhead on both sides

HACK ON TOP OF HACK:
  Developers used "domain sharding":
  - Serve images from images.example.com
  - Serve CSS from static.example.com
  - Serve JS from cdn.example.com
  - Browser opens 6 connections PER DOMAIN
  - 3 domains × 6 connections = 18 parallel streams

  This worked but was an ugly hack.
```

---

Let's continue. Full HTTP/2 and HTTP/3 deep dive, uninterrupted.

---

# HTTP/2 — The Real Fix (2015)

Based on Google's SPDY protocol. The goal: solve HTTP/1.1's problems **without changing HTTP semantics** (GET, POST, headers, status codes all stay the same).

## The Core Innovation: Binary Framing Layer

HTTP/1.1 is **text-based**. HTTP/2 is **binary**.

```
HTTP/1.1 (text):
  GET /index.html HTTP/1.1\r\n
  Host: example.com\r\n
  Accept: text/html\r\n
  \r\n

  → Human readable
  → Must be parsed character by character
  → Ambiguous (where does one message end?)
  → Cannot be multiplexed

HTTP/2 (binary frames):
  ╭──────────────────────────────────╮
  │ Length (24 bits)                 │
  │ Type (8 bits) — HEADERS, DATA,   │
  │                  SETTINGS, etc.  │
  │ Flags (8 bits)                   │
  │ Stream Identifier (31 bits) ◄────── THIS IS THE KEY
  │ Payload                          │
  ╰──────────────────────────────────╯

  → Machine-parseable (fast)
  → Unambiguous (length-prefixed)
  → Every frame tagged with a STREAM ID
  → Multiple streams can share one connection
```

## Streams, Messages, and Frames

This is the concept that makes everything work:

```
ONE TCP CONNECTION carries MULTIPLE STREAMS:

╔══════════════════════════════════════════════════════════════╗
║   Single TCP Connection                                      ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   Stream 1 (GET /index.html):                                ║
║     [HEADERS frame, stream=1]                                ║
║     [DATA frame, stream=1, chunk 1]                          ║
║     [DATA frame, stream=1, chunk 2]                          ║
║                                                              ║
║   Stream 3 (GET /style.css):                                 ║
║     [HEADERS frame, stream=3]                                ║
║     [DATA frame, stream=3]                                   ║
║                                                              ║
║   Stream 5 (GET /app.js):                                    ║
║     [HEADERS frame, stream=5]                                ║
║     [DATA frame, stream=5]                                   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

On the wire, frames are INTERLEAVED:

Time →
╔══════════════════════════════════════════════════════════════╗
║ H1│D1│H3│D3│H5│D1│D5│D1│D3│D5│D1                             ║
╚══════════════════════════════════════════════════════════════╝
 ▲     ▲     ▲
 │     │     │
 │     │     Stream 5 headers
 │     Stream 3 headers
 Stream 1 headers

H = HEADERS frame, D = DATA frame
Number = stream ID

The receiver reassembles each stream independently.
Stream 3 frames go to the style.css handler.
Stream 5 frames go to the app.js handler.
They don't block each other at the HTTP layer!
```

**This solves HTTP-layer HOL blocking.** If stream 1 (huge image) is slow, streams 3 and 5 can still make progress because frames are interleaved.

## Key HTTP/2 Features

### 1. Multiplexing (just described above)
```
HTTP/1.1: 1 request at a time per connection
           → Need 6-8 connections for parallelism

HTTP/2:   100+ concurrent streams on 1 connection
           → Single TCP connection per origin
           → No domain sharding needed
           → Better congestion control (one cwnd)
           → Fewer sockets, less memory, less CPU
```

### 2. Header Compression (HPACK)

```
HTTP/1.1 problem:
  Every request sends ALL headers. Repeatedly.

  Request 1: GET /page1
    Host: example.com
    User-Agent: Mozilla/5.0 (Windows NT 10.0; ...)
    Accept: text/html,application/xhtml+xml,...
    Accept-Language: en-US,en;q=0.9
    Cookie: session=abc123def456...

  Request 2: GET /page2
    Host: example.com                    ← SAME
    User-Agent: Mozilla/5.0 (Win...     ← SAME
    Accept: text/html,application...     ← SAME
    Accept-Language: en-US,en;q=0.9     ← SAME
    Cookie: session=abc123def456...     ← SAME (huge!)

  Headers can be 500 bytes to 2KB+ per request.
  50 requests = 25-100KB of REDUNDANT headers.

HTTP/2 HPACK compression:
  ╔══════════════════════════════════════════════════════════════╗
  ║   STATIC TABLE (61 pre-defined entries)                      ║
  ║   Index 2: GET                                               ║
  ║   Index 4: /                                                 ║
  ║   Index 8: 200 status                                        ║
  ║   ... common headers pre-indexed                             ║
  ║                                                              ║
  ║   DYNAMIC TABLE (connection-specific)                        ║
  ║   Builds up as headers are sent                              ║
  ║   Index 62: Host: example.com                                ║
  ║   Index 63: Cookie: session=abc123...                        ║
  ║   Index 64: User-Agent: Mozilla/5.0...                       ║
  ╚══════════════════════════════════════════════════════════════╝

  Request 1: Send full headers → populate dynamic table
  Request 2: Send only INDEX NUMBERS for unchanged headers
             + literal values for changed ones

  "Send header #62, #63, #64, and path=/page2"

  Compression ratio: 85-95% reduction in header size.
```

### 3. Stream Prioritization

```
Not all resources are equal:

  CSS → Blocks page rendering (HIGH priority)
  JS  → Blocks interactivity (HIGH priority)
  Hero image → Important for UX (MEDIUM priority)
  Analytics script → Not urgent (LOW priority)

HTTP/2 allows clients to assign:
  - Weight (1-256) to each stream
  - Dependencies between streams

  Stream 1 (CSS):     weight=256
  Stream 3 (JS):      weight=256, depends on Stream 1
  Stream 5 (image):   weight=128
  Stream 7 (analytics): weight=16

  Server uses this to allocate bandwidth:
  CSS gets sent first → then JS → then image → then analytics

  In practice: Most servers implement this poorly,
  and Chrome eventually simplified their priority scheme.
  But the capability exists.
```

### 4. Server Push

```
Without server push:
  Client: GET /index.html
  Server: 200 OK <html><link href="style.css">...
  Client: (parses HTML, discovers it needs style.css)
  Client: GET /style.css          ← 1 extra RTT!
  Server: 200 OK body{...}

With server push:
  Client: GET /index.html
  Server: PUSH_PROMISE (I'm going to send you style.css)
  Server: 200 OK <html>...        (response to index.html)
  Server: 200 OK body{...}        (pushed style.css)

  Client already has style.css BEFORE it even
  finishes parsing index.html!
  Saved: 1 full RTT.

In practice: Server push was controversial.
  - Hard to know what client already has cached
  - Can waste bandwidth pushing things client doesn't need
  - Chrome removed support in 2022
  - 103 Early Hints is the modern replacement
```

## HTTP/2's Remaining Problem: TCP-Level HOL Blocking

**This is critical.** HTTP/2 solved HOL blocking at the HTTP layer. But remember — HTTP/2 runs on **TCP**. And TCP still has its own HOL blocking:

```
HTTP/2 multiplexes streams on ONE TCP connection.

Stream 1: [frame A] [frame B] [frame C]
Stream 3: [frame D] [frame E] [frame F]
Stream 5: [frame G] [frame H] [frame I]

On the wire (interleaved):
A, D, G, B, E, H, C, F, I

TCP sees this as ONE byte stream:
[A][D][G][B][E][H][C][F][I]
         ▲
         ╰── This TCP segment is LOST!

TCP behavior:
  - Segments after [B] are buffered but NOT delivered
  - TCP retransmits [B]
  - Until [B] arrives, [E], [H], [C], [F], [I] are ALL stuck

Impact on HTTP/2:
  - Stream 1 needs [B] — so blocking stream 1 is fair
  - But streams 3 and 5 DON'T need [B]!
  - Stream 3's frames [E] and [F] are stuck waiting for
    a packet that belongs to stream 1
  - Stream 5's frames [H] and [I] are also stuck!

ALL streams are blocked because ONE stream lost ONE packet.

This is WORSE than HTTP/1.1 in some cases!

HTTP/1.1 with 6 connections:
  - If connection 1 has packet loss, only that
    connection's request is blocked
  - The other 5 connections are fine

HTTP/2 with 1 connection:
  - If that connection has packet loss, ALL requests
    on ALL streams are blocked

On high-loss networks (mobile, WiFi): HTTP/2 can
actually be SLOWER than HTTP/1.1!
```

This is the fundamental problem that HTTP/3 was created to solve.

---

# HTTP/3 — The Paradigm Shift (2022)

## The Radical Decision: Abandon TCP

```
The problem is unfixable within TCP.

TCP guarantees ordered delivery of a SINGLE byte stream.
You cannot have multiple independent streams within TCP.
The kernel enforces this — applications can't opt out.

Google's insight:
  "What if we build a NEW transport protocol that
   understands multiple streams natively?"

But changing transport protocols is nearly impossible:
  - Middleboxes (firewalls, NATs) inspect TCP/UDP headers
  - They DROP packets with unknown protocol numbers
  - Deploying a new protocol takes decades

Google's hack:
  "Build the new protocol ON TOP OF UDP."

  Every middlebox on earth already allows UDP through.
  We'll put our new protocol in UDP's payload.
  Middleboxes see UDP and let it pass.

  This protocol is QUIC.
```

## QUIC: The New Transport Layer

```
Traditional stack:          HTTP/3 stack:

╭──────────╮               ╭──────────╮
│  HTTP/2  │               │  HTTP/3  │
├──────────┤               ├──────────┤
│  TLS 1.2 │               │   QUIC   │ ← Combines transport
├──────────┤               │  (TLS    │    + encryption
│   TCP    │               │   1.3    │    + multiplexing
├──────────┤               │ built-in)│
│    IP    │               ├──────────┤
╰──────────╯               │   UDP    │
                           ├──────────┤
                           │    IP    │
                           ╰──────────╯

QUIC runs in USERSPACE (not in the kernel like TCP).
This means:
  - Can be updated without OS updates
  - Deployed via application/library updates
  - Google can ship QUIC changes in Chrome updates
  - No waiting for Linux kernel patches
```

## How QUIC Solves HOL Blocking

```
QUIC has NATIVE stream multiplexing:

╔══════════════════════════════════════════════════════════════╗
║   QUIC Connection                                            ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   Stream 1: [A]───[B]───[C]    (independent)                 ║
║   Stream 3: [D]───[E]───[F]    (independent)                 ║
║   Stream 5: [G]───[H]───[I]    (independent)                 ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

If packet containing [B] is lost:

  Stream 1: [A]───[?]───[C]  → Stream 1 is blocked
                                (waiting for [B])
  Stream 3: [D]───[E]───[F]  → DELIVERED NORMALLY! ✓
  Stream 5: [G]───[H]───[I]  → DELIVERED NORMALLY! ✓

QUIC knows which stream each packet belongs to.
Loss on stream 1 does NOT block streams 3 and 5.

This is the FUNDAMENTAL difference from TCP.
TCP sees one stream. QUIC sees many.
```

## QUIC Connection Establishment: 0-RTT

```
TCP + TLS 1.2:  3 round trips before data
  1 RTT: TCP handshake (SYN/SYN-ACK/ACK)
  2 RTT: TLS handshake (ClientHello/ServerHello/...)
  Then: Send HTTP request
  Total: 3 RTT before first byte of response

TCP + TLS 1.3:  2 round trips
  1 RTT: TCP handshake
  1 RTT: TLS 1.3 handshake (faster than 1.2)
  Total: 2 RTT

QUIC first connection:  1 RTT
  QUIC merges transport + TLS handshake into ONE step
  1 RTT: QUIC handshake (includes TLS 1.3)
  Total: 1 RTT

QUIC subsequent connection:  0 RTT!!!
  Client caches server's cryptographic parameters
  Sends data WITH the very first packet
  Server validates cached credentials, processes immediately
  Total: 0 RTT — data sent INSTANTLY

  ╔══════════════════════════════════════════════════════════════╗
  ║   Connection setup comparison:                               ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   TCP + TLS 1.2:    ████████████  3 RTT                      ║
  ║   TCP + TLS 1.3:    ████████      2 RTT                      ║
  ║   QUIC (first):     ████          1 RTT                      ║
  ║   QUIC (repeat):    ▏             0 RTT                      ║
  ║                                                              ║
  ║   On mobile (100ms RTT):                                     ║
  ║   TCP+TLS 1.2 = 300ms just to connect                        ║
  ║   QUIC 0-RTT  = 0ms overhead                                 ║
  ╚══════════════════════════════════════════════════════════════╝

0-RTT security caveat:
  0-RTT data is replayable! An attacker could capture
  and resend it. So 0-RTT should ONLY be used for
  idempotent requests (GET, not POST).
  Same concern as TCP Fast Open.
```

## QUIC Connection Migration

```
TCP connections are identified by:
  (source IP, source port, destination IP, destination port)

If ANY of these change, the connection is DEAD.

Scenario: User on phone
  - Connected to WiFi at coffee shop
  - Walks outside, phone switches to cellular
  - IP address changes
  - ALL TCP connections die
  - ALL HTTP/2 streams die
  - Browser must: TCP handshake + TLS handshake +
    re-request everything
  - User sees: page stalls for 2-3 seconds

QUIC connections are identified by:
  A CONNECTION ID (random 64-bit+ identifier)

  Not tied to IP address or port!

Scenario with QUIC:
  - Connected to WiFi
  - Walks outside, phone switches to cellular
  - IP changes, but connection ID is the same
  - QUIC connection MIGRATES seamlessly
  - User sees: nothing. Maybe 1 packet of delay.

This is huge for mobile users, which is now the
majority of internet traffic.
```

## QUIC Built-In Encryption

```
TCP: Encryption is optional (TLS is a separate layer)
     → TCP headers are in plaintext
     → Middleboxes can inspect and modify TCP
     → This has caused protocol ossification
        (can't change TCP because middleboxes
         depend on specific header formats)

QUIC: Encryption is MANDATORY
     → Almost everything is encrypted (even packet numbers)
     → Middleboxes can only see: UDP ports +
       QUIC connection ID
     → Cannot inspect or modify QUIC internals
     → Prevents ossification — QUIC can evolve freely
```

---

## Complete Comparison: HTTP/1.1 vs HTTP/2 vs HTTP/3

```
Feature              │ HTTP/1.1        │ HTTP/2          │ HTTP/3
─────────────────────┼─────────────────┼─────────────────┼────────────────
Transport            │ TCP             │ TCP             │ QUIC (over UDP)
Encoding             │ Text            │ Binary          │ Binary
Multiplexing         │ No              │ Yes (streams)   │ Yes (streams)
Connections needed   │ 6-8 per origin  │ 1 per origin    │ 1 per origin
Header compression   │ None            │ HPACK           │ QPACK
Server push          │ No              │ Yes (removed)   │ Yes (unused)
HOL blocking (HTTP)  │ Yes             │ No              │ No
HOL blocking (TCP)   │ Per-connection  │ Yes (ALL streams)│ No (per-stream)
Connection setup     │ 2-3 RTT         │ 2-3 RTT         │ 1 RTT (0 repeat)
Connection migration │ No              │ No              │ Yes
Encryption           │ Optional (HTTPS)│ Effectively req │ Mandatory
Implemented in       │ Kernel (TCP)    │ Kernel (TCP)    │ Userspace (QUIC)

When to use HTTP/1.1:
  - Legacy systems
  - Simple APIs where you control both ends
  - Debugging (human-readable)

When to use HTTP/2:
  - Most web traffic today
  - APIs with many concurrent requests
  - Low-loss networks (datacenter, fiber)

When to use HTTP/3:
  - Mobile-heavy traffic
  - High-loss networks (WiFi, cellular)
  - Latency-sensitive applications
  - Users who move between networks
```

---

## Real-World Adoption

```
Who uses what:

Google:    HTTP/3 for all Google services
           (Search, YouTube, Gmail, Maps)
           They invented QUIC.

Cloudflare: HTTP/3 enabled by default on their CDN
            Handles ~20% of web traffic

Meta:      HTTP/3 for Facebook, Instagram
           Reported 6% latency reduction on
           video streaming, 20% on worst connections

Netflix:   Still primarily HTTP/2
           (their traffic is long-lived video streams,
           HOL blocking is less impactful when you're
           streaming one large file)

Apple:     HTTP/3 support in Safari and iOS

Amazon:    HTTP/2 for most AWS services
           CloudFront CDN supports HTTP/3
```

---

## QPACK vs HPACK (Why HTTP/3 Needed New Header Compression)

```
HPACK (HTTP/2) relies on ORDERED delivery of headers.
  - Dynamic table must be synchronized between
    client and server
  - If header frame N is lost, frame N+1 can't be
    decoded (depends on N's table updates)
  - This creates... HOL blocking for headers!

QPACK (HTTP/3) solves this:
  - Uses two unidirectional QUIC streams for table updates
  - Header blocks can reference the table at a known
    safe point
  - Allows out-of-order header delivery
  - Slightly less compression than HPACK, but no blocking
```

---

## Key SRE Considerations

```
HTTP/2 operational concerns:
  1. Single connection = single point of failure
     → If the one TCP connection drops, ALL streams fail
     → Monitor connection health carefully

  2. Thundering herd on reconnect
     → 100 streams were multiplexed
     → Connection drops
     → All 100 retry simultaneously
     → Server spike

  3. Window size tuning
     → TCP receive window must be large enough for
       all multiplexed streams
     → Default OS settings may be too small
     → sysctl net.ipv4.tcp_rmem / tcp_wmem

  4. Load balancer configuration
     → L7 load balancer must understand HTTP/2
     → Some LBs accept HTTP/2 from client but speak
       HTTP/1.1 to backends
     → This loses multiplexing benefits internally

HTTP/3 operational concerns:
  1. UDP is often rate-limited or blocked
     → Corporate firewalls may block UDP 443
     → Must fall back to HTTP/2 over TCP
     → Browsers use "Happy Eyeballs v2": try QUIC
       and TCP simultaneously, use whichever connects first

  2. Debugging is harder
     → Encrypted, binary, over UDP
     → tcpdump/Wireshark need QUIC dissectors
     → Can't read packets in plaintext anymore

  3. CPU cost
     → QUIC runs in userspace (not kernel)
     → Kernel TCP is highly optimized (decades of work)
     → QUIC can use more CPU than TCP for same throughput
     → Google reported ~2x CPU for QUIC vs TCP initially
     → Improving with optimizations (sendmmsg, GSO)

  4. No kernel optimization
     → TCP has hardware offloading (TSO, GRO, checksum offload)
     → QUIC mostly doesn't benefit from these
     → Work in progress (QUIC-aware NICs)
```

---

---

## Production Failure Patterns

```
PATTERN 1: HTTP/2 MULTIPLEXING KILLED AT DOWNGRADE
  Symptom: p99 spikes after adding microservices; requests/page explodes
  Cause:   HTTP/2 front → HTTP/1.1 backend hop serializes streams
  Fix:     End-to-end HTTP/2, BFF aggregation, or gRPC between services

PATTERN 2: TCP HOL BLOCKING UNDER LOSS (HTTP/2)
  Symptom: single slow/lost packet stalls all multiplexed streams
  Cause:   HTTP/2 runs over single TCP connection per origin
  Fix:     HTTP/3/QUIC, multiple connections (limited), or reduce per-connection load

PATTERN 3: 0-RTT REPLAY ATTACK SURFACE
  Symptom: duplicate mutations after reconnect (rare but catastrophic)
  Cause:   TLS 1.3 early data accepted on non-idempotent endpoints
  Fix:     Disable 0-RTT for mutating routes; anti-replay tokens at app layer

PATTERN 4: QUIC BLOCKED BY CORPORATE FIREWALL
  Symptom: EU enterprise users on HTTP/3 timeout; TCP fallback slow
  Cause:   UDP/443 blocked; Alt-Svc advertises QUIC that never connects
  Fix:     Adaptive protocol selection, shorter QUIC timeout, TCP fallback hints

PATTERN 5: ALT-SVC STICKY BAD STATE
  Symptom: subset of users stuck on broken HTTP/3 path for hours
  Cause:   Alt-Svc max-age too long after QUIC regression
  Fix:     Reduce max-age during incidents; purge via Cache-Control on HTML
```

---

### Staff

## SRE Diagnostic Toolkit

```
METRICS:
  http_requests_total{protocol="h2|h3|http/1.1"}  — protocol mix shift
  http_request_duration_seconds (by handler)       — p50/p99 per route
  ALB TargetResponseTime + HTTPCode_Target_5XX
  CloudFront OriginLatency vs TimeToFirstByte

COMMANDS:
  curl -sI --http2 https://origin/health | grep -i "HTTP/2\|HTTP/3"
  curl -w "dns:%{time_namelookup} connect:%{time_connect} tls:%{time_appconnect}\n" -o /dev/null -s URL
  h2load -n10000 -c100 -m100 URL                    — HTTP/2 load test
  openssl s_client -connect host:443 -alpn h2,http/1.1

LOG PATTERNS:
  "PRI * HTTP/2.0" parse errors                     — bad client or downgrade bug
  Spike in 499 (client closed)                      — timeout before response
  HTTP/1.1 200 with high body latency on fan-out    — missing aggregation

BROWSER / RUM:
  Compare TTFB by protocol version and geography
  Navigation Timing: connectEnd - connectStart (TCP/TLS cost)
```

---

## Decision Framework

```
WHICH HTTP VERSION?

  Browser → CDN → static/API                     → HTTP/2 minimum; HTTP/3 if CDN supports
  Mobile global users, lossy networks              → HTTP/3 (QUIC) with TCP fallback
  Legacy corporate proxy environment             → HTTP/1.1 or HTTP/2 only; test QUIC
  Service-to-service inside VPC                  → HTTP/2 or gRPC over h2; not HTTP/3 required

MICROSERVICE EXPOSURE:
  Never expose N microservice calls to browser     → BFF/GraphQL/edge aggregate
  HTTP/2 end-to-end through ALB                  → enable ALPN on targets

0-RTT POLICY:
  Idempotent GET/HEAD only                         → 0-RTT allowed
  POST/PUT/PATCH/DELETE                            → disable early data
```
---

## Hands-On Exercises

### Exercise 1: Protocol Negotiation Check

```bash
# Verify HTTP/2 from client to ALB
curl -sI --http2 https://api.example.com/health | head -1
# HTTP/2 200

# Verify backend protocol (from inside VPC)
curl -sI --http2 http://backend.internal:8080/health
# If HTTP/1.1 200 → downgrade hop exists
```

### Exercise 2: Request Count per Page (RUM / ALB)

```bash
# ALB access log Athena — requests per minute per client IP during page load
# Spike from ~5 to ~200 after deploy confirms amplification

# Chrome DevTools → Network → filter Fetch/XHR
# Count API calls loading one listing page
```

### Exercise 3: h2load Multiplexing vs Serial

```bash
# HTTP/2: 100 requests, 1 connection, 100 concurrent streams
h2load -n100 -c1 -m100 https://api.example.com/v1/product/1

# Compare to HTTP/1.1: 100 requests, 6 connections
h2load -n100 -c6 -m1 --alpn-list=http/1.1 https://api.example.com/v1/product/1
# HTTP/2 completes faster when server supports it end-to-end
```

### Exercise 4: QUIC / HTTP/3 Availability Test

```bash
# Check Alt-Svc header
curl -sI https://cdn.example.com/ | grep -i alt-svc

# Test QUIC (curl 7.66+ with ngtcp2/openssl)
curl --http3-only -w "time_connect:%{time_connect}\n" -o /dev/null -s URL
# If timeout → corporate UDP block; verify TCP fallback latency
```

### Exercise 5: 0-RTT Safety Audit

```bash
# grep codebase for early data on mutating routes
# TLS 1.3 0-RTT must be disabled for POST/PUT/PATCH/DELETE
# nginx: ssl_early_data off; on payment/checkout locations
```

### Exercise 6: BFF Aggregation Smoke Test

```python
# Pseudocode: single bundle endpoint replaces 4 client calls
async def get_product_bundle(product_id: str):
    details, price, reviews, images = await asyncio.gather(
        fetch_details(product_id),
        fetch_price(product_id),
        fetch_reviews(product_id),
        fetch_images(product_id),
    )
    return {"details": details, "price": price, "reviews": reviews, "images": images}
# Browser: 1 request. Server: 4 parallel internal calls over HTTP/2 or gRPC.
```

---

## Key Takeaways

```
╔══════════════════════════════════════════════════════════════╗
║   1. HTTP/2 multiplexing dies at protocol downgrade points.  ║
║   2. HTTP/2 fixed HTTP-layer HOL; TCP-layer HOL remains.     ║
║   3. 0-RTT is for idempotent reads only.                     ║
║   4. HTTP/3 + corporate firewalls can destroy p99.           ║
║   5. Microservice splits multiply requests — aggregate.      ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading

- RFC 9113 (HTTP/2), RFC 9114 (HTTP/3), RFC 9000 (QUIC)
- High Performance Browser Networking — Ch 12–15

---

### Principal stretch

## Ops Sim: Northstar Product Catalog Request Fan-Out

**Drill note:** Answer from the production report below. Cite protocol, request-count, and RUM evidence for every claim.


```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P2
Service: E-commerce product catalog API
Time: 2:15 PM (peak shopping hours)

ARCHITECTURE:
  Users → CloudFront CDN → ALB (Application Load
  Balancer) → 12 backend API servers

  CloudFront → ALB: HTTP/2
  ALB → Backend: HTTP/1.1 (ALB terminates HTTP/2)

SYMPTOMS:
  - Users report pages loading slowly
  - Product listing pages (which load 40-60 product
    images + metadata in parallel) are especially slow
  - Monitoring shows:
    → Backend server response time: 15ms avg (NORMAL)
    → ALB latency: 18ms avg (NORMAL)
    → User-perceived page load time: 4.2 seconds
      (normally 1.1 seconds)
    → CloudFront cache hit rate: 94% (NORMAL)
    → No errors — just slowness
    → Backend CPU: 30%, Memory: 45% (NORMAL)
  - The issue started 2 hours ago
  - A deployment went out 2 hours ago that "only
    changed the product API response format"
  - Mobile users are MORE affected than desktop users

DEPLOYMENT CHANGE (from git diff):
  Before: Single API endpoint returns product data
          + image URLs in one response
  After:  Product data split into separate endpoints:
          /api/product/{id}/details
          /api/product/{id}/price
          /api/product/{id}/reviews
          /api/product/{id}/images
          (for "microservice readiness")
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** What is the root cause? Walk through your reasoning using specific data points from the incident report.

**Question 2:** Why are mobile users more affected than desktop users?

**Question 3:** What is the immediate mitigation?

**Question 4:** If the team insists on keeping the split endpoints for "microservice readiness," what architectural changes would you propose to eliminate this latency problem permanently?

> **Answer key (open only after you have answered):**
> [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/HTTP-1.1-vs-HTTP-2-vs-HTTP-3 Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/HTTP-1.1-vs-HTTP-2-vs-HTTP-3 Answers.md)


--- 



---
