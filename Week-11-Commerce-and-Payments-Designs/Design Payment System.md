
# Design Payment System

> Week 11, Topic 1 — System Design. Stripe-grade payment infrastructure: idempotency,
> double-entry ledger, PCI scope reduction, saga-orchestrated checkout, and
> production reconciliation. Connects to Week 6 Saga Pattern.

Same teaching contract as all curriculum modules: every section answers *what do I
run, what do I look at, what's the bug nobody warned me about?*

**Prerequisite mental model.** A payment system is not a database that stores
"paid = true." It is an **append-only financial ledger** with **state machines**
for external PSP calls, **idempotent APIs** at every money boundary, and
**reconciliation** that proves ledger balances match bank deposits.


---

## Learning Objectives

```
╔═══════════════════════════════════════════════════════════════╗
║ AFTER THIS MODULE, YOU WILL BE ABLE TO:                       ║
║                                                               ║
║ 1. Design a Stripe-like payment API with idempotency keys,    ║
║    PaymentIntent state machines, and webhook delivery         ║
║                                                               ║
║ 2. Build a double-entry ledger that is the source of truth    ║
║    for balances, payouts, fees, and refunds                   ║
║                                                               ║
║ 3. Scope PCI DSS correctly (SAQ A vs SAQ D) using tokenization║
║    and network segmentation                                   ║
║                                                               ║
║ 4. Orchestrate checkout with Week 6 sagas: reserve inventory, ║
║    authorize, capture, fulfill — with compensations           ║
║                                                               ║
║ 5. Diagnose production payment incidents: phantom charges,    ║
║    double captures, stuck 3DS, reconciliation drift           ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "Payment row in orders table = ledger"              ║
║ WRONG. Order status and financial truth diverge. Refunds, partial    ║
║ captures, chargebacks, and platform fees require an immutable ledger.║
║ The orders table is a business view; the ledger is accounting truth. ║
║                                                                      ║
║ MENTAL MODEL #2: "Idempotency key = no duplicates ever"              ║
║ WRONG. Idempotency prevents duplicate *API effects* for the same key.║
║ It does not fix: client retries with NEW keys, webhook redelivery,   ║
║ or saga compensation racing with capture. You need keys + saga state.║
║                                                                      ║
║ MENTAL MODEL #3: "We use Stripe so PCI is their problem"             ║
║ WRONG. Stripe reduces scope; you still own SAQ A eligibility.        ║
║ Any server that touches PAN (even in logs) expands scope to SAQ D.   ║
║ Your VPC, logging, and admin access are in scope.                    ║
║                                                                      ║
║ MENTAL MODEL #4: "Authorize then capture is optional"                ║
║ WRONG. Auth/capture split is how you avoid charging for inventory    ║
║ you cannot fulfill. Single-step charge is for digital goods only.    ║
║ E-commerce with physical fulfillment almost always needs auth hold.  ║
║                                                                      ║
║ MENTAL MODEL #5: "Webhooks are notifications, not contracts"         ║
║ WRONG. PSP webhooks are eventual consistency signals. Your ledger    ║
║ must reconcile even if webhooks are lost. Webhooks accelerate        ║
║ state; they do not replace polling and daily settlement files.       ║
║                                                                      ║
║ MENTAL MODEL #6: "Saga compensation = automatic refund"              ║
║ WRONG. Week 6: compensation is semantic reversal with its own        ║
║ failure modes. Refund may fail, take days, or need fraud review.     ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching


### Step 1: Clarify Requirements

Interview opening (60 seconds):

```
"We're designing a payment platform for a marketplace — merchants sell,
platform takes a fee, payouts go to merchant bank accounts. Think Stripe
Connect or PayPal Commerce. I'll scope to core money movement: pay-in,
refund, payout, ledger, and merchant onboarding. I'll defer subscriptions
and crypto unless asked."
```

FUNCTIONAL REQUIREMENTS:
━━━━━━━━━━━━━━━━━━━━━━━

  Customer-facing:
    F1. Create payment for an order (card, wallet, bank debit)
    F2. Support authorize → capture (two-step) and direct charge
    F3. Refund full or partial; idempotent per refund request
    F4. 3D Secure / SCA for EU cards (PSD2)
    F5. Store payment method for returning customers (tokenized)

  Merchant-facing:
    F6. Onboard merchant (KYC stub), attach bank account for payouts
    F7. Split payment: platform fee + merchant net
    F8. Payout on schedule (daily T+2) or on-demand
    F9. Dispute/chargeback workflow with evidence upload

  Platform-internal:
    F10. Double-entry ledger — every cent accounted
    F11. Reconcile PSP settlement files daily
    F12. Webhook delivery to merchant systems (payment.succeeded, etc.)
    F13. Admin: search payments, force refund, freeze merchant

NON-FUNCTIONAL REQUIREMENTS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  NFR1. Durability: no lost payments — 99.999% for ledger writes
  NFR2. Correctness > availability for money (CP on ledger partition)
  NFR3. Latency: p99 < 800ms for PaymentIntent create (excl. 3DS)
  NFR4. Idempotency: all mutating APIs safe to retry 24h
  NFR5. Audit: immutable journal, 7-year retention
  NFR6. PCI: SAQ A — card data never touches our servers
  NFR7. Compliance: PSD2 SCA, AML screening hooks for payouts

OUT OF SCOPE (say explicitly):
  → Building a card network / acquiring bank
  → Full subscription billing (mention Stripe Billing as extension)
  → In-house fraud ML (integrate Stripe Radar / Sardine)
  → Multi-PSP routing v1 (single PSP + abstraction layer)

### Step 2: Capacity Estimation

```
ASSUMPTIONS (marketplace, US-heavy):
  50M registered users, 5M DAU
  2% of DAU complete a purchase/day = 100K payments/day
  Peak (Black Friday): 20× average = 2M payments/day

THROUGHPUT:
  Average: 100K / 86400 ≈ 1.2 payments/sec
  Peak:    2M / 86400 ≈ 23 payments/sec sustained
           Minute burst (flash): ~200 payments/sec

  Rule of thumb: design for 10× peak = 2,000 payments/sec
  (PSP handles card rails; we handle API + ledger)

STORAGE (10-year retention):
  Payment record: ~2 KB (metadata, state history, idempotency)
  Ledger entries: ~500 B × 4 entries per payment (fee splits)
  100K/day × 365 × 10 × 2.5 KB ≈ 900 GB payments + ledger
  → RDS Postgres with partitioning by month; archive to S3 after 2 years

BANDWIDTH:
  API mostly small JSON; webhook fan-out dominates egress
  100K webhooks/day × 5 KB × 3 retries ≈ 1.5 GB/day (negligible)

MONEY AT RISK (why correctness matters):
  Avg order $85 → peak minute 200 × $85 = $17,000/sec gross
  0.01% duplicate charge rate at peak = $1.70/sec customer harm
  → idempotency is not optional
```

### Step 3: High-Level Architecture

```
                         ┌─────────────────────────────────────────┐
                         │           CLIENT APPLICATIONS           │
                         │  Web (Stripe.js)  │  Mobile (SDK)       │
                         └─────────┬───────────────────┬───────────┘
                                   │ HTTPS              │
                                   ▼                    ▼
                         ┌─────────────────────────────────────────┐
                         │  API Gateway + WAF + Rate Limiter       │
                         │  (AWS API Gateway or ALB + AWS WAF)     │
                         └─────────┬───────────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Payment API     │    │ Merchant API    │    │ Webhook Ingress │
│ (ECS Fargate)   │    │ (ECS Fargate)   │    │ (Lambda)        │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  ▼
                    ┌─────────────────────────────┐
                    │   Payment Orchestrator      │
                    │   (Step Functions Standard) │
                    │   CheckoutSaga per order    │
                    └─────────────┬───────────────┘
                                  │
    ┌──────────────┬──────────────┼──────────────┬──────────────┐
    ▼              ▼              ▼              ▼              ▼
┌────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│ Ledger │  │ Idempotency│ │ PSP      │  │ Payout   │  │ Webhook  │
│ Service│  │ Store      │ │ Adapter  │  │ Service  │  │ Delivery │
│        │  │ (DynamoDB) │ │ (Stripe) │  │          │  │ (SQS)    │
└───┬────┘  └──────────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
    │                            │             │             │
    ▼                            ▼             ▼             ▼
