# Answer Key — Saga Pattern

> Open only after attempting the learner file questions.

## Expert Analysis

### Question 1: Triage and Causal Chain

```
CAUSAL CHAIN (trip_b44e8d):
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ROOT CAUSES (Friday deploy v2.14.0):
    RC1: reserve-hotel HTTP timeout 30s → 8s
         Booking.com p99 was 11.4s Monday AM → mass timeouts
    RC2: Removed GET /holds/by-saga/{sagaId} endpoint
         reconcile-hotel Lambda gets 404 → cannot distinguish
         TIMEOUT+success from TIMEOUT+failure

  AMPLIFYING FACTORS:
    AF1: Hotel partner elevated latency (external, but our timeout
         made it catastrophic)
    AF2: ReconcileHotel failure treated as "hotel definitely not held"
         → CompensateFlight ran while hotel WAS held
    AF3: trip_b44e8d payment anomaly — ChargePayment NOT in Step Functions
         history but Stripe shows charge. SEPARATE BUG investigation:
         likely duplicate execution or choreography listener on
         FlightReserved (legacy EventBridge rule not disabled).
         Payment at 09:12:19 during ReserveHotel timeout window.
    AF4: UI shows "not charged" based on saga FAILED without Stripe verify
    AF5: Manual refund script without reservation checks (09:18 AM)

  trip_b44e8d FINAL STATE EXPLAINED:
    09:12:11  ReserveHotel starts
    09:12:19  Hotel hold created (partner) + Lambda timeout (our side)
    09:12:19  PARALLEL: legacy payment-charge-handler on EventBridge
              still listening to FlightReserved → charges card
              (FlightReserved fired at 09:12:15 before hotel step)
    09:12:22  Step Functions: ReserveHotel timeout → ReconcileHotel 404
              → CompensateFlight (cancelled) → BookingFailed
    Result: charged, hotel held, flight cancelled, saga FAILED, wrong UI

STOP IMMEDIATELY:
  1. HALT manual refund script (causing wrongful refunds)
  2. DISABLE legacy EventBridge rule payment-on-flight-reserved
     (root of phantom charges during hotel timeout)
  3. ROLLBACK reserve-hotel Lambda timeout 8s → 30s (or 45s)
  4. DO NOT mass-refund until per-saga reconciliation script ready
  5. ENABLE maintenance mode on booking API if charges continue
     (feature flag booking_enabled=false)
```

### Question 2: trip_b44e8d Remediation

```
REMEDIATION ORDER (do not parallelize payment + hotel release):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 0 — VERIFY CURRENT STATE:
  aws stepfunctions describe-execution \
    --execution-arn .../trip_b44e8d

  stripe payment_intents list \
    --query "data[?metadata.sagaId=='trip_b44e8d']"
  # Confirm: pi_2abc999 succeeded $1204.00

  curl "https://hotel.internal/api/v1/holds/by-saga/trip_b44e8d"
  # If 404 (endpoint removed): query HotelSvc DB directly or partner portal
  # Expected: HTL-88271 status=HELD

  curl "https://flight.internal/reservations?sagaId=trip_b44e8d"
  # Expected: CANCELLED (already compensated)

STEP 1 — DECIDE BUSINESS OUTCOME (support + user contact):
  Option A: Honor booking — rebook flight, confirm hotel, complete saga
  Option B: Full cancel — release hotel, refund payment, confirm flight cancelled

  Assume Option B (user saw "failed", expects refund):

STEP 2 — RELEASE HOTEL HOLD:
  curl -X DELETE \
    "https://hotel.internal/api/v1/holds/HTL-88271" \
    -H "Idempotency-Key: trip_b44e8d:CANCEL_HOTEL" \
    -H "Authorization: Bearer $INTERNAL_TOKEN"
  # Verify: status=CANCELLED

STEP 3 — REFUND PAYMENT (only after hotel release OR decision to refund anyway):
  stripe refunds create \
    --payment-intent pi_2abc999 \
    -H "Idempotency-Key: trip_b44e8d:REFUND_PAYMENT"
  # Verify: refund status succeeded

STEP 4 — UPDATE SAGA LOG:
  aws dynamodb update-item \
    --table-name saga_instances \
    --key '{"sagaId":{"S":"trip_b44e8d"}}' \
    --update-expression "SET #s = :status, remediation = :note, updatedAt = :now" \
    --expression-attribute-names '{"#s":"status"}' \
    --expression-attribute-values '{
      ":status":{"S":"FAILED_REMEDIATED"},
      ":note":{"S":"Manual remediation: hotel released, refund issued"},
      ":now":{"S":"2026-07-06T14:45:00Z"}
    }'

  Append saga_step_log entries for MANUAL_CANCEL_HOTEL, MANUAL_REFUND

STEP 5 — CUSTOMER COMMUNICATION (only after Steps 2-3 verified):
  "Your booking could not be completed due to a partner system issue.
   Your hotel hold has been released. A full refund of $1,204.00 has been
   issued to your card (allow 5-10 business days). We apologize."

  NEVER say "not charged" without Stripe verification.

VERIFY BEFORE CUSTOMER MESSAGE:
  □ Stripe PaymentIntent status = succeeded
  □ Stripe Refund status = succeeded (if refunding)
  □ Hotel hold status = CANCELLED
  □ Flight status = CANCELLED (no orphan active reservation)
  □ saga log updated for audit
```

