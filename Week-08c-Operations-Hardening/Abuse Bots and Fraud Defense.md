# Abuse Bots and Fraud Defense

Northstar Commerce now has enough moving parts that the
hard problems are not only algorithmic. Checkout,
inventory, seller analytics, auth, rate limits, feature
flags, CloudFront, MSK, Debezium CDC, PostgreSQL, Redis,
mobile clients, and support tools all preserve different
invariants. Operations hardening is the practice of making
changes, tests, defenses, and clients safe when those
invariants meet real traffic.

This Week 08c module sits between the mechanism weeks and
the large design weeks. It assumes the learner remembers
DNS, HTTP, caches, replication, queues, outbox, feature
flags, observability, SLOs, rate limits, auth, cost, and
tenancy. The goal is to force those pieces into rollout
and incident decisions instead of isolated flash cards.

Abuse is adversarial capacity planning. Credential
stuffing, scraping, card testing, refund fraud, cache
poisoning, and collusion are not edge cases; they are
users optimizing against your defenses. The system must
preserve availability for good customers, reject bad
actions, avoid cross-tenant harm, and keep evidence strong
enough for later decisions.

This module connects Week 07 rate limits with Week 08b
auth and multi-tenancy. Authentication proves something
about a caller. Rate limits allocate scarce resources.
Fraud controls judge risk over time. Abuse defense needs
all three, plus observability that does not leak private
data or explode cardinality.

## Learning objectives

### Foundation

> Staff is the mastery gate; Principal stretch is optional depth.


1. Classify credential stuffing, account takeover,
   scraping, card testing, refund abuse, cache poisoning,
   and collusion by mechanism.
2. Design limiter stacks that combine global, IP, ASN,
   device, account, tenant, endpoint, and risk-based
   dimensions.
3. Explain why authentication alone does not stop
   authenticated abuse or seller noisy-neighbor behavior.
4. Tie bot and fraud defense to OAuth audience, session
   risk, mTLS service identity, and support-tool
   authorization.
5. Recognize rate-limit bypass through distributed IPs,
   token rotation, endpoint cost mismatch, and shared
   burst buckets.
6. Protect caches, CDNs, and derived data from poisoning,
   personalization leaks, and adversarial cache-key
   explosion.
7. Detect card testing and payment fraud without turning
   every false positive into a checkout outage.
8. Model collusion and marketplace abuse as graph, timing,
   and economics problems rather than single-request
   validation.
9. Build evidence packs for abuse incidents: risk signals,
   limiter decisions, auth facts, affected tenants, and
   legal-safe logs.
10. Choose mitigations that degrade risky or optional
    paths while preserving legitimate buyer checkout and
    seller operations.

## Wrong mental models

| Wrong model | Correction | Why it hurts |
| --- | --- | --- |
| Bots are just high QPS | Many attacks are low-and-slow, distributed, authenticated, or economically optimized. | Simple global QPS limits miss the attack. |
| Login success means the user is legitimate | Valid credentials can be stolen, stuffed, phished, or automated. | Account takeover proceeds under correct passwords. |
| CAPTCHA fixes abuse | CAPTCHA is one friction tool; attackers route around it or outsource it. | The attack shifts to APIs or aged sessions. |
| IP limits are enough | Residential proxies, mobile carriers, NATs, and IPv6 rotation defeat IP-only logic. | Good users get blocked while attackers continue. |
| Rate limits are security only | Limits also protect capacity, tenant fairness, and downstream cost. | Card testing starves payment capacity. |
| Fraud systems can fail open for revenue | Some paths may degrade, but payment and account integrity cannot ignore risk. | Short-term conversion creates chargebacks and ATO. |
| Scraping is harmless reads | Scraping consumes CDN/origin capacity, leaks inventory strategy, and trains competitors. | Margins and availability suffer. |
| Cache poisoning is only web security | Wrong cache keys can poison prices, auth decisions, risk responses, or tenant content. | One attacker changes what many users see. |
| Collusion looks like one bad account | Collusion appears across accounts, devices, payments, graph edges, and timing. | Single-account rules miss coordinated abuse. |
| Block everything suspicious | Defense must manage false positives, appeals, and tiered friction. | Good buyers abandon checkout. |

## Core mechanism

### 1. Credential stuffing

Credential stuffing tests leaked username/password pairs
against Northstar login. The primary control is not a
single password check; it is a stack: breached-password
detection, MFA/risk step-up, device/session reputation,
IP/ASN velocity, account lockout without enumeration, and
safe refresh-token rotation.

- Slice by account, IP, ASN, device, and credential pair.
- Do not reveal whether username or password was wrong.
- Protect JWKS and auth control planes from miss storms.
- Step up risk instead of locking every victim account.
- Preserve evidence without storing raw passwords.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while credential stuffing changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while credential stuffing is active? | Name the Northstar owner for Credential stuffing: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls credential stuffing risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Credential stuffing. |
| Blast radius | Which slice sees credential stuffing first? | Compare cell, tenant tier, region, route, app version, and dependency for Credential stuffing. |
| Rollback | What rollback edge remains open for credential stuffing, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Credential stuffing. |

### 2. Scraping and inventory harvesting

Scrapers collect product, price, inventory, and seller
analytics data. They may mimic browsers, rotate IPs, and
exploit cacheable endpoints. Defense combines CDN rules,
signed URLs, bot signals, endpoint cost limits, response
shaping, and business-specific freshness controls.

- Separate public catalog from seller/private data.
- Use cache keys that include viewer class and variant.
- Throttle expensive search and pagination patterns.
- Watch origin miss ratio and unusual traversal depth.
- Avoid leaking anti-bot rules through error details.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while scraping and inventory harvesting changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while scraping and inventory harvesting is active? | Name the Northstar owner for Scraping and inventory harvesting: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls scraping and inventory harvesting risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Scraping and inventory harvesting. |
| Blast radius | Which slice sees scraping and inventory harvesting first? | Compare cell, tenant tier, region, route, app version, and dependency for Scraping and inventory harvesting. |
| Rollback | What rollback edge remains open for scraping and inventory harvesting, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Scraping and inventory harvesting. |

### 3. Card testing

Card testing submits many small payment attempts to
discover valid card details. It is a capacity attack on
payment, a fraud attack on issuers, and a conversion risk
for good buyers. The limiter must weight payment attempts
far more than reads.

- Limit by card fingerprint, BIN, account, device, IP, and
  tenant.
- Use PSP response codes as risk signals, not just errors.
- Keep idempotency keys stable across retries.
- Prefer step-up or hold to global checkout block.
- Watch authorization decline mix and velocity.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while card testing changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while card testing is active? | Name the Northstar owner for Card testing: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls card testing risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Card testing. |
| Blast radius | Which slice sees card testing first? | Compare cell, tenant tier, region, route, app version, and dependency for Card testing. |
| Rollback | What rollback edge remains open for card testing, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Card testing. |

### 4. Rate-limit bypass

Attackers bypass naive limits by spreading requests across
IPs, accounts, tokens, paths, and time windows. Endpoint
cost weighting, hierarchical buckets, risk-adjusted
limits, and shared downstream budgets are required to
protect scarce resources.

