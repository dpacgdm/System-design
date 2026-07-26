# Answer Key - Design Ad Platform

> Open only after attempting the learner file questions.

A strong answer treats ads as three coupled systems: a low-latency serving path, a policy and campaign control plane, and an auditable event-to-billing pipeline.
It also names what is deliberately not optimized during an incident: do not trade privacy, billing correctness, or advertiser isolation for short-term revenue.

## Principal Model Answer - What Excellent Looks Like

1. Draws serving cells separately from campaign management and billing reconciliation.
2. Keeps campaign, creative, budget ledger, and policy status as authoritative control-plane records.
3. Uses precomputed regional serving indexes instead of joining campaigns, users, catalog, and budgets on every request.
4. Orders request-path logic as context, retrieval, policy, budget, pacing, cap, ranking, auction, response, and logging.
5. Explains first-price and second-price intuition with quality score and reserve price implications.
6. Uses budget leases and spend shadows for latency, but reconciles final spend through an immutable ledger.
7. Implements frequency caps with bounded windows, sharded keys, privacy-safe identifiers, and conservative timeout behavior.
8. Treats impression, click, and conversion events as at-least-once and dedupes all money-impacting events.
9. Separates estimated reporting from finalized billing and preserves raw evidence for fraud review.
10. Controls tenants by API quotas, report export budgets, serving fair share, and scoped kill switches.
11. Can calculate peak QPS, candidate scoring cost, logging volume, outstanding lease exposure, and hot-key risk.
12. During incidents, narrows blast radius to campaign, tenant, placement, region, or model version before global toggles.

## Ops Sim Model Answer - Northstar Sponsored Ads Overpacing

### Root cause chain

1. The primary symptom is ad serving and pacing, not checkout or billing ledger failure.
2. Campaign `camp-9842` is overpacing because outstanding regional budget leases are far above the intended guardrail.
3. The cap service is timing out on a hot campaign/user cap family and the config fails open with `cap_service_on_timeout: allow`.
4. Fail-open caps explain repeated exposure to the same creative and the very low cap hit rate.
5. EU no-fill and stale out-of-stock creative are amplified by `campaign_changed` materializer lag, especially partition 17.
6. Ranker feature timeouts contribute to p99 but do not explain overspend by themselves.
7. Raw impression lag is important for reconciliation but is not the first customer pain if serving is still producing bad decisions.
8. Fraud score is a red herring because entropy and conversion quality look normal; the pattern is organic event load plus bad guardrails.

### First 15 minutes

1. Declare incident ownership with ads serving as primary and notify finance, advertiser support, marketplace/search lead, and incident command.
2. Freeze or disable `camp-9842` or the advertiser tenant in the affected placements if spend exposure is above the preauthorized threshold.
3. Change cap timeout behavior for affected campaign or placement to fail closed or conservative stale, not fail open.
4. Reduce `budget_lease_max_usd_per_campaign_region` for the tenant and stop issuing new large leases until reconciliation catches up.
5. Scope mitigation to campaign, advertiser, category, and region before disabling all sponsored ads.
6. Apply contextual/simple ranking fallback or lower deep-rank candidates to reduce p99 while preserving policy and budget checks.
7. Pause the tenant bulk update or cap materializer partition causing lag; do not globally restart all materializers during peak.
8. Hide or suppress out-of-stock creative by product/category policy override while inventory cache catches up.
9. Start a billing-protection marker so events in the incident window are reviewed before final invoicing.
10. Do not replay impression backlog or drain DLQ aggressively until serving p99, cap hot keys, and budget leases are stable.

### Capacity and exposure calculation

- Peak ad decision QPS is 78k, close to the module's expected 83k Black Friday target.
- Outstanding lease exposure is $14,800 for one campaign where expected exposure is <= $2,000.
- If spend slope continues at 6.8x target for 15 minutes, overspend grows faster than ledger reconciliation can correct serving decisions.
- Smallest blast-radius boundary is campaign `camp-9842` and advertiser `adv-luma-market`, then placement/category/region if materializer lag affects adjacent campaigns.
- The budget guard should cap combined leases to the advertiser's allowed overspend, for example 1 percent of budget or a contract-specific dollar ceiling.
- Cap service p99 of 41 ms consumes one third of the 120 ms budget, and ranker at 64 ms pushes end-to-end p99 above target.
- Scaling Redis alone may reduce p99 but leaves fail-open cap semantics and large leases in place, so it does not stop overspend.
- Adding Kafka consumers may help materializer lag, but unbounded consumers can hurt shared brokers and does not fix cap fallback or budget sizing.

