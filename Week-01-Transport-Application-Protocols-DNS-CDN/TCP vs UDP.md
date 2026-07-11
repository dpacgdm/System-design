# Topic 1: TCP vs UDP — The Foundation of All Network Communication

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Explain the three-way handshake and WHY three steps       ║
║      are required (delayed duplicate SYN, ghost connections)   ║
║                                                                ║
║   2. Trace how TCP guarantees ordering, reliability, and       ║
║      flow control — and diagnose HOL blocking at the           ║
║      transport layer                                           ║
║                                                                ║
║   3. Choose TCP vs UDP for a workload and justify with         ║
║      latency, loss tolerance, and connection overhead          ║
║                                                                ║
║   4. Diagnose production incidents: TIME_WAIT exhaustion,      ║
║      connection pool bypass, ephemeral port churn, and         ║
║      sysctl-level mitigations                                  ║
║                                                                ║
║   5. Tune TCP for production: Nagle, keepalive, TFO, and       ║
║      when application-level heartbeats beat kernel defaults    ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═══════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "TCP is always better — UDP is legacy"             ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. TCP pays for reliability, ordering, and congestion           ║
║   control on every byte. Real-time media, DNS, QUIC, and gaming       ║
║   use UDP because retransmitting a 20ms-old video frame is            ║
║   worse than dropping it. Choose by loss tolerance, not age.          ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "UDP is unreliable, so never use it in prod"       ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. UDP gives you message boundaries and minimal overhead.       ║
║   QUIC, WireGuard, and custom protocols add reliability at the        ║
║   application layer where they control the tradeoffs — not the        ║
║   kernel's one-size-fits-all TCP stack.                               ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "The three-way handshake is just ceremony"         ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. SYN/SYN-ACK/ACK exchanges initial sequence numbers and       ║
║   prevents ghost connections from delayed duplicate SYNs. Two-way     ║
║   handshakes fail under real network delay and replay.                ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "More TCP connections = more throughput"           ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Each connection costs kernel state, file descriptors,        ║
║   and ephemeral ports. High-churn microservices hit TIME_WAIT         ║
║   exhaustion and port exhaustion before bandwidth limits.             ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Disable Nagle (TCP_NODELAY) for all latency"      ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Nagle coalesces tiny writes to reduce packet storms.         ║
║   Disabling it everywhere increases CPU and packet overhead.          ║
║   Enable selectively where small-write latency actually matters.      ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "TCP guarantees low latency"                       ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. TCP optimizes for throughput and reliability, not latency.   ║
║   Retransmissions, HOL blocking, and slow start inflate tail          ║
║   latency on lossy or high-RTT paths — the root cause HTTP/3          ║
║   replaces TCP entirely.                                              ║
╚═══════════════════════════════════════════════════════════════════════╝
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

# 🛑 SOCRATIC CHECK — STOP AND THINK

Before we do the SRE troubleshooting scenario, I need to make sure the foundation is solid. Answer these:

**Question 1:** In your own words, explain WHY the TCP three-way handshake requires three steps instead of two. Don't just say "to confirm both sides can communicate" — give me the specific failure scenario that two steps can't handle.

**Question 2:** A system you built uses TCP. A user reports that when one image on a webpage is slow to load, ALL other images on that page also stall. What TCP-level phenomenon explains this, and why does it happen?

**Question 3:** You're designing a multiplayer game where 60 players' positions are updated 30 times per second. Should you use TCP or UDP? Explain your reasoning — and what would you build on TOP of your choice to handle the scenarios it doesn't cover natively?

---

> **Socratic check answer key:**
> See [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/TCP%20vs%20UDP%20Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/TCP%20vs%20UDP%20Answers.md).

## Production Failure Patterns

```
PATTERN 1: TIME_WAIT EXHAUSTION (high-churn microservices)
  Symptom: connect() failures, "Cannot assign requested address", rising error rate
  Cause:   Short-lived TCP connections without reuse; default ip_local_port_range
  Fix:     Connection pooling, keep-alive, SO_REUSEADDR, tune net.ipv4.tcp_tw_reuse

PATTERN 2: SYN FLOOD / BACKLOG OVERFLOW
  Symptom: intermittent connection timeouts under load spikes
  Cause:   listen backlog too small, slow accept loop, SYN cookies not enabled
  Fix:     Increase somaxconn, optimize accept path, enable SYN cookies, scale out

PATTERN 3: SILENT PACKET LOSS ON UDP
  Symptom: "works in dev, garbled in prod" for VoIP/gaming/custom protocols
  Cause:   No app-level sequencing; middleboxes drop large UDP datagrams
  Fix:     App-level ACK/retransmit, MTU discovery, or move to QUIC/TCP

PATTERN 4: NAGLE + DELAYED ACK INTERACTION
  Symptom: 200ms stalls on tiny request/response pairs
  Cause:   TCP_NODELAY off + delayed ACK waiting for piggyback data
  Fix:     TCP_NODELAY on latency-sensitive paths; batch writes where safe

PATTERN 5: EPHEMERAL PORT EXHAUSTION ON NAT/LB
  Symptom: outbound connections fail from app servers despite low CPU
  Cause:   Each destination:port tuple consumes ephemeral port until TIME_WAIT clears
  Fix:     Connection pooling to backends, ip_local_port_range expansion, L4 SNAT
```

