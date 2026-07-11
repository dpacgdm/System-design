# Client Offline and Edge Resilience Answers

Open only after attempting the learner file Ops Sim.

## Northstar Mobile Offline Queue Duplicates Checkout

### Q1 - Which operations should have been offline queueable, revalidated, or onl

Name the narrow failing layer first, then show why
adjacent healthy systems do not disprove it. The root
cause should be phrased as a mechanism with an invariant,
not as a team name or product name.

### Q2 - Which signals prove the duplicate is client idempotency/retry behavior r

Use the telemetry pack in slices. A strong answer cites at
least three metrics, one log/config fact, and one
misleading global signal that would hide the affected
customer group.

### Q3 - How does QUIC connection migration help, and what app-level problem rema

The first fifteen minutes should freeze additional blast
radius, preserve evidence, scope or disable the dangerous
path, and avoid destructive cleanup. Do not optimize for
green dashboards before protecting correctness.

### Q4 - Write the first 15-minute mitigation that stops new risk without corrupt

Reject fixes that weaken authentication, authorization,
idempotency, source-of-truth repair, or tenant boundaries.
Also reject broad global changes when the evidence points
to a cell, tier, client version, route, or operation
class.

### Q5 - What should the server do with stale price and inventory versions during

The capacity or blast-radius answer must do arithmetic
from the prompt: rates, percentages, queue depth, lag,
stale windows, or duplicate counts. Fleet averages are not
enough.

### Q6 - What conflict UX should buyers and sellers see

The durable fix should include an automated test or game-
day, a config or protocol change, telemetry, an owner, and
a clear acceptance threshold.

### Q7 - What mobile flag and cache TTL design would make rollback reliable

The org/runbook answer should name incident command,
service owner, security or fraud if relevant,
product/support, and the approval boundary for risky
mitigations.

### Q8 - Name durable telemetry and tests before relaunch.

The final answer should turn the incident into launch
criteria: what must be true before the next rollout and
which bad state is now impossible or quickly detected.

## Worked response outline

- Primary diagnosis: mobile offline queue treats checkout
  submit as queueable with a new idempotency key per
  retry; QUIC migration helps transport but the app
  timeout creates a new business operation.
- Ledger duplicate business effects being zero is good but
  not sufficient; PSP duplicate authorize attempts are
  still external risk and customer harm.
- Immediate move: remotely disable offline checkout
  submit, force server to reject stale price/inventory for
  money decisions, preserve pending operation IDs, and
  avoid deleting local queues blindly.
- Fix: stable client_operation_id per checkout intent,
  server idempotency record scoped to
  tenant/account/operation/payload hash, bounded retry
  with jitter, and user-visible pending until server
  confirms.
- Rollback design: critical mobile flags have short TTL,
  safe default false, server override, app-version gates,
  and telemetry for stale flag versions.

## Principal-depth model answer

### Q1 - Operation classification

Do not treat the offline queue as "HTTP requests saved for
later." It stores user intent with safety classes:

- Safe offline/queueable: cart draft edits, wish-list changes,
  local notes, and display preferences, provided they carry
  operation ids and conflict metadata.
- Stale for display only: catalog title/image, old price for
  browsing, seller profile snippets, and cached availability
  labels with visible freshness.
- Must revalidate before decision: price, promotion,
  inventory version, buyer eligibility, seller restrictions,
  tax/shipping quote, and risk state.
- Online-only or pending-confirmation: checkout submit,
  payment authorize/capture, final inventory reserve, and any
  action with external side effects.

The protected invariant is: a local enqueue cannot imply
server-confirmed order placement, and one checkout intent
cannot create multiple PSP effects.

### Q2 - Evidence for client retry/idempotency

The ledger is not double-committing; the client is creating
new operations:

- `sync_duplicate_operation_total{operation=checkout_submit}:
  812` is route-specific.
- `duplicate_psp_authorize_attempt_total: 143` shows external
  risk.
- `duplicate_business_effect_total{ledger}: 0` proves ledger
  dedupe is holding internally.
- `client_retry_attempts_p99{network=cellular}: 19` and the
  train/network context show retry amplification.
- Log: `generated idempotency key per HTTP retry` names the
  bug.
- Trace: QUIC migrates successfully, but the app timeout fires
  and the sync worker retries as a new operation.
- `mobile_flag_version` stale on 62% of affected clients
  explains why backend flips alone do not instantly stop the
  path.

### Q3 - QUIC helps transport, not business identity

