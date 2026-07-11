# Answer Key - Week-14

> Open only after attempting `Retention-Tests/Week-14.md`.

---

## Part 1: Rapid-Fire Model Answers

**Q1:** Concurrent edits can arrive in different orders and target the same positions. Without OT/CRDT or an authoritative sequencing protocol, clients diverge, lose keystrokes, or overwrite each other.

**Q2:** OT wins when a central server can order operations and metadata must stay compact, common for document editors. CRDTs win for offline/edge collaboration where replicas must merge without a central transformer, at the cost of metadata and compaction complexity.

**Q3:** Presence/cursors are ephemeral and high-frequency, so store them in Redis/pub-sub with TTL and throttling. Document operations are durable state and must go through the op log/snapshot path.

**Q4:** The client must rebase/transform queued edits from revision 100 through revisions 101-140, dedupe already-applied ops, then apply remaining operations under server sequencing. A CRDT path would exchange state vectors/updates and merge.

**Q5:** Prefill processes the prompt and builds KV cache; decode generates tokens autoregressively. Long prompts heavily affect prefill compute and KV cache memory, while long outputs stress decode throughput over time.

**Q6:** PagedAttention manages KV cache in blocks/pages instead of contiguous per-request allocation. It reduces fragmentation and lets more sequences share GPU memory efficiently.

**Q7:** Continuous batching admits new requests as others finish instead of waiting for a static batch to complete. It keeps GPUs busy despite varied prompt/output lengths.

**Q8:** Point-in-time correctness means training features are joined as of the event timestamp, not using future values. This prevents label leakage where training sees information unavailable at inference time.

**Q9:** `feature_staleness_seconds{feature}` or freshness lag by feature/entity. It should page when it exceeds the model's freshness SLO.

**Q10:** Fixed 1s retry synchronizes clients into a reconnect herd. Replacement gateways, Redis presence, and auth services can be overwhelmed.

**Q11:** The op log is the authoritative ordered history for replay, audit, conflict resolution, and snapshot generation. S3 snapshots speed load but are derived state.

**Q12:** GPU cache usage, requests waiting/running/swapped, prefill and decode tokens/sec, time-to-first-token, output tokens/sec, OOM count, queue depth by priority, model loading time, and KV block utilization.

**Q13:** Static JS/CSS, editor assets, images, and public templates can be CDN cached. Realtime document ops, presence, auth room state, and personalized doc contents must not be CDN cached.

**Q14:** Accepting divergent writes can fork document history and lose edits. For authoritative OT/op-sequencer designs, it is safer to reject or enter read-only/offline queue mode until sequencing returns.

**Q15:** Token budgets and priority queues reserve capacity by tenant/tier and shed best-effort requests first. They prevent one tenant's long prompts from consuming all KV cache and decode slots.

**Q16:** Authenticate the user, verify document ACL/role, tenant membership, sharing link scope, document id binding, and optionally enforce room capacity/rate limits before subscribing.

---

## Part 2: Compound Scenario - Expert Analysis

### Contributing Factors

| Factor | Area | Evidence |
|--------|------|----------|
| Gateway deploy caused reconnect storm | Collab | reconnects/min 420k, fixed retry clients 64% |
| Presence unthrottled | Collab | presence updates 1.4M/sec |
| Presence competes with ops | Collab | op queue depth p99 18,000 |
| Op idempotency key too broad | Collab | client_op_id only, duplicate rejections 4.9% |
| Snapshot lag/replay cost | Collab | docs >1000 ops since snapshot 46% |
| Context window 4x | LLM | 8k -> 32k for canary tenants |
| KV cache saturation | LLM | gpu_cache_usage 98%, swapped 4,800 |
| No priority isolation | LLM | premium/best-effort same queue |
| Feature materialization late | Feature store | staleness p99 3.8h |
| Point-in-time tests skipped | Feature store | skew detector +12 sigma |
| Rollouts overlapped | Ops | collab deploy, context change, feature backfill same morning |

### T+0 Decision

- Collab: throttle/drop presence first, cap reconnects with server-directed backoff if possible, disable old-client rollout path, and prioritize document ops over cursor updates.
- LLM: roll back 32k context canary or restrict it to tiny premium allowlist; shed best-effort AI copy requests.
- Feature store: disable stale recommendation feature or fall back to last known-good feature set/model; page feature-store owner because 3.8h staleness is user-impacting.

### T+5 Safe Document Mode

