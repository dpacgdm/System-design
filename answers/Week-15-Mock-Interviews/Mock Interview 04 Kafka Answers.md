# Answer Key - Mock Interview 04 Kafka

> Open only after attempting the learner file questions.

## Expert Answer — Full 45-Minute Narrative

```
MINUTE 0–5 — REQUIREMENTS

  "Before I draw anything, I want to confirm scope.

   Functional P0: append-only durable log, produce/consume APIs,
   per-key ordering, independent consumer groups for fan-out, replay
   within retention, multi-tenant ACLs and quotas.

   Non-functional: 10M events/sec peak (~10 GB/s), p99 produce < 10ms,
   99.99% availability, no data loss on single broker failure,
   7-day default retention with optional 90-day archive.

   I'll assume at-least-once delivery with idempotent consumers as
   the default; exactly-once within Kafka via transactions where
   teams explicitly need it.

   Design driver: partition count and key design — they set the
   throughput ceiling AND the ordering contract. Does that match?"

MINUTE 5–12 — CAPACITY

  "10M events/sec × 1 KB = 10 GB/s ingress. With zstd compression
   at batch level, ~3.3 GB/s on disk.

   Partitions: ~10 MB/s per partition sustained → 1,000 minimum,
   ×3 for skew and growth → 4,096 partitions on shared high-volume topics.

   Storage: 864 TB/day raw. Seven days compressed hot ≈ 2 PB,
   ×RF=3 ≈ 6 PB cluster — tiered storage to S3 is mandatory, not optional.

   Five consumer groups reading full stream → ~16 GB/s egress.
   I'd consider a separate offline cluster for analytics fan-out."

MINUTE 12–18 — API & DATA MODEL

  "Topic naming: domain.entity.event.version. Partition key documented
   per topic — order_id for commerce, null for click analytics.

   Schema registry with backward-compatible Avro. Admin API for tenant
   quotas. DLQ topic suffix .dlt for poison messages.

   Offsets in __consumer_offsets; replay via new consumer group or
   timestamp seek — guarded admin API for reset."

MINUTE 18–28 — ARCHITECTURE

  [Draw diagram from Architecture section]

  "KRaft for metadata — no ZooKeeper dependency. Brokers rack-aware
   across 3 AZs. RF=3, min.insync.replicas=2, acks=all.

   Producers use idempotent producer by default. Quotas enforced at
   broker per tenant principal. Tiered storage: NVMe hot, S3 cold.

   New consumer group for replay; beyond 7 days, bootstrap from
   S3 archive into temporary replay topic."

MINUTE 28–40 — DEEP DIVE

  "Deploy rebalance storm: eager protocol stops the world on every pod
   restart. Fix: CooperativeStickyAssignor, group.instance.id for
   static membership, session.timeout tuned to K8s preStop.

   Hot partition: bad key like country_code. Fix with composite key
   or dedicated topic for whale tenant. Monitor per-partition lag.

   ISR shrink: slow follower → ISR={leader} → min.isr=2 blocks writes.
   Fix broker disk; never enable unclean leader election in prod.

   Exactly-once to Postgres: Kafka transactions don't cross the boundary.
   Idempotent consumer with UNIQUE(event_id). Outbox pattern if they
   need atomic DB write + publish.

   90-day replay: tiered storage + S3 archive; replay service loads
   into temp topic with rate limits."

MINUTE 40–45 — FAILURE MODES & CLOSE

  "Four things break first: rebalance storm on deploy, hot partition
   from bad keys, ISR shrink blocking producers, poison message stalling
   one partition. Detection: per-partition lag, IsrShrinks, rebalance
   rate, DLT growth.

   V1: shared cluster, quotas, tiered storage, cooperative rebalance,
   schema registry, DLQ pattern. V2: cross-region MirrorMaker, Flink
   platform, self-serve topic provisioning UI."
```

---
