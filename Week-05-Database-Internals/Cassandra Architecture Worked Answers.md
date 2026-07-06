# Worked Answers — Cassandra Architecture

Companion to [Cassandra Architecture](./Cassandra%20Architecture.md) and [Retention Test Week 5](../Retention-Tests/Week-05.md).

The SRE scenario setup remains in the main module. These are expert analyses for self-check.

---

## Root Cause vs. Consequences

**ROOT CAUSE**: Vnode distribution imbalance from an unfinished topology change → Nodes 7 and 3 accumulated disproportionate data over 14 months → disk filled → compaction failed.

Everything else is a **consequence**.

## The Complete Chain (10 Links)

```text
PRECONDITION (14 months ago):
  Topology change (node add/remove/replace) completed,
  but vnode token rebalancing was NEVER finalized.
  Nodes 7 and 3 own more token ranges than peers.
  
  Fair share per node: 400GB × 12 nodes = 4.8TB total
    → 4.8TB ÷ 12 = 400GB per node (even distribution)
  Actual: Nodes 7/3 own ~47% more token ranges
    → Node 7: ~1.89TB, Node 3: ~1.82TB vs others at 1.1-1.4TB

TRIGGER (3 weeks ago):
  Node 7 crosses STCS compaction headroom threshold.

  ┌──────────────────────────────────────────────────┐
  │               THE 10-LINK CASCADE                │
  └──────────────────────────────────────────────────┘

  Link 1: DISK EXHAUSTION
  ━━━━━━━━━━━━━━━━━━━━━━━
  Node 7 hits 94%+ disk. STCS attempts compaction:
  must write NEW merged SSTable BEFORE deleting old
  SSTables. Free space insufficient for output file.
  
  Compaction aborts: "java.io.IOException: 
  No space left on device"
  
  Link 2: COMPACTION BACKLOG ACCUMULATES
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Every memtable flush creates a NEW SSTable (~50-200MB).
  Normally STCS merges similar-sized SSTables into tiers:
  
    HEALTHY STCS:              BROKEN STCS:
    4×50MB → 1×200MB           50MB  50MB  50MB  50MB
    4×200MB → 1×800MB          50MB  50MB  50MB  50MB
    4×800MB → 1×3.2GB          50MB  50MB  50MB  50MB
    (pyramid structure)        50MB  50MB  50MB  ...
                               (flat pile of small files)
  
  51.8M writes/day ÷ 12 nodes × RF=3 = ~12.95M writes/node/day
  Each memtable flush ≈ every few seconds under this load.
  Result: hundreds of tiny SSTables pile up → 12 → 87 in 3 weeks.
  847 pending compactions = the entire STCS tier pipeline is stalled.
  
  Link 3: SSTABLE PROLIFERATION → READ AMPLIFICATION
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Read for "sensor-42 on 2024-10-15":
  
    HEALTHY (12 SSTables):
    Check 12 bloom filters → 1-2 disk reads → merge → done
    
    BROKEN (87 SSTables):
    Check 87 bloom filters → N disk reads → merge 87 fragments → done
  
  Cassandra must check EVERY SSTable that MIGHT contain
  the requested partition. With no compaction merging 
  SSTables, the same partition's data is scattered across
  dozens of SSTables (each memtable flush writes the 
  latest batch to a new file).
  
  Read I/O: 12 → 87 SSTable checks = 7.25× amplification
  
  Link 4: BLOOM FILTER DEGRADATION
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Each SSTable has its own bloom filter. Bloom filter answers:
  "Is partition X POSSIBLY in this SSTable?" 
  
  Per-SSTable FP rate configured at ~1% (default).
  Probability of at least one false positive across N SSTables:
  
    P(≥1 FP) = 1 - (1 - fp_rate)^N
    
    Healthy: 1 - (0.99)^12  = 0.114 → 11.4% chance of ≥1 FP
    Broken:  1 - (0.99)^87  = 0.583 → 58.3% chance of ≥1 FP
  
  OBSERVED bloom filter FP ratio: 0.18 (aggregate across checks)
  This means 18% of all "positive" bloom filter results trigger
  unnecessary disk reads. With 87 SSTables per read, that's
  ~15 wasted disk I/O operations per query.
  
  Link 5: BLOOM FILTER MEMORY PRESSURE → GC
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  87 SSTables × bloom filters = 3.1GB of heap (of 8GB total).
  That's 38.75% of heap consumed by bloom filters alone.
  
  Remaining heap for:
  - Memtables (write buffer)
  - Row cache / key cache
  - JVM internals
  - Read buffers
  
  GC pressure increases → stop-the-world pauses → 
  additional latency spikes on top of I/O amplification.
  
  Link 6: TTL TOMBSTONE ACCUMULATION
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  90-day TTL: data written 90+ days ago is expiring continuously.
  14-month-old cluster → steady-state: ~51.8M rows expire/day
  (matching write rate — input = output at steady state).
  
  Expiration creates tombstones (markers saying "this row is dead").
  Normally, compaction purges tombstones older than gc_grace_seconds
  (10 days). Without compaction:
  
  - Tombstones from the last 21 days (3 weeks) are NEVER purged
  - They accumulate across all 87 SSTables
  - 51.8M expirations/day × 21 days ÷ 12 nodes × RF=3
    = ~272M tombstones per node (worst case on Nodes 7/3)
  
  Link 7: TOMBSTONE SCAN AMPLIFICATION
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Read for "sensor-42, last 24h": Cassandra must read the
  partition, but the partition also contains tombstones
  scattered across 87 SSTables.
  
  Cassandra can NOT skip tombstones — it must read them to
  know what data is dead vs alive. The merge iterator walks
  through ALL cells (live + tombstone) to produce the result.
  
    Query result: 17,280 live rows (24h of readings)
    Tombstones scanned: 14,200 (average)
    Total cells processed: 31,480
    Useful work: 17,280 / 31,480 = 55% efficiency
  
  For older partitions (e.g., 90-day-old day partitions):
    Live rows: 0 (all expired)
    Tombstones: 17,280 (all expired rows → tombstones)
    Useful work: 0% — pure waste
    
  This is why "alert history" queries on old dates hit
  TombstoneOverwhelmingException (89,400+ tombstones scanned).
  
  Link 8: TOMBSTONE WARNING → EXCEPTION ESCALATION
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Cassandra has two thresholds:
  
    tombstone_warn_threshold: 1,000 (default)
    → Log WARN, continue serving the read
    
    tombstone_failure_threshold: 100,000 (default)
    → Throw TombstoneOverwhelmingException, ABORT the read
  
  Current trajectory:
    3 weeks ago: tombstones per read ≈ hundreds (warnings start)
    Now: 14,200 average, 89,400 observed on older partitions
    Next: older partitions will cross 100,000 → reads FAIL
    
  sensor-2847 on 2024-09-15 already hit 100K+ → hard failure.
  This date is ~40 days old. Partitions from 60-90 days ago
  will be WORSE (more expired data, more tombstones, zero 
  live rows).
  
  Link 9: READ LATENCY → APPLICATION CASCADING
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  12ms → 340ms p99 = 28× degradation.
  
  Dashboard polls every N seconds per sensor panel.
  At 12ms: requests complete fast, connections freed.
  At 340ms: requests hold connections 28× longer.
  
  If dashboard has connection pool of size P with 
  concurrency C:
    Healthy throughput: P × (1000ms / 12ms) = P × 83 req/s
    Degraded throughput: P × (1000ms / 340ms) = P × 2.9 req/s
    
  28× throughput reduction → connection pool exhaustion →
  dashboard timeouts → user-visible "slow" reports.
  
  TombstoneOverwhelmingException queries return 500 errors →
  alert history pages completely broken for older date ranges.
  
  Link 10: FEEDBACK LOOP (makes everything worse over time)
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  More SSTables → more disk used by SSTable data files
  → LESS free space for compaction → compaction even more stuck
  → MORE SSTables accumulate → more tombstones unpurged
  → more bloom filter memory → more GC pressure → worse reads
  → this is a POSITIVE FEEDBACK LOOP with no natural ceiling
    except total disk exhaustion or node crash.
  
  ┌─────────────────────────────────────────────────────────┐
  │                   FEEDBACK LOOP DIAGRAM                 │
  │                                                         │
  │  Disk full ──→ Compaction fails ──→ SSTables pile up    │
  │     ↑                                    │              │
  │     │                                    ▼              │
  │     │                          More disk consumed       │
  │     │                          by uncompacted files     │
  │     │                                    │              │
  │     └────────────────────────────────────┘              │
  │                                                         │
  │  SIMULTANEOUSLY:                                        │
  │                                                         │
  │  No compaction ──→ Tombstones unpurged ──→ More cells   │
  │       │               per read ──→ Slower reads         │
  │       │                              │                  │
  │       ▼                              ▼                  │
  │  Bloom filters ──→ Heap pressure ──→ GC pauses          │
  │  multiply (87×)        (38% heap)     (latency spikes)  │
  └─────────────────────────────────────────────────────────┘
```

