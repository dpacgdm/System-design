# Week-08c Answers

Open only after attempting `Retention-Tests/Week-08c.md`.

## Part 1: Rapid-fire model answers

**A01 [W1 DNS]**
- Prompt focus: A Route 53 cutover completes, but Android clients keep sending checkout traffic to the old origin for 40 minutes. What cache/connection behaviors explain it?
- Model answer (A01): DNS/control-plane changes are advisory; client DNS caches, connection pools, JVM/mobile caches, and CDN/origin connections may keep old routes. Watch old endpoint request rate and drain connections.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A02 [W1 HTTP/2]**
- Prompt focus: A mobile app multiplexes all sync traffic over one long-lived connection through an L4 balancer. Why can one backend stay hot after scale-out?
- Model answer (A02): Classify operation safety, require stable idempotency, bound retries, revalidate stale decision data, expose conflicts, and account for client cache/flag TTL.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A03 [W2 Cache]**
- Prompt focus: A service-worker cache key omits tenant_id and auth viewer class for price preview. Which invariant is missing?
- Model answer (A03): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A04 [W2 SQL]**
- Prompt focus: A backfill updates 80M rows and checkout p99 rises while CPU is moderate. Name two non-CPU resources to inspect.
- Model answer (A04): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A05 [W3 Consistency]**
- Prompt focus: A client reads its queued cart edit as saved, then server sync rejects it. Which UI distinction should have existed?
- Model answer (A05): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A06 [W3 Clocks]**
- Prompt focus: Offline bids arrive after auction close with client timestamps before close. Which clock authority should decide?
- Model answer (A06): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A07 [W4 Replication]**
- Prompt focus: A migration verifies against an async replica lagging 90 seconds. Why can parity look falsely bad or falsely good?
- Model answer (A07): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A08 [W4 CDC]**
- Prompt focus: A new projection starts from latest after a snapshot but snapshot_end_lsn was not recorded. What failure appears?
- Model answer (A08): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A09 [W5 Pooling]**
- Prompt focus: Backfill opens many connections through PgBouncer and user traffic queues. Which reservation was missing?
- Model answer (A09): Treat the change as a migration state-machine: source of truth, compatibility, parity, offsets, backfill pressure, rollback edge, and contract timing must be explicit.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A10 [W5 Transactions]**
- Prompt focus: Dual-write commits primary but secondary times out. Which persisted key makes retry safe?
- Model answer (A10): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A11 [W6 Outbox]**
- Prompt focus: A checkout migration writes DB then emits a cutover event outside the transaction. What failure window returns?
- Model answer (A11): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A12 [W6 Retries]**
- Prompt focus: A mobile sync worker retries every second without jitter after a network drop. What cascade can follow?
- Model answer (A12): Classify operation safety, require stable idempotency, bound retries, revalidate stale decision data, expose conflicts, and account for client cache/flag TTL.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A13 [W7 Rate Limits]**
- Prompt focus: Payment authorize uses the same token cost as product browse. What abuse failure follows?
- Model answer (A13): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A14 [W7 Flags]**
- Prompt focus: A critical mobile flag has safe_default=true and 24h TTL. What rollback problem appears?
- Model answer (A14): DNS/control-plane changes are advisory; client DNS caches, connection pools, JVM/mobile caches, and CDN/origin connections may keep old routes. Watch old endpoint request rate and drain connections.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A15 [W8 SLO]**
- Prompt focus: Global checkout is green but enterprise EU sellers miss analytics orders during cutover. Which slice matters?
- Model answer (A15): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A16 [W8 Observability]**
- Prompt focus: A test dashboard shows latency only. Which correctness signal is missing for payment retry replay?
- Model answer (A16): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A17 [08b Auth]**
- Prompt focus: A replay test accepts a seller-admin token at checkout because signature is valid. Which validation was missing?
- Model answer (A17): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A18 [08b Tenancy]**
- Prompt focus: Support exports migration mismatches by order_id without tenant context. Which boundary is violated?
- Model answer (A18): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A19 [08b Cost]**
- Prompt focus: A reconciliation job scans raw S3 cross-region every minute during incident. What hidden cost/capacity issue appears?
- Model answer (A19): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A20 [08b Noisy Neighbor]**
- Prompt focus: One seller backfill consumes all shared worker threads. Which fairness control should exist?
- Model answer (A20): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A21 [08c Migration]**
- Prompt focus: In expand/contract, why does contract happen last?
- Model answer (A21): Treat the change as a migration state-machine: source of truth, compatibility, parity, offsets, backfill pressure, rollback edge, and contract timing must be explicit.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A22 [08c Migration]**
- Prompt focus: Dual-write mismatch rises only for promo orders. What should shadow-read comparison include besides row count?
- Model answer (A22): Treat the change as a migration state-machine: source of truth, compatibility, parity, offsets, backfill pressure, rollback edge, and contract timing must be explicit.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A23 [08c Migration]**
- Prompt focus: Why can rollback to old code be unsafe after new enum values are written?
- Model answer (A23): Treat the change as a migration state-machine: source of truth, compatibility, parity, offsets, backfill pressure, rollback edge, and contract timing must be explicit.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A24 [08c Migration]**
- Prompt focus: Name four preconditions before moving CDC projection authority.
- Model answer (A24): Treat the change as a migration state-machine: source of truth, compatibility, parity, offsets, backfill pressure, rollback edge, and contract timing must be explicit.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A25 [08c Migration]**
- Prompt focus: A DNS TTL was lowered at cutover time, not before. Why is that too late?
- Model answer (A25): DNS/control-plane changes are advisory; client DNS caches, connection pools, JVM/mobile caches, and CDN/origin connections may keep old routes. Watch old endpoint request rate and drain connections.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A26 [08c Testing]**
- Prompt focus: Why is deterministic simulation useful for retry timeout bugs?
- Model answer (A26): Name the test layer and invariant. Strong answers include reproducible seed or replay fence, contract semantics, correctness signals, abort criteria, and launch gate.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A27 [08c Testing]**
- Prompt focus: A chaos game-day has no hypothesis or abort criteria. What is wrong?
- Model answer (A27): Name the test layer and invariant. Strong answers include reproducible seed or replay fence, contract semantics, correctness signals, abort criteria, and launch gate.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A28 [08c Testing]**
- Prompt focus: Contract tests for OrderCreated add a new enum. What consumer behavior should be tested?
- Model answer (A28): Name the test layer and invariant. Strong answers include reproducible seed or replay fence, contract semantics, correctness signals, abort criteria, and launch gate.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A29 [08c Testing]**
- Prompt focus: Replay uses live email and PSP sinks. Which fence is missing?
- Model answer (A29): Name the test layer and invariant. Strong answers include reproducible seed or replay fence, contract semantics, correctness signals, abort criteria, and launch gate.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A30 [08c Testing]**
- Prompt focus: A canary improves p99 but duplicate external attempts rise. Which gate wins?
- Model answer (A30): Name the test layer and invariant. Strong answers include reproducible seed or replay fence, contract semantics, correctness signals, abort criteria, and launch gate.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A31 [08c Abuse]**
- Prompt focus: Credential stuffing has low per-IP rate but high account velocity. Why does IP-only limiting fail?
- Model answer (A31): Abuse defense combines auth validation, limiter hierarchy, risk/friction, cache safety, evidence preservation, and false-positive control. IP-only or global-only limits are insufficient.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A32 [08c Abuse]**
- Prompt focus: JWKS fetches spike for random kid values. Which cache behavior protects verifiers?
- Model answer (A32): Abuse defense combines auth validation, limiter hierarchy, risk/friction, cache safety, evidence preservation, and false-positive control. IP-only or global-only limits are insufficient.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A33 [08c Abuse]**
- Prompt focus: Card testing attempts are small-value and highly declined. Which dimensions should limiters include?
- Model answer (A33): Abuse defense combines auth validation, limiter hierarchy, risk/friction, cache safety, evidence preservation, and false-positive control. IP-only or global-only limits are insufficient.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A34 [08c Abuse]**
- Prompt focus: A CDN accepts arbitrary Vary headers into cache key. What abuse can result?
- Model answer (A34): Abuse defense combines auth validation, limiter hierarchy, risk/friction, cache safety, evidence preservation, and false-positive control. IP-only or global-only limits are insufficient.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A35 [08c Abuse]**
- Prompt focus: A valid seller token runs exports every second. Why is auth not sufficient?
- Model answer (A35): Abuse defense combines auth validation, limiter hierarchy, risk/friction, cache safety, evidence preservation, and false-positive control. IP-only or global-only limits are insufficient.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A36 [08c Client]**
- Prompt focus: Which operations can be stale for display but must revalidate before checkout?
- Model answer (A36): Classify operation safety, require stable idempotency, bound retries, revalidate stale decision data, expose conflicts, and account for client cache/flag TTL.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A37 [08c Client]**
- Prompt focus: A mobile app generates idempotency key per HTTP attempt. What duplicate risk appears?
- Model answer (A37): Classify operation safety, require stable idempotency, bound retries, revalidate stale decision data, expose conflicts, and account for client cache/flag TTL.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A38 [08c Client]**
- Prompt focus: How does QUIC connection migration help, and what does it not solve?
- Model answer (A38): Classify operation safety, require stable idempotency, bound retries, revalidate stale decision data, expose conflicts, and account for client cache/flag TTL.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A39 [08c Client]**
- Prompt focus: A seller inventory edit conflicts after offline sync. What UX must appear?
- Model answer (A39): Classify operation safety, require stable idempotency, bound retries, revalidate stale decision data, expose conflicts, and account for client cache/flag TTL.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A40 [08c Client]**
- Prompt focus: Push invalidation is delayed for some devices. Why must cache max-age still exist?
- Model answer (A40): Classify operation safety, require stable idempotency, bound retries, revalidate stale decision data, expose conflicts, and account for client cache/flag TTL.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A41 [08c Mix]**
- Prompt focus: For Migration rollback, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A41): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A42 [08c Mix]**
- Prompt focus: For Backfill capacity, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A42): Treat the change as a migration state-machine: source of truth, compatibility, parity, offsets, backfill pressure, rollback edge, and contract timing must be explicit.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A43 [08c Mix]**
- Prompt focus: For Shadow reads, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A43): Treat the change as a migration state-machine: source of truth, compatibility, parity, offsets, backfill pressure, rollback edge, and contract timing must be explicit.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A44 [08c Mix]**
- Prompt focus: For Feature flags, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A44): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A45 [08c Mix]**
- Prompt focus: For CDC offsets, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A45): Treat the change as a migration state-machine: source of truth, compatibility, parity, offsets, backfill pressure, rollback edge, and contract timing must be explicit.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A46 [08c Mix]**
- Prompt focus: For Simulation seeds, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A46): Name the test layer and invariant. Strong answers include reproducible seed or replay fence, contract semantics, correctness signals, abort criteria, and launch gate.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A47 [08c Mix]**
- Prompt focus: For Contract drift, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A47): Name the test layer and invariant. Strong answers include reproducible seed or replay fence, contract semantics, correctness signals, abort criteria, and launch gate.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A48 [08c Mix]**
- Prompt focus: For Replay privacy, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A48): Name the test layer and invariant. Strong answers include reproducible seed or replay fence, contract semantics, correctness signals, abort criteria, and launch gate.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A49 [08c Mix]**
- Prompt focus: For Game-day roles, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A49): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A50 [08c Mix]**
- Prompt focus: For Golden signals, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A50): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A51 [08c Mix]**
- Prompt focus: For Bot velocity, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A51): Abuse defense combines auth validation, limiter hierarchy, risk/friction, cache safety, evidence preservation, and false-positive control. IP-only or global-only limits are insufficient.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A52 [08c Mix]**
- Prompt focus: For Risk timeout, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A52): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A53 [08c Mix]**
- Prompt focus: For Cache poisoning, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A53): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A54 [08c Mix]**
- Prompt focus: For Collusion graph, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A54): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A55 [08c Mix]**
- Prompt focus: For False positives, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A55): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A56 [08c Mix]**
- Prompt focus: For Offline queue, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A56): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A57 [08c Mix]**
- Prompt focus: For Conflict merge, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A57): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A58 [08c Mix]**
- Prompt focus: For SWR cache, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A58): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A59 [08c Mix]**
- Prompt focus: For Reconnect storm, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A59): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A60 [08c Mix]**
- Prompt focus: For Mobile telemetry, name the mechanism, the protected invariant, one metric, and one bad fix to reject.
- Model answer (A60): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A61 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Migration rollback. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A61): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A62 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Backfill capacity. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A62): Treat the change as a migration state-machine: source of truth, compatibility, parity, offsets, backfill pressure, rollback edge, and contract timing must be explicit.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A63 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Shadow reads. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A63): Treat the change as a migration state-machine: source of truth, compatibility, parity, offsets, backfill pressure, rollback edge, and contract timing must be explicit.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A64 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Feature flags. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A64): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A65 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving CDC offsets. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A65): Treat the change as a migration state-machine: source of truth, compatibility, parity, offsets, backfill pressure, rollback edge, and contract timing must be explicit.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A66 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Simulation seeds. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A66): Name the test layer and invariant. Strong answers include reproducible seed or replay fence, contract semantics, correctness signals, abort criteria, and launch gate.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A67 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Contract drift. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A67): Name the test layer and invariant. Strong answers include reproducible seed or replay fence, contract semantics, correctness signals, abort criteria, and launch gate.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A68 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Replay privacy. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A68): Name the test layer and invariant. Strong answers include reproducible seed or replay fence, contract semantics, correctness signals, abort criteria, and launch gate.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A69 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Game-day roles. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A69): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A70 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Golden signals. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A70): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A71 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Bot velocity. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A71): Abuse defense combines auth validation, limiter hierarchy, risk/friction, cache safety, evidence preservation, and false-positive control. IP-only or global-only limits are insufficient.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A72 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Risk timeout. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A72): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A73 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Cache poisoning. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A73): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A74 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Collusion graph. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A74): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A75 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving False positives. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A75): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A76 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Offline queue. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A76): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A77 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Conflict merge. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A77): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A78 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving SWR cache. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A78): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A79 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Reconnect storm. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A79): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A80 [08c Mix]**
- Prompt focus: Northstar sees a P1 involving Mobile telemetry. What is your first slice query and what mitigation would you avoid until evidence improves?
- Model answer (A80): State the mechanism, evidence signal, protected invariant, immediate mitigation, and one bad fix. Slice by tenant, region, cell, client version, and route.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

