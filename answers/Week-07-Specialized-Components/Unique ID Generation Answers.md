# Answer Key - Unique ID Generation

> Open only after attempting the learner file questions.

# Incident Deep-Dive: Snowflake Collision Storm on Black Friday

---

## Question 1: The Exact Failure Chain

### Why 2:41 AM, Not Before

```
NORMAL TRAFFIC (800 tx/sec, 20 pods):
  20 pods on 8 nodes → ~2-3 pods per node
  2-3 pods sharing machine_id → 2-3 × 256 = 768 IDs per 10ms
  800 tx/sec = 8 per 10ms globally → 1 per 10ms per machine_id group
  Utilization: 1/768 = 0.1% of capacity
  → No problem. Plenty of headroom.

BLACK FRIDAY RAMP (8,000 tx/sec, 60 pods):
  Auto-scaler adds 40 pods in 10 minutes (2:30-2:40 AM)
  60 pods on 12 nodes → 5 pods per node (exactly)
  5 pods sharing same machine_id (private IP & 0xFFFF)

  8,000 tx/sec = 80 per 10ms globally
  Per machine_id group (5 pods): 80/12 nodes ≈ 6.7 per 10ms average

  Still under 256/10ms capacity? YES on average.
  But traffic is BURSTY, not uniform:

  Burst pattern (measured in logs):
    2:40:45 — 340 tx in 100ms (flash sale item drops)
    = 34 per 10ms per node group
    Still OK.

  THE TRIGGER at 2:41:33:
    1. Flash sale burst: 500 tx in 200ms
    2. 3.2% already failing (early duplicate attempts from sequence pressure)
    3. Client SDK auto-retries failed payments (3 retries, exponential backoff)
    4. Retry storm: 500 × 1.032 × 3 = 1,548 effective attempts in 200ms
    5. Per machine_id group: 1,548 / 12 = 129 per 10ms
    6. 129 > 256? No — but Sonyflake sequence is PER PROCESS

  THE ACTUAL ROOT CAUSE (two compounding bugs):

  BUG 1: Shared machine_id across pods on same node
    5 separate Sonyflake instances, same machine_id
    Each maintains its OWN sequence counter (in-process memory)
    They do NOT coordinate sequence numbers

    Timeline within one 10ms window (machine_id=48291):
      T+0ms:  Pod-A seq=0 → ID ...8016
      T+1ms:  Pod-B seq=0 → ID ...8016  ← DUPLICATE (independent counters!)
      T+2ms:  Pod-C seq=0 → ID ...8016  ← DUPLICATE
      T+3ms:  Pod-A seq=1 → ID ...8017
      T+3ms:  Pod-B seq=1 → ID ...8017  ← DUPLICATE

    Sonyflake sequence is per-instance, NOT shared.
    Same machine_id + same 10ms window + same sequence = COLLISION.

  BUG 2: NTP step on 3 nodes at 2:38 AM
    chrony stepped clock backward 2.7 seconds on nodes 4, 7, 11
    Sonyflake default: throws exception on backward clock
    Pods on those nodes: ID generation halted for ~3 seconds
    Then: burst of requests when pods recover
    All pods on affected nodes generate IDs with same "recovered" timestamp
    Amplifies collision probability in the 10ms window after recovery

  COMBINED EFFECT:
    Shared machine_id (Bug 1) + retry storm + NTP step recovery burst (Bug 2)
    = 847 duplicate ID attempts in 17 minutes
    First duplicate logged at 2:41:33 — 11 minutes after traffic ramp
    (Time needed for auto-scale to 60 pods + flash sale burst + retry storm)
```

### The Collision Math

```
Sonyflake uniqueness guarantee assumes:
  ONE process per machine_id

With 5 processes sharing machine_id:
  Collision probability in same 10ms window:
    P(two pods same seq) = 1/256 per pair
    Pairs among 5 pods: C(5,2) = 10 pairs
    P(at least one collision per 10ms) ≈ 10/256 ≈ 3.9%

  At 6.7 IDs per 10ms per group × 3.9% = 0.26 collisions per 10ms
  Over 17 minutes (102,000 windows): 0.26 × 102,000 ≈ 26,500 expected collisions

  Observed: 847 duplicate attempts
  (Lower because not all windows have concurrent generation from all 5 pods)

  The PK constraint rejected 847 inserts.
  Each rejection = failed payment = customer charged but no transaction record.
  (Separate bug: idempotency not implemented on payment path)
```