## The Specific STCS Behavior

```
  STCS compaction strategy is the AMPLIFIER, not the root cause.
  
  HOW STCS WORKS:
  
  SSTables are grouped by size into "buckets" (tiers).
  When a bucket has min_threshold (default: 4) similar-sized
  SSTables, STCS merges them into one larger SSTable.
  
    Tier 0: 4 × 50MB  → compact → 1 × 200MB (Tier 1)
    Tier 1: 4 × 200MB → compact → 1 × 800MB (Tier 2)  
    Tier 2: 4 × 800MB → compact → 1 × 3.2GB (Tier 3)
    ...
  
  THE CRITICAL STCS PROPERTY THAT KILLS US:
  
  STCS compaction is ALL-OR-NOTHING per tier.
  It writes the FULL merged output before deleting inputs.
  
  A Tier 2 compaction of 4 × 800MB files:
    → Reads 3.2GB of input
    → Writes 3.2GB of output (NEW file)
    → Total disk during compaction: 3.2GB input + 3.2GB output = 6.4GB
    → Only after output is complete: delete 3.2GB input
    → Net: 3.2GB (same), but TRANSIENT peak = 2× the tier size
  
  WORST CASE: the largest tier determines space requirement.
  If your biggest SSTables are 50GB each and STCS wants to
  merge 4 of them: you need 200GB TRANSIENT free space.
  
  Node 7 at 94.5% = 110GB free on 2TB disk.
  Any compaction involving tiers larger than ~55GB each 
  (110GB ÷ 2) is IMPOSSIBLE.
  Even smaller tier compactions consume the remaining 
  space and prevent larger tiers from ever running.
  
  THIS IS THE STCS SPACE TRAP:
  Once disk crosses ~50% utilization, large-tier compactions
  become impossible. Once it crosses ~80%, even medium-tier
  compactions stall. The threshold depends on largest SSTable
  size, but the GENERAL RULE for STCS:
  
    Never exceed 50% disk utilization.
  
  Node 7 at 94.5% has been in the trap for weeks.
  Node 3 at 91% is in the same trap.
  The other 10 nodes (55-70%) are degraded but can still
  compact — their problem is the BACKLOG, not disk space.
```

## Summary Classification

```
  ┌───────────────────────────────────────────────────────┐
  │  CLASSIFICATION          │  ITEM                      │
  ├──────────────────────────┼────────────────────────────┤
  │  PRECONDITION            │  Vnode imbalance (14 mo)   │
  │  ROOT CAUSE              │  Disk exhaustion (Node 7)  │
  │  TRIGGER                 │  STCS compaction failure   │
  │  AMPLIFIER               │  STCS space requirement    │
  │                          │  (needs 2× tier size free) │
  │  CONSEQUENCE 1           │  SSTable proliferation     │
  │  CONSEQUENCE 2           │  Read amplification (7×)   │
  │  CONSEQUENCE 3           │  Bloom filter FP (58%)     │
  │  CONSEQUENCE 4           │  Heap pressure (38% bloom) │
  │  CONSEQUENCE 5           │  Tombstone accumulation    │
  │  CONSEQUENCE 6           │  TombstoneOverwhelming     │
  │  CONSEQUENCE 7           │  Dashboard degradation     │
  │  FEEDBACK LOOP           │  Disk ↔ compaction ↔ disk  │
  └──────────────────────────┴────────────────────────────┘
```

---

# Q2: The Zombie Data Time Bomb

## What Tombstones Do and Why gc_grace_seconds Exists

```
  TOMBSTONE LIFECYCLE:
  
  1. Row expires (TTL) or is explicitly deleted
  2. Cassandra writes a TOMBSTONE marker 
     (not a physical delete — this is an append-only engine)
  3. Tombstone has a creation timestamp (local_deletion_time)
  4. Tombstone is replicated to all RF=3 replicas via:
     - Normal write path (if explicit delete)
     - Read repair (if discovered during read)
     - Anti-entropy repair (full Merkle tree comparison)
  5. After gc_grace_seconds (10 days) SINCE the tombstone 
     creation, compaction is ALLOWED to purge the tombstone
  6. Compaction physically removes the tombstone from the 
     SSTable during merge
     
  gc_grace_seconds EXISTS because of this scenario:
  
    Node A has: row X (live) + tombstone for X (delete)
    Node B was DOWN when tombstone was written
    Node B still has: row X (live), no tombstone
    
    If Node A purges the tombstone before Node B learns 
    about it, then:
    - Node A: row X doesn't exist (tombstone purged, row gone)
    - Node B: row X exists (live, never saw the tombstone)
    
    Read repair or anti-entropy from Node B → Node A:
    "Hey, I have row X!" → Node A accepts it → ZOMBIE.
    The deleted data is RESURRECTED.
    
  gc_grace_seconds = the window during which you MUST run 
  repair so all replicas learn about all tombstones.
  After that window, compaction purges tombstones, assuming
  repair has propagated them everywhere.
```

## Exactly What Happened Over 11 Weeks

```
  TIMELINE:
  
  Week  0: Last successful full repair completes.
           All replicas consistent. Tombstones propagated.
  
  Week  1: (gc_grace = 10 days) — SAFE.
  Day 10:  gc_grace_seconds window CLOSES.
           From this point forward, tombstones from Week 0 
           are ELIGIBLE for purging by compaction.
           But compaction would only purge them IF it runs.
           
  Week  2: Tombstones from Day 1-4 of this period are now
           past gc_grace. Compaction CAN purge them.
           Any node that missed the tombstone during this 
           window has NOT been repaired since.
           ZOMBIE RISK BEGINS.
           
  Week 3 (= 3 weeks ago): Compaction STOPS on Nodes 7/3.
           Now tombstones can't be purged even if gc_grace 
           passed — no compaction to do the purging.
           But on other nodes (55-70% disk), compaction IS 
           still partially running...
           
  HERE IS THE CRITICAL PROBLEM:
  
  Nodes with free disk space (Nodes 1,2,4,5,6,8,9,10,11,12)
  ARE still compacting, albeit with a backlog. When they 
  compact, they PURGE tombstones older than 10 days.
  
  But repair hasn't run in 11 weeks. So:
  
  ┌───────────────────────────────────────────────────────┐
  │  Node A (healthy, compacting):                        │
  │    Has tombstone for row X (created 15 days ago)      │
  │    gc_grace = 10 days → tombstone eligible for purge  │
  │    Compaction runs → tombstone PURGED                 │
  │    Node A: row X doesn't exist                        │
  │                                                       │
  │  Node B (was briefly unresponsive / hints expired /   │
  │    or was the node that missed the write):            │
  │    NEVER received tombstone for row X                 │
  │    Still has row X as LIVE data                       │
  │    No repair has reconciled since Week 0              │
  │                                                       │
  │  RESULT: Zombie row X exists on Node B.               │
  │  Any read at CL=ONE hitting Node B returns the        │
  │  zombie. Read repair MIGHT fix it... but only if      │
  │  read repair triggers AND another replica still has   │
  │  the tombstone. If all other replicas already purged  │
  │  the tombstone, read repair sees the "live" row on    │
  │  Node B and PROPAGATES IT to other replicas.          │
  │  The zombie SPREADS.                                  │
  └───────────────────────────────────────────────────────┘
```

## Is There Zombie Data Right Now? YES.

