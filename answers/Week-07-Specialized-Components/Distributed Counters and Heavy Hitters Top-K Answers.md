# Answer Key - Week 7: Distributed Counters and Heavy Hitters Top-K

> Open only after attempting the learner file scenario questions.

## Principal Model Answer & Interview Evaluation Matrix

```
╔══════════════════════════════════════════════════════════════════════════╗
║ PRINCIPAL MODEL ANSWER SUMMARY — DISTRIBUTED COUNTERS & HEAVY HITTERS    ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 1. Sharded Redis counters eliminate single-core hot-key CPU saturation.  ║
║ 2. Count-Min Sketch provides bounded one-sided overestimation in 76KB.   ║
║ 3. Space-Saving + Min-Heap tracks Top-K stream trends in constant O(K).  ║
║ 4. Bloom filters gate and deduplicate viral bot plays before the stream. ║
║ 5. Decoupled async flushers protect database WALs from write storms.     ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Detailed Model Solutions to Section 9 Practice Drills

### Q1: Viral Video Redis INCR Bottleneck
* **Root Cause:** Redis executes single-threaded on a single CPU core. At 100k views/sec, CPU is consumed entirely by networking socket reads and single-key lock serialization.
* **Architectural Fix:** Partition into $M$ sub-counters: `views:{video_id}:{shard_id}` where `shard_id = rand() % M`.
* **Read Path:** `MGET views:{video_id}:0 ... views:{video_id}:M-1` and sum in the API application layer. Sub-millisecond read, 10x throughput boost.

### Q2: Count-Min Sketch vs Hash Map Tradeoffs
* **Space Bound:** A hash map for 500M unique search queries requires $> 16 	ext{ GB}$ of RAM. Count-Min Sketch requires $W 	imes D 	imes 4 	ext{ bytes} pprox 76 	ext{ KB}$ for $\epsilon = 0.001, \delta = 0.001$.
* **Error Bound Proof:** For true count $C(x)$ and estimate $\hat{C}(x)$, the algorithm guarantees:
  $$\hat{C}(x) \ge C(x) \quad 	ext{and} \quad \hat{C}(x) \le C(x) + \epsilon N 	ext{ with probability } \ge 1 - \delta$$

### Q3: Anti-Fraud and Bot View Deduplication
* **Layer 1 (Edge WAF):** Rate limit IP bursts at Cloudflare/Envoy API Gateway.
* **Layer 2 (Stateful Bloom Filter):** Keyed by `hash(video_id, user_id, user_agent)`. Filter has a 24-hour expiration window.
* **Layer 3 (Offline Auditing):** Asynchronous MapReduce / Spark job compares view timestamps against IP session entropy; inflations are decremented from durable totals.

### Q4: Database Outage Resilience
* **Decoupling Ingestion from Storage:** Kafka acts as the durable shock absorber. View counts continue serving from Redis in-memory cache without interruption.
* **Catch-Up Synchronization:** Once ClickHouse restarts, flusher consumers resume offset processing with idempotency keys, avoiding duplicate counting.

### Q5: Space-Saving Top-K Guarantee
* **Theorem:** In a stream of $N$ items, any item with frequency $f > rac{N}{K + 1}$ is guaranteed to be present in the Space-Saving summary table of size $K$.
* **Error Margin:** The error on any item's frequency count never exceeds $rac{N}{K + 1}$.
