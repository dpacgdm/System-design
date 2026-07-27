# Answer Key — LLD Expiring / LRU Cache (SRE-thick)

> Open only after attempting the learner module and 20-min micro-drill.

## Grading bar (Staff)

| Criterion | Points | Pass |
|-----------|-------:|------|
| O(1) structure (map + DLL or named approx) | 5 | Correct invariants |
| Hard capacity bound | 4 | Evict before grow forever |
| TTL + LRU interaction | 4 | Expired = miss; eviction cause distinct |
| Single-flight / stampede | 5 | Shared future; failure doesn't wedge |
| Concurrency strategy | 4 | Named locks/stripes + tradeoff |
| Stale-after-write | 4 | Invalidate / version / TTL honesty |
| Operability | 4 | hit/evict/load metrics + alerts |
| Blind transfer | 4 | TTL shrink → origin burn chain |
| **Staff pass** | **/34** | **≥24** and no automatic fail |

**Automatic fails:** unbounded `HashMap` as production cache; ignore stampede; claim "just use Redis" with zero in-process concurrency story when asked for in-process LLD; cache errors forever with no negative TTL policy discussion.

---

## Expert model — classic concurrent LRU + TTL

### Structures

```text
map: HashMap<K, Node>
lru: doubly linked list (MRU at head, LRU at tail)
each Node: key, value, expiresAt, prev, next, sizeBytes?
lock: ReentrantLock OR ReadWriteLock OR striped + sizeMutex
inflight: ConcurrentHashMap<K, CompletableFuture<V>>
```

### Invariants (say these)

1. `map.size() ≤ capacity` (or `totalBytes ≤ maxBytes`)
2. Bijection: every map entry ↔ exactly one list node
3. Lazy expire: get on expired → remove → miss (optional eager sweeper)
4. Inflight entry removed in `finally` after load completes or fails

### get

```text
lock
  node = map.get(key)
  if node == null → miss
  if now >= node.expiresAt → unlink, map.remove, unlock → miss
  moveToHead(node)
  return value
unlock
```

### put

```text
lock
  if exists → update value/ttl, moveToHead
  else → while size >= capacity: evictTail(cause=lru)
         insert head
unlock
```

### getOrLoad (single-flight)

```text
opt = get(key); if present return
f = inflight.computeIfAbsent(key, k -> supplyAsync(loader))
try:
  v = f.get(loadTimeout)
  put(key, v, ttl)   # careful: may race with invalidate — see below
  return v
except:
  // do not put; optional negative cache short TTL
  throw
finally:
  inflight.remove(key, f)  # only if same future
```

**Waiters share one load.** Loader failure fails all waiters — correct; prevents forever hang if you also have timeout.

---

## TTL strategies

| Mode | How | Tradeoff |
|------|-----|----------|
| Lazy | Check on access | Cheap; dead entries linger until touched or size pressure |
| Eager sweeper | Sample / timing wheel | Extra CPU; better memory hygiene |
| Soft expire + SWR | Serve stale, revalidate async | Better UX; complexity + stampede on revalidate |

**Early expire (probabilistic):** refresh before TTL end with probability rising near expiry — reduces synchronized expiry stampede.

---

## Eviction causes (metric labels)

- `lru` — capacity
- `ttl` — expired on access or sweep
- `manual` — invalidate
- `size` — bytes watermark
- `replace` — put same key

Never mix causes silently — ops needs to know why hit ratio fell.

---

## Concurrency deep dive

### Global mutex
Correct, simple, dies under multi-core get-heavy workloads.

### ReadWriteLock
Concurrent hits; writers (put/evict) exclusive. Risk: writer starvation if gets never quit — use fair lock or accept.

### Striped locks
`lockFor(key)` for get/put of that key; **eviction and global size** need a separate protocol:
- Approximate size (AtomicLong) with periodic reconcile, or
- Brief global lock only for eviction decisions

### Production honesty
Caffeine: W-TinyLFU + hill climber; not textbook LRU. **Interview path:** draw textbook LRU, then say "I'd use Caffeine/Guava in Java; the point was concurrency + TTL + stampede."

---

## Stampede physics

```text
TTL ends for hot key K at T
10k threads miss simultaneously
10k origin queries → origin CPU melt → latency ↑ → more timeouts → more retries
```

Mitigations stacked:
1. Single-flight
2. Probabilistic early refresh
3. Stale-while-revalidate
4. Origin bulkhead / concurrency limit
5. Jittered TTLs per key (`ttl * (0.9 + 0.2*rand)`)

---

## Write path correctness

### Cache-aside (common)
```text
read: get or load from DB + put
write: DB write → invalidate (or put new)
```

**Race:** Thread A loads stale → Thread B writes+invalidates → Thread A puts stale back.

**Mitigations:**
- Version token in value / compare-and-set put
- Short TTL always
- Put-if-absent only after load with generation check
- Delay put until after verifying DB read-your-write version

### Write-through
Write DB and cache together — lower stale risk, higher write latency; failure partial updates need care.

### Multi-replica
In-process caches on N pods: invalidate bus (Redis pub/sub, Kafka) best-effort; **never** claim instant global consistency. Versioned keys help.

---

## Failure modes — Staff answers