```
  CALCULATING THE SCOPE:
  
  gc_grace_seconds: 10 days
  Repair gap: 11 weeks = 77 days
  Days past gc_grace_seconds: 77 - 10 = 67 days
  
  Any tombstone created between Day 0 (last repair) and 
  Day 67 (today minus gc_grace) is ELIGIBLE for purging.
  
  Nodes that are still compacting (10 of 12) have been 
  purging tombstones older than 10 days for the entire 
  11-week period. Tombstones from weeks 1-9 have been 
  progressively purged on these nodes.
  
  THE ZOMBIE WINDOW:
  
  ┌────────────────────────────────────────────────────────────┐
  │                                                            │
  │  Week 0          Day 10        Week 3        Week 11       │
  │  (last repair)   (gc_grace)    (compaction    (today)      │
  │  │                │            stops N7/N3)    │           │
  │  ▼                ▼            ▼               ▼           │
  │  ├────SAFE────────┤            │               │           │
  │  │                ├─ZOMBIE RISK ZONE───────────┤           │
  │  │                │            │               │           │
  │  │                │  67 days of tombstones     │           │
  │  │                │  eligible for purge on     │           │
  │  │                │  nodes that never got them │           │
  │  │                │                            │           │
  │  └────────────────┴────────────────────────────┘           │
  └────────────────────────────────────────────────────────────┘
  
  AFFECTED DATA SCOPE:
  
  67 days × 51.8M writes/day = 3.47 BILLION rows potentially
  affected. Not all are zombies — only rows where:
  
  1. The TTL expiration tombstone was written
  2. At least one replica missed it (hints expired, 
     node was briefly down, network partition, etc.)
  3. A compacting replica purged the tombstone
  4. No read repair has since reconciled
  
  Realistic estimate: even a 0.1% miss rate across 
  3.47B rows = 3.47 MILLION zombie rows.
  
  These are sensor readings that expired (TTL) and 
  SHOULD be gone, but are now live again on some replicas.
```

## The Specific Resurrection Sequence

```
  CONCRETE EXAMPLE:
  
  1. sensor-1500 reported temperature=85.2°C on July 15 (98 days ago)
  2. TTL=90 days → expired 8 days ago → tombstone created
  3. Node A (coordinator for this write) has the tombstone
  4. Node B was experiencing GC pause during tombstone propagation
     → hinted handoff created on Node A
  5. Hint expired (default max_hint_window = 3 hours) before 
     Node B recovered
  6. Node B: still has live row (temperature=85.2°C on July 15)
  7. No repair has run in 11 weeks → no reconciliation
  8. Node A compacts → tombstone is 8 days old, gc_grace = 10 days
     → NOT YET purged (still within gc_grace)
     
  BUT for data that expired 15+ days ago:
  
  1. sensor-500 reported vibration=12.4 on June 20 (133 days ago)  
  2. TTL=90 days → expired 43 days ago → tombstone created 43 days ago
  3. Node C has tombstone (43 days old > 10 day gc_grace)
  4. Node D missed tombstone (was in a rolling restart that day)
  5. Node C compacted 30 days ago → tombstone PURGED
  6. Node C: no row, no tombstone (clean)
  7. Node D: live row vibration=12.4 (ZOMBIE)
  8. Read at CL=ONE hits Node D → returns the zombie reading
  9. Read repair: Node C has nothing, Node D has live row
     → Cassandra resolves by TIMESTAMP: Node D's row wins
     → Row PROPAGATED to Node C → zombie spreads to all replicas
  10. The deleted data is now permanently resurrected on ALL replicas.
      Only an explicit DELETE with a newer timestamp can kill it.
```

## Impact Assessment

```
  SEVERITY: HIGH but not catastrophic for this use case.
  
  IoT sensor readings are APPEND-ONLY time series.
  Zombie data = stale sensor readings reappearing in dashboards.
  
  Consequences:
  → Dashboard shows readings from >90 days ago mixed with current
  → Alert history contains phantom alerts from expired data
  → Storage: zombie data consumes disk space that should be freed
  → Regulatory: if data retention policy requires 90-day max 
    retention, zombie data violates it (data exists past expiry)
  → Analytics: any aggregation (avg temp over 30 days) could 
    include zombie readings from months ago → WRONG RESULTS
  
  If this were a DELETION (not TTL expiry) — e.g., user 
  requested data deletion under GDPR — zombie resurrection 
  would be a COMPLIANCE VIOLATION. For IoT readings, it's 
  "just" data integrity corruption.
```

---

# Q3: The STCS Space Trap

## Can STCS Run Compaction on Node 7?

```
  NODE 7 STATE:
  Disk: 1.89TB used / 2TB total = 110GB free (5.5%)
  SSTables: 87 per table
  Pending compactions: 847
  
  STCS SPACE REQUIREMENT:
  
  STCS merges N similar-sized SSTables into 1 output SSTable.
  Both input AND output exist simultaneously during compaction.
  
  Minimum free space needed = size of the compaction OUTPUT
  (the merged SSTable).
  
  For the SMALLEST possible compaction (min_threshold=4, 
  smallest SSTables):
  
    4 × 50MB flush SSTables → 200MB output
    Transient space needed: 200MB
    110GB free → YES, this fits.
  
  For MEDIUM tier compaction:
    4 × 5GB SSTables → 20GB output
    Transient space: 20GB
    110GB free → YES, this fits.
  
  For LARGE tier compaction (the ones that actually matter):
    4 × 30GB SSTables → 120GB output  
    Transient space: 120GB
    110GB free → NO. CANNOT RUN.
    
  And HERE is the cascading trap:
  
  If only small-tier compactions can run, they produce 
  medium SSTables. Medium tier accumulates. Medium compaction 
  produces output that needs more space. Eventually medium 
  tier is blocked too.
  
  ┌──────────────────────────────────────────────────────┐
  │  STCS SPACE REQUIREMENT RULE:                        │
  │                                                      │
  │  Free space must be ≥ largest_sstable_size ×         │
  │  min_threshold (typically 4)                         │
  │                                                      │
  │  BUT more practically, the Cassandra community rule: │
  │                                                      │
  │  ┌─────────────────────────────────────────────┐     │
  │  │  STCS: keep disk utilization below 50%      │     │
  │  │  (need up to 50% transient space for        │     │
  │  │   worst-case major compaction)              │     │
  │  │                                             │     │
  │  │  LCS: keep disk utilization below 80%       │     │
  │  │  (compacts small fixed-size SSTables,       │     │
  │  │   needs ~10% transient overhead)            │     │
  │  └─────────────────────────────────────────────┘     │
  │                                                      │
  │  Node 7 at 94.5%: STCS is COMPLETELY TRAPPED         │
  │  for any meaningful compaction.                      │
  │                                                      │
  │  Even small compactions that DO fit will only        │
  │  consume the remaining 110GB, making the situation   │
  │  WORSE — they produce output files that consume      │
  │  free space, leaving even less room for larger tiers.│
  └──────────────────────────────────────────────────────┘
  
  ANSWER: Node 7 CANNOT run any compaction that would 
  meaningfully reduce SSTable count. Small compactions 
  might technically fit but make the problem worse by 
  consuming remaining free space.
  
  Node 3 at 91% (180GB free): same trap for large tiers, 
  might handle medium tiers, but also in a death spiral.
```

## Why Are Nodes 7 and 3 Disproportionately Large?

```
  The setup says: "vnode distribution imbalance from a 
  past topology change that was never rebalanced."
  
  WHAT HAPPENED:
  
  Scenario: a node was decommissioned or added, and the 
  token ranges were redistributed. But the redistribution 
  was either:
  
  a) Interrupted (nodetool cleanup never completed), or
  b) The new node was added with num_tokens that didn't 
     balance with existing nodes, or  
  c) A node was replaced and inherited token ranges that
     were already skewed, or
  d) Manual token assignment was done incorrectly
  
  RESULT:
  
  In vnode-based token assignment with RandomPartitioner or 
  Murmur3Partitioner, each node owns num_tokens random 
  positions on the ring. When a node leaves/joins, its 
  tokens are redistributed.
  
  If rebalancing wasn't finalized:
  
    Normal: 12 nodes, each owns 1/12 = 8.33% of token space
    Skewed: Nodes 7/3 own ~12-13% each (≈1.5× fair share)
    
  Over 14 months at 51.8M writes/day:
    Fair: 51.8M × 90 days ÷ 12 nodes × RF_local ≈ 400GB
    Skewed: 51.8M × 90 days × 1.5 ÷ 12 × RF_local ≈ 600GB+
    
  But observed: Node 7 = 1.89TB. This means Node 7 owns 
  significantly more token ranges AND is a replica for 
  adjacent ranges (RF=3 means each node stores data for 
  its own ranges + neighboring ranges).
  
  With vnode imbalance, Node 7 may be both PRIMARY for 
  too many ranges AND REPLICA for neighboring ranges that 
  are also imbalanced.
```

