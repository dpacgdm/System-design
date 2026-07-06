# Topic 1: TCP vs UDP — The Foundation of All Network Communication

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Explain what TCP guarantees (ordered, reliable byte     ║
║      stream) and what UDP does NOT — at the mechanism level  ║
║                                                              ║
║   2. Walk the 3-way handshake and connection teardown,       ║
║      including why TIME_WAIT exists and how long it lasts    ║
║                                                              ║
║   3. Explain congestion control, slow start, and how TCP     ║
║      HOL blocking causes page-wide stalls                    ║
║                                                              ║
║   4. Choose TCP vs UDP for a workload and know what you      ║
║      must build on top of UDP if you pick it                 ║
║                                                              ║
║   5. Diagnose port exhaustion, TIME_WAIT buildup, and        ║
║      connection-pool incidents with exact commands           ║
║                                                              ║
║   6. Apply AWS timeout limits (NLB 350s idle, ALB 60s)       ║
║      to real connection designs                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "TCP is reliable, so my data is safe"       ║
╟────────────────────────────────────────────────────────────────╢
║   WRONG. TCP guarantees delivery to the OTHER KERNEL, not      ║
║   to your application logic or disk. A crash after ACK but     ║
║   before your app processes/persists the data still loses      ║
║   it. Reliability is hop-level, not end-to-end business        ║
║   durability — you still need acks/idempotency at the app.     ║
╠════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "UDP is just faster TCP"                    ║
╟────────────────────────────────────────────────────────────────╢
║   WRONG. UDP has NO ordering, NO retransmission, NO            ║
║   congestion control, NO connection. It is faster because      ║
║   it does nothing. If you need any of those, you rebuild       ║
║   them yourself (QUIC did exactly this over UDP).              ║
╠════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "A closed connection frees resources now"   ║
╟────────────────────────────────────────────────────────────────╢
║   WRONG. The side that closes actively enters TIME_WAIT for    ║
║   2×MSL (~60s) holding the 4-tuple. Under high churn this      ║
║   exhausts ephemeral ports — the classic connection-storm      ║
║   outage. Reuse connections (pools, keep-alive) instead.       ║
╠════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "More connections = more throughput"        ║
╟────────────────────────────────────────────────────────────────╢
║   WRONG. Each new TCP connection restarts slow start and       ║
║   costs a handshake RTT + kernel memory. Many short            ║
║   connections can be SLOWER and more expensive than a few      ║
║   long-lived pooled ones.                                      ║
╠════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Packet loss means the network is broken"   ║
╟────────────────────────────────────────────────────────────────╢
║   WRONG. TCP USES loss as its congestion signal. Some loss     ║
║   is normal and expected; TCP backs off and recovers. The      ║
║   problem is when loss is high enough that HOL blocking and    ║
║   retransmits dominate latency.                                ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Let's Start With WHY This Matters

Every single system you will ever design — Netflix, WhatsApp, Uber, Google — transmits data over a network. And at the very bottom of that stack, every single byte goes through either **TCP** or **UDP**. If you don't understand these deeply, you're building on sand.

---

## The Problem Both Protocols Solve

Two machines want to talk to each other across a network. That's it. But the network between them is **unreliable**:

```
Machine A ──────── The Internet ──────── Machine B
                       │
                       │  Packets can be:
                       │  • LOST (router drops them)
                       │  • REORDERED (take different paths)
                       │  • DUPLICATED (retransmission artifacts)
                       │  • CORRUPTED (bit flips)
                       │  • DELAYED (congestion)
```

TCP and UDP take **fundamentally different philosophical approaches** to this problem.

---

## TCP: Transmission Control Protocol

### The Philosophy
> "I will guarantee that every byte you send arrives correctly, in order, exactly once — no matter what. I'll handle the complexity so you don't have to."

TCP is a **connection-oriented, reliable, ordered, byte-stream protocol**.

Let's break down what each of those words means precisely.

### Connection-Oriented: The Three-Way Handshake

Before any data is sent, TCP establishes a connection. This is the **three-way handshake**:

```
    Client                          Server
      │                               │
      │──── SYN (seq=100) ───────────►│  Step 1: "I want to talk. 
      │                               │           My starting sequence 
      │                               │           number is 100."
      │                               │
      │◄─── SYN-ACK (seq=300,  ───────│  Step 2: "OK, I heard you.
      │      ack=101)                 │           My starting sequence
      │                               │           number is 300.
      │                               │           I expect your next
      │                               │           byte to be 101."
      │                               │
      │──── ACK (ack=301) ───────────►│  Step 3: "Got it. I expect
      │                               │           your next byte 
      │                               │           to be 301."
      │                               │
      │   CONNECTION ESTABLISHED      │
      │   Data can now flow           │
```