┌──────────────┐          ┌──────────┐  ┌──────────┐  ┌──────────┐
│ RDS Postgres │          │ Stripe   │  │ Bank     │  │ Merchant │
│ ledger_*     │          │ API      │  │ (ACH)    │  │ endpoints│
│ (multi-AZ)   │          │          │  │ via PSP  │  │          │
└──────────────┘          └──────────┘  └──────────┘  └──────────┘

DATA FLOW — HAPPY PATH (physical goods checkout):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Client loads Stripe.js → card tokenized in browser (PCI SAQ A)
  2. POST /v1/payment_intents { amount, currency, payment_method_token,
     idempotency_key, metadata.order_id }
  3. Payment API:
       a. Check idempotency store (DynamoDB conditional write)
       b. Insert ledger PENDING entries (double-entry)
       c. Start CheckoutSaga (Step Functions)
  4. Saga steps (Week 6 orchestration):
       ReserveInventory → AuthorizePayment → CreateOrder →
       CapturePayment → ConfirmFulfillment → COMPLETED
  5. PSP webhook payment_intent.succeeded → Webhook Ingress
       → verify signature → idempotent handler → ledger POSTED
  6. Webhook Delivery queue → merchant URL with HMAC signature

WHY STEP FUNCTIONS FOR CHECKOUT SAGA:
  → Money + inventory = need visible saga state (Week 6 lesson)
  → Choreography across 5 services = grep hell in incidents
  → Standard workflow gives exactly-once state transitions per execution
  → Built-in timeout → triggers compensation path

### Step 4: API Design (Stripe-Like)

Stripe's API is the industry reference. Copy these properties:

```
STRIPE API PROPERTIES WE EMULATE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Resource-oriented nouns (PaymentIntent, Refund, Payout)
  2. Idempotency-Key header on ALL POST that move money
  3. Idempotent replay returns SAME response body + HTTP 200
  4. Expandable objects (?expand[]=charges) reduce round trips
  5. Metadata map (key/value strings) for correlation IDs
  6. Version header (Stripe-Version) for backward compatibility
  7. Error shape: { error: { type, code, message, param } }
  8. Test mode vs live mode via API key prefix (sk_test_ / sk_live_)
```

IDEMPOTENCY KEY SEMANTICS:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  Header: Idempotency-Key: <client-generated UUID v4>

  Server behavior:
    1. First request: process normally, store { key → response_hash, body }
    2. Retry same key + same body hash: return stored response (200)
    3. Retry same key + DIFFERENT body: 409 idempotency_key_mismatch
    4. TTL: 24 hours (Stripe default); after TTL, key reusable

  Storage schema (DynamoDB table idempotency_keys):
    PK: idempotency_key
    SK: api_version (allows key reuse across API versions)
    request_hash: SHA256(canonical JSON body)
    response_status: 200
    response_body: compressed JSON (max 32 KB — truncate refs for large)
    created_at: TTL attribute (epoch + 86400)

  CRITICAL: idempotency store write MUST be in same transaction boundary
  as ledger insert OR use conditional write before PSP call:

    BEGIN ledger transaction
    INSERT idempotency record (conditional: not exists)
    INSERT journal entries (status=PENDING)
    COMMIT
    CALL PSP (if PSP succeeds but crash before response store →
              retry returns same PI id from ledger lookup by key)

ENDPOINT CATALOG:
━━━━━━━━━━━━━━━━━


```
POST /v1/payment_intents
  Purpose: Create PaymentIntent
  Notes:   Idempotency-Key required
  Body:    amount, currency, capture_method (automatic|manual), payment_method, metadata
```


```
GET /v1/payment_intents/{id}
  Purpose: Retrieve PaymentIntent
  Notes:   Read-only
  Body:    expands charges
```


```
POST /v1/payment_intents/{id}/confirm
  Purpose: Confirm (client-side 3DS)
  Notes:   Idempotency-Key
  Body:    payment_method, return_url
```


```
POST /v1/payment_intents/{id}/capture
  Purpose: Capture authorized funds
  Notes:   Idempotency-Key
  Body:    amount_to_capture (partial OK)
```


```
POST /v1/payment_intents/{id}/cancel
  Purpose: Cancel / void authorization
  Notes:   Idempotency-Key
  Body:
```


```
POST /v1/refunds
  Purpose: Create refund
  Notes:   Idempotency-Key
  Body:    payment_intent, amount, reason
```


```
GET /v1/refunds/{id}
  Purpose: Retrieve refund
  Notes:
  Body:
```


```
POST /v1/payouts
  Purpose: Create merchant payout
  Notes:   Idempotency-Key
  Body:    merchant_id, amount
```


```
GET /v1/balance_transactions
  Purpose: Ledger-facing history
  Notes:   Paginated
  Body:    merchant_id, created
```


```
POST /v1/webhook_endpoints
  Purpose: Register merchant webhook
  Notes:
  Body:    url, events[]
```


PAYMENTINTENT STATE MACHINE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
                    ┌──────────────┐
                    │   created    │
                    └───────┬──────┘
                            │   confirm()
                            ▼
                ┌────────────────────────┐
                │    requires_action     │  (3DS challenge)
                └────────────┬───────────┘
                             │   3DS complete
                             ▼
                ┌────────────────────────┐
                │       processing       │
                └────────────┬───────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
        cancel()          success           fail
            │                │                │
            ▼                ▼                ▼
      ┌──────────┐   ┌──────────────┐ ┌──────────────┐
      │ canceled │   │  succeeded   │ │    failed    │
      └──────────┘   └───────┬──────┘ └──────────────┘
                             │   capture() [if manual]
                             ▼

              (funds captured — terminal)

  capture_method=automatic: succeeded implies captured
  capture_method=manual: succeeded = authorized only until capture
```

State transitions are APPEND-ONLY in payment_intent_events table.
Never UPDATE status in place without event row.

### Step 5: Double-Entry Ledger

The ledger is the **source of financial truth**. Orders, PaymentIntents, and
PSP dashboards are views. Finance, auditors, and regulators ask the ledger.

```
DOUBLE-ENTRY INVARIANT (non-negotiable):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ∀ journal_entry: SUM(debits) = SUM(credits)
  ∀ account: balance = SUM(credits) - SUM(debits)  [per normal balance sign]

  No UPDATE on journal_lines — INSERT only.
  Corrections = reversing entries (new journal), never DELETE.