## Fix Without Adding Hardware Immediately

```
  OPTION 1: MANUAL DATA OFFLOAD VIA NODETOOL CLEANUP + REPAIR
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  
  Can't do this — cleanup RUNS compaction, which needs 
  the disk space we don't have. Circular dependency.
  
  OPTION 2: TARGETED SSTABLE OFFLOAD (the actual fix)
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  
  STEP 1: Identify expired SSTables (100% tombstoned data).
  
    nodetool sstableexpiredblockers iot readings
    
  SSTables where ALL data has expired AND max timestamp 
  is older than gc_grace_seconds can be dropped entirely 
  WITHOUT compaction using:
  
    nodetool sstableexpiredcheck (identify them)
    
  Then use sstablemetadata to verify each SSTable's 
  min/max timestamps and tombstone ratio.
  
  For SSTables that are 100% expired data + tombstones
  past gc_grace:
  
  ⚠️  WAIT — gc_grace is meaningless without repair.
  Dropping SSTables with tombstones that haven't been 
  propagated via repair = GUARANTEED zombie creation.
  
  CAN'T safely drop expired SSTables until repair runs.
  This path is BLOCKED by the repair gap.
  
  OPTION 3: REDUCE DATA ON NODE 7 BY STREAMING DATA OFF
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  
  a) nodetool relocatesstables: moves SSTables to the 
     correct token range owner. If Node 7 has data from 
     past topology change that belongs to other nodes, 
     this streams it off.
     
     Risk: consumes network bandwidth, but FREES disk 
     on Node 7.
     
     Verify first: nodetool ring — check if Node 7 
     actually has data for token ranges it no longer owns.
  
  b) Reduce RF temporarily? NO — RF=3 is minimum for 
     production IoT. Don't touch this.
  
  OPTION 4: THE PRACTICAL FIX — EXPAND DISK, THEN FIX
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  
  "Without adding hardware immediately" — but we CAN 
  expand DISK without adding nodes:
  
  If cloud (EBS/PD/Azure Disk):
    → Resize volume from 2TB → 4TB online (no downtime 
      on AWS EBS, GCP PD)
    → resize2fs /dev/xvdf (or xfs_growfs for XFS)
    → Immediate: Node 7 goes from 94.5% → 47.25%
    → Compaction can now run.
    
  This is not "adding hardware" (no new nodes), it's 
  expanding existing storage — fast, online, and the 
  correct first move.
  
  If bare metal:
    → Add a second disk, configure as additional 
      Cassandra data directory (data_file_directories 
      supports multiple paths)
    → Cassandra will write new SSTables to the directory 
      with more free space
    → Existing SSTables stay on old disk, new writes go 
      to new disk
    → Over time, compaction merges across directories
  
  OPTION 5 (EMERGENCY): REMOVE NODE 7 FROM SERVING READS
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  
  As an IMMEDIATE MEASURE while fixing disk:
  
    Set Node 7 to drain (nodetool drain) — stops accepting 
    new connections but doesn't decommission.
    
    With RF=3 and CL=ONE/QUORUM:
    → CL=ONE: other replicas serve reads. Some reads now 
      hit Node 3 (also sick) or healthy nodes.
    → CL=QUORUM: need 2 of 3 replicas. If Node 7 is down 
      for a partition, the other 2 must be available. 
      If Node 3 is also a replica for the same range → 
      only 1 healthy replica → QUORUM FAILS for those ranges.
      
    MUST VERIFY: which token ranges overlap between Node 7 
    and Node 3. If they share ranges, draining Node 7 makes 
    those ranges single-replica. Draining BOTH = data 
    unavailable for shared ranges.
    
    → Check: nodetool ring | grep Node7, nodetool ring | grep Node3
    → If overlapping ranges exist, drain only ONE node.
  
  RECOMMENDED APPROACH:
  
  1. Expand disk on Nodes 7 and 3 (cloud resize if possible)
  2. If cloud resize unavailable: drain ONE node (7, the worse one),
     verify Node 3 doesn't share all its ranges with Node 7
  3. Once free space exists: let compaction proceed naturally
  4. THEN run repair (after compaction catches up enough to 
     be meaningful)
```

---

# Q4: Immediate Mitigation Plan (09:30 - 13:30)

## Priority Assessment

```
  CONCURRENT PROBLEMS:
  
  P0 — TombstoneOverwhelmingException (reads FAILING)
  P1 — 340ms p99 latency (SLA breach: 50ms)
  P2 — Disk space trap on Nodes 7/3 (blocks all recovery)
  P3 — 847 pending compactions (root of latency issue)
  P4 — Repair gap (67 days past gc_grace — zombie risk)
  P5 — Vnode imbalance (precondition for recurrence)
  
  DEPENDENCY CHAIN:
  
  Can't fix P3 (compaction backlog) without fixing P2 (disk space)
  Can't fix P4 (repair) without fixing P3 (compaction must 
    catch up first — repair on 87 SSTables per node generates 
    massive streaming volume and Merkle tree computation)
  Can't fix P5 (rebalance) without fixing P3+P4 first 
    (rebalancing moves data, needs stable cluster)
  
  P0 (hard failures) and P1 (SLA breach) need IMMEDIATE 
  mitigation while P2 is being resolved.
```

## Minute-by-Minute Plan