**Why three steps? Why not two?**

This is critical. Two steps wouldn't work because:

```
Scenario: Two-way handshake failure

1. Client sends SYN (seq=100)
2. Server sends SYN-ACK (seq=300, ack=101)
   → Server thinks connection is established
   → But what if this SYN-ACK gets LOST?
   → Client doesn't know the server's sequence number
   → Client doesn't know if server even received the SYN

With three-way:
3. Client sends ACK (ack=301)
   → Now BOTH sides have confirmed they can 
     send AND receive
   → Both sides know each other's sequence numbers
```

There's also the problem of **old duplicate SYNs**:
```
Without 3-way handshake:
1. Client sends SYN (seq=100) — this gets DELAYED in network
2. Client gives up, goes away
3. 30 seconds later, the delayed SYN arrives at server
4. Server sends SYN-ACK and thinks connection is open
5. Server is now wasting resources on a ghost connection

With 3-way handshake:
→ Server sends SYN-ACK, waits for ACK
→ ACK never comes (client is gone)
→ Server times out, cleans up
→ No ghost connection
```

### Sequence Numbers and Acknowledgments

Every byte in TCP has a **sequence number**. This is how TCP guarantees ordering and detects loss.

```
Client sends 3 segments:

Segment 1: [seq=100, data="Hello"] (5 bytes)
Segment 2: [seq=105, data=" World"] (6 bytes)  
Segment 3: [seq=111, data="!!!!"] (4 bytes)

Server receives them and ACKs:

ACK [ack=105]  → "I got everything up to byte 104.
                   Send me byte 105 next."
ACK [ack=111]  → "I got everything up to byte 110.
                   Send me byte 111 next."
ACK [ack=115]  → "I got everything up to byte 114."

The ACK number means: "I've received all bytes BEFORE 
this number. Send me this byte next."
```

**What happens when a packet is lost?**

```
Client sends:
  Segment 1: [seq=100] ──────►  ✓ Received
  Segment 2: [seq=105] ────X    ✗ LOST!
  Segment 3: [seq=111] ──────►  ✓ Received

Server sends:
  ACK [ack=105]  → "Got segment 1, want 105 next"
  ACK [ack=105]  → "Got segment 3, but I'm STILL 
                     missing 105! (duplicate ACK)"
  ACK [ack=105]  → "Still waiting for 105! (triple dup ACK)"

After 3 duplicate ACKs, client knows segment 2 was lost.
→ Client retransmits segment 2 (FAST RETRANSMIT)
→ No need to wait for timeout!
```

This is called **Fast Retransmit** — triggered by 3 duplicate ACKs. Without it, the client would have to wait for a timeout timer (which is much slower).

### TCP Flow Control: Sliding Window

The receiver might be slower than the sender. TCP handles this with a **sliding window**:

```
Receiver advertises: "My receive window is 4 segments"

Sender's view:
╔══════════════════════════════════════════════════════════════╗
║  1 │ 2 │ 3 │ 4 │ 5 │ 6 │ 7 │ 8 │ 9 │ 10                      ║
╚══════════════════════════════════════════════════════════════╝
 ▲ACK'd▲         ▲              ▲
 (done)  Sent,    Can send      Cannot send yet
         waiting  (in window)   (outside window)
         for ACK

As ACKs come back, the window SLIDES forward:

After ACK for 2:
╔══════════════════════════════════════════════════════════════╗
║  1 │ 2 │ 3 │ 4 │ 5 │ 6 │ 7 │ 8 │ 9 │ 10                      ║
╚══════════════════════════════════════════════════════════════╝
     ▲ACK'd▲              ▲
              Window slides right →
```

The **receive window size** is communicated in every TCP header. If the receiver is overwhelmed, it can shrink the window — even to 0, telling the sender to STOP.

**Zero window situation:**
```
Receiver: "Window = 0" → STOP SENDING!
Sender: Stops. Starts a "persist timer."
         Periodically sends 1-byte "probe" segments.
Receiver: When ready, responds with non-zero window.
Sender: Resumes.
```

### TCP Congestion Control: The Network Perspective

Flow control protects the **receiver**. But what about the **network itself**? If everyone blasts data at full speed, routers overflow and drop packets. This is **congestion collapse**.

TCP uses congestion control algorithms. The modern default is **CUBIC** (Linux) or **BBR** (Google). But let's understand the classic approach first:

