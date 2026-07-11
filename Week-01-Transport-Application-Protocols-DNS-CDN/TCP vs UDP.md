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

## Socratic Check — Worked Answers

> Attempt the questions above from memory before reading these.

### Question 1: The TCP Three-Way Handshake

The critical failure scenario that a two-way handshake cannot handle is the Delayed Duplicate SYN.

The Scenario:

The Ghost Request: A client sends a SYN packet to a server. However, due to network congestion or a routing loop, this packet is delayed and wanders the internet for several seconds.

The Retry: The client times out, assumes the packet was lost, and sends a new SYN. This second attempt succeeds; the connection is established, the data is exchanged, and the connection is closed.

The Zombie Arrival: Now, the original, delayed SYN packet finally arrives at the server.

If we used a 2-way handshake:
The server would receive that old SYN, send a SYN-ACK, and immediately mark the connection as ESTABLISHED. It would allocate memory (the Transmission Control Block) and wait for data. However, the client—which has already finished its business—will receive a SYN-ACK for a connection it didn't start and will simply ignore it.

The server is now stuck holding a "half-open" connection, wasting resources on a ghost client.

Why the 3rd step fixes this:
In a 3-way handshake, the server doesn't consider the connection "Established" until it receives the final ACK from the client. In the zombie scenario, the client receives the SYN-ACK for the old request, realizes the sequence number is outdated/invalid, and sends a RST (Reset) or simply ignores it. Because the server never gets that 3rd packet, it never fully allocates the resources for a full connection.

### Question 2: Head-of-Line (HOL) Blocking

This phenomenon is called TCP Head-of-Line Blocking.

Why it happens:
TCP is designed to be a reliable, ordered stream of bytes. It guarantees that the application receives data in the exact order it was sent.

If you are downloading multiple images over a single TCP connection, the images are sent as a continuous sequence of segments. If one segment (containing part of Image A) is lost in transit, the TCP receiver cannot "skip over" that hole to deliver the data for Image B and C to the browser—even if the packets for Image B and C have already arrived and are sitting in the kernel's receive buffer.

The TCP stack must hold all subsequent data in a queue until the missing segment of Image A is successfully retransmitted and received. To the user, it looks like the entire page has frozen, but at the kernel level, the TCP stack is simply refusing to pass the "out-of-order" data up to the application to maintain the integrity of the stream.

### Question 3: Multiplayer Game Architecture

**The choice:** UDP (User Datagram Protocol)

**Reasoning:** In a high-frequency real-time game (30Hz updates), latency and jitter matter more than occasional packet loss.

**Ephemeral data:** Position updates are perishable. If packet #10 (player position at t=10) is lost but packet #11 (position at t=11) arrives, packet #10 is useless.

**The TCP penalty:** Loss of packet #10 triggers retransmission. TCP blocks packet #11 from reaching the game engine until #10 is recovered — a lag spike where the game freezes then fast-forwards.

**UDP's advantage:** Drop the lost packet and process the most recent position, keeping state close to real-time.

**What to build on top of UDP:**

- **Sequence numbers:** Discard packets with sequence lower than last processed (prevents teleporting backward).
- **Selective reliability (ACKs):** Positions can be lost; events like "player fired" or "player died" cannot. Manual ACK for reliable packet types with re-send on timeout.
- **Client-side prediction and interpolation:** Hide 30Hz stutter and occasional drops by predicting between known positions.

---

---

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

ROOT CAUSE:
  New service registered as inventory-svc.commerce.svc.cluster.local but
  callers use bare inventory-svc without FQDN. ndots:5 causes 4 search-domain
  expansions per lookup → 5× query amplification → CoreDNS meltdown.

QUESTIONS:
  Q1: Why did ALL services slow down, not just commerce namespace?
  Q2: Immediate mitigation (60 seconds)?
  Q3: Long-term fix that survives new services?
  Q4: Why UDP for DNS and when does TCP kick in?
```

### Expert Analysis — DNS Cascade

**Q1:** CoreDNS is shared cluster infrastructure. Every pod's resolver hits the same
ClusterIP (kube-dns). Amplified NXDOMAIN traffic saturates CoreDNS CPU — a **shared
fate domain** problem. One team's hostname misconfiguration becomes everyone's outage.

**Q2:**
```bash
# Scale CoreDNS immediately
kubectl -n kube-system scale deployment/coredns --replicas=12

# Fix ndots for commerce namespace (reduce search expansion)
kubectl patch deployment inventory-caller -p '{"spec":{"template":{"spec":{"dnsConfig":{"options":[{"name":"ndots","value":"2"}]}}}}}'

# Or use FQDN in config: inventory-svc.commerce.svc.cluster.local.
```

**Q3:** Policy-as-code: all service URLs must be FQDN in ConfigMaps; lint in CI.
Consider NodeLocal DNSCache DaemonSet to absorb amplification at node level.
Document ndots behavior in onboarding (Week 1 DNS module cross-reference).

**Q4:** DNS uses UDP port 53 for speed (single RTT). TCP is used when response
exceeds 512 bytes (truncated flag) or for zone transfers. Resolver timeout on UDP
often indicates overload or packet loss — not "switch to TCP" as first fix.

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

