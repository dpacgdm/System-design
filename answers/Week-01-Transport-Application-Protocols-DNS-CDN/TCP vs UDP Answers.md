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
