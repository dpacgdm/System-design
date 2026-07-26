# Answer Key - Design Ticketmaster

> Open only after attempting the learner file questions.

---

## Expert Analysis - Ops Sim Worked Response

### Q1 - Root cause and layer split

Primary integrity risk:

1. The primary risk is not stale maps; it is ambiguous hold/payment state.
2. `hold_unknown_status_rate = 6.8%` means clients and services cannot tell whether some hold commands committed.
3. `payment_attempts_in_unknown = 8,900` means PSP authorizations may exist without local certainty.
4. Integrity is still preserved because `seat_oversell_detected_count = 0`, `order_inventory_mismatch_count = 0`, and `capture_without_order_count = 0`.
5. The first invariant is: do not capture unless order and inventory commit are durable.

Capacity amplifier:

1. Queue admission is over plan.
2. `queue_admission_rate = 180,000 users/min` admits 3,000 users/sec.
3. Planned hold capacity is 8,000 attempts/sec, but actual attempts are 13,500/sec.
4. Queue token reuse succeeds at 2.7%, so admitted users can amplify hold pressure.
5. `queue_token_max_hold_attempts = 25` is too high for scarce floor seats.

Fairness/abuse signal:

1. `bot_risk_high_share_of_hold_attempts = 41%`.
2. Risk cluster `R-77` has 28,000 accounts.
3. Average think time is 210 ms, too low for organic seat selection.
4. High-risk cluster hold success is 18%, high enough to materially affect allocation.
5. Token reuse success suggests replay or weak token state enforcement.

Read-model UX problem:

1. `seat_map_projection_lag_seconds = 52` explains flicker.
2. It is not proof of oversell.
3. It can worsen trust and support volume.
4. It must not be fixed by making the map authoritative.
5. Projection lag is secondary to hold, queue, and payment integrity.

Likely causal chain:

1. Manual queue override raises admission to 180,000/min.
2. Queue tokens allow reuse within TTL and 25 hold attempts.
3. Hold attempts exceed plan by 68.75%.
4. Floor section receives 63% of attempts but has only 8 shards, while planned was 32.
5. Conditional write throttles and conflicts raise hold p99 and unknown status.
6. PSP auth p95 reaches 11.8s while local timeout is 5s and retry policy is immediate.
7. Payment attempts enter UNKNOWN and holds remain active under grace.
8. Active held seats reach 61,000, making the event appear nearly gone.
9. Seat-map projection lags, users retry, and bots exploit weak pre-hold friction.
10. No oversell yet because commit/capture gates still hold.

---

### Q2 - Evidence

Queue over-admission:

1. `hold_attempts_per_sec = 13,500` vs `hold_capacity_planned_per_sec = 8,000`.
2. `queue_admission_rate_per_minute = 180000` from config and log.
3. `admitted_users_active = 410,000`, which is too high when 61,000 seats are held.
4. `queue_token_reuse_success_rate = 2.7%` means admission is not a strict one-use gate.
5. `queue_token_max_hold_attempts = 25` permits too much scarce-resource churn.

No oversell evidence:

1. `seat_oversell_detected_count = 0`.
2. `order_inventory_mismatch_count = 0`.
3. `capture_without_order_count = 0`.
4. These are stronger integrity signals than social media reports.
5. Continue to monitor sampled seat transition audit for confirmation.

Hot shard evidence:

1. `floor_section_attempt_share = 63%`.
2. `conditional_write_throttles_per_sec{section="FLOOR"} = 4,200`.
3. Upper section throttles are only 120/sec.
4. The log names `shard=FLOOR-07`.
5. `floor_section_shards = 8` while planned floor shards were 32.

Idempotency weakness:

1. `10:04:11 hold retry idempotency_key=missing`.
2. This retry can turn an unknown status into duplicate pressure.
3. Payment duplicate capture is being rejected, so payment idempotency is stronger than hold idempotency.
4. Missing hold idempotency should trigger client gate and BFF validation.