- Use global plus identity plus endpoint plus resource
  buckets.
- Give writes and payment attempts higher token cost.
- Tie limits to tenant tier without letting one tenant
  spend all burst.
- Bound retries so clients do not amplify denial.
- Log limiter reason codes for appeal and tuning.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while rate-limit bypass changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while rate-limit bypass is active? | Name the Northstar owner for Rate-limit bypass: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls rate-limit bypass risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Rate-limit bypass. |
| Blast radius | Which slice sees rate-limit bypass first? | Compare cell, tenant tier, region, route, app version, and dependency for Rate-limit bypass. |
| Rollback | What rollback edge remains open for rate-limit bypass, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Rate-limit bypass. |

### 5. Poisoned caches

A poisoned cache serves attacker-influenced data to other
users. Causes include missing tenant/auth variant,
accepting untrusted headers in cache keys, caching error
responses, or allowing bots to fill keyspace with
expensive variants.

- Default private for personalized responses.
- Normalize and bound vary headers.
- Separate risk responses from shared cache.
- Use cache-key versioning during auth or price changes.
- Alert on key cardinality and origin miss spikes.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while poisoned caches changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while poisoned caches is active? | Name the Northstar owner for Poisoned caches: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls poisoned caches risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Poisoned caches. |
| Blast radius | Which slice sees poisoned caches first? | Compare cell, tenant tier, region, route, app version, and dependency for Poisoned caches. |
| Rollback | What rollback edge remains open for poisoned caches, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Poisoned caches. |

### 6. Collusion and marketplace fraud

Collusion is coordinated behavior: fake reviews, bid
rings, seller-buyer refund loops, coupon abuse, or
synthetic volume. It is detected through graphs, repeated
payment instruments, device clusters, timing patterns, and
economics, not one HTTP request.

- Build graph features with privacy controls.
- Avoid irreversible punishment from one weak signal.
- Use hold/review queues for ambiguous high-value cases.
- Preserve audit trails for appeals.
- Measure false positives by customer segment.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while collusion and marketplace fraud changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while collusion and marketplace fraud is active? | Name the Northstar owner for Collusion and marketplace fraud: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls collusion and marketplace fraud risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Collusion and marketplace fraud. |
| Blast radius | Which slice sees collusion and marketplace fraud first? | Compare cell, tenant tier, region, route, app version, and dependency for Collusion and marketplace fraud. |
| Rollback | What rollback edge remains open for collusion and marketplace fraud, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Collusion and marketplace fraud. |

### 7. Auth and abuse boundaries

AuthN/AuthZ says whether a principal may attempt an
action. Abuse defense says whether the pattern remains
acceptable under risk and capacity. A valid seller token
can still be limited for exports, and a valid buyer
session can still be stepped up before payment.

- Validate issuer, audience, token type, tenant, and scope
  first.
- Then apply risk and limiter decisions.
- Never use abuse mitigation to bypass authorization.
- Keep service mTLS separate from user risk.
- Audit support overrides as privileged actions.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while auth and abuse boundaries changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while auth and abuse boundaries is active? | Name the Northstar owner for Auth and abuse boundaries: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls auth and abuse boundaries risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Auth and abuse boundaries. |
| Blast radius | Which slice sees auth and abuse boundaries first? | Compare cell, tenant tier, region, route, app version, and dependency for Auth and abuse boundaries. |
| Rollback | What rollback edge remains open for auth and abuse boundaries, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Auth and abuse boundaries. |

### 8. Risk scoring and friction

Risk scores should drive graduated controls: allow,
silently throttle optional work, require MFA, require 3DS,
delay settlement, queue review, or deny. The right action
depends on path criticality, confidence, value, and
customer harm.

- Use friction where it reduces risk without broad outage.
- Never silently drop money-moving writes.
- Expose safe user messages without rule details.
- Tie manual review capacity to queue admission.
- Expire risk decisions and allow appeal.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while risk scoring and friction changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while risk scoring and friction is active? | Name the Northstar owner for Risk scoring and friction: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls risk scoring and friction risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Risk scoring and friction. |
| Blast radius | Which slice sees risk scoring and friction first? | Compare cell, tenant tier, region, route, app version, and dependency for Risk scoring and friction. |
| Rollback | What rollback edge remains open for risk scoring and friction, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Risk scoring and friction. |

### 9. Evidence and privacy

Abuse incidents need evidence: request facts, auth facts,
device hashes, limiter decisions, PSP codes, cache keys,
and graph links. Evidence must avoid raw secrets, raw PAN,
passwords, or excessive personal data in chat and metrics.

- Hash or tokenize sensitive identifiers.
- Use audit logs for tenant/account IDs, not high-
  cardinality metrics.
- Preserve chain-of-custody for legal cases.
- Separate detection data from public dashboards.
- Define retention for abuse evidence.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while evidence and privacy changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while evidence and privacy is active? | Name the Northstar owner for Evidence and privacy: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls evidence and privacy risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Evidence and privacy. |
| Blast radius | Which slice sees evidence and privacy first? | Compare cell, tenant tier, region, route, app version, and dependency for Evidence and privacy. |
| Rollback | What rollback edge remains open for evidence and privacy, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Evidence and privacy. |

### 10. Operational response

Abuse response is not only blocking. It includes
protecting control planes, communicating with support,
tuning thresholds, preserving good traffic, updating fraud
models, and later removing emergency rules that would harm
conversion if left forever.

- Declare abuse incident severity by customer and risk
  impact.
- Freeze risky launches that reduce defense visibility.
- Use scoped rules by slice before global rules.
- Review false positives continuously.
- Set expiration and owner on emergency mitigations.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while operational response changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while operational response is active? | Name the Northstar owner for Operational response: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls operational response risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for this mechanism. |
| Blast radius | Which slice sees operational response first? | Compare cell, tenant tier, region, route, app version, and dependency before trusting fleet averages. |
| Rollback | What rollback edge remains open for operational response, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Operational response. |

## Production anatomy

Production anatomy is the concrete evidence a staff
engineer expects on the bridge: metrics with dimensions,
logs with reason codes, config that shows the dangerous
default, and runbook decisions tied to thresholds. A
design that cannot say what it will measure is not ready
for Northstar traffic.

### Telemetry pack

| Signal | Useful dimensions | Why it matters |
| --- | --- | --- |
| login_attempt_rate | result, ip_asn, device_class | Credential stuffing shape. |
| account_lockout_total | reason, segment | False positive and victim impact. |
| mfa_stepup_rate | risk_reason, region | Graduated friction signal. |
| card_auth_decline_mix | bin, psp_code, route | Card testing evidence. |
| payment_attempts_per_card_hash | window, result | Velocity on payment instrument. |
| scrape_traversal_depth | client_class, route | Bot catalog walking. |
| cdn_origin_miss_ratio | path_class, bot_score_bucket | Scraping and cache poisoning pressure. |
| cache_key_cardinality | cache, route | Adversarial key explosion. |
| rate_limit_decision_total | scope, endpoint, reason | Limiter behavior and appeals. |
| tenant_burst_credit_spent | tenant_tier, endpoint_class | Noisy-neighbor and abuse budget. |
| refund_velocity | seller_cluster, buyer_cluster | Collusion/refund-loop signal. |
| review_graph_cluster_score | seller_tier | Marketplace manipulation signal. |
| support_override_total | role, reason | Privileged bypass monitoring. |
| false_positive_report_rate | segment, mitigation | Customer harm signal. |
| abuse_rule_expiring_soon | rule, owner | Prevents permanent emergency friction. |