### Question 3: Stop the Bleeding

```
NEXT 15 MINUTES — EXACT ACTIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. DISABLE LEGACY CHOREOGRAPHY (09:23):
   aws events disable-rule --name payment-on-flight-reserved
   # Stops phantom charges parallel to Step Functions

2. ROLLBACK reserve-hotel Lambda (09:25):
   aws lambda update-function-configuration \
     --function-name reserve-hotel \
     --environment "Variables={HOTEL_API_TIMEOUT_MS=30000,...}"
   # Or: deploy previous image tag v2.13.9

3. CIRCUIT BREAKER on hotel API (09:26):
   # In reserve-hotel Lambda / AppConfig:
   hotel_api_circuit_open: true
   # Fail fast with "hotel service unavailable" — no timeout wait
   # Prevents slot exhaustion; users get clear error, no phantom holds

4. STEP FUNCTIONS — pause new executions (if still degrading):
   # Booking API feature flag:
   aws appconfig start-deployment \
     --application-id xxx --environment-id yyy \
     --configuration-profile-id booking-flags \
     --configuration-content '{"booking_enabled":false}'
   # Returns 503 to users — better than wrong charges

5. RESTORE reconciliation endpoint (09:30 hotfix):
   # Revert removal of GET /holds/by-saga/{sagaId}
   # Deploy hotel-svc v2.14.1-hotfix

6. SQS — do NOT drain compensations DLQ blindly during incident
   # Manual triage per message

TIMEOUT VALUES POST-ROLLBACK:
  reserve-hotel client timeout: 30000 ms
  reserve-hotel Lambda timeout: 45 s
  Step Functions ReserveHotel TimeoutSeconds: 40
  ReconcileHotel: must succeed before CompensateFlight triggers
```

### Question 4: Detection Gaps

```
ALERT THAT WOULD HAVE FIRED AT 08:56 AM:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Panel: Partner API Health
    Metric: hotel_api_client_timeout_rate (from Lambda embedded metrics)
    Baseline: < 1% (Friday)
    Observed: would climb at 08:56 as Booking.com latency rose

  Alert rule (CloudWatch):
    Metric: reserve_hotel_timeout_rate
    Statistic: Average over 5 minutes
    Threshold: > 5%
    EvaluationPeriods: 2
    → Fires ~09:06 AM (before payment alerts at 09:14)

  SECONDARY ALERT (reconciliation):
    Metric: reconcile_hotel_error_rate
    Threshold: > 0% for 1 minute
    → Would fire immediately on first 404 after deploy

  SAGA LOG FIELD (add):
    partner_latency_ms on each saga_step_log entry
    Dashboard: p99 partner_latency by step
    Alert: p99 > client_timeout * 0.8 for 5 min → P3 warning

  SYNTHETIC CANARY:
    EventBridge schedule every 5 min: run full saga against test inventory
    in staging with SAME Lambda versions as prod (promote together)
    Alert on canary failure → block prod deploy pipeline
```

### Question 5: Long-Term Fixes

```
ARCHITECTURAL FIXES:
━━━━━━━━━━━━━━━━━━

  1. TIMEOUT SEMANTICS
     ReserveHotel timeout → ReconcileHotel (required, not optional)
     ReconcileHotel must NOT fall through to compensation on 404/500
     → mark saga UNKNOWN, page on-call, do NOT compensate
     Compensation only after confirmed hold does not exist

  2. DELETE CHOREOGRAPHY PAYMENT PATH
     Remove all EventBridge rules that touch payment outside Step Functions
     CI test: assert no rule targets payment-charge-handler except from SFN

  3. PAYMENT GATE
     PaymentSvc rejects charge unless saga log shows
     RESERVE_FLIGHT + RESERVE_HOTEL + RESERVE_CAR all COMPLETED
     (defense in depth even if orchestrator bugs)

  4. UI TRUTH SOURCE
     "Not charged" only if: no Stripe PI OR PI status cancelled/failed
     Query Stripe from booking status API, not saga status alone

  5. DEPLOY CHECKLIST (blocking)
     □ Reconciliation endpoints covered by contract tests
     □ Timeout values > partner p99 from last 7 days (auto-computed)
     □ Canary saga passed in staging with prod Lambda ARNs
     □ Rollback tag documented in deploy ticket

  6. MANUAL SCRIPT GUARDRAILS
     Refund script must:
       - Join Stripe PI + saga_log + reservation DBs
       - Idempotency key per refund
       - Dry-run mode default
       - Require two-person approval for batch > 10
       - Never key only on saga status=FAILED

  7. IDEMPOTENCY + SINGLE WRITER
     One orchestrator path per saga type
     saga start: conditional write on sagaId
     Disable parallel execution paths

  8. POSTMORTEM ACTION ITEMS
     P0: ReconcileHotel blocking compensation
     P0: Remove legacy payment rule
     P1: Partner latency adaptive timeouts
     P1: UNKNOWN saga state + watchdog
     P2: Staging canary in deploy pipeline
```

---