QUIC connection migration preserves transport continuity
across Wi-Fi/cellular changes and can reduce dropped
connections. It does not decide whether two HTTP attempts
represent one checkout intent. If the app timeout path creates
a new idempotency key, QUIC success only hides part of the
network symptom while the business operation still duplicates.

The app-level fix is a stable `client_operation_id` generated
when the user commits the checkout intent, persisted locally,
and reused across retries, app restarts, transport migration,
and server reconciliation.

### Q4 - First 15-minute mitigation

T+0 to T+5:

1. Declare P1 for Android 2026.07.11 offline checkout.
2. Name owners: mobile, checkout API, pay-ledger, inventory,
   support, finance/risk, and product.
3. State invariant: no duplicate PSP effects and no checkout
   decision from stale price/inventory.
4. Freeze mobile rollout and any server change that expands
   offline checkout.

T+5 to T+10:

5. Server-side gate `checkout_submit.queueable_offline=false`
   for affected app versions regardless of stale client flag.
6. Reject stale price/inventory at checkout with a conflict
   response, not silent acceptance.
7. Preserve pending operation ids and local queues; do not
   tell clients to delete queues blindly.
8. Lower retry pressure by returning explicit pending/conflict
   states and `Retry-After`.

T+10 to T+15:

9. Build affected ledger from operation id, account, tenant,
   app version, PSP key, and inventory hold version.
10. Notify support that "pending" means awaiting server
    confirmation, not successful order placement.
11. Track duplicate PSP attempts, ledger duplicate effects,
    stale checkout blocks, and queue age by app version.

### Q5 - Server handling of stale state

The server must be authoritative:

- If `price_age_seconds` exceeds the decision budget, return
  a revalidation conflict with current price; do not accept
  client price for money movement.
- If `client_version` of inventory is behind server version,
  require refresh or hold reconciliation.
- If an idempotency key exists with the same payload hash,
  return pending/succeeded status without new PSP attempt.
- If an idempotency key exists with a different payload hash,
  reject as conflict.
- If no stable key exists for an affected app version, mint a
  compatibility key from server-known checkout intent and
  force online confirmation.

### Q6 - Conflict UX

Buyer UX:

- "Order pending" only while server status is unknown.
- "Price or availability changed; review before placing
  order" for stale decision data.
- One receipt/status per checkout intent, tied to server
  operation status.
- Clear refund/authorization language: duplicate
  authorization attempts are being reconciled; do not imply
  duplicate charges if ledger effects are zero.

Seller UX:

- Inventory hold conflict should show current server version,
  pending holds, and whether a hold is reserved, expired, or
  conflicting.
- Seller analytics may show a freshness label while repair
  runs, but source inventory state must not be invented from
  client cache.

### Q7 - Flag/cache rollback design

Critical mobile flags need:

- safe default false for risky offline checkout;
- server override that can deny the operation even if the
  client flag is stale;
- TTL measured in minutes, not 24 hours, for kill switches;
- app-version gates and minimum supported version;
- signed/config-versioned flag payloads;
- telemetry for stale flag version, flag age, decision route,
  and server override count;
- explicit offline behavior when flag cannot be refreshed.

SWR cache needs a split between display freshness and decision
freshness. Product pages may display bounded stale values with
labels; checkout must revalidate price/inventory/risk before
payment.

### Q8 - Durable telemetry and tests

Acceptance criteria:

- replay of Wi-Fi-to-cellular timeout preserves one operation
  id and creates zero duplicate PSP attempts;
- app restart and offline queue drain preserve stable
  `client_operation_id`;
- stale price/inventory contract test returns conflict before
  payment;
- affected old app versions use server-generated compatibility
  id or are blocked from offline checkout;
- retry budget and jitter tests cap reconnect storms;
- flag TTL/override test proves stale clients cannot keep
  risky checkout enabled for a day;
- dashboards slice duplicate attempts, queue age, stale
  blocks, flag staleness, ledger duplicates, and PSP attempts
  by app version/network/tenant;
- game-day includes train/network migration, push invalidation
  delay, offline drain, and payment timeout.

## Scoring rubric

| Score | Description |
| --- | --- |
| Meets bar | Names mechanism, protects invariant, sequences mitigation safely, includes evidence and numeric blast-radius/capacity reasoning. |
| Borderline | Finds the symptom but misses one of rollback, capacity, customer slice, or rejected bad fix. |
| Miss | Optimizes a dashboard, repairs from derived state, weakens trust/idempotency, or ignores affected slice evidence. |
