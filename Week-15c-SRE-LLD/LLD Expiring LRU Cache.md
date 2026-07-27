# LLD: Expiring / LRU Cache (SRE-thick)

**Contract:** MODULE_CONTRACT_V2 · **Archetype:** Design · **Tier:** Core (SRE LLD)  
**Prep:** [TIMED_INTERVIEW_OS](../00-Curriculum/TIMED_INTERVIEW_OS.md) · [Caching Patterns](../Week-02-Storage-Fundamentals/Caching%20Patterns.md) · [Consistent Hashing](../Week-03-Distributed-Systems-Theory/Consistent%20Hashing.md)  
**Timebox:** 45 min · **Drill:** 20 min micro  
**Sealed:** [answers/Week-15c-SRE-LLD/LLD Expiring LRU Cache.answers.md](../answers/Week-15c-SRE-LLD/LLD%20Expiring%20LRU%20Cache.answers.md)

---

## Why this is SRE LLD

Caches are where **latency wins** and **correctness dies**. Interviewers want concurrency, eviction under memory pressure, stampede control, and what happens when the cache lies after a deploy or partition.

---

## Problem statement

Design a thread-safe in-process cache with:

- Get / put / invalidate
- Capacity bound (max entries or max bytes)
- TTL expiration + LRU (or LFU) eviction
- Optional single-flight loader to prevent stampedes
- Metrics for hit ratio, eviction cause, load latency

Optional stretch: write-through vs cache-aside; multi-replica invalidation hook.

Non-goals: full Redis; distributed cache cluster design (point to HLD Caching week).

---

## Requirements

| Dimension | Target | Tradeoff |
|-----------|--------|----------|
| Hit ratio | Workload-dependent; measure, don't invent | Bigger cache ≠ always better (GC / RSS) |
| Get latency | O(1) expected | Exact LFU is costlier than LRU |
| Memory | Hard cap | Evict before OOM; never unbounded map |
| Freshness | TTL + explicit invalidate | Stale-while-revalidate vs hard expire |
| Stampede | Single-flight per key | Loader failure must not wedge waiters |

---

## Core structures

```text
class Cache<K,V> {
  final int capacity;
  final Duration defaultTtl;
  final Map<K, Node> map;          // HashMap
  final DoublyLinkedList lru;      // head=MRU, tail=LRU
  final ReadWriteLock or striped locks;

  Optional<V> get(K key);
  void put(K key, V value, Duration ttl);
  void invalidate(K key);
  V getOrLoad(K key, Loader<K,V> loader);
}

class Node {
  K key; V value;
  Instant expiresAt;
  Node prev, next;
  long sizeBytes; // if size-aware
}
```

**Invariants:**
1. `map.size() ≤ capacity` (or bytes ≤ maxBytes)
2. Every map entry is exactly once in the LRU list
3. Expired entries are treated as miss (lazy) and optionally swept (eager)

---

## Algorithms

### LRU on access
- get hit → move node to MRU
- put on full → evict LRU tail (if not being loaded)

### TTL
- Lazy: on get, if `now ≥ expiresAt` → remove + miss
- Eager: background sweeper samples / timing wheel — discuss CPU vs memory tradeoff

### Single-flight (`getOrLoad`)
```text
inflight: Map<K, CompletableFuture<V>>
on miss:
  if inflight.contains(key): await same future
  else: create future, load, put, complete, remove inflight
on load failure: complete exceptionally; all waiters fail; do not cache error unless negative-cache TTL
```

### Size-aware eviction
- Track `sizeBytes`; evict until under watermark (high/low) — prevent oscillation

---

## Concurrency

| Approach | Pros | Cons |
|----------|------|------|
| Single global mutex | Simple correctness | Throughput cliff |
| ReadWriteLock | Concurrent gets | Writer starvation risk |
| Striped locks by key hash | Scales | Cross-key eviction harder — need global size lock or approximate |
| ConcurrentHashMap + ConcurrentLinkedQueue approximations | Fast | Exact LRU harder (use W-TinyLFU / Clock) |

**Interview honesty:** say "exact LRU under high concurrency is expensive; production often uses Clock / W-TinyLFU (Caffeine)." Sketch classic LRU first, then name the upgrade.

---

## Failure & correctness modes

| Mode | What breaks | Mitigation |
|------|-------------|------------|
| Stampede on expiry | Origin overload | Single-flight + probabilistic early expire |
| Cache stamped false data | Wrong answers at scale | Short TTL; version in key; invalidate on write |
| Negative caching none | Retry storm on 404 | Brief negative TTL |
| Invalidate missed | Split-brain stale | Pub/sub invalidate; version tokens |
| Loader hangs | Threads pile on key | Timeout + circuit on loader |
| Soft references only | GC thrash | Hard capacity + RSS alert |
| Size underestimate | OOM | Measure serialized size or conservative estimate |

---

## Operability

**Metrics:** `hit_ratio`, `evictions{cause=lru|ttl|manual|size}`, `load_latency`, `inflight_gauge`, `size_entries`, `size_bytes`.  
**Alerts:** hit ratio collapse; eviction storm; loader error rate; RSS near limit.  
**Dashboards:** top keys by miss (sampled); deploy markers overlay.  
**Config:** capacity, TTL, negative TTL — canary.

---

## Sketch → critique

```text
Service → Cache.getOrLoad(key)
  → hit & fresh → return
  → miss → single-flight → DB/RPC → put(ttl) → return
Write path → DB write → cache.invalidate(key) [+ async bus]
```

**Critique:** read-your-writes? multi-thread get during put? what if invalidate arrives before put completes?

---

## 20-min micro-drill

Whiteboard **only**: concurrent LRU + TTL lazy expire + single-flight. Include lock strategy and 4 failure modes.

---

## Self-check

- [ ] O(1) get/put structure named
- [ ] Capacity hard bound
- [ ] TTL + LRU interaction clear
- [ ] Stampede control
- [ ] Metrics for hit/evict/load
- [ ] Stale after write addressed

---

## Blind transfer

After a config push, TTL goes from 5m to 5s. Origin CPU burns. Walk the causal chain and the safer rollout.