```

CHART OF ACCOUNTS (starter):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  platform_cash          Asset      PSP settlement account — money we hold
  merchant_payable       Liability  Owed to merchants before payout
  platform_revenue       Revenue    Platform fees earned
  psp_fees               Expense    Interchange + PSP processing fees
  customer_receivable    Asset      Authorized but not captured (rare)
  refund_reserve         Liability  Expected refund liability
  chargeback_loss        Expense    Lost disputes
  suspense               Asset/Liability Unmatched reconciliation items


JOURNAL ENTRY — CUSTOMER PAYS $100, PLATFORM FEE 10%, PSP FEE $2.90:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Customer charged: $100.00 (gross)
  PSP fee:           $2.90 (2.9% + $0.30)
  Platform fee:     $10.00 (10% of gross)
  Merchant net:     $87.10

  Entry JE-88421 (payment captured):
  ┌─────────────────────┬──────────┬──────────┐
  │ Account             │ Debit    │ Credit   │
  ├─────────────────────┼──────────┼──────────┤
  │ platform_cash       │  $97.10  │          │  (net after PSP fee)
  │ psp_fees            │   $2.90  │          │
  │ merchant_payable    │          │  $87.10  │
  │ platform_revenue    │          │  $10.00  │
  │ customer_receivable │          │  $3.00   │  (timing: auth/capture gap)
  └─────────────────────┴──────────┴──────────┘
  Note: simplify for interview; real systems split auth/capture timing.

REFUND $30 PARTIAL:
  Entry JE-88422:
  ┌─────────────────────┬──────────┬──────────┐
  │ merchant_payable    │  $27.00  │          │  (merchant bears pro-rata)
  │ platform_revenue    │   $3.00  │          │  (fee reversed pro-rata)
  │ platform_cash       │          │  $30.00  │
  └─────────────────────┴──────────┴──────────┘

SCHEMA (Postgres, ledger schema):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  accounts (
    account_id UUID PK,
    account_code TEXT UNIQUE,
    account_type TEXT, -- ASSET, LIABILITY, REVENUE, EXPENSE
    currency CHAR(3),
    normal_balance TEXT -- DEBIT or CREDIT
  )

  journal_entries (
    entry_id UUID PK,
    idempotency_key TEXT UNIQUE,
    entry_type TEXT, -- PAYMENT_CAPTURE, REFUND, PAYOUT, ADJUSTMENT
    reference_type TEXT, -- payment_intent, refund, payout
    reference_id TEXT,
    created_at TIMESTAMPTZ,
    posted_at TIMESTAMPTZ,
    status TEXT -- PENDING, POSTED, REVERSED
  )

  journal_lines (
    line_id UUID PK,
    entry_id UUID FK,
    account_id UUID FK,
    debit_amount NUMERIC(20,4),
    credit_amount NUMERIC(20,4),
    currency CHAR(3)
  )

  CONSTRAINT: per entry_id, SUM(debit) = SUM(credit) checked by trigger

BALANCE QUERIES:
  Materialized view account_balances refreshed every 60s for reads.
  Real-time payout eligibility uses SERIALIZABLE transaction on merchant_payable.

WHY NOT EVENT SOURCING ONLY:
  Event sourcing is great for PaymentIntent state. Ledger needs SQL constraints
  for debit=credit. Use both: events for workflow, ledger for money.


EXAMPLE TRANSACTION PATTERN #1:
  Scenario: authorize for order ORD-10001
  Idempotency key: pi_create_10001
  Ledger entries created atomically with PSP callback correlation_id=evt_1
  Reconciliation tag: settlement_batch_2026-07-02


EXAMPLE TRANSACTION PATTERN #2:
  Scenario: refund for order ORD-10002
  Idempotency key: pi_create_10002
  Ledger entries created atomically with PSP callback correlation_id=evt_2
  Reconciliation tag: settlement_batch_2026-07-03


EXAMPLE TRANSACTION PATTERN #3:
  Scenario: capture for order ORD-10003
  Idempotency key: pi_create_10003
  Ledger entries created atomically with PSP callback correlation_id=evt_3
  Reconciliation tag: settlement_batch_2026-07-04


EXAMPLE TRANSACTION PATTERN #4:
  Scenario: authorize for order ORD-10004
  Idempotency key: pi_create_10004
  Ledger entries created atomically with PSP callback correlation_id=evt_4
  Reconciliation tag: settlement_batch_2026-07-05


EXAMPLE TRANSACTION PATTERN #5:
  Scenario: refund for order ORD-10005
  Idempotency key: pi_create_10005
  Ledger entries created atomically with PSP callback correlation_id=evt_5
  Reconciliation tag: settlement_batch_2026-07-06


EXAMPLE TRANSACTION PATTERN #6:
  Scenario: capture for order ORD-10006
  Idempotency key: pi_create_10006
  Ledger entries created atomically with PSP callback correlation_id=evt_6
  Reconciliation tag: settlement_batch_2026-07-07


EXAMPLE TRANSACTION PATTERN #7:
  Scenario: authorize for order ORD-10007
  Idempotency key: pi_create_10007
  Ledger entries created atomically with PSP callback correlation_id=evt_7
  Reconciliation tag: settlement_batch_2026-07-08


EXAMPLE TRANSACTION PATTERN #8:
  Scenario: refund for order ORD-10008
  Idempotency key: pi_create_10008
  Ledger entries created atomically with PSP callback correlation_id=evt_8
  Reconciliation tag: settlement_batch_2026-07-09


EXAMPLE TRANSACTION PATTERN #9:
  Scenario: capture for order ORD-10009
  Idempotency key: pi_create_10009
  Ledger entries created atomically with PSP callback correlation_id=evt_9
  Reconciliation tag: settlement_batch_2026-07-10


EXAMPLE TRANSACTION PATTERN #10:
  Scenario: authorize for order ORD-10010
  Idempotency key: pi_create_10010
  Ledger entries created atomically with PSP callback correlation_id=evt_10
  Reconciliation tag: settlement_batch_2026-07-11


EXAMPLE TRANSACTION PATTERN #11:
  Scenario: refund for order ORD-10011
  Idempotency key: pi_create_10011
  Ledger entries created atomically with PSP callback correlation_id=evt_11
  Reconciliation tag: settlement_batch_2026-07-12


EXAMPLE TRANSACTION PATTERN #12:
  Scenario: capture for order ORD-10012
  Idempotency key: pi_create_10012
  Ledger entries created atomically with PSP callback correlation_id=evt_12
  Reconciliation tag: settlement_batch_2026-07-13


EXAMPLE TRANSACTION PATTERN #13:
  Scenario: authorize for order ORD-10013
  Idempotency key: pi_create_10013
  Ledger entries created atomically with PSP callback correlation_id=evt_13
  Reconciliation tag: settlement_batch_2026-07-14


EXAMPLE TRANSACTION PATTERN #14:
  Scenario: refund for order ORD-10014
  Idempotency key: pi_create_10014
  Ledger entries created atomically with PSP callback correlation_id=evt_14
  Reconciliation tag: settlement_batch_2026-07-15


EXAMPLE TRANSACTION PATTERN #15:
  Scenario: capture for order ORD-10015
  Idempotency key: pi_create_10015
  Ledger entries created atomically with PSP callback correlation_id=evt_15
  Reconciliation tag: settlement_batch_2026-07-16


EXAMPLE TRANSACTION PATTERN #16:
  Scenario: authorize for order ORD-10016
  Idempotency key: pi_create_10016
  Ledger entries created atomically with PSP callback correlation_id=evt_16
  Reconciliation tag: settlement_batch_2026-07-17


EXAMPLE TRANSACTION PATTERN #17:
  Scenario: refund for order ORD-10017
  Idempotency key: pi_create_10017
  Ledger entries created atomically with PSP callback correlation_id=evt_17
  Reconciliation tag: settlement_batch_2026-07-18


EXAMPLE TRANSACTION PATTERN #18:
  Scenario: capture for order ORD-10018
  Idempotency key: pi_create_10018
  Ledger entries created atomically with PSP callback correlation_id=evt_18
  Reconciliation tag: settlement_batch_2026-07-19


EXAMPLE TRANSACTION PATTERN #19:
  Scenario: authorize for order ORD-10019
  Idempotency key: pi_create_10019
  Ledger entries created atomically with PSP callback correlation_id=evt_19
  Reconciliation tag: settlement_batch_2026-07-20


EXAMPLE TRANSACTION PATTERN #20:
  Scenario: refund for order ORD-10020
  Idempotency key: pi_create_10020
  Ledger entries created atomically with PSP callback correlation_id=evt_20
  Reconciliation tag: settlement_batch_2026-07-21

### Step 6: PCI DSS Scope Reduction

```
PCI DSS 4.0 — WHAT MATTERS FOR OUR DESIGN:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Cardholder Data (CHD): PAN, cardholder name, expiration, service code
  Sensitive Auth Data (SAD): CVV/CVC, full track data, PIN — NEVER STORE

  SAQ A (simplest): card data handled entirely by PCI-validated third party
  (Stripe Elements / Checkout). Your servers only receive tokens (pm_xxx).

ARCHITECTURE FOR SAQ A:
━━━━━━━━━━━━━━━━━━━━━━━

  Browser → Stripe.js (hosted iframe) → Stripe vault
                ↓
           payment_method token (pm_1abc...)
                ↓
  Your API ← token only, NEVER PAN

  Network segmentation:
    Payment API tier: no SSH from internet, no admin browsing
    Logging: scrub pm_ tokens from debug logs (still sensitive)
    WAF: block request bodies matching PAN regex (Luhn-valid 13-19 digits)

  SAQ A ELIGIBILITY DESTROYERS (never do these):
    ✗ Logging request bodies on /confirm endpoint
    ✗ Storing PAN encrypted "for convenience"
    ✗ Support rep asks customer to read card number over phone into ticket
    ✗ Mobile app embeds WebView that you control with card form (SAQ A-EP)

  3D SECURE / SCA:
    Stripe handles 3DS redirect/challenge UI
    Your return_url: https://shop.example.com/checkout/3ds-return
    State: store payment_intent_id in session; verify on return

TOKEN LIFECYCLE:
  pm_xxx single-use or attached to Customer cus_xxx for repeat
  Attach requires CVC re-collection for MIT (merchant-initiated transactions)

COMPLIANCE HOOKS (mention in interview):
  AML/KYC: merchant onboarding collects EIN, beneficial owners (stub)
  PSD2: SCA required EEA cards; exemptions for low value / TRA
  Chargeback limits: monitor dispute rate < 0.9% (Visa VDMP)