```
  ┌─────────────────────────────────────────────────────────┐
  │  09:30-09:45  PHASE 0: STOP THE BLEEDING                │
  │  (Fix P0: TombstoneOverwhelmingException)               │
  └─────────────────────────────────────────────────────────┘
  
  ACTION 1: Raise tombstone_failure_threshold temporarily.
  
    # In cassandra.yaml on ALL nodes (or via JMX live):
    tombstone_failure_threshold: 500000  (from 100,000)
    tombstone_warn_threshold: 50000     (from 1,000)
    
    # Via JMX (no restart required):
    nodetool sjk mx -b org.apache.cassandra.db:type=StorageService \
      -f TombstoneFailureThreshold --set 500000
    
    Or for Cassandra 4.0+:
    ALTER TABLE iot.readings WITH 
      tombstone_failure_threshold = 500000;
  
  What this fixes: reads stop FAILING with exceptions.
  What this doesn't fix: reads are still SLOW (still scanning 
    100K+ tombstones, just not aborting).
  What to verify before executing: nothing — this is a 
    safety threshold change, no data risk. Pure risk/reward 
    tradeoff: accept slow reads instead of failed reads.
  Operational risk: LOW. Reads will be slow but succeed. 
    Extreme tombstone scans consume heap memory — monitor 
    GC pressure after change. If GC pauses spike >5s, 
    revert and accept hard failures on worst partitions.
  
  
  ACTION 2: Restrict queries on old partitions.
  
  The worst tombstone scans are on OLD day partitions 
  (60-90 days ago) where most/all data has expired.
  
    Application-level: add WHERE day >= '2024-10-01' 
    to dashboard queries (limit to last 30 days).
    
    If dashboard code can't be changed immediately:
    Add a Cassandra-side row limit as a guard:
    
    ALTER TABLE iot.readings WITH 
      default_time_to_live = 7776000
      AND caching = {'rows_per_partition': '1000'};
  
  What this fixes: prevents dashboard from hitting the 
    worst partitions (old dates with maximum tombstones).
  What this doesn't fix: alert history queries that 
    specifically request old dates. Those need application 
    changes or must remain degraded.
  Verify before: confirm dashboard query patterns — are 
    all slow queries hitting old dates, or are recent dates 
    also slow? Check: 
    nodetool toppartitions iot readings 60000
  Operational risk: LOW. Restricting query range is 
    purely beneficial.
  
  
  ┌─────────────────────────────────────────────────────────┐
  │  09:45-10:15  PHASE 1: FREE DISK SPACE                  │
  │  (Fix P2: disk space trap on Nodes 7/3)                 │
  └─────────────────────────────────────────────────────────┘
  
  ACTION 3: Expand disk on Nodes 7 and 3.
  
  IF CLOUD (AWS EBS):
    aws ec2 modify-volume --volume-id vol-xxx --size 4096
    # Wait for optimization state:
    aws ec2 describe-volumes-modifications --volume-ids vol-xxx
    # Extend filesystem:
    sudo resize2fs /dev/xvdf    # ext4
    # OR
    sudo xfs_growfs /data        # XFS
    
    Result: Node 7 goes from 1.89TB/2TB (94.5%) 
            to 1.89TB/4TB (47.25%) — BELOW STCS 50% threshold.
    
  IF BARE METAL / CAN'T RESIZE:
    Option A: Add secondary data directory
      # cassandra.yaml:
      data_file_directories:
        - /data/cassandra
        - /data2/cassandra    # new disk
      # Requires node restart
      
    Option B: Move snapshots/backups off-node
      nodetool listsnapshots
      nodetool clearsnapshot --all
      # Snapshots can consume significant disk
      # Verify: du -sh /data/cassandra/data/iot/readings-*/snapshots/
  
  VERIFY BEFORE EXECUTING:
  → Check for existing snapshots consuming disk:
    du -sh /data/cassandra/data/*/*/snapshots/
    If snapshots exist: clearsnapshot frees space IMMEDIATELY 
    without any resize. CHECK THIS FIRST — it might solve 
    disk pressure instantly.
  → If cloud resize: confirm EBS volume type supports online 
    resize (gp2/gp3/io1/io2: yes. Instance store: no.)
  → If bare metal disk add: schedule 2-min restart window 
    for each node (rolling).
  
  What this fixes: unblocks compaction on the two sickest nodes.
  What this doesn't fix: compaction backlog still exists 
    (847 pending), just now has room to run.
  Operational risk: MEDIUM. Cloud resize is online, no risk. 
    Bare metal disk add requires restart. Snapshot cleanup is 
    immediate and safe.
  
  
  ┌─────────────────────────────────────────────────────────┐
  │  10:15-11:00  PHASE 2: ACCELERATE COMPACTION            │
  │  (Fix P3: 847 pending compactions)                      │
  └─────────────────────────────────────────────────────────┘
  
  ACTION 4: Increase compaction throughput.
  
  VERIFY FIRST: disk space is now available (Phase 1 complete).
  If disk space is NOT freed yet, DO NOT increase compaction 
  throughput — it will attempt compactions that fail and 
  consume I/O without progress.
  
    # Increase concurrent compactors (default: 2, or 
    # min(num_cores, num_disks)):
    nodetool setconcurrentcompactors 4
    
    # Increase compaction throughput (default: 64MB/s):
    nodetool setcompactionthroughput 256
    
    # On ALL nodes, not just 7/3 — all have backlogs
  
  What this fixes: clears the 847 pending compaction backlog 
    faster. Merges SSTables, purges eligible tombstones, 
    reduces SSTable count, restores bloom filter efficiency.
  What this doesn't fix: won't purge tombstones safely 
    (repair hasn't run — tombstones past gc_grace will be 
    purged during compaction, potentially enabling zombies).
    THIS IS A CALCULATED RISK — discussed below.
  Verify before: disk I/O capacity. More compactors = more 
    disk I/O = potential read latency impact during compaction.
    Check: iostat -x 5 — if disk utilization already >90%, 
    adding compactors will hurt read latency further.
  Operational risk: MEDIUM-HIGH.
    → Compaction I/O competes with read I/O → reads may get 
      SLOWER during catch-up (temporarily).
    → On Nodes 7/3 with fresh disk space: compaction will 
      consume the new space rapidly. Monitor df -h continuously.
    → ZOMBIE RISK: compaction will purge tombstones past 
      gc_grace on nodes that have them, BEFORE repair runs.
      This is the same zombie problem from Q2 — we're 
      ACCEPTING this risk because the alternative (reads 
      failing) is worse. We'll run repair ASAP after 
      compaction stabilizes.
  
  
  ACTION 5: User-facing compaction for worst partitions.
  
  For the specific partitions causing TombstoneOverwhelmingException:
  
    nodetool compact iot readings
    
  This forces a major compaction of the entire table.
  
  ⚠️  DANGER: Major compaction on STCS creates ONE massive 
  SSTable. This SSTable can NEVER be compacted again by STCS 
  (nothing similar-sized to merge with) until it's as large 
  as all new incoming data combined.
  
  BETTER ALTERNATIVE: run subrange compaction on specific 
  token ranges if your Cassandra version supports it:
  
    nodetool compact iot readings --start-token <token> --end-token <token>
  
  Where tokens correspond to the worst partitions 
  (sensor-2847 etc.). This limits blast radius.
  
  Verify before: 
  → Confirm disk has enough space for output SSTable 
    (estimate: sum of all SSTables for this table on this node)
  → Schedule during lowest-traffic window if possible 
    (even though we're mid-incident, this is a high-I/O 
    operation)
  Operational risk: HIGH for full major compaction (creates 
    un-compactable giant SSTable). MEDIUM for subrange compaction.
  
  
  ┌─────────────────────────────────────────────────────────┐
  │  11:00-12:00  PHASE 3: STAKEHOLDER COMMUNICATION +      │
  │  REPAIR PLANNING                                        │
  └─────────────────────────────────────────────────────────┘
  
  ACTION 6: Stakeholder communication.
  
  By 11:00 — 90 minutes in — communicate:
  
  → Operations team: "Dashboard latency is improving. Old 
    date range queries (>30 days) may still be slow or fail. 
    Restrict dashboard to last 30 days until further notice."
  → Engineering lead: "Cluster has a compaction backlog and 
    repair gap. Stabilization in progress. ETA for SLA 
    restoration: 4-8 hours (compaction catch-up). Full 
    cluster health restoration: 48-72 hours (repair cycle)."
  → Management: "P1 incident. Dashboard degraded, not down. 
    Active mitigation underway. No data loss risk for new 
    writes. Historical data integrity being assessed."
  
  ACTION 7: Plan repair (DO NOT EXECUTE YET).
  
  Repair must wait until:
  a) Compaction backlog is below ~50 pending per node
  b) SSTable count is back to <20 per node
  c) Disk utilization is below 60% on all nodes
  
  Why: running repair on a cluster with 87 SSTables per node 
  generates massive Merkle tree computation (hashing all data 
  in all 87 files). This will:
  → Consume enormous heap (Merkle trees are in-memory)
  → Generate massive disk I/O (reading all SSTables to hash)
  → Compete with the compaction catch-up we just started
  → Potentially OOM the nodes if heap is already 38% bloom filters
  
  REPAIR PLAN (execute after compaction stabilizes):
  
    # Use subrange repair, not full repair (much lighter):
    # Recommended: use Reaper (cassandra-reaper) for managed repair
    
    # If manual:
    nodetool repair iot readings --full --sequential
    
    # Sequential: one node at a time (less cluster impact)
    # --full: Merkle tree comparison (not incremental — 
    #   incremental repair has known issues in C* 3.x)
    
    # Estimate: 12 nodes × 400GB each × sequential 
    # = 24-48 hours for full repair cycle
  
  Verify before executing repair:
  → SSTable count < 20 per node
  → Pending compactions < 50 per node
  → Heap usage stable (GC pauses < 500ms)
  → Disk utilization < 60% on all nodes (repair creates 
    temporary SSTables during streaming)
  
  
  ┌─────────────────────────────────────────────────────────┐
  │  12:00-13:30  PHASE 4: MONITOR COMPACTION PROGRESS      │
  │  + APPLICATION-LEVEL MITIGATIONS                        │
  └─────────────────────────────────────────────────────────┘
  
  ACTION 8: Monitor compaction progress continuously.
  
    # Every 15 minutes:
    nodetool compactionstats
    # Look for: pending compactions decreasing
    
    nodetool cfstats iot.readings
    # Look for: SSTable count decreasing, 
    #   read latency improving, bloom filter FP decreasing
    
    watch -n 30 'nodetool tpstats | grep -i compact'
    # Look for: compaction threads active, not blocked
    
    df -h /data/cassandra
    # Look for: disk usage not climbing back toward ceiling
  
  ACTION 9: Application-level read optimization (while waiting).
  
  Add a Cassandra read-side guard to the application:
  
    SELECT * FROM iot.readings 
    WHERE sensor_id = ? AND day = ? AND event_time > ?
    LIMIT 20000;
    
  → Add LIMIT to prevent unbounded tombstone scans
  → Add event_time > (now - 24h) for dashboard queries 
    to skip expired rows
  → For alert history: paginate with token()/clustering 
    key ranges instead of full partition scans
  
  What this fixes: reduces per-query tombstone scan, even 
    before compaction clears the backlog.
  Verify before: confirm application has query modification 
    capability (code deploy vs config change).
  Operational risk: LOW — purely reduces query scope.
```