```
CONGESTION CONTROL PHASES:

1. SLOW START (exponential growth)
   ╔══════════════════════════════════════════════════════════════╗
   ║   cwnd                                                       ║
   ║   (congestion   16│        ●                                 ║
   ║    window)       8│      ●                                   ║
   ║                  4│    ●                                     ║
   ║                  2│  ●                                       ║
   ║                  1│●                                         ║
   ║                   ╰──────────────                            ║
   ║                    RTTs                                      ║
   ║                                                              ║
   ║   Start with cwnd = 1 segment                                ║
   ║   Each ACK: cwnd += 1                                        ║
   ║   Effect: cwnd doubles each RTT                              ║
   ║   (1 → 2 → 4 → 8 → 16 → ...)                                 ║
   ╚══════════════════════════════════════════════════════════════╝

2. CONGESTION AVOIDANCE (linear growth)
   After cwnd reaches "slow start threshold" (ssthresh):
   ╔══════════════════════════════════════════════════════════════╗
   ║   cwnd                                                       ║
   ║               20│          ●                                 ║
   ║               19│        ●                                   ║
   ║               18│      ●                                     ║
   ║               17│    ●                                       ║
   ║   ssthresh→  16│  ●                                          ║
   ║                ╰──────────────                               ║
   ║                                                              ║
   ║   Each RTT: cwnd += 1 segment                                ║
   ║   Linear growth (much slower)                                ║
   ╚══════════════════════════════════════════════════════════════╝

3. ON PACKET LOSS:
   
   If timeout:
     → ssthresh = cwnd / 2
     → cwnd = 1
     → Back to slow start (HARSH!)
   
   If 3 duplicate ACKs (fast retransmit):
     → ssthresh = cwnd / 2
     → cwnd = cwnd / 2
     → Enter "fast recovery" (less harsh)
```

**The sawtooth pattern:**
```
cwnd
  │    /\      /\      /\
  │   /  \    /  \    /  \
  │  /    \  /    \  /    \
  │ /      \/      \/      \
  │/
  ╰─────────────────────────── time
    
  Ramp up → Loss detected → Cut in half → Ramp up again
```

**Google BBR (Bottleneck Bandwidth and RTT):**
BBR is different. Instead of treating packet loss as the congestion signal, BBR:
- Probes for the maximum bandwidth
- Probes for the minimum RTT
- Tries to send at exactly the rate the bottleneck link can handle
- Much better performance on lossy networks (like mobile/wireless)

### TCP Connection Termination: Four-Way Handshake

```
    Client                          Server
      │                               │
      │──── FIN ─────────────────────►│  "I'm done sending"
      │                               │
      │◄─── ACK ──────────────────────│  "Got it"
      │                               │
      │     (Server may still send    │
      │      remaining data)          │
      │                               │
      │◄─── FIN ──────────────────────│  "I'm done too"
      │                               │
      │──── ACK ─────────────────────►│  "Got it"
      │                               │
      │   TIME_WAIT (2*MSL)           │
      │   Client waits before         │
      │   fully closing               │
```

**Why TIME_WAIT?** (This comes up in SRE troubleshooting ALL the time)

```
TIME_WAIT lasts for 2 × MSL (Maximum Segment Lifetime)
Usually 60 seconds on Linux.

Two reasons:
1. If the final ACK is lost, the server will re-send FIN.
   Client needs to be around to re-ACK it.

2. Prevents old packets from a previous connection on the 
   same port from being misinterpreted as new data.

SRE IMPACT:
  - High-traffic servers can accumulate THOUSANDS of 
    TIME_WAIT sockets
  - Each takes memory and a port number
  - Can exhaust ephemeral ports (default range: 32768-60999)
  - Fix: net.ipv4.tcp_tw_reuse = 1
         net.ipv4.tcp_tw_recycle = 1 (DANGEROUS with NAT!)
```

### TCP Header Structure (For Completeness)

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
├─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┤
│          Source Port            │       Destination Port         │
├─────────────────────────────────┼────────────────────────────────┤
│                        Sequence Number                           │
├──────────────────────────────────────────────────────────────────┤
│                     Acknowledgment Number                        │
├──────┼────────┼─┼─┼─┼─┼─┼─┼──────────────────────────────────────┤
│Offset│Reserved│U│A│P│R│S│F│           Window Size                │
│      │        │R│C│S│S│Y│I│                                      │
│      │        │G│K│H│T│N│N│                                      │
├──────┴────────┴─┴─┴─┴─┴─┴─┼──────────────────────────────────────┤
│          Checksum           │         Urgent Pointer             │
├─────────────────────────────┴────────────────────────────────────┤
│                    Options (variable)                            │
├──────────────────────────────────────────────────────────────────┤
│                    Data (payload)                                │
╰──────────────────────────────────────────────────────────────────╯

Key flags:
  SYN - Synchronize (connection setup)
  ACK - Acknowledgment
  FIN - Finish (connection teardown)
  RST - Reset (abort connection immediately)
  PSH - Push (deliver to application immediately)
  URG - Urgent data