---

## SRE Diagnostic Toolkit

```
METRICS (Prometheus / CloudWatch):
  node_netstat_Tcp_CurrEstab          — active TCP connections
  node_netstat_Tcp_ActiveOpens        — new connections/sec (churn indicator)
  node_sockstat_TCP_tw                — sockets in TIME_WAIT
  node_netstat_TcpExt_ListenOverflows — accept queue drops (critical)

COMMANDS:
  ss -s                               — socket summary (TIME_WAIT count)
  ss -tan state time-wait | wc -l     — TIME_WAIT connections
  cat /proc/sys/net/ipv4/ip_local_port_range
  netstat -s | grep -i "listen\|overflow\|retransmit"
  ss -i dst <backend-ip>:443          — per-connection TCP info (cwnd, rtt)

LOG PATTERNS:
  "connection refused" + rising ActiveOpens → backlog or target down
  "cannot assign requested address"         → ephemeral port / TIME_WAIT exhaustion
  "broken pipe" after deploy                → drained connections hitting closed sockets

AWS-SPECIFIC:
  NLB/ALB TargetConnectionErrorCount      — backend connect failures
  NLB ActiveFlowCount / ProcessedBytes    — correlate with app connection pools
  Enhanced networking (ENA) metrics       — packet drops at hypervisor
```

---

## Decision Framework

```
TCP vs UDP — QUICK CHOOSER:

  Need reliable ordered byte stream?           → TCP (default for APIs, DB, HTTP)
  Can tolerate loss, need message boundaries?  → UDP (+ app reliability if needed)
  Need low latency + encryption + multiplex?   → QUIC (HTTP/3) over UDP
  Real-time media with late-frame discard?     → UDP (RTP/WebRTC) or QUIC streams

CONNECTION MANAGEMENT:
  High RPS to same backend                   → persistent connection pool (HTTP/2, gRPC)
  Millions of short RPCs                     → watch TIME_WAIT; pool or tune sysctl
  NAT traversal / mobile                     → QUIC or TCP keepalive + app heartbeats

TUNING:
  Interactive small messages                 → consider TCP_NODELAY
  Bulk transfer                              → leave Nagle on; increase buffer sizes
  Long-idle connections through LBs          → app-level heartbeats < LB idle timeout
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

- **Question 1:** Based on this data, what is the root cause? Walk through your reasoning step by step.
- **Question 2:** What is the immediate mitigation (stop the bleeding RIGHT NOW)?
- **Question 3:** What is the long-term fix so this never happens again?
- **Question 4:** Why did the problem get worse gradually over 15 minutes instead of all at once?

---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**
> [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/TCP vs UDP Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/TCP vs UDP Answers.md)

## On-Call Drill: Pre-Failure TIME_WAIT Alert

Rapid-fire: You're the on-call SRE. It's 3 AM. Your monitoring fires an alert:

ALERT: payment-node-04 TIME_WAIT count = 24,000
       (threshold: 10,000)
       Ephemeral port range: 32768-60999 (28,232 ports)
       Current error rate: 0.3% (within SLO)
       Trending: TIME_WAIT count increasing ~500/min

The system is NOT yet broken. Error rate is still within SLO. But you can see it's heading toward failure.

You have roughly (28,232 - 24,000) / 500 = ~8 minutes before port exhaustion.

What do you do, in order, right now? Be specific. Give me the exact commands or actions, sequenced by priority.

> **On-call drill worked answer:**
> See [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/TCP%20vs%20UDP%20Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/TCP%20vs%20UDP%20Answers.md).

---

## Incident Scenario (Extended): DNS Resolver Timeout Cascade

```
INCIDENT REPORT #2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: Internal microservices mesh (EKS, us-east-1)
Time: 11:23 AM UTC (peak traffic)

ARCHITECTURE:
  800 microservice pods → CoreDNS (3 replicas) → Route 53 Resolver
  Services use short hostnames: payment-svc, inventory-svc
  ndots:5 (default Kubernetes) — search path expansion active

SYMPTOMS:
  - p99 latency 50ms → 2,800ms across ALL services simultaneously
  - No deployment in last 24 hours
  - CPU: app pods normal; CoreDNS 98% CPU on all 3 replicas
  - CoreDNS QPS: 620,000 (baseline: 45,000)
  - NXDOMAIN rate: 78% of queries
  - Errors: "dial tcp: lookup inventory-svc on 10.100.0.10:53: i/o timeout"

