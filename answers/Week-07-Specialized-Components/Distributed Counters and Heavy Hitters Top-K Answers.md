# Distributed Counters, Heavy Hitters and Top-K Streaming — Worked Answers

## Answer 1: Minimum vs. Average in Count-Min Sketch

1. **One-Sided Error Property**:
   Count-Min Sketch only increments counters; it never decrements them. Therefore, hash collisions can only **inflate** an entry's count.
2. **Noise Minimization**:
   If an item hashes into bucket $B_{i, j}$, that bucket's value is:
   $$\text{Bucket Value} = \text{True Count of Item} + \sum \text{Counts of Colliding Items}$$
   Since the noise term is strictly non-negative ($\ge 0$), the bucket with the **minimum** value contains the least amount of colliding noise.
3. **Why Not Average?**:
   Taking the average would incorporate inflated noisy buckets into the result. The minimum provides the tightest mathematical upper bound.

---

## Answer 2: Space-Saving Invariant for Heavy Hitters

1. **The Space-Saving Mechanism**:
   Maintains $K$ monitored elements. When a new stream item $x$ arrives:
   - If $x$ is already in the monitored set, increment its count: $c_x \leftarrow c_x + 1$.
   - If $x$ is NOT in the set, find the item $y$ with the **minimum count** $c_{\min}$. Replace $y$ with $x$, set $c_x \leftarrow c_{\min} + 1$, and set its maximum error $\epsilon_x \leftarrow c_{\min}$.
2. **Heavy Hitter Preservation**:
   Any item whose true frequency exceeds $\frac{N}{K}$ is mathematically guaranteed to appear in the monitored summary, because the maximum error on any replacement item is bounded by $\frac{N}{K}$. A true heavy hitter cannot be evicted by low-frequency noise.

---

## Answer 3: Atomic Reset/Deletion of Sharded Counters in Redis

1. **The Multi-Key Race Condition**:
   Deleting keys `counter:item:0` through `counter:item:15` individually allows concurrent writes to increment a key between deletions, leaving phantom residual counts.
2. **Atomic Deletion via Lua Script**:
   ```lua
   local item_id = ARGV[1]
   local num_shards = tonumber(ARGV[2])
   local keys = {}
   for i = 0, num_shards - 1 do
       table.insert(keys, "counter:" .. item_id .. ":" .. i)
   end
   return redis.call('DEL', unpack(keys))
   ```
3. **Redis Cluster Slot Tagging**:
   In a clustered Redis environment where keys are sharded across nodes, multi-key commands require all sub-keys to map to the same hash slot:
   $$\text{Key Pattern: } \text{counter:\{item\_123\}:0}, \dots, \text{counter:\{item\_123\}:15}$$
   The `{item_123}` hash tag forces all 16 shards into the exact same Redis node, enabling atomic Lua transactions!