```

### TCP Head-of-Line Blocking

This is a **critical concept** that comes back in HTTP/2 and HTTP/3:

```
TCP guarantees in-order delivery. This means:

Application sends:    Segment 1, Segment 2, Segment 3

Network delivers:     Segment 1 ✓
                      Segment 2 ✗ (lost)
                      Segment 3 ✓ (arrived, but...)

TCP's receive buffer:
╔══════════════════════════════════════════════════════════════╗
║  Seg 1   │  (gap!)  │  Seg 3                                 ║
║  ready   │  waiting │  buffered                              ║
╚══════════════════════════════════════════════════════════════╝

TCP CANNOT deliver Segment 3 to the application until 
Segment 2 arrives. Segment 3 is stuck in the buffer!

This is HEAD-OF-LINE BLOCKING.

Even though Segment 3 has arrived, the application 
can't see it. Everything behind the lost packet is blocked.
```

This will become very important when we discuss HTTP/2 and HTTP/3.

---

## UDP: User Datagram Protocol

### The Philosophy
> "Here's your data. I made zero promises. Good luck."

UDP is **connectionless, unreliable, unordered, message-oriented**.

### UDP Header (Look How Simple)

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
├─────────────────────────────────┼────────────────────────────────┤
│          Source Port            │       Destination Port         │
├─────────────────────────────────┼────────────────────────────────┤
│            Length               │          Checksum              │
├─────────────────────────────────┴────────────────────────────────┤
│                          Data                                    │
╰──────────────────────────────────────────────────────────────────╯

That's it. 8 bytes of header. 
TCP header: minimum 20 bytes, up to 60 with options.
```

### What UDP Does NOT Do

```
TCP feature              │ UDP equivalent
─────────────────────────┼──────────────────────
Connection setup         │ None. Just send.
Reliability (retransmit) │ None. Packets may vanish.
Ordering                 │ None. May arrive in any order.
Flow control             │ None. May overwhelm receiver.
Congestion control       │ None. May overwhelm network.
Duplicate detection      │ None. May get duplicates.
```

### Why Would ANYONE Use UDP?

Because sometimes TCP's guarantees are **not just unnecessary — they're harmful**:

```
SCENARIO: Live video call (Zoom, Google Meet)

Frame 1 (timestamp: 0ms)    → Delivered ✓
Frame 2 (timestamp: 33ms)   → LOST
Frame 3 (timestamp: 66ms)   → Delivered ✓
Frame 4 (timestamp: 100ms)  → Delivered ✓

WITH TCP:
  TCP retransmits Frame 2
  Frame 3 and 4 are BLOCKED (head-of-line blocking)
  By the time Frame 2 arrives (say, 200ms later),
  Frames 2, 3, and 4 are ALL stale
  Video freezes, audio stutters
  User sees: "glitch..... then fast-forward"

WITH UDP:
  Frame 2 is lost? Skip it.
  Show Frame 3 immediately, then Frame 4
  User sees: tiny visual artifact, then smooth video
  
  The application handles the loss:
  - Video codec conceals the missing frame
  - Forward Error Correction adds redundancy
  - Application-level retransmit only for keyframes
```

### Real-World UDP Use Cases

```
1. REAL-TIME MEDIA: VoIP, video calls, live streaming
   → Latency matters more than perfect delivery
   → Old data is useless (50ms old audio = garbage)

2. GAMING: Multiplayer game state updates
   → Need the LATEST position, not a retransmitted 
     position from 200ms ago
   → Games implement their own reliability for 
     critical events (damage, scoring)

3. DNS: Domain Name System queries
   → Small request (fits in one packet)
   → Small response (usually)
   → Simple request/response, no need for connection
   → If lost, just retry at application level
   → TCP handshake would DOUBLE latency for a simple lookup

4. DHCP: Getting an IP address
   → You don't HAVE an IP yet, so TCP is awkward

5. QUIC (HTTP/3): Built ON TOP of UDP
   → Implements reliability and congestion control 
     in userspace
   → But solves TCP's head-of-line blocking problem
   → We'll cover this in HTTP/3 section

6. IoT/Telemetry: Sensor data
   → Sending temperature readings every second
   → If one is lost, the next one is coming anyway
```

---

## TCP vs UDP: Complete Comparison