### Bad fixes to reject

- Global ads disable: safe only as last resort; it creates revenue loss, support noise, and can hide whether one tenant or campaign caused the blast radius.
- Failing caps open during Redis latency: repeats the exact user-trust problem and allows overdelivery.
- Increasing budget leases for latency: improves request path briefly but increases financial exposure during failover or lag.
- Replaying all impression events immediately: can double count or overload attribution while the source of bad serving continues.
- Bypassing consent or policy to keep fill rate high: unacceptable even during P1 revenue incidents.
- Editing DB rows manually: bypasses campaign changelog, audit, materializers, and serving version fences.

### Durable prevention

- Make cap timeout behavior configurable by risk level with default conservative rejection for repeated creative exposure.
- Limit outstanding budget leases by campaign, region, and advertiser contract; prove region failure cannot exceed allowed overspend.
- Shard cap state by campaign and user bucket; pre-split event campaigns and sale categories.
- Create a materializer SLO for critical campaign status and budget changes; reject stale serving indexes for pause/block/budget updates.
- Add tenant bulk-update concurrency limits and backpressure so advertiser UI cannot starve serving materializers.
- Record incident-window events with a billing hold marker and reconcile with raw evidence, dedupe keys, and fraud review.
- Add game day: hot campaign, cap shard latency, materializer lag, feature store timeout, and budget lease failover in one regional cell.
- Acceptance criteria: no paused/blocked creative serves after status version reaches cell; cap timeout does not increase repeated exposure; overspend bounded by configured lease ceiling.

## Design Gates - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principals include shoppers, anonymous devices, advertisers, seller-advertisers, creative reviewers, support/admin users, serving services, materializers, collectors, stream processors, and billing workers.
2. The first untrusted request enters at API gateway for users and advertisers; external event pixels enter at collectors with signed tokens and rate limits.
3. Campaign API authorizes campaign writes; ad serving authorizes eligible user/context use; billing ledger authorizes charge creation; support tools authorize break-glass actions.
4. Identity artifacts include user session, advertiser OAuth/API token, mTLS workload identity, signed click/impression token, and job identity with original actor context.
5. Consent, policy, campaign pause, budget charge, and admin actions fail closed when authoritative policy is unavailable.
6. Contextual no-ad fallback is allowed; personalized targeting is not allowed without consent proof.
7. Support exports require tenant scope, purpose, approval for sensitive data, and immutable audit logs.
8. Cached creative payloads do not override creative review, advertiser block, product inventory, or campaign status.
9. Cross-region serving preserves identity, consent, and budget fences; failover never mints unlimited spend leases.
10. A good diagram puts trust boundaries before caches and queues.

### Gate 2 - Abuse and misuse

1. Highest amplification actors are large advertisers, hot campaigns, bot click clusters, and bulk update jobs that invalidate serving indexes.
2. Abusable endpoints include ad refresh, click tracking, conversion ingestion, creative upload, campaign bulk edit, report export, and attribution replay.
3. Quota keys include user/device, IP/ASN, advertiser, campaign, creative, placement, region, model version, report export bytes, and global event collector ingress.
4. Organic sale spikes show diverse users and healthy conversion quality; abuse shows low entropy, repeated timing, mismatched conversions, or tenant/API anomalies.
5. Retries from clients, collectors, materializers, and billing replays need jitter, idempotency, and bounded budgets.
6. Fraud decisions should mark events non-billable without deleting raw evidence.
7. Risk controls must not share unlimited capacity with serving or checkout.
8. Kill switches exist by advertiser, campaign, creative, placement, region, candidate source, and model version.
9. A weak answer says rate limit clicks; a strong answer names dimensions and downstream billing effects.
10. Abuse telemetry must support forensics and advertiser dispute workflows.

### Gate 3 - Multi-tenant isolation