```

### Step 7: Checkout Saga (Week 6 Integration)

Physical-goods checkout is the canonical saga from Week 6 Saga Pattern.
Use **orchestration** (Step Functions), not choreography — money paths
need a single pane of glass.

```
SAGA: CheckoutSaga (Step Functions Standard)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Input: { orderId, cartId, paymentIntentId, idempotencyKey, merchantId }

  Compensation rule (Week 6): compensate in REVERSE order of successful steps.
  Each compensation must be idempotent (compensation_id = sagaId + stepName).
```


STEP 1: ReserveInventory
  Service:      InventorySvc
  Forward:      Reserve stock 15min TTL
  Compensation: ReleaseReservation
  Notes:        HTTP 409 insufficient → FAIL saga, no payment attempted


STEP 2: AuthorizePayment
  Service:      PSP Adapter
  Forward:      PaymentIntent confirm, manual capture
  Compensation: VoidAuthorization
  Notes:        Timeout → ReconcilePayment (GET PI status) before void


STEP 3: CreateOrder
  Service:      OrderSvc
  Forward:      Persist order PENDING
  Compensation: CancelOrder
  Notes:        Duplicate order_id → idempotent return existing


STEP 4: CapturePayment
  Service:      PSP Adapter
  Forward:      Capture PI up to authorized amount
  Compensation: RefundCapture
  Notes:        Partial capture if partial ship (extension)


STEP 5: EmitEvents
  Service:      Outbox→MSK
  Forward:      order.placed, payment.captured
  Compensation: EmitCompensationEvents
  Notes:        At-least-once; consumers idempotent


SAGA STATE (DynamoDB checkout_sagas):
  PK: saga_id (order_id)
  status: RUNNING | COMPLETED | COMPENSATING | FAILED
  current_step, completed_steps[], compensation_log[]
  TTL on RUNNING > 1 hour → alert (not auto-delete)

TIMEOUT SEMANTICS (lesson from Week 6 incident):
  NEVER set HTTP client timeout < PSP p99 without reconciliation step.
  Pattern: on timeout → Reconcile{Step} (GET status) → branch success/fail
  Do NOT compensate until reconcile proves forward step failed.

PHANTOM CHARGE PREVENTION:
  AuthorizePayment timeout + actual success = classic bug.
  Fix: ReconcilePayment polls GET /v1/payment_intents/{id}
  If status=succeeded or requires_capture → do NOT void; continue saga.
  If status=processing > 60s → wait with heartbeat.
  If status=canceled/failed → compensate inventory.

STEP FUNCTIONS DEFINITION (abbreviated):
  States:
    ReserveInventory → AuthorizePayment → ReconcileAuth →
    CreateOrder → CapturePayment → ReconcileCapture → Completed
  Catch blocks route to Compensate* states in reverse order.
  HeartbeatSeconds on Task states calling external APIs.

### Step 8: Webhooks and Reconciliation

```
INBOUND (from Stripe / PSP):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  POST /webhooks/stripe
  Headers: Stripe-Signature: t=timestamp,v1=hmac

  Verification:
    signed_payload = timestamp + "." + raw_body
    expected = HMAC-SHA256(webhook_secret, signed_payload)
    Compare v1 to expected; reject if timestamp > 5 min old (replay)

  Handler idempotency:
    event_id (evt_xxx) stored in processed_webhook_events (DynamoDB TTL 30d)
    Conditional write; duplicate → 200 OK immediately

  Processing:
    Map event type → ledger posting command
    Use same journal entry idempotency_key = "webhook:" + event_id

OUTBOUND (to merchants):
━━━━━━━━━━━━━━━━━━━━━━━

  SQS queue webhook_delivery { merchant_id, event_payload, attempt }
  Exponential backoff: 1m, 5m, 30m, 2h, 24h (max 5 days)
  Sign with merchant-specific secret: X-Signature-SHA256
  Disable endpoint after 7 days consecutive failures

RECONCILIATION (daily, non-negotiable):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Download PSP settlement report (CSV) for T+1
  2. Match rows to journal_entries by payment_intent_id + amount
  3. Unmatched → suspense account; alert if > 0.01% of volume
  4. Sum(platform_cash) ≈ PSP balance API (within timing window)

  Reconciliation job: AWS Batch or Lambda scheduled 06:00 UTC
  Output: reconciliation_runs table + Slack summary

  DRIFT EXAMPLE:
    Webhook missed → ledger shows PENDING, PSP shows captured
    Nightly reconcile backfills POSTED entry from settlement file

  Event handler: payment_intent.succeeded → ledger posting rule documented in runbook section payment_intent

  Event handler: payment_intent.payment_failed → ledger posting rule documented in runbook section payment_intent

  Event handler: payment_intent.canceled → ledger posting rule documented in runbook section payment_intent

  Event handler: charge.refunded → ledger posting rule documented in runbook section charge

  Event handler: charge.dispute.created → ledger posting rule documented in runbook section charge

  Event handler: payout.paid → ledger posting rule documented in runbook section payout

  Event handler: payout.failed → ledger posting rule documented in runbook section payout

  Event handler: account.updated → ledger posting rule documented in runbook section account

---

## Concrete Examples


### Example 1: AWS Deployment — Payment API on ECS Fargate

```
VPC: 10.0.0.0/16
  Public subnets: ALB only
  Private subnets: ECS tasks, RDS, DynamoDB gateway endpoint

ALB: payment-api.example.com
  Listener 443 → TG payment-api-fargate (health: GET /health)
  WAF ACL: AWSManagedRulesCommonRuleSet + custom PAN block rule

ECS service payment-api:
  Task: 1 vCPU, 2 GB, min 6 / max 40 tasks
  Auto-scale: target tracking CPU 60%, request count 1000/task
  Env: STRIPE_SECRET_ARN (Secrets Manager), LEDGER_DB_URL, IDEMPOTENCY_TABLE

RDS Postgres ledger (db.r6g.xlarge Multi-AZ):
  database: ledger
  schemas: accounts, journal_entries, journal_lines, payment_intents
  Partition journal_entries by RANGE (created_at) monthly
  RPO: 5 min (PITR), RTO: 30 min (failover)

DynamoDB idempotency_keys: on-demand, TTL enabled
DynamoDB checkout_sagas: on-demand, PITR enabled

Step Functions: CheckoutSaga
  Logging: ALL → CloudWatch, X-Ray enabled
  IAM: least privilege per Lambda worker

CloudWatch alarms:
  payment_api_5xx_rate > 0.1% for 5 min → P2
  ledger_posting_lag_seconds p99 > 30 → P1
  reconciliation_unmatched_count > 10 → P2
```

### Example 2: Idempotent PaymentIntent Create (Pseudocode)

```python
def create_payment_intent(req, idempotency_key):
    body_hash = sha256(canonical_json(req))

    # Fast path: existing idempotency record
    rec = idempotency_store.get(idempotency_key)
    if rec:
        if rec.request_hash != body_hash:
            raise IdempotencyMismatch()
        return rec.stored_response

    with ledger_db.transaction(isolation='SERIALIZABLE'):
        # Correlation: same key may already have PI from partial failure
        existing = payment_intents.find_by_idempotency_key(idempotency_key)
        if existing:
            response = serialize(existing)
        else:
            pi = payment_intents.insert(PENDING, req)
            ledger.post_pending_payment(pi)  # double-entry PENDING
            stripe_pi = stripe.PaymentIntent.create(
                amount=req.amount,
                currency=req.currency,
                capture_method=req.capture_method,
                idempotency_key=idempotency_key,  # forward to PSP
            )
            payment_intents.attach_psp_id(pi.id, stripe_pi.id)
            response = serialize(pi)

        idempotency_store.put_if_absent(
            idempotency_key, body_hash, response, ttl_hours=24
        )
        return response
```

### Example 3: Stripe Connect Split (Marketplace)

```
Customer pays $100 → PaymentIntent on platform account
  transfer_data[destination] = merchant_connected_account_id
  application_fee_amount = 1000  ($10.00 platform fee)

Stripe automatically:
  Charges customer $100
  Transfers $90 to connected account (minus Stripe fees on connected)
  Platform keeps $10 application fee

Ledger must still record all splits — Stripe dashboard ≠ your books.
```

---

## Production Patterns


PATTERN 1: Ledger-first webhook processing
  Context: Payment platform at scale — pattern 1 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-001; on-call rotation owns verification.
  Metric: payment_pattern_1_violation_total should remain 0; alert on increment.