SMOKING GUN (from one pod's tcpdump):
  Query 1: inventory-svc.default.svc.cluster.local → NXDOMAIN (wrong suffix attempt)
  Query 2: inventory-svc.svc.cluster.local → NXDOMAIN
  Query 3: inventory-svc.cluster.local → NXDOMAIN
  Query 4: inventory-svc → SUCCESS (after 4 wasted round-trips)

CLUE TO INVESTIGATE:
  A new service was registered in the commerce namespace. Callers use a
  short service name rather than a fully-qualified service DNS name.

QUESTIONS:
  Q1: Why did ALL services slow down, not just commerce namespace?
  Q2: Immediate mitigation (60 seconds)?
  Q3: Long-term fix that survives new services?
  Q4: Why UDP for DNS and when does TCP kick in?
```

> **Extended DNS cascade answer key:**
> See [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/TCP%20vs%20UDP%20Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/TCP%20vs%20UDP%20Answers.md).

---

## Hands-On Exercises

These exercises build muscle memory for TCP/UDP production diagnostics. Run on a Linux VM or EKS node with appropriate permissions.

### Exercise 1: TIME_WAIT Census

```bash
# Baseline socket summary
ss -s

# Count TIME_WAIT to database port (Postgres 5432 example)
ss -tan state time-wait dst :5432 | wc -l

# Ephemeral port range (Linux)
cat /proc/sys/net/ipv4/ip_local_port_range
# Example: 32768 60999 → 28,232 available ports

# MATH: if churn rate = 500 new connections/sec and TIME_WAIT = 60s
# steady-state TIME_WAIT ≈ 500 × 60 = 30,000 → near exhaustion
```

### Exercise 2: Connection Pool vs Churn Detection

```bash
# Established connections per process
ss -tnp state established | awk '{print $NF}' | sort | uniq -c | sort -rn | head

# If one PID has >> pool max (e.g., 800 vs max 100) → leak or bypass

# Watch churn in real time (5-second samples)
watch -n 5 'ss -s | grep -E "TCP:|timewait"'
```

### Exercise 3: sysctl Tuning (lab only — document before prod)

```bash
# Enable TIME_WAIT reuse (Linux 4.x+)
sudo sysctl -w net.ipv4.tcp_tw_reuse=1

# Widen ephemeral range (doubles runway)
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"

# Verify
sysctl net.ipv4.tcp_tw_reuse net.ipv4.ip_local_port_range
```

### Exercise 4: UDP Loss vs TCP Retransmit

```bash
# UDP: send 1000 datagrams, count received (two terminals)
# Terminal A: nc -u -l 9999 | wc -l
# Terminal B: for i in $(seq 1 1000); do echo $i | nc -u localhost 9999; done

# TCP: same test — all 1000 arrive (unless severe loss)
# Observe: TCP slower under loss; UDP faster but incomplete
```

### Exercise 5: ALB / NLB Connection Logs (AWS)

```bash
# Enable ALB access logs to S3; query with Athena:
# SELECT target_ip, count(*) AS requests
# FROM alb_logs
# WHERE day = current_date AND request_url LIKE '%/payments%'
# GROUP BY target_ip
# ORDER BY requests DESC;
# Skew > 3× median → connection stickiness or gRPC black hole (Week 1 gRPC module)
```

### Exercise 6: tcpdump Handshake Forensics

```bash
# Capture SYN/SYN-ACK/ACK for failed connection
sudo tcpdump -i any host db.internal.example.com and port 5432 -w /tmp/db.pcap

# In Wireshark: Statistics → Conversations → TCP
# Look for: SYN retransmits (timeout), RST after SYN-ACK (ACL/firewall)
```

---

## Ops Sim: Northstar Checkout Port Exhaustion

**Time box:** 30 minutes
**Severity:** P1
**Service / domain:** `checkout-api` transport path to PostgreSQL
**Northstar system:** Checkout OLTP (`checkout-api` -> PgBouncer -> PostgreSQL 15)

### Rules

1. Answer from memory; do not re-read the TCP section mid-drill.
2. Write decisions in order (T+0 -> T+60).
3. Name evidence (metric, log line, config key) for every claim.
4. Do not open the answer key until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  18% of checkout attempts hang for 8-12s, then fail with "try again".
  Product pages, search, and wallet balance reads are normal.

WHAT ON-CALL SEES:
  P1 checkout availability burn; p99 latency 280ms -> 9.4s.
  Errors are mostly connect timeouts from checkout-api to PgBouncer.
  CPU and memory are normal on checkout-api, PgBouncer, and Postgres.

BUSINESS CONSTRAINT:
  A celebrity auction closes in 25 minutes. Disabling checkout globally costs
  about $180K/minute; duplicate charges are worse than temporary cart failures.
```

### 2. Telemetry pack

```text
METRICS:
  checkout-api pods: 36; RPS 18k; CPU 38%; memory 51%
  checkout_api_db_connect_timeout_total: 0/min -> 2,900/min
  node_netstat_Tcp_ActiveOpens: 4k/min -> 640k/min
  node_sockstat_TCP_tw: median 1,900 -> 41,700 per pod
  ip_local_port_range: 32768 60999 (28,232 ports)
  PgBouncer checkout pool: cl_active=180, cl_waiting=0, sv_active=180, sv_idle=20
  Postgres max_connections=260; active=214; lock waits normal

LOG LINES:
  checkout-api: dial tcp 10.42.8.17:6432: connect: cannot assign requested address
  checkout-api: created transient pg client for request_id=... route=/bid/settle
  PgBouncer: login attempt: db=checkout user=checkout tls=no
  kernel: possible SYN flooding on port 47412; sending cookies

TRACE:
  checkout_api -> pg_bouncer connect span p99=7.8s
  SQL execution span p99=22ms when a connection is acquired
```

### 3. Config pack

```yaml
# checkout-api deployment
env:
  PGBOUNCER_DSN: postgres://checkout@pgbouncer.checkout.svc:6432/checkout
  DB_POOL_MAX: "40"
  DB_POOL_IDLE_TIMEOUT_MS: "30000"
  PAYMENT_LEDGER_DSN: postgres://ledger@pgbouncer.pay.svc:6432/ledger

# wrong/dangerous config introduced in the auction settlement worker
auctionSettlement:
  use_shared_pool: false
  connect_per_bid: true
  tcp_keepalive_seconds: 0
  retry_connects: 3

# node sysctl
net.ipv4.tcp_fin_timeout = 60
net.ipv4.tcp_tw_reuse = 0
```

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | P1 page: checkout connect timeouts; SQL time is normal. | |
| T+5 | TIME_WAIT exceeds ephemeral port range on 19/36 pods. | |
| T+15 | Product VP asks to "just raise Postgres max_connections to 1000". | |
| T+60 | Auction traffic is stable; error rate is below 0.5% but TIME_WAIT still elevated. | |

### 5. Questions

**Q1 - Layer & root cause:** Which layer owns the primary symptom? What mechanism turns short-lived DB connects into checkout failure?

**Q2 - Evidence:** Which 3 signals prove port exhaustion / connection churn? Which signal is a red herring?

**Q3 - Sequencing:** What do you do in the first 15 minutes? Include one mitigation that buys time and one that removes load.

**Q4 - Bad fix gallery:** Why is "raise Postgres max_connections" dangerous? Why is "restart all checkout pods now" incomplete?

**Q5 - Capacity / blast radius:** With 28,232 ephemeral ports and 60s TIME_WAIT, what approximate new-connect rate per pod is unsafe? What else breaks if all pods reconnect at once?

**Q6 - Durable fix:** Name the code/config change and the acceptance criteria.

**Q7 - Org / runbook:** Who is informed by T+10, and what is pre-authorized for checkout during this P1?

### 6. Self-score

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Knowledge gap | | |
| Wrong layer | | |
| Sequencing error | | |
| Capacity miss | | |
| Org/runbook miss | | |

**Answer key:** [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/TCP vs UDP Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/TCP%20vs%20UDP%20Answers.md)

---

## Key Takeaways

```
╔══════════════════════════════════════════════════════════════╗
║   1. TCP guarantees delivery and order; UDP trades that for  ║
║      latency. Choose based on whether stale data is useless. ║
║                                                              ║
║   2. Three-way handshake prevents ghost connections from     ║
║      delayed duplicate SYNs — two steps are insufficient.    ║
║                                                              ║
║   3. TCP HOL blocking: one lost segment stalls the entire    ║
║      byte stream — this is why HTTP/3 moved to QUIC.         ║
║                                                              ║
║   4. TIME_WAIT exhaustion is a port-range problem, not CPU.  ║
║      ss -s timewait count is the first diagnostic.           ║
║                                                              ║
║   5. Connection pools exist for a reason — bypassing them    ║
║      creates churn that eventually blocks new connections.   ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading

- RFC 9293 (TCP) — especially §3.3 (handshake) and §3.8 (congestion control)
- *High Performance Browser Networking* — Ch 2–4 (TCP/UDP fundamentals)
- Brendan Gregg: USE method applied to network stack (`ss`, `netstat`, `tcpdump`)

---

## Next Module

HTTP/1.1, HTTP/2, and HTTP/3 build directly on TCP and UDP concepts taught above.

**Continue to:** [HTTP/1.1 vs HTTP/2 vs HTTP/3](./HTTP-1.1-vs-HTTP-2-vs-HTTP-3.md)