For affected docs, preserve correctness over realtime polish:

- Enter degraded mode: document edits go through authoritative sequencer only; if queue too deep, make document read-only or local-offline queue with clear UI.
- Drop/throttle presence and comments before document ops.
- Require `(doc_id, client_op_id)` idempotency and server revision checks.
- Stop accepting independent regional writes that bypass the sequencer.

### T+15 LLM Change

Adding pods may not help if each request consumes too much KV cache or weights are cold-loading. Roll back `max_context_tokens` to 8k or lower canary percentage; reduce `max_num_seqs`, separate premium/best-effort queues, enforce token budgets, and cap prompt length. The confirming metrics are lower `vllm_gpu_cache_usage_perc`, fewer swapped requests, fewer OOMs, and falling waiting queue.

### T+60 Repair

Documents:

1. Identify docs with convergence probe failures and high duplicate/out-of-order ops.
2. Rebuild from last good snapshot plus ordered op log.
3. Deduplicate using `(doc_id, client_op_id)` and server revision.
4. Compare checksums/state vectors across replicas/clients.
5. Generate new snapshots and notify affected users if local edits need manual conflict resolution.

Recommendations:

1. Halt bad materialization.
2. Recompute features point-in-time from offline store for affected window.
3. Materialize online features after validation.
4. Compare distributions against training baseline and canary CTR.
5. Re-run recommendations or mark previous recommendations stale.

### Presence Must Not Starve Ops

Presence is disposable; document operations are durable user work. Presence updates at 1.4M/sec can fill queues and memory, delaying op sequencing and causing out-of-order application. Systems should prioritize/drop presence under load, throttle cursor frequency, and keep separate queues.

### LLM OOM Cascade

Increasing context 8k -> 32k roughly quadruples KV cache per request for those tenants. With shared queues and high `max_num_seqs`, the scheduler admits too many large-context requests, KV cache reaches 98%, requests swap, throughput drops 55%, queues grow, and OOM restarts reduce capacity further. Continuous batching helps utilization only within memory limits; it cannot overcome KV saturation.

### Feature Store Failure

The online store served 3.8h-stale seller features while the offline backfill was incomplete and point-in-time tests were skipped. The model received feature distributions 12 sigma from training baseline for `seller_popularity_7d`, so recommendations inside docs used old/popularity-skewed signals. This is training-serving skew plus freshness violation.

### Bad-Fix Gallery

| Bad fix | Failure mode |
|---------|--------------|
| Persist every cursor update | Turns ephemeral presence into durable write storm; worsens oplog/snapshot lag |
| Accept edits independently in every region | Forks document history unless CRDT protocol is designed for it |
| Double `max_num_seqs` | Admits more sequences into already saturated KV cache; more OOM/swap |
| Disable feature freshness alerts | Hides the user-impacting skew instead of fixing it |
| Flush prefix cache globally | Increases prefill cost and latency; does not address context/KV saturation |

### Capacity Answer

For the 20% canary traffic, a 4x context window can use roughly 4x KV cache per active sequence if prompts expand to the limit. Even if only a subset uses the full window, average KV pressure rises enough to reduce the number of concurrent sequences. Metrics confirming this: `vllm_gpu_cache_usage_perc` at 98%, `num_requests_swapped`, falling generation throughput, OOM restarts, and waiting queue growth.

### Org/Runbook Changes

- No overlapping collab gateway deploy, LLM context expansion, and feature-store backfill for enterprise launch windows.
- Collab runbook: drop presence first, protect op sequencer, reconnect jitter enforcement, convergence probes, doc repair from oplog.
- LLM runbook: context-window canary gates on KV usage, swapped requests, OOM, TTFT, tokens/sec, and tenant budget.
- Feature-store runbook: freshness pages, point-in-time tests required, backfill validation before online materialization, rollback to last-good feature view.
- Launch review names owners across collab, AI platform, feature store, and enterprise support.

---

## Scoring Guide - 85% Gate

| Area | Points |
|------|--------|
| Rapid-fire correctness | 32 |
| Contributing factor map | 16 |
| Collab safe-mode and repair | 14 |
| LLM KV/cache analysis | 14 |
| Feature-store skew analysis | 10 |
| Bad-fix analysis | 8 |
| Capacity reasoning | 3 |
| Org/runbook gates | 3 |

Pass gate: **85%+**. Critical misses: treating presence as durable document state, increasing LLM concurrency during KV saturation, or ignoring feature freshness/skew.