1. Advertiser_id is the tenant root, but seller_id, billing_account_id, region, and agency/subaccount also matter.
2. Tenant context appears in campaign DB rows, serving indexes, cache keys, Kafka headers, stream state, report paths, support tools, and ledger entries.
3. Shared resources get fair share: serving CPU, candidate index rebuilds, cap state, budget leases, report exports, creative review, and API write concurrency.
4. One tenant can be paused, spend-capped, moved to a dedicated materializer lane, report-throttled, or isolated to a dedicated index shard.
5. Exports run from snapshots and object storage with byte quotas, not from live serving stores.
6. Missing tenant context is a policy error, not a global default.
7. Backfills and replays are tenant-scoped and budgeted by bytes and ledger impact.
8. Support tools filter server-side and log exact tenant scope.
9. Isolation test: advertiser A cannot see advertiser B campaign metrics through dashboard, export, cache, logs, or support replay.
10. Large tenants can receive dedicated cells without changing the public API contract.

### Gate 4 - Unit cost at target scale

1. Business units are ad request, slot decision, billable impression, click, conversion, and report row.
2. At 720M opportunities/day and 83k peak QPS, serving CPU and memory dominate the online path.
3. Candidate scoring cost is controlled by staged retrieval; scoring 400 candidates deeply per request is too expensive.
4. Logging and stream processing dominate the offline path because every impression and decision emits durable events.
5. Billing ledger writes are lower volume but higher correctness cost.
6. Track cost per thousand ad requests, per thousand billable impressions, per tenant, per placement, and per model version.
7. Cost alerts should fire on deep-rank candidate count, feature-store timeout fallback, event bytes/sec, and report export bytes.
8. Graceful cost reduction: fewer deep-rank candidates, disable experimental models, contextual fallback, lower debug sampling, defer reports, not weaker policy or billing.
9. Include replica overhead, checkpoint storage, observability cardinality, idle headroom, and replay capacity.
10. A defensible answer can estimate vCPU from QPS times candidates times score cost.

### Gate 5 - Failure blast radius

1. Smallest intended boundaries are campaign, advertiser, creative, placement, category, region/cell, stream partition, model version, and budget lease group.
2. Critical dependencies shared with optional paths include Kafka brokers, Redis clusters, feature stores, materializer workers, and support/reporting databases.
3. Fail closed: personalized targeting without consent, blocked creative, paused campaign, budget exhausted, unsigned click token, ledger writes.
4. Serve stale: dashboard estimates, low-risk candidate indexes, contextual ads, cached creative asset if status is still valid.
5. Disable first: experimental ranker, long-tail candidate source, debug payloads, report exports, one campaign/tenant/placement.
6. Runbook hazards: global cache flush, manual DB edits, unbounded replay, increasing leases, bypassing policy, and resharding during peak.
7. Bulkheads separate serving, event collection, attribution, reporting, creative review, and advertiser UI.
8. Game day should combine hot campaign, cap shard latency, budget failover, materializer lag, and report export pressure.
9. Alerts need leading indicators: budget lease outstanding, cap timeout mode, materializer lag by tenant, and spend curve deviation.
10. A good answer states what remains working: organic search/feed, checkout, unaffected advertisers, and contextual or no-ad fallback.

## Scenario Variants for Self-Review

Use these variants to check transfer, not memorization.

### Variant A - Underpacing with healthy latency

1. Global serving p99 is normal, but one tenant spends only 35 percent of its expected curve by noon.
2. Candidate retrieval returns almost no candidates for the tenant after a category taxonomy deploy.
3. Correct first move is to inspect targeting reach, index version, and policy filters, not to raise bids blindly.
4. Durable fix is taxonomy compatibility tests and canary campaigns per category.

### Variant B - Billing duplicate with healthy serving

1. Advertisers see spend double for a 20-minute window while ad p99 and impressions are normal.
2. Collector retried click events after timeout and billing sink lacked idempotent upsert on click token.
3. Correct first move is to place invoice hold and stop duplicate sink writes, not disable serving globally.
4. Durable fix is ledger idempotency, replay test, and duplicate-rate alert tied to billing finalization.

### Variant C - Privacy fallback revenue drop

1. EU personalized eligible rate falls from 72 percent to 3 percent after consent service deploy.
2. Revenue drops but policy behavior is safe because serving forced contextual-only.
3. Correct first move is to confirm no personalized targeting bypass and then debug consent propagation.
4. Durable fix is consent canary, jurisdiction-scoped rollback, and contextual capacity headroom.

### Variant D - Advertiser noisy neighbor

