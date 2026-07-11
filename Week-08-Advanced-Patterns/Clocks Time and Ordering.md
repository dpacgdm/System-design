# Week 8, Topic 1 — Clocks, Time, and Ordering

---

## Learning Objectives
```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Distinguish physical clocks (wall clock / RTC) from       ║
║      logical clocks (Lamport, vector) and monotonic clocks     ║
║      (CLOCK_MONOTONIC) — and state which operations each       ║
║      is safe for in production                                 ║
║                                                                ║
║   2. Explain clock skew, drift, and leap seconds — and why     ║
║      they make wall-clock timestamps UNRELIABLE for ordering   ║
║      events across distributed nodes                           ║
║                                                                ║
║   3. Describe how NTP and AWS Time Sync Service synchronize    ║
║      clocks, what accuracy they achieve, and what failure      ║
║      modes remain even with perfect NTP                        ║
║                                                                ║
║   4. Articulate the happens-before relation (→) as the         ║
║      fundamental partial order of distributed causality —      ║
║      independent of any physical clock                         ║
║                                                                ║
║   5. Explain TrueTime (Google Spanner): GPS + atomic clocks,   ║
║      uncertainty intervals, and how commit-wait achieves       ║
║      external consistency (linearizability)                    ║
║                                                                ║
║   6. Diagnose production bugs caused by wall-clock misuse:     ║
║      LWW data loss, TTL expiry storms, lease split-brain,      ║
║      out-of-order log compaction, and "time travel" reads      ║
║                                                                ║
║   7. Choose the correct time source for a given engineering    ║
║      decision: wall clock vs monotonic vs logical vs hybrid    ║
║      clock (HLC) vs TrueTime-style bounded uncertainty         ║
║                                                                ║
║   8. Operate an SRE toolkit for clock health: chrony status,   ║
║      AWS Time Sync metrics, leap-second readiness, and         ║
║      application-level timestamp audit patterns                ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════╗
║   DESTROY THESE BEFORE GOING FURTHER                           ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   WRONG #1: "All machines have the same time."                 ║
║   ───────────────────────────────────────────                  ║
║   Two EC2 instances launched from the same AMI at the same     ║
║   second can disagree by milliseconds to SECONDS. NTP brings   ║
║   them close (typically <1ms in same AZ with Time Sync), but   ║
║   "close" is not "identical." Clock skew is always non-zero.   ║
║   Distributed systems must assume clocks disagree.             ║
║                                                                ║
║   WRONG #2: "NTP fixes everything — just enable it."           ║
║   ──────────────────────────────────────────────────           ║
║   NTP synchronizes wall clocks. It does NOT provide:           ║
║   → A global total order of events                             ║
║   → Causal ordering across asynchronous message paths          ║
║   → Immunity to leap seconds, VM freeze, or manual clock set   ║
║   → Sub-millisecond certainty without specialized hardware     ║
║   NTP is necessary infrastructure. It is NOT a consistency     ║
║   protocol.                                                    ║
║                                                                ║
║   WRONG #3: "Monotonic clocks are synchronized across nodes."  ║
║   ─────────────────────────────────────────────────────────    ║
║   CLOCK_MONOTONIC on host A and host B are INDEPENDENT.        ║
║   They count nanoseconds since boot on THAT machine. You       ║
║   cannot compare monotonic timestamps from two different       ║
║   hosts. Monotonic clocks are for DURATION and LOCAL           ║
║   ordering on one machine — not cross-node ordering.           ║
║                                                                ║
║   WRONG #4: "Timestamps give you a total order."               ║
║   ─────────────────────────────────────────────                ║
║   Wall-clock timestamps give you an APPROXIMATE order with     ║
║   AMBIGUITY. Two events with timestamps T1 and T2 where        ║
║   T1 < T2 might actually have happened in the opposite         ║
║   order (clock skew). Events with the SAME timestamp are       ║
║   concurrent — no order at all. Only happens-before gives      ║
║   a provably correct partial order.                            ║
║                                                                ║
║   WRONG #5: "TrueTime means Google has perfect clocks."        ║
║   ─────────────────────────────────────────────────────        ║
║   TrueTime explicitly ACKNOWLEDGES imperfection. It returns    ║
║   an INTERVAL [earliest, latest] — "the true time is           ║
║   somewhere in here, we're not sure exactly where." Spanner    ║
║   waits out the uncertainty (commit-wait) before exposing      ║
║   a transaction. Perfect clocks would return a point, not an   ║
║   interval. TrueTime is engineering around clock error.        ║
║                                                                ║
║   WRONG #6: "Use Date.now() for distributed IDs/ordering."     ║
║   ───────────────────────────────────────────────────────      ║
║   Date.now() / time.time() / System.currentTimeMillis()        ║
║   read the wall clock. It can GO BACKWARDS (NTP step, leap     ║
║   second, manual correction, VM migration). Snowflake IDs,     ║
║   LWW registers, and TTL calculations built on wall clock      ║
║   without safeguards are production incident factories.        ║
║                                                                ║
║   WRONG #7: "Leap seconds don't matter anymore."               ║
║   ─────────────────────────────────────────────                ║
║   Google abolished leap seconds internally (smearing). AWS     ║
║   and Linux distros have varying strategies. Your app may      ║
║   still see: repeated timestamps, backward jumps, or 61-       ║
║   second minutes depending on OS and NTP config. "Someone      ║
║   else handles it" is not an engineering answer.               ║
║                                                                ║
║   WRONG #8: "Happens-before is just a formal name for          ║
║              timestamps."                                      ║
║   ─────────────────────────────────────────────────────        ║
║   Happens-before is defined by PROGRAM STRUCTURE and MESSAGE   ║
║   FLOW — not by any clock reading. Event A → B means A         ║
║   causally influenced B. Two events with A ↛ B and B ↛ A       ║
║   are CONCURRENT — no clock can prove which came first.        ║
║   This is the foundation of Lamport clocks (Topic 2).          ║
╚════════════════════════════════════════════════════════════════╝
```

**Where you've already seen time bite you (connecting prior weeks):**

```
╔════════════════════════════════════════════════════════════════╗
║   PRIOR REFERENCE             │  CLOCK / ORDERING CONNECTION   ║
╠════════════════════════════════════════════════════════════════╣
║  Week 3 T2: Linearizability   │ Defined using REAL TIME —      ║
║                               │ "after write completes at      ║
║                               │ wall-clock moment T, all reads ║
║                               │ see new value." Requires       ║
║                               │ synchronized clocks OR logical ║
║                               │ equivalent (TrueTime, Raft).   ║
╠════════════════════════════════════════════════════════════════╣
║  Week 4 T1: Leader lease      │ Lease expiry uses wall clock.  ║
║                               │ Clock skew → split brain: two  ║
║                               │ nodes both believe they are    ║
║                               │ leader. THE canonical clock    ║
║                               │ skew failure.                  ║
╠════════════════════════════════════════════════════════════════╣
║  Week 5 T1: LSN / WAL position│ Total order within one DB —    ║
║                               │ NOT across shards. Logical     ║
║                               │ ordering without wall clock.   ║
╠════════════════════════════════════════════════════════════════╣
║  Week 6 T6: Outbox sequence   │ Monotonic sequence per         ║
║                               │ aggregate — logical order, not ║
║                               │ timestamp order.               ║
╠════════════════════════════════════════════════════════════════╣
║  Week 8 T2: CRDTs (preview)   │ LWW-Register uses timestamps.  ║
║                               │ Clock skew → silent data loss. ║
║                               │ This topic explains WHY.       ║
╠════════════════════════════════════════════════════════════════╣
║  Week 1 T6: CDN Age header    │ Age = now - Date response      ║
║                               │ header. Uses origin/edge wall  ║
║                               │ clocks. Skew → wrong Age,      ║
║                               │ premature/late TTL expiry.     ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

### 3.1 — The Fundamental Problem: There Is No Global Now

```
IN A SINGLE PROCESS:

  int x = 0;
  x = 1;          // Event A
  print(x);       // Event B

  A happened before B. Guaranteed. Same memory, same thread,
  same happens-before chain. No clock needed.

IN A DISTRIBUTED SYSTEM:

  Node 1 (Virginia):  x = 1;     // Event A, local time 14:32:01.003
  Node 2 (Tokyo):     print(x);  // Event B, local time 14:32:01.001

  Node 2's clock says B happened 2ms BEFORE A.
  But if A caused B (write then read), A MUST have happened first.

  The clocks are WRONG about ordering — or rather, they measure
  something different from causality.

THE INSIGHT (Lamport, 1978):

  "The concept of 'happening before' defines an invariant partial
   ordering of events in a distributed system."

  Physical time does not give you this ordering reliably.
  Logical time does.

WHY THIS MATTERS FOR SYSTEM DESIGN:

  Every time you use a timestamp to:
    → Order events across nodes
    → Decide "which write wins" (LWW)
    → Expire a lease or lock
    → Generate a unique ID
    → Set a TTL
    → Compact logs ("delete everything before T")

  ...you are implicitly assuming something about clocks.
  This section makes that assumption explicit — so you can
  decide whether it's safe.
```

---

### 3.2 — Physical Clocks (Wall Clock / Real-Time Clock)

```
PHYSICAL CLOCK = A clock that measures REAL-WORLD (civil) time.

  Sources:
    → Quartz crystal oscillator (cheap, drifts)
    → CPU timestamp counter (TSC) — very fast, can drift or
      be affected by frequency scaling / VM migration
    → Network Time Protocol (NTP) — synchronizes to reference
    → GPS receiver — ~100ns accuracy to UTC
    → Atomic clock (cesium, rubidium) — defines the second
    → Real-Time Clock (RTC) chip on motherboard — battery-
      backed, survives reboot, often drifts seconds/day

WHAT YOUR APPLICATION READS:

  Linux:
    clock_gettime(CLOCK_REALTIME, &ts)   // wall clock (UTC-based)
    // Equivalent to what Date.now(), time.time(), Instant.now() use

  Java:
    System.currentTimeMillis()            // wall clock, ms precision
    Instant.now()                         // wall clock, ns precision

  Python:
    time.time()                           // wall clock (float seconds)
    datetime.now(timezone.utc)            // wall clock, aware

  Go:
    time.Now()                            // wall clock

  JavaScript (browser/Node):
    Date.now()                            // wall clock, ms
    performance.timeOrigin + performance.now()  // hybrid (see 3.3)

