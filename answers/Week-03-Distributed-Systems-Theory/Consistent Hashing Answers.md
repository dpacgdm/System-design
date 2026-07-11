# Answer Key - Consistent Hashing

> Open only after attempting the learner file Ops Sim.

## Ops Sim: Northstar Session Ring Hot Workspace

### Q1 - Layer & root cause

Consistent hashing distributes keys/slots, not load inside one key. If one workspace session key receives 91k ops/min, every operation still goes to the node owning that key's slot.

Root cause: key design aggregates a large seller workspace into one hot key. Resharding slots does not split the key.

### Q2 - Evidence

- Slot counts are nearly equal across masters.
- One key accounts for 88% of hot-key samples.
- master-2 CPU and p99 are high while other masters are normal.
- Resharding causes ASK/MOVED redirects but does not remove the hot key.

### Q3 - First 15 minutes

1. Stop/pause resharding if safe; avoid extra I/O on the hot master.
2. Degrade optional presence/typing features for affected seller workspace.
3. Prevent session timeouts from being treated as logout; serve stale session for a short bounded window if auth token remains valid.
4. Add local/request coalescing for the hot workspace key.
5. Protect auth-service by throttling rebuilds and increasing connection headroom only if verified safe.
6. Monitor Redis CPU/p99, auth rebuild QPS, DB pool, and seller control-plane errors.

### Q4 - Bad fixes

Resharding an overloaded node reads and migrates keys from the node that is already saturated. During migration, ASK redirects add round trips and client overhead.

Treating Redis timeouts as logouts turns a cache/session latency issue into an auth storm and user-visible outage. Timeout should mean "unknown; retry/bounded stale," not immediate session deletion.

### Q5 - Capacity / blast radius

Auth rebuild QPS increased:

```text
6,400 / 900 ~= 7.1x
```

Next likely failures: auth-service worker saturation, auth DB/PgBouncer connection exhaustion, and login rate-limit false positives.

### Q6 - Durable fix

New key design:

```text
session:workspace:{workspace_id}:shard:{hash(user_id) % 64}
presence:workspace:{workspace_id}:segment:{region_or_role}:{bucket}
```

Use client-side scatter/gather only for dashboard summaries, not per-request hot paths. Add top-key alerts, reshard preconditions, and a rule: never reshard a saturated master without first reducing hot-key traffic.

### Q7 - Org / runbook

Notify incident commander, seller platform owner, Redis/session owner, auth owner, auction operations, and support.

Allowed degradation: presence/typing indicators, non-critical live analytics, and stale dashboard widgets. Not allowed: losing seller auth/session state or disabling auction controls without business approval.
# Answer Key — Consistent Hashing

> Open only after attempting the learner file questions.

---

# Incident Deep-Dive: Global Session Store Migration Gone Wrong

---

## Q1: Why Consistent Hashing Cannot Solve This Hot-Node Problem

### a) Why Consistent Hashing Fails Here

```
Consistent hashing solves ONE problem: distributing
MANY KEYS evenly across MANY NODES so that adding
or removing a node only remaps a minimal subset of keys.

It CANNOT solve the HOT KEY problem.

THE DISTINCTION:

  HOT PARTITION: Many keys land on the same node due
  to uneven distribution. Consistent hashing WITH
  vnodes solves this — 150 vnodes per node produces
  near-uniform distribution.

  HOT KEY: One SINGLE KEY receives disproportionate
  traffic regardless of which node it's on. Moving
  the key to another node just makes THAT node hot.

Master-2's problem is NOT uneven slot distribution.
It has 2730 slots — almost exactly 1/6 of 16384.
The distribution is PERFECT.

The problem is that ONE KEY — session:workspace:acme-corp
— receives 820 reads/sec. This single key hashes to
ONE slot, which lives on ONE master. No amount of
resharding, rebalancing, or vnode tuning changes this.

  ╔══════════════════════════════════════════════════════════════╗
  ║   CONSISTENT HASHING DISTRIBUTES KEYS.                       ║
  ║   IT CANNOT DISTRIBUTE A SINGLE KEY.                         ║
  ║                                                              ║
  ║   CRC16("session:workspace:acme-corp") = 4127                ║
  ║   Slot 4127 → master-2. ALWAYS.                              ║
  ║                                                              ║
  ║   Even if you reshard slot 4127 to master-7:                 ║
  ║   → master-7 now gets 820 reads/sec                          ║
  ║   → master-7 becomes the new hot node                        ║
  ║   → You've MOVED the problem, not solved it                  ║
  ║                                                              ║
  ║   Resharding redistributes slots.                            ║
  ║   It doesn't split traffic within a slot.                    ║
  ║   It doesn't split traffic to a single key.                  ║
  ╚══════════════════════════════════════════════════════════════╝
```

### b) The Key Design Decision That Created This Hot Spot

```
The design decision: using a SINGLE KEY per workspace
for shared mutable state that ALL workspace members
read from.

  session:workspace:acme-corp → {
    presence: {user1: online, user2: away, ...},  // 47,000 entries
    typing: {channel1: [user5, user9], ...},
    active_channels: [general, engineering, ...],
    notification_state: {...}
  }

47,000 users polling presence/typing indicators for
their workspace. ALL of them read the SAME key. The
key becomes a convergence point — every user in the
workspace funnels through one Redis slot on one master.

IN MEMCACHED, THIS WAS HIDDEN:
  Memcached's consistent hashing with 150 vnodes per
  node and 20 nodes distributed the load differently.
  The workspace key still went to ONE node, but:
  → 20 nodes meant each node had 5% of keys (vs 16.7%
    with 6 masters)
  → Memcached is simpler (no cluster protocol, no slot
    redirection) — pure get/set with lower per-operation
    CPU cost
  → The workspace key was hot on Memcached too, but the
    node could absorb it because Memcached is more
    CPU-efficient for simple key-value operations

  Moving to Redis Cluster with 6 masters (vs 20 Memcached
  nodes) concentrated traffic onto fewer nodes. The hot
  key that was "warm" on Memcached became "scalding" on
  Redis.

THE ROOT CAUSE IS THE DATA MODEL:
  Shared mutable state for N users should not live in
  a single key when N can be 47,000. This is a
  fan-in/fan-out problem disguised as a caching problem.
```

### c) Fix: Eliminate the Hot Key