### Config pack

#### Limiter stack

```text
endpoint: POST /checkout/payment-authorize
cost_weight: 50
buckets:
  - global_payment_authorize_per_region
  - tenant_tier_payment_budget
  - account_payment_velocity
  - card_fingerprint_velocity
  - device_risk_velocity
  - ip_asn_velocity
risk_actions:
  low: allow
  medium: require_3ds_or_mfa
  high: hold_or_deny
retry_after: required
audit_reason: required
```

#### Dangerous limiter

```text
endpoint: POST /checkout/payment-authorize
bucket: global_requests
cost_weight: 1
key: ip
on_limit: return 500
comment: bots will slow down eventually
```

#### Cache safety

```text
route: GET /seller/price-preview
cache_control: private, no-store
shared_cache_allowed: false
cache_key_required_context:
  - tenant_id
  - price_list_id
  - auth_viewer_class
  - currency
reject_untrusted_vary_headers: true
poison_probe_alert: true
```

### Runbook anatomy

- Declare the protected invariant before naming the fix;
  this prevents fast actions that make the system less
  safe.
- Slice the symptom by cell, tenant tier, region, client
  version, route, and dependency before trusting a global
  graph.
- Identify the current authority for reads, writes, risk
  decisions, and customer communications.
- Name the pre-authorized mitigations and the actions that
  require security, finance, product, or executive
  approval.
- Write down the bad fixes the bridge is likely to propose
  so they can be rejected quickly and calmly.
- Keep a decision log with metric values before and after
  each mitigation; rollback without evidence is guessing.
- Assign one owner for customer/support language and one
  owner for evidence preservation.
- Set a timer to revisit temporary rules, flags,
  throttles, or queues so the incident fix does not become
  permanent architecture.

### Production review questions

1. What is the smallest blast radius that still gives
   meaningful evidence?
2. Which metric would change first if the suspected
   mechanism is true?
3. Which metric would stay green and mislead executives?
4. What scarce resource is consumed by the mitigation
   itself?
5. Which clients, jobs, or partners may continue old
   behavior after rollback?
6. What data must be preserved before cleanup or
   mitigation destroys it?
7. Which tenant or customer slice has a stricter contract
   than the fleet?
8. How will support distinguish pending, failed, rejected,
   and repaired customer states?
9. What is the maximum safe duration for any temporary
   degradation?
10. Who owns the follow-up test that prevents recurrence?

### Staff

## Failure catalog

| Failure | Trigger | Amplifier | Blast radius |
| --- | --- | --- | --- |
| Stuffing hides in averages | Low per-IP rate across botnet | No account/device velocity | ATO spike |
| Enumeration leak | Different errors for missing user | Attack validates usernames | More targeted phishing |
| JWKS stampede by random kid | Bots send random JWT kids | Verifier fetches every miss | Auth control-plane outage |
| Card test underweighted | Payment attempt costs one token | Bots consume PSP capacity | Good checkout denied |
| Global block | All high-risk ASNs denied | Carrier NAT users blocked | Conversion loss |
| Cache key explosion | Bot varies headers | Millions of keys fill CDN | Origin overload |
| Personalized cache leak | Auth response cached shared | One buyer sees another price | Trust incident |
| Scrape warms bad cache | Bot requests stale variants | Edge serves wrong inventory | Seller complaints |
| Tenant burst theft | One seller spends shared tokens | Other sellers starve | Noisy-neighbor outage |
| Support override abused | Manual bypass lacks audit | Fraudster gets refund approved | Forensics weak |
| Collusion single-signal ban | Graph score alone bans sellers | False positives high | Legal/support escalation |
| Risk model fail open | Feature timeout returns allow | Attack floods checkout | Chargeback spike |
| Risk model fail closed globally | Feature timeout denies all checkout | Revenue outage | Bad degradation |
| Emergency rule permanent | Temporary CAPTCHA never expires | Conversion falls for months | Hidden cost |
| Raw secret in evidence | Token pasted into chat | Incident creates new breach | Security escalation |

Failure catalogs are not lists of scary nouns. Each row
should teach the incident shape: the trigger starts the
problem, the amplifier turns it into a distributed
failure, and the blast radius says who or what is harmed.
During a design review, pick the three rows most likely
for the proposed change and prove the telemetry and
rollback exist.

### Failure drill prompts

- For Stuffing hides in averages, what single metric would
  page before the customer-visible ato spike?
- What mitigation reduces no account/device velocity
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Enumeration leak, what single metric would page
  before the customer-visible more targeted phishing?
- What mitigation reduces attack validates usernames
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For JWKS stampede by random kid, what single metric
  would page before the customer-visible auth control-
  plane outage?
- What mitigation reduces verifier fetches every miss
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Card test underweighted, what single metric would
  page before the customer-visible good checkout denied?
- What mitigation reduces bots consume psp capacity
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Global block, what single metric would page before
  the customer-visible conversion loss?
- What mitigation reduces carrier nat users blocked
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Cache key explosion, what single metric would page
  before the customer-visible origin overload?
- What mitigation reduces millions of keys fill cdn
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Personalized cache leak, what single metric would
  page before the customer-visible trust incident?
- What mitigation reduces one buyer sees another price
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Scrape warms bad cache, what single metric would
  page before the customer-visible seller complaints?
- What mitigation reduces edge serves wrong inventory
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Tenant burst theft, what single metric would page
  before the customer-visible noisy-neighbor outage?
- What mitigation reduces other sellers starve without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Support override abused, what single metric would
  page before the customer-visible forensics weak?
- What mitigation reduces fraudster gets refund approved
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Collusion single-signal ban, what single metric
  would page before the customer-visible legal/support
  escalation?
- What mitigation reduces false positives high without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Risk model fail open, what single metric would page
  before the customer-visible chargeback spike?
- What mitigation reduces attack floods checkout without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Risk model fail closed globally, what single metric
  would page before the customer-visible bad degradation?
- What mitigation reduces revenue outage without hiding
  the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Emergency rule permanent, what single metric would
  page before the customer-visible hidden cost?
- What mitigation reduces conversion falls for months
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Raw secret in evidence, what single metric would
  page before the customer-visible security escalation?
- What mitigation reduces incident creates new breach
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

## Decision framework

Good operational decisions are conditional. They do not
say always use one pattern or never use another. They name
the invariant, workload shape, rollback cost, evidence
quality, and human ownership. Use this table as a forcing
function before launch and during incidents.