## Rapid-fire calibration notes for Week 08c

Use these notes to grade terse answers. The rapid-fire section
is intentionally compact, but a passing answer still needs a
mechanism, an invariant, a signal, and a rejected bad fix.

### Migration prompts

- Expand/contract answers should say "contract last" because
  old readers, old writers, caches, jobs, partners, rollback
  binaries, and replay tools may still need the old shape.
- Shadow-read answers should compare semantic hashes, not just
  row counts: tenant, order id, sku, quantity, money fields,
  enum state, and promo/feature context.
- Rollback answers must ask whether old code can parse new
  enum/data values. If not, freeze expansion and route
  narrowly instead of global rollback.
- CDC answers must name `snapshot_end_lsn` or equivalent
  offset fence. "Start from latest" after snapshot is a gap.
- DNS/cutover answers should remember clients, recursive
  resolvers, connection pools, JVM/mobile caches, and old
  endpoints outlive control-plane changes.

### Testing prompts

- Simulation answers should identify the minimal state space:
  accepted externally, timed out locally, retried with same or
  new operation id, and observed by replay.
- Chaos/game-day answers need a hypothesis, scope, owners,
  abort criteria, and post-game acceptance threshold.
- Contract drift answers should include semantic compatibility
  for enum values, auth claims, cache headers, mobile payloads,
  and event consumers, not only JSON shape.