```
APPROACH: Shard the workspace session data across
multiple keys, distributed across multiple slots
(and therefore multiple masters).

OLD KEY STRUCTURE (hot key):
  session:workspace:acme-corp → {everything}
  CRC16 → slot 4127 → master-2 → ALL 820 reads/sec

NEW KEY STRUCTURE (sharded):

  # Presence: shard by user_id hash
  session:workspace:acme-corp:presence:{shard_id}

  # 16 presence shards (adjustable per workspace size):
  session:workspace:acme-corp:presence:0   → slot X → master-1
  session:workspace:acme-corp:presence:1   → slot Y → master-4
  session:workspace:acme-corp:presence:2   → slot Z → master-6
  ...
  session:workspace:acme-corp:presence:15  → slot W → master-3

  # Each user's presence goes to:
  shard_id = CRC16(user_id) % 16
  key = f"session:workspace:acme-corp:presence:{shard_id}"

  # Typing indicators: shard by channel_id
  session:workspace:acme-corp:typing:{channel_id}

  # Each channel's typing state is its own key:
  session:workspace:acme-corp:typing:general     → slot A
  session:workspace:acme-corp:typing:engineering → slot B
  session:workspace:acme-corp:typing:random      → slot C

  # Active channels: per-user (not shared)
  session:user:{user_id}:active_channels

  # This was never shared state — it's per-user.
  # It was incorrectly bundled into the workspace key.

TRAFFIC DISTRIBUTION AFTER SHARDING:

  BEFORE: 1 key × 820 reads/sec = 820 reads/sec on ONE node

  AFTER:  16 presence shards across multiple masters:
          → ~51 reads/sec per shard, spread across 6 masters
          → No single master gets more than ~140 reads/sec
            from acme-corp presence alone (3 shards per master)

          Typing indicators: per-channel keys
          → acme-corp has ~200 channels
          → ~4 reads/sec per channel (most channels are quiet)
          → Spread across all 6 masters

          Active channels: per-user keys
          → Already distributed by user_id across all masters
          → No hot key possible

  ╔══════════════════════════════════════════════════════════════╗
  ║   Node 1: ~140 reads/s (presence shards 0,5,11)              ║
  ║   Node 2: ~135 reads/s (presence shards 2,8,14)              ║
  ║   Node 3: ~130 reads/s (presence shards 3,6,12)              ║
  ║   Node 4: ~140 reads/s (presence shards 1,9,13)              ║
  ║   Node 5: ~125 reads/s (presence shards 4,7,15)              ║
  ║   Node 6: ~150 reads/s (presence shards 10 + typing)         ║
  ║                                                              ║
  ║   vs BEFORE: Node 2: 820 reads/s, others: ~30 reads/s        ║
  ╚══════════════════════════════════════════════════════════════╝

IMPLEMENTATION NOTE ON REDIS HASH TAGS:

  Redis Cluster determines the slot using hash tags:
  if a key contains {tag}, only the tag portion is hashed.

  DO NOT USE: session:{acme-corp}:presence:0
  This would hash ONLY "acme-corp" → ALL shards land
  on the same slot → defeats the purpose entirely.

  DO USE: session:workspace:acme-corp:presence:0
  No hash tags → the FULL key is hashed → each shard
  lands on a different slot → distributed across masters.

  TRADEOFF: Without hash tags, you CANNOT use Redis
  multi-key operations (MGET, transactions) across
  shards. Each shard must be read independently.

  This is acceptable: presence reads are already
  per-channel or per-view, not "give me all 47,000
  users' presence in one operation."

READ PATTERN FOR CLIENTS:

  # When a user opens a channel, they need:
  # 1. Their own session (already per-user key)
  # 2. Presence for users IN THAT CHANNEL (not all 47K)
  # 3. Typing indicators for that channel

  async def get_channel_view(user_id, channel_id, workspace_id):
      # Get channel members (from separate service/DB)
      members = await get_channel_members(channel_id)

      # Determine which presence shards we need
      shards_needed = set()
      for member_id in members:
          shard = crc16(member_id) % 16
          shards_needed.add(shard)

      # Fetch presence from each shard (parallel)
      presence_tasks = [
          redis.hgetall(
              f"session:workspace:{workspace_id}:presence:{shard}"
          )
          for shard in shards_needed
      ]
      presence_results = await asyncio.gather(*presence_tasks)

      # Fetch typing for this channel (single key)
      typing = await redis.smembers(
          f"session:workspace:{workspace_id}:typing:{channel_id}"
      )

      # Assemble and return
      return ChannelView(
          presence=merge_presence(presence_results, members),
          typing=typing
      )
```

---

## Q2: Why Resharding Was Wrong and What To Do Instead

### a) Why Resharding an Overloaded Node Makes Things Worse