```
Feature              │ TCP                 │ UDP
─────────────────────┼─────────────────────┼──────────────────
Connection           │ Connection-oriented │ Connectionless
Reliability          │ Guaranteed delivery │ Best-effort
Ordering             │ Guaranteed order    │ No ordering
Duplex               │ Full-duplex         │ Full-duplex
Overhead             │ 20-60 byte header   │ 8 byte header
Speed                │ Slower (overhead)   │ Faster (minimal)
Flow control         │ Yes (window)        │ No
Congestion control   │ Yes (built-in)      │ No
Broadcast/Multicast  │ No                  │ Yes
Unit of data         │ Byte stream         │ Datagrams (messages)
Error detection      │ Checksum + recovery │ Checksum only
Use when             │ Correctness > Speed │ Speed > Correctness

SRE keyword: "byte stream vs datagram"
  TCP: No message boundaries. "HelloWorld" might arrive 
       as "Hel" + "loWor" + "ld" — application must frame.
  UDP: Message boundaries preserved. Each send() = one 
       receive(). Clean and simple.
```

---

## TCP Optimizations You Must Know (SRE-Level)

### Nagle's Algorithm
```
Problem: Application sends many tiny packets (1 byte each)
  → Each packet has 40 bytes of headers (IP + TCP)
  → 1 byte data + 40 bytes header = absurd overhead
  → Known as "silly window syndrome"

Nagle's Algorithm:
  IF there is unacknowledged data in flight:
    Buffer small segments and send them together
    Wait until ACK or buffer is full
  ELSE:
    Send immediately

Problem with Nagle + Delayed ACK:
  → Nagle: "I'll wait for the ACK before sending more"
  → Delayed ACK: "I'll wait 200ms before ACKing, 
     hoping to piggyback on data"
  → They're WAITING FOR EACH OTHER = 200ms delay!
  
Fix: TCP_NODELAY socket option (disables Nagle)
When: Low-latency applications, interactive protocols
Netflix, game servers, trading systems: ALWAYS TCP_NODELAY
```

### TCP Keep-Alive
```
Problem: How to detect dead connections?
  - Client crashes without sending FIN
  - Network path goes down silently
  - NAT/firewall drops idle connections

TCP Keep-Alive:
  After idle period (default: 2 hours on Linux!)
  → Send probe packet
  → If no response after N retries → connection dead

SRE tuning:
  net.ipv4.tcp_keepalive_time = 600    (10 min, not 2 hours)
  net.ipv4.tcp_keepalive_intvl = 60    (retry every 60s)
  net.ipv4.tcp_keepalive_probes = 3    (3 retries)
  
  But application-level heartbeats are often better 
  (more control, faster detection)
```

### TCP Fast Open (TFO)
```
Normal TCP: 1 RTT for handshake + 1 RTT for request = 2 RTT
TCP Fast Open: Send data WITH the SYN packet = 1 RTT

How:
  First connection: Normal handshake. Server gives client 
                    a TFO cookie.
  Subsequent connections: Client sends SYN + cookie + data
                          Server validates cookie, processes 
                          data immediately.

Limitation: Only safe for idempotent requests (GET, not POST)
Used by: Google services, CDNs
```

---

## Decision Framework: TCP vs UDP

```
START: Does your data lose value if it arrives late but in order?
│
├── NO  (files, web pages, APIs, DB queries, payments)
│        → USE TCP. You want ordered, reliable, congestion-controlled.
│
└── YES (live position, live audio/video, telemetry)
         → Is occasional loss acceptable if you get the FRESHEST data?
             ├── YES → USE UDP + a thin reliability layer (see below)
             └── NO, must be fresh AND reliable AND multiplexed
                     → USE QUIC (UDP + per-stream reliability) / HTTP/3
```

```
┌──────────────────────┬──────────────────────────────────────────┐
│ Workload             │ Choice + why                              │
├──────────────────────┼──────────────────────────────────────────┤
│ REST/gRPC API        │ TCP (HTTP/2) — ordered, reliable          │
│ Database connection  │ TCP — correctness is non-negotiable       │
│ File download / CDN  │ TCP — every byte must arrive              │
│ DNS query            │ UDP first (small, fast), TCP fallback     │
│ Live game state      │ UDP + seq numbers + selective reliability │
│ VoIP / live video    │ UDP/RTP — drop late frames, stay real-time│
│ Metrics/logs firehose│ UDP (statsd) if loss-tolerant, else TCP   │
│ Mobile, lossy, multi-│ QUIC/HTTP/3 — per-stream, survives IP change│
│   stream             │                                           │
└──────────────────────┴──────────────────────────────────────────┘

IF YOU CHOOSE UDP, you must build what TCP gave you for free
(only the parts you need):
  → Sequence numbers    (detect loss / reorder; drop stale packets)
  → Selective ACKs      (reliable ONLY for critical events, not all)
  → Congestion control  (or you become a bad network citizen)
  → Fragmentation limits (keep payloads under path MTU, ~1200B safe)
```

---