| Option | Use when | Caution |
| --- | --- | --- |
| Credential stuffing | Login failures by account/device/ASN, known breach | Step-up, velocity limits, password reset for victims |
| Scraping | Traversal depth, bot score, origin miss, pagination abuse | CDN rules, signed access, response shaping, endpoint quotas |
| Card testing | Payment declines, card hash velocity, BIN concentration | Weighted limits, 3DS, PSP rules, hold/deny high risk |
| Rate bypass | Many identities share downstream resource pressure | Hierarchical and adaptive buckets |
| Cache poisoning | Key cardinality, variant anomalies, shared personalized response | Private/no-store, normalize keys, purge scoped variants |
| Collusion | Graph clusters, repeated instruments, economics anomalies | Review holds, graph model, appeal process |
| Authenticated abuse | Valid token but harmful rate or scope of work | Workload quotas and endpoint cost limits |
| Control-plane abuse | JWKS/flag/risk service pressured | Caches, negative cache, singleflight, stale-safe rules |
| False positive wave | Support tickets and conversion drop after rule | Rollback scoped rule, tune thresholds, communicate |
| Fraud model outage | Risk dependency slow/unavailable | Predefined fail mode by path criticality |

### Decision checklist

1. State the business invariant in one sentence. If the
   invariant is vague, stop and clarify.
2. Name the source of truth and the derived views. Never
   repair the source from an unverified projection.
3. Choose the rollout unit: request, tenant, seller tier,
   region, cell, app version, or control-plane version.
4. Define the abort condition before starting. Include
   correctness, latency, saturation, cost, security, and
   support signals.
5. Estimate cross-system capacity impact. A safe local fix
   can overload Kafka, Redis, Postgres, PSP, or support.
6. List data that becomes hard or impossible to recover
   after the next step.
7. Choose communication timing and audience based on
   affected slice, not global severity language.
8. Decide what can be automated and what must require
   human approval.
9. Set expiration for emergency mitigations and create a
   follow-up owner before leaving the bridge.
10. Write the acceptance test that would have caught the
    issue before launch.

### Northstar field practice cards

Use these cards as mini design-review prompts before the
Ops Sim. They are not answer keys; they force you to name
mechanism, evidence, invariant, and rollback before the
timed drill.

#### Card 01 - Stuffing distributed IPs

- **Setup:** Login attempts are low per IP but high per
             account and device family.
- **Mechanism to name:** Credential stuffing velocity
                         across identities.
- **Evidence to request:** Account failure velocity,
                           device hash, ASN, breached
                           credential signal, MFA step-up.
- **Safe first move:** Apply account/device/ASN risk
                       limits and step-up victims.
- **Bad fix to reject:** Block every IP with one failed
                         login.
- **Durable gate:** Stuffing dashboard includes account
                    and device dimensions.

#### Card 02 - Random kid attack

- **Setup:** Bots send JWTs with random kid values to
             checkout-api.
- **Mechanism to name:** Auth control-plane abuse and
                         negative JWKS cache.
- **Evidence to request:** Unknown kid rate, JWKS fetch
                           QPS, cache miss reason,
                           verifier latency.
- **Safe first move:** Enable negative cache and
                       singleflight; keep signature
                       validation.
- **Bad fix to reject:** Disable JWT checks until attack
                         passes.
- **Durable gate:** Verifier stress test for random-kid
                    traffic.

#### Card 03 - Card testing

- **Setup:** Small-value payment attempts decline at high
             rate across many accounts.
- **Mechanism to name:** Payment instrument velocity and
                         endpoint cost weighting.
- **Evidence to request:** Card hash, BIN, PSP code,
                           account age, device family,
                           attempt rate.
- **Safe first move:** Increase payment endpoint weight
                       and require 3DS/hold high risk.
- **Bad fix to reject:** Global block all checkout
                         payments.
- **Durable gate:** Card-testing game-day with PSP sandbox
                    declines.

#### Card 04 - Scraper pagination

- **Setup:** One client walks every search page with
             rotating IPs.
- **Mechanism to name:** Scraping by traversal behavior
                         rather than single IP.
- **Evidence to request:** Traversal depth, cursor
                           pattern, bot score, origin
                           miss, response bytes.
- **Safe first move:** Throttle expensive pagination and
                       require stronger signals for deep
                       access.
- **Bad fix to reject:** Raise CDN TTL for all search
                         results containing private
                         prices.
- **Durable gate:** Search abuse contract defines cost and
                    max traversal.

#### Card 05 - Cache key explosion

- **Setup:** Vary allowlist accepts arbitrary headers at
             CloudFront.
- **Mechanism to name:** Adversarial cache-key
                         cardinality.
- **Evidence to request:** Cache key count, origin miss
                           ratio, header diversity,
                           eviction rate.
- **Safe first move:** Normalize/allowlist vary headers
                       and purge poisoned variants.
- **Bad fix to reject:** Add more origins to handle
                         misses.
- **Durable gate:** Cache config test rejects unbounded
                    vary keys.

#### Card 06 - Personalized cache leak

- **Setup:** Price preview with Set-Cookie is cached
             public.
- **Mechanism to name:** Personalization and tenant cache
                         boundary.
- **Evidence to request:** Set-Cookie on cached response,
                           cache-control, tenant/auth in
                           key, hit logs.
- **Safe first move:** Set private/no-store and purge
                       scoped route.
- **Bad fix to reject:** Ignore because only preview page
                         is affected.
- **Durable gate:** CDN test blocks shared caching when
                    Set-Cookie appears.

#### Card 07 - Seller export abuse

- **Setup:** Valid seller token calls export every second.
- **Mechanism to name:** Authenticated abuse and workload
                         quotas.
- **Evidence to request:** Token scope, tenant tier,
                           endpoint weight, worker pool,
                           queue delay.
- **Safe first move:** Apply tenant/workload quota and
                       async admission control.
- **Bad fix to reject:** Revoke all seller tokens
                         globally.
- **Durable gate:** Export route has weighted fair queue
                    and per-tenant budget.

#### Card 08 - Risk timeout

- **Setup:** Fraud service times out and payment path
             defaults allow.
- **Mechanism to name:** Risk dependency fail-mode by
                         path.
- **Evidence to request:** Risk timeout rate, decision
                           default, chargeback proxy,
                           checkout SLO.
- **Safe first move:** Step-up or hold high-risk payments
                       while preserving low-risk paths.
- **Bad fix to reject:** Fail open for all payments to
                         protect conversion.
- **Durable gate:** Risk contract names fail mode per
                    action class.

#### Card 09 - False positive wave

- **Setup:** New rule blocks many carrier NAT buyers.
- **Mechanism to name:** False-positive monitoring and
                         scoped rollback.
- **Evidence to request:** Support tickets, conversion by
                           ASN, deny reason, good-account
                           age.
- **Safe first move:** Rollback or narrow the rule for
                       affected ASN while preserving card
                       controls.
- **Bad fix to reject:** Remove all abuse defenses.
- **Durable gate:** Rule rollout requires false-positive
                    budget and expiry.

#### Card 10 - Collusion ring

- **Setup:** Refunds loop among related buyers and
             sellers.
- **Mechanism to name:** Graph/timing/economics fraud.
- **Evidence to request:** Shared devices/payment
                           instruments, refund velocity,
                           graph clusters, seller tier.
- **Safe first move:** Hold ambiguous high-value refunds
                       for review and preserve graph
                       evidence.
- **Bad fix to reject:** Ban every connected account from
                         one weak edge.