```
RESHARDING MECHANICS:

  redis-cli --cluster reshard moves slots from a source
  node to a target node. For each slot, it:

  1. Sets the slot to MIGRATING state on source node
  2. Sets the slot to IMPORTING state on target node
  3. For EVERY KEY in that slot:
     a) DUMP the key on source (serializes to memory)
     b) RESTORE the key on target (deserializes, writes)
     c) DEL the key on source (after confirmed on target)
  4. Update cluster slot ownership

  EACH KEY MIGRATION IS:
  → A full key read on the source node (CPU + memory)
  → A serialization operation (CPU)
  → A network transfer (bandwidth)
  → A write on the target node
  → A deletion on the source node

MASTER-2's STATE AT 12:05:
  → CPU: 92%
  → Serving 820+ reads/sec for acme-corp alone
  → Serving normal traffic for all other keys in
    2730 slots
  → p99 latency already at 89ms (degraded)

WHAT THE RESHARD DOES TO MASTER-2:

  ╔══════════════════════════════════════════════════════════════╗
  ║   EXISTING LOAD:                                             ║
  ║   → 820 reads/sec (acme-corp)                                ║
  ║   → ~300 reads/sec (other workspace keys)                    ║
  ║   → ~1500 reads/sec (individual session keys)                ║
  ║   → Total: ~2620 reads/sec                                   ║
  ║   → CPU: 92%                                                 ║
  ║                                                              ║
  ║   RESHARD ADDS:                                              ║
  ║   → DUMP + serialize for every key in 683 slots              ║
  ║   → Each slot may have hundreds or thousands of              ║
  ║     keys (4M sessions / 16384 slots ≈ 244 keys               ║
  ║     per slot average)                                        ║
  ║   → 683 slots × 244 keys = ~166,000 keys to                  ║
  ║     serialize and transfer                                   ║
  ║   → Each DUMP+DEL is CPU work on an already-                 ║
  ║     saturated node                                           ║
  ║                                                              ║
  ║   IMMEDIATE EFFECT:                                          ║
  ║   → CPU: 92% → 99% (migration I/O added)                     ║
  ║   → Latency: 89ms → seconds (CPU saturated)                  ║
  ║   → ALL keys on master-2 affected (not just the              ║
  ║     migrating slots — CPU is shared)                         ║
  ║   → Users on master-2 who had nothing to do with             ║
  ║     acme-corp now experience degradation                     ║
  ║   → BLAST RADIUS EXPANDED from "acme-corp users"             ║
  ║     to "all users with sessions on master-2"                 ║
  ║                                                              ║
  ║   EVENTUAL EFFECT (if it completes):                         ║
  ║   → master-2 has fewer slots → less load                     ║
  ║   → But the HOT KEY is still on master-2                     ║
  ║     (unless you specifically moved slot 4127)                ║
  ║   → Even then: master-7 just becomes hot                     ║
  ╚══════════════════════════════════════════════════════════════╝

  TIMELINE:

  LOAD ▲
       │   ╔══════════════════════════════════╗
  100% │───║─reshard─starts──────────────────║──────
       │   ║                                  ║
   92% │───║──────────────────────────────────║──────
       │   ║        migration I/O overhead    ║
       │   ║                                  ║
       │   ╚══════════╗                       ║
       │              ║  if reshard completes  ║
       │              ║  load EVENTUALLY drops ║
       │              ╚═══════════════════════╝
       │                         maybe here: 70%?
       │                         BUT hot key still here
       ╰────────────────────────────────────────────► time
           12:05   12:10    12:15    12:20

  The reshard makes the patient SICKER before the
  medicine works. On a node at 92% CPU, the additional
  I/O pushes it past the point of recovery. The node
  becomes so slow that the cluster declares it dead
  and triggers a failover — which interrupts the
  reshard and creates an INCONSISTENT STATE.

  The cure was worse than the disease.
```

### b) What They Should Have Done Instead

```
IMMEDIATE MITIGATION (should have done at 12:05):

STEP 1: REDUCE TRAFFIC TO THE HOT KEY (seconds to execute)

  The hot key is session:workspace:acme-corp. 47,000
  users polling presence from it. The application
  layer can absorb this WITHOUT touching Redis.

  Option A: Application-level local cache for hot keys

  # In each application server's memory (Caffeine/Guava):
  # Cache the hot workspace key with a 500ms TTL.
  # 47,000 users hitting 50 app servers = 940 users/server
  # Instead of 940 Redis reads/sec/server → 2 reads/sec/server
  # (one cache miss every 500ms)
  # Total Redis reads: 50 servers × 2/sec = 100 reads/sec
  # Down from 820 reads/sec → 87% reduction

  async def get_workspace_presence(workspace_id):
      cache_key = f"workspace_presence:{workspace_id}"

      cached = local_cache.get(cache_key)
      if cached:
          return cached  # In-memory hit, no Redis call

      # Cache miss: read from Redis
      result = await redis.get(
          f"session:workspace:{workspace_id}"
      )
      local_cache.set(cache_key, result, ttl_ms=500)
      return result

  # This can be deployed as a feature flag toggle:
  # HOT_KEY_LOCAL_CACHE=true
  # Enable it in 30 seconds via config push.

  Option B: Rate-limit reads to the hot key

  # If local caching isn't available, throttle at the
  # Redis proxy layer:
  # Allow max 100 reads/sec to any single key.
  # Excess reads get a cached response from the proxy.

  EITHER OPTION: master-2 CPU drops from 92% to ~45%
  within seconds of deployment. Crisis averted.

STEP 2: STOP DUAL-WRITES TO MEMCACHED (minutes)

  The system is currently dual-writing to both Memcached
  AND Redis. This doubles write load. Since reads are
  already on Redis (Phase 2 complete), Memcached writes
  are pure waste.

  # Disable Memcached writes:
  feature_flag.set("DUAL_WRITE_MEMCACHED", False)

  This doesn't help master-2 specifically (the hot key
  is a READ problem, not a write problem), but it
  reduces overall Redis write load and frees CPU
  headroom across all masters.

STEP 3: VERIFY STABILIZATION (5-10 minutes)

  # Monitor master-2 CPU, latency, error rate
  # Expect: CPU < 50%, p99 < 5ms, error rate < 0.1%
  # ONE CHANGE → VERIFY → NEXT CHANGE

  redis-cli -h master-2 INFO cpu
  redis-cli -h master-2 INFO stats | grep instantaneous_ops
  redis-cli -h master-2 --latency-history -i 5
```

### c) When Resharding Becomes Appropriate

```
PRECONDITIONS FOR RESHARDING:

  1. NODE CPU < 50% (headroom for migration overhead)
     → The reshard itself consumes 10-30% additional CPU
     → At 50% base, you peak at 80% during migration
     → At 92% base, you peak at >100% → cascade failure

  2. HOT KEY MITIGATED FIRST
     → The hot key problem is solved via key sharding
       (Q1c) or application-level caching
     → Resharding without solving the hot key just
       MOVES the hot key to another node

  3. LOW TRAFFIC PERIOD
     → Reshard during off-peak hours (3-5 AM local time)
     → Migration I/O competes with user traffic
     → Lower baseline = more headroom for migration

  4. MIGRATION THROTTLED
     → redis-cli --cluster reshard supports
       --cluster-pipeline option to batch key migrations
     → Set a low pipeline count to throttle migration speed
     → Slower migration = less I/O spike = safer

  5. FAILOVER PREVENTION DURING RESHARD
     → Temporarily increase cluster-node-timeout to prevent
       false failover detection during migration-induced
       latency spikes (covered in Q3c)

  6. ROLLBACK PLAN DEFINED
     → If migration causes CPU > 80% on source, STOP
     → Slots partially migrated can be rolled back with:
       redis-cli --cluster fix (repairs inconsistent slots)

  WHEN TO RESHARD:
  → After Steps 1-3 from (b) above stabilize the node
  → During the next maintenance window (off-peak)
  → With the hot key already sharded (Q1c fix deployed)
  → With preconditions 1-6 all satisfied
  → NOT during an active incident. NEVER during an
    active incident.
```

