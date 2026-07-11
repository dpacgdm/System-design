# Week-08c Retention Test

Questions only. Attempt without opening answers. This is a spaced mix of Weeks 1-8, Week 08b trust/cost/tenancy, and Week 08c operations hardening. For every incident question, name the layer, invariant, metric, and one bad fix.

## Rules

```text
1. Answer from memory; do not open modules or answer keys.
2. Rapid-fire answers should name mechanism, evidence, invariant, and one bad fix.
3. The compound Ops Sim should be answered like you are incident lead.
4. If unsure, write the safest invariant-preserving action and move on.
5. Open the answer key only after completing your attempt.
```

## Part 1: Rapid-fire spaced review (80 questions)

The mix is intentional: new Week 08c topics, recent trust/cost/tenancy, and older foundations.

**Q01 [W1 DNS]**
A Route 53 cutover completes, but Android clients keep sending checkout traffic to the old origin for 40 minutes. What cache/connection behaviors explain it?

**Q02 [W1 HTTP/2]**
A mobile app multiplexes all sync traffic over one long-lived connection through an L4 balancer. Why can one backend stay hot after scale-out?

**Q03 [W2 Cache]**
A service-worker cache key omits tenant_id and auth viewer class for price preview. Which invariant is missing?

**Q04 [W2 SQL]**
A backfill updates 80M rows and checkout p99 rises while CPU is moderate. Name two non-CPU resources to inspect.

**Q05 [W3 Consistency]**
A client reads its queued cart edit as saved, then server sync rejects it. Which UI distinction should have existed?

**Q06 [W3 Clocks]**
Offline bids arrive after auction close with client timestamps before close. Which clock authority should decide?

**Q07 [W4 Replication]**
A migration verifies against an async replica lagging 90 seconds. Why can parity look falsely bad or falsely good?

**Q08 [W4 CDC]**
A new projection starts from latest after a snapshot but snapshot_end_lsn was not recorded. What failure appears?

**Q09 [W5 Pooling]**
Backfill opens many connections through PgBouncer and user traffic queues. Which reservation was missing?

**Q10 [W5 Transactions]**
Dual-write commits primary but secondary times out. Which persisted key makes retry safe?

**Q11 [W6 Outbox]**
A checkout migration writes DB then emits a cutover event outside the transaction. What failure window returns?

**Q12 [W6 Retries]**
A mobile sync worker retries every second without jitter after a network drop. What cascade can follow?

**Q13 [W7 Rate Limits]**
Payment authorize uses the same token cost as product browse. What abuse failure follows?

**Q14 [W7 Flags]**
A critical mobile flag has safe_default=true and 24h TTL. What rollback problem appears?

**Q15 [W8 SLO]**
Global checkout is green but enterprise EU sellers miss analytics orders during cutover. Which slice matters?

**Q16 [W8 Observability]**
A test dashboard shows latency only. Which correctness signal is missing for payment retry replay?

**Q17 [08b Auth]**
A replay test accepts a seller-admin token at checkout because signature is valid. Which validation was missing?

**Q18 [08b Tenancy]**
Support exports migration mismatches by order_id without tenant context. Which boundary is violated?

**Q19 [08b Cost]**
A reconciliation job scans raw S3 cross-region every minute during incident. What hidden cost/capacity issue appears?

**Q20 [08b Noisy Neighbor]**
One seller backfill consumes all shared worker threads. Which fairness control should exist?

**Q21 [08c Migration]**
In expand/contract, why does contract happen last?

**Q22 [08c Migration]**
Dual-write mismatch rises only for promo orders. What should shadow-read comparison include besides row count?

**Q23 [08c Migration]**
Why can rollback to old code be unsafe after new enum values are written?

**Q24 [08c Migration]**
Name four preconditions before moving CDC projection authority.

**Q25 [08c Migration]**
A DNS TTL was lowered at cutover time, not before. Why is that too late?

**Q26 [08c Testing]**
Why is deterministic simulation useful for retry timeout bugs?

**Q27 [08c Testing]**
A chaos game-day has no hypothesis or abort criteria. What is wrong?

**Q28 [08c Testing]**
Contract tests for OrderCreated add a new enum. What consumer behavior should be tested?

**Q29 [08c Testing]**
Replay uses live email and PSP sinks. Which fence is missing?

**Q30 [08c Testing]**
A canary improves p99 but duplicate external attempts rise. Which gate wins?

**Q31 [08c Abuse]**
Credential stuffing has low per-IP rate but high account velocity. Why does IP-only limiting fail?

**Q32 [08c Abuse]**
JWKS fetches spike for random kid values. Which cache behavior protects verifiers?

**Q33 [08c Abuse]**
Card testing attempts are small-value and highly declined. Which dimensions should limiters include?

**Q34 [08c Abuse]**
A CDN accepts arbitrary Vary headers into cache key. What abuse can result?

**Q35 [08c Abuse]**
A valid seller token runs exports every second. Why is auth not sufficient?

**Q36 [08c Client]**
Which operations can be stale for display but must revalidate before checkout?

**Q37 [08c Client]**
A mobile app generates idempotency key per HTTP attempt. What duplicate risk appears?

**Q38 [08c Client]**
How does QUIC connection migration help, and what does it not solve?

