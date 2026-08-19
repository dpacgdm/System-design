# Answer Key — Design WhatsApp

> Open only after attempting the learner file questions.

## Expert Analysis
### Question 1: Cascade Chain

```
TRIGGER:
  Cricket goal → grp_cricket_2026 message rate 2K → 8K msg/sec
  Combined with: fanout_mode=WRITE (bug — should be READ for 18K group)
  → Each message = 18,000 inbox writes (write amplification)

AMPLIFIER 1 — WRITE AMPLIFICATION (the force multiplier):
  8K msg/sec × 18,000 inbox writes = 144M Cassandra writes/sec
  (theoretical; batched to ~2.8M actual batch writes/sec)
  Single partition grp_cricket_2026 + 18K inbox partitions
  Cassandra p99: 15ms → 890ms → 2,100ms

AMPLIFIER 2 — FAN-OUT WORKER v2.14.0 DEPLOY:
  Batch size 50 → 200: fewer, larger Cassandra batches
  Larger batches → longer coordinator hold time on hot partition
  Consumer rebalance at 8:45 (full fleet on new version)
  Brief lag spike during rebalance + larger batches hit hot node

AMPLIFIER 3 — SCALE CONSUMERS 48 → 96 (8:56 PM):
  2× consumers = 2× Cassandra write pressure
  Cross-system capacity violation (Handoff Doc growth area)
  Cassandra p99: 890ms → 2,100ms
  Lag growth: 50K/min → 120K/min

VICTIM 1 — KAFKA CONSUMER LAG (ACTIVE CASCADE):
  Consumers cannot commit fast enough
  Lag 500K → 900K and accelerating
  Messages persist in Cassandra (ingress OK) but delivery delayed
  STATUS: ACTIVE — still worsening until write pressure reduced

VICTIM 2 — WS PUSH SUCCESS RATE (ACTIVE CASCADE):
  Fan-out workers timeout on Cassandra writes
  Skip push → fall back to inbox-only path
  Online users not receiving real-time delivery
  STATUS: ACTIVE — coupled to lag

VICTIM 3 — REDIS EVICTIONS (AMPLIFIER → becoming ACTIVE):
  Fan-out retry loops + debugging queries created 2.1M ephemeral keys
  Memory 71% → eviction under pressure
  conn registry keys evicted → push path broken even when Cassandra recovers
  STATUS: CONTAINED if evictions stop; ACTIVE if eviction continues

CONTAINED:
  Ingress (45ms p99 — not affected, AP path healthy)
  Gateway fleet (CPU normal, connections stable)
  Media/S3 (not in this path)

QUANTIFIED AMPLIFICATION:
  Normal group (256 members, WRITE fan-out): 8K msg × 256 = 2M writes/sec
  Actual bug (18K members): 8K × 18,000 = 144M writes/sec
  Amplification factor: 72× vs intended max group size
  Consumer scale mistake: 2× additional pressure on already 80× degraded Cassandra
```

### Question 2: Evaluate Scaling Decision + Correct Mitigation

```
SCALING 48 → 96 WAS WRONG:

  Fan-out workers were at 38% CPU — NOT compute bound
  Lag caused by Cassandra write latency (890ms), not consumer throughput
  Doubling consumers doubled write load on degraded Cassandra
  Classic cross-system capacity failure

SHOULD HAVE CHECKED FIRST:
  1. Cassandra write latency (was 890ms — RED FLAG)
  2. Which partition is hot (partition 147 = grp_cricket_2026)
  3. fanout_mode for that group (WRITE for 18K = bug)
  4. "If I add consumers, can Cassandra handle 2× writes?" → NO

CORRECT MITIGATION SEQUENCE (8:56–9:10):

  MINUTE 0 (8:56): STOP consumer scale-up
    Roll back fan-out worker deploy v2.14.0 → v2.13.0
    (rebalance storm + batch size regression)

  MINUTE 1 (8:57): EMERGENCY — switch grp_cricket_2026 to READ fanout
    UPDATE groups SET fanout_mode='READ' WHERE group_id='grp_cricket_2026'
    Invalidate Redis group cache
    Effect: inbox writes drop from 18K to 0 per message
    Cassandra write pressure drops ~95% within 60 seconds

  MINUTE 2 (8:58): RATE LIMIT grp_cricket_2026
    Server-side: max 50 msg/sec to this group_id
    Client-side push: "High traffic — messages may be delayed"
    Reduces remaining group log writes from 8K to 50/sec

  MINUTE 3 (8:59): DO NOT scale consumers yet
    Wait for Cassandra p99 < 100ms (monitor 2 min)

  MINUTE 5 (9:01): Verify Redis eviction stopped
    If still evicting: redis-cli CONFIG SET maxmemory-policy volatile-lru
    Pin conn registry keys ( separate Redis instance or no-eviction policy)

  MINUTE 7 (9:03): IF lag still growing AND cassandra p99 < 100ms:
    Scale consumers 48 → 64 (modest 33%, NOT 100%)
    Verify lag derivative turns negative within 3 min

  MINUTE 10 (9:06): Stakeholder comms
    Status page: "Delayed message delivery in India region — investigating"
    VP message: "Root cause identified (fan group config), fix deploying,
                 ETA 15 min to clear backlog"
    Cricket partner: direct call — NOT public speculation

  MINUTE 14 (9:10): Lag should be decreasing
    If not: throttle ingress for grp_cricket ONLY (drop to 10 msg/sec)
    NEVER throttle global ingress (cricket is the problem, not 420K/sec normal)
```