---

## Q3: Failover During Reshard — Consistency Violation and Recovery

### a) Consistency Model Violation

```
THE VIOLATION: LINEARIZABILITY for keys in the
migrating slots.

During a reshard, slots in MIGRATING/IMPORTING state
have a specific protocol:

  1. Client requests key K in a MIGRATING slot on master-2
  2. If K still EXISTS on master-2 → serve it normally
  3. If K has been MIGRATED to master-7 → respond with
     ASK redirect → client re-asks master-7
  4. This provides linearizability: every key is served
     from exactly ONE authoritative source at all times

THE FAILOVER BROKE THIS PROTOCOL:

  Old master-2 (now demoted):
  → Had slots in MIGRATING state
  → Had already deleted some keys (migrated to master-7)
  → Had NOT yet deleted other keys (migration in progress)

  New master-2 (promoted replica):
  → Was an async replica of old master-2
  → Was BEHIND old master-2 (async replication lag)
  → Has NO knowledge of MIGRATING state
     (replication doesn't replicate cluster slot metadata)
  → Has OLD versions of keys that were already migrated
  → Does NOT have keys that were written to old master-2
     after the replica's last sync

  Master-7 (migration target):
  → Has keys that were successfully migrated from old
     master-2 before the failover
  → Believes it OWNS those slots (IMPORTING state
     partially complete)
  → But new master-2 ALSO believes it owns those slots
     (it inherited slot ownership from old master-2's
     cluster config, minus the MIGRATING metadata)

  RESULT — SPLIT OWNERSHIP:

  ╔══════════════════════════════════════════════════════════════╗
  ║  KEY STATE  │ NEW MASTER-2  │ MASTER-7                       ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Key A      │ HAS (old ver) │ HAS (new ver)                  ║
  ║  (migrated  │ Stale copy    │ Current copy                   ║
  ║   before    │ from replica  │ received via                   ║
  ║   failover) │ replication   │ RESTORE                        ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Key B      │ HAS           │ DOESN'T HAVE                   ║
  ║  (not yet   │ (current)     │                                ║
  ║   migrated) │               │                                ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Key C      │ DOESN'T HAVE  │ DOESN'T HAVE                   ║
  ║  (written   │ (replica was  │ (not yet                       ║
  ║   to old    │ behind)       │  migrated)                     ║
  ║   master-2  │               │                                ║
  ║   after     │               │                                ║
  ║   replica   │               │                                ║
  ║   sync)     │               │                                ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Key D      │ HAS           │ HAS                            ║
  ║  (migrated  │ (old version  │ (new version                   ║
  ║   but DEL   │  from before  │  received via                  ║
  ║   not yet   │  replica lag) │  RESTORE)                      ║
  ║   replicated│               │                                ║
  ║   to replica│               │                                ║
  ║   before    │               │                                ║
  ║   failover) │               │                                ║
  ╚══════════════════════════════════════════════════════════════╝

  VIOLATIONS:

  1. LINEARIZABILITY VIOLATED (Key A, Key D):
     Two nodes both have the key. Which is authoritative?
     New master-2 believes it owns the slot.
     Master-7 has the NEWER version from the migration.
     A client reading from new master-2 gets STALE data.
     A client redirected to master-7 gets NEWER data.
     The system has lost its single-source-of-truth
     for these keys.

  2. DURABILITY VIOLATED (Key C):
     The key was written to old master-2 and acknowledged
     to the client. But async replication hadn't synced
     it to the replica. After failover, the key is GONE.
     An acknowledged write has been lost. This is the
     async replication durability gap — the same failure
     mode as the double-debit scenario from the teaching
     material.

  3. MONOTONIC READS VIOLATED:
     A client that read Key A from old master-2 (new value)
     now reads from new master-2 (old value from replica).
     The value went BACKWARD. Time travel.
```

### b) Recovery Procedure

```
RECOVERY: Fix slot ownership and key conflicts between
new master-2 and master-7.

STEP 1: STOP ALL CLIENT WRITES TO AFFECTED SLOTS

  # Identify which slots are in inconsistent state.
  # These are the slots that were in MIGRATING state
  # on old master-2 when the failover happened.
  # Slots 2731-3413 were being moved. The reshard was
  # 60% complete at 12:12, so approximately:
  # Slots 2731-3140: fully migrated to master-7 (~410 slots)
  # Slots 3141-3413: in-flight or not yet started (~273 slots)

  # Check actual state:
  redis-cli --cluster check <any-cluster-node>:6379

  # This will show:
  # [ERR] Nodes disagree about configuration!
  # [ERR] Slots X-Y are open (MIGRATING/IMPORTING state)
  # [ERR] Slots A-B have multiple owners

STEP 2: USE redis-cli --cluster fix TO RESOLVE

  redis-cli --cluster fix <any-cluster-node>:6379

  # What --cluster fix does for each inconsistent slot:
  #
  # Case 1: Slot has IMPORTING flag on master-7 but no
  #   MIGRATING flag on new master-2 (because the promoted
  #   replica doesn't have the migration metadata):
  #   → Clears the IMPORTING flag on master-7
  #   → Assigns slot ownership back to new master-2
  #   → Keys that were already migrated to master-7
  #     are now ORPHANED on master-7 (exist but the
  #     slot is owned by new master-2)
  #
  # Case 2: Both nodes claim to own the slot:
  #   → fix resolves based on cluster consensus
  #   → Typically assigns to the node that the majority
  #     of the cluster agrees on

  # PROBLEM: --cluster fix resolves SLOT OWNERSHIP but
  # does NOT reconcile KEY CONFLICTS.
  # Key A may exist on both nodes with different versions.
  # Key C may exist on neither.

STEP 3: RECONCILE KEYS IN FORMERLY-MIGRATING SLOTS

  # For slots that were fully migrated (2731-3140):
  # master-7 has the AUTHORITATIVE data (it received
  # the keys via migration, which includes the latest
  # version from old master-2).
  # New master-2 has STALE data (from async replication
  # which was behind).

  # Decision: master-7's data wins for these slots.
  # Re-assign slots 2731-3140 to master-7:

  redis-cli --cluster reshard <node>:6379 \
    --cluster-from <new-master-2-id> \
    --cluster-to <master-7-id> \
    --cluster-slots 410 \
    --cluster-yes

  # BUT WAIT — we just said resharding an overloaded
  # node is dangerous. New master-2 is no longer at
  # 99% CPU (it's a fresh replica with less data),
  # and traffic has been disrupted (23% miss rate means
  # many requests aren't hitting Redis at all).
  # CPU should be lower. Verify before proceeding:

  redis-cli -h new-master-2 INFO cpu
  # If used_cpu_sys < 50%: safe to reshard these slots

  # For slots that were in-flight (3141-3413):
  # Neither node may have complete data.
  # New master-2 has whatever the replica had (potentially
  # stale). Master-7 has partial data (some keys migrated,
  # some not).

  # SAFEST APPROACH: Assign these slots to new master-2.
  # Accept that some keys are lost (Key C scenario).
  # The application must handle cache misses gracefully
  # (rebuild session from auth service).

  redis-cli --cluster setslot <slot> NODE <new-master-2-id>
  # Repeat for each slot in 3141-3413 range

  # Delete orphaned keys on master-7 for slots owned
  # by new master-2 (they're stale copies):
  for slot in range(3141, 3414):
      keys = redis_cli(f"CLUSTER GETKEYSINSLOT {slot} 1000",
                        host="master-7")
      for key in keys:
          redis_cli(f"DEL {key}", host="master-7")

STEP 4: VERIFY CLUSTER HEALTH

  redis-cli --cluster check <node>:6379
  # Expected: [OK] All 16384 slots covered
  # No ERR messages
  # All nodes agree on slot ownership

  redis-cli --cluster info <node>:6379
  # Verify key counts per master are reasonable

  # Run application-level health check:
  # Pick 100 random sessions, verify they're readable
  # Check error rate: should drop from 4.7% to < 0.1%
```