- **Durable gate:** Collusion model has appeal and manual-
                    review capacity gates.

#### Card 11 - Support bypass

- **Setup:** Support overrides fraud hold without reason
             code.
- **Mechanism to name:** Privileged action audit and
                         authorization.
- **Evidence to request:** Override role, tenant, reason,
                           approver, downstream action.
- **Safe first move:** Require approval/reason and
                       preserve audit trail.
- **Bad fix to reject:** Let support bypass because
                         customer is angry.
- **Durable gate:** Support tool enforces tenant and risk
                    override policy.

#### Card 12 - Emergency CAPTCHA

- **Setup:** CAPTCHA added globally and never removed.
- **Mechanism to name:** Temporary mitigation ownership
                         and expiry.
- **Evidence to request:** Challenge rate, conversion
                           drop, false positives, rule
                           age, owner.
- **Safe first move:** Set expiry, scope by risk, and
                       review conversion/customer harm.
- **Bad fix to reject:** Leave it on because fraud might
                         return.
- **Durable gate:** Every emergency abuse rule has owner,
                    expiry, and rollback metric.

### Principal stretch

## Ops Sim

### Northstar Card Testing and Cache Poisoning Combo

**Time box:** 75 minutes  
**Severity:** P1  
**Service / domain:** Abuse, payments, rate limits, CDN/cache, auth  
**Northstar system:** shared commerce platform

#### Rules

1. Answer from memory of this module and earlier Northstar
   weeks; do not open the key mid-drill.
2. Write decisions in order from T+0 to T+60, including
   what you intentionally do not do.
3. Name evidence for every claim: metric, log line, trace
   field, config key, or customer slice.
4. Include at least one capacity or blast-radius
   calculation before proposing a repair.
5. Do not put worked answers in this learner file; open
   the answer key only after attempting.

#### Scenario stem

```text
WHAT USERS SEE:
  Good buyers in us-east-1 intermittently receive payment step-up or
  payment unavailable messages. A few sellers report strange public
  price-preview results at the edge.

WHAT ON-CALL SEES:
  Payment authorization traffic is up only 18% globally, but PSP
  declines are up 900% for small-value attempts. CDN origin misses are
  concentrated on price-preview variants with unusual headers.

BUSINESS CONSTRAINT:
  The marketing team is running a flash sale. Blocking all anonymous
  catalog browsing would harm revenue, but letting card testing continue
  risks PSP throttling and chargeback penalties.
```

#### Telemetry pack

```text
METRICS:
  checkout_payment_authorize_rps: +18% global
  psp_decline_rate{amount_bucket=small}: 2.1% -> 38%
  payment_attempts_per_card_hash_p95: 2 -> 47/10m
  account_payment_velocity_p99: 4 -> 61/10m
  ip_unique_accounts_p95: 3 -> 480/10m
  rate_limit_decision_total{bucket=global_requests, decision=allow}: 97%
  cdn_origin_miss_ratio{route=price-preview}: 8% -> 54%
  cache_key_cardinality{route=price-preview}: 41k -> 7.8M
  cache_hit_served_with_set_cookie_total: 19
  enterprise_checkout_slo_burn: 6.2x

LOG LINES:
  risk-api: feature timeout, default=allow for payment_authorize
  limiter: endpoint cost missing, POST /payment-authorize weight=1
  cloudfront: vary header x-device-fingerprint accepted into key
  auth: valid buyer sessions, many created within 90 seconds

TRACE NOTES:
  Card attempts use different IPs but same BIN ranges and device hash family
  Price-preview response includes seller-specific discount and Set-Cookie
```

#### Config pack

```yaml
# dangerous settings included
limiter:
  key: ip
  global_bucket_rps: 200000
  endpoint_weights:
    GET /products: 1
    POST /checkout/payment-authorize: 1

risk_api:
  timeout_ms: 200
  on_timeout: allow

cdn_cache:
  route: /seller/price-preview
  cache_control_override: public, max-age=600
  vary_allowlist: ['*']
```

#### Timeline and decision points

| Time | Event | Your move |
| --- | --- | --- |
| T+0 | Incident or gate failure declared; first dashboards are noisy. | Name invariant, commander, owner, and first slice query. |
| T+5 | A tempting fast fix appears in chat. | Decide whether to reject, defer, or scope it. |
| T+15 | Telemetry narrows the mechanism and blast radius. | Apply the smallest safe mitigation and record evidence. |
| T+30 | Support/product ask what customers are affected. | Communicate slice, status, and uncertainty. |
| T+60 | System is stable enough for durable repair planning. | Write acceptance tests and follow-up owners. |

#### Questions

1. Classify the two abuse mechanisms and name the
   protected invariants.
2. Which signals prove card testing despite only modest
   global traffic growth?
3. Which limiter hierarchy should replace the current
   IP/global bucket?
4. What cache poisoning or personalization leak evidence
   exists, and what is the immediate containment?
5. What should risk-api do on timeout for payment
   authorize versus public catalog read?
6. Which mitigations preserve flash-sale revenue while
   protecting PSP capacity?
7. What evidence must be preserved for fraud/security
   without leaking secrets?
8. Name bad fixes to reject and durable tests to add.

#### Self-score after opening the key

| Error type | Did it happen? | Note |
| --- | --- | --- |
| Knowledge gap |  |  |
| Wrong layer |  |  |
| Sequencing error |  |  |
| Capacity or blast-radius miss |  |  |
| Security/tenancy invariant miss |  |  |
| Org/comms miss |  |  |
| Careless slip |  |  |

**Pass bar:** correct mechanism, safe sequencing, explicit rejection of at least one bad fix, one numeric capacity or blast-radius check, and a durable prevention plan grounded in source of truth.

**Answer key:** [answers/Week-08c-Operations-Hardening/Abuse Bots and Fraud Defense Answers.md](../answers/Week-08c-Operations-Hardening/Abuse%20Bots%20and%20Fraud%20Defense%20Answers.md)

## Key takeaways

- Abuse defense is adversarial capacity, trust, and
  economics combined.
- Authentication does not imply an action pattern is safe.
- Payment attempts, exports, and searches need endpoint
  cost weights.
- IP-only rate limits are weak against modern bot traffic.
- Caches can be abused through personalization leaks and
  key explosion.
- Fraud response must manage false positives as a
  production signal.
- Evidence handling is part of the security boundary.

### 4. Graph-Based Fraud Detection & Anti-Collusion PageRank Math

Marketplace collusion (e.g., merchant-buyer review rings, money laundering loops, referral fraud) manifests as dense subgraphs or cyclic transaction chains.

```
GRAPH COLLUSION DETECTION ARCHITECTURE:

    [ Buyer A ] ────── Paid ──────► [ Merchant X ] ────── Refund ──────► [ Buyer B ]
         │                                                                   │
         └──────────────────────── Shared Device / IP ───────────────────────┘
```

#### Graph Adjacency Matrix & Personalised PageRank (PPR)
We construct an entity graph $G = (V, E)$ where nodes $V$ represent accounts, devices, credit card hashes, and IP addresses. Edge weights $W_{ij}$ represent interaction frequency or money transferred.

$$\mathbf{p}^{(t+1)} = (1 - \alpha) \mathbf{M} \mathbf{p}^{(t)} + \alpha \mathbf{s}$$