### Question 3: Redis Eviction Analysis + Defense Layers

```
REDIS EVICTION: AMPLIFIER (not root cause)

  Root cause: Cassandra slow → fan-out retries → extra Redis lookups
  + engineers running --scan --pattern "conn:*" debugging
  + 18K member presence subscriptions (grp_cricket)
  = memory pressure → eviction of conn registry keys

BLAST RADIUS IF REGISTRY EVICTED:
  Fan-out worker: conn_registry_miss → skip push
  Online users appear offline → messages inbox-only
  ws_push_success_rate: 72% → 54% (observed)
  Users who ARE online don't get real-time delivery
  Data NOT lost (Cassandra inbox has messages)
  User experience: "app shows delivered when I open chat but
                   no notification while online"

L1 (PRIMARY): Separate Redis cluster for conn registry
  Memory: 32 GB dedicated, no eviction policy (noeviction)
  Capacity: 500M keys × 200 bytes = 100 GB → 4-shard cluster
  Handles: conn:*, devices:* only

L2 (FALLBACK): Local gateway cache
  Each gateway caches conn lookups for 30s (in-memory LRU)
  If Redis miss: check peer gateways via gossip (expensive)
  Capacity: 100K connections × 200B = 20 MB per gateway

L3 (LAST RESORT): FCM/APNs push for online-fallback
  If WS push fails after 3 retries → push notification
  "You have a new message" (no content — E2E)
  Latency: 1-30 seconds (worse than WS but better than nothing)
  Capacity: FCM handles 1M/sec globally
```

### Question 4: Operational Prerequisites

```
COMMANDS THAT MIGHT FAIL:

  nodetool tablestats:
    → May timeout if Cassandra coordinators overloaded (p99 2s)
    → Use -Dcom.sun.jmx.remote.port=7199 with 30s timeout
    → Alternative: Grafana cassandra_write_latency (already have data)

  kafka-consumer-groups.sh --describe:
    → Works (Kafka healthy, lag is consumer-side)
    → BUT: resetting offsets is DANGEROUS — do NOT reset to latest
      (would drop 900K undelivered fan-out events)

  kubectl scale deployment fanout-worker --replicas=96:
    → Already executed (the mistake)
    → Rolling pods causes ANOTHER rebalance storm
    → Rollback to 48 requires careful coordination

  redis-cli --scan --pattern "conn:*":
    → BLOCKS Redis (O(N) scan) — engineers may have CAUSED eviction
    → NEVER run SCAN on production Redis during incident
    → Use: redis-cli INFO keyspace + sampled HGETALL instead

VERIFY BEFORE CASSANDRA ACTIONS:

  □ Coordinator reachable: cqlsh -e "SELECT now() FROM system.local"
  □ Not in repair/compaction storm: nodetool compactionstats (timeout OK)
  □ Identify node owning hot partition:
    nodetool ring | grep token_for_grp_cricket_2026
  □ Check disk: df -h on that node (compaction needs disk headroom)

VERIFY BEFORE SCALING CONSUMERS:

  □ Cassandra write p99 < 100ms (MANDATORY)
  □ Redis eviction rate = 0
  □ Consumer CPU > 70% (actually compute bound — was 38%, so NO)
  □ Lag derivative negative (already recovering — don't disturb)
```

### Question 5: Post-Mortem