- Replay privacy answers must fence PSP/email/customer sinks
  and redact tokens/PII. A replay that can send live side
  effects is not a test.
- Correctness gates beat latency gates for payment,
  inventory, identity, and customer-visible state.

### Abuse prompts

- IP-only limits fail against distributed bots, NATs, device
  farms, account churn, and card-testing campaigns. Good
  answers include card/device/account/ASN/tenant dimensions.
- Risk timeout policy is class-based: payment and admin paths
  step up or hold; low-risk catalog reads may degrade.
- Cache abuse answers should distinguish key explosion from
  personalization leaks and should fix headers before purging.
- Fraud evidence must preserve fingerprints, decisions,
  scores, provider ids, and cache keys without raw PAN, CVV,
  bearer tokens, cookies, or full JWTs.
- False positives are production impact; mitigation should
  preserve flash-sale browsing while protecting PSP capacity.

### Client and edge prompts

- Offline queueing stores user intent, not arbitrary HTTP
  attempts. Checkout submit and payment authorize are not
  blindly queueable.
- Idempotency keys must survive retries, app restarts,
  transport migration, and offline drain. Per-attempt keys are
  duplicate generators.
- QUIC connection migration helps transport continuity; it
  does not solve app-level operation identity.
- Stale catalog data may be displayable with labels; stale
  price, inventory, risk, or eligibility must revalidate
  before checkout.