### c) Preventing Failover During Reshard

```
THE CONFIGURATION: cluster-node-timeout

  # Default: 15000ms (15 seconds)
  # If a master doesn't respond to PING within this
  # window, replicas initiate failover.

  # At 12:10, master-2 was at 99% CPU. Response times
  # to PING exceeded 15 seconds. The replica interpreted
  # this as "master is down" and triggered failover.

  # But master-2 wasn't DOWN — it was SLOW. The
  # reshard's I/O load pushed response times above
  # the timeout threshold.

PREVENTION — INCREASE TIMEOUT BEFORE RESHARD:

  # Before starting any reshard operation:
  redis-cli -h master-2 CONFIG SET cluster-node-timeout 60000
  redis-cli -h replica-2 CONFIG SET cluster-node-timeout 60000

  # Set on ALL nodes (replicas won't trigger failover
  # unless the timeout is exceeded):
  for node in $(redis-cli --cluster nodes | awk '{print $2}'); do
    redis-cli -h ${node%:*} -p ${node#*:} \
      CONFIG SET cluster-node-timeout 60000
  done

  # 60 seconds gives the overloaded node time to be
  # slow without being declared dead.

  # AFTER reshard completes: restore original timeout
  for node in $(redis-cli --cluster nodes | awk '{print $2}'); do
    redis-cli -h ${node%:*} -p ${node#*:} \
      CONFIG SET cluster-node-timeout 15000
  done

ADDITIONAL SAFEGUARD — DISABLE AUTOMATIC FAILOVER:

  # On the specific replica of the resharding node:
  redis-cli -h replica-2 CLUSTER FAILOVER ABORT

  # Or: temporarily set the replica to not participate
  # in elections:
  redis-cli -h replica-2 CONFIG SET cluster-replica-no-failover yes

  # This PREVENTS the replica from initiating failover
  # under ANY circumstances.
  # Risk: if master-2 truly dies during reshard, there's
  # no automatic failover. Manual intervention required.
  # But that's BETTER than an automatic failover that
  # corrupts the migration state.

  # Re-enable after reshard:
  redis-cli -h replica-2 CONFIG SET cluster-replica-no-failover no

TRADEOFF:
  → During the reshard window: no automatic failover
    for the resharding node
  → If the node truly crashes: manual intervention needed
    (slower recovery, ~5-10 minutes)
  → But: this prevents the CATASTROPHIC outcome of a
    failover during migration, which is far worse than
    a brief manual recovery
  → Increased timeout + disabled auto-failover is the
    standard operational practice for Redis Cluster
    resharding in production
```

---

## Q4: Proper Migration Plan

```
╔══════════════════════════════════════════════════════════════╗
║   MIGRATION PLAN: MEMCACHED → REDIS CLUSTER                  ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   DESIGN PRINCIPLES:                                         ║
║   1. Detect problems BEFORE they affect users                ║
║   2. Maintain rollback capability at EVERY phase             ║
║   3. One change at a time → verify → next change             ║
║   4. The hashing algorithm change is a MIGRATION             ║
║      of key mapping, not just a backend swap                 ║
║                                                              ║
║   TOTAL PHASES: 6 (not 3)                                    ║
║   ESTIMATED DURATION: 3-4 weeks                              ║
╚══════════════════════════════════════════════════════════════╝
```

### Phase 0: Pre-Migration Analysis [Week 1]