PROPERTIES OF PHYSICAL CLOCKS:

  ✓ Human-meaningful: "this log entry is from March 15 at 3pm"
  ✓ Comparable across systems (if synchronized)
  ✓ Required for certificates, OAuth expiry, cron schedules
  ✓ Required for audit trails regulators can read

  ✗ Can go BACKWARDS (NTP step correction, leap second, admin)
  ✗ Can JUMP FORWARDS (NTP catch-up after outage)
  ✗ Drift between machines even when synchronized (residual skew)
  ✗ VM suspend/resume causes discontinuities
  ✗ Resolution ≠ accuracy (millisecond resolution does not mean
    millisecond accuracy — you can read timestamps 1ms apart that
    are actually out of order by 100ms)

TAI vs UTC — THE LEAP SECOND PROBLEM:

  TAI (International Atomic Time):
    → Monotonically increasing
    → Counts SI seconds from epoch
    → 37 seconds ahead of UTC (as of 2024)
    → Used by GPS internally

  UTC (Coordinated Universal Time):
    → What civil clocks display
    → TAI minus leap seconds
    → NOT monotonic — leap seconds insert extra second
    → NTP distributes UTC

  When a leap second is inserted (rare — last was 2016):
    23:59:59 → 23:59:60 → 00:00:00   (positive leap second)
    OR the second is "smeared" over hours (Google, AWS approach)

  Your application sees:
    → Duplicate Unix timestamps (same second twice)
    → time.time() going backward (if OS steps)
    → Metrics graphs with a one-second gap or overlap
    → TTL timers firing one second late or early

  Linux kernel behavior (varies by version and config):
    → leapsecond.list + tzdata
    → Some kernels: "insert" leap second in kernel clock
    → chrony: can slew or step depending on config
    → AWS: leap second smearing on Amazon Linux / Time Sync

VISUAL: CLOCK DRIFT WITHOUT SYNCHRONIZATION

  Real time ──────────────────────────────────────────────►

  Reference (UTC):  12:00:00.000 ────────────────────────►
  Server A:         12:00:00.000 ─── +50ms drift ────────►
  Server B:         12:00:00.000 ──────── +200ms drift ──►
  Server C:         12:00:00.000 ── -30ms drift ─────────►

  After 1 hour without NTP:
    Server A might be 3-5 seconds off (typical quartz drift)
    Server B might be 10+ seconds off
    Server C might be 2 seconds off

  With NTP (same datacenter):
    Typically within 0.1 - 1ms of reference
    With AWS Time Sync in same AZ: often <100 microseconds
    With specialized hardware (Spanner): <1ms uncertainty
```

---

### 3.3 — Monotonic Clocks

```
MONOTONIC CLOCK = A clock that NEVER goes backwards.
                  NOT tied to civil time.
                  NOT comparable across machines.