---

## Question 2: Immediate Mitigation — Priority Order

```
╔══════════════════════════════════════════════════════════════════╗
║  PRIORITY │ ACTION                        │ TIME    │ IMPACT     ║
╠══════════════════════════════════════════════════════════════════╣
║  P0 (+0m) │ Stop duplicate generation     │ 2 min   │ Stop bleed ║
║           │ Switch to UUID v7 fallback    │         │            ║
╠══════════════════════════════════════════════════════════════════╣
║  P0 (+2m) │ Verify PK constraint holding  │ 1 min   │ Confirm    ║
║           │ No duplicate rows in DB       │         │ safety     ║
╠══════════════════════════════════════════════════════════════════╣
║  P1 (+3m) │ Scale DOWN to StatefulSet     │ 10 min  │ Reduce     ║
║           │ max 16 replicas (unique IDs)  │         │ collision  ║
╠══════════════════════════════════════════════════════════════════╣
║  P1 (+5m) │ Enable idempotency on payment │ 15 min  │ Stop double║
║           │ path (client retry safe)      │         │ charges    ║
╠══════════════════════════════════════════════════════════════════╣
║  P2 (+15m)│ Identify failed tx, reconcile │ 30 min  │ Customer   ║
║           │ with payment processor        │         │ recovery   ║
╠══════════════════════════════════════════════════════════════════╣
║  P2 (+30m)│ Fix MachineID assignment      │ 1 hour  │ Permanent  ║
║           │ Deploy StatefulSet + ordinal  │         │ fix        ║
╚══════════════════════════════════════════════════════════════════╝
```

### Action 1: Emergency ID Fallback (Minute 0-2)

```go
// Feature flag: EMERGENCY_ID_MODE=uuid_v7
func (g *IDGenerator) NextID() (int64, error) {
    if os.Getenv("EMERGENCY_ID_MODE") == "uuid_v7" {
        // UUID v7 as int64 is not possible — use separate column
        // OR: use timestamp_ms << 22 | random(22 bits)
        // Quick hack: nanosecond timestamp + crypto random
        return generateEmergencyID(), nil
    }
    return g.sonyflake.NextID()
}

func generateEmergencyID() int64 {
    // NOT Snowflake-compatible but UNIQUE and FAST
    // High bits: unix nano / 1000 (microsecond precision)
    // Low 22 bits: crypto rand
    ns := time.Now().UnixNano() / 1000
    rand := cryptoRand22Bits()
    return (ns << 22) | rand
}
```

```bash
# Deploy emergency flag via ConfigMap (no redeploy needed):
kubectl patch configmap order-api-config \
  -p '{"data":{"EMERGENCY_ID_MODE":"uuid_v7"}}'

# Rolling restart to pick up config:
kubectl rollout restart deployment/order-api

# Verify error rate dropping:
kubectl logs -l app=order-api --since=2m | \
  grep -c "duplicate key"
# Should trend to 0 within 2 minutes
```

### Action 2: Verify Database Integrity (Minute 2-3)

```sql
-- CRITICAL: Confirm zero duplicate rows stored
SELECT id, COUNT(*) AS cnt
FROM transactions
WHERE created_at > '2026-11-28 02:30:00'
GROUP BY id
HAVING COUNT(*) > 1;
-- MUST return 0 rows

-- Count failed-but-charged transactions (idempotency gap):
SELECT COUNT(*) FROM payment_attempts
WHERE status = 'charged'
  AND transaction_id IS NULL
  AND created_at > '2026-11-28 02:30:00';
-- This is your customer impact number
```

### Action 3: Reduce Collision Surface (Minute 3-10)

```bash
# Immediately scale DOWN to reduce pods-per-node density
# Fewer pods sharing machine_id = fewer collisions
# (Band-aid until StatefulSet fix deploys)

kubectl scale deployment order-api --replicas=16

# 16 pods on 12 nodes → max 2 pods per node (most nodes: 1 pod)
# Collision pairs: C(2,2) = 1 pair per node vs C(5,2) = 10 pairs
# 10x reduction in collision probability
```

### Action 4: Payment Idempotency (Minute 5-15)