```
OBJECTIVE: Understand traffic patterns BEFORE touching
anything. Find hot keys before they find you.

STEP 1: KEY ACCESS PROFILING ON MEMCACHED

  # Enable Memcached verbose logging (or use extstore
  # metrics, or proxy-level logging):

  # Use mcrouter (Facebook's Memcached proxy) or
  # mctop (Memcached top):
  mctop --host memcached-node1 --port 11211 --sort calls

  # Run for 24 hours during peak traffic.
  # Identify:
  # → Top 100 keys by read frequency
  # → Top 100 keys by size
  # → Keys with read:write ratio > 100:1 (hot reads)
  # → Keys with size > 10KB (large values)

  EXPECTED FINDING:
  → session:workspace:acme-corp — 820 reads/sec
  → session:workspace:globex — 340 reads/sec
  → session:workspace:initech — 290 reads/sec
  → These workspace keys are HOT KEYS.

STEP 2: KEY REDESIGN

  → BEFORE migration, redesign the workspace key
    structure (Q1c solution):
    → Shard presence by user_id
    → Shard typing by channel_id
    → Move active_channels to per-user keys

  → Deploy the new key structure to Memcached FIRST.
  → Run for 1 week. Verify hot keys are eliminated.
  → The key sharding fix is independent of the
    Memcached → Redis migration. Do it first.

  RATIONALE: Fix the data model BEFORE changing the
  infrastructure. Two simultaneous changes = impossible
  to diagnose if something goes wrong.

STEP 3: HASHING ALGORITHM ANALYSIS

  Memcached consistent hashing and Redis CRC16 slot
  mapping produce COMPLETELY DIFFERENT key distributions.

  # For every active key in Memcached, compute:
  memcached_node = consistent_hash(key, nodes=20, vnodes=150)
  redis_slot = CRC16(key) % 16384
  redis_master = slot_to_master(redis_slot)

  # Build a heat map:
  # For each Redis master, sum the access frequency of
  # all keys that will land on it.
  #
  # If any master's projected load is >2x the average:
  # → Adjust the slot distribution BEFORE migration
  # → Or add more masters to reduce per-node load

STEP 4: REDIS CLUSTER SIZING

  Current Memcached: 20 nodes, ~16GB total
  Proposed Redis: 6 masters → too few.

  SIZING CALCULATION:
  → 4M sessions × 4KB = 16GB data
  → Memcached spreads across 20 nodes = 800MB per node
  → Redis 6 masters = 2.67GB per node (3.3x more per node)
  → Redis is more CPU-intensive than Memcached per
    operation (richer data structures, cluster protocol)
  → 6 masters cannot absorb 20 Memcached nodes' worth
    of load, even without hot keys

  RECOMMENDATION: Start with 12 masters (not 6).
  → 1.33GB per master, ~333K sessions per master
  → More headroom for CPU spikes
  → Slots better distributed
  → Can scale down later if over-provisioned
    (removing nodes is safer than adding under pressure)

ROLLBACK: N/A (this phase is analysis only, no
production changes except the key redesign, which
rolls back by reverting the application code).
```

### Phase 1: Shadow Reads [Week 2, Days 1-3]

```
OBJECTIVE: Prove Redis returns the SAME data as Memcached
for every read, at acceptable latency, without affecting
users.

IMPLEMENTATION:
  Every read request goes to MEMCACHED (the source of
  truth). In parallel, a SHADOW READ goes to Redis.
  The Redis result is COMPARED to the Memcached result
  but NOT returned to the user.

  async def get_session(session_key):
      # Primary read: Memcached (user sees this)
      mc_result = await memcached.get(session_key)

      # Shadow read: Redis (user doesn't see this)
      try:
          redis_result = await asyncio.wait_for(
              redis.get(session_key), timeout=0.05  # 50ms
          )
          # Compare
          if redis_result and mc_result:
              if redis_result != mc_result:
                  metrics.increment("shadow_read.mismatch")
                  log.warn(f"Mismatch: key={session_key}")
              else:
                  metrics.increment("shadow_read.match")
          elif mc_result and not redis_result:
              metrics.increment("shadow_read.redis_miss")
          # Redis miss is expected initially — dual-write
          # hasn't run long enough to populate everything
      except asyncio.TimeoutError:
          metrics.increment("shadow_read.redis_timeout")

      return mc_result  # Always return Memcached result

METRICS TO WATCH:
  → shadow_read.mismatch: should be 0% after warm-up
  → shadow_read.redis_miss: should decrease over time
    as dual-write populates Redis
  → shadow_read.redis_timeout: should be < 0.1%
  → Redis node CPU: verify no hot node developing
  → Redis p99 latency: should be < 5ms

  ╔══════════════════════════════════════════════════════════════╗
  ║   KEY INSIGHT: Shadow reads reveal the hot key               ║
  ║   problem BEFORE it affects users. If master-2               ║
  ║   shows 78% CPU during shadow reads, you KNOW                ║
  ║   it will be worse under real read traffic.                  ║
  ║   You can fix it (Q1c) before Phase 2.                       ║
  ╚══════════════════════════════════════════════════════════════╝

EXIT CRITERIA FOR PHASE 1:
  → Mismatch rate: 0% for 48 hours
  → Redis miss rate: < 2%
  → Redis p99: < 5ms
  → NO hot node (max CPU across masters < 40%)
  → All criteria met for 48 consecutive hours

ROLLBACK: Remove shadow read code path. Zero user impact
(shadow reads were never user-facing).
```

### Phase 2: Dual-Write [Week 2, Day 3 — ongoing]

```
OBJECTIVE: Every write goes to both Memcached and Redis.
Reads still from Memcached.

  async def write_session(session_key, session_data, ttl):
      # Primary: Memcached
      await memcached.set(session_key, session_data, ttl)

      # Secondary: Redis (async, fire-and-forget with retry)
      try:
          await asyncio.wait_for(
              redis.set(session_key, session_data, ex=ttl),
              timeout=0.05
          )
      except Exception as e:
          # Log and retry asynchronously
          # DO NOT fail the user's request because Redis
          # write failed. Memcached is still primary.
          await retry_queue.enqueue(
              "redis_write", session_key, session_data, ttl
          )
          metrics.increment("dual_write.redis_failure")

  # Redis write failures: queue and retry.
  # If retry queue grows: Redis is unhealthy → investigate
  # before proceeding to Phase 3.

EXIT CRITERIA:
  → dual_write.redis_failure rate: < 0.01%
  → Shadow read mismatch: 0% (still running from Phase 1)
  → Redis hit rate on shadow reads: > 99%
  → No hot nodes on Redis

ROLLBACK: Stop Redis writes. Memcached remains primary.
No user impact.
```

### Phase 3: Canary Read Switch [Week 3, Days 1-3]

```
OBJECTIVE: Switch a SMALL percentage of reads to Redis.
Validate with real user traffic. Detect problems at
small blast radius.

  CANARY STRATEGY:
  → 1% of reads from Redis (99% still Memcached)
  → Target: non-critical workspaces first
    (internal test workspaces, low-activity workspaces)
  → Exclude top-10 workspaces by size from canary

  → If 1% clean for 4 hours: increase to 5%
  → If 5% clean for 4 hours: increase to 10%
  → If 10% clean for 12 hours: increase to 25%
  → If 25% clean for 24 hours: increase to 50%
  → If 50% clean for 24 hours: increase to 100%

  async def get_session(session_key, user_id):
      if should_use_redis(user_id):  # Canary selection
          result = await redis.get(session_key)
          if result is None:
              # Redis miss: fall back to Memcached
              # This shouldn't happen if dual-write is
              # working, but defense in depth
              metrics.increment("canary.redis_miss_fallback")
              return await memcached.get(session_key)
              # Also backfill Redis:
              # await redis.set(session_key, result, ex=ttl)
          return result
      else:
          return await memcached.get(session_key)

MONITORING AT EACH CANARY STEP:
  → Error rate: per-canary vs control group
  → Latency: per-canary vs control group
  → User-facing metrics: presence accuracy, typing
    indicator delay, session expiry rate
  → Redis cluster: per-node CPU, per-node connections,
    per-node memory
  → Hot key detection: continuous top-key monitoring

  IF ANY METRIC DEGRADES:
  → STOP canary ramp
  → Investigate
  → If Redis-specific: fix and restart canary from
    current percentage
  → If unfixable: roll back to 0% Redis reads

ROLLBACK: Set canary percentage to 0%. All reads
return to Memcached instantly. Redis data remains
populated via dual-write for future attempt.
```

