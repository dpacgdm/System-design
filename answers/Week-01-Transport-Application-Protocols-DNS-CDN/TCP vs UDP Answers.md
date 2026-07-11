# Answer Key — TCP vs UDP

> Open only after attempting the learner file questions.

## Expert Analysis

## Question 1: Root Cause Analysis
```
MINUTE-BY-MINUTE REASONING:

T+0: TIME_WAIT ~2,000 — within noise. ActiveOpens rising slowly.
T+5: TIME_WAIT ~12,000. estab 847 despite pool max=100 → pool bypass.
T+10: Port consumption exceeds TIME_WAIT release (~28K ephemeral range).
T+15: ALERT. connect() EADDRNOTAVAIL → "connection timeout" to Postgres.

EVIDENCE: ss timewait 38,102 + estab 847 + DB 497/500 = per-request TCP churn.
```

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

***The 15-minute window was the time it took for the application to burn through the entire available range of source ports.***

---

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

---

## On-Call Drill: Pre-Failure TIME_WAIT Alert — Worked Answer

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

## Preserved notes from retired Northstar drill

## Ops Sim: Northstar Checkout Port Exhaustion

### Q1 - Layer & root cause

Primary layer: client-side TCP connection management on `checkout-api`, not Postgres query execution.

Mechanism:
- `auctionSettlement.connect_per_bid=true` bypasses the shared pool.
- Every bid settlement opens a short-lived TCP connection to PgBouncer.
- The local ephemeral port remains in `TIME_WAIT` after close.
- Once `TIME_WAIT` sockets approach or exceed the local ephemeral range, new connects fail with `EADDRNOTAVAIL` / timeout.

### Q2 - Evidence

Confirming signals:
1. `node_sockstat_TCP_tw` at ~41,700 per pod while the port range has only 28,232 ports.
2. `ActiveOpens` jumping from 4k/min to 640k/min: connection churn, not query load.
3. App log `cannot assign requested address` on connect to PgBouncer: local source port exhaustion.

Red herring: normal SQL execution p99 and normal Postgres lock waits. The DB can execute queries; clients cannot reliably establish sockets.

### Q3 - First 15 minutes

Safe sequence:
1. Declare/confirm P1 and freeze non-essential checkout deploys.
2. Stop the new churn path: disable or roll back `auctionSettlement.connect_per_bid`; route settlement through the shared pool.
3. Buy runway on affected nodes if allowed by runbook: widen `ip_local_port_range` and enable safe `tcp_tw_reuse` for outbound connections.
4. Drain/restart pods in small batches only after traffic is reduced; do not create a synchronized reconnect storm.
5. Watch `TCP_tw`, connect timeouts, PgBouncer client/server counts, and successful checkout rate.

### Q4 - Bad fixes

Raising Postgres `max_connections` is dangerous because the bottleneck is local ports and churn. It also increases DB memory/context-switch overhead and can destabilize Postgres during a sale.

Restarting all checkout pods may temporarily clear sockets, but it does not remove `connect_per_bid`; the pods will refill `TIME_WAIT`. Restarting all at once also floods PgBouncer/Postgres with new connections.

### Q5 - Capacity / blast radius

Approximate unsafe new-connect rate per pod:

```text
28,232 ephemeral ports / 60s TIME_WAIT ~= 470 new connects/sec
```

Sustained churn near or above that rate risks exhaustion. Retries make the effective rate higher.

If all pods reconnect at once:
- PgBouncer accepts a login storm.
- Postgres may hit connection or authentication CPU limits.
- Payment ledger calls sharing the same node/network path may also fail.
- Health checks may restart otherwise recoverable pods.

### Q6 - Durable fix

Fix:
- Remove per-bid DB clients.
- Enforce a singleton PgBouncer-backed pool per process.
- Add static lint/tests blocking `new Client()` or equivalent in hot request paths.
- Keep PgBouncer pool math below Postgres capacity.

Acceptance criteria:
- `ActiveOpens` returns near baseline under auction load.
- `TCP_tw` stays below 50% of ephemeral range per pod.
- `checkout-api` p99 < 300ms and connect timeout rate < 0.1% during a replay of peak auction traffic.

### Q7 - Org / runbook

By T+10 notify: incident commander, checkout lead, database on-call, auction business owner, payments lead, support lead.

Pre-authorized:
- Disable the settlement worker feature flag.
- Batch drain/restart checkout pods.
- Apply documented TCP sysctl runway changes.

Escalate before:
- Changing Postgres global connection limits.
- Disabling all checkout.
- Making durability/charge semantics changes.