PATTERN 2: PSP timeout reconciliation
  Context: Payment platform at scale — pattern 2 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-002; on-call rotation owns verification.
  Metric: payment_pattern_2_violation_total should remain 0; alert on increment.


PATTERN 3: Outbox for merchant webhooks
  Context: Payment platform at scale — pattern 3 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-003; on-call rotation owns verification.
  Metric: payment_pattern_3_violation_total should remain 0; alert on increment.


PATTERN 4: Production hardening pattern #4
  Context: Payment platform at scale — pattern 4 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-004; on-call rotation owns verification.
  Metric: payment_pattern_4_violation_total should remain 0; alert on increment.


PATTERN 5: Production hardening pattern #5
  Context: Payment platform at scale — pattern 5 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-005; on-call rotation owns verification.
  Metric: payment_pattern_5_violation_total should remain 0; alert on increment.


PATTERN 6: Production hardening pattern #6
  Context: Payment platform at scale — pattern 6 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-006; on-call rotation owns verification.
  Metric: payment_pattern_6_violation_total should remain 0; alert on increment.


PATTERN 7: Production hardening pattern #7
  Context: Payment platform at scale — pattern 7 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-007; on-call rotation owns verification.
  Metric: payment_pattern_7_violation_total should remain 0; alert on increment.


PATTERN 8: Production hardening pattern #8
  Context: Payment platform at scale — pattern 8 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-008; on-call rotation owns verification.
  Metric: payment_pattern_8_violation_total should remain 0; alert on increment.


PATTERN 9: Production hardening pattern #9
  Context: Payment platform at scale — pattern 9 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-009; on-call rotation owns verification.
  Metric: payment_pattern_9_violation_total should remain 0; alert on increment.


PATTERN 10: Production hardening pattern #10
  Context: Payment platform at scale — pattern 10 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-010; on-call rotation owns verification.
  Metric: payment_pattern_10_violation_total should remain 0; alert on increment.


PATTERN 11: Production hardening pattern #11
  Context: Payment platform at scale — pattern 11 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-011; on-call rotation owns verification.
  Metric: payment_pattern_11_violation_total should remain 0; alert on increment.


PATTERN 12: Production hardening pattern #12
  Context: Payment platform at scale — pattern 12 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-012; on-call rotation owns verification.
  Metric: payment_pattern_12_violation_total should remain 0; alert on increment.


PATTERN 13: Production hardening pattern #13
  Context: Payment platform at scale — pattern 13 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-013; on-call rotation owns verification.
  Metric: payment_pattern_13_violation_total should remain 0; alert on increment.


PATTERN 14: Production hardening pattern #14
  Context: Payment platform at scale — pattern 14 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-014; on-call rotation owns verification.
  Metric: payment_pattern_14_violation_total should remain 0; alert on increment.


PATTERN 15: Production hardening pattern #15
  Context: Payment platform at scale — pattern 15 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-015; on-call rotation owns verification.
  Metric: payment_pattern_15_violation_total should remain 0; alert on increment.


PATTERN 16: Production hardening pattern #16
  Context: Payment platform at scale — pattern 16 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-016; on-call rotation owns verification.
  Metric: payment_pattern_16_violation_total should remain 0; alert on increment.


PATTERN 17: Production hardening pattern #17
  Context: Payment platform at scale — pattern 17 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-017; on-call rotation owns verification.
  Metric: payment_pattern_17_violation_total should remain 0; alert on increment.


PATTERN 18: Production hardening pattern #18
  Context: Payment platform at scale — pattern 18 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-018; on-call rotation owns verification.
  Metric: payment_pattern_18_violation_total should remain 0; alert on increment.


PATTERN 19: Production hardening pattern #19
  Context: Payment platform at scale — pattern 19 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-019; on-call rotation owns verification.
  Metric: payment_pattern_19_violation_total should remain 0; alert on increment.


PATTERN 20: Production hardening pattern #20
  Context: Payment platform at scale — pattern 20 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-020; on-call rotation owns verification.
  Metric: payment_pattern_20_violation_total should remain 0; alert on increment.


PATTERN 21: Production hardening pattern #21
  Context: Payment platform at scale — pattern 21 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-021; on-call rotation owns verification.
  Metric: payment_pattern_21_violation_total should remain 0; alert on increment.


PATTERN 22: Production hardening pattern #22
  Context: Payment platform at scale — pattern 22 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-022; on-call rotation owns verification.
  Metric: payment_pattern_22_violation_total should remain 0; alert on increment.


PATTERN 23: Production hardening pattern #23
  Context: Payment platform at scale — pattern 23 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-023; on-call rotation owns verification.
  Metric: payment_pattern_23_violation_total should remain 0; alert on increment.


PATTERN 24: Production hardening pattern #24
  Context: Payment platform at scale — pattern 24 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-024; on-call rotation owns verification.
  Metric: payment_pattern_24_violation_total should remain 0; alert on increment.


PATTERN 25: Production hardening pattern #25
  Context: Payment platform at scale — pattern 25 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-025; on-call rotation owns verification.
  Metric: payment_pattern_25_violation_total should remain 0; alert on increment.


PATTERN 26: Production hardening pattern #26
  Context: Payment platform at scale — pattern 26 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-026; on-call rotation owns verification.
  Metric: payment_pattern_26_violation_total should remain 0; alert on increment.


PATTERN 27: Production hardening pattern #27
  Context: Payment platform at scale — pattern 27 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-027; on-call rotation owns verification.
  Metric: payment_pattern_27_violation_total should remain 0; alert on increment.


PATTERN 28: Production hardening pattern #28
  Context: Payment platform at scale — pattern 28 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-028; on-call rotation owns verification.
  Metric: payment_pattern_28_violation_total should remain 0; alert on increment.


PATTERN 29: Production hardening pattern #29
  Context: Payment platform at scale — pattern 29 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-029; on-call rotation owns verification.
  Metric: payment_pattern_29_violation_total should remain 0; alert on increment.


PATTERN 30: Production hardening pattern #30
  Context: Payment platform at scale — pattern 30 documents a shipped invariant.
  Implementation: Documented in runbook PAY-RB-030; on-call rotation owns verification.
  Metric: payment_pattern_30_violation_total should remain 0; alert on increment.

### Pattern: Exactly-Once Ledger Posting

```
PROBLEM: Webhook delivered twice + handler retried = double posting.

SOLUTION:
  idempotency_key = "webhook:" + evt_id (PSP event ID, globally unique)
  journal_entries UNIQUE constraint on idempotency_key
  INSERT ... ON CONFLICT DO NOTHING RETURNING entry_id
  If no row returned → already processed → skip

This is separate from API idempotency but same principle.
```

### Pattern: Dead Letter Queue for Failed Captures

```
Capture succeeds at PSP, ledger POST fails (DB blip):
  Message on capture_completion_queue retries with exponential backoff
  After 10 failures → DLQ capture_dlq
  P1 alert: manual verify PSP vs ledger, backfill journal entry
  NEVER auto-refund from DLQ without human — might double-refund
```

#### Deep Dive 1: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0001
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0001_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0001
  If failure at step 2: compensate steps 1..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0001

SRE note:
  Monitor payment_edge_1_failure_total; runbook PAY-EDGE-0001
```


#### Deep Dive 2: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0002
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0002_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0002
  If failure at step 3: compensate steps 2..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0002

SRE note:
  Monitor payment_edge_2_failure_total; runbook PAY-EDGE-0002
```


#### Deep Dive 3: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0003
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0003_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0003
  If failure at step 4: compensate steps 3..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0003

SRE note:
  Monitor payment_edge_3_failure_total; runbook PAY-EDGE-0003
```


#### Deep Dive 4: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0004
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0004_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0004
  If failure at step 5: compensate steps 4..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0004

SRE note:
  Monitor payment_edge_4_failure_total; runbook PAY-EDGE-0004
```


#### Deep Dive 5: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0005
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0005_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0005
  If failure at step 1: compensate steps 0..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0005

SRE note:
  Monitor payment_edge_5_failure_total; runbook PAY-EDGE-0005
```


#### Deep Dive 6: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0006
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0006_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0006
  If failure at step 2: compensate steps 1..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0006

SRE note:
  Monitor payment_edge_6_failure_total; runbook PAY-EDGE-0006
```


