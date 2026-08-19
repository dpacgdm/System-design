# Ops-Sim: Week 07 — Northstar Vector Index HNSW Recall Degradation

## Incident Telemetry Brief
At **09:15 UTC**, semantic search recall accuracy dropped from 98.5% to 62.1% following a bulk catalog update of 5,000,000 product embeddings.

```
INCIDENT METRICS SIGNAL:
  - Vector Query Recall@10: 62.1% (Baseline 98.5%)
  - HNSW Graph Depth      : 16 layers (Degraded Graph Topology)
  - Un-indexed Tombstones : 1.2M deleted vectors
  - Search Latency (p99)  : 180ms (Baseline 12ms)
```

## SRE Diagnostic Checklist & Triage Objectives
1. Diagnose why high mutation rates caused HNSW graph tombstone accumulation.
2. Trigger dynamic background graph re-indexing and compaction.
3. Formulate an index optimization script to restore Recall@10 to > 98%.