## 4-Hour Timeline Summary

```
  ┌────────┬──────────────────────────────────────────────┐
  │  TIME  │  ACTION                                      │
  ├────────┼──────────────────────────────────────────────┤
  │  09:30 │  Raise tombstone_failure_threshold (JMX)     │
  │  09:35 │  Restrict dashboard to last 30 days          │
  │  09:45 │  Check/clear snapshots on Nodes 7/3          │
  │  09:50 │  Expand disk on Nodes 7/3 (cloud resize)     │
  │  10:15 │  Verify disk space freed                     │
  │  10:20 │  Increase compaction throughput + concurrency│
  │  10:30 │  Subrange compaction on worst partitions     │
  │  11:00 │  Stakeholder communication (ops/eng/mgmt)    │
  │  11:15 │  Plan repair (DON'T execute yet)             │
  │  11:30 │  Application query restrictions deployed     │
  │  12:00 │  Monitor: compaction stats, disk, latency    │
  │  12:30 │  Monitor: SSTable count decreasing?          │
  │  13:00 │  Monitor: p99 latency improving?             │
  │  13:30 │  CHECKPOINT: if SSTable count < 40,          │
  │        │  expect p99 < 100ms. Plan repair window.     │
  └────────┴──────────────────────────────────────────────┘
  
  EXPECTED OUTCOMES BY 13:30:
  → P0 (hard failures): RESOLVED at 09:30 (threshold raise)
  → P1 (SLA breach): IMPROVING — p99 should drop from 340ms 
    to ~80-120ms as compaction clears backlog. Full SLA 
    restoration (< 50ms) expected within 8-12 hours.
  → P2 (disk space): RESOLVED at 10:00 (resize/snapshots)
  → P3 (compaction backlog): IN PROGRESS — 847 → estimated 
    ~400 by 13:30 with 4 concurrent compactors at 256MB/s
  → P4 (repair gap): PLANNED — execute after compaction 
    stabilizes (24-48 hours)
  → P5 (vnode imbalance): DEFERRED — address in post-mortem 
    architecture redesign
```

---

# Q5: Architecture Redesign — Preventing ALL Failure Modes

## Change 1: Compaction Strategy — STCS → TWCS

**Defense Layer: L1 (PRIMARY) — prevents the root cause of SSTable accumulation for time-series data.**

```
  WHY TWCS (TimeWindowCompactionStrategy):
  
  This is TIME-SERIES DATA. Every row has a TTL of 90 days.
  Writes are append-only, ordered by time. This is the 
  EXACT use case TWCS was built for.
  
  HOW TWCS WORKS:
  
  ┌─────────────────────────────────────────────────────────┐
  │  TWCS divides time into windows (e.g., 1 day each).     │
  │  Within each window: runs STCS-like compaction.         │
  │  Once a window is CLOSED (time has passed), the         │
  │  SSTables for that window are NEVER compacted again.    │
  │                                                         │
  │  Window 1 (Oct 1):  [SSTable] (sealed, never touched)   │
  │  Window 2 (Oct 2):  [SSTable] (sealed, never touched)   │
  │  Window 3 (Oct 3):  [SSTable] (sealed, never touched)   │
  │  ...                                                    │
  │  Window 90 (today): [SST][SST][SST] (active, compacting)│
  │                                                         │
  │  When Window 1's data expires (TTL = 90 days):          │
  │  → The ENTIRE SSTable is dropped as a unit              │
  │  → NO tombstones created                                │
  │  → NO compaction needed to reclaim space                │
  │  → Instant disk reclamation                             │
  └─────────────────────────────────────────────────────────┘
  
  CONFIGURATION:
  
  ALTER TABLE iot.readings WITH compaction = {
    'class': 'TimeWindowCompactionStrategy',
    'compaction_window_unit': 'DAYS',
    'compaction_window_size': '1',
    'expired_sstable_check_frequency_seconds': '600',
    'unsafe_aggressive_sstable_expiration': 'true'
  };
  
  KEY PROPERTIES THAT PREVENT EACH FAILURE:
  
  1. SSTable proliferation: TWCS limits SSTables to 
     ~1-2 per time window + active window's working set.
     90 windows × 2 SSTables = ~180 max (predictable, bounded).
     vs STCS: unbounded growth when compaction stalls.
     
  2. Tombstone problem: TWCS drops entire expired windows 
     as whole-file deletions. No tombstones needed for 
     TTL-expired data. The tombstone scan problem DISAPPEARS.
     
  3. Disk space: TWCS doesn't need 50% free space. Sealed 
     windows are never re-compacted. Only the active window 
     (today's data) compacts. Space requirement: ~10-15% for 
     active window compaction.
     
  4. Compaction I/O: massively reduced. Only active window 
     compacts (1 day of data, not 90 days).
  
  WHAT THIS PREVENTS: Links 2-8 of the entire cascade chain.
  
  MIGRATION PATH:
  → Can ALTER TABLE live (no data migration)
  → Existing SSTables will be handled by STCS rules until 
    they compact into time-aligned windows
  → New writes immediately go into TWCS windows
  → Full transition: ~90 days (as old STCS SSTables expire)
  
  CONSTRAINT: TWCS requires NO out-of-order writes (no 
  backfilling old time windows). If sensors can report late 
  data, need a separate table for backfill or accept that 
  late writes create small SSTables in sealed windows.
```

**L2 (FALLBACK)**: If TWCS can't be used (out-of-order writes required), use **LCS** (LeveledCompactionStrategy):
- Guaranteed bounded SSTable count per level
- Bounded read amplification (worst case: one SSTable per level, ~10 levels)
- Needs only ~10% transient free space (vs STCS 50%)
- Tradeoff: higher write amplification (4-8× vs STCS 2-3×)

**L3 (LAST RESORT)**: Stay on STCS but with strict disk monitoring and automated compaction throttling (Action 6 below handles this).

## Change 2: Partition Key Redesign

**Defense Layer: L1 (PRIMARY) — prevents oversized partitions that amplify tombstone scans.**

```
  CURRENT SCHEMA:
  PRIMARY KEY ((sensor_id, day), event_time)
  
  Partition size = 1 sensor × 1 day × 17,280 readings
  At ~100 bytes/row: 17,280 × 100 = ~1.7MB per partition
  
  This is REASONABLE for daily queries. But the problem 
  shows "Maximum partition size: 2.4GB" — this means 
  SOMETHING is creating giant partitions.
  
  INVESTIGATION: 2.4GB partition ÷ ~100 bytes/row = ~24M rows.
  That's ~1,389 DAYS of data for one sensor in one partition.
  
  POSSIBLE CAUSE: application bug writing wrong 'day' value,
  OR the 2.4GB is INCLUSIVE of tombstones (14,200 tombstones 
  per read × many reads = large on-disk partition with dead data).
  
  REGARDLESS — defensive partition design:
  
  Option A (if query pattern allows): Add hour bucketing
  
    PRIMARY KEY ((sensor_id, day, hour), event_time)
    
    Partition size: 17,280 / 24 = 720 rows per partition
    Max tombstones per partition scan: 720 (not 17,280)
    Dashboard query "last 24h" = 24 parallel partition reads
    (scatter within same node — fast)
    
  Option B (keep current, add guard): Enforce partition size limit
    
    ALTER TABLE iot.readings WITH 
      compaction = {
        ...
        'max_threshold': 32  -- limit SSTables per compaction
      };
      
    Application-side: validate 'day' format before writing.
    Add integration test asserting partition key correctness.
  
  WHAT THIS PREVENTS: TombstoneOverwhelmingException on individual 
  partitions. Even without compaction, smaller partitions have 
  fewer tombstones per scan.
```

**L2 (FALLBACK)**: Application-level query LIMIT on all reads (max 20,000 rows per query). Prevents unbounded tombstone scanning regardless of partition size.

**L3 (LAST RESORT)**: Cassandra-side tombstone_failure_threshold set to a sane elevated value (e.g., 200,000) with alerting at 50,000 — converts hard failures into degraded-but-serving responses while the actual fix is applied.

## Change 3: Repair Automation

**Defense Layer: L1 (PRIMARY) — prevents the zombie data time bomb.**

