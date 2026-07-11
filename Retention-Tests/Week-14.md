# WEEK 14 RETENTION TEST

Covers **Weeks 1-14** with emphasis on Google Docs, LLM serving, feature stores, and realtime collaboration outages.

---

## Rules

```text
RULES OF ENGAGEMENT

1. Answer from memory. Do not open answer files, modules, or prior notes.
2. Rapid-fire: 2-4 sentences each.
3. Ops Sim: include telemetry interpretation, decisions, and recovery.
4. Honest uncertainty is better than invented certainty.
5. Open the answer key only after completing your attempt.
```

---

## Part 1: Rapid-Fire Concept Recall (16 Questions)

**Q1 (Current - Google Docs):** Why is "broadcast every keystroke over WebSocket" insufficient for collaborative editing?

**Q2 (Current - OT/CRDT):** Compare Operational Transformation and CRDTs for rich-text collaboration. Give one reason each might win.

**Q3 (Current - presence):** Why should cursor/presence state be stored differently from document operations?

**Q4 (Current - offline sync):** A client reconnects with queued edits from revision 100 while the server is at revision 140. What must the sync protocol do?

**Q5 (Current - LLM prefill/decode):** Distinguish prefill and decode phases. Which phase is more sensitive to long prompts and KV cache memory?

**Q6 (Current - KV cache):** What problem does vLLM-style PagedAttention solve?

**Q7 (Current - continuous batching):** Why does continuous batching improve GPU utilization for mixed-length LLM requests?

**Q8 (Current - feature store):** What is point-in-time correctness in offline feature retrieval, and why does it prevent label leakage?

**Q9 (Current - feature freshness):** Online feature store returns latest materialized value. What metric tells you it is too stale for inference?

**Q10 (Mid - WebSockets/TCP):** What happens if 300k collaboration clients reconnect with fixed 1s retry after an ALB/WebSocket deploy?

**Q11 (Mid - Kafka/outbox):** Why might document operations be written to an append-only op log before snapshotting to S3?

**Q12 (Mid - observability):** Name useful LLM serving metrics beyond HTTP latency.

**Q13 (Old - caching/CDN):** Which collaboration assets can be CDN-cached, and which realtime data must not be cached there?

**Q14 (Old - CAP):** For collaborative docs, why might you reject edits when the authoritative op sequencer is unavailable instead of accepting divergent writes?

**Q15 (Old - tenancy/cost):** In a multi-tenant LLM platform, how do priority queues and token budgets prevent one tenant from starving others?

**Q16 (Old - auth):** What authorization checks must occur before a WebSocket client can subscribe to a document room?

---

## Part 2: Compound Ops Sim - Realtime Collaboration and AI Outage

```text
INCIDENT REPORT

Severity: P1
Company: Northstar Commerce
Systems:
  - seller-docs: collaborative campaign docs for sellers
  - collab-gateway: WebSocket realtime editing
  - doc-oplog: append-only operation log
  - doc-snapshots: S3 snapshots
  - ai-copy-assist: LLM serving platform
  - seller-feature-store: online/offline features for campaign recommendations

Business event:
  Enterprise sellers prepare a live-auction campaign. AI copy assist
  generates product blurbs inside collaborative docs. A new feature-store
  materialization and a larger LLM context window launch the same morning.

Timeline:
  09:00 - Larger context window enabled for 20% tenants.
  09:08 - Feature materialization job starts late.
  09:15 - Collab gateways deploy.
  09:18 - Cursor presence starts flickering.
  09:23 - Edits duplicate or disappear for 2% of active docs.
  09:27 - AI copy assist p99 reaches 38s; GPU OOMs begin.
  09:35 - Enterprise seller reports wrong recommended products in doc.
```

### Telemetry Pack

```text
collab-gateway:
  active_websockets: 310k
  reconnects/min: 12k -> 420k
  fixed_retry_clients: 64%
  op_queue_depth_p99: 40 -> 18,000
  presence_updates/sec: 70k -> 1.4M
  ops_applied_out_of_order_total: +31k
  duplicate_op_id_rejections: 0.02% -> 4.9%

doc-oplog/snapshots:
  oplog append p99: 18ms -> 950ms
  snapshot job lag: 12 min -> 5.2h
  docs with >1000 ops since snapshot: 8% -> 46%
  idempotency key: client_op_id only, not doc_id+client_op_id

LLM serving:
  model: 70B, tensor_parallel=4
  max_context_tokens: 8k -> 32k for 20% tenants
  vllm_gpu_cache_usage_perc: 62% -> 98%
  num_requests_waiting: 200 -> 19,000
  num_requests_swapped: 0 -> 4,800
  avg_generation_throughput_toks_per_s: -55%
  GPU OOM restarts: 0 -> 37

feature store:
  online feature staleness p99: 4 min -> 3.8h
  offline backfill finished: false
  training-serving skew detector: +12 sigma on seller_popularity_7d
  recommendation CTR: -22%

customer:
  doc save success: 99.7% -> 96.1%
  edit convergence probe failures: 0 -> 2.4%
  enterprise tenant T-884 impacted: yes
```

### Config Pack

```text
collab:
  presence throttle: disabled
  max_ops_buffer_per_socket: 50000
  reconnect policy: fixed 1s for old web client
  op sequencing: server assigns revision; client optimistic apply
  room routing: doc_id hash to collab shard

LLM:
  max_num_seqs=256
  gpu_memory_utilization=0.92
  max_context_tokens=32768 for canary tenants
  premium and best-effort share same queue
  prefix cache enabled

feature store:
  materialization schedule: hourly
  online TTL: 6h
  freshness alert threshold: 30m, ticket only
  point-in-time join tests: skipped for emergency backfill
```

### Decision Points

**T+0:** What do you disable or throttle first across collab, LLM, and feature-store systems?

**T+5:** Some users see duplicated/disappearing edits. What is the safe mode for documents while you restore convergence?

**T+15:** GPU OOMs continue after adding more pods. What LLM-serving setting or traffic class do you change?

**T+60:** You need to repair affected docs and recommendations. What reconciliation steps prove convergence and feature correctness?

### Scenario Questions

1. Identify at least seven contributing factors across collab, LLM, feature store, and rollout operations.
2. Explain why presence flicker should not be allowed to starve document operations.
3. Explain the LLM OOM cascade using context length, KV cache, continuous batching, and queue priority.
4. Explain how feature staleness/training-serving skew produces wrong product recommendations inside docs.
5. **Bad-fix gallery:** Analyze (a) persist every cursor update to the document store, (b) accept edits independently in every region, (c) double `max_num_seqs`, (d) disable feature freshness alerts, (e) flush the prefix cache globally.
6. **Capacity question:** If context window increases 4x for 20% of traffic, what qualitative effect does that have on KV cache capacity and waiting queue? What metric confirms it?
7. **Org/runbook question:** What launch gates and runbooks should coordinate collab deploys, LLM context changes, and feature-store backfills?

---

## Self-Score Error-Type Table

| Error type | Count | Notes to review |
|------------|-------|-----------------|
| OT/CRDT/convergence error | | |
| WebSocket/reconnect/presence error | | |
| Oplog/snapshot/idempotency error | | |
| LLM KV cache/batching error | | |
| Feature-store freshness/skew error | | |
| Incident sequencing error | | |
| Capacity reasoning error | | |
| Org/runbook gap | | |

---

> **Answer key (do not open until you attempt the test):**  
> [`../answers/Retention-Tests/Week-14 Answers.md`](../answers/Retention-Tests/Week-14%20Answers.md)