## Deep Dive: Three Questions That Reveal Whether You Truly Understand TCP

These three questions separate memorization from understanding. Each is answered in full.

### 1. Why does the handshake need THREE steps, not two?

The failure a two-way handshake cannot handle is the **delayed duplicate SYN**.

```
THE GHOST-SYN SCENARIO:

  1. Client sends SYN. It gets delayed in a routing loop (wanders for seconds).
  2. Client times out, sends a NEW SYN. This one succeeds: connection opens,
     data flows, connection closes.
  3. The ORIGINAL delayed SYN finally arrives at the server.

  With a 2-way handshake:
    Server sees the old SYN → replies SYN-ACK → marks ESTABLISHED,
    allocates a Transmission Control Block, waits for data that never comes.
    → A half-open zombie connection wasting memory.

  With a 3-way handshake:
    Server does NOT consider the connection established until the client's
    final ACK arrives. The client, having finished, sees a SYN-ACK for a
    connection it didn't start, and replies RST (or ignores it).
    → No 3rd ACK → server never allocates a full connection. Problem solved.
```

The third step is what lets the server distinguish a *fresh* client from a *ghost*.

### 2. Why does one slow image stall the whole page? (TCP Head-of-Line Blocking)

TCP delivers a **single ordered byte stream**. The application receives bytes in exactly the order sent.

```
  Multiple images share one TCP connection → one byte stream.
  A segment carrying part of Image A is lost.

  Image B and Image C segments have ALREADY ARRIVED and sit in the
  kernel receive buffer — but TCP will NOT hand them to the app,
  because doing so would deliver data out of order.

  Everything freezes until Image A's missing segment is retransmitted.
  User sees: whole page frozen. Kernel reality: refusing out-of-order delivery.
```

This is exactly the problem HTTP/2 hit (one TCP connection) and HTTP/3 solved (QUIC per-stream delivery). See the HTTP module.

### 3. 60 players, 30 updates/sec — TCP or UDP?

**UDP**, plus a custom reliability layer. In a 30Hz real-time game, **jitter hurts more than loss**.

```
  Position updates are PERISHABLE:
    If packet #10 (position at t=10) is lost but #11 (t=11) arrives,
    #10 is already useless — you want the newest position, now.

  TCP penalty: losing #10 blocks #11 until #10 is retransmitted →
    the game freezes then fast-forwards (a lag spike).

  UDP wins: drop the lost packet, immediately use the latest position.

  WHAT TO BUILD ON TOP OF UDP:
    → Sequence numbers: discard any packet older than the last processed
      (prevents "teleporting" backward from reordered packets).
    → Selective reliability: positions may be dropped, but EVENTS
      ("player fired", "player died") must not. ACK + resend only those.
    → Client-side prediction + interpolation: hide the 33ms gaps and
      occasional drops by smoothing between known states.
```

---

## Incident Scenario: The Mystery Latency Spike

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: Payment Processing API
Time: 3:47 AM UTC

SYMPTOMS:
  - API latency spiked from 50ms (p50) to 3,200ms (p50)
  - Error rate jumped from 0.01% to 12%
  - Errors are all "connection timeout" from the 
    payment service → database
  - CPU on payment service nodes: 23% (normal)
  - Memory on payment service nodes: 41% (normal)
  - CPU on database: 15% (normal)
  - Network bandwidth: well within limits
  - No deployments in the last 8 hours
  - The issue started gradually, getting worse over 
    ~15 minutes before triggering alerts

ADDITIONAL DATA (you had to ask for this — I'm 
giving it to you):
  - `ss -s` on payment service nodes shows:
    TCP: 48,291 (estab 847, closed 38,102, 
         timewait 38,102)
  - Connection pool config: max_connections = 100
  - Database max_connections = 500
  - There are 6 payment service nodes
  - Database `SHOW PROCESSLIST` shows 497/500 
    connections used
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
Your Task:
Question 1: Based on this data, what is the root cause of this incident? Walk me through your reasoning step by step — what data points led you to your conclusion?

Question 2: What is the immediate mitigation (stop the bleeding RIGHT NOW)?

Question 3: What is the long-term fix so this never happens again?

Question 4: Why did the problem get worse gradually over 15 minutes instead of happening all at once?

# Incident Response & Analysis

---

## Question 1: Root Cause Analysis

> **Root Cause:** Ephemeral Port Exhaustion caused by TCP Connection Churning.

Here is the step-by-step reasoning:

*   **The "Timeout" Clue:** The errors are "connection timeouts" from the service → database. This means the service cannot even establish the initial TCP handshake. If the database were simply slow or locked, we would see "Query Timeout" or "Lock Wait Timeout," not "Connection Timeout."
*   **The "Resource" Paradox:** CPU and Memory are normal on both ends. This tells us the bottleneck is not computational; it is a networking or configuration limit.
*   **The Smoking Gun (`ss -s`):** This is the most critical data point. You have 38,102 connections in `TIME_WAIT`.
    *   In a healthy system using a connection pool, you should see a small, stable number of `estab` (established) connections and very few `TIME_WAIT` connections.
    *   `TIME_WAIT` occurs when the local side (the API service) closes a TCP connection. The kernel keeps the socket in this state for a period (usually 60–240 seconds) to ensure any stray packets still in flight are handled.
*   **The Connection Pool Failure:** The config says `max_connections = 100`, but the `ss -s` shows 847 established connections per node. This means the application is bypassing its own connection pool and opening a new TCP connection for every single incoming request.
*   **The Math of Exhaustion:** Linux has a finite range of ephemeral ports (typically ~28,000 to 60,000 ports). Because the app is opening and closing connections rapidly, it is "churning" through these ports. Once the number of sockets in `TIME_WAIT` exceeds the available ephemeral port range, the kernel cannot assign a source port to a new connection request. The request hangs and eventually times out.
*   **The DB Side:** The DB shows 497/500 connections. This confirms the DB is also saturated because the service is opening far more connections than the DB is configured to handle.

---

## Question 2: Immediate Mitigation

**Fix:** Restart the Payment Service nodes/pods.

**Why?** A restart does two things immediately:
1.  **Clears the Socket Table:** It wipes the `TIME_WAIT` state and releases all exhausted ephemeral ports.
2.  **Resets the Connection Pool:** If the pool was in a corrupted state or experiencing a leak, a restart forces the application to re-initialize its connection management.

> *Note: While you could try to tune `sysctl` (like `tcp_tw_reuse`), a restart is the fastest way to restore service during a P1 incident.*

---

## Question 3: Long-term Fix

To prevent this from happening again, I would implement a three-tiered fix:

1.  **Code/Configuration Audit (The Root):** 
    Investigate why the application bypassed the connection pool. Look for code paths where a developer might have instantiated a new DB client instead of using the singleton pool, or check if a recent config change disabled the pool.

2.  **Align Connection Limits (The Guardrail):**
    *   **Current math:** 6 nodes × 100 `max_connections` = 600 potential connections.
    *   **DB limit:** 500.
    *   **Fix:** Either increase the DB `max_connections` to 650 (to allow a buffer) or lower the service pool size to 80 per node. This prevents the "DB Full" scenario.

3.  **Kernel Tuning (The Safety Net):** 
    Enable `tcp_tw_reuse` in the OS kernel. This allows the kernel to reuse a socket in `TIME_WAIT` state for a new connection if it is safe from a protocol perspective, drastically reducing the risk of port exhaustion.
    ```bash
    sysctl -w net.ipv4.tcp_tw_reuse=1
    ```

---

## Question 4: Why was the onset gradual?

The problem got worse gradually because ephemeral port exhaustion is a "filling the bucket" problem.

*   **The Buffer:** When the connection churning started, the system had ~30,000 available ephemeral ports.
*   **The Accumulation:** Every request consumed one port and put it into `TIME_WAIT`. These ports stay "locked" for a set amount of time (e.g., 60 seconds).
*   **The Tipping Point:** For the first few minutes, the rate of port release (ports exiting `TIME_WAIT`) was roughly equal to the rate of port consumption. As traffic increased or the leak worsened, the consumption rate surpassed the release rate.
*   **The Crash:** Once the "bucket" (the port range) was 100% full, the system hit a hard wall. Every subsequent request failed instantly.

***The 15-minute window was the time it took for the application to burn through the entire available range of available source ports.***

Rapid Fire Question: You're the on-call SRE. It's 3 AM. Your monitoring fires an alert:

ALERT: payment-node-04 TIME_WAIT count = 24,000
       (threshold: 10,000)
       Ephemeral port range: 32768-60999 (28,232 ports)
       Current error rate: 0.3% (within SLO)
       Trending: TIME_WAIT count increasing ~500/min

The system is NOT yet broken. Error rate is still within SLO. But you can see it's heading toward failure.

You have roughly (28,232 - 24,000) / 500 = ~8 minutes before port exhaustion.

The correct prioritized response, in order:

