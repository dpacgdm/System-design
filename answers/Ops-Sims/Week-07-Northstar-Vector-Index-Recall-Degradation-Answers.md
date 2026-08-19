# Ops-Sim Answer Key: Week 07 — Northstar Vector Index HNSW Recall Degradation

## 1. Root Cause Analysis (5-Whys)
1. **Why did Recall@10 drop to 62%?** HNSW graph traversal encountered disconnected graph paths.
2. **Why disconnected paths?** High deletion volume created 1.2M tombstones without restructuring neighbor edges.
3. **Why no edge restructuring?** Vector database garbage collection frequency was set to `daily` instead of `continuous`.
4. **Why high mutation rate?** Recommendation re-ranking job deleted and re-inserted vectors instead of updating payload in-place.
5. **Why search parameter low?** `efSearch` was set to 16 to save CPU, restricting candidate graph traversal depth.

## 2. Immediate Containment Commands
```bash
# Increase efSearch parameter dynamically to bypass graph disconnects
curl -X POST http://vector-db:6333/collections/products -H 'Content-Type: application/json' \
  -d '{"params": {"hnsw_config": {"ef_search": 128}}}'

# Trigger background compaction and tombstone garbage collection
curl -X POST http://vector-db:6333/collections/products/compact
```