Wrong or dangerous config:

1. `queue_admission_rate_per_minute: 180000`.
2. `queue_token_max_hold_attempts: 25`.
3. `queue_token_reuse_policy: allow_within_ttl`.
4. `hold_attempt_cost_tokens: 1` equal to browse cost.
5. `floor_section_shards: 8` vs planned 32.
6. `psp_auth_timeout_ms: 5000` lower than observed p95.
7. `psp_retry_policy: retry_timeout_immediately`.
8. `bot_high_risk_action: challenge_after_hold_failure`.

---

### Q3 - T+0 to T+5 mitigation

Safe first actions:

1. Declare incident commander and freeze global manual overrides.
2. Confirm no oversell: check seat audit, order/inventory mismatch, capture without order.
3. Pause or sharply reduce queue admission for `E-TITAN-STADIUM`.
4. Preserve active holds; do not release them blindly.
5. Reject hold requests missing idempotency key.
6. Change queue tokens to single-use for hold attempts.
7. Lower max hold attempts per admitted user.
8. Move high-risk users to pre-hold challenge or deny lane.
9. Stop immediate PSP timeout retry; reconcile unknown attempts first.
10. Keep capture gated on durable order and inventory commit.

What to pause:

1. Pause queue admission immediately or reduce to a trickle tied to hold p99.
2. Do not pause all hold creation if known-good admitted users can still complete safely.
3. Pause new high-risk hold creation until friction is moved before hold.
4. Do not pause payment capture for already durable orders unless capture errors rise.
5. Pause payment submission only if PSP idempotency/reconciliation cannot keep up.

Payments role:

1. Own PSP status lookup for UNKNOWN auths.
2. Disable immediate retry on timeout.
3. Ensure merchant reference/idempotency lookup before any retry.
4. Report capture_without_order and duplicate_capture_rejected every minute.
5. Prepare void-auth workflow for expired or failed holds.

Abuse/fraud role:

1. Identify risk cluster `R-77` and related graph.
2. Move challenge before queue admission or before hold.
3. Apply event-scoped account/device/payment limits.
4. Watch false positives by region/device/accessibility cohorts.
5. Keep evidence for fairness review.

Support message by T+5:

1. "Some payments are processing slowly; a successful authorization is not a completed order."
2. "Do not promise tickets unless order status is confirmed."
3. "Do not manually release or reassign held floor seats."
4. "Use incident dashboard fields: payment_auth_seen, hold_state, order_id, capture_state."
5. "Escalate charged/no-ticket cases to payment reconciliation queue."

---

### Q4 - T+15 mitigation

Hold policy:

1. Do not globally set `hold_ttl_seconds` to 3600.
2. Extend only holds that reached server-side payment submit before expiry.
3. Extension should be event-scoped, short, and auditable.
4. Extension should require low/medium risk or additional verification.
5. Extension should stop when active held seats exceed a threshold.

Eligible users:

1. Users with valid hold ownership.
2. Users with payment_attempt state AUTHORIZING or UNKNOWN.
3. Users whose submit timestamp was received before expires_at plus configured grace.
4. Users not in confirmed bot clusters.
5. Users not exceeding purchase cap.

Bot containment:

1. High-risk cohorts get no automatic extension or must revalidate.
2. Queue token reuse is disabled.
3. Hold attempts become costlier than browse.
4. Payment instrument and device graph limits are enforced.
5. Bot challenge happens before scarce hold attempt, not after failure.

User messaging:

1. Use "processing" for UNKNOWN auth.
2. Do not tell user they have tickets until order and inventory are durable.
3. Show hold deadline or extension clearly.
4. Tell users not to resubmit payment repeatedly.
5. Provide receipt only after capture/order complete.

Avoid:

1. Capturing all auths without order.
2. Releasing all active holds to make more seats visible.
3. Disabling queue under promoter pressure.
4. Increasing floor concurrency without partition plan.
5. Making seat map read model authoritative.

