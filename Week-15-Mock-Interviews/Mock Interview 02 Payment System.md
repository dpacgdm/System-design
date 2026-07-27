> **Run under** [`00-Curriculum/TIMED_INTERVIEW_OS.md`](../00-Curriculum/TIMED_INTERVIEW_OS.md). Communication scorecard hard gate applies. Use ≥2 interrupts.

# Mock Interview 02 — Design a Payment System

> **Format:** 45-minute timed mock interview
> **Level:** L5–L6 (Senior / Staff)
> **Prerequisites:** Week 6 (Saga Pattern, Outbox Pattern), Week 4 (Replication), Interview Rubric.md
> **Use this module as:** Interviewer script, self-practice guide, or peer mock with scoring worksheet

---

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════╗
║   AFTER THIS MOCK INTERVIEW, YOU WILL BE ABLE TO:                ║
╟──────────────────────────────────────────────────────────────────╢
║                                                                  ║
║   1. Run or complete a 45-minute payment system interview        ║
║      with correct pacing across all 8 rubric dimensions          ║
║                                                                  ║
║   2. Design for exactly-once money movement at 50K TPS           ║
║      using idempotency keys, double-entry ledger, and            ║
║      sagas — not hand-waved "ACID transactions"                  ║
║                                                                  ║
║   3. Articulate PCI scope boundaries: what touches card          ║
║      data, what stays in tokenized vault, and why that           ║
║      drives architecture                                         ║
║                                                                  ║
║   4. Explain reconciliation, outbox publishing, and              ║
║      settlement drift detection as first-class components        ║
║                                                                  ║
║   5. Score your answer (or a peer's) on the 8-dimension          ║
║      rubric and identify the single highest-leverage gap         ║
║                                                                  ║
║   6. Diagnose failure modes: duplicate charges, split            ║
║      brain, reconciliation drift — with detection and            ║
║      mitigation for each                                         ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Exactly-once = use a distributed transaction"    ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. 2PC across payment gateway, ledger, and merchant            ║
║   service does not exist at 50K TPS. Exactly-once is an              ║
║   EFFECT achieved via idempotency keys + ledger invariants +         ║
║   at-least-once delivery with deduplication.                         ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Store card numbers in our database"              ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Raw PAN in your DB expands PCI scope to your entire         ║
║   stack. Production systems tokenize at the edge (Stripe,            ║
║   Adyen vault) and store only tokens + last4 + expiry metadata.      ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Payment succeeded = money moved"                 ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Authorization ≠ capture ≠ settlement. A charge can          ║
║   be authorized, fail on capture, settle days later, or              ║
║   chargeback weeks later. The ledger tracks STATE TRANSITIONS,       ║
║   not a single boolean "paid."                                       ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Retries fix transient failures"                  ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG WITHOUT IDEMPOTENCY. Retrying a charge without an            ║
║   idempotency key IS the duplicate charge bug. Timeouts are          ║
║   ambiguous — the gateway may have charged while your client         ║
║   saw a timeout. Design for ambiguous outcomes explicitly.           ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Reconciliation is a finance team problem"        ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Engineering owns the reconciliation PIPELINE:               ║
║   daily settlement files, ledger vs processor diff, alerting         ║
║   on drift > $0.01. Without it, duplicate charges hide for           ║
║   months and split-brain writes compound silently.                   ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Saga = refund the whole flow on failure"         ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Payment sagas have asymmetric compensations: void           ║
║   authorization (instant) vs refund capture (3–5 days).              ║
║   Some steps are irreversible. Saga state must handle                ║
║   "compensation in progress" and manual intervention queues.         ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Mock Interview Setup

### Roles and Materials

```
INTERVIEWER NEEDS:
  → This document (Interviewer Script section)
  → Whiteboard / Excalidraw / shared doc
  → Interview Rubric.md scoring worksheet
  → Timer (visible to interviewer only)
  → Problem card (copy Problem Statement section to candidate)

CANDIDATE NEEDS:
  → Problem statement only (do NOT share script or expert answer)
  → Whiteboard tool
  → 45 uninterrupted minutes

OPTIONAL CONSTRAINT CARDS (inject if candidate is ahead):
  → "Add multi-currency support"
  → "Processor outage lasting 15 minutes — what degrades?"
  → "Regulatory requirement: 7-year immutable audit trail"
```

### Interview Flow Overview

```
╔══════════════════════════════════════════════════════════════════════╗
║   45-MINUTE SCHEDULE                                                 ║
╟──────────────────────────────────────────────────────────────────────╢
║   MIN  0–5  │ Requirements & scope clarification                     ║
║   MIN  5–10 │ Capacity estimation (QPS, storage, bandwidth)          ║
║   MIN 10–15 │ API design & data model                                ║
║   MIN 15–25 │ High-level architecture                                ║
║   MIN 25–40 │ Deep dive (interviewer picks: ledger, idempotency,     ║
║             │             sagas, or PCI boundary)                    ║
║   MIN 40–45 │ Failure modes, wrap-up, candidate questions            ║
╠══════════════════════════════════════════════════════════════════════╣
║   REDIRECT RULE: If candidate skips idempotency or ledger by         ║
║   minute 20, interviewer MUST probe: "What happens on retry?"        ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Level Calibration

```
L5 BAR:  Solid ledger + idempotency; 3 failure modes; math within 2×
L6 BAR:  Double-entry invariants; saga with compensation; PCI scope;
         reconciliation pipeline; cascade failure analysis
L7 BAR:  Cost model; multi-region active-active trade-offs; regulatory
         audit trail; references real incidents (Stripe idempotency, etc.)
```

---

## Problem Statement (Give to Candidate)

```
DESIGN A PAYMENT PROCESSING SYSTEM

Your company operates a marketplace. Merchants sell goods; buyers pay
via credit/debit cards and bank transfers. You must build the internal
payment platform that:

  → Accepts payment requests from merchant services
  → Routes to external payment processors (Stripe-like PSPs)
  → Maintains an authoritative ledger of all money movement
  → Supports refunds, partial refunds, and chargebacks
  → Provides payment status APIs for merchants and support teams

SCALE & CONSTRAINTS (stated by interviewer if not asked):

  → 50,000 payment transactions per second at peak
  → Exactly-once semantics for money movement (no duplicate charges)
  → 99.99% availability for the payment API (52 min downtime/year)
  → p99 authorization latency < 500ms
  → PCI DSS compliance required
  → Multi-region deployment (US + EU) with data residency for EU cards

OUT OF SCOPE (unless candidate has time):

  → Fraud ML models (assume third-party fraud API)
  → Merchant onboarding / KYC
  → FX trading / treasury optimization

Start by clarifying requirements. You have 45 minutes.
```

---

## Interviewer Script

### Phase 1: Opening (Minute 0–5)

```
SAY:
  "Design a payment processing system for our marketplace. I'll give
   you the basics — ask clarifying questions before you draw anything."

LISTEN FOR:
  → Payment types (auth/capture/settle/refund/chargeback)
  → Exactly-once vs at-least-once distinction
  → Read vs write ratio
  → Consistency requirements for ledger
  → PCI / card data handling question
  → Multi-region / data residency

IF CANDIDATE JUMPS TO DIAGRAM (before minute 3):
  "Hold on — what are the top 3 things this system must do perfectly?"
  "What's your consistency model for the ledger?"

IF CANDIDATE ASKS FEW QUESTIONS:
  "Are we optimizing for latency or correctness if they conflict?"
  "What happens if the same payment request arrives twice?"
```

### Phase 2: Estimation (Minute 5–10)

```
SAY (if candidate doesn't start math):
  "Can you estimate QPS and storage for the ledger?"

EXPECTED ANCHORS:
  → 50K TPS peak given — validate they use it, not re-derive from DAU
  → Read QPS: status checks ~5–10× writes = 250K–500K reads/sec
  → Ledger entry: ~200 bytes × 2 entries (double-entry) per payment
  → Daily volume: 50K × 86400 × 0.3 (peak factor adjustment) ≈ 1.3B/day
    OR simpler: 50K peak sustained 4 hours = 720M/day order of magnitude
  → Storage: 500M payments/day × 400 bytes × 365 × 7 years ≈ hundreds of TB
  → Bandwidth: API payloads ~1KB × 50K = 50 MB/sec ingress (modest)

PROBE:
  "What's the bottleneck at 50K writes/sec?"
  → Answer should mention: ledger DB write throughput, NOT network

IF MATH IS WAY OFF:
  Don't interrupt mid-calculation. At end: "Walk me through that again —
  50K TPS for 7 years is how much storage?"
```

### Phase 3: API & Data Model (Minute 10–15)

```
SAY (if APIs not defined by minute 12):
  "Define the core APIs — create payment, get status, refund."

PROBE QUESTIONS:
  "What fields are on the create payment request?"
  "Where does the idempotency key live — header or body?"
  "What's your payment state machine?"

EXPECTED:
  POST /v1/payments
    Headers: Idempotency-Key (required)
    Body: { merchant_id, amount, currency, payment_method_token,
            capture_method: "automatic" | "manual", metadata }

  GET /v1/payments/{payment_id}
    → status, amount, created_at, failure_code, processor_ref

  POST /v1/payments/{payment_id}/refunds
    Headers: Idempotency-Key
    Body: { amount, reason }

  States: CREATED → AUTHORIZED → CAPTURED → SETTLED
          CREATED → FAILED
          CAPTURED → REFUND_PENDING → REFUNDED
          SETTLED → DISPUTED → CHARGEBACK

IF CANDIDATE USES SINGLE BALANCE COLUMN:
  "How do you detect accounting errors? What invariant must always hold?"
  → Redirect to double-entry ledger
```

### Phase 4: High-Level Architecture (Minute 15–25)

```
SAY (at minute 15 if no architecture):
  "Draw the high-level architecture. Walk me through a payment request."

EXPECTED COMPONENTS:
  ┌──────────┐     ┌─────────────┐     ┌──────────────────┐
  │ Merchant │────▶│ API Gateway │────▶│ Payment Service  │
  │ Services │     │ + AuthN/Z   │     │ (stateless)      │
  └──────────┘     └─────────────┘     └────────┬─────────┘
                                                 │
                    ┌────────────────────────────┼────────────────────┐
                    ▼                            ▼                    ▼
             ┌─────────────┐            ┌──────────────┐      ┌─────────────┐
             │ Idempotency │            │ Ledger DB    │      │ Outbox →    │
             │ Store       │            │ (sharded)    │      │ Kafka       │
             │ (Redis/DB)  │            └──────────────┘      └──────┬──────┘
                    │                            │                    │
                    └────────────────────────────┼────────────────────┘
                                                 ▼
                                        ┌──────────────────┐
                                        │ PSP Adapter      │
                                        │ (Stripe/Adyen)   │
                                        └──────────────────┘

PROBE:
  "Why is the idempotency store separate from the ledger?"
  "Where does card data touch your system?"
  "Sync or async path to the processor?"

CONSTRAINT INJECTION (minute 20, if not struggling):
  "Processor latency spikes to 3 seconds — what happens to your 500ms p99?"
  → Expect: async acceptance pattern, 202 + webhook, or queue with timeout
```

### Phase 5: Deep Dive (Minute 25–40)

```
INTERVIEWER CHOOSES ONE TRACK (or follows candidate's strongest thread):

─────────────────────────────────────────────────────────────────────
TRACK A: IDEMPOTENCY (default if candidate hasn't covered deeply)
─────────────────────────────────────────────────────────────────────

SAY:
  "Walk me through exactly what happens when the same Idempotency-Key
   arrives twice — same body, different body, and after 24 hours."

EXPECTED FLOW:
  1. Client sends POST with Idempotency-Key: abc-123
  2. Payment service begins transaction:
     a. INSERT idempotency_record (key, request_hash, status=IN_PROGRESS)
        ON CONFLICT → return cached response if COMPLETED
     b. If IN_PROGRESS and started < 30s ago → 409 Conflict
     c. If IN_PROGRESS and stale → reclaim or return 409
  3. Write ledger entries + outbox in SAME DB transaction
  4. Call PSP with idempotency key forwarded
  5. Update idempotency_record with response, status=COMPLETED
  6. Commit

  Different body + same key → 422 Unprocessable (key reuse violation)
  PSP timeout → status UNKNOWN; reconciliation resolves

PROBE:
  "Client retries after timeout. PSP charged but you returned 504. Now what?"
  → Reconciliation job queries PSP by idempotency key / payment intent ID

─────────────────────────────────────────────────────────────────────
TRACK B: DOUBLE-ENTRY LEDGER
─────────────────────────────────────────────────────────────────────

SAY:
  "Explain your ledger schema. How do you guarantee no money is created
   or destroyed?"

EXPECTED:
  ledger_accounts:
    account_id, type (ASSET/LIABILITY/REVENUE), owner_id, currency

  ledger_entries:
    entry_id, transaction_id, account_id, amount (signed),
    currency, created_at, idempotency_key

  INVARIANT: SUM(amount) GROUP BY transaction_id = 0
  INVARIANT: SUM(amount) GROUP BY account_id = displayed balance

  Example payment of $100:
    DR  merchant_escrow     +100
    CR  platform_clearing   -100
    (on capture)
    DR  platform_clearing   +100
    CR  external_psp        -100

PROBE:
  "How do you shard the ledger at 50K TPS?"
  → Shard by account_id hash; avoid cross-shard transactions via
    per-merchant escrow accounts (all entries for one payment share
    transaction_id, may span accounts on same shard via merchant_id key)

  "How do you run a balance query?"
  → Materialized balance table updated synchronously OR async with
    version column; never SUM full history at read time

─────────────────────────────────────────────────────────────────────
TRACK C: SAGAS (refund / multi-step payment)
─────────────────────────────────────────────────────────────────────

SAY:
  "A refund requires: ledger debit, PSP refund API, merchant notification,
   and inventory restock. Walk me through failure at each step."

EXPECTED (orchestration saga):
  Step 1: Mark refund PENDING in ledger (hold funds)
  Step 2: Call PSP refund (idempotent)
  Step 3: On PSP success → finalize ledger, publish RefundCompleted
  Step 4: Inventory service consumes event

  Failure at Step 2: retry with backoff; after N failures → manual queue
  Failure at Step 3 after Step 2 succeeded: CRITICAL — reconciliation
    detects PSP refunded but ledger not updated; auto-repair job

  Compensation: void auth (instant) vs refund capture (async, irreversible)

PROBE:
  "Choreography or orchestration — why?"
  → Orchestration for money: centralized saga log, auditable, debuggable

─────────────────────────────────────────────────────────────────────
TRACK D: PCI SCOPE
─────────────────────────────────────────────────────────────────────

SAY:
  "Draw the PCI boundary. What runs in scope vs out of scope?"

EXPECTED:
  OUT OF SCOPE (goal):
    → Client → PSP JS SDK (Stripe Elements) → token returned
    → Your API receives pm_token_xxx only
    → Payment service never sees PAN

  IN SCOPE (minimal):
    → Token vault if self-hosted (usually avoided)
    → Logging pipeline (must scrub PAN from logs)
    → Support tools viewing last4 only

  Network segmentation: CDE (cardholder data environment) isolated
  SAQ A vs SAQ D depending on architecture
```

### Phase 6: Failure Modes & Wrap-Up (Minute 40–45)

```
SAY:
  "What breaks first in production? Name three failure modes."

IF CANDIDATE DOESN'T MENTION THESE, PROMPT ONE:
  → Duplicate charges
  → Split brain between regions
  → Reconciliation drift

SAY (minute 43):
  "Any questions for me?"

CLOSE:
  Do NOT reveal expert answer during interview. Save for debrief.
```

---

## Candidate Expectations

### By Phase — What "Meets Bar" Looks Like

```
REQUIREMENTS (min 0–5):
  ✓ Asks about auth/capture/settle lifecycle
  ✓ Confirms exactly-once for money movement
  ✓ Identifies PCI as architecture driver
  ✓ Scopes refunds/chargebacks (even if deferred implementation)
  ✓ States 99.99% availability and 500ms p99 as NFRs

ESTIMATION (min 5–10):
  ✓ Accepts 50K TPS; derives read QPS (~5×)
  ✓ Estimates ledger storage with retention (7 years)
  ✓ Identifies DB write throughput as bottleneck

API & DATA MODEL (min 10–15):
  ✓ Idempotency-Key on mutating endpoints
  ✓ Payment state machine with ≥5 states
  ✓ Double-entry or explicit "ledger entries" concept

ARCHITECTURE (min 15–25):
  ✓ Stateless payment service behind gateway
  ✓ Separate idempotency store
  ✓ Ledger as source of truth
  ✓ Async outbox for downstream events
  ✓ PSP adapter abstraction
  ✓ No raw card data in core path

DEEP DIVE (min 25–40):
  ✓ Idempotency: conflict handling, timeout ambiguity
  ✓ Ledger: DR/CR invariants, sharding strategy
  ✓ OR Saga: compensation asymmetry
  ✓ OR PCI: tokenization boundary

FAILURE MODES (min 40–45):
  ✓ Duplicate charge scenario + mitigation
  ✓ At least one multi-region or reconciliation failure
  ✓ Detection mechanism (metrics, alerts, reconciliation job)
```

### Red Flags (Score ≤2 on Dimension)

```
  ✗ "Use database transactions" with no idempotency for external calls
  ✗ Single balance column with no audit trail
  ✗ Store encrypted card numbers in application DB
  ✗ Retry PSP calls without idempotency key forwarding
  ✗ No reconciliation or "finance handles it"
  ✗ Synchronous 50K TPS to single PostgreSQL primary
  ✗ "Kafka gives exactly-once" without consumer idempotency
```

### Green Flags (Score 4 Signals)

```
  ✓ "Exactly-once is an effect, not a protocol"
  ✓ Draws PCI boundary before architecture
  ✓ Ledger invariant: sum of entries per transaction = 0
  ✓ Outbox pattern for payment events (not dual-write)
  ✓ Reconciliation as daily job with alerting on drift
  ✓ Distinguishes authorization, capture, settlement timelines
  ✓ Unknown state handling after PSP timeout
```

---

## Reference Architecture

### End-to-End Payment Flow

```
CREATE PAYMENT (happy path):

  1. Merchant Svc → POST /v1/payments
     Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000

  2. API Gateway: auth, rate limit (per merchant), validate schema

  3. Payment Service:
     ┌─────────────────────────────────────────────────────────────┐
     │ BEGIN TRANSACTION                                           │
     │   a. Upsert idempotency_keys (key, hash, status=IN_PROGRESS)│
     │   b. INSERT payments (payment_id, merchant_id, amount, ...) │
     │   c. INSERT ledger_entries (DR/CR pair, txn_id)             │
     │   d. INSERT outbox (event=PaymentCreated, payload)          │
     │ COMMIT                                                      │
     └─────────────────────────────────────────────────────────────┘

  4. Call PSP: POST /charges with Idempotency-Key forwarded

  5. PSP returns charge_id, status=authorized

  6. Payment Service:
     ┌─────────────────────────────────────────────────────────────┐
     │ BEGIN TRANSACTION                                           │
     │   a. UPDATE payments SET status=AUTHORIZED, psp_ref=...     │
     │   b. INSERT ledger_entries (capture entries if auto-capture)│
     │   c. INSERT outbox (event=PaymentAuthorized)                │
     │   d. UPDATE idempotency_keys SET status=COMPLETED, response │
     │ COMMIT                                                      │
     └─────────────────────────────────────────────────────────────┘

  7. Outbox publisher → Kafka → Merchant notification, analytics, fraud

  8. Return 201 { payment_id, status, ... } to merchant
```

### Component Diagram

```
                    ┌─────────────────────────────────────────────┐
                    │              MULTI-REGION EDGE              │
                    │  ┌─────────┐  ┌─────────┐  ┌─────────────┐  │
                    │  │ CDN/WAF │  │ API GW  │  │ Rate Limiter│  │
                    │  └────┬────┘  └────┬────┘  └──────┬──────┘  │
                    └───────┼────────────┼───────────────┼──────────┘
                            │            │               │
              ┌─────────────▼────────────▼───────────────▼─────────────┐
              │              PAYMENT SERVICE CLUSTER (stateless)       │
              │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
              │  │ Payment API  │  │ Refund API   │  │ Webhook Hdlr │  │
              │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
              └─────────┼─────────────────┼─────────────────┼──────────┘
                        │                 │                 │
         ┌──────────────┼─────────────────┼─────────────────┼──────────────┐
         │              ▼                 ▼                 ▼              │
         │  ┌─────────────────┐  ┌─────────────┐  ┌─────────────────┐    │
         │  │ Idempotency DB  │  │ LEDGER DB   │  │ Outbox Table    │    │
         │  │ (Redis Cluster  │  │ (Cockroach/ │  │ (same txn as    │    │
         │  │  + DB fallback) │  │  Spanner /  │  │  ledger)        │    │
         │  │                 │  │  sharded PG)│  └────────┬────────┘    │
         │  └─────────────────┘  └─────────────┘           │              │
         │         DATA PLANE (strong consistency per payment)           │
         └───────────────────────────────────────────────────┼──────────────┘
                                                             ▼
                                                    ┌─────────────────┐
                                                    │ Kafka / SQS     │
                                                    └────────┬────────┘
                                                             │
              ┌──────────────────────────────────────────────┼──────────────┐
              │                    ASYNC PLANE               ▼              │
              │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │
              │  │ Settlement   │  │ Reconciliation│  │ Merchant Event  │  │
              │  │ Worker       │  │ Job (daily)   │  │ Fanout          │  │
              │  └──────┬───────┘  └──────┬───────┘  └─────────────────┘  │
              └─────────┼─────────────────┼─────────────────────────────────┘
                        ▼                 ▼
              ┌─────────────────┐  ┌─────────────────┐
              │ PSP Adapter     │  │ Settlement Files│
              │ (Stripe/Adyen)  │  │ + Alerting      │
              └─────────────────┘  └─────────────────┘

PCI BOUNDARY (dashed):
  ╔═══════════════════════════════════════════════════════════════╗
  ║  Client browser → PSP hosted fields (Stripe.js) → token only  ║
  ║  Your Payment Service: tokens + metadata ONLY                 ║
  ╚═══════════════════════════════════════════════════════════════╝
```

### Ledger Schema (Production-Grade)

```
ledger_accounts
─────────────────────────────────────────────────────────
  account_id        UUID PK
  owner_type        ENUM (MERCHANT, PLATFORM, PSP, CUSTOMER)
  owner_id          UUID
  account_type      ENUM (ESCROW, CLEARING, REVENUE, FEE)
  currency          CHAR(3)
  balance_cached    BIGINT  -- cents, updated synchronously
  version           BIGINT  -- optimistic locking
  shard_key         INT     -- merchant_id hash mod N

ledger_entries (append-only, immutable)
─────────────────────────────────────────────────────────
  entry_id          UUID PK
  transaction_id    UUID    -- groups DR/CR pairs
  account_id        UUID FK
  amount            BIGINT  -- signed: positive=DR, negative=CR
  currency          CHAR(3)
  payment_id        UUID
  entry_type        ENUM (AUTH, CAPTURE, REFUND, FEE, CHARGEBACK)
  created_at        TIMESTAMPTZ
  idempotency_key   VARCHAR(255)

  INDEX (payment_id)
  INDEX (account_id, created_at DESC)
  UNIQUE (idempotency_key, entry_type)  -- prevent duplicate entries

INVARIANT (checked by DB constraint or reconciliation job):
  ∀ transaction_id: SUM(amount) = 0
```

### Idempotency Store Schema

```
idempotency_keys
─────────────────────────────────────────────────────────
  key               VARCHAR(255) PK  -- client-provided
  merchant_id       UUID
  request_hash      SHA256 of canonical request body
  status            ENUM (IN_PROGRESS, COMPLETED, FAILED)
  response_code     INT
  response_body     JSONB
  locked_until      TIMESTAMPTZ  -- for stale lock reclaim
  created_at        TIMESTAMPTZ
  expires_at        TIMESTAMPTZ  -- 24–72 hour retention

BEHAVIOR:
  Same key + same hash + COMPLETED  → return cached response (200/201)
  Same key + same hash + IN_PROGRESS → 409 Conflict (or wait)
  Same key + different hash           → 422 Unprocessable Entity
  Same key + stale IN_PROGRESS        → reclaim lock, reprocess
```

---

## Rubric Scoring — Payment System Specific

Use Interview Rubric.md 1–4 scale. Problem-specific calibration below.

### Dimension 1: Requirements & Scope

```
SCORE 4 INDICATORS (payment-specific):
  → Asks auth vs capture vs settlement timeline
  → Confirms exactly-once; distinguishes from at-least-once delivery
  → PCI scope question in first 5 minutes
  → EU data residency for card tokens
  → Defers fraud ML but includes chargeback state

SCORE 2 INDICATORS:
  → Treats payment as single "charge" boolean
  → No refund/chargeback scope discussion
  → Ignores 99.99% availability implication (multi-region, no SPOF)
```

### Dimension 2: Capacity Estimation

```
SCORE 4 INDICATORS:
  → Uses 50K TPS; derives 250K+ read QPS
  → Ledger storage: entries × size × retention (7 yr)
  → Identifies ledger write throughput as bottleneck
  → Shards needed: 50K writes / 5K per shard = ~10+ ledger shards

SCORE 2 INDICATORS:
  → No storage calculation
  → Assumes single DB handles 50K TPS without sharding discussion
```

### Dimension 3: API & Data Model

```
SCORE 4 INDICATORS:
  → Idempotency-Key on POST payments and POST refunds
  → Full state machine (≥6 states)
  → Double-entry ledger schema with invariants
  → payment_method_token not raw PAN

SCORE 2 INDICATORS:
  → No idempotency in API design
  → balance DECIMAL column on merchants table
```

### Dimension 4: High-Level Architecture

```
SCORE 4 INDICATORS:
  → PCI boundary shown (tokenization at PSP)
  → Outbox for events (not dual-write to Kafka)
  → Idempotency store + ledger + PSP adapter separated
  → Sync critical path bounded; async for notifications

SCORE 2 INDICATORS:
  → Monolith with "payment module"
  → Card data flows through application servers
```

### Dimension 5: Deep Dive

```
SCORE 4 INDICATORS (any one track to depth):
  IDEMPOTENCY: timeout ambiguity, PSP key forwarding, 409 vs cached 200
  LEDGER: DR/CR example, shard key, balance cache, invariant check
  SAGA: orchestration, asymmetric compensation, stuck saga detection
  PCI: SAQ level, CDE network isolation, log scrubbing

SCORE 2 INDICATORS:
  → "Database handles consistency"
  → Cannot explain double-entry on whiteboard
```

### Dimension 6: Trade-offs & Alternatives

```
SCORE 4 INDICATORS:
  → Sync vs async PSP call (latency vs simplicity)
  → Orchestration vs choreography for refunds
  → CockroachDB/Spanner vs sharded Postgres (global consistency cost)
  → Redis idempotency vs DB-only (speed vs durability trade-off)

SCORE 2 INDICATORS:
  → Single approach with no alternatives named
```

### Dimension 7: Failure Modes & Reliability

```
SCORE 4 INDICATORS:
  → Duplicate charge: idempotency failure scenario + fix
  → Split brain: multi-region write conflict + mitigation (single writer per payment or CRDT not applicable — use payment_id affinity)
  → Reconciliation drift: PSP file vs ledger diff + alert
  → PSP timeout unknown state + repair job
  → SLO: 99.99% with error budget reasoning

SCORE 2 INDICATORS:
  → "We retry" without duplicate risk analysis
```

### Dimension 8: Communication & Structure

```
SCORE 4 INDICATORS:
  → Requirements → math → API → architecture → deep dive progression
  → Checkpoints: "Does ledger approach make sense before PSP?"
  → Manages time; reaches deep dive by minute 30

SCORE 2 INDICATORS:
  → Silent diagram drawing 10+ minutes
  → Never reaches idempotency or ledger
```

### Scoring Worksheet

```
╔═════════════════════════════════════════════════════════════════════╗
║   MOCK INTERVIEW 02 — PAYMENT SYSTEM                                ║
╠═════════════════════════════════════════════════════════════════════╣
║   Candidate: _______________  Date: ___________                     ║
║   Interviewer: _____________  Duration: 45 min                      ║
╠═════════════════════════════════════════════════════════════════════╣
║   Dimension                    │ Score (1-4) │ Notes                ║
║   ─────────────────────────────┼─────────────┼──────────────────    ║
║   1. Requirements & Scope        │             │ PCI? exactly-once? ║
║   2. Capacity Estimation         │             │ 50K TPS, storage   ║
║   3. API & Data Model            │             │ idempotency, ledger║
║   4. High-Level Architecture     │             │ outbox, PSP adapter║
║   5. Deep Dive                   │             │ track: __________  ║
║   6. Trade-offs & Alternatives   │             │                    ║
║   7. Failure Modes & Reliability │             │ dup/split/drift    ║
║   8. Communication & Structure   │             │                    ║
║   ─────────────────────────────┼─────────────┼──────────────────    ║
║   TOTAL                          │    /32      │                    ║
╠═════════════════════════════════════════════════════════════════════╣
║   TOP STRENGTH: ___________________________________________         ║
║   TOP GAP:      ___________________________________________         ║
║   NEXT FOCUS:   ___________________________________________         ║
║   HIRE SIGNAL:  [ ] Strong Yes  [ ] Yes  [ ] Lean  [ ] No           ║
╚═════════════════════════════════════════════════════════════════════╝
```

---

> **Answer key (do not open until you attempt the Ops Sim / questions):**
> [`../answers/Week-15-Mock-Interviews/Mock Interview 02 Payment System Answers.md`](../answers/Week-15-Mock-Interviews/Mock%20Interview%2002%20Payment%20System%20Answers.md)

## Debrief Guide

### Interviewer Debrief Script (5–10 min post-interview)

```
1. ASK: "What would you change if you had 10 more minutes?"
   → Reveals self-awareness of gaps

2. REVEAL GAP (pick one based on their weakest dimension):
   → Missed idempotency: Walk through timeout scenario
   → Missed ledger: Show DR/CR example
   → Missed PCI: Draw tokenization boundary

3. SCORE: Share dimension scores (not total unless they want it)

4. ONE ACTION ITEM: "Next mock, lead with failure modes in minute 35"

5. POINT TO READING: Saga Pattern, Outbox Pattern modules
```

### Self-Debrief Checklist

```
[ ] Did I ask about exactly-once in the first 5 minutes?
[ ] Did I put Idempotency-Key on mutating APIs?
[ ] Did I draw double-entry ledger with sum=0 invariant?
[ ] Did I mention outbox (not dual-write)?
[ ] Did I handle PSP timeout as unknown state?
[ ] Did I name duplicate charge, split brain, reconciliation drift?
[ ] Did I reach deep dive before minute 30?
[ ] Score myself on all 8 dimensions honestly
```

---

## Key Takeaways

```
1. Exactly-once payments = idempotency keys + ledger invariants +
   reconciliation — not distributed transactions.

2. Double-entry ledger is non-negotiable for production payment systems;
   single balance columns cannot be audited.

3. PCI scope drives architecture: tokenize at PSP, never store PAN.

4. PSP timeouts create UNKNOWN state — design reconciliation to resolve,
   not blind retry.

5. Outbox pattern publishes payment events atomically with ledger writes.

6. Sagas for refunds have asymmetric compensations; orchestration +
   saga log beats choreography for money workflows.

7. Reconciliation is engineering ownership — daily diff against PSP
   settlement files with alerting on drift.

8. At 50K TPS, ledger sharding by merchant_id is the bottleneck —
   calculate shards, don't hand-wave "distributed database."
```

---

## Targeted Reading

```
CURRICULUM:
  → Week 6: Saga Pattern — compensation, orchestration, stuck sagas
  → Week 6: Outbox Pattern and CDC — atomic event publish
  → Week 4: Replication Strategies — sync vs async for ledger replicas
  → Interview Rubric.md — 8-dimension scoring

EXTERNAL:
  → Stripe Idempotency Keys documentation
  → DDIA Chapter 7 (Transactions) + Chapter 11 (Stream Processing)
  → "Payments Systems in the US" (Princeton / industry primers)
  → Square / Stripe engineering blogs on ledger design
  → PCI DSS SAQ A vs SAQ D — scope reduction via tokenization
```

---

## Appendix: Constraint Injection Cards

```
CARD A (minute 20): MULTI-CURRENCY
  "Merchants receive USD but buyer pays EUR. What changes?"
  → FX rate source, separate currency accounts in ledger, settlement in
    merchant currency, PSP handles FX or treasury service

CARD B (minute 25): PROCESSOR OUTAGE
  "Stripe is down for 15 minutes during Black Friday. What degrades?"
  → Queue payment requests (bounded queue + 503), fail open NOT option
    for money; circuit breaker; secondary PSP failover with routing rules

CARD C (minute 30): REGULATORY AUDIT
  "Auditor needs proof payment X was not duplicated. Show me."
  → idempotency_keys table + ledger_entries + PSP charge_id immutable trail

CARD D (minute 35): CHARGEBACK
  "Customer disputes charge 60 days later. Walk me through."
  → Webhook from PSP → ledger CHARGEBACK entries → merchant balance debit
    → notification → optional auto-evidence submission
```

---

## Appendix: Orchestration Saga State Machine (Refund)

```
                    ┌─────────────┐
                    │   START     │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
               ┌───│   PENDING   │─── timeout ──▶ MANUAL_REVIEW
               │   └──────┬──────┘
               │          ▼
               │   ┌─────────────┐
               │   │ LEDGER_HOLD │  (debit merchant escrow)
               │   └──────┬──────┘
               │          ▼
               │   ┌─────────────┐
               │   │  PSP_REFUND │
               │   └──────┬──────┘
               │     fail │ success
               │          ▼
               │   ┌─────────────┐
               │   │  FINALIZE   │  (ledger finalize + outbox event)
               │   └──────┬──────┘
               │          ▼
               │   ┌─────────────┐
               └──▶│  COMPLETED  │
                   └─────────────┘

  Compensation from PSP_REFUND fail:
    → Release ledger hold if PSP confirms no refund initiated
    → If PSP state unknown → reconciliation before release
```