#### Deep Dive 7: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0007
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0007_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0007
  If failure at step 3: compensate steps 2..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0007

SRE note:
  Monitor payment_edge_7_failure_total; runbook PAY-EDGE-0007
```


#### Deep Dive 8: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0008
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0008_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0008
  If failure at step 4: compensate steps 3..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0008

SRE note:
  Monitor payment_edge_8_failure_total; runbook PAY-EDGE-0008
```


#### Deep Dive 9: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0009
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0009_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0009
  If failure at step 5: compensate steps 4..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0009

SRE note:
  Monitor payment_edge_9_failure_total; runbook PAY-EDGE-0009
```


#### Deep Dive 10: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0010
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0010_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0010
  If failure at step 1: compensate steps 0..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0010

SRE note:
  Monitor payment_edge_10_failure_total; runbook PAY-EDGE-0010
```


#### Deep Dive 11: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0011
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0011_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0011
  If failure at step 2: compensate steps 1..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0011

SRE note:
  Monitor payment_edge_11_failure_total; runbook PAY-EDGE-0011
```


#### Deep Dive 12: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0012
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0012_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0012
  If failure at step 3: compensate steps 2..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0012

SRE note:
  Monitor payment_edge_12_failure_total; runbook PAY-EDGE-0012
```


#### Deep Dive 13: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0013
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0013_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0013
  If failure at step 4: compensate steps 3..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0013

SRE note:
  Monitor payment_edge_13_failure_total; runbook PAY-EDGE-0013
```


#### Deep Dive 14: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0014
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0014_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0014
  If failure at step 5: compensate steps 4..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0014

SRE note:
  Monitor payment_edge_14_failure_total; runbook PAY-EDGE-0014
```


#### Deep Dive 15: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0015
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0015_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0015
  If failure at step 1: compensate steps 0..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0015

SRE note:
  Monitor payment_edge_15_failure_total; runbook PAY-EDGE-0015
```


#### Deep Dive 16: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0016
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0016_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0016
  If failure at step 2: compensate steps 1..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0016

SRE note:
  Monitor payment_edge_16_failure_total; runbook PAY-EDGE-0016
```


#### Deep Dive 17: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0017
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0017_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0017
  If failure at step 3: compensate steps 2..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0017

SRE note:
  Monitor payment_edge_17_failure_total; runbook PAY-EDGE-0017
```


#### Deep Dive 18: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0018
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0018_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0018
  If failure at step 4: compensate steps 3..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0018

SRE note:
  Monitor payment_edge_18_failure_total; runbook PAY-EDGE-0018
```


#### Deep Dive 19: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0019
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0019_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0019
  If failure at step 5: compensate steps 4..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0019

SRE note:
  Monitor payment_edge_19_failure_total; runbook PAY-EDGE-0019
```


#### Deep Dive 20: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0020
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0020_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0020
  If failure at step 1: compensate steps 0..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0020

SRE note:
  Monitor payment_edge_20_failure_total; runbook PAY-EDGE-0020
```


#### Deep Dive 21: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0021
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0021_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0021
  If failure at step 2: compensate steps 1..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0021

SRE note:
  Monitor payment_edge_21_failure_total; runbook PAY-EDGE-0021
```


#### Deep Dive 22: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0022
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0022_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0022
  If failure at step 3: compensate steps 2..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0022

SRE note:
  Monitor payment_edge_22_failure_total; runbook PAY-EDGE-0022
```


#### Deep Dive 23: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0023
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0023_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0023
  If failure at step 4: compensate steps 3..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0023

SRE note:
  Monitor payment_edge_23_failure_total; runbook PAY-EDGE-0023
```


#### Deep Dive 24: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0024
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0024_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0024
  If failure at step 5: compensate steps 4..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0024

SRE note:
  Monitor payment_edge_24_failure_total; runbook PAY-EDGE-0024
```


#### Deep Dive 25: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0025
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0025_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0025
  If failure at step 1: compensate steps 0..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0025

SRE note:
  Monitor payment_edge_25_failure_total; runbook PAY-EDGE-0025
```


#### Deep Dive 26: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0026
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0026_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0026
  If failure at step 2: compensate steps 1..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0026

SRE note:
  Monitor payment_edge_26_failure_total; runbook PAY-EDGE-0026
```


#### Deep Dive 27: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0027
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0027_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0027
  If failure at step 3: compensate steps 2..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0027

SRE note:
  Monitor payment_edge_27_failure_total; runbook PAY-EDGE-0027
```


#### Deep Dive 28: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0028
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0028_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0028
  If failure at step 4: compensate steps 3..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0028

SRE note:
  Monitor payment_edge_28_failure_total; runbook PAY-EDGE-0028
```


#### Deep Dive 29: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0029
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0029_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0029
  If failure at step 5: compensate steps 4..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0029

SRE note:
  Monitor payment_edge_29_failure_total; runbook PAY-EDGE-0029
```


#### Deep Dive 30: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0030
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0030_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0030
  If failure at step 1: compensate steps 0..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0030

SRE note:
  Monitor payment_edge_30_failure_total; runbook PAY-EDGE-0030
```


#### Deep Dive 31: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0031
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0031_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0031
  If failure at step 2: compensate steps 1..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0031

SRE note:
  Monitor payment_edge_31_failure_total; runbook PAY-EDGE-0031
```


#### Deep Dive 32: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0032
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0032_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0032
  If failure at step 3: compensate steps 2..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0032

SRE note:
  Monitor payment_edge_32_failure_total; runbook PAY-EDGE-0032
```


#### Deep Dive 33: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0033
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0033_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0033
  If failure at step 4: compensate steps 3..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0033

SRE note:
  Monitor payment_edge_33_failure_total; runbook PAY-EDGE-0033
```


#### Deep Dive 34: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0034
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0034_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0034
  If failure at step 5: compensate steps 4..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0034

SRE note:
  Monitor payment_edge_34_failure_total; runbook PAY-EDGE-0034
```


#### Deep Dive 35: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0035
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0035_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0035
  If failure at step 1: compensate steps 0..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0035

SRE note:
  Monitor payment_edge_35_failure_total; runbook PAY-EDGE-0035
```


#### Deep Dive 36: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0036
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0036_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0036
  If failure at step 2: compensate steps 1..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0036

SRE note:
  Monitor payment_edge_36_failure_total; runbook PAY-EDGE-0036
```


#### Deep Dive 37: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0037
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0037_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0037
  If failure at step 3: compensate steps 2..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0037

SRE note:
  Monitor payment_edge_37_failure_total; runbook PAY-EDGE-0037
```


#### Deep Dive 38: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0038
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0038_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0038
  If failure at step 4: compensate steps 3..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0038

SRE note:
  Monitor payment_edge_38_failure_total; runbook PAY-EDGE-0038
```


#### Deep Dive 39: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0039
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0039_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0039
  If failure at step 5: compensate steps 4..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0039

SRE note:
  Monitor payment_edge_39_failure_total; runbook PAY-EDGE-0039
```


#### Deep Dive 40: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0040
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0040_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0040
  If failure at step 1: compensate steps 0..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0040

SRE note:
  Monitor payment_edge_40_failure_total; runbook PAY-EDGE-0040
```


#### Deep Dive 41: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0041
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0041_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0041
  If failure at step 2: compensate steps 1..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0041

SRE note:
  Monitor payment_edge_41_failure_total; runbook PAY-EDGE-0041
```


#### Deep Dive 42: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0042
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0042_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0042
  If failure at step 3: compensate steps 2..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0042

SRE note:
  Monitor payment_edge_42_failure_total; runbook PAY-EDGE-0042
```


#### Deep Dive 43: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0043
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0043_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0043
  If failure at step 4: compensate steps 3..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0043

SRE note:
  Monitor payment_edge_43_failure_total; runbook PAY-EDGE-0043
```


#### Deep Dive 44: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0044
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0044_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0044
  If failure at step 5: compensate steps 4..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0044

SRE note:
  Monitor payment_edge_44_failure_total; runbook PAY-EDGE-0044
```


#### Deep Dive 45: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0045
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0045_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0045
  If failure at step 1: compensate steps 0..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0045

SRE note:
  Monitor payment_edge_45_failure_total; runbook PAY-EDGE-0045
```


#### Deep Dive 46: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0046
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0046_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0046
  If failure at step 2: compensate steps 1..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0046

SRE note:
  Monitor payment_edge_46_failure_total; runbook PAY-EDGE-0046
```


#### Deep Dive 47: Payment Edge Case — Payout