```
847 failed inserts but payment processor may have CHARGED the customer.
This is the REAL business impact — not the duplicate IDs themselves.

IMMEDIATE:
  Query payment processor API for all charges in window without matching tx:
    SELECT p.external_charge_id, p.amount, p.customer_id
    FROM payment_attempts p
    LEFT JOIN transactions t ON p.transaction_id = t.id
    WHERE p.status = 'charged' AND t.id IS NULL
      AND p.created_at > '2026-11-28 02:30:00';

  For each orphaned charge:
    Option A: Create transaction record retroactively (if business allows)
    Option B: Refund immediately + notify customer
    Option C: Hold for manual review (if amount > threshold)

  DO NOT wait for ID fix before addressing customer money.
```

---

## Question 3: Is the PK Constraint "The System Working"?

```
SHORT ANSWER: The PK constraint did its job. The SYSTEM did not.

WHAT THE PK CONSTRAINT PREVENTED:
  ✓ Zero duplicate transaction rows in database
  ✓ Zero double-credit to merchants
  ✓ Zero audit trail corruption
  ✓ Data integrity maintained despite application bug

WHAT THE PK CONSTRAINT DID NOT PREVENT:
  ✗ 847 failed payment attempts (customer experience)
  ✗ Potential double-charges (payment path lacks idempotency)
  ✗ $120K/minute GMV loss during peak (3.2% error rate × 8K tx/sec)
  ✗ Customer trust damage ("payment failed" on Black Friday)
  ✗ Engineering pager at 2:47 AM

THE CRITICAL DISTINCTION:

  Database constraint = last line of defense (data layer)
  Application ID generation = first line of defense (app layer)

  Relying on PK constraint as "the fix" is like saying:
  "The fire alarm worked correctly — it detected the fire.
   The building is still on fire."

  CORRECT FRAMING:
    Layer 1 (App): Generate unique IDs → FAILED (Sonyflake collision)
    Layer 2 (DB):  Reject duplicates → SUCCEEDED (PK constraint)
    Layer 3 (Biz): Idempotent payments → FAILED (not implemented)

  Two of three layers failed. Only the database saved data integrity.
  The business layer (customer money) was exposed.

METRICS TO REPORT IN POST-MORTEM:
  → 847 duplicate ID generation attempts (app bug)
  → 847 failed transaction inserts (PK rejections)
  → ~260 estimated orphaned payment charges (idempotency gap)
  → ~$2.1M GMV at risk during 17-minute window (3.2% × 8K × $50 AOV × 17min)
  → 0 duplicate rows in database (PK constraint success)
  → 260 customer support tickets in 1 hour
```

---

## Question 4: Long-Term Fix — Defense in Depth

### Layer 1: Fix Machine ID Assignment (Code + Infrastructure)

```yaml
# Change Deployment → StatefulSet
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: order-api
spec:
  replicas: 32  # max 32 = 16-bit machine_id capacity per DC
  serviceName: order-api
  template:
    spec:
      containers:
      - name: order-api
        env:
        - name: POD_ORDINAL
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['apps.kubernetes.io/pod-index']
```

```go
// Sonyflake with guaranteed unique MachineID
settings := sonyflake.Settings{
    StartTime: time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC),
    MachineID: func() (uint16, error) {
        ordinal, err := strconv.Atoi(os.Getenv("POD_ORDINAL"))
        if err != nil {
            return 0, fmt.Errorf("POD_ORDINAL required: %w", err)
        }
        dcOffset := datacenterOffset(os.Getenv("AWS_REGION"))
        return uint16(dcOffset + ordinal), nil
    },
}

// Startup validation: register machine_id in Redis/etcd
// Fail fast if machine_id already claimed
func validateMachineID(id uint16) error {
    claimed, err := redis.SetNX(ctx, fmt.Sprintf("machine_id:%d", id),
        os.Getenv("HOSTNAME"), 30*time.Second).Result()
    if err != nil || !claimed {
        return fmt.Errorf("machine_id %d already claimed", id)
    }
    // Heartbeat goroutine renews lease every 10 seconds
    return nil
}
```

### Layer 2: Clock Drift Hardening

```go
// Tolerate backward drift up to 5 seconds
func (g *Generator) nextTimestamp() (uint64, error) {
    now := time.Now()
    elapsed := now.Sub(g.epoch) / 10ms

    if elapsed < g.lastElapsed {
        drift := g.lastElapsed - elapsed
        if drift <= 500 { // 500 × 10ms = 5 seconds tolerance
            g.metrics.ClockDriftCounter.Inc()
            elapsed = g.lastElapsed // logical monotonic time
        } else {
            return 0, fmt.Errorf("clock drift %d exceeds tolerance", drift)
        }
    }
    g.lastElapsed = elapsed
    return uint64(elapsed), nil
}
```