Linux clock types:

  CLOCK_MONOTONIC
    → Seconds + nanoseconds since an unspecified point (boot)
    → Pauses during suspend (S3 sleep) on some systems
    → Use for: measuring elapsed time, timeouts on one host

  CLOCK_BOOTTIME
    → Like MONOTONIC but INCLUDES suspend time
    → Use for: "how long has this process been waiting total"
    → Preferred for timeout logic on laptops/mobile; good practice
      on servers too

  CLOCK_MONOTONIC_RAW
    → Not adjusted by NTP frequency correction
    → Pure hardware tick rate
    → Use for: benchmarking (don't conflate NTP slewing with perf)

  CLOCK_REALTIME
    → Wall clock. CAN go backwards. NOT monotonic.

API mapping:

  Java:
    System.nanoTime()          // monotonic, nanosecond resolution
    System.currentTimeMillis() // wall clock — DO NOT use for duration

  Python:
    time.monotonic()           // monotonic seconds (PEP 418)
    time.time()                // wall clock

  Go:
    time.Since(start)          // uses monotonic reading internally
                               // when start came from time.Now()
    time.Now()                 // wall clock, but Go stores monotonic
                               // reading alongside for Sub/Since/Until

  JavaScript:
    performance.now()          // monotonic ms since navigation start
                               // NOT comparable across tabs/processes
    Date.now()                 // wall clock

  C# / .NET:
    Stopwatch.GetTimestamp()   // monotonic
    DateTime.UtcNow            // wall clock

CORRECT USAGE PATTERNS:

  # TIMEOUT on a single server (CORRECT):
  start = time.monotonic()
  ... do work ...
  if time.monotonic() - start > 30.0:
      raise TimeoutError("operation exceeded 30s")

  # TIMEOUT (WRONG — wall clock can go backward):
  start = time.time()
  ... NTP steps clock back 5 seconds ...
  if time.time() - start > 30.0:   # might never fire!
      raise TimeoutError(...)

  # LATENCY MEASUREMENT in a service (CORRECT):
  t0 = time.monotonic()
  response = call_downstream()
  latency_ms = (time.monotonic() - t0) * 1000
  metrics.histogram("downstream.latency", latency_ms)

  # EXPIRY TOKEN (wall clock — CORRECT use case):
  if time.time() > token.expires_at:
      raise AuthError("token expired")
  # OAuth, JWT exp, certificate notBefore/notAfter — MUST be wall

DECISION RULE:

  ┌─────────────────────────────────────────────────────────────┐
  │  Question: "How long did this TAKE?" (one machine)          │
  │  Answer: MONOTONIC clock                                    │
  ├─────────────────────────────────────────────────────────────┤
  │  Question: "When did this happen in the real world?"        │
  │  Answer: WALL clock (with skew awareness)                   │
  ├─────────────────────────────────────────────────────────────┤
  │  Question: "Which of two events on DIFFERENT machines       │
  │            happened first?"                                 │
  │  Answer: NOT monotonic. Use happens-before, logical clocks, │
  │          or TrueTime-style bounded uncertainty.             │
  └─────────────────────────────────────────────────────────────┘

GO GOTCHA (production-relevant):

  Go's time.Time from time.Now() carries both wall and monotonic.
  time.Sleep, time.Since, time.Until use the monotonic reading.
  BUT: if you serialize time.Time to JSON/protobuf and deserialize
  on another machine, the monotonic reading is STRIPPED.
  Only the wall clock survives transmission.
  → Never use deserialized timestamps for duration measurement.
```

---

### 3.4 — Clock Skew and Clock Drift

```
CLOCK DRIFT = The rate at which a clock's time diverges from true time.
              Measured in ppm (parts per million).
              A clock at +50 ppm gains 50 microseconds per second.
              After 1 hour: 50ppm × 3600s = 180ms error.

CLOCK SKEW = The instantaneous DIFFERENCE between two clocks at a moment.
             skew(A,B) = clock_A - clock_B

             Example:
               Server A thinks it is 12:00:00.500
               Server B thinks it is 12:00:00.200
               Skew = +300ms (A is ahead of B)

DRIFT vs SKEW:

  Drift is a VELOCITY (how fast error accumulates).
  Skew is a POSITION (how far apart clocks are right now).

  NTP corrects skew by adjusting the clock RATE (slew) or
  stepping the clock (jump). Slew is preferred: gradually speed
  up or slow down the tick rate so the clock "catches up" without
  a discontinuity.

TYPICAL SKEW VALUES (order of magnitude):

  Unsynchronized VMs:           10ms - several seconds
  NTP-synchronized (internet):  1-50ms
  NTP-synchronized (same DC):   0.1-1ms
  AWS Time Sync (same AZ):      <100 microseconds (often <50μs)
  GPS-disciplined oscillator:   <1 microsecond
  Atomic clock (lab):           nanoseconds
  Spanner TrueTime:             <1ms uncertainty interval (7ms max
                                under GPS outage with atomic backup)

WHY SKEW BREAKS DISTRIBUTED ALGORITHMS:

  LEADER LEASE (from Week 4):

    Leader holds lease until local_time > lease_expiry.
    If leader's clock is SLOW by 500ms:
      → Leader believes lease is valid 500ms longer than intended
      → Backup's clock is FAST: believes lease expired 500ms earlier
      → For 1 second window: BOTH can think they're leader
      → SPLIT BRAIN

    Mitigation: conservative lease duration >> max clock skew.
    etcd uses 15-second TTL with Raft — not wall-clock lease alone.
    FoundationDB: Clock correctness is a first-class design constraint.

  LAST-WRITER-WINS (LWW):

    Two writes to same key:
      Node A: write(v=1) at local time 1000
      Node B: write(v=2) at local time 999

    LWW picks B (999 < 1000, B wins).
    But A's write might have happened AFTER B in real causality.
    A was just on a slower clock.
    → Silent data loss of v=1

  DISTRIBUTED TRACING:

    Span on Service A: start=1000, end=1005
    Span on Service B: start=1003 (child of A)

    If B's clock is 10ms behind A:
      Child appears to START before parent.
      Jaeger/Zipkin shows "impossible" traces.
      → Debugging confusion, not usually data corruption.

  LOG ORDERING / SIEM:

    Security event on firewall: 14:32:01.500
    Auth failure on app server: 14:32:01.200

    App server clock is 400ms ahead.
    SIEM shows auth failure BEFORE firewall event.
    → Incident timeline is wrong. Investigation goes sideways.

BOUNDING SKEW (what production systems assume):

  Google Spanner: TrueTime uncertainty ε typically <1ms, max 7ms.
                commit_wait sleeps 2ε to ensure ordering.

  Cassandra:    safe-to-use clock skew for LWW: operator must ensure
                NTP; documented assumption < 1 second skew for
                tombstone gc (gc_grace_seconds default 864000s).

  etcd/Raft:      election timeout 1000-5000ms >> expected skew.
                Does not rely on wall clock for leader election.

  AWS DynamoDB:   uses internal logical clocks (vector clock variant)
                for versioning — NOT client wall clock.

  Rule of thumb: if your correctness depends on skew < X,
                 you MUST measure and alert on skew > X/2.
```

---

### 3.5 — NTP: Network Time Protocol

```
NTP (Network Time Protocol) — RFC 5905 (NTPv4)

PURPOSE: Synchronize computer clocks to UTC over a network.

ARCHITECTURE:

  Stratum 0: Reference clocks (GPS, atomic clock, radio)
             Not on the network directly.

  Stratum 1: Servers directly attached to stratum 0
             (time.google.com, time.aws.com infrastructure)

  Stratum 2: Servers that sync from stratum 1
             (your datacenter NTP pool)

  Stratum 3+: Further downstream
             (accuracy degrades with each stratum)

  Rule: NEVER sync from stratum 16 (unsynchronized) sources.

HOW NTP WORKS (simplified):

  Client sends request to server at t1 (client time)
  Server receives at t2 (server time)
  Server sends response at t3 (server time)
  Client receives at t4 (client time)

  Round-trip delay: δ = (t4 - t1) - (t3 - t2)
  Offset: θ = ((t2 - t1) + (t3 - t4)) / 2

  Client adjusts its clock toward server_time + θ
  Adjustment method:
    → SLEW: change tick rate (preferred, no backward jump)
    → STEP: jump clock instantly (when offset > step threshold,
             typically 128ms in chrony default)

  NTP uses multiple samples, discards outliers (Marzullo algorithm),
  and prefers low-jitter sources.

NTP DAEMON CHOICES:

  chrony (modern default on RHEL, Amazon Linux 2/2023, Ubuntu):
    → Faster convergence after boot (minutes vs hours for ntpd)
    → Better handling of intermittent connectivity (laptops, VMs)
    → Can sync even when network is temporarily unavailable
      (uses drift file)
    → Preferred for cloud VMs

  ntpd (classic):
    → Still used in some legacy environments
    → Slower initial sync
    → Being phased out on many distros

  systemd-timesyncd:
    → Lightweight SNTP client (not full NTP)
    → Good enough for desktop, NOT for distributed databases
    → No sophisticated filtering

  chrony vs ntpd on EC2:
    → ALWAYS use chrony for production distributed systems
    → Enable AWS Time Sync as upstream (see 3.7)

CHRONY CONFIGURATION (production baseline):

  # /etc/chrony.conf (Amazon Linux / RHEL pattern)

  # AWS Time Sync Service — link-local, stratum 1 equivalent
  server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4

  # Fallback public pool (optional, for non-AWS or redundancy)
  pool 2.amazon.pool.ntp.org iburst

  # Record drift rate for resync after reboot
  driftfile /var/lib/chrony/drift

  # Allow stepping clock on first sync if offset > 1 second
  makestep 1.0 3

  # Enable kernel RTC synchronization
  rtcsync

  # Leap second handling: chrony can notify the kernel
  leapsecmode slew

  Key settings explained:

    iburst: send burst of 4 packets on startup for fast sync
    minpoll 4 / maxpoll 4: poll every 16 seconds (2^4)
    prefer: prioritize this source when selecting best time
    makestep 1.0 3: step if offset >1s in first 3 updates
    rtcsync: keep hardware RTC aligned (helps after reboot)

VERIFICATION COMMANDS:

  # Is chrony running and synchronized?
  chronyc tracking

  # Output fields that matter:
  #   Reference ID:  A9FEA97B (169.254.169.123 = AWS Time Sync)
  #   Stratum:       1 or 2
  #   System time:   0.000000123 seconds fast of NTP time
  #   Last offset:   +0.000001456 seconds
  #   RMS offset:    0.000002000 seconds
  #   Leap status:   Normal

  # List all time sources and their quality:
  chronyc sources -v

  #   M = multiplexer source
  #   * = currently selected best source
  #   + = acceptable alternate
  #   - = discarded (high jitter, unreachable)
  #   ? = unreachable

  # Instantaneous offset from each source:
  chronyc sourcestats

  # Force immediate sync (troubleshooting only):
  chronyc makestep

NTP FAILURE MODES (operational):

  1. Symmetric NTP amplification DDoS (historical):
     → NTP monlist command abused. Modern NTP disables this.
     → Not your problem if using chrony + AWS Time Sync.

  2. Stratum 0 spoofing:
     → Attacker advertises as stratum 1 with wrong time.
     → Mitigation: authenticate NTP (NTS — Network Time Security,
       RFC 8915). AWS Time Sync on link-local is harder to spoof
       from outside the VPC.

  3. Leap second mishandling:
     → Kernel panic on leap insert (historical bugs).
     → Test leap second behavior in staging.

  4. VM freeze / live migration:
     → Clock stops during migration, jumps on resume.
     → chrony re-syncs but window of wrong time exists.
     → Applications see time gap.

  5. Container time namespace:
     → Containers share host clock by default (CLOCK_REALTIME).
     → Monotonic clocks are per-process/container in some setups.
     → Kubernetes: all pods on a node share host wall clock.
     → If host clock is wrong, ALL pods are wrong.

  6. Dual-NIC / network partition to time source:
     → chrony falls back to drift file estimation.
     → Accuracy degrades silently until network restores.
     → ALERT on chrony "Not synchronised" state.

NTP IS NECESSARY BUT NOT SUFFICIENT:

  NTP gives you: "these machines agree on civil time within ε"
  NTP does NOT give you:
    → Causal ordering across async message paths
    → Total order of concurrent events
    → Immunity to application-level timestamp misuse
    → Sub-millisecond global consistency without extra hardware
```

---

### 3.6 — Leap Seconds: The Edge Case That Breaks Assumptions

```
WHAT IS A LEAP SECOND?

  Earth's rotation is slowing. UTC is kept aligned with solar day
  by inserting an extra second — a leap second.

  Positive leap second: 23:59:59 → 23:59:60 → 00:00:00
  (one minute with 61 seconds)

  Scheduled by IERS (International Earth Rotation Service).
  Announced ~6 months in advance.
  Unpredictable in long term — can be positive, negative, or none.
  Last positive leap second: December 31, 2016.
  As of 2024: discussion of abolishing leap seconds by 2035.

WHY ENGINEERS CARE:

  Unix timestamps assume every minute has 60 seconds.
  Leap seconds break that assumption.

  During positive leap second:
    → Same Unix timestamp can occur TWICE
    → time.time() may return the same value for 2 seconds
    → Timestamps are NOT unique during leap second
    → Timers scheduled for "next second" may fire late

  If OS steps clock backward to "repeat" a second:
    → time.time() GOES BACKWARDS
    → UUID v1 (time-based) can generate duplicates
    → LWW tie-breaking breaks
    → Metrics counters appear to reset

HANDLING STRATEGIES:

  1. KERNEL INSERT (traditional):
     Linux kernel inserts leap second at UTC midnight.
     Clock reads: ...58, 59, 60, 00...
     Some applications see 61-second minute.

  2. KERNEL STEP (some configs):
     Clock paused for 1 second at boundary.
     From app's view: time "stops" for 1 second, then continues.
     Monotonic clocks unaffected.

  3. LEAP SMEARING (Google, AWS, Microsoft Azure):
     Spread the extra second over 24 hours (or window before).
     Clock runs SLOWLY (13.9μs slower per second for 24h).
     No discontinuity. No duplicate timestamps.
     No backward jump.
     BUT: during smear window, clock is deliberately WRONG vs true UTC.
     Cross-system comparison with non-smearing systems shows offset.

  AWS Time Sync leap smear:
    → Smears over 0-24 hours preceding the leap second
    → Amazon Linux chrony configured for slew mode
    → EC2 instances generally do NOT see backward jumps

  Google "leap smear":
    → Pioneered for internal systems
    → Now industry standard for hyperscalers

  4. TAI-BASED INTERNAL TIME (some databases):
     Store TAI internally, convert to UTC for display.
     Avoids leap second in internal ordering.
     Complex at API boundaries.

APPLICATION DEFENSIVE PATTERNS:

  # Never assume timestamps are unique:
  event_id = f"{timestamp_ns}:{sequence}:{node_id}"

  # Detect backward clock:
  last_ts = 0
  def next_timestamp():
      global last_ts
      now = time.time_ns()
      if now <= last_ts:
          now = last_ts + 1    # artificial increment
      last_ts = now
      return now

  # Snowflake-style IDs use sequence counter within same ms:
  # (timestamp_ms, sequence, worker_id) — handles duplicate ms

  # For TTL: use monotonic duration, not wall clock comparison:
  # WRONG: expires_at = time.time() + 3600
  #   (if clock jumps, expiry is wrong)
  # BETTER for local cache: store duration, check monotonic elapsed
  # For distributed TTL: store absolute wall time BUT accept fuzz

LEAP SECOND READINESS CHECKLIST:

  □ chrony configured with leapsecmode slew (not step)
  □ Application code does not assume time never repeats
  □ ID generation has sequence component within same second
  □ Monitoring alerts on clock step events
  □ Run chaos test: simulate clock step in staging
  □ Document whether your cloud provider smears or steps
```

---

### 3.7 — AWS Time Sync Service

```
AWS TIME SYNC SERVICE

  Endpoint:  169.254.169.123 (IPv4, link-local)
             fd00:ec2::123 (IPv6, link-local)

  Availability: All EC2 instances in all regions (no extra charge)
  Protocol: NTP (UDP port 123)
  Accuracy: Typically within 50 microseconds of UTC
            (same Availability Zone, modern instance types)
  Stratum: Effectively stratum 1 (connected to AWS reference clocks)

WHY NOT use pool.ntp.org on EC2?

  1. Latency: public NTP adds 1-50ms network jitter
     AWS Time Sync: <1ms (link-local, no internet hop)

  2. Reliability: no dependency on external internet for time
     Instance in private subnet without NAT: Time Sync still works

  3. Security: link-local not reachable from outside VPC
     Reduced attack surface vs public NTP

  4. Consistency: all instances in region use same reference
     Minimizes inter-instance skew

SETUP (Amazon Linux 2023 / AL2):

  # Install chrony (usually pre-installed)
  sudo yum install chrony -y

  # Edit /etc/chrony.conf — ADD (or replace pool lines):
  server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4

  # Remove or comment out generic pool.ntp.org lines
  # (keep as fallback only if you want redundancy)

  sudo systemctl enable chronyd
  sudo systemctl restart chronyd

  # Verify:
  chronyc sources -v
  # Should show 169.254.169.123 as ^* (selected source)

  chronyc tracking
  # System time: should be sub-millisecond offset

AMAZON TIME SYNC ENGINEERING (EC2):

  Instance metadata does NOT expose clock offset directly.
  You monitor via chrony on the host.

  For containers on EC2:
    → Containers inherit host CLOCK_REALTIME
    → Configure chrony on the HOST (or use DaemonSet in K8s)
    → Do NOT run chrony inside every container

EKS / KUBERNETES PATTERN:

  # DaemonSet: one chrony-monitor pod per node
  # OR: rely on host chrony + node_exporter metric

  # node_exporter exposes ntp collector (if enabled):
  # node_timex_offset_seconds — clock offset from NTP
  # node_timex_sync_status — 1 if synchronized

  # Alert:
  # node_timex_offset_seconds > 0.001 for 5m → page
  # node_timex_sync_status == 0 for 2m → page

AWS SERVICES AND TIME:

  DynamoDB:        internal versioning, Hybrid Logical Clock
  S3:              LastModified from server clock (authoritative)
  RDS:             PostgreSQL/Cassandra clock is YOUR responsibility
  Aurora:          Same — configure chrony on instances
  MSK (Kafka):     Broker log ordering uses offset, not wall clock
  CloudWatch:      Timestamps are server-side (AWS clock)
  X-Ray:           Trace timestamps from AWS infrastructure
  EventBridge:     Schedule expressions use UTC (AWS-managed)

  CRITICAL: AWS manages time for MANAGED SERVICE operations.
            YOU manage time for code running on EC2, ECS, EKS, Lambda.

  Lambda:
    → No chrony access (managed runtime)
    → AWS maintains host clock
    → Assume sub-ms skew within region for practical purposes
    → Do NOT assume cross-region Lambda timestamps are ordered

CROSS-REGION CLOCK SKEW:

  us-east-1 and eu-west-1 EC2 instances both using regional
  Time Sync: typically <1ms skew between regions.
  Good enough for: logging, metrics, human-facing timestamps.
  NOT good enough for: distributed consensus without protocol.

  Spanner multi-region: uses TrueTime hardware, not just NTP.
  Your app on EC2: use logical ordering for correctness.
```

---

### 3.8 — Why Distributed Systems Cannot Rely on Wall Clock

```
THE FORMAL ARGUMENT:

  Lamport (1978) proved: you cannot deduce ordering of distributed
  events from physical timestamps alone, unless you have perfect
  synchronization (which is physically impossible at scale).

  Proof sketch:
    Message m takes time d to travel (d > 0).
    Event A on node P at physical time T.
    Event B on node Q at physical time T + d/2.
    But B could be a REPLY to A — meaning A → B causally.
    Q's clock might say B happened BEFORE A.
    Physical timestamps contradict causality.

THE PRACTICAL ARGUMENT (production):

  1. CLOCKS DISAGREE
     Even with NTP, residual skew is non-zero.
     Any algorithm where correctness requires skew < ε must
     MEASURE ε and have a plan when ε is exceeded.

  2. CLOCKS GO BACKWARD
     NTP step, leap second, admin date -s, VM migration.
     Any code assuming time is strictly increasing will break.

  3. CONCURRENT EVENTS HAVE NO ORDER
     Two writes on two nodes with no message path between them
     are CONCURRENT. No wall clock can assign them a correct
     total order without external coordination.

  4. LATENCY ≠ TIME
     Event A timestamped earlier than B might have been CAUSED by B
     if the timestamp was assigned before A's processing completed
     (queueing delay). Timestamp marks receipt, not causation.

  5. USER-FACING TIME ZONES
     Wall clock includes timezone/DST complexity.
     Store UTC. Convert at display. DST jumps cause 1-hour
     "backward" moves in local time — never use local time internally.

WHAT WALL CLOCK IS STILL GOOD FOR:

  ✓ Audit logs humans read ("transaction at 2024-03-15 14:32 UTC")
  ✓ Certificate/TLS validity (notBefore, notAfter)
  ✓ JWT/OAuth expiry (exp claim)
  ✓ Cron schedules and business-hour logic
  ✓ Metrics and dashboards (approximate ordering is fine)
  ✓ TTL with fuzz factor (cache expires "about 5 minutes")
  ✓ Debugging ("correlate logs from two systems roughly")

WHAT WALL CLOCK IS BAD FOR:

  ✗ Deciding which of two concurrent writes wins (use CRDT, version
    vector, or consensus)
  ✗ Distributed locking without fencing tokens
  ✗ Exactly-once deduplication across nodes (use idempotency keys
    with logical sequence)
  ✗ Cross-node timeout coordination (use protocol heartbeats)
  ✗ Ordering events for correctness (use happens-before, log
    sequence numbers, or consensus)
  ✗ Leader election alone (use Raft/etcd, not "lowest timestamp wins")

THE DDIA RULE (Kleppmann):

  "In a distributed system, a timestamp from a clock is only
   as trustworthy as the clock itself."

  Process clocks can be wrong. Use:
    → Monotonic clocks for durations (single process)
    → Logical clocks for ordering (distributed)
    → TrueTime / HLC when you need both (hybrid)
    → Consensus (Raft/Paxos) when you need agreement
```

---

### 3.9 — Happens-Before: The Causal Partial Order

```
HAPPENS-BEFORE (→) — Lamport's relation

  Defined WITHOUT any clock. Defined by program structure and
  message flow.

RULES (axioms):

  1. PROGRAM ORDER (same process):
     If events A and B occur in the same process, and A comes
     before B in the program, then A → B.

  2. SEND-RECEIVE (message):
     If event A is "send message M" on process P, and event B is
     "receive message M" on process Q, then A → B.

  3. TRANSITIVITY:
     If A → B and B → C, then A → C.

  4. IRREFLEXIVITY:
     A ↛ A (an event does not happen before itself)

CONCURRENT EVENTS:

  If A ↛ B AND B ↛ A, then A and B are CONCURRENT.
  Neither causally influenced the other.
  Physical clocks may assign them an order, but that order is
  ARBITRARY — not meaningful for correctness.

EXAMPLE:

  Process P          Process Q          Process R
  ─────────          ─────────          ─────────
  A: x = 1
  B: send(m1) ──────────► C: recv(m1)
                          D: y = 2
                          E: send(m2) ──────► F: recv(m2)
  G: x = 3

  A → B (program order)
  B → C (send-receive)
  C → D (program order)
  D → E (program order)
  E → F (send-receive)

  Therefore: A → F (transitivity)

  G is on P. Is G → F? NO. G is concurrent with B, C, D, E, F.
  (G happens after B on P, but B → F, so actually B → G? 
   Wait — A → B and G is after B on P, so B → G by program order.
   And B → F by transitivity. So B → G and B → F, but G and F
   are NOT ordered relative to each other — G and F are CONCURRENT.)

  Correct analysis:
    A → B → G (program order on P)
    B → C → D → E → F (message chain)
    G ↛ F and F ↛ G (CONCURRENT)

VISUAL (space-time diagram):

  P │ A──B────────────────G
    │    \
    │     \ m1
    │      \
  Q │       C──D──E
    │              \
    │               \ m2
    │                \
  R │                 F

  Solid lines = program order (→)
  Dashed arrows = message flow (→)
  G and F have no path between them = CONCURRENT

WHY HAPPENS-BEFORE MATTERS:

  CONSISTENCY MODELS are defined using happens-before:
    → Causal consistency: reads respect happens-before
    → Read-your-writes: your write → your subsequent read
    → Sequential consistency: all ops in order consistent with →

  CONFLICT DETECTION:
    Two writes to same object without happens-before between them
    = CONFLICT (concurrent writes). Must merge or reject.

  DISTRIBUTED TRACING:
    Span parent-child encodes happens-before.
    Critical path analysis follows → chains.

  LOG REPLICATION:
    Raft log index provides total order WITHIN a partition.
    Happens-before across partitions requires vector clocks (T2).

HAPPENS-BEFORE ≠ PHYSICAL TIME ORDER:

  Real time:  A at 12:00:00.100,  F at 12:00:00.050
  Physical order says F before A.
  Causal order says A → F (A is send, F is receive chain).
  PHYSICAL TIME IS WRONG HERE (clock skew on R).

  This is not a corner case. This is NORMAL in distributed systems.
  Design for happens-before. Use physical time only as hint.
```

---

### 3.10 — TrueTime: Google's Answer to Wall-Clock Untrustworthiness

```
TRUETIME (Google Spanner, OSDI 2012)

PROBLEM SPANNER SOLVED:
  Globally distributed SQL with EXTERNAL CONSISTENCY
  (= linearizability — see Week 3 Topic 2).
  Linearizability is defined using real-time order.
  How do you achieve real-time order without perfect clocks?

TRUETIME API:

  TT.now() → TTinterval {
      earliest: Timestamp   // lower bound on true UTC
      latest:   Timestamp   // upper bound on true UTC
  }

  True time is GUARANTEED to be within [earliest, latest].
  Width of interval = UNCERTAINTY ε.
  Typical ε: <1ms. Maximum ε under GPS outage: 7ms.

TRUETIME IMPLEMENTATION:

  Per datacenter Time Master:
    → GPS receivers (4+ antennas, multipath rejection)
    → Atomic clocks (GPS-disciplined, holdover during GPS outage)
    → Armageddon master: holds atomic clock only (no GPS)
      for disaster scenarios

  Time Slave daemons on every machine:
    → Query Time Masters over network
    → Maintain local clock synchronized to masters
    → Expose TT.now() to applications

  Uncertainty ε computed from:
    → GPS signal quality
    → Time since last GPS sync
    → Atomic clock drift rate since sync
    → Network delay to Time Master

COMMIT-WAIT PROTOCOL:

  When Spanner commits a transaction at commit timestamp s:

  1. Transaction completes, assigned commit timestamp s = TT.now().latest
  2. COMMIT WAIT: sleep until TT.now().earliest > s
     (i.e., wait until ALL clocks in the system are past s)
  3. Only THEN acknowledge commit to client
  4. All reads with read timestamp t ≥ s will see this write

  Why this works:
    If commit ACK after wait, true time has advanced past s everywhere.
    No reader can observe state "before" the commit in real time.
    → External consistency (linearizability) achieved.

  Cost:
    Every write pays commit-wait latency ≈ 2ε (typically 2-14ms).
    Spanner trades WRITE LATENCY for global consistency without
    a single global leader.

TRUETIME AND SNAPSHOT ISOLATION:

  Spanner assigns every transaction a commit timestamp from TrueTime.
  Serializable ordering: transactions appear in commit-timestamp order.
  If TT interval overlaps detect conflict:
    → Spanner uses two-phase commit + Paxos per shard
    → Conflicting transactions: later commit timestamp wins
    → TrueTime provides global timestamp source

COMPARISON TO ALTERNATIVES:

  ┌──────────────────┬──────────────────────────────────────────────┐
  │ Approach         │ Tradeoff                                     │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ TrueTime         │ Hardware cost (GPS+atomic), commit-wait      │
  │ (Spanner)        │ latency, but TRUE external consistency       │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ HLC (CockroachDB,│ No special hardware. Clock skew assumed      │
  │  YugabyteDB)     │ <250ms. Smaller wait (1-25ms). "External     │
  │                  │ consistency" with bounded clock error.       │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ Raft log index   │ Total order per shard. Cross-shard needs     │
  │ (etcd, TiKV)     │ 2PC or Percolator-style timestamps.          │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ Lamport clocks   │ Causal order only. No real-time guarantee.   │
  │ (theory)         │ Cannot implement linearizability alone.      │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ LWW wall clock   │ Simple. WRONG under skew. Silent data loss.  │
  │ (naive)          │                                              │
  └──────────────────┴──────────────────────────────────────────────┘

TRUETIME LIMITATIONS:

  → Requires specialized hardware deployment (not available on
    vanilla EC2)
  → 7ms max uncertainty under GPS failure — commit-wait up to 14ms
  → Not immune to Byzantine clock failures (assumes Time Master honest)
  → You cannot "install TrueTime" on a random microservices app
  → Application must be designed to USE uncertainty intervals

COCKROACHDB'S HLC (practical alternative on commodity hardware):

  Hybrid Logical Clock = physical time + logical counter

  HLC_timestamp = (physical_time, logical_counter)

  On send: HLC = max(local_HLC, msg_HLC) + increment logical
  Preserves happens-before: if A → B, then HLC(A) < HLC(B)
  Does NOT require GPS. Assumes max clock skew bound.

  max_offset setting (default 250ms):
    If local clock is more than 250ms behind another node,
    operations wait for clock to catch up.
    → Similar spirit to commit-wait, software-only.

  Lesson: TrueTime is the gold standard WITH hardware.
  HLC is the pragmatic approximation on AWS EC2.
```

---

### 3.11 — Hybrid Logical Clocks (HLC) Preview

```
HLC bridges physical and logical clocks — included here because
it's what you'll actually deploy on AWS (not TrueTime hardware).

STRUCTURE: HLC = (pt, lc)
  pt = physical time (milliseconds, wall clock)
  lc = logical counter (handles same-pt events)

MERGE RULE (on receive message with HLC_m):

  pt_local = wall_clock_ms()
  pt_new = max(pt_local, pt_msg)
  lc_new = max(lc_local, lc_msg) + 1   if pt_new == pt_local == pt_msg
           max(lc_local, lc_msg)        if pt_new > pt_local or pt_msg
           lc_local + 1                 if pt_new == pt_local > pt_msg
  (full rules in Kulkarni et al. 2014 paper)

PROPERTIES:
  → If A → B (happens-before), then HLC(A) < HLC(B)
  → Preserves causality (like Lamport clocks)
  → Stays close to physical time (unlike pure Lamport)
  → Bounded drift from physical time if clocks synchronized

COCKROACHDB EXAMPLE:

  -- Cluster setting
  SET CLUSTER SETTING kv.closed_timestamp.target_duration = '3s';

  -- Max clock offset between nodes (default 250ms)
  -- If exceeded: node crashes rather than serve inconsistent data
  SET CLUSTER SETTING server.time_until_store_dead = '30s';

  CockroachDB refuses to run if clock skew exceeds max_offset.
  This is a FEATURE: fail loud rather than corrupt silently.

  Compare to Cassandra LWW: silently picks wrong winner under skew.
  CockroachDB: refuses to start or kills node.

OPERATIONAL IMPLICATION:

  On AWS: chrony + Time Sync → skew typically <1ms.
  HLC max_offset 250ms gives enormous margin.
  But: if chrony breaks on one node, CockroachDB detects and
  isolates it. YOU must fix chrony. The database won't hide it.
```

---

## Concrete Examples

### 4.1 — Snowflake IDs: Wall Clock With Defensive Sequencing

```
TWITTER SNOWFLAKE (and variants: Sonyflake, Baidu UidGenerator)

STRUCTURE (64 bits):
  | 1 bit unused | 41 bits timestamp ms | 10 bits machine ID | 12 bits sequence |

  timestamp: milliseconds since custom epoch (wall clock)
  machine ID: datacenter + worker (assigned at deploy)
  sequence: incremented within same millisecond

WHY SEQUENCE EXISTS:

  Same millisecond on same worker → sequence increments.
  Handles:
    → Multiple IDs generated in one ms
    → Leap second duplicate timestamps
    → Brief clock backward step (if ts < last_ts, wait or error)

CLOCK BACKWARD HANDLING (Twitter's approach):

  if current_timestamp < last_timestamp:
      # Clock moved backward — refuse to generate IDs
      # until clock catches up to last_timestamp
      raise ClockMovedBackwardsException

  Production impact:
    → Brief ID generation outage during NTP step
    → Better than duplicate IDs

AWS ALTERNATIVE — NO WALL CLOCK:

  DynamoDB does not use Snowflake. Uses internal UUID/version.
  For app-level IDs on EC2 without coordination:
    → ULID: lexicographically sortable, 48-bit timestamp + random
    → UUID v7: timestamp-based with random component (RFC draft)
    → Database sequence (RDS, or dedicated ID service)

  ULID example:
    01ARZ3NDEKTSV4RRFFQ69G5FAV
    │└── random ──┘└─ timestamp (ms) ─┘
    Sortable by generation time (approximate order).
    NOT guaranteed causal order across nodes.
```

---

### 4.2 — Cassandra LWW: When Wall Clock Loses Data

```
CASSANDRA CONFLICT RESOLUTION (last-write-wins):

  Each cell stores: (value, timestamp, ttl)
  timestamp = client-supplied OR server wall clock at write time

  On read conflict (multiple replicas disagree):
    Pick cell with HIGHEST TIMESTAMP.
    Tie-break: lexicographically largest value (arbitrary).

CLOCK SKEW SCENARIO:

  Node A (clock ahead 500ms):
    write(user.balance = 100, ts=T+500)

  Node B (correct clock):
    write(user.balance = 50, ts=T)
    (This write happened 200ms AFTER A's in real time)

  LWW winner: A (ts=T+500 > T)
  Result: balance = 100
  Reality: B's write was later. Correct balance might be 50.

  Data loss: B's write silently discarded.

CASSANDRA MITIGATIONS:

  1. NTP everywhere (operator responsibility)
  2. gc_grace_seconds: tombstones kept for 10 days default
     (handles deleted-then-resurrected under skew)
  3. Lightweight transactions (LWT) — Paxos, not LWW
     for compare-and-set operations
  4. Application-level version vectors (bring your own)

  # LWT example (linearizable compare-and-set):
  UPDATE accounts SET balance = 50
  IF balance = 100;
  # Uses Paxos — not subject to LWW timestamp ordering

LESSON: Cassandra's default LWW trusts YOUR clocks.
       Chrony on every node is not optional — it's correctness-critical.
```

---

### 4.3 — etcd/Raft: Ordering Without Wall Clock

```
ETCD / RAFT — LOG INDEX AS LOGICAL CLOCK

  Each entry in Raft log: (index, term, command)
  index: monotonically increasing integer (1, 2, 3, ...)
  term: logical epoch (increments on each election)

  TOTAL ORDER within a Raft group:
    index 5 happened before index 6. Always. On all nodes.
    No wall clock involved.

LEADER ELECTION — NOT "lowest timestamp wins":

  Randomized election timeout (150-300ms).
  Candidate requests votes. Majority wins.
  Term number breaks ties (higher term wins).
  Log completeness breaks ties (more up-to-date log wins).

  Wall clock used ONLY for election timeout DURATION measurement.
  Measured with monotonic clock internally.
  NOT used for ordering or leader selection.

LEASE (etcd) — WHERE WALL CLOCK APPEARS:

  etcd grants lease with TTL (e.g., 15 seconds).
  Lease renewed by heartbeat before expiry.
  If lease expires: associated keys deleted.

  Clock skew risk:
    → Slow clock on leader: holds lease longer
    → Fast clock on follower: thinks lease expired early

  Mitigation:
    → TTL >> max expected skew (15s >> 1ms typical skew)
    → Raft consensus for actual leader determination
    → Lease is optimization for key expiry, not sole leader lock

  For distributed locking: use fencing tokens (Week 4).
  Wall-clock lease alone is insufficient.
```

---

### 4.4 — CDN Age Header: Wall Clock at the Edge

```
FROM WEEK 1 — CDN CACHE AGE:

  CloudFront response header:
    Date: Mon, 15 Mar 2024 14:32:00 GMT      (origin/edge time when cached)
    Age:  847                                   (seconds since Date)

  Age = edge_wall_clock_now - Date

CLOCK SKEW EFFECT:

  Edge node clock 5 seconds AHEAD of origin:
    Age appears 5 seconds larger than reality
    → Cache seems "older" than it is
    → May trigger revalidation earlier (minor impact)

  Edge node clock 5 seconds BEHIND:
    Age appears smaller
    → Cache seems "fresher"
    → Stale content served longer past true TTL

  Origin Date header wrong (app server clock skew):
    All Age calculations wrong across entire CDN.
    → Systematic early/late expiry

MITIGATION:

  → NTP on origin servers (chrony + AWS Time Sync)
  → CDN providers run NTP on edge (their responsibility)
  → For critical TTL: use short max-age + stale-while-revalidate
  → Do not use Age header for application correctness logic
```

---

### 4.5 — PostgreSQL: Timestamps and Transaction IDs

```
POSTGRESQL TIME SOURCES:

  now() / CURRENT_TIMESTAMP:
    → Transaction start time (stable within transaction)
    → Wall clock at transaction begin
    → Same value for all statements in one transaction

  clock_timestamp():
    → Actual current wall clock (changes during transaction)

  statement_timestamp():
    → Wall clock when current statement received

  pg_current_xact_id():
    → Transaction ID (logical, monotonic within cluster)
    → Used for vacuum, visibility — NOT wall clock

TIMESTAMP COLUMNS:

  TIMESTAMP WITH TIME ZONE (timestamptz):
    → Stored as UTC internally
    → Correct choice for all application timestamps
    → Display converts to session timezone

  TIMESTAMP WITHOUT TIME ZONE:
    → Dangerous in distributed systems
    → "2024-03-15 14:32:00" — which timezone?
    → Never use for cross-region apps

REPLICATION AND ORDERING:

  WAL LSN (Log Sequence Number):
    → Physical position in write-ahead log
    → Total order of writes on ONE primary
    → Logical replication uses LSN for cursor position
    → Cross-region: LSN orders events, not wall clock

  Read replica lag measurement:
    pg_last_xact_replay_timestamp() on replica
    now() - pg_last_xact_replay_timestamp() = lag time

    Uses wall clock for LAG MEASUREMENT (observability).
    Correctness uses LSN comparison, not timestamp.
```

---

### 4.6 — DynamoDB: Version Numbers and Hybrid Logical Time

```
DYNAMODB INTERNAL VERSIONING:

  Each item has internal version stamp (not exposed as wall clock).
  Conditional writes:
    UpdateItem with ConditionExpression:
      attribute_not_exists(pk) OR version = :expected

  Optimistic locking — version is logical, server-assigned.
  Client wall clock NEVER enters conflict resolution.

  ConditionalCheckFailedException = concurrent write detected.
  Application must retry with fresh read.

DYNAMODB STREAMS ORDERING:

  Records within same partition key: TOTAL ORDER (by sequence number).
  Across partition keys: NO ORDER GUARANTEE.
  Sequence number is logical — monotonic per shard.

  EventBridge Pipes / Lambda consumer:
    → Process records in sequence number order per shard
    → Do NOT use ApproximateCreationDateTime for ordering
      (it's approximate wall clock — hint only)

GLOBAL TABLES:

  Multi-region replication: last-writer-wins at attribute level
  using internal versioning — NOT client timestamps.
  Clock skew between regions handled by DynamoDB service layer.
  You cannot override with client-supplied timestamp for ordering.
```

---

### Staff

## Production Patterns

### 5.1 — The Chrony Baseline (Every EC2 Fleet)

```
MANDATORY FOR ANY DISTRIBUTED SYSTEM ON AWS:

  1. chrony installed and enabled on every EC2 instance
  2. server 169.254.169.123 prefer iburst in chrony.conf
  3. Alert on offset > 1ms sustained or sync lost
  4. Ansible/Terraform/SSM enforcement — not manual setup

TERRAFORM USER-DATA EXAMPLE:

  #!/bin/bash
  yum install -y chrony
  cat > /etc/chrony.conf << 'EOF'
  server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4
  driftfile /var/lib/chrony/drift
  makestep 1.0 3
  rtcsync
  leapsecmode slew
  logdir /var/log/chrony
  EOF
  systemctl enable chronyd
  systemctl restart chronyd

SSM ASSOCIATION (ongoing compliance):

  # AWS Systems Manager State Manager document
  # Runs daily: verify chrony active, offset < 1ms
  # Remediate: restart chronyd if drift detected

KUBERNETES NODE REQUIREMENT:

  # Admission policy or DaemonSet check
  # node_timex_offset_seconds from node_exporter
  # Taint node if clock unsynchronized
```

---

### 5.2 — Timestamp Storage Patterns

```
DATABASE SCHEMA RULES:

  -- ALWAYS store UTC
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

  -- NEVER store local timezone in DB
  -- NEVER use TIMESTAMP WITHOUT TIME ZONE for distributed data

  -- For ordering within service: use BIGSERIAL or UUID v7
  event_sequence BIGSERIAL PRIMARY KEY
  event_time TIMESTAMPTZ NOT NULL  -- informational, not ordering key

APPLICATION LOGGING:

  Structured JSON logs:
  {
    "timestamp": "2024-03-15T14:32:01.123Z",   // ISO 8601 UTC
    "monotonic_ns": 18446744073709551615,       // optional, same host only
    "trace_id": "abc123",                       // cross-service ordering
    "span_id": "def456",
    "event": "payment_processed"
  }

  Cross-service ordering: use trace_id + span parent chain.
  NOT log timestamp string comparison.

API DESIGN:

  # WRONG: client sends timestamp, server trusts it for ordering
  POST /events { "time": 1710505921, "data": "..." }

  # RIGHT: server assigns timestamp at receipt
  POST /events { "data": "..." }
  Response: { "id": "evt_01HQ...", "server_time": "2024-03-15T14:32:01Z" }

  # RIGHT: client sends logical version
  PUT /resource { "version": 42, "data": "..." }
  Condition: If-Match: "version-42"
```

---

### 5.3 — Distributed Locking With Clock Awareness

```
ANTI-PATTERN: Redis lock with wall-clock TTL only

  SET lock:resource1 token:abc EX 30 NX
  # Holder believes lock valid for 30 seconds
  # If holder clock slow: holds past intended expiry
  # If contender clock fast: steals lock while holder still working

CORRECT PATTERN: Fencing token (from Week 4)

  1. Acquire lock with TTL (best-effort mutual exclusion)
  2. Lock value = monotonically increasing fencing token
     (from database sequence or dedicated counter)
  3. Before ANY write to shared resource:
     Check fencing token > last_seen_token for this resource
  4. Storage rejects stale writes even if lock was "stolen"

  # Pseudo-code
  token = redis.incr("fencing:resource1")
  if redis.set("lock:resource1", token, nx=True, ex=30):
      storage.write(resource1, data, min_token=token)
      # storage layer: reject if min_token < resource1.last_token

LEASE DURATION RULE:

  lease_ttl >= 10 * max_clock_skew + max_operation_duration

  If max_skew = 250ms (CockroachDB assumption), op = 5s:
    lease_ttl >= 10 * 0.25 + 5 = 7.5s → use 15s minimum

  etcd default 15s lease with typical <1ms skew: enormous margin.
  That's intentional engineering.
```

---

### 5.4 — Idempotency Keys vs Timestamps

```
PAYMENT / WRITE DEDUPLICATION:

  WRONG:
    dedupe_key = f"{user_id}:{timestamp_ms}"
    # Clock skew → duplicate keys for same logical operation
    # Clock backward → key collision with different operation

  RIGHT:
    dedupe_key = client_generated_uuid  # client assigns once
    # Server stores: idempotency_key → response mapping
    # TTL on mapping: 24 hours (wall clock OK for expiry)
    # Ordering: first-seen wins (server receive order)

  Stripe API pattern:
    Idempotency-Key: uuid-v4 (client supplied)
    Server stores result for 24 hours.
    Duplicate request with same key → return cached response.
    No timestamp in key.
```

---

### 5.5 — Metrics and Observability Timestamps

```
PROMETHEUS:

  scrape_timestamp: when Prometheus server scraped (Prometheus clock)
  sample timestamp: optional, usually NOT set by exporters
  → Metrics ordering: scrape interval order, not sample time

  For event logging in metrics (rare):
    use created timestamp label — informational only

CLOUDWATCH:

  PutMetricData with Timestamp parameter:
    → If not specified: uses CloudWatch server time (authoritative)
    → If specified: must be within 2 weeks of now
    → Do NOT use client wall clock from EC2 unless chrony verified

DISTRIBUTED TRACING (OpenTelemetry):

  Span start/end: recorded by SDK at span creation/close
  Uses wall clock — traces can show impossible parent-child order

  Mitigation:
    → Jaeger adjusts for clock skew in UI (optional)
    → Design reviews: don't use trace timestamps for billing
    → Use span duration (monotonic on same host) for latency

  Trace context propagation (W3C traceparent):
    Ordering via trace/span IDs — not timestamps
```

---

## Failure Modes

```
╔═════════════════════════════════════════════════════════════════╗
║   FAILURE MODE #1: LEASE SPLIT-BRAIN (CLOCK SKEW)               ║
╠═════════════════════════════════════════════════════════════════╣
║                                                                 ║
║   System: Custom leader election using Redis TTL lock           ║
║   Lock TTL: 10 seconds                                          ║
║   Clock skew: Node A slow 8s, Node B fast 8s (extreme NTP       ║
║   failure — 16 second effective disagreement)                   ║
║                                                                 ║
║   Timeline:                                                     ║
║   T+0:  Node A acquires lock, begins processing                 ║
║   T+10: Node B's clock says lock expired (A still believes      ║
║         2 seconds remain)                                       ║
║   T+10: Node B acquires lock, begins processing                 ║
║   T+10 to T+12: BOTH nodes believe they are leader              ║
║         → duplicate writes, conflicting state                   ║
║                                                                 ║
║   Root cause: Wall-clock lease without fencing token.           ║
║   Clock skew exceeded TTL safety margin.                        ║
║                                                                 ║
║   Fix:                                                          ║
║   → Fencing tokens on all writes                                ║
║   → Use etcd/Consul/Raft for leader election (not raw TTL)      ║
║   → Alert on chrony offset > 100ms                              ║
║   → lease_ttl >> max_skew (10x minimum)                         ║
╠═════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #2: LWW SILENT DATA LOSS                         ║
╠═════════════════════════════════════════════════════════════════╣
║                                                                 ║
║   System: Multi-region Cassandra, active-active writes          ║
║   Conflict resolution: last-write-wins (default)                ║
║                                                                 ║
║   us-east-1 node clock: +300ms ahead (chrony broken 3 days)     ║
║   eu-west-1 node clock: correct (chrony healthy)                ║
║                                                                 ║
║   User updates profile bio in EU at T (real time).              ║
║   User updates avatar metadata in US at T+100ms (real time).    ║
║   US write gets timestamp T+400ms (clock ahead).                ║
║   EU write gets timestamp T.                                    ║
║   LWW: US write wins for ALL fields in row (not just avatar).   ║
║   EU bio update silently lost.                                  ║
║                                                                 ║
║   Root cause: Row-level LWW with divergent clocks.              ║
║   No per-field versioning. No LWT.                              ║
║                                                                 ║
║   Fix:                                                          ║
║   → Fix chrony immediately (P0)                                 ║
║   → Per-field version vectors or CRDTs for concurrent fields    ║
║   → LWT for critical updates                                    ║
║   → Monitor NTP on all Cassandra nodes (metric + alert)         ║
╠═════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #3: DUPLICATE SNOWFLAKE IDs                      ║
╠═════════════════════════════════════════════════════════════════╣
║                                                                 ║
║   System: Order ID service using Snowflake-style generation     ║
║   Event: NTP step correction — clock moved BACK 500ms           ║
║                                                                 ║
║   Before step: generating IDs at ts=1710505921500, seq=0..4095  ║
║   After step:  clock now says ts=1710505921000                  ║
║   Generator: waits until ts catches up (500ms stall)            ║
║   OR (buggy impl): reuses ts=1710505921000, seq=0 again         ║
║   → DUPLICATE order IDs                                         ║
║   → Two orders map to same ID in database                       ║
║   → Payment charged once, two shipments                         ║
║                                                                 ║
║   Root cause: Snowflake generator without backward-clock        ║
║   handling; or sequence reset on same timestamp.                ║
║                                                                 ║
║   Fix:                                                          ║
║   → Wait for clock catch-up (Twitter pattern)                   ║
║   → Or: include sequence that never resets within process       ║
║     lifetime (monotonic counter independent of clock)           ║
║   → Database UNIQUE constraint on order_id (detect, not prevent)║
║   → chrony leapsecmode slew (avoid steps)                       ║
╠═════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #4: LOG COMPACTION "TIME TRAVEL"                 ║
╠═════════════════════════════════════════════════════════════════╣
║                                                                 ║
║   System: Kafka with log retention by timestamp                 ║
║   Broker clock jumps BACK 1 hour (manual admin error)           ║
║                                                                 ║
║   log.retention.ms = 7 days                                     ║
║   Compaction thinks messages from "future" exist                ║
║   After clock step back: ALL messages appear 1 hour "old"       ║
║   → Premature deletion of recent messages                       ║
║   → Consumers miss events                                       ║
║   OR: messages timestamped "in future" retained forever         ║
║   → Disk fills                                                  ║
║                                                                 ║
║   Root cause: Retention policy trusts broker wall clock.        ║
║                                                                 ║
║   Fix:                                                          ║
║   → chrony + alert on step events                               ║
║   → Prefer log.retention.bytes as safety bound                  ║
║   → Kafka: retention by LOG OFFSET for critical topics          ║
║   → Message timestamp = CreateTime (broker) not LogAppendTime   ║
║     unless producer timestamps trusted (they shouldn't be)      ║
╠═════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #5: IMPOSSIBLE DISTRIBUTED TRACES                ║
╠═════════════════════════════════════════════════════════════════╣
║                                                                 ║
║   System: 20 microservices, OpenTelemetry tracing               ║
║   Symptom: Jaeger shows child span STARTING before parent       ║
║                                                                 ║
║   Service A (offset -50ms): parent span start=1000, end=1050    ║
║   Service B (offset +100ms): child span start=990               ║
║                                                                 ║
║   Child appears 10ms before parent start.                       ║
║   Engineers waste hours investigating "time travel requests."   ║
║                                                                 ║
║   Root cause: 150ms clock skew between services.                ║
║   Not a request ordering bug — observability artifact.          ║
║                                                                 ║
║   Fix:                                                          ║
║   → chrony on all nodes (eliminate 150ms skew)                  ║
║   → Jaeger clock skew adjustment (configurable)                 ║
║   → Document: trace timestamps are approximate                  ║
║   → Use span duration within same service (monotonic)           ║
╠═════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #6: JWT "NOT YET VALID" AFTER CLOCK STEP         ║
╠═════════════════════════════════════════════════════════════════╣
║                                                                 ║
║   System: API authentication with JWT (nbf, exp claims)         ║
║   Event: Server clock stepped FORWARD 30 seconds (NTP catch-up) ║
║                                                                 ║
║   Token issued at real T with nbf=T, exp=T+3600                 ║
║   Server clock now T+30                                         ║
║   Token appears issued 30 seconds "in the past" — OK            ║
║                                                                 ║
║   Opposite: clock stepped BACK 30 seconds:                      ║
║   Valid tokens rejected: "token not yet valid" (nbf in future)  ║
║   All users logged out. P1 incident.                            ║
║                                                                 ║
║   Root cause: Strict JWT nbf validation vs clock step.          ║
║                                                                 ║
║   Fix:                                                          ║
║   → chrony slew instead of step (makestep threshold tuning)     ║
║   → JWT validation leeway: 30-60 seconds (PyJWT leeway param)   ║
║   → Monitor chrony offset                                       ║
╠═════════════════════════════════════════════════════════════════╣
║   FAILURE MODE #7: CRON DOUBLE-FIRE OR MISSED FIRE              ║
╠═════════════════════════════════════════════════════════════════╣
║                                                                 ║
║   System: Kubernetes CronJob, schedule "0 * * * *" (hourly)     ║
║   Event: Node clock steps backward 5 minutes after DST bug      ║
║                                                                 ║
║   Cron controller sees time "go back" — may fire job again      ║
║   OR: clock jumps forward — skips an hour                       ║
║   Financial reconciliation job runs twice / not at all.         ║
║                                                                 ║
║   Root cause: Cron assumes monotonic wall clock progression.    ║
║                                                                 ║
║   Fix:                                                          ║
║   → Use UTC for all cron schedules (never local TZ)             ║
║   → Idempotent job design (safe to run twice)                   ║
║   → Distributed cron: use leader election + logical schedule    ║
║     (run job N after previous completion, not wall clock)       ║
║   → chrony slew mode                                            ║
╚═════════════════════════════════════════════════════════════════╝
```

---

## SRE Diagnostic Toolkit
### 7.1 — Chrony Health Checks

```bash
# ── QUICK HEALTH CHECK (run on any suspect node) ──────────────

# 1. Is chronyd running?
systemctl is-active chronyd
# Expected: active

# 2. Tracking summary — THE most important command
chronyc tracking
# Healthy output:
#   Reference ID    : A9FEA97B (169.254.169.123)
#   Stratum         : 1
#   System time     : 0.000000045 seconds fast of NTP time
#   Last offset     : +0.000000123 seconds
#   RMS offset      : 0.000000200 seconds
#   Leap status     : Normal

# 3. Source list with selection state
chronyc sources -v
# ^* = selected source (should be 169.254.169.123 on AWS)
# ^? = unreachable (BAD — investigate network/firewall)

# 4. Per-source statistics
chronyc sourcestats
# Std Dev should be < 1ms on AWS

# 5. Check if clock would step on next sync
chronyc -a dump
```

```bash
# ── ALERT THRESHOLDS (Prometheus / CloudWatch Agent) ───────────

# node_exporter NTP collector (enable with --collector.timex)
# node_timex_offset_seconds         → alert if abs() > 0.001 for 5m
# node_timex_sync_status            → alert if == 0 for 2m
# node_timex_maxerror_seconds       → alert if > 0.016 (16ms)

# Custom chrony check script for CloudWatch:
OFFSET=$(chronyc tracking | awk '/Last offset/ {print $4}')
# Push as custom metric: ClockOffsetSeconds

# chrony text export for automation:
chronyc -c tracking    # CSV format for scripts
```

```bash
# ── CROSS-NODE SKEW MEASUREMENT ───────────────────────────────

# From a bastion, compare all app nodes:
for host in app-{1..5}.internal; do
  offset=$(ssh $host "chronyc tracking | awk '/Last offset/ {print \$4}'")
  echo "$host: offset=${offset}s"
done

# Or: application-level skew probe
# Each node writes {node_id, wall_time_ns} to Redis every 10s
# Monitor max(wall_time) - min(wall_time) across nodes
# Alert if > 10ms (tunable)
```

---

### 7.2 — Linux Clock Inspection

```bash
# Current wall clock and resolution
date -u +"%Y-%m-%d %H:%M:%S.%N UTC"
timedatectl status
# Shows: System clock synchronized: yes
#        NTP service: active
#        RTC time, Time zone

# Kernel timekeeping stats
cat /proc/timer_list | head -50    # verbose; shows clock events

# Check for recent clock steps in kernel log
dmesg | grep -i "clock\|time\|ntp\|chrony" | tail -20
journalctl -u chronyd --since "24 hours ago" | grep -i "step\|adjust\|slew"

# TSC (Time Stamp Counter) stability — relevant for perf timing
grep -o 'tsc.*' /proc/cpuinfo | head -1
# constant_tsc nonstop_tsc = good for monotonic measurements
```

```bash
# ── CONTAINER / KUBERNETES ────────────────────────────────────

# Container inherits host clock
kubectl exec -it pod-name -- date -u
kubectl exec -it pod-name -- chronyc tracking 2>/dev/null || echo "no chrony in container (expected)"

# Check NODE clock (where it matters)
kubectl debug node/node-name -it --image=ubuntu -- chroot /host chronyc tracking

# EKS node group: verify user-data installed chrony with AWS Time Sync
```

---

### 7.3 — Application-Level Timestamp Audits

```python
# ── CLOCK SANITY MIDDLEWARE (Python / Flask example) ──────────

import time
import logging

_last_wall = 0

def clock_audit_middleware():
    global _last_wall
    now = time.time()
    if now < _last_wall - 1.0:  # backward jump > 1 second
        logging.critical(
            "CLOCK_STEP_BACKWARD",
            extra={"delta": _last_wall - now, "last": _last_wall, "now": now}
        )
    _last_wall = now

# Emit metric: clock_backward_events_total
```

```sql
-- ── FIND DUPLICATE TIMESTAMPS IN EVENT TABLE ────────────────
-- Sign of leap second or Snowflake-style collision

SELECT created_at, COUNT(*) AS cnt
FROM events
GROUP BY created_at
HAVING COUNT(*) > 100   -- tune threshold
ORDER BY cnt DESC
LIMIT 20;

-- ── FIND "FUTURE" EVENTS (clock ahead) ──────────────────────
SELECT id, created_at, created_at - now() AS future_by
FROM events
WHERE created_at > now() + interval '5 minutes'
ORDER BY created_at DESC;
```

```bash
# ── CORRELATE LOGS ACROSS SERVICES (skew diagnosis) ───────────

# Same request_id, different service timestamps — compute spread
# Loki / CloudWatch Logs Insights:
fields @timestamp, service, request_id
| filter request_id = "req-abc-123"
| sort @timestamp asc

# If spread between first and last > expected processing time:
# likely clock skew, not slow request
```

---

### 7.4 — Hands-On Exercises

```
╔═════════════════════════════════════════════════════════════════╗
║   EXERCISE 1: Measure AWS Time Sync Accuracy                    ║
║                                                                 ║
║   On a fresh EC2 instance (Amazon Linux 2023):                  ║
║                                                                 ║
║   1. Before configuring: chronyc tracking (note offset)         ║
║   2. Configure 169.254.169.123 in chrony.conf                   ║
║   3. Restart chronyd, wait 30 seconds                           ║
║   4. chronyc tracking — offset should be < 500 microseconds     ║
║   5. Run 1000 samples:                                          ║
║      for i in $(seq 1 1000); do                                 ║
║        chronyc tracking | awk '/Last offset/ {print $4}';       ║
║      done | sort -n | awk '                                     ║
║        {a[NR]=$1} END{                                          ║
║          print "min:", a[1];                                    ║
║          print "p50:", a[int(NR/2)];                            ║
║          print "p99:", a[int(NR*0.99)];                         ║
║          print "max:", a[NR]}'                                  ║
║                                                                 ║
║   Expected on c6i in same AZ: p99 < 200μs                       ║
╠═════════════════════════════════════════════════════════════════╣
║   EXERCISE 2: Observe Monotonic vs Wall Clock                   ║
║                                                                 ║
║   Python script:                                                ║
║   import time                                                   ║
║   wall_start = time.time()                                      ║
║   mono_start = time.monotonic()                                 ║
║   time.sleep(2)                                                 ║
║   print("wall elapsed:", time.time() - wall_start)              ║
║   print("mono elapsed:", time.monotonic() - mono_start)         ║
║                                                                 ║
║   Then: sudo chronyc makestep (force step)                      ║
║   Run again. Wall elapsed may be wrong. Mono still ~2.0.        ║
╠═════════════════════════════════════════════════════════════════╣
║   EXERCISE 3: Happens-Before Identification                     ║
║                                                                 ║
║   Given three processes P, Q, R and messages m1, m2:            ║
║   P: A, B, send(m1), C, D                                       ║
║   Q: E, recv(m1), F, send(m2), G                                ║
║   R: H, recv(m2), I, J                                          ║
║                                                                 ║
║   List all pairs of events that are CONCURRENT.                 ║
║   (Answer: E and A,B; H and A,B,C,D; etc. — draw diagram)       ║
╠═════════════════════════════════════════════════════════════════╣
║   EXERCISE 4: Simulate LWW Data Loss                            ║
║                                                                 ║
║   Two terminal windows, Redis:                                  ║
║   Terminal 1: SET key v1 EX 3600  (pretend ts=1000)             ║
║   Terminal 2: SET key v2 EX 3600  (pretend ts=999, later)       ║
║   If using Redis, last SET wins regardless of time.             ║
║   Extend: use Cassandra or mock with timestamp field.           ║
║   Demonstrate: higher timestamp wins even if logically later.   ║
╚═════════════════════════════════════════════════════════════════╝
```

---

## Decision Framework
```
╔══════════════════════════════════════════════════════════════════╗
║   WHICH TIME SOURCE FOR WHICH PROBLEM?                           ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║   YOUR REQUIREMENT                    │ USE THIS                 ║
║   ────────────────────────────────────┼───────────────────────   ║
║   Measure request latency on 1 host   │ Monotonic clock          ║
║   HTTP timeout / circuit breaker      │ Monotonic clock          ║
║   JWT / certificate expiry            │ Wall clock (UTC)         ║
║   Audit log "when did this happen"    │ Wall clock (UTC)         ║
║   Cron / scheduled jobs               │ Wall clock (UTC)         ║
║   Cache TTL (approximate)             │ Wall clock + fuzz        ║
║   Order events on ONE machine         │ Monotonic or sequence    ║
║   Order events across machines        │ Logical clock /          ║
║                                       │ consensus log index      ║
║   Causal ordering (A maybe caused B)  │ Happens-before /         ║
║                                       │ Lamport / vector (T2)    ║
║   Detect concurrent writes            │ Vector clock (T2)        ║
║   Merge concurrent writes             │ CRDT (T3)                ║
║   Linearizability globally            │ TrueTime / HLC +         ║
║                                       │ consensus, or single     ║
║                                       │ leader (Raft)            ║
║   Unique IDs (no coordination)        │ UUID v4 (random) or      ║
║                                       │ ULID / Snowflake w/      ║
║                                       │ sequence guard           ║
║   Unique IDs (with coordination)      │ Database sequence /      ║
║                                       │ Raft log index           ║
║   Distributed lock                    │ Consensus lease +        ║
║                                       │ fencing token            ║
║   Leader election                     │ Raft / Paxos (NOT        ║
║                                       │ wall-clock election)     ║
║   Metrics dashboard ordering          │ Wall clock (approx OK)   ║
║   Billing / financial ordering        │ Consensus + idempotency  ║
║                                       │ (NOT wall clock)         ║
╚══════════════════════════════════════════════════════════════════╝
```

### Decision Tree

```
START: Do two events on DIFFERENT machines need ordering?

  NO → Is it about duration or expiry on ONE machine?
    YES → Duration: MONOTONIC. Expiry: WALL (UTC).
    NO  → Single-machine sequence: counter or monotonic.

  YES → Does correctness require REAL-TIME order?
    (linearizability — "after write, all reads see it")

    YES → Can you deploy GPS/atomic clock hardware?
      YES → TrueTime-style (Spanner)
      NO  → HLC + bounded skew wait (CockroachDB)
            OR single-leader Raft (simpler)

    NO → Does correctness require CAUSAL order?
      (if A → B, everyone sees A before B)

      YES → Lamport / vector clocks (Topic 2)
            OR application-level version chains

      NO  → Events are independent (concurrent).
            Use CRDT merge or application conflict UI.
            Do NOT force total order with timestamps.
```

### AWS-Specific Recommendations

```
╔════════════════════════════════════════════════════════════════╗
║   SERVICE TYPE              │ CLOCK RECOMMENDATION             ║
╠════════════════════════════════════════════════════════════════╣
║  EC2 / EKS / ECS workloads  │ chrony + 169.254.169.123         ║
║                             │ Alert offset > 1ms               ║
╠════════════════════════════════════════════════════════════════╣
║  Lambda                     │ Trust AWS host clock             ║
║                             │ Don't read time for ordering     ║
╠════════════════════════════════════════════════════════════════╣
║  RDS / Aurora (self-managed)│ chrony on instance (if access)   ║
║                             │ Use LSN for replication order    ║
╠════════════════════════════════════════════════════════════════╣
║  DynamoDB                   │ Trust service versioning         ║
║                             │ Conditional writes for conflicts ║
╠════════════════════════════════════════════════════════════════╣
║  MSK (Kafka)                │ chrony on brokers                ║
║                             │ Prefer offset-based retention    ║
╠════════════════════════════════════════════════════════════════╣
║  ElastiCache (Redis)        │ chrony on nodes if using TTL     ║
║                             │ locks; use fencing tokens        ║
╠════════════════════════════════════════════════════════════════╣
║  Multi-region active-active │ HLC or CRDT; NEVER naive LWW     ║
║                             │ on client timestamps             ║
╚════════════════════════════════════════════════════════════════╝
```

---

### Principal stretch

## Ops Sim: Northstar Coupon Expiry Clock Step

**Time box:** 50 minutes  
**Severity:** P1  
**Service / domain:** Clock sync, token expiry, coupon validation, mobile checkout  
**Northstar system:** Northstar Commerce

### Practice rules

1. Answer from memory of the Clocks Time and Ordering teaching section; do not re-read mid-drill.
2. Write decisions in order: T+0, T+5, T+15, T+30, T+60, and follow-up.
3. Tie every claim to a metric, log line, trace, query output, or config key from this packet.
4. Name the correctness invariant before proposing scale, failover, replay, or data repair.
5. Do not open the answer key until your response is written.

---

### What is happening

```text
WHAT USERS SEE:
  - EU buyers see valid coupons rejected as issued in the future.
  - Source-of-truth records and derived projections disagree.
  - Support reports cluster in the named slice, not the full fleet.
  - A proposed generic mitigation would hide or worsen the invariant risk.

WHAT ON-CALL SEES:
  - Issuer NTP offset is +88 seconds and client-time fallback is active.
  - Fleet-average dashboards understate the incident.
  - The config fragment below changed recently or lacks a guardrail.
  - Repair must wait for a bounded affected set and idempotent operation key.

BUSINESS CONSTRAINT:
  Do not accept expired/fraudulent coupons globally; affected valid coupons can be reissued or validated with bounded skew.
```

### Root-cause mechanics

EU coupon issuers use a different leap-smear profile and drift 88 seconds ahead. A client-time fallback widens the issue, so valid coupons look issued in the future.

Break it into these forces before answering:
- trigger: the release/config/data shape that started the failure
- amplifier: retry, cache, routing, projection, or observability behavior that widened it
- scarce resource: the metric that reaches a limit first
- invariant: what must remain conservative even while users see degraded experience
- repair boundary: the source of truth and operation id used after mitigation

### Change clues

- The suspicious production lever is `coupon.acceptable_clock_skew_seconds: 30`; tie it to the first bad minute before changing capacity.
- The dashboard that stayed calm does not expose `coupon_reject_rate{reason="issued_in_future"}` for the damaged slice.
- The runbook move closest to "raise skew to 24h globally" needs an explicit no-go decision on the bridge.
- The repair path is allowed only after the source-of-truth query and operation key are written down.

### Telemetry card

```text
METRICS:
  - coupon_reject_rate{reason="issued_in_future"}: 0.1% -> 18%
  - ntp_offset_ms{region="eu-west"}: +88000
  - checkout_conversion_drop{region="eu-west"}: 11%
  - token_iat_future_seconds{p99}: 92
  - mobile_client_time_fallback_total: +480k
  - payment_success_rate: stable
  - inventory_reservation_success_rate: stable
  - coupon_reissue_success_total: +22000

LOG LINES:
  - coupon: token iat future by 92s issuer=eu-west
  - Northstar Coupon Expiry Clock Step: derived projection disagrees with source of truth
  - Northstar Coupon Expiry Clock Step: unsafe repair or fallback proposed on bridge
  - Northstar Coupon Expiry Clock Step: affected-slice metric exceeds fleet average
  - Northstar Coupon Expiry Clock Step: capacity check missing before replay/scale

TRACE / QUERY / INSPECTION NOTES:
  - Inspect token issuer region, NTP profile, and server/client validation path.
  - Before/after config diff aligns with the first bad metric.
  - The affected set is bounded by time window plus business key.
  - One generic health check remains green and is a red herring.
```

### Config card

```yaml
coupon.acceptable_clock_skew_seconds: 30
coupon.use_client_time_on_server_error: true
ntp.leap_smear_profile: mixed
token.issuer_region: eu-west
monotonic_deadline_for_expiry: false
```

### Decision table

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | EU coupon future-iat rejects spike. | Compare issuer and validator clocks. |
| T+5 | Marketing asks to disable expiry checks. | Use bounded issuer skew instead. |
| T+15 | Mixed leap-smear and client fallback confirmed. | Disable client-time fallback. |
| T+30 | Valid coupons are reissued. | Track rejected token ids. |
| T+60 | Checkout conversion stabilizes. | Audit fraud exposure. |
| T+24h | Platform reviews time discipline. | Standardize NTP profile and skew alerts. |

### Recovery tools

- Roll back or disable the specific dangerous config from the packet.
- Shed decorative, derived, notification, or analytics work before weakening source-of-truth correctness.
- Throttle retry/replay using the narrowest downstream capacity limit.
- Keep an affected-record ledger before customer-visible repair.
- Verify recovery with the sliced SLI plus the scarce-resource metric, not a fleet average.

### Do-not-do list

For each proposal, name the concrete failure mode it creates.

- raise skew to 24h globally
- trust mobile device time
- disable all expiry checks
- refund every coupon rejection from dashboard counts

### Questions

**Q01.** What exact layer owns the failure and why is the most obvious graph a red herring?

**Q02.** Which config line is wrong, and what failure physics does it create?

**Q03.** Select three metrics and two log/inspection clues that prove your diagnosis.

**Q04.** What is the safe T+0 to T+5 announcement and freeze/rollback decision?

**Q05.** What do you stop first: trigger, amplifier, or repair job? Explain sequencing.

**Q06.** What invariant must remain true if every dashboard is stale?

**Q07.** Which bad fix is most tempting in this incident, and why does it make recovery worse?

**Q08.** What numeric capacity or blast-radius check is required before scale/failover/replay?

**Q09.** What is the source-of-truth query or ledger for the affected set?

**Q10.** Which derived systems may lag, and which external side effects require idempotency?

**Q11.** Write the durable config/architecture change and its acceptance test.

**Q12.** Who joins by T+10, and what is pre-authorized versus escalated?

### Self-score

| Error type | Count | Notes |
|------------|-------|-------|
| Wrong layer/root cause | | |
| Evidence gap | | |
| Unsafe first action | | |
| Capacity/blast-radius miss | | |
| Correctness invariant miss | | |
| Repair/replay mistake | | |
| Org/runbook gap | | |

**Pass bar:** correct mechanism, safe sequencing, explicit rejection of the bad fix, one numeric capacity check, and a repair plan grounded in source of truth.

**Answer key:** [answers/Week-08-Advanced-Patterns/Clocks Time and Ordering Answers.md](../answers/Week-08-Advanced-Patterns/Clocks%20Time%20and%20Ordering%20Answers.md)