Where:
- $\mathbf{M}$: Transition probability matrix normalized from $W_{ij}$.
- $\alpha$: Teleportation parameter (typically $0.15$).
- $\mathbf{s}$: Seed vector highlighting known fraud nodes.

High PPR scores indicate nodes tightly linked to known bad actors, triggering automated review holds before funds settle.

#### 5. Bot Traffic Cost Weighting Matrix

| Route / Endpoint | Resource Intensity | Cost Weight | Limiter Action on Exceeding Budget |
| :--- | :--- | :--- | :--- |
| `GET /catalog/products` | Low (Edge Cached) | 1 | Soft HTTP 429 Retry-After: 5s |
| `POST /search/query` | Medium (Elasticsearch BM25) | 10 | CAPTCHA / Proof-of-Work Challenge |
| `POST /checkout/payment` | High (PSP + Database Write) | 50 | Hard Block + Account Risk Step-up |
| `POST /reports/export-csv` | Very High (Heavy SQL Join) | 100 | Queue for Async Background Processing |

---

## Targeted reading

- OWASP Automated Threats to Web Applications for
  credential stuffing and scraping classes.
- OWASP API Security Top 10 for authorization, rate
  limiting, and resource consumption risks.
- Stripe documentation on Radar, idempotency, and card
  testing defenses.
- Cloudflare and AWS WAF bot management documentation for
  edge controls and bot signals.
- NIST Digital Identity Guidelines sections on
  authenticator replay and risk-based authentication.
- Google SRE material on overload and graceful
  degradation.
- Northstar Week 07 rate limiting and Week 08b auth/multi-
  tenancy modules.
- Academic marketplace fraud and graph-abuse papers for
  collusion detection concepts.

---

## Staff & Principal Stretch: Advanced Fraud & Bot Defense Systems

### 1. Mathematical Analysis of Rate Limiting Algorithms & Distributed Lua Scripts

Different rate limiting primitives offer distinct trade-offs between memory overhead, accuracy, and latency:

#### Sliding Window Counter Algorithm
Combines previous window count and current window count using linear interpolation:

$$\text{Estimated Count} = \text{Count}_{\text{prev}} \times \left(1 - \frac{t_{\text{current}}}{\text{WindowSize}}\right) + \text{Count}_{\text{curr}}$$

Memory footprint: $O(1)$ per key (stores two counter integers).

#### Distributed Redis Lua Script (Atomic Sliding Window):

```lua
-- KEYS[1]: Rate limit key (e.g., rate:user_123:checkout)
-- ARGV[1]: Current timestamp in milliseconds
-- ARGV[2]: Window size in milliseconds (e.g., 60000)
-- ARGV[3]: Max allowed requests

local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local clear_before = now - window

-- 1. Remove timestamps older than the window
redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)

-- 2. Count requests in current window
local current_requests = redis.call('ZCARD', key)

if current_requests < limit then
    -- 3. Add current timestamp to sorted set
    redis.call('ZADD', key, now, now)
    redis.call('PEXPIRE', key, window)
    return {1, current_requests + 1} -- ALLOWED
else
    return {0, current_requests} -- REJECTED
end
```

### 2. TLS Client Hello Fingerprinting (JA3 / JA4 Signature Extraction)

Standard HTTP headers (like `User-Agent`) are trivially spoofed by botnets. **TLS Client Hello Fingerprinting (JA3)** extracts parameters from the unencrypted initial TLS handshake packet:

$$\text{JA3 String} = \text{TLSVersion},\text{Ciphers},\text{Extensions},\text{EllipticCurves},\text{EllipticCurvePointFormats}$$

$$\text{JA3 Hash} = \text{MD5}(\text{JA3 String})$$

```
TLS CLIENT HELLO FINGERPRINTING:

  Client (Python Requests / Script)
    │
    │── ClientHello (TLS 1.2, 18 Ciphers, 5 Extensions) ──► Envoy / CloudFront Edge
    │                                                            │
    │                                                            ▼
    │                                                    Extract JA3 Hash:
    │                                                    "771,4865-4866-4867,0-23-65281..."
    │                                                            │
    │                                                            ▼
    │                                                    Check JA3 Threat DB:
    │                                                    Matches "Known Scraping Script"
    │                                                            │
    │                                                            ▼
    │                                                    Inject `x-ja3-risk: high` header
```

### 3. ML Fraud Inference Latency Budgets & Asynchronous Shadow Mode

```
FRAUD INFERENCE PIPELINE LATENCY BUDGET:

  Total HTTP Latency Budget = 200ms
  ├── Edge WAF / JA3 Filter :   5ms
  ├── AuthN / AuthZ Token   :  15ms
  ├── Feature Store Lookup  :  20ms (Redis Online Store)
  ├── ML Model Inference    :  40ms (XGBoost / LightGBM on ONNX Runtime)
  └── Business Logic / DB   : 120ms

SHADOW EVALUATION PIPELINE:
  To avoid blocking customer checkout when deploying new ML fraud models, run
  the candidate model asynchronously via Kafka / Kinesis:

  Inference Request ──► Production Model (Sync, 40ms) ──► Allow/Deny
           │
           └── Async Publish ──► Kafka ──► Shadow Model (Async) ──► Log Model Divergence
```

---

## Appendix A: Extended Principal SRE Field Guide for Bot & Abuse Mitigation

### A.1 — Credential Stuffing Incident Response Workflow

```
CREDENTIAL STUFFING ATTACK DETECTION & AUTOMATED MITIGATION PIPELINE:

  1. Detection: High volume of failed login attempts across disparate IP ranges with constant User-Agent.
  2. Signal Verification:
     - Check Redis Rate Limiter: rate:login:account:<user_id> > 5 attempts / min.
     - Check IP Velocity: Distinct account attempts per IP > 10 / min.
     - Query Identity Provider (Cognito / Auth0): Invalid password error rate > 85%.
  3. Automated Defense Execution:
     - Issue risk step-up: Mandate CAPTCHA / WebAuthn for affected IP ranges.
     - Account Lockout: Temporarily lock target accounts and send security email alerts.
     - IP Range Throttling: Return HTTP 429 Retry-After: 60s at CloudFront / Edge WAF.
```

### A.2 — Advanced Payment Gateway Rate Limiting & Token Bucket Math

When defending payment gateways against carding attacks (automated validation of stolen credit cards using low-value transactions), simple fixed-window rate limiters fail because botnets spread requests across thousands of rotating residential proxies.

```
MULTI-TIER TOKEN BUCKET LIMITER HIERARCHY:

  Tier 1: Global Merchant Bucket (Capacity: 50,000 req/min, Refill Rate: 833 req/sec)
  Tier 2: BIN / Card Network Bucket (Capacity: 500 req/min per Issuer BIN)
  Tier 3: Device Fingerprint Bucket (Capacity: 5 req/min per Device Hash)
  Tier 4: IP Subnet / ASN Bucket (Capacity: 50 req/min per /24 Subnet)
```

```python
# Token Bucket Algorithm Reference Implementation
import time

class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()

    def consume(self, tokens: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now
        
        # Add new tokens based on elapsed time
        self.tokens = min(float(self.capacity), self.tokens + elapsed * self.refill_rate)
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True  # Allowed
        return False  # Rate limited
```

