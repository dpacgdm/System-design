# Vector Databases — Socratic Check Answer Key

## Question 1: Throughput Drop When Increasing `efSearch`

**Answer:**
The throughput drop is caused by **Expanded Priority Queue Size during Layer 0 Graph Traversal**.

`efSearch` controls the size of the dynamic priority queue used during the greedy nearest-neighbor search phase on `Layer 0`.
* At `efSearch=32`, the algorithm evaluates distance against a maximum candidate frontier of 32 nodes before terminating.
* At `efSearch=256`, the candidate frontier expands by 8x. The CPU must perform 8x more SIMD distance calculations ($O(\text{efSearch} \times M_{\text{max}} \times D)$) per query, visiting significantly more graph nodes.

Because distance calculations dominate query execution time, increasing `efSearch` by 8x increases CPU work per query proportionally, dropping total cluster QPS from 2,500 to 400 while improving recall accuracy.

---

## Question 2: Memory Bloat and Insertion Stalls Post-Soft Deletes

**Answer:**
The root cause is **HNSW Routing Graph Tombstone Accumulation and Graph Path Fragility**.

1. **Why RAM Remains Constant:** In HNSW graphs, simply deleting a node pointer would sever navigation paths between upper and lower layers for neighboring nodes. Vector DB engines handle deletes by marking nodes as **Tombstones (Soft Deletes)** while retaining their structural pointers in memory to preserve graph navigation connectivity.
2. **Why Ingestion Stalls:** As soft deletes accumulate, newly inserted vectors traversing the HNSW graph spend CPU cycles visiting tombstoned nodes that cannot be returned in final results. The candidate priority queue fills up with dead nodes, forcing the graph insertion algorithm to perform additional hop steps to find valid non-tombstoned neighbors to establish $M_{\text{max}}$ links.

**Mitigation:**
Trigger an asynchronous index compaction / vacuum to rebuild the HNSW graph topology cleanly without dead node tombstones.