### Phase 4: Full Read Cutover [Week 3, Day 4]

```
OBJECTIVE: 100% of reads from Redis.

  This is where the original plan jumped to immediately.
  We arrive here only after the canary has been at 100%
  for 24 hours with zero issues.

  → Memcached is still receiving dual-writes (safety net)
  → If anything goes wrong: revert to Memcached reads
    in one config change (< 30 seconds)

DURATION: Run for 1 FULL WEEK at 100% Redis reads +
Memcached dual-write before proceeding.

ROLLBACK: Revert read config to Memcached. Dual-write
ensures Memcached has current data. Instant rollback.
```

### Phase 5: Stop Dual-Write [Week 4, Day 1]

```
OBJECTIVE: Stop writing to Memcached. Redis is now
the sole session store.

  BEFORE THIS STEP:
  → Redis has been serving 100% of reads for 1 week
  → Zero Redis-attributable incidents
  → All monitoring baselines established on Redis-only
    read path

  AFTER STOPPING DUAL-WRITE:
  → Memcached data immediately starts aging out (TTLs
    expire, no new writes)
  → Rollback to Memcached becomes IMPOSSIBLE once
    Memcached data expires
  → This is the POINT OF NO RETURN

  THEREFORE:
  → Memcached remains running (but not receiving writes)
    for 48 hours
  → During those 48 hours: if Redis fails, re-enable
    dual-write + switch reads to Memcached
  → Memcached data may be stale (up to 48 hours old),
    but stale sessions > no sessions
  → After 48 hours: Memcached can be decommissioned

ROLLBACK: Re-enable dual-write + Memcached reads.
Sessions written in the last 48 hours may be lost
(users re-login). Acceptable for a messaging platform.
```

### Phase 6: Decommission Memcached [Week 4, Day 3+]

```
OBJECTIVE: Remove Memcached infrastructure.

  → Drain Memcached nodes
  → Remove dual-write code path
  → Remove Memcached client libraries
  → Terminate Memcached instances
  → Update architecture documentation
  → Close migration project

ROLLBACK: None. This is irreversible. Only proceed
when confident Redis is stable.
```

---

## Q5: Mitigation Plan at 12:20

### Situation Assessment

```
╔══════════════════════════════════════════════════════════════╗
║   CURRENT STATE AT 12:20                                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   REDIS CLUSTER:                                             ║
║   → master-2 (NEW — promoted replica): has stale data        ║
║   → master-7: has partially migrated data                    ║
║   → Slots 2731-3413: inconsistent state                      ║
║   → Error rate: 4.7% (was 0.01%)                             ║
║   → Cache miss rate: 23% (was 1.8%)                          ║
║                                                              ║
║   DOWNSTREAM IMPACT:                                         ║
║   → Auth service load: 3x normal (session misses →           ║
║     re-authentication flood)                                 ║
║   → Auth service DB pool: 87% (approaching exhaustion)       ║
║   → If auth DB pool exhausts: ALL logins fail, not just      ║
║     the 23% with cache misses → TOTAL OUTAGE                 ║
║                                                              ║
║   RISK HIERARCHY:                                            ║
║   1. Auth service cascade failure (imminent, affects ALL)    ║
║   2. Continued data loss in inconsistent slots               ║
║   3. User experience (presence, typing, sessions)            ║
║   4. Redis cluster stability                                 ║
║                                                              ║
║   CRITICAL INSIGHT: Memcached is still receiving writes      ║
║   (Phase 2 = reads switched, but dual-write still active).   ║
║   Memcached has CURRENT data. It's a ready rollback target.  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

### Step-by-Step Mitigation

```
STEP 1: PROTECT THE AUTH SERVICE [IMMEDIATE — 12:20]

  The auth service at 87% DB pool utilization is the
  most dangerous element. If it exhausts, we go from
  "23% of users have session issues" to "100% of users
  can't log in." This is the cascade.

  # Rate-limit session-miss-triggered re-authentication:
  # Instead of every cache miss triggering a full
  # re-auth against the DB, implement a token bucket:

  # OPTION A: Return a temporary "session rebuilding"
  # state to the client. Client retries in 5 seconds.
  # This spreads the re-auth load over time instead
  # of a thundering herd.

  # OPTION B: Queue re-auth requests with a concurrency
  # limit matching the DB pool headroom:

  AUTH_SEMAPHORE = asyncio.Semaphore(50)  # Max 50 concurrent re-auths

  async def handle_session_miss(user_id):
      if AUTH_SEMAPHORE.locked():
          # Queue is full. Tell client to retry.
          return Response(status=503,
                         headers={"Retry-After": "5"})
      async with AUTH_SEMAPHORE:
          return await rebuild_session(user_id)

  # This caps auth DB load regardless of cache miss rate.
  # Pool stays at safe utilization.

  VERIFY: Auth service DB pool drops below 70%.
  TIME: 2-3 minutes to deploy config change.
```

```
STEP 2: ROLL BACK READS TO MEMCACHED [12:23]

  Memcached has been receiving dual-writes this entire
  time. It has CURRENT DATA for all sessions. It's the
  fastest path to stability.

  # Feature flag or config change:
  feature_flag.set("SESSION_READ_SOURCE", "memcached")

  # Immediately:
  # → All session reads go to Memcached (known-good)
  # → Cache miss rate drops from 23% to ~1.8% (baseline)
  # → Auth service load drops from 3x to 1x
  # → Error rate drops from 4.7% to ~0.01%
  # → Users stop being logged out
  # → Presence and typing indicators recover

  # DO NOT touch Redis Cluster yet. Just stop reading
  # from it. Let it sit in its inconsistent state while
  # users recover.

  VERIFY:
  → Error rate < 0.1% within 2 minutes
  → Cache miss rate < 2% within 2 minutes
  → Auth service DB pool < 50% within 5 minutes
  → User-facing symptoms (presence, typing) recovering

  TIME: 30 seconds to change config. 2-5 minutes to verify.