```
  DEPLOY CASSANDRA REAPER (or equivalent):
  
  Reaper (reaper.io) provides:
  → Automated scheduled repairs
  → Subrange repair (lightweight, less impact)
  → Segment-based progress tracking
  → Pause/resume capability
  → Multi-datacenter awareness
  → Dashboard for repair status
  
  CONFIGURATION:
  
  Repair schedule: complete full repair cycle every 7 DAYS.
  (MUST be < gc_grace_seconds of 10 days, with margin)
  
  repair_schedule:
    interval_days: 7
    repair_type: SUBRANGE
    segment_count_per_node: 256
    intensity: 0.5         # use 50% of available throughput
    repair_parallelism: DATACENTER_AWARE
    incremental: false     # full Merkle repair (safer in 3.x)
    
  WHY 7 DAYS (not 9):
  gc_grace_seconds = 10 days.
  Repair must COMPLETE within 10 days.
  7-day schedule = 3 days of buffer for delays, retries, 
  or partial failures before gc_grace window closes.
  
  ALERT IF: repair cycle takes >9 days to complete.
  CRITICAL ALERT IF: repair hasn't completed in 10 days.
  BLOCK COMPACTION TOMBSTONE PURGING IF: repair gap > gc_grace.
    (Cassandra 4.0+: -Dcassandra.allow_unsafe_aggressive_
    sstable_expiration=false when repair is overdue)
  
  WHAT THIS PREVENTS: The entire zombie data scenario from Q2.
  gc_grace_seconds is meaningless without repair. This makes 
  repair a first-class automated operation, not a manual 
  afterthought.
```

**L2 (FALLBACK)**: If Reaper fails or is unavailable, cron-based `nodetool repair` with a wrapper script that:
- Runs sequential repair per node
- Checks completion before moving to next node
- Alerts on failure
- Has been tested in staging

**L3 (LAST RESORT)**: Increase gc_grace_seconds to 30 days (buys more time for manual repair, at the cost of retaining tombstones longer = more disk and more tombstone scanning). This is a tradeoff, not a solution.

## Change 4: Disk Capacity Planning + Monitoring

**Defense Layer: L1 (PRIMARY) — prevents the disk exhaustion that started the entire cascade.**

```
  MONITORING ALERTS (ordered by urgency):
  
  ┌─────────────────────────────────────────────────────────┐
  │  METRIC                    │ WARN    │ CRITICAL │ ACTION│
  ├────────────────────────────┼─────────┼──────────┼───────┤
  │  Disk utilization          │  40%    │  50%     │ resize│
  │  (STCS threshold: 50%)     │         │          │       │
  │                            │         │          │       │
  │  Pending compactions       │  50     │  200     │ page  │
  │  per node                  │         │          │       │
  │                            │         │          │       │
  │  SSTable count per table   │  20     │  40      │ page  │
  │                            │         │          │       │
  │  Bloom filter FP ratio     │  0.05   │  0.10    │ invest│
  │                            │         │          │       │
  │  Tombstones per read (avg) │  500    │  5,000   │ page  │
  │                            │         │          │       │
  │  p99 read latency          │  30ms   │  100ms   │ page  │
  │                            │         │          │       │
  │  Repair age (days since    │  8      │  9       │ BLOCK │
  │  last successful full      │         │          │ comp. │
  │  repair)                   │         │          │ purge │
  │                            │         │          │       │
  │  Heap usage (bloom filter  │  25%    │  35%     │ invest│
  │  component)                │         │          │       │
  │                            │         │          │       │
  │  Compaction throughput     │  <50%   │  <25%    │ diag  │
  │  vs configured max         │  config │  config  │       │
  │                            │         │          │       │
  │  Partition size (max)      │  500MB  │  1GB     │ invest│
  └────────────────────────────┴─────────┴──────────┴───────┘
  
  CAPACITY PLANNING FORMULA:
  
  Data volume per node per day:
    51.8M writes/day × ~100 bytes × RF=3 ÷ 12 nodes = ~1.3GB/day
  
  With 90-day TTL at steady state:
    1.3GB/day × 90 days = ~117GB per node (live data)
  
  STCS space amplification:
    Worst case: 2× (transient compaction overhead)
    Size with amplification: 117GB × 2 = 234GB
  
  STCS 50% rule:
    Minimum disk size: 234GB × 2 = 468GB per node
    With growth buffer (20%): 468GB × 1.2 = 562GB
    
  CURRENT: 2TB per node is PLENTY for fair distribution.
  
  THE REAL PROBLEM: vnode imbalance means Nodes 7/3 get 
  ~1.5× their fair share → 351GB live data → 702GB with 
  amplification → 1.4TB at 50% threshold.
  
  Fix the imbalance (Change 5) and 2TB is sufficient.
  
  AUTOMATED DISK EXPANSION:
  If cloud: auto-scaling policy on disk utilization.
    AWS: CloudWatch alarm on disk% → Lambda → modify-volume
    Trigger at 40% utilization. No human approval needed.
    THIS IS THE MOST IMPORTANT AUTOMATION — it removes the 
    human decision that failed over the past 14 months.
```

**L2 (FALLBACK)**: Manual disk expansion runbook with SLA: respond within 2 hours of 40% warning, expand within 4 hours of 50% critical. Runbook is pre-approved (no change management gate).

**L3 (LAST RESORT)**: Automatic nodetool drain of any node exceeding 85% disk utilization. Sacrifices availability of that node's ranges to prevent the compaction death spiral. Other replicas serve reads at CL=ONE. Verify before enabling: confirm no two replica-set peers share this auto-drain policy simultaneously (would kill quorum).

## Change 5: Vnode Rebalancing

**Defense Layer: L1 (PRIMARY) — eliminates the precondition that allowed uneven disk usage.**

```
  OPTION A: Rebalance vnodes (if num_tokens is configurable).
  
  For Cassandra 3.x:
    → Cannot rebalance in-place. Must decommission + rejoin 
      with new token assignment.
    → Process: 
      1. Add a NEW node with proper tokens
      2. Run nodetool cleanup on existing nodes (frees data)
      3. Decommission the imbalanced node
      4. Repeat for each imbalanced node
    → SLOW (days), but correct.
    
  For Cassandra 4.0+:
    → Token allocation improved with allocate_tokens_for_keyspace
    → New nodes automatically get balanced tokens
    → Still requires decommission/rejoin for existing nodes
    
  OPTION B: Use allocate_tokens_for_local_replication (4.0+)
    → Automatically optimizes token distribution for the 
      given replication factor
    → Applied on new nodes joining the cluster
    
  VERIFICATION:
    nodetool ring
    → Each node should own ~8.33% of token ranges (1/12)
    → Nodes 7/3 currently own ~12-13%
    → After rebalancing: all within ±1% of 8.33%
    
  MONITORING:
    Alert if any node's effective ownership deviates 
    >20% from fair share:
    nodetool describering iot
    → Compare effective ownership per node
    → Alert if max/min ratio > 1.2
```

**L2 (FALLBACK)**: If rebalancing is too risky, right-size disks per node based on actual ownership. Node 7 owns 1.5× fair share → give it 1.5× disk (3TB instead of 2TB). This accepts the imbalance and compensates for it.

**L3 (LAST RESORT)**: Monitor per-node ownership and alert if skew exceeds 20%. Manual review within 1 week. No automated action (rebalancing is too high-risk to automate).

## Change 6: Operational Runbook — Compaction Emergency

**Defense Layer: L1 (PRIMARY) — eliminates the human response delay that let 3 weeks pass.**

```
  RUNBOOK: "Compaction Backlog Emergency"
  
  TRIGGER: pending compactions > 200 per node for > 1 hour
  
  AUTOMATED ACTIONS (no human approval):
  1. Increase compaction throughput to 256MB/s
  2. Page on-call SRE
  3. If disk > 50%: trigger disk expansion (Change 4 automation)
  
  HUMAN ACTIONS (within 30 minutes of page):
  1. Check nodetool compactionstats — is compaction actually running?
  2. Check disk utilization — is this a space problem?
  3. Check Cassandra logs for compaction errors
  4. If space problem: verify disk expansion completed
  5. If I/O problem: check competing workloads (repair running?)
  6. If configuration problem: check compaction strategy settings
  
  ESCALATION:
  → 1 hour: pending > 200 → SRE page
  → 4 hours: pending > 500 → engineering lead
  → 8 hours: pending > 500 → incident commander
  → 24 hours: no improvement → management escalation
  
  WHAT THIS PREVENTS: the 3-week gap between compaction 
  failure starting and human detection. The current incident 
  was detected by user complaint ("dashboard is slow"), 
  not by monitoring. This runbook ensures detection within 
  1 hour and human response
```
  WHAT THIS PREVENTS: the 3-week gap between compaction 
  failure starting and human detection. The current incident 
  was detected by user complaint ("dashboard is slow"), 
  not by monitoring. This runbook ensures detection within 
  1 hour and human response within 30 minutes.