- Critical mobile flags need safe default false, short TTL,
  server override, app-version gates, and stale-flag telemetry.

### Mixed incident grading

For A41-A80, require the learner to identify the first slice
query before mitigation. Strong slice examples include:

- migration: tenant/cell/client version/promo route and shadow
  disagreement field;
- backfill: WAL retained bytes, replica lag, pool waiters, and
  chunk ownership;
- testing: replay diff by app version, route, operation-id
  source, and side-effect sink;
- abuse: card/device/account/ASN velocity and PSP decline mix;
- client: app version, network transition, queue age,
  duplicate PSP attempt, and stale flag age.

Bad fixes to reject across the week:

- global rollback when old code cannot read new state;
- doubling backfill while WAL/lag grows;
- launching because p99 improved while correctness regressed;
- blocking all anonymous browsing for scoped card testing;
- default-allow risk timeout on payment authorize;
- accepting client price or inventory state for checkout;
- deleting local queues or replay artifacts before repair;
- repairing from analytics/search/cache instead of source of
  truth.

## Part 2: Compound Ops Sim model response

- Do not collapse all symptoms into one root cause. There
  are at least four layers: unsafe order-shape cutover/CDC
  lag, mobile offline idempotency, card-testing abuse, and
  CDN cache poisoning/personalization risk.