**Q39 [08c Client]**
A seller inventory edit conflicts after offline sync. What UX must appear?

**Q40 [08c Client]**
Push invalidation is delayed for some devices. Why must cache max-age still exist?

**Q41 [08c Mix]**
For Migration rollback, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q42 [08c Mix]**
For Backfill capacity, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q43 [08c Mix]**
For Shadow reads, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q44 [08c Mix]**
For Feature flags, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q45 [08c Mix]**
For CDC offsets, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q46 [08c Mix]**
For Simulation seeds, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q47 [08c Mix]**
For Contract drift, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q48 [08c Mix]**
For Replay privacy, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q49 [08c Mix]**
For Game-day roles, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q50 [08c Mix]**
For Golden signals, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q51 [08c Mix]**
For Bot velocity, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q52 [08c Mix]**
For Risk timeout, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q53 [08c Mix]**
For Cache poisoning, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q54 [08c Mix]**
For Collusion graph, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q55 [08c Mix]**
For False positives, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q56 [08c Mix]**
For Offline queue, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q57 [08c Mix]**
For Conflict merge, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q58 [08c Mix]**
For SWR cache, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q59 [08c Mix]**
For Reconnect storm, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q60 [08c Mix]**
For Mobile telemetry, name the mechanism, the protected invariant, one metric, and one bad fix to reject.

**Q61 [08c Mix]**
Northstar sees a P1 involving Migration rollback. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q62 [08c Mix]**
Northstar sees a P1 involving Backfill capacity. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q63 [08c Mix]**
Northstar sees a P1 involving Shadow reads. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q64 [08c Mix]**
Northstar sees a P1 involving Feature flags. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q65 [08c Mix]**
Northstar sees a P1 involving CDC offsets. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q66 [08c Mix]**
Northstar sees a P1 involving Simulation seeds. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q67 [08c Mix]**
Northstar sees a P1 involving Contract drift. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q68 [08c Mix]**
Northstar sees a P1 involving Replay privacy. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q69 [08c Mix]**
Northstar sees a P1 involving Game-day roles. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q70 [08c Mix]**
Northstar sees a P1 involving Golden signals. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q71 [08c Mix]**
Northstar sees a P1 involving Bot velocity. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q72 [08c Mix]**
Northstar sees a P1 involving Risk timeout. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q73 [08c Mix]**
Northstar sees a P1 involving Cache poisoning. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q74 [08c Mix]**
Northstar sees a P1 involving Collusion graph. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q75 [08c Mix]**
Northstar sees a P1 involving False positives. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q76 [08c Mix]**
Northstar sees a P1 involving Offline queue. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q77 [08c Mix]**
Northstar sees a P1 involving Conflict merge. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q78 [08c Mix]**
Northstar sees a P1 involving SWR cache. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q79 [08c Mix]**
Northstar sees a P1 involving Reconnect storm. What is your first slice query and what mitigation would you avoid until evidence improves?

**Q80 [08c Mix]**
Northstar sees a P1 involving Mobile telemetry. What is your first slice query and what mitigation would you avoid until evidence improves?

## Part 2: Compound Ops Sim - Northstar Cutover Meets Abuse and Mobile Offline

Use the shared Northstar Commerce context. Answer as incident lead; include layer, invariant, metric, rejected bad fix, and one capacity/blast-radius check for every major claim.

```text
INCIDENT REPORT

Severity: P1
Time: T+0 is 11:05 UTC during a flash-sale preview.

User impact:
  - Android buyers on app 2026.07.11 report pending orders that later
    show duplicate payment authorization notifications.
  - Enterprise EU sellers report missing line items in analytics.
  - PSP decline rate for small payments is nine times normal.

Recent changes:
  - order_line_items normalized table cut over for 15% of EU tenants.
  - mobile offline queue enabled for Android 2026.07.11.
  - payment retry library canary at 10%.
  - CDN rule for seller price-preview changed to public cache for sale.

Telemetry:
  checkout_success_rate_global: 99.91%
  enterprise_eu_order_line_mismatch: 0.73%
  duplicate_psp_authorize_attempt_total: 188
  duplicate_business_effect_total{ledger}: 0
  psp_decline_rate{amount_bucket=small}: 36%
  payment_attempts_per_card_hash_p95: 52/10m
  mobile_flag_version{offline_checkout_enabled}: stale on 58% affected clients
  cdc_projection_lag_seconds{orders_v2}: 84
  wal_retained_gb{slot=orders_v2}: +48GB/10m
  cache_key_cardinality{price-preview}: 6.4M
  cache_hit_served_with_set_cookie_total: 11

Bad fixes proposed in chat:
  A. Disable idempotency because ledger duplicates are zero.
  B. Roll back all checkout-api pods to the old binary immediately.
  C. Block all anonymous catalog traffic globally.
  D. Double backfill concurrency so analytics catches up.
  E. Trust client price because the sale banner is time limited.
```

Answer prompts:

- Root-cause layers and evidence by symptom.
- First 15-minute mitigation sequence and what to freeze.
- Bad fixes to reject with reasons.
- Capacity/blast-radius arithmetic from the prompt.
- Customer/support communication slices.
- Durable tests and launch gates before relaunch.
