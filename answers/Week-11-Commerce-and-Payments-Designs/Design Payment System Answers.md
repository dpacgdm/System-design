# Answer Key — Design Payment System

> Open only after attempting the learner file questions.

## Expert Analysis


### Question 1: Causal Chain

```
ROOT CAUSE:
  RC1: v3.8.2 Stripe client timeout 25s → 5s while Stripe p99 = 6.1s
  RC2: ReconcileAuth removed/disabled — timeout always → compensate path

AMPLIFIERS:
  A1: User message derives from saga status, not ledger/PSP truth
  A2: Retry creates new order_id + new idempotency_key → double auth
  A3: Void script without capture-state check → wrongful void attempts

IMMEDIATE STOP:
  1. Rollback payment-api to v3.8.1 (ALB weighted routing 100% previous TG)
  2. Enable feature flag reconcile_auth_mandatory=true (kill switch)
  3. Disable void_failed_sagas_cron job
  4. Status page: "Checkout degraded — do not retry payment if charged"
```

### Question 2: order_7712 Remediation

```bash
# 1. Verify Stripe truth
stripe payment_intents retrieve pi_8xx
# expect: status=requires_capture, amount=18900

# 2. Check ledger
psql -c "SELECT * FROM journal_entries WHERE reference_id='pi_8xx';"

# 3. Inventory — reservation released; decide hold or honor
# If stock available: re-reserve for customer; else offer substitute

# 4. If fulfilling: capture (customer intended to buy)
stripe payment_intents capture pi_8xx
# Post ledger CAPTURE entry idempotency_key=manual:order_7712

# 5. Create order record (backfill) linked to pi_8xx
# Update saga status COMPLETED_WITH_REMEDIATION (audit)

# 6. Void pi for duplicate order_7713 if user does not want two orders

# 7. Customer message ONLY after Stripe + ledger agree:
# "We experienced a technical issue. Your payment of $189.00 is confirmed.
#  Order #7712 is processing."
```

### Question 3: Stop Bleeding

```
Rollback v3.8.1 — 5 min via ECS blue/green
Stripe read timeout: restore 25000ms
Step Functions: set AuthorizePayment HeartbeatSeconds=60
Circuit breaker: if stripe_error_rate > 10% for 2 min → open 30s
Rate limit checkout: 5 attempts per user per 10 min (WAF rule)
```

### Question 4: Detection

```
Alert: stripe_p99_latency > 4s for 10 min AND authorize_timeout_rate > 5%
Severity: P2 (page payment on-call)
Panel: overlay Stripe dashboard latency vs our timeout config line (5s)

Synthetic canary: every 1 min create $0.50 test PI in staging mirror prod timeout
```

### Question 5: Long-Term

```
- Reconcile step CANNOT be feature-flagged off in prod (config guard)
- Timeout must be > PSP p99.99 + network (auto from metric)
- User payment status = f(ledger, PSP) not saga alone
- Retry UX: same idempotency_key for same cart_id
- Void script: require human approval + SQL join captures
- Post-deploy: soak test 30 min at 2x traffic before full promotion
```

---