---

### Q5 - Bad fix gallery

Global one-hour TTL:

1. Hoards scarce inventory.
2. Rewards bots already holding seats.
3. Makes active_held_seats look like sellout for an hour.
4. Starves legitimate queue cohorts.
5. Increases support and payment ambiguity.

Disabling waiting room:

1. Sends millions directly to hold and map services.
2. Removes fairness and risk gating.
3. Lets replay/token bugs become unconstrained request floods.
4. Makes event blast radius spread to shared dependencies.
5. Reduces ability to pause admission safely.

Capture all PSP auths:

1. Violates finance constraint.
2. Charges users without durable order/inventory.
3. Creates refunds, chargebacks, and legal risk.
4. Breaks idempotent state machine.
5. Turns ambiguous auths into confirmed customer harm.

Flush every seat-map cache:

1. It increases origin load.
2. It does not fix hold p99 or queue over-admission.
3. It does not repair PSP unknowns.
4. It can worsen flicker while projection lags.
5. It attacks UX symptom, not integrity path.

Raising floor shards mid-incident:

1. Seat ownership state must be repartitioned safely.
2. Existing holds reference old shard ids.
3. Command ordering can break during migration.
4. Projection stream offsets can duplicate or skip updates.
5. It may be safer to steer queue away from floor or pause than reshard hot.

---

### Q6 - Capacity math

Seat conditional writes:

1. 13,500 attempts/sec * 3.4 seats/hold = 45,900 seat conditional writes/sec.
2. This excludes retries from missing idempotency.
3. With retry amplification, true write pressure can be higher.

Floor shard load:

1. Floor attempts = 13,500 * 0.63 = 8,505 attempts/sec.
2. Floor seat writes = 8,505 * 3.4 = 28,917 seat writes/sec.
3. With 8 floor shards, each shard sees about 3,615 seat writes/sec.
4. That is far above a 500 writes/sec planning budget.
5. Planned 32 floor shards would still see about 904 writes/sec before steering/headroom.

Over plan:

1. 13,500 / 8,000 = 1.6875.
2. Current demand is 68.75% over plan.
3. Admission must be reduced below plan until p99 and unknown status recover.

Queue inventory signal:

1. 61,000 held + 9,400 sold = 70,400 against 70,000 public seats.
2. The excess is possible because some held seats are expired, grace-held, or counted in lagging state.
3. Queue must know active sellable availability is effectively exhausted.
4. It should pause admission or set expectation that only released holds may become available.
5. It should not keep admitting users as if 70,000 seats remain.

Expired/blocked holds:

1. `expired_holds_still_counted = 12,400`.
2. `hold_reaper_lag_seconds = 310`.
3. These holds may be unavailable in projection but not truly sellable until safely released.
4. Reaper must conditionally release HELD with matching hold_id, not delete blindly.

---

### Q7 - Abuse and fairness

Bot vs organic:

1. Bot cluster has 28,000 related accounts.
2. Average think time 210 ms is unrealistic for human seat selection.
3. Hold success of 18% for high-risk cluster is materially high.
4. Queue token reuse success suggests automated replay.
5. Organic evidence would include normal account age mix, marketing-driven demand, and human think times.

Controls before hold:

1. Signed single-use queue tokens.
2. Max hold attempts per admitted token.
3. Risk challenge before admission or before hold.
4. Event-scoped purchase caps.
5. Device/account/payment graph throttles.
6. Rejection of missing idempotency keys.
7. Higher token cost for hold attempts than browse.

Event-scoped limits:

1. Account max tickets.
2. Device cluster attempts.
3. Payment instrument purchases.
4. Queue entries per account/device.
5. Transfer/resale velocity after sale.

Avoid false positives:

1. Keep accessible challenge alternative.
2. Do not block all VPNs or regions.
3. Use multiple signals, not one device feature.
4. Provide support appeal for held-seat loss caused by controls.
5. Monitor challenge failure by region, browser, and assistive tech.