1. One agency uploads 1.2M campaign edits and invalidates shared indexes.
2. Serving materializers lag for unrelated advertisers in the same category.
3. Correct first move is to throttle that tenant bulk job and move it to a dedicated lane.
4. Durable fix is tenant write budgets, bulk job admission control, and index rebuild quotas.

### Variant E - Fraud spike during organic event

1. Click rate triples but conversion quality remains normal and user entropy is high.
2. The wrong fix is to globally block the campaign as fraud without conversion and identity evidence.
3. Correct response is to compare entropy, timing, device clusters, and conversion quality, then mark uncertain events for review.
4. Durable fix is fraud decision transparency and billing hold workflow for uncertain windows.

## Minimum Whiteboard Capacity Answer

1. Daily opportunities: 12M DAU * 60 = 720M.
2. Average QPS: 720M / 86,400 = about 8.3k.
3. Peak QPS at 10x = about 83k.
4. Slot decisions at 2.2 slots/request = about 183k/sec.
5. Deep rank operations at 80 candidates/request = about 6.6M candidate scores/sec.
6. At 50 microseconds per score = about 332 vCPU before overhead and headroom.
7. With 2x overhead/headroom and regional replication, expect hundreds of vCPU, not a single service box.
8. Impression events at 183k/sec and 0.5 KB each produce about 91 MB/sec before replication and compression.
9. A 1 percent duplicate rate at 720M/day creates 7.2M suspect impressions/day.
10. A $10k lease per region across three regions creates $30k outstanding exposure if the central ledger is partitioned.

## Evaluator Rubric and Red Flags

- Pass: candidate separates serving, control plane, and billing/reconciliation.
- Pass: candidate quantifies QPS, candidate score rate, log volume, and lease exposure.
- Pass: candidate names exact consistency boundaries and fail-closed behaviors.
- Pass: candidate handles first-price/second-price at intuition level without ignoring quality or policy.
- Pass: candidate uses idempotency for impression/click/conversion and immutable ledger adjustments.
- Pass: candidate scopes incident mitigation to smallest campaign/tenant/region boundary first.
- Red flag: charges advertisers based only on ad response or raw client event.
- Red flag: joins campaign DB, user DB, catalog DB, and budget DB synchronously on every request.
- Red flag: fails open for consent, policy, or budget during dependency outage.
- Red flag: no answer for hot campaign budget keys or cap keys.
- Red flag: global ads disable or global cache flush as the first mitigation.
- Red flag: reporting exports read from live serving stores without tenant byte limits.

## Additional Verification Checklist

1. Verify serving p99 dashboard is split by placement, region, tenant tier, and model version.
2. Verify spend curve alerts page on overpacing and underpacing separately.
3. Verify campaign pause/block reaches serving indexes within the stated 60-second SLO.
4. Verify cap timeout mode cannot default to allow for high-risk campaigns.
5. Verify budget leases are bounded by allowed overspend during region loss.
6. Verify event collectors attach schema version, ingestion time, source, and idempotency key.
7. Verify billing ledger uses immutable adjustment records rather than destructive edits.
8. Verify advertiser reports label estimated versus finalized metrics.
9. Verify report exports are tenant-scoped, audited, and byte-limited.
10. Verify support tools cannot bypass campaign API authorization.
11. Verify fraud decisions preserve raw evidence and mark billing disposition.
12. Verify replay jobs have tenant, campaign, time-window, and byte budgets.
13. Verify model rollouts include fallback and cost guardrails.
14. Verify canaries exercise no-ad, contextual-only, model timeout, cap timeout, and budget exhausted paths.
15. Verify load tests include skewed campaign and placement hot keys, not only uniform QPS.
16. Verify no metric label exposes raw user attributes or unbounded campaign names.
17. Verify creative asset cache respects policy status version and product inventory freshness.
18. Verify checkout and bidding systems are protected from ad-system backpressure.
19. Verify the runbook names preauthorized spend-protection thresholds.
20. Verify incident-window billing hold and advertiser communication templates exist.
21. Verify post-incident reconciliation compares raw events, dedupe output, ledger, and reports.
22. Verify multi-region failover cannot double issue budget leases.
23. Verify emergency switches can disable one advertiser, campaign, creative, placement, model, or region.
24. Verify candidate retrieval and ranker deadlines fit inside the 120 ms p99 budget.
25. Verify privacy review covers attribution windows and audience report thresholds.