```
Scenario ID: PAY-EDGE-0047
Description: Production-grade walkthrough of ACH settlement
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: PAYOUT
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0047_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0047
  If failure at step 3: compensate steps 2..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0047

SRE note:
  Monitor payment_edge_47_failure_total; runbook PAY-EDGE-0047
```


#### Deep Dive 48: Payment Edge Case — Authorization

```
Scenario ID: PAY-EDGE-0048
Description: Production-grade walkthrough of void timing
  for marketplace merchant tier premium.

Ledger impact:
  Journal entry type: AUTH_HOLD
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0048_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0048
  If failure at step 4: compensate steps 3..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0048

SRE note:
  Monitor payment_edge_48_failure_total; runbook PAY-EDGE-0048
```


#### Deep Dive 49: Payment Edge Case — Capture

```
Scenario ID: PAY-EDGE-0049
Description: Production-grade walkthrough of partial capture
  for marketplace merchant tier standard.

Ledger impact:
  Journal entry type: CAPTURE
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0049_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0049
  If failure at step 5: compensate steps 4..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0049

SRE note:
  Monitor payment_edge_49_failure_total; runbook PAY-EDGE-0049
```


#### Deep Dive 50: Payment Edge Case — Refund

```
Scenario ID: PAY-EDGE-0050
Description: Production-grade walkthrough of chargeback
  for marketplace merchant tier new.

Ledger impact:
  Journal entry type: REFUND
  Accounts touched: platform_cash, merchant_payable, platform_revenue, psp_fees
  Idempotency key: edge_0050_{operation}

Saga interaction:
  Step Functions execution: checkout-edge-0050
  If failure at step 1: compensate steps 0..1 in order
  Reconcile endpoint: GET /internal/reconcile/pay-edge-0050

SRE note:
  Monitor payment_edge_50_failure_total; runbook PAY-EDGE-0050
```

---

## Failure Modes


Production payment failures — each entry is a class of incident seen at
Stripe-scale companies and marketplaces.



```
FAILURE: Phantom charge
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Symptom:  Auth succeeded, saga marked FAILED, user not notified
Root cause: Missing ReconcilePayment after timeout
Fix:      Reconcile before compensate; fix user messaging
Detection: metric or reconciliation rule specific to Phantom charge
```


```
FAILURE: Double capture
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Symptom:  Retry with NEW idempotency key
Root cause: Client SDK bug
Fix:      SDK must reuse key; server dedupe by payment_intent_id + amount
Detection: metric or reconciliation rule specific to Double capture
```


```
FAILURE: Ledger drift
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Symptom:  PSP balance ≠ platform_cash account
Root cause: Missed webhooks
Fix:      Nightly settlement reconciliation; suspense account
Detection: metric or reconciliation rule specific to Ledger drift
```


```
FAILURE: Stuck 3DS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Symptom:  requires_action forever
Root cause: User abandoned challenge
Fix:      PI auto-cancel after 1h; release inventory reservation
Detection: metric or reconciliation rule specific to Stuck 3DS
```


```
FAILURE: Payout double-send
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Symptom:  Payout worker retried
Root cause: No idempotency on payout
Fix:      Payout idempotency_key = payout_batch_id + merchant_id
Detection: metric or reconciliation rule specific to Payout double-send
```


```
FAILURE: Chargeback after payout
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Symptom:  Merchant already paid out
Root cause: Dispute opened day 45
Fix:      Negative balance on merchant_payable; clawback next payout
Detection: metric or reconciliation rule specific to Chargeback after payout
```


```
FAILURE: Refund exceeds capture
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Symptom:  Partial capture math wrong
Root cause: Race partial ship
Fix:      Refundable amount = captured - sum(refunds); DB constraint
Detection: metric or reconciliation rule specific to Refund exceeds capture
```


```
FAILURE: SAQ scope breach
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Symptom:  PAN in application logs
Root cause: Debug logging left on
Fix:      Scrub logs; incident response; re-assess SAQ level
Detection: metric or reconciliation rule specific to SAQ scope breach
```


```
FAILURE: Webhook replay attack
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Symptom:  Old signed webhook resent
Root cause: No timestamp check
Fix:      Reject Stripe-Signature if t > 5 min skew
Detection: metric or reconciliation rule specific to Webhook replay attack
```


```
FAILURE: Currency mismatch
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Symptom:  USD ledger entry for EUR charge
Root cause: FX not modeled
Fix:      Separate ledger accounts per currency; no implicit conversion
Detection: metric or reconciliation rule specific to Currency mismatch
```


```
FAILURE CLASS #11: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 2 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #12: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 3 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #13: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 4 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #14: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 5 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #15: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 1 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #16: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 2 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #17: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 3 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #18: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 4 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #19: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 5 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #20: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 1 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #21: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 2 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #22: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 3 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #23: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 4 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #24: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 5 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #25: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 1 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #26: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 2 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #27: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 3 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #28: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 4 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #29: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 5 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #30: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 1 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #31: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 2 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #32: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 3 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #33: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 4 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #34: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 5 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #35: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 1 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #36: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 2 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #37: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 3 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #38: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 4 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #39: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 5 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```


```
FAILURE CLASS #40: Edge case in payment orchestration
Symptom:  Anomaly detected in saga step 1 with elevated timeout rate
Root cause: Partner API degradation or deploy regression (see Week 6 saga incident)
Fix:      Reconcile-before-compensate; rollback client timeout; enable circuit breaker
```

---

## SRE Diagnostic Toolkit


### Metrics (Prometheus / CloudWatch)

```
# API
payment_api_requests_total{method, path, status}
payment_api_latency_seconds{path} histogram

# Money correctness
ledger_posting_lag_seconds (time from PSP success to POSTED)
reconciliation_unmatched_total
phantom_charge_total (saga FAILED but PI succeeded — MUST be 0)
double_capture_attempts_total

# Idempotency
idempotency_replay_total (expected on retries)
idempotency_mismatch_total (409 — investigate client bugs)

# Saga (Week 6)
checkout_saga_started_total
checkout_saga_completed_total{status}
checkout_saga_stuck_count (RUNNING > 15 min)
checkout_saga_step_duration_seconds{step}

# PSP
psp_request_duration_seconds{operation}
psp_webhook_processing_lag_seconds
psp_webhook_duplicate_total
```

### Logs (structured JSON)

```json
{
  "level": "info",
  "msg": "payment_intent_created",
  "payment_intent_id": "pi_internal_abc",
  "psp_payment_intent_id": "pi_3NxYz",
  "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
  "amount": 10000,
  "currency": "usd",
  "merchant_id": "mer_123",
  "saga_id": "ord_998877",
  "trace_id": "abc123"
}
```

NEVER log: full card numbers, CVV, raw Stripe secret keys.

### Commands

```bash
# Check stuck sagas
aws stepfunctions list-executions --state-machine-arn $SF_ARN --status-filter RUNNING

# Query phantom charges (last hour)
psql $LEDGER_URL -c "
  SELECT pi.id, pi.psp_id, s.status AS saga_status
  FROM payment_intents pi
  JOIN checkout_sagas s ON s.order_id = pi.metadata->>'order_id'
  WHERE pi.psp_status = 'succeeded'
    AND s.status IN ('FAILED','COMPENSATING')
    AND pi.created_at > now() - interval '1 hour';"

# Reconcile unmatched
psql $LEDGER_URL -c "
  SELECT count(*) FROM reconciliation_items
  WHERE status = 'UNMATCHED' AND run_date = CURRENT_DATE;"

# Stripe CLI webhook test
stripe listen --forward-to localhost:8080/webhooks/stripe
stripe trigger payment_intent.succeeded
```

### Dashboards

Panel 1: Payments/sec + error rate (stacked by error code)
Panel 2: Ledger posting lag heatmap
Panel 3: Saga funnel (started → completed / failed / stuck)
Panel 4: Reconciliation unmatched (7-day trend)
Panel 5: PSP latency p50/p99 by operation

---

## Decision Framework