```

## Complete Defense Matrix

```
  ┌──────────────────────────────────────────────────────────────────────────────────────────┐
  │  FAILURE MODE           │ L1 (PRIMARY)      │ L2 (FALLBACK)     │ L3 (LAST RESORT)       │
  ├─────────────────────────┼───────────────────┼───────────────────┼────────────────────────┤
  │  SSTable proliferation  │ TWCS (Change 1)   │ LCS alternative   │ STCS + strict disk     │
  │  & compaction stall     │ Sealed windows    │ Bounded SSTable   │ monitoring (Change 4)  │
  │                         │ never re-compact  │ count per level   │                        │
  ├─────────────────────────┼───────────────────┼───────────────────┼────────────────────────┤
  │  Tombstone accumulation │ TWCS whole-file   │ App-level query   │ Elevated tombstone     │
  │  & scan overhead        │ drop (Change 1)   │ LIMIT (Change 2)  │ threshold + alert      │
  │                         │ No tombstones     │ Bounds scan cost  │ (Change 2 L3)          │
  │                         │ for TTL expiry    │                   │                        │
  ├─────────────────────────┼───────────────────┼───────────────────┼────────────────────────┤
  │  Zombie data            │ Reaper automated  │ Cron repair       │ Increase gc_grace to   │
  │  resurrection           │ repair (Change 3) │ with wrapper      │ 30 days (buys time,    │
  │                         │ 7-day cycle       │ script + alerts   │ not a fix)             │
  ├─────────────────────────┼───────────────────┼───────────────────┼────────────────────────┤
  │  Disk exhaustion        │ Auto-expand disk  │ Manual runbook    │ Auto-drain node at     │
  │                         │ at 40% (Change 4) │ with 2hr/4hr SLA  │ 85% (sacrifice avail.) │
  │                         │ No human decision │                   │ Verify no double-drain │
  ├─────────────────────────┼───────────────────┼───────────────────┼────────────────────────┤
  │  Vnode imbalance        │ Rebalance tokens  │ Right-size disk   │ Monitor ownership skew │
  │                         │ (Change 5)        │ per actual owner- │ Alert if >20% deviation│
  │                         │ Decommission/     │ ship (compensate) │ Manual review 1 week   │
  │                         │ rejoin cycle      │                   │                        │
  ├─────────────────────────┼───────────────────┼───────────────────┼────────────────────────┤
  │  Slow human detection   │ Automated runbook │ Pager at pending  │ Dashboard user         │
  │  (3-week gap)           │ (Change 6)        │ > 200 + disk >50% │ complaints (current    │
  │                         │ Auto-action +     │ Human in 30 min   │ state — unacceptable)  │
  │                         │ page in 1 hour    │                   │                        │
  ├─────────────────────────┼───────────────────┼───────────────────┼────────────────────────┤
  │  Bloom filter heap      │ TWCS reduces      │ Off-heap bloom    │ Increase heap or       │
  │  pressure               │ SSTable count     │ filters (C* 4.0+  │ reduce bloom filter    │
  │                         │ → fewer filters   │ supports this)    │ bits_per_key (accept   │
  │                         │ → less heap       │                   │ higher FP rate)        │
  └─────────────────────────┴───────────────────┴───────────────────┴────────────────────────┘
```

## Failure Independence Verification

```
  IF Change 1 fails (TWCS migration incomplete):
  → Change 3 (Reaper) still prevents zombies
  → Change 4 (disk monitoring) still prevents disk exhaustion
  → Change 6 (runbook) still catches compaction backlog early
  → Tombstone accumulation will still occur, but Change 2 
    (query limits) bounds the per-query impact
  
  IF Change 3 fails (Reaper down, repair not running):
  → Change 1 (TWCS) eliminates MOST tombstones (whole-file drop)
  → Remaining tombstones (from explicit DELETEs, not TTL) still 
    need repair, but the volume is 1000× smaller without TTL 
    tombstones
  → gc_grace_seconds L3 (30 days) buys more time
  → Alert fires at repair age > 8 days → human intervention
  
  IF Change 4 fails (disk expansion doesn't trigger):
  → Change 1 (TWCS) needs far less disk space than STCS 
    (~15% overhead vs 50%)
  → Change 5 (vnode rebalance) prevents uneven distribution
  → Change 6 (runbook) detects compaction backlog from disk 
    pressure within 1 hour
  → L3 auto-drain removes the node before compaction death spiral
  
  IF Change 5 fails (vnode rebalance not completed):
  → Change 4 L2 (right-size disk per ownership) compensates
  → Change 4 L1 (auto-expand) handles organic growth
  → Monitoring alerts if skew exceeds 20%
  
  EVERY failure mode has at least TWO independent defenses.
  No single change failure can recreate the full cascade.
```

## Implementation Priority and Timeline

```
  ┌────────┬───────────────────────────────────────────────────┐
  │ WEEK 1 │ Change 1: ALTER TABLE → TWCS (live, no downtime)  │
  │        │ Change 3: Deploy Reaper, start first repair cycle │
  │        │ Change 4: Deploy disk monitoring + auto-expand    │
  │        │ Change 6: Deploy compaction runbook + alerting    │
  ├────────┼───────────────────────────────────────────────────┤
  │ WEEK 2 │ Change 2: Application query limits deployed       │
  │        │ Change 3: First Reaper repair cycle completes     │
  │        │ Change 4: Verify auto-expand triggered correctly  │
  │        │           in staging                              │
  ├────────┼───────────────────────────────────────────────────┤
  │ WEEK 3 │ Change 5: Begin vnode rebalancing (first node)    │
  │        │ Verify TWCS windows forming correctly             │
  │        │ Verify tombstone counts dropping on new writes    │
  ├────────┼───────────────────────────────────────────────────┤
  │ WEEK 4 │ Change 5: Continue rebalancing (2-3 nodes/week)   │
  │  -8    │ Monitor all metrics trending toward targets       │
  │        │ Validate zombie data scope (spot-check old reads) │
  ├────────┼───────────────────────────────────────────────────┤
  │ WEEK 12│ Full rebalance complete                           │
  │        │ TWCS has replaced all STCS SSTables               │
  │        │ (90-day TTL means old STCS files fully expired)   │
  │        │ All metrics at target levels                      │
  │        │ Post-implementation review                        │
  └────────┴───────────────────────────────────────────────────┘
```

## Zombie Data Remediation (parallel to architecture changes)

```
  The 67 days of potential zombie data (Q2) must be addressed:
  
  STEP 1: After Reaper's first full repair completes (Week 2):
  → All replicas are now consistent
  → Any zombie rows that were resurrected are now consistently 
    resurrected across all replicas (repair propagated them)
  → These zombies will NOT self-expire (their original TTL 
    timestamp already passed — Cassandra won't re-apply TTL 
    to resurrected data)
  
  STEP 2: Identify zombie rows.
  
    Run analytics query per sensor:
    SELECT sensor_id, day, COUNT(*) FROM iot.readings
    WHERE sensor_id = ? AND day = ?
    
    For days older than 90 days: ANY rows returned are zombies.
    
    Scope: check day values from 91-157 days ago 
    (90-day TTL + 67-day zombie window).
  
  STEP 3: Explicitly DELETE zombie rows.
  
    DELETE FROM iot.readings 
    WHERE sensor_id = ? AND day = ?
    
    For each zombie partition identified in Step 2.
    Run at CL=QUORUM to ensure deletion propagates.
    
    These new tombstones will be properly handled by repair 
    (Reaper is now running) and properly purged by compaction 
    (TWCS or repaired STCS).
  
  STEP 4: Validate.
    Re-read the same partitions. Expect zero rows.
    If rows reappear after repair: indicates a deeper 
    consistency issue. Escalate.
```

