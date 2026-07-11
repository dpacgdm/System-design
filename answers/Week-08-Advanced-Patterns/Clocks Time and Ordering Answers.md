# Answer Key — Clocks Time and Ordering

> Open only after attempting the learner file questions.

## Expert Analysis
### 10.1 — Full Worked Response to "The Inventory Ghost"

#### Root Cause Chain

```
TRIGGER (14:20):
  Terraform security group change blocked UDP/123 to 169.254.169.123.
  Four K8s worker nodes in us-east-1b lost AWS Time Sync.

AMPLIFIER (14:22–14:38):
  chrony on affected nodes entered unsynchronized state.
  Quartz crystal drift pushed clocks ~800ms AHEAD of real time.
  No alert fired — chrony offset monitoring was not deployed.

CASCADE (14:41–14:47):
  a) SnowflakeGenerator on affected pods: ClockMovedBackwardsException
     when chrony briefly stepped clock → CrashLoopBackOff → 50% capacity loss

  b) LWW on Cassandra: pods on fast-clock nodes wrote inventory updates
     with timestamps 800ms in the "future"
     → Overwrote correct zero-quantity writes with stale qty=3
     → "Ghost inventory" — system thinks stock exists when sold out

  c) warehouse-api read stale qty=3 → created duplicate pick orders

  d) checkout captured payment for last unit while inventory showed 0
     on correctly-synced nodes → reservation conflict

DISTINCT BUGS (5):
  1. Security group blocked NTP (infra)
  2. No chrony offset alerting (observability)
  3. LWW using client wall-clock timestamps for inventory (application)
  4. Snowflake crash loop without graceful degradation (application)
  5. No fencing/version check on warehouse pick creation (integration)
```

#### Immediate Mitigation (First 15 Minutes)

```
MINUTE 0-5:
  1. Rollback security group Terraform change — restore UDP/123 to
     169.254.169.123 (link-local only — no internet exposure)
  2. Scale inventory-service to healthy AZ nodes only (cordon AZ-1b workers)
  3. Page infra — stop CrashLoop; pods will recover after chrony resync

MINUTE 5-10:
  4. Disable inventory writes temporarily — flip feature flag
     "inventory.writes.enabled=false" → checkout shows "try again"
  5. Halt warehouse pick job consumer — stop duplicate picks

MINUTE 10-15:
  6. Force chrony resync on affected nodes:
     ssh node && sudo chronyc makestep && systemctl restart chronyd
  7. Verify offset < 1ms on all nodes before re-enabling writes
  8. Communicate: status page — "inventory delays, no duplicate charges"
```

#### Data Correctness

```
AUTHORITATIVE SOURCE:
  NOT wall-clock timestamps. Use:
  1. Payment capture log (ORD-7721) — ground truth for sold units
  2. Cassandra LWT read with QUORUM for current state
  3. Warehouse WMS physical count (manual verification)

RECONCILIATION:
  For sku-88421:
    - Count successful captures in payment DB since 14:15
    - Set inventory = max(0, physical_count - captured_count)
    - Use LWT (Paxos) update, NOT timestamp-based write
    - Audit log every correction with operator ID

  DO NOT: pick highest timestamp write — that's what caused the bug.
```

#### Long-Term Fixes

```
P0 (this week):
  □ Security group: allow UDP/123 to 169.254.169.123 ONLY (documented)
  □ Alert: node_timex_offset_seconds > 1ms for 2m → page
  □ Alert: chrony sync status lost → page
  □ Inventory: replace LWW with LWT (IF version = :expected)
  □ Remove client-supplied timestamps from Cassandra writes entirely

P1 (this sprint):
  □ Snowflake: graceful degradation (fall back to UUID) on clock error
  □ CockroachDB-style: refuse writes if local clock skew > 100ms
  □ Warehouse: idempotent pick orders with version check
  □ Integration test: simulate 500ms clock skew in CI

P2 (this quarter):
  □ Evaluate CRDT counter for inventory (PN-Counter) or authoritative
    single-leader writes per SKU partition
  □ Chaos Engineering: "clock skew" as quarterly game day scenario
  □ SSM compliance: 100% nodes with verified chrony config
```

#### Consistency Model Violation