```yaml
# Prometheus alerts
- alert: ClockDriftDetected
  expr: id_generator_clock_drift_total > 0
  for: 1m
  labels:
    severity: warning

- alert: ClockDriftCritical
  expr: chrony_tracking_offset_seconds > 0.5
  for: 30s
  labels:
    severity: critical
```

### Layer 3: Idempotent Payment Path

```sql
ALTER TABLE payment_attempts
  ADD COLUMN idempotency_key UUID UNIQUE;

-- Client sends Idempotency-Key header with every payment request
-- UNIQUE constraint prevents double-charge on retry
```

```go
func CreateTransaction(ctx context.Context, req PaymentRequest) (*Transaction, error) {
    // Idempotency check FIRST (before ID generation)
    existing, err := db.FindByIdempotencyKey(req.IdempotencyKey)
    if existing != nil {
        return existing, nil // safe retry
    }

    id, err := idGenerator.NextID()
    if err != nil {
        return nil, err
    }

    tx, err := db.InsertTransaction(id, req)
    if isDuplicateKeyError(err) {
        // Another pod won the race — fetch the existing record
        return db.FindByIdempotencyKey(req.IdempotencyKey)
    }
    return tx, err
}
```

### Layer 4: Process Controls

```
PRE-DEPLOY CHECKLIST (add to CI/CD):
  □ Load test ID generator at 2x expected peak with N replicas
  □ Verify all machine_ids unique: integration test
  □ Chaos test: NTP step backward during load test
  □ Chaos test: pod kill + restart during load test
  □ Verify idempotency key prevents double-charge on retry

AUTO-SCALER CONSTRAINT:
  Max replicas ≤ 65536 (Sonyflake 16-bit machine_id)
  BUT: practically max 32 per datacenter (operational limit)
  Configure HPA maxReplicas: 32

MONITORING (new dashboards):
  → id_generation_total (success/failure by reason)
  → id_generation_duplicate_key_total (should ALWAYS be 0)
  → id_generator_machine_id (unique per pod — alert on duplicate)
  → chrony_tracking_offset_seconds (alert > 100ms)
  → payment_idempotency_cache_hit_total (retry safety)
```

### Layer 5: Dual-ID Fallback Architecture

```
LONG-TERM ARCHITECTURE (belt and suspenders):

  transactions table:
    id              BIGSERIAL PRIMARY KEY     ← DB-assigned, always unique
    external_id     BIGINT UNIQUE NOT NULL    ← Snowflake, customer-facing
    idempotency_key UUID UNIQUE               ← client retry safety

  If Snowflake fails → insert with external_id = NULL, backfill later
  If Snowflake collides → PK on external_id catches it, idempotency returns existing
  If everything fails → BIGSERIAL still gives a valid internal row

  The BIGSERIAL is the ultimate fallback.
  Snowflake is for customer-facing sortable IDs.
  Idempotency key is for payment safety.
  Three independent uniqueness guarantees.
```

---

## Post-Mortem Summary

```
ROOT CAUSE:
  Sonyflake default MachineID (IP-based) shared across multiple pods
  on same Kubernetes node → independent sequence counters with
  same machine_id → duplicate IDs under burst load + retry storm.

CONTRIBUTING FACTORS:
  1. Deployment (not StatefulSet) — no guaranteed unique pod identity
  2. NTP step on 3 nodes during traffic ramp — amplified burst after recovery
  3. No idempotency on payment path — failed insert = potential double-charge
  4. Auto-scaler increased pods-per-node density (5 pods/node at peak)
  5. No integration test for ID uniqueness under concurrent load

WHAT SAVED YOU:
  Postgres PRIMARY KEY constraint — zero duplicate rows stored

WHAT DIDN'T SAVE YOU:
  847 customers with failed payments during peak revenue window
  ~260 potential orphaned charges requiring manual reconciliation
  $2.1M GMV at risk during 17-minute incident window

LESSONS:
  1. PK constraint is last-resort defense, not a strategy
  2. ID generator uniqueness must be tested under concurrent load
  3. Payment paths MUST be idempotent independent of ID generation
  4. Kubernetes Deployment + IP-based MachineID = collision waiting to happen
  5. Auto-scaling increases collision probability — cap replicas or fix MachineID first
```

---