- First 15 minutes: declare P1, assign incident command
  plus checkout, mobile, payments/fraud, CDN, data
  platform, support, and security leads; freeze further
  migration and mobile rollout; disable offline checkout
  submit through server-side gate; force stale
  price/inventory revalidation; weight/limit payment
  authorize by card/device/account/ASN; disable public
  cache for price-preview and purge scoped variants;
  throttle backfill on WAL/lag.
- Reject A because idempotency is the safety mechanism
  even if ledger duplicates are zero. PSP duplicate
  attempts are already harm. Reject B because old binary
  may not read new enum/data shape. Reject C because
  global anonymous block damages sale traffic when scoped
  bot/payment controls exist. Reject D because WAL is
  already growing 48GB/10m and CDC lag is 84s. Reject E
  because client price is display state, not authority for
  checkout.
- Capacity/blast radius: 0.73% enterprise EU mismatch
  during sale can be thousands of orders per hour
  depending on order rate; 188 duplicate PSP attempts is
  nonzero external risk; stale flag on 58% affected
  clients means backend rollback alone will not stop the
  path; 6.4M cache keys and Set-Cookie hits prove cache
  containment is urgent.
- Customer/support: separate buyer pending/duplicate
  authorization notifications from seller analytics
  freshness. Do not claim duplicate charges if ledger has
  zero duplicate business effects; say payment
  authorizations are being reconciled and affected
  buyers/sellers are scoped by app version, EU enterprise
  tenant, and payment attempt fingerprints.
- Durable gates: migration requires snapshot_end_lsn and
  parity threshold by tenant; mobile requires stable
  client_operation_id and stale checkout block; retry
  library requires replay duplicate external attempts = 0;
  CDN price-preview must be private/no-store or correctly
  keyed; abuse limiter must weight payment authorize and
  include card/device/account/ASN dimensions.