| Mode | Breakage | Mitigation |
|------|----------|------------|
| Stampede | Origin overload | Single-flight + jitter + SWR |
| False data cached | Wrong answers at scale | Invalidate + version + short TTL |
| No negative cache | 404 retry storms | Negative TTL 1–30s |
| Missed invalidate | Stale split | Message bus + TTL ceiling |
| Loader hang | Thread pileup | Timeout; circuit breaker on loader |
| Soft-only refs | GC thrash / RSS surprise | Hard entry/byte cap + RSS alert |
| Size underestimate | OOM kill | Conservative size; host limit |
| Cache poison from error | Outage sticky | Don't cache 5xx; brief negative only |

---

## Operability exemplar

**Metrics:**
- `cache_hit_ratio` (or hits/misses counters)
- `cache_evictions_total{cause}`
- `cache_load_latency_ms`
- `cache_inflight_gauge`
- `cache_entries`, `cache_bytes`
- `cache_load_errors_total`

**Alerts:**
1. Hit ratio collapse vs baseline after deploy
2. Eviction storm (`lru` cause) — undersized or scan pattern
3. Loader error rate
4. RSS near pod limit
5. Inflight gauge stuck high → loader timeout bug

**Dashboards:** deploy markers; top miss keys **sampled**.

---

## 20-min micro-drill — Staff key

**Lock strategy:** single `ReentrantLock` for v1 correctness narration; mention RWLock/stripes as scale-up.

**Components:** HashMap + DLL + expiresAt + inflight map.

**Four failures:**
1. Stampede without single-flight  
2. Stale put-after-invalidate race  
3. Loader timeout wedging waiters (missing timeout)  
4. TTL synchronized expiry (no jitter)

---

## Blind transfer — Staff answer

**Causal chain:**
1. TTL 5m → 5s multiplies miss rate ~60× for previously hot keys (order-of-magnitude).
2. Misses become origin loads; single-flight helps per key but **many keys** expiring denser still multiply origin QPS.
3. Origin CPU / DB connections saturate.
4. Load latency ↑ → inflight hold time ↑ → thread pool / request queue pressure.
5. User latency SLO burn; possible retry amplification.

**Safer rollout:**
- Canary pods/tenants with new TTL
- Watch origin QPS, cache hit ratio, load latency, RSS
- Autonomic floor: if origin QPS > threshold, auto-revert TTL
- Prefer gradual: 5m → 2m → 1m → 30s with bake each step
- Pair TTL shrink with capacity increase only if working set fits; otherwise expect hit ratio drop

---

## Sketch critique answers

**Read-your-writes:** sticky session to same pod OR version in DB returned to client OR write-through on that key OR short bypass cache header for actor.

**Concurrent get during put:** lock or CHM compute; ensure moveToHead atomic with read under same protocol.

**Invalidate before put completes:** generation/version; discard put if generation mismatch; or invalidate sets tombstone generation.

---

## Below-bar vs Staff

**Below bar:** "LinkedHashMap accessOrder=true synchronized."  
**Staff:** Notes single lock throughput, TTL absence, stampede, stale race, metrics — then upgrades design.

**Below bar:** "Redis solves this."  
**Staff:** Redis is distributed cache; still need client stampede control, timeouts, and local hot-key cache often remains.

---

## Principal stretch

1. Design size-aware eviction with high/low watermark hysteresis.  
2. Compare LRU vs LFU vs W-TinyLFU for scan-resistant workloads.  
3. Multi-tier: L1 in-process + L2 Redis — coherency protocol.

### Stretch sketches

1. Evict to low watermark when high exceeded — prevent oscillation.  
2. Scans thrash LRU; LFU/W-TinyLFU resist.  
3. L1 short TTL; L2 longer; invalidate both on write; accept brief incoherence windows.

---

## Interview narration beats (45)

0–5 requirements + capacity/TTL  
5–20 structures + get/put  
20–30 single-flight + races  
30–40 failures + metrics  
40–45 Caffeine honesty + blind prompts  

---

## Scoring worksheet

```text
Structure ____ /5
Capacity ____ /4
TTL/LRU ____ /4
Stampede ____ /5
Concurrency ____ /4
Stale write ____ /4
Ops ____ /4
Blind ____ /4
TOTAL ____ /34
Auto-fail? ____
```

---

## Tie-ins

- Week-03 Caching HLD  
- Consistent hashing for distributed  
- Worker pool: loader uses bounded executor — don't sync-load on request threads unboundedly  
- Timed OS LLD battery

---

## Negative caching policy (explicit)

| Upstream result | Cache? | TTL |
|-----------------|--------|-----|
| 200 | yes | default |
| 404 | optional | 1–30s |
| 401/403 | usually no (or tiny) | — |
| 5xx | never | — |
| timeout | never | — |

---

## Memory & GC notes (SRE)

- Huge caches → old-gen pressure → long GC → latency cliffs  
- Measure RSS not just entry count  
- Cap bytes; alert at 80% of pod memory budget for cache  
- On eviction storm, check for full-scan keys (iterator abuse)

---

## End state claim

Staff-ready when you can draw map+DLL+inflight, name the stale put race, and walk a TTL-shrink outage without keys.