```

```
STEP 3: STABILIZE — STOP DIGGING [12:28]

  # Do NOT:
  # → Attempt further resharding
  # → Attempt manual failover or failback
  # → Try to fix Redis cluster state under pressure

  # DO:
  # → Confirm Memcached is serving all reads correctly
  # → Confirm dual-write is still active (Redis still
  #   receiving writes for later recovery)
  # → Communicate to stakeholders: "Service restored.
  #   Migration rolled back. Redis cluster repair will
  #   happen during maintenance window."

  VERIFY: All user-facing metrics at baseline for
  15 minutes before proceeding.
```

```
STEP 4: FIX REDIS CLUSTER STATE [12:45, after stabilization]

  Users are on Memcached. Redis is not serving traffic.
  We can now repair Redis WITHOUT user impact.

  # Step 4a: Check cluster state
  redis-cli --cluster check <node>:6379
  # Identify all inconsistent slots

  # Step 4b: Fix slot ownership
  redis-cli --cluster fix <node>:6379
  # Resolves IMPORTING/MIGRATING states
  # Assigns disputed slots to single owners

  # Step 4c: If --cluster fix doesn't fully resolve:
  # Manually set slot ownership for each affected slot:
  for slot in range(2731, 3414):
      # Assign all contested slots back to new master-2
      redis-cli -h <each-master> \
        CLUSTER SETSLOT $slot NODE <new-master-2-id>
  done

  # Step 4d: Clean up orphaned keys on master-7
  # Keys in slots now owned by new master-2 that
  # exist on master-7 are orphans:
  for slot in range(2731, 3414):
      keys=$(redis-cli -h master-7 \
        CLUSTER GETKEYSINSLOT $slot 100)
      for key in $keys; do
          redis-cli -h master-7 DEL $key
      done
  done

  # Step 4e: Verify cluster health
  redis-cli --cluster check <node>:6379
  # [OK] All 16384 slots covered
  # [OK] All nodes agree on configuration

  # Step 4f: Repopulate Redis from Memcached
  # Dual-write is still active, so new writes land
  # in Redis. But keys that were lost during the
  # failover need to be backfilled.
  # Option: temporarily enable shadow-reads from Redis
  # (reads go to Memcached, shadow to Redis).
  # On shadow miss: backfill Redis from Memcached result.
  # Run for 1 hour to warm up Redis.

  VERIFY: Redis cluster healthy, all slots covered,
  hit rate recovering toward 98%+ on shadow reads.
```

```
STEP 5: ROOT CAUSE FIXES BEFORE RE-ATTEMPTING MIGRATION [Next Week]

  Before re-attempting the Memcached → Redis migration:

  1. FIX THE HOT KEY (Q1c)
     → Deploy workspace key sharding
     → Verify on Memcached first (1 week)
     → Then proceed with proper migration plan (Q4)

  2. RIGHT-SIZE THE REDIS CLUSTER
     → 12 masters instead of 6
     → Verify projected load per master < 40% CPU
       at peak traffic

  3. IMPLEMENT THE PROPER MIGRATION PLAN (Q4)
     → Phase 0 through Phase 6
     → Shadow reads before live reads
     → Canary before full cutover
     → Rollback capability at every phase

  4. OPERATIONAL SAFEGUARDS FOR FUTURE RESHARDS
     → Increase cluster-node-timeout before resharding
     → Disable auto-failover on resharding node
     → Never reshard a node above 50% CPU
     → Never reshard during peak traffic

  5. POST-INCIDENT REVIEW
     → Why was the hot key not detected before migration?
       → No pre-migration traffic profiling
     → Why was the cluster sized at 6 masters for
       workload that ran on 20 Memcached nodes?
       → Undersizing without load testing
     → Why was resharding attempted on an overloaded node
       during peak traffic?
       → Panic response without pre-defined playbook
     → Why was there no rollback plan for Phase 2?
       → Memcached was the rollback, but nobody explicitly
         documented "if Redis fails, revert reads to
         Memcached" as a runbook step
```

### Mitigation Timeline Summary

```
╔══════════════════════════════════════════════════════════════╗
║   TIME  │ ACTION                          │ EFFECT           ║
╠══════════════════════════════════════════════════════════════╣
║  12:20  │ Rate-limit auth re-auth flood   │ Prevent auth     ║
║         │ (semaphore on concurrent auths) │ DB cascade       ║
╠══════════════════════════════════════════════════════════════╣
║  12:23  │ Roll back reads to Memcached    │ Error rate       ║
║         │                                 │ 4.7% → <0.1%     ║
║         │                                 │ Miss rate        ║
║         │                                 │ 23% → <2%        ║
╠══════════════════════════════════════════════════════════════╣
║  12:28  │ Verify stabilization. Stop.     │ Confirm          ║
║         │ Communicate to stakeholders.    │ baseline         ║
╠══════════════════════════════════════════════════════════════╣
║  12:45  │ Fix Redis cluster state         │ Redis healthy    ║
║         │ (--cluster fix, slot reassign,  │ but not          ║
║         │  orphan cleanup)                │ serving reads    ║
╠══════════════════════════════════════════════════════════════╣
║  13:00  │ Backfill Redis via shadow reads │ Redis warm       ║
║         │ from Memcached                  │ cache ready      ║
╠══════════════════════════════════════════════════════════════╣
║  Next   │ Fix hot key, resize cluster,    │ Proper           ║
║  week   │ re-attempt with proper plan     │ migration        ║
╚══════════════════════════════════════════════════════════════╝

KEY PRINCIPLE APPLIED:
  → Step 1: Stop the bleeding (protect auth service)
  → Step 2: Restore service (rollback to Memcached)
  → Step 3: Stabilize and verify (one change, verify)
  → Step 4: Fix the broken thing (Redis cluster repair)
  → Step 5: Fix the root cause (hot key, sizing, process)

  NEVER try to fix the root cause during an active
  incident. Restore service FIRST, root-cause LATER.
```