```bash
# ==========================================
# MINUTE 0-1: BUY TIME (stop the clock)
# ==========================================

# Enable TIME_WAIT reuse — takes effect INSTANTLY
# No restart needed, no traffic impact
sudo sysctl -w net.ipv4.tcp_tw_reuse=1

# Verify it took effect
cat /proc/sys/net/ipv4/tcp_tw_reuse
# Should return: 1

# OPTIONAL (more aggressive, buys more ports):
# Widen the ephemeral port range
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"
# Goes from ~28K ports to ~64K ports — doubles your runway


# ==========================================
# MINUTE 1-2: CHECK THE BLAST RADIUS
# ==========================================

# Are other nodes also accumulating TIME_WAIT?
for node in payment-node-0{1..6}; do
  echo "=== $node ==="
  ssh $node "ss -s | grep timewait"
done

# Expected bad output:
#   payment-node-01: timewait 22,841
#   payment-node-02: timewait 25,003
#   ...
# If ALL nodes are affected → systemic (code bug)
# If ONE node → something specific to that node

# Apply sysctl fix to ALL affected nodes:
for node in payment-node-0{1..6}; do
  ssh $node "sudo sysctl -w net.ipv4.tcp_tw_reuse=1"
done


# ==========================================
# MINUTE 2-4: FIND THE LEAK
# ==========================================

# What process is creating all these connections?
# Show connections to the DB port (usually 3306 or 5432)
ss -tnp state time-wait | grep :5432 | head -20

# Count connections per process
ss -tnp state established dst :5432 | \
  awk '{print $NF}' | sort | uniq -c | sort -rn

# Expected output might show:
#   743  users:(("payment-api",pid=8821,fd=...))
#   104  users:(("payment-api",pid=8821,fd=...))
#
# If one PID has way more than pool max (100)
# → THAT process has a connection leak


# ==========================================
# MINUTE 4-5: DRAIN THE SICK NODE
# ==========================================

# Remove node-04 from the load balancer
# (exact command depends on your infrastructure)

# If using Kubernetes:
kubectl cordon payment-node-04

# If using a load balancer like nginx/HAProxy:
# Mark server as "drain" in LB config

# If using AWS ALB:
aws elbv2 deregister-targets \
  --target-group-arn <arn> \
  --targets Id=<instance-id>


# ==========================================
# MINUTE 5-6: RESTART THE DRAINED NODE
# ==========================================

# Node is drained, no traffic flowing to it
# Safe to restart the application process

# If containerized:
kubectl delete pod payment-api-xxxxx -n payments

# If running as a systemd service:
sudo systemctl restart payment-api

# Verify it comes back healthy:
curl -f http://localhost:8080/health

# Verify TIME_WAIT is cleared:
ss -s | grep timewait
# Should be near zero now

# Re-register in load balancer:
kubectl uncordon payment-node-04


# ==========================================
# MINUTE 6-8: VERIFY STABILIZATION
# ==========================================

# Watch TIME_WAIT count — is it climbing again?
watch -n 5 "ss -s | grep timewait"

# If climbing again → the code bug is still active
# → You've bought time but need a code fix
# If stable → restart fixed the pool corruption

# Check error rate in monitoring
# Should be dropping back toward 0.01%

# Check DB connection count
mysql -e "SHOW STATUS LIKE 'Threads_connected';"
# Should be dropping back to normal
```

---

## Key Takeaways

```
╔══════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:             ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. TCP = ordered, reliable, congestion-controlled byte     ║
║      stream. UDP = fire-and-forget datagrams. Everything     ║
║      else follows from this one difference.                  ║
║                                                              ║
║   2. TIME_WAIT (2×MSL, ~60s) on the ACTIVE closer is the     ║
║      #1 cause of port exhaustion. Reuse connections; enable  ║
║      tcp_tw_reuse; widen ephemeral range as a stopgap.       ║
║                                                              ║
║   3. TCP HOL blocking: one lost segment stalls ALL bytes     ║
║      behind it on that connection. This is why HTTP/3 exists.║
║                                                              ║
║   4. Choosing UDP means rebuilding sequence numbers,         ║
║      selective reliability, and congestion control yourself. ║
║                                                              ║
║   5. AWS timeouts bite silently: NLB 350s idle (fixed),      ║
║      ALB 60s (configurable). Long-lived connections need     ║
║      heartbeats under these limits.                          ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading

- TCP/IP Illustrated Vol. 1 (Stevens) — Ch 17–24 (TCP), Ch 11 (UDP)
- High Performance Browser Networking (Grigorik) — Ch 1–2 (latency, TCP)
- RFC 9293 (TCP, 2022 consolidation) — handshake, state machine, TIME_WAIT
- Linux `man tcp(7)` — sysctl knobs referenced above
- AWS docs: NLB/ALB idle timeout limits

---

## Next Module

HTTP/1.1, HTTP/2, and HTTP/3 build directly on TCP and UDP concepts taught above.

**Continue to:** [HTTP/1.1 vs HTTP/2 vs HTTP/3](./HTTP-1.1-vs-HTTP-2-vs-HTTP-3.md)