### A.3 — Edge WAF Ruleset Configuration (CloudFront / AWS WAF)

```json
{
  "Name": "BlockHighRiskBotnetTraffic",
  "Priority": 1,
  "Statement": {
    "AndStatement": {
      "Statements": [
        {
          "ByteMatchStatement": {
            "SearchString": "/checkout/payment-authorize",
            "FieldToMatch": { "URIPath": {} },
            "TextTransformations": [ { "Priority": 0, "Type": "LOWERCASE" } ]
          }
        },
        {
          "NumericGreaterThanStatement": {
            "FieldToMatch": { "SingleHeader": { "Name": "x-bot-score" } },
            "Constraint": 80
          }
        }
      ]
    }
  },
  "Action": { "Block": { "CustomResponse": { "ResponseCode": 429 } } }
}
```

### A.4 — Operational Incident Runbook Template for Fraud Outages

```
INCIDENT RUNBOOK: ADVERSARIAL FRAUD & BOT DEFENSE EMERGENCY PROTOCOL

  1. INCIDENT CLASSIFICATION & ALERT TRIAGE
     - Priority: P1 (Revenue / Security Impact)
     - Trigger: Fraud rule false-positive rate > 5% OR Unmitigated Carding Attack > 1,000 req/min.
     - On-Call Roles: Incident Commander, Fraud Lead, Security Ops, Payment SRE.

  2. IMMEDIATE MITIGATION STEPS (T+0 to T+15m)
     - Step 2.1: Verify edge WAF rules are actively intercepting request patterns.
     - Step 2.2: If false positives spike, narrow WAF rule targeting from Global ASN to Subnet/Path.
     - Step 2.3: Scale Redis rate limiter cluster memory headroom if evicted_keys > 0.

  3. COMMUNICATIONS & AUDIT RECOVERY (T+15m to T+60m)
     - Step 3.1: Notify Merchant Support with exact error codes returned to impacted users.
     - Step 3.2: Export incident telemetry logs to S3 WORM storage for legal compliance.
     - Step 3.3: Schedule post-incident game day to re-tune ML model thresholds.
```

### A.5 — Machine Learning Feature Engineering Matrix for Real-Time Abuse Signals

| Feature Name | Computation Window | Data Source | Feature Description |
| :--- | :--- | :--- | :--- |
| `ip_login_failure_rate_10m` | 10 minutes | Redis Counter | Ratio of failed logins to total logins per /24 IP subnet |
| `card_bin_velocity_1h` | 1 hour | Kafka Stream | Distinct payment attempts using the same 6-digit BIN |
| `device_account_entropy_24h` | 24 hours | Feature Store | Shannon entropy of user account IDs associated with a single device hash |
| `ja3_fingerprint_anomaly_score` | Real-time | Edge Proxy | Cosine similarity between client JA3 fingerprint and user historical baseline |

### A.6 — Bot Mitigation Edge Architecture & Fail-Safe Matrix

```
EDGE BOT MANAGEMENT PIPELINE:

  Client Request ──► CloudFront / Envoy Edge ──► WAF Ruleset (JA3 & Rate Limit)
                           │
                           ├── High Risk Score ( > 80 )  ──► Block HTTP 429 / CAPTCHA
                           ├── Medium Risk ( 40 - 80 ) ──► Inject Risk Headers & Proceed
                           └── Low Risk ( < 40 )        ──► Route to Origin API
```

```
BOT DEFENSE FAIL-SAFE RULES:

  1. WAF Service Outage ──────► Fail Open for READ requests, Fail Closed for PAYMENT requests.
  2. Redis Rate Limiter Timeout ──► Allow request with log warning; do NOT block live traffic.
  3. Feature Store Unavailable ──► Fallback to static heuristic rules (IP subnet + User-Agent).
```

### A.7 — SRE Incident Case Study: Mitigating a 500,000 IP Distributed Carding Storm

```
POST-MORTEM INCIDENT ANALYSIS: 500k RESIDENTIAL PROXY CARDING ATTACK

  BACKGROUND:
  At 02:14 UTC, payment gateway error rates spiked to 42%. A distributed botnet using 500,000 rotating
  residential IP addresses launched a carding attack against `/checkout/payment-authorize`.

  CHALLENGES:
  - Per-IP rate limiting was ineffective (each IP sent only 1 request every 5 minutes).
  - Web application firewall (WAF) rule based on User-Agent failed because requests spoofed Chrome 126 headers.

  ROOT CAUSE DIAGNOSIS:
  - Analysis of Envoy edge access logs revealed identical TLS Client Hello fingerprints (JA3: 771,4865-4866-4867...).
  - Device fingerprinting revealed 98% of requests shared an identical Canvas rendering hash.

  REMEDIATION ACTIONS:
  1. T+12m: Injected dynamic WAF blocking rule filtering by JA3 hash + URI path.
  2. T+18m: Applied sliding-window rate limit on credit card Issuer Identification Numbers (BINs).
  3. T+25m: Forced 3D Secure (3DS) authentication for all transactions with risk score > 50.

  PREVENTION LESSONS:
  - Never rely solely on IP reputation or User-Agent headers for bot mitigation.
  - Mandate JA3/JA4 fingerprinting at the edge ingress layer.
```

### A.8 — Automated Bot Detection & Threat Intelligence Data Pipeline

```
BOT DETECTION DATA PIPELINE ARCHITECTURE:

  [ Edge Envoy Proxy ] ── TLS / JA3 / IP Logs ──► [ Kafka Log Topic ]
                                                           │
                                                           ▼
                                                 [ Flink Stream Processor ]
                                                           │
                                        ┌──────────────────┴──────────────────┐
                                        ▼                                     ▼
                           [ Velocity Aggregations ]            [ Feature Store (Redis) ]
                                        │                                     │
                                        ▼                                     ▼
                           [ WAF Rule Engine (AWS WAF) ] ◄── Risk Score ── [ ML Model ]
```

### A.9 — SRE Checklist for Launching Bot Mitigation Policies

```
BOT MITIGATION LAUNCH CHECKLIST:

  [ ] Verify false-positive rate on historical traffic using Shadow Mode execution for >= 48 hours.
  [ ] Ensure CAPTCHA fallback path is fully accessible and localized for international users.
  [ ] Confirm Redis Rate Limiter cluster has multi-AZ replication enabled with failover TTL < 5s.
  [ ] Establish automated alert for `waf_block_rate > 10%` to detect accidental legitimate user lockouts.
  [ ] Audit log pipeline compliance to ensure credit card numbers (PAN) are NEVER recorded in WAF telemetry logs.
```

### A.10 — Advanced Fraud & Bot Defense Telemetry Metric Dictionary