Fairness audit:

1. Compare purchase distribution by queue cohort.
2. Compare high-risk vs low-risk success.
3. Measure resale listing velocity by cohort.
4. Review token reuse and purchase cap violations.
5. Publish internal postmortem with false-positive rate and remediation.

---

### Q8 - Durable design fixes

Config changes:

1. Queue admission tied to hold p99, unknown status, active holds, sold count, and PSP health.
2. Queue tokens single-use for hold attempts.
3. Max hold attempts lowered by event heat.
4. Hold attempt token cost greater than browse.
5. PSP timeout and retry policy changed to status lookup before retry.
6. High-risk challenge moved before hold attempt.
7. Floor shards configured to planned 32 or more before sale.

Architecture changes:

1. Event cell admission controller reads real-time inventory and PSP signals.
2. Floor/section sharding supports expected skew before sale starts.
3. Hold idempotency required at BFF and Hold Service.
4. Reaper uses priority lane for expired hot-event holds.
5. Seat-map projection has explicit lag budget and degraded display mode.

Payment changes:

1. Merchant reference used for PSP auth idempotency.
2. UNKNOWN auth reconciliation queue with user-visible processing state.
3. Capture worker checks order and inventory durable commit.
4. Void-auth worker for expired failed holds.
5. Provider capacity pre-negotiated for heat-score events.

Week-08c abuse changes:

1. No IP-only limiting.
2. Account/device/payment/event graph limits.
3. Randomized or verified-fan queue cohorts.
4. Pre-hold friction for high-risk sessions.
5. Token replay metrics and fail-closed behavior.

Acceptance criteria:

1. Zero oversell in audit replay.
2. Zero capture_without_order.
3. Hold p99 under target at planned admission.
4. Queue token reuse success zero.
5. PSP unknowns reconcile within SLO.
6. Seat-map projection lag under degraded-mode budget.
7. Fairness review shows no material bot bypass.

---

### Q9 - Org and runbook

T+0 roles:

1. Incident commander: ticketing platform lead or designated SRE.
2. Inventory lead: owns hold/commit integrity.
3. Queue lead: owns admission control.
4. Payments lead: owns PSP unknowns, auth, capture, voids.
5. Fraud lead: owns bot cluster actions.
6. Comms lead: owns status page, support macros, promoter updates.

Pre-authorized:

1. Pause or reduce event-specific queue admission.
2. Disable queue token reuse.
3. Reject missing idempotency keys.
4. Challenge or throttle high-risk cohorts.
5. Stop immediate PSP retries.
6. Enable targeted hold grace for payment-submitted users within bounded policy.

Requires approval:

1. Cancel or postpone sale.
2. Change purchase caps or fairness policy.
3. Extend all holds globally.
4. Honor old price after pricing defect if policy unclear.
5. Public statements about bot allocation outcomes.
6. Refund/credit program beyond standard policy.

Support runbook:

1. Verify order_id before confirming tickets.
2. Verify capture_id before saying user was charged.
3. If auth exists but no order, place case in reconciliation queue.
4. Never manually release floor seats during active incident.
5. Use event-specific macro for processing state.

---

## Scoring Guide

Foundation pass:

1. Names hold service as authority.
2. Separates seat-map lag from oversell.
3. Pauses/reduces queue admission before scaling writes.
4. Rejects capture without durable order.
5. Performs at least one capacity calculation.

Staff pass:

1. Identifies bad configs.
2. Handles PSP UNKNOWN safely.
3. Applies event-scoped abuse controls.
4. Preserves active holds while stopping amplification.
5. Produces T+0/T+5/T+15 sequence with roles.

Principal stretch pass:

1. Frames fairness, legal, and promoter tradeoffs.
2. Avoids global blast-radius changes.
3. Specifies durable sharding and event-cell changes.
4. Defines audit evidence for "no oversell".
5. Plans post-sale fairness and payment reconciliation.