```
PAYMENT ARCHITECTURE DECISIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌────────────────────────┬──────────────────────┬─────────────────────┐
│ Decision               │ Choose A when        │ Choose B when       │
├────────────────────────┼──────────────────────┼─────────────────────┤
│ Build vs buy PSP       │ Need full control,   │ Default: Stripe/    │
│                        │ own acquiring        │ Adyen — ship faster │
├────────────────────────┼──────────────────────┼─────────────────────┤
│ Auth+capture vs charge │ Physical goods,      │ Digital instant     │
│                        │ inventory risk       │ delivery            │
├────────────────────────┼──────────────────────┼─────────────────────┤
│ Saga orchestration     │ Money + 3+ steps     │ Single PSP call only│
│ (Step Functions)       │                      │ (rare)              │
├────────────────────────┼──────────────────────┼─────────────────────┤
│ Ledger DB              │ Postgres SERIALIZABLE│ Event store only    │
│                        │ finance queries      │ (insufficient)      │
├────────────────────────┼──────────────────────┼─────────────────────┤
│ Idempotency store      │ DynamoDB TTL         │ Postgres (if low    │
│                        │ high write scale     │ scale monolith)     │
└────────────────────────┴──────────────────────┴─────────────────────┘

WHEN TO ADD MULTI-PSP:
  Single PSP OK until: >$50M GMV, geographic gaps, or negotiation leverage.
  Abstraction: PaymentProvider interface { authorize, capture, refund, webhook }
  Route by: card BIN country, merchant preference, failover on PSP 5xx.
```

---

## Incident Scenario


```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1 (REVENUE + TRUST + REGULATORY)
Service: PayFlow Marketplace Payment Platform
Time: 14:32 EST Tuesday (post-lunch checkout peak)

ARCHITECTURE:
  ALB → Payment API (ECS 24 tasks) → Step Functions CheckoutSaga
  PSP: Stripe PaymentIntents (manual capture)
  Ledger: RDS Postgres Multi-AZ
  Idempotency: DynamoDB
  Deploy: 11:45 AM — payment-api v3.8.2 "reduce latency"
    change: Stripe HTTP client timeout 25s → 5s

SYMPTOMS (14:32):
  P1: phantom_charge_total = 7 (threshold 0)
  P1: checkout_saga_completed{FAILED} +340% vs same hour yesterday
  P2: payment_api_latency p99 down (misleading — failures fast)
  Support: 23 tickets "charged but order cancelled"
  Stripe dashboard: 41 PaymentIntents succeeded (requires_capture)
    in last 20 min where internal admin shows saga FAILED

SAMPLE BAD CASE — order_7712:
  14:28:01 ReserveInventory OK
  14:28:03 AuthorizePayment Task timed out at 5s
  14:28:03 ReconcileAuth SKIPPED (bug: v3.8.2 removed reconcile on auth path)
  14:28:04 CompensateInventory OK
  14:28:05 Saga FAILED
  Stripe: pi_8xx succeeded, status requires_capture, $189.00 at 14:28:06
  User UI: "Payment failed — you were not charged"

  14:31:00 User retries → NEW order_7713 → second authorization $189
  Stripe: two authorized PIs for same cart (different idempotency keys)

ADDITIONAL:
  14:35 Engineer runs script: "void all FAILED saga PIs from last hour"
  Script voids 18 PIs — 3 were actually CAPTURED 2 min earlier by retry worker
  Finance: 3 customers need manual refund + apology

METRICS:
  authorize_payment_timeout_rate: 28% (Stripe p99 was 6.1s)
  reconcile_auth_skipped: 100% (feature flag accidentally off)
  ledger_entries PENDING: +412 unmatched POSTED

YOUR ROLE: Principal engineer joins bridge 14:40.
```

### Question 1: Causal chain for order_7712

Trace deploy → timeout → skipped reconcile → false user message → retry double auth.
What is root cause vs amplifying? What must stop immediately?

### Question 2: Remediate order_7712

Exact steps: Stripe PI state, inventory, saga log, ledger, customer comms.
Include Stripe CLI commands and SQL. What do you verify before messaging user?

### Question 3: Stop bleeding in 15 minutes

Config rollbacks, feature flags, circuit breakers — exact values.

### Question 4: Detection gaps

What alert fires at 12:00 when Stripe latency elevated but before phantom charges?

### Question 5: Long-term fixes

Architecture + process: reconcile mandatory, timeout policy, deploy checklist,
user-facing payment state source of truth, script guardrails.

---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**
> [`../answers/Week-11-Commerce-and-Payments-Designs/Design Payment System Answers.md`](../answers/Week-11-Commerce-and-Payments-Designs/Design Payment System Answers.md)

## Key Takeaways

```
╔══════════════════════════════════════════════════════════════╗
║ IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:               ║
║                                                              ║
║ 1. LEDGER FIRST. Every money movement is double-entry.       ║
║    UI state follows ledger; never the reverse.               ║
║                                                              ║
║ 2. IDEMPOTENCY AT EVERY BOUNDARY. API, webhooks, saga steps. ║
║                                                              ║
║ 3. AUTH/CAPTURE SPLIT for physical goods.                    ║
║                                                              ║
║ 4. PCI SCOPE IS ARCHITECTURE. Tokenization = SAQ A.          ║
║                                                              ║
║ 5. RECONCILE DAILY. Ledger vs PSP settlement files.          ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading


```
REQUIRED:
  1. Stripe API — Idempotent requests
     https://stripe.com/docs/api/idempotent_requests
     → Exact key semantics and 24h window

  2. Stripe — PaymentIntents lifecycle
     https://stripe.com/docs/payments/paymentintents/lifecycle
     → Auth/capture states for interview drawing

  3. PCI SSC — SAQ A eligibility
     https://www.pcisecuritystandards.org/document_library
     → Know what keeps you out of full PCI audit

  4. Week 6 curriculum — Saga Pattern.md
     → Reconcile-before-compensate; phantom charge incident

  5. Designing Data-Intensive Applications (Kleppmann) Ch. 11
     → Stream processing for ledger; exactly-once semantics

OPTIONAL:
  6. Adyen Payment lifecycle docs (multi-PSP comparison)
  7. Square double-entry ledger engineering blog (2019)
```

---

## Design Gates (mandatory)

Answer these before calling the design complete. Keep responses concise in the
learner notes; compare against the answer key only after attempting the gates.

> Gate template: [`../templates/DESIGN_MODULE_GATES.md`](../templates/DESIGN_MODULE_GATES.md)
> Model responses: [`../answers/Week-11-Commerce-and-Payments-Designs/Design Payment System Answers.md`](../answers/Week-11-Commerce-and-Payments-Designs/Design%20Payment%20System%20Answers.md)

### Gate 1 - Authn/z trust boundary

1. Who is authenticated in this design: end user, admin, service, device, worker, tenant, or partner?
2. Where does the first untrusted request cross into your trusted control plane?
3. Which component makes the final authorization decision for each protected object or action?
4. What identity artifact is accepted: session cookie, bearer token, API key, mTLS SPIFFE ID, signed URL, or job identity?
5. What does the system do when the identity provider, policy store, or trust bundle is unavailable?

### Gate 2 - Abuse and misuse

6. Which actor can generate the largest write amplification or fan-out?
7. Which endpoint or background job can be abused while still authenticated?
8. What per-user, per-tenant, per-key, per-IP, per-region, and global quotas are required?
9. What telemetry distinguishes a legitimate flash crowd from abuse or scraping?
10. Which retry policy could amplify a partial outage into a full outage?

### Gate 3 - Multi-tenant isolation, if multi-tenant

11. What is the tenancy model for API, database, cache, queue/topic, search/index, and object storage?
12. Where is tenant context required, and how is it propagated through async jobs and support tools?
13. Which shared resource has reserved capacity or fair-share limits per tenant or tier?
14. How can one tenant be throttled, disabled, migrated, or isolated without affecting others?
15. What test proves a tenant cannot read another tenant's data through cache, search, export, or logs?

### Gate 4 - Unit cost at target scale

16. What is the business unit for cost: request, message, ride, order, document, query, minute, or tenant?
17. At the stated target scale and peak multiplier, what is the rough unit cost?
18. Which line items dominate: compute, storage, replication, egress, NAT, observability, ML inference, third-party APIs, or idle headroom?
19. What cost metric pages before margin, budget, or SLO error budget is breached?
20. What graceful degradation lowers cost without damaging the correctness-critical path?

### Gate 5 - Failure blast radius

21. What is the smallest unit that can fail independently: partition, shard, cell, topic, region, tenant, cache key, model, worker pool, or queue?
22. Which dependencies are shared between critical and non-critical paths?
23. What fails closed, what serves stale, and what can be disabled first?
24. Which runbook action could accidentally widen blast radius?
25. What game day proves the blast radius stays inside the intended boundary?