```
Checkout flow required LINEARIZABILITY (or at minimum:
read-your-writes + monotonic reads) for inventory:

  User completes purchase → inventory deducted → confirmation shown.
  Read-your-writes violated: user saw "purchased" but inventory
  service still showed stock (different pods, different clock skew).

  Monotonic reads violated: inventory count went 0 → 3 → 0 (LWW
  time travel).

From Week 3 Topic 2: the fix is NOT "stronger Cassandra CL" alone.
  Client-side LWW with bad clocks defeats any replica consistency.
  Need: authoritative ordering (LWT/Paxos) + synchronized clocks +
  application-level version checks.
```

---

### 10.2 — Five In-Depth Questions

#### Question 1: Why can't we just use NTP to order events across services?

**Short answer:** NTP synchronizes wall clocks to within milliseconds (microseconds on AWS). It does not establish causal order. Two events with no message path between them are concurrent — NTP will assign them an arbitrary order that may contradict happens-before. NTP also doesn't prevent backward jumps during steps.

**Full answer:** Ordering for correctness requires either: (1) a happens-before chain (logical clocks), (2) a consensus log index (Raft), or (3) bounded uncertainty with commit-wait (TrueTime). NTP provides none of these. It is infrastructure hygiene — necessary to reduce skew-driven bugs in LWW and leases, but not sufficient for distributed ordering. Even at 50μs skew, two events in the same millisecond are unordered by timestamp.

---

#### Question 2: Spanner's commit-wait adds latency. When is it worth it?

**When linearizability (external consistency) across geographically distributed replicas is a product requirement.** Google Ads, AdWords, and financial products on Spanner need global consistency. The 2–14ms commit-wait is cheaper than cross-region 2PC coordination with a single leader in one region (which would add RTT latency to ALL remote writes anyway).

**When NOT worth it:** Single-region apps on EC2 where a Raft leader (etcd, CockroachDB single-region) suffices. Or eventually consistent workloads (analytics, caches) where causal or no ordering is fine. Pay commit-wait latency only when you need real-time global ordering.

---

#### Question 3: How does happens-before relate to linearizability from Week 3?

**Linearizability implies happens-before for real-time dependencies:** If operation A completes before operation B starts in real time, linearizability requires A appears before B in the sequential order.

**Happens-before is strictly weaker:** Causal consistency respects happens-before but allows concurrent operations to be seen in different orders by different clients. Happens-before is the causal structure; linearizability adds a real-time constraint on top.

**Clocks bridge the gap:** Without perfect clocks, you can't implement linearizability from happens-before alone — you need either synchronized clocks (TrueTime) or a single ordering point (Raft leader).

---

#### Question 4: What is the difference between leap second smearing and stepping?

**Stepping:** Clock jumps at the leap second boundary. Can go backward (positive leap) or skip a second (negative). Applications see discontinuity. `time.time()` may return same value twice or go backward.

**Smearing:** Spread the leap second over hours. Clock runs slightly slow (or fast) before the event. No discontinuity. No duplicate timestamps. But clock is deliberately wrong vs true UTC during smear window. AWS and Google use smearing. Cross-system comparison with non-smearing systems shows temporary offset.

**Operational choice:** Smearing for application stability. Stepping for astronomical correctness. On AWS EC2 with Amazon Linux, you get smearing via chrony + Time Sync — design apps for smeared time, not true UTC during smear window.

---

#### Question 5: Design a clock-health system for a 500-node EKS cluster.

```
COMPONENTS:

1. INFRASTRUCTURE (DaemonSet):
   - node_exporter with --collector.timex on every node
   - Optional: chrony-exporter sidecar parsing chronyc tracking

2. METRICS (Prometheus):
   - node_timex_offset_seconds (gauge)
   - node_timex_sync_status (gauge, 1=synced)
   - clock_step_events_total (custom, from dmesg watcher)

3. ALERTS:
   P1: abs(offset) > 100ms for 2m on any node
   P2: abs(offset) > 10ms for 5m on >3 nodes in same AZ
   P3: sync_status == 0 for 5m
   P2: clock_step_events_total increase

4. REMEDIATION (SSM Automation):
   - On P2: restart chronyd, verify 169.254.169.123 reachable
   - On P1: cordon node, drain pods, replace instance

5. COMPLIANCE (weekly):
   - SSM State Manager: chrony.conf contains 169.254.169.123
   - Security group audit: UDP/123 to link-local NOT blocked

6. APPLICATION:
   - Middleware logs clock backward jumps
   - Services using timestamps for ordering: health check refuses
     traffic if offset > threshold (CockroachDB pattern)

COST: ~500 additional time series. Negligible vs cost of inventory ghost incident.
```

---