```
ROOT CAUSE:
  Migration script set fanout_mode=WRITE for grp_cricket_2026
  (18K members) — threshold should enforce READ at > 256 members
  Cricket event + WRITE fan-out = 72× write amplification →
  Cassandra hot partition → fan-out lag → delivery delay

IMMEDIATE FIX:
  1. grp_cricket_2026 → fanout_mode=READ (done during incident)
  2. Audit all groups > 256 members for incorrect fanout_mode
  3. Roll back fan-out v2.14.0 batch size change

LONG-TERM ARCHITECTURE CHANGES:

  1. AUTOMATIC FANOUT MODE ENFORCEMENT
     Trigger: member_count > 256 → fanout_mode=READ (immutable)
     Implementation: Group Service check on MEMBER_ADDED event
     Prevent: migration scripts from overriding without override flag
     Alert: fanout_mode=WRITE AND member_count > 256 → P2 page

  2. HOT PARTITION CIRCUIT BREAKER
     Monitor: cassandra write rate per chat_id partition
     Threshold: > 1000 writes/sec per partition
     Action: auto rate-limit + auto-switch to READ fanout
     L1: rate limit 50/sec, L2: READ fanout, L3: pause group

  3. CROSS-SYSTEM CAPACITY GATE ON AUTOSCALE
     KEDA fan-out scaler: add precondition
     "cassandra_write_p99 < 50ms" before allowing scale-up
     Prevents consumer scale from amplifying storage bottleneck

STAKEHOLDER COMMUNICATION:
  T+0:  Status page + internal war room
  T+15: "Fix deployed, backlog clearing, ETA 30 min normal"
  T+60: "Resolved. India region fully recovered."
  T+24h: Customer blog post (transparency — cricket group config error)
  Cricket partner: direct account manager call at T+15

PRE-EVENT RUNBOOK (viral events):
  7 days before: marketing calendar → engineering review
  3 days before: identify affected groups, verify fanout_mode
  24 hours before: scale Cassandra compaction headroom +20%
  2 hours before: pre-warm Redis, confirm consumer count at 1.5×
  During event: dedicated dashboard for event group_ids
  On-call: assign cricket-specific engineer (not general on-call)
```

---

---

## Design Gates (mandatory) - Model Responses

These responses are intentionally gate-shaped rather than a second full design.
Use them to verify the design explicitly covers trust, abuse, tenancy, cost,
and blast radius.

### Gate 1 - Authn/z trust boundary

- State every principal: external user, internal service, admin/support actor,
  background worker, tenant, and third-party partner where applicable.
- Put the first trust boundary at the public edge or private service ingress,
  then name the enforcement point that owns object/action authorization.
- Accept only scoped identity artifacts with issuer, audience, expiry, and
  key/certificate validation. Service-to-service calls should use workload
  identity or mTLS, not ambient network trust.
- Fail closed for money, privacy, admin, and write paths. Degrade or serve
  cached public content only where policy explicitly allows it.

### Gate 2 - Abuse and misuse

- Identify the highest-amplification actor in `Design WhatsApp`: the one that can turn
  one request into many writes, fetches, fan-outs, model calls, or downstream
  retries.
- Use layered quotas: user/API key, tenant/tier, entity key, endpoint/job
  class, region/cell, and global safety cap.
- Distinguish organic flash traffic from abuse with per-key skew, user-agent
  or principal entropy, retry rate, error mix, and historical baselines.
- Bound retries with budgets, jitter, circuit breakers, and idempotency keys.

### Gate 3 - Multi-tenant isolation

- Name the tenancy model for every stateful plane: relational data, cache,
  queue/topic, object storage, search index, model/vector store, metrics, logs,
  and support exports.
- Tenant context must be explicit in APIs, async messages, cache keys, search
  filters, audit logs, and support tooling. Missing tenant context fails closed.
- Reserve or quota shared scarce resources: DB connections, Kafka partitions
  and bytes, cache memory/ops, worker concurrency, indexing bandwidth, and
  third-party API calls.
- Prove isolation with cross-tenant cache/search/export tests, route-map tests,
  and incident kill switches for one tenant or cell.

### Gate 4 - Unit cost at target scale

- Define one business unit and compute order-of-magnitude cost at target scale
  and at peak multiplier. Include idle headroom and replication, not only
  request CPU.
- Dominant line items usually include storage retention, egress/cross-AZ or
  cross-region transfer, observability ingest, model/API calls, NAT, cache
  memory, and replay/rebuild capacity.
- Page on cost per successful business unit and slope by feature/deploy/tenant,
  not only monthly spend after the fact.
- Preferred degradation cuts optional analytics, freshness, ranking depth,
  export concurrency, or non-critical replicas before correctness-critical
  writes and reads.

### Gate 5 - Failure blast radius

- Declare the intended blast-radius boundary: partition, shard, tenant, topic,
  cell, region, queue, worker pool, cache namespace, or model version.
- Separate critical and non-critical paths so analytics, exports, replay,
  recommendation/ranking, or support tooling cannot starve checkout, payment,
  auth, or core serving.
- Document runbook hazards: global cache flush, raising max connections,
  disabling auth, removing rate limits, replaying without throttle, or widening
  a feature flag globally.
- Game day the highest-risk boundary and verify alerts fire before customer or
  tenant-wide impact.


---