```
COMPLETE METRIC REGISTRY FOR BOT & FRAUD SUBSYSTEMS:

  1. bot_request_total{route, bot_score_bucket, risk_action}
     - Type: Counter
     - Description: Total requests classified by edge bot management engine.

  2. credit_card_velocity_exceeded_total{issuer_bin, account_id}
     - Type: Counter
     - Description: Triggered carding attack limits on payment authorization paths.

  3. rate_limit_bucket_tokens_remaining{bucket_type, entity_id}
     - Type: Gauge
     - Description: Current available capacity in hierarchical rate limit buckets.

  4. ja3_fingerprint_unique_count{subnet_24}
     - Type: Gauge
     - Description: Cardinality of TLS Client Hello fingerprints per IP subnet.

  5. captcha_challenge_issued_total{route, client_class}
     - Type: Counter
     - Description: Proof-of-work or CAPTCHA challenges presented to high-risk requests.

  6. captcha_challenge_passed_ratio{route}
     - Type: Gauge
     - Description: Ratio of successfully solved CAPTCHA challenges (detects false positives).
```

### A.11 — Comprehensive Socratic Review & Production Verification Drill

```
SOCRATIC REVIEW DRILL — BOT & ABUSE HARDENING:

  Question 1: Why does using HTTP header User-Agent filtering fail against modern residential botnets?
  Answer 1: Residential proxy botnets replay legitimate web browser User-Agent strings and rotate IP addresses
            across millions of nodes. Edge security must inspect unencrypted TLS handshake signatures (JA3/JA4)
            and behavioral rate limits rather than static strings.

  Question 2: What is the primary operational danger of setting a rate-limiter decision to 'Fail Closed' (500 Internal Error) on Redis backend timeout?
  Answer 2: If the Redis rate-limiter cluster experiences high memory pressure or network latency, setting the default
            action to 'Fail Closed' converts a local caching issue into a global availability outage for all legitimate users.

  Question 3: How does Token Bucket cost-weighting protect costly API endpoints (e.g., PDF generation or Payment Authorize)?
  Answer 3: By assigning higher token costs (e.g., 50 tokens vs 1 token) to expensive endpoints, clients exhaust their
            allocated rate-limit budget faster when making resource-intensive calls, preserving backend CPU and database worker pools.
```

### A.12 — Summary Architectural Invariants for Fraud & Bot Defense Systems

1. **Security Boundaries precede Rate Limiting:** Authentication and Authorization checks must execute before risk scoring to prevent unauthenticated resource consumption.
2. **Deterministic Token Buckets for Multi-Tenant Isolation:** Tenant rate limits must enforce per-tenant quotas to prevent noisy neighbors from exhausting global connection capacity.
3. **Automated Expiry for Emergency Rules:** Every temporary WAF rule or rate-limit override must carry an automated expiration TTL and an assigned SRE owner.

### A.13 — Staff SRE Case Study: Mitigating Sophisticated API Coupon Enumeration

```
CASE STUDY: API COUPON CODE ENUMERATION ATTACK

  BACKGROUND:
  Attackers launched a distributed script trying millions of alphanumeric coupon code combinations against
  `/api/v1/coupons/apply` to discover unreleased promotional discounts.

  ATTACK VECTOR:
  - 100,000 distinct IP addresses derived from commercial cloud providers (AWS, GCP, DigitalOcean).
  - Low velocity per IP (1 request every 3 minutes per IP), evading basic rate limiters.

  DETECTION & TELEMETRY:
  - `coupon_validation_failure_ratio` reached 99.4% (baseline is < 15%).
  - Distributed tracing showed 90% of requests carried invalid coupon codes generated by sequential brute-force pattern.

  MITIGATION ARCHITECTURE:
  1. Implemented Exponential Backoff Delays on repeated invalid coupon validation attempts per account.
  2. Injected HMAC-signed Proof-of-Work (PoW) tokens into coupon application forms during high-volume periods.
  3. Added CloudFront WAF Managed Rule blocking known cloud provider proxy IPs on payment routes.

  RESULTS:
  - Invalid coupon validation traffic dropped by 99.8% within 5 minutes of rule deployment.
  - Zero impact on legitimate customer checkouts during peak promotion window.
```

### A.14 — Anti-Abuse Rate-Limiter Capacity Planning Worksheet

```
RATE LIMITER MEMORY & CAPACITY CALCULATIONS:

  1. Keyspace Estimation:
     - Target Active Users: 10,000,000 users / day.
     - Rate Limit Key Size: `rate:user:<user_id>:<endpoint>` = 64 bytes.
     - Redis Sorted Set (ZSET) overhead per timestamp entry = 32 bytes.
     - Average sliding window requests per key = 20 entries.
     - Total Memory per Key = 64 + (20 * 32) = 704 bytes.

  2. Cluster Memory Requirement:
     - Total RAM = 10,000,000 * 704 bytes ≈ 7.04 GB.
     - With 3x Replication factor + 50% headroom = 7.04 GB * 3 * 1.5 ≈ 31.68 GB RAM.
     - Recommended Redis Cluster configuration: 3 Shards (AWS ElastiCache `cache.m6g.xlarge` with 13GB RAM per node).
```

### A.15 — Advanced Risk-Based Authentication (RBA) Decision Engine Architecture

```
RISK-BASED AUTHENTICATION (RBA) STATE FLOW:

  User Login Request ──► Feature Ingestion (IP, ASN, JA3, Device Hash, Geo-Velocity)
                               │
                               ▼
                   [ Risk Score Evaluator (XGBoost) ]
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
     Risk Score < 30    30 <= Score <= 75   Risk Score > 75
            │                  │                  │
            ▼                  ▼                  ▼
      [ Direct Allow ]  [ Step-Up MFA ]    [ Hard Deny + Audit ]
```

### A.16 — Fraud Mitigation Emergency Incident Command Checklist

```
EMERGENCY INCIDENT COMMAND CHECKLIST — ABUSE & BOT ATTACKS:

  [ ] T+00m: Declare P1 Fraud Incident; establish dedicated Slack/Teams war room and Incident Command channel.
  [ ] T+05m: Identify primary attack vector (Credential Stuffing, Carding, Scraping, or Inventory Hoarding).
  [ ] T+10m: Deploy scoped WAF blocking rules at CloudFront / Edge API Gateway layer.
  [ ] T+15m: Adjust Redis Rate Limiter thresholds for affected endpoints and verify memory capacity headroom.
  [ ] T+30m: Provide formal update to Customer Support and Executive Stakeholders with clear blast radius metrics.
  [ ] T+60m: Review false-positive telemetry signals and initiate long-term model re-tuning.
```

























### A.17 — Bot Defense & Anti-Fraud SRE Operations Summary Table

| Defense Layer | Primary Target Threat | Core Signal Used | Preferred Mitigation Mechanism |
| :--- | :--- | :--- | :--- |
| Edge Ingress WAF | Automated Scraping & Scrapers | JA3/JA4 TLS Handshake Signature | Edge Block (HTTP 429) / Proof-of-Work Challenge |
| Identity / Auth Gateway | Credential Stuffing | IP Subnet Account Failure Velocity | Step-Up Multi-Factor Auth (WebAuthn / CAPTCHA) |
| Payment Gateway | Carding & Card Testing Attacks | Issuer BIN Attempt Velocity + Device Hash | 3D-Secure (3DS) Challenge / Rate-Limit Budget |
| Marketplace Engine | Merchant-Buyer Collusion Rings | Graph Personalised PageRank (PPR) | Manual Review Hold & Settlement Freeze |








---
