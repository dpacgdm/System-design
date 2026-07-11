# Week 7, Topic 5 — Feature Flags and Progressive Delivery

> Shipping code to production is not the same as releasing a feature to users. Progressive delivery separates deployment (code on servers) from release (behavior visible to users), and feature flags are the control plane that makes that separation safe. This module teaches flag taxonomy, LaunchDarkly and AWS AppConfig patterns, canary and blue-green releases, dark launches, kill switches, flag hygiene, and how flags compose with Week 6 circuit breakers during incidents.

---

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                         ║
╟──────────────────────────────────────────────────────────────────╢
║                                                                  ║
║   1. Distinguish feature flags from configuration and            ║
║      choose the right control mechanism for runtime              ║
║      behavior vs environment settings                            ║
║                                                                  ║
║   2. Classify flags by type (release, ops, experiment,           ║
║      permission) and design evaluation context, targeting        ║
║      rules, and percentage rollouts correctly                    ║
║                                                                  ║
║   3. Implement LaunchDarkly-style patterns: segments,            ║
║      multivariate flags, prerequisites, and server-side          ║
║      evaluation with correct defaults and fallbacks              ║
║                                                                  ║
║   4. Configure AWS AppConfig for feature flags, safe             ║
║      deployments with validators, and agent/extension            ║
║      integration on ECS, EC2, and Lambda                         ║
║                                                                  ║
║   5. Design canary, blue-green, and dark launch strategies       ║
║      using ALB weighted routing, CodeDeploy, Istio, and          ║
║      shadow traffic — with rollback triggers                     ║
║                                                                  ║
║   6. Build kill switches that compose with circuit               ║
║      breakers (Week 6): operational tripping vs traffic          ║
║      splitting, fallback paths, and half-open probing            ║
║                                                                  ║
║   7. Maintain flag hygiene: naming, lifecycle, sunset            ║
║      deadlines, and technical debt controls that prevent         ║
║      permanent if/else graveyards in production code             ║
║                                                                  ║
║   8. Diagnose flag-related incidents: stuck-on flags,            ║
║      wrong cohort targeting, stale client caches, and            ║
║      percentage rollout math errors from metrics and logs        ║
╚══════════════════════════════════════════════════════════════════╝
```

**Prerequisite mental model.** Deployment puts code on disk. Release changes what users experience. A feature flag is a runtime branch that lets you decouple those two events. Progressive delivery is the discipline of moving from 0% to 100% exposure in measured steps, with observability gates at each step — the same instinct as a circuit breaker's half-open probe, applied to product risk instead of dependency health.

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Feature flags are just dynamic config"              ║
╟─────────────────────────────────────────────────────────────────────────╢
║   PARTIALLY WRONG. Configuration sets environment parameters            ║
║   (timeouts, pool sizes, API keys) that apply uniformly and             ║
║   change rarely. Feature flags control per-user or per-cohort           ║
║   behavior, change frequently, and carry product/experiment             ║
║   semantics. Using AppConfig for DB URLs is correct. Using              ║
║   AppConfig for "show new checkout to 5% of users in Oregon"            ║
║   without evaluation context is a category error.                       ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Ship the flag, leave it forever"                    ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. A release flag exists to gate incomplete work. Once            ║
║   the feature is fully rolled out, the flag MUST be removed             ║
║   and the dead branch deleted. Permanent flags are technical            ║
║   debt that doubles test matrix size and hides bugs behind              ║
║   untested code paths. LaunchDarkly's own guidance: flags               ║
║   older than 90 days without a sunset plan are a smell.                 ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Canary = feature flag"                              ║
╟─────────────────────────────────────────────────────────────────────────╢
║   INCOMPLETE. Canary releases route TRAFFIC to different                ║
║   binary versions (infrastructure layer). Feature flags route           ║
║   BEHAVIOR within the same binary (application layer). They             ║
║   compose: canary deploys v2 pods, feature flag inside v2               ║
║   enables the new UI for 10% of users on those pods.                    ║
║   Conflating them leads to "we canaried 5% but the flag is              ║
║   on for everyone on those pods" — wrong blast radius math.             ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Kill switch = flip flag to false"                   ║
╟─────────────────────────────────────────────────────────────────────────╢
║   TOO SIMPLE. A kill switch must: (a) default to safe when              ║
║   the flag service is unreachable, (b) propagate within                 ║
║   seconds not minutes, (c) have a documented fallback path,             ║
║   (d) be tested in game days. Flipping a flag that 40% of               ║
║   mobile clients cached 5 minutes ago does NOT kill the                 ║
║   feature for those users. Kill switches are operational                ║
║   controls — treat them like circuit breakers, not config.              ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Blue-green means zero downtime"                     ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG FOR STATEFUL SYSTEMS. Blue-green gives instant traffic          ║
║   switch for stateless apps. If green has a different schema,           ║
║   cache format, or event contract, switching 100% instantly             ║
║   causes data corruption. Blue-green requires backward-compatible       ║
║   migrations, expand-contract schema changes, and often a               ║
║   canary phase BEFORE the final switch.                                 ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Dark launch = feature flag off"                     ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Dark launch means code RUNS in production (writes              ║
║   to shadow tables, emits shadow metrics, calls dependencies            ║
║   in dry-run mode) but user-visible output is suppressed.               ║
║   Flag-off means code path is not executed at all. Dark                 ║
║   launch validates production load on new paths; flag-off               ║
║   validates nothing about production behavior.                          ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #7: "Percentage rollout is random per request"           ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Consistent percentage rollout requires STICKY                  ║
║   assignment: same user always gets same variant during the             ║
║   experiment. Random per request gives users a flickering               ║
║   experience and corrupts A/B metrics. Use hash(userId +                ║
║   flagKey) % 100 < rolloutPercentage.                                   ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #8: "Client-side flags are faster, so use them"          ║
╟─────────────────────────────────────────────────────────────────────────╢
║   DANGEROUS FOR SECURITY AND PRICING. Client-side evaluation            ║
║   exposes flag rules to the browser/mobile app. A user can              ║
║   enable premium features by editing local flag state.                  ║
║   Server-side evaluation for anything affecting auth,                   ║
║   billing, or data access. Client-side only for UI                      ║
║   experiments with no security boundary.                                ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Feature Flags vs Configuration — The Boundary

```
THE FUNDAMENTAL DISTINCTION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CONFIGURATION answers: "How should this service run in this environment?"
  FEATURE FLAGS answer: "Which behavior should this user see right now?"

  ┌────────────────────────┬─────────────────────┬─────────────────────┐
  │ Dimension              │ Configuration       │ Feature Flag        │
  ├────────────────────────┼─────────────────────┼─────────────────────┤
  │ Scope                  │ Environment-wide    │ Per-user/cohort     │
  │ Change frequency       │ Days to weeks       │ Minutes to hours    │
  │ Owner                  │ Platform/SRE        │ Product/Engineering │
  │ Evaluation             │ At startup / reload │ Per request/session │
  │ Rollback urgency       │ Planned             │ Instant (incident)  │
  │ Typical store          │ AppConfig, SSM,     │ LaunchDarkly,       │
  │                        │ Secrets Manager     │ AppConfig flags,    │
  │                        │                     │ Unleash, Flagsmith  │
  │ Example                │ DB pool size = 50   │ new-checkout = 5%   │
  │                        │ fraud API timeout   │ dark-mode-beta on   │
  │                        │ = 2s                │ for employees       │
  └────────────────────────┴─────────────────────┴─────────────────────┘

WHEN THEY OVERLAP:
  AWS AppConfig "feature flags" blur the line — a boolean flag in
  AppConfig can gate behavior. The distinction is INTENT and EVALUATION:
    → If you need user targeting, segments, experiments → flag platform
    → If you need uniform env settings with safe rollout → AppConfig config
    → If you need both → AppConfig for infra config, LaunchDarkly for
      product flags; never one system for everything without taxonomy

ANTI-PATTERN: "We'll use environment variables for feature flags"
  → Requires redeploy to change
  → No percentage rollout
  → No per-user targeting
  → No audit trail of who changed what when
  → Fine for kill switches in extreme simplicity; not fine for product
```

### Flag Taxonomy — Four Types You Must Classify

```
EVERY FLAG MUST HAVE A TYPE. Type determines lifecycle, owner, and cleanup.

  ╔════════════════════════════════════════════════════════════════════╗
  ║   TYPE 1: RELEASE FLAGS (short-lived)                              ║
  ╟────────────────────────────────────────────────────────────────────╢
  ║   Purpose: Hide incomplete features on trunk/main                  ║
  ║   Owner: Feature team                                              ║
  ║   Lifetime: Days to weeks — DELETE after 100% rollout              ║
  ║   Example: enable-new-payment-flow                                 ║
  ║   Default: false (safe)                                            ║
  ║   Risk if left: Dead code paths, untested regressions              ║
  ╠════════════════════════════════════════════════════════════════════╣
  ║   TYPE 2: OPS FLAGS / KILL SWITCHES (long-lived)                   ║
  ╟────────────────────────────────────────────────────────────────────╢
  ║   Purpose: Emergency disable without deploy                        ║
  ║   Owner: SRE + feature team                                        ║
  ║   Lifetime: Permanent until feature is retired                     ║
  ║   Example: enable-recommendations-api                              ║
  ║   Default: true (feature on) — flip to false kills feature         ║
  ║   Risk if misused: Ops flags become release flags (never cleaned)  ║
  ╠════════════════════════════════════════════════════════════════════╣
  ║   TYPE 3: EXPERIMENT FLAGS (medium-lived)                          ║
  ╟────────────────────────────────────────────────────────────────────╢
  ║   Purpose: A/B test, multivariate test, measure conversion         ║
  ║   Owner: Product + Data                                            ║
  ║   Lifetime: Until experiment concludes + code path merged          ║
  ║   Example: checkout-button-color → "green" | "blue" | "red"        ║
  ║   Default: control variant                                         ║
  ║   Risk: Peeking, underpowered tests, Simpson's paradox             ║
  ╠════════════════════════════════════════════════════════════════════╣
  ║   TYPE 4: PERMISSION FLAGS (long-lived)                            ║
  ╟────────────────────────────────────────────────────────────────────╢
  ║   Purpose: Entitlement, plan tier, beta access                     ║
  ║   Owner: Product / Identity                                        ║
  ║   Lifetime: Permanent (tied to billing/roles)                      ║
  ║   Example: premium-analytics-enabled                               ║
  ║   Default: false                                                   ║
  ║   Risk: Should often be authorization, not a flag — don't use      ║
  ║         flags where RBAC/ABAC belongs                              ║
  ╚════════════════════════════════════════════════════════════════════╝

NAMING CONVENTION (enforce in CI):
  release.{feature-name}          → must have sunset date in registry
  ops.{feature-name}              → must have runbook link
  experiment.{hypothesis-id}      → must have experiment end date
  permission.{capability-name}    → must map to auth system
```

### Flag Evaluation Architecture

```
SERVER-SIDE EVALUATION (production default):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  User Request
       │
       ▼
  ┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
  │ API Gateway │────►│ checkout-svc     │────►│ Flag SDK        │
  │ or ALB      │     │                  │     │ (server-side)   │
  └─────────────┘     │  context = {     │     │                 │
                      │    userId,       │     │  evaluates:     │
                      │    country,      │     │  new-checkout?  │
                      │    plan,         │     │  → true/false   │
                      │    requestId     │     │                 │
                      │  }               │     └────────┬────────┘
                      └──────────────────┘              │
                                                        │
                      ┌─────────────────────────────────┘
                      │
                      ▼
              ┌───────────────┐
              │ Flag Service  │  LaunchDarkly / AppConfig / Unleash
              │ (hosted)      │
              └───────────────┘

EVALUATION FLOW (per request):

  1. BUILD CONTEXT
     → Stable user key (userId, not sessionId — sessions rotate)
     → Anonymous: deviceId or hashed cookie (consistent bucketing)
     → Custom attributes: country, plan, accountAge, isEmployee

  2. SDK EVALUATES LOCALLY (after sync)
     → SDK maintains local copy of flag rules (streaming or poll)
     → Evaluation is in-process (microseconds) — no network per request
     → Network only for rule updates (SSE stream or 15-30s poll)

  3. APPLY RULES IN ORDER
     → Prerequisites (flag B requires flag A)
     → Individual targeting (user X always gets true)
     → Segment rules (country=US AND plan=premium)
     → Percentage rollout (hash bucket)
     → Default rule (fallback)

  4. RETURN VARIANT + REASON
     → Log evaluation reason for debugging ("matched segment beta-testers")
     → Emit exposure event for experiments (LaunchDarkly analytics)

DEFAULT AND OFFLINE BEHAVIOR (critical):

  ┌────────────────────────┬────────────────────────────────────────┐
  │ Flag type              │ Default when SDK cannot reach service  │
  ├────────────────────────┼────────────────────────────────────────┤
  │ Release flag           │ false (safe — old behavior)            │
  │ Ops kill switch        │ true (feature stays on — avoid false   │
  │                        │ outage from flag service down)         │
  │ Experiment             │ control variant                        │
  │ Permission             │ false (deny)                           │
  └────────────────────────┴────────────────────────────────────────┘

  The kill-switch default=true vs release default=false distinction
  is the most commonly misconfigured setting in production incidents.
```

### Percentage Rollout — Sticky Bucketing Math

```
GOAL: Roll out to 5% of users. Each user consistently in or out.

CORRECT: Deterministic hash bucketing

  bucket = hash(flagKey + ":" + userKey) % 10000   // basis points
  inRollout = (bucket < rolloutPercentage * 100)

  Example: rolloutPercentage = 5.0
    bucket 0-499   → in rollout (5%)
    bucket 500-9999 → not in rollout

WHY NOT random() per request:
  User sees new checkout on request 1, old checkout on request 2.
  Support tickets: "It works sometimes."
  A/B conversion metrics are meaningless.

WHY NOT userId % 100 < 5:
  Different flags get correlated cohorts (same 5% users in every test).
  hash(flagKey + userKey) decorrelates across flags.

ROLLOUT SCHEDULE (typical production cadence):

  Day 0:   0%   — dark launch / internal only (employee segment)
  Day 1:   1%   — canary cohort, watch error budget
  Day 2:   5%   — early adopters
  Day 4:   25%  — if metrics clean
  Day 7:   50%
  Day 10:  100% — remove flag, delete old path

  At each step, PAUSE if:
    → Error rate delta > 0.1% vs control
    → p99 latency delta > 20% vs control
    → Business metric (conversion) drops > 2% (pre-registered threshold)
```

### LaunchDarkly Patterns — Production Mental Model

```
LaunchDarkly is the reference architecture for managed feature flags.
Even if you use AppConfig or Unleash, understand these patterns.

CORE ENTITIES:

  ┌────────────┐     ┌────────────┐     ┌────────────────┐
  │ Project    │────►│ Environment│────►│ Flag           │
  │ (product)  │     │ prod/stage │     │ boolean/string │
  └────────────┘     └────────────┘     │ /json/number   │
                                        └───────┬────────┘
                                                │
                    ┌───────────────────────────┼───────────────────┐
                    ▼                           ▼                   ▼
              ┌──────────┐              ┌────────────┐      ┌────────────┐
              │ Segments │              │ Targeting  │      │ Prerequisites│
              │ (reusable│              │ rules per  │      │ (flag deps) │
              │  cohorts)│              │ environment│      └────────────┘
              └──────────┘              └────────────┘

PATTERN 1: Employee dogfooding segment
  Segment "employees": email ends with @company.com
  Rule: IF user in employees → true
  Rule: IF percentage rollout → 0%
  → Only employees see feature until ready for external rollout

PATTERN 2: Geographic canary
  Segment "us-west-beta": country=US AND region=west
  Rule 1: IF us-west-beta → true (100%)
  Rule 2: IF country=US → 10%
  Rule 3: default → false
  → Geo-fenced progressive delivery without separate deployments

PATTERN 3: Multivariate experiment
  Flag "checkout-cta-variant" type: string
  Variations: "control" | "urgent-copy" | "social-proof"
  Allocation: 34% / 33% / 33%
  → SDK returns variation name; app renders matching UI
  → LaunchDarkly Experimentation tracks conversion per variation

PATTERN 4: Flag prerequisites (dependency chain)
  Flag "new-checkout-enabled" prerequisite: "payments-v2-ready" = true
  → Prevents enabling checkout UI before payment backend is ready
  → Misconfiguration: prerequisite circular dependency (A requires B, B requires A)

PATTERN 5: Migration flag (strangler fig)
  Flag "read-from-new-orders-table" percentage rollout
  Code path:
    if flag → query orders_v2
    else    → query orders_v1
  → Pair with dual-write until read migration complete
  → Sunset: remove v1 read path, then remove flag

SDK INTEGRATION PATTERN (server-side, Java example):

  LDContext context = LDContext.builder(userId)
      .set("country", request.getCountry())
      .set("plan", user.getPlanTier())
      .set("accountAgeDays", user.getAccountAgeDays())
      .build();

  boolean useNewCheckout = ldClient.boolVariation(
      "release.new-checkout",
      context,
      false   // safe default
  );

STREAMING UPDATES:
  LaunchDarkly SDK opens SSE connection to stream flag changes.
  Rule change propagates to all SDK instances in ~200-500ms.
  NOT instant — plan for propagation delay in kill switch runbooks.

AUDIT AND GOVERNANCE:
  Every flag change logged: who, when, old value, new value, reason.
  Approval workflows for production environment changes.
  Code references integration: PR shows which flags the diff touches.
```

### AWS AppConfig — Configuration and Feature Flags

```
AWS AppConfig is AWS-native dynamic configuration with:
  → Hosted configuration versions
  → Deployment strategies (canary, linear, all-at-once)
  → Validators (JSON Schema, Lambda)
  → Feature flag extension (boolean flags in hosted config)
  → Agents for EC2/ECS; Lambda extension for serverless

WHEN TO USE APPCONFIG vs LAUNCHDARKLY:

  ┌────────────────────────────┬──────────────┬──────────────────┐
  │ Need                       │ AppConfig    │ LaunchDarkly     │
  ├────────────────────────────┼──────────────┼──────────────────┤
  │ Per-user targeting         │ Poor         │ Excellent        │
  │ A/B experiments            │ Manual       │ Built-in         │
  │ AWS-native, no SaaS        │ Yes          │ No               │
  │ Infra config (timeouts)    │ Excellent    │ Overkill         │
  │ Kill switch (uniform)      │ Good         │ Good             │
  │ Percentage rollout         │ DIY in app   │ Built-in         │
  │ Cost at 100M evals/month   │ Low          │ $$$              │
  └────────────────────────────┴──────────────┴──────────────────┘

APPCONFIG ARCHITECTURE:

  ┌─────────────────┐
  │ AppConfig       │  Application
  │                 │   └─ Environment (prod, staging)
  │                 │       └─ Profile (feature-flags, service-config)
  │                 │           └─ Hosted config version
  └────────┬────────┘
           │ deployment strategy (linear 10% every 5 min)
           ▼
  ┌─────────────────┐     ┌─────────────────┐
  │ AppConfig Agent │────►│ Your application│
  │ (sidecar on ECS)│     │ reads local     │
  │ or Lambda ext   │     │ cached config   │
  └─────────────────┘     └─────────────────┘

HOSTED FEATURE FLAGS FORMAT (AppConfig):

  {
    "flags": {
      "enable-recommendations": {
        "name": "enable-recommendations"
      },
      "new-checkout-flow": {
        "name": "new-checkout-flow"
      }
    },
    "values": {
      "enable-recommendations": true,
      "new-checkout-flow": false
    },
    "version": "1"
  }

  Note: AppConfig flags are BOOLEAN and UNIFORM per environment.
  Percentage rollout requires application-side logic or a separate system.

DEPLOYMENT STRATEGIES (AppConfig):

  ┌────────────────────┬────────────────────────────────────────────┐
  │ Strategy           │ Behavior                                   │
  ├────────────────────┼────────────────────────────────────────────┤
  │ AllAtOnce          │ 100% immediately — dev/staging only        │
  │ Linear             │ 10% → 20% → ... → 100% over bake periods   │
  │ Exponential        │ 1% → 2% → 4% → 8% → ... → 100%             │
  │ Canary (custom)    │ 1% bake 10min → 50% bake 30min → 100%      │
  └────────────────────┴────────────────────────────────────────────┘

  Linear10PercentEvery1Minute:
    → Each minute, 10% more targets receive new config version
    → CloudWatch alarm on error rate can trigger auto-rollback
    → AppConfig stops deployment and reverts to previous version

VALIDATORS (prevent bad config from deploying):

  1. JSON Schema validator — structure check before any target sees it
  2. Lambda validator — custom logic:
       → Reject if new-checkout=true but payments-v2-ready=false
       → Reject if timeout < 100ms
  3. Syntactic vs semantic: schema catches typos; Lambda catches logic

APPCONFIG AGENT ON ECS (sidecar pattern):

  Task definition has two containers:
    1. appconfig-agent (reads from AppConfig, serves localhost:2772)
    2. application (polls http://localhost:2772/applications/.../config)

  Agent handles:
    → Polling AppConfig for new versions
    → Local disk cache (survives brief AppConfig outage)
    → Deployment strategy enforcement at target level
```

### Progressive Delivery — The Release Spectrum

```
DEPLOYMENT ≠ RELEASE

  DEPLOYMENT: New code version running on some servers
  RELEASE:    New behavior affecting some users

  Progressive delivery = controlled movement along the release spectrum.

  ╔════════════════════════════════════════════════════════════════════╗
  ║   RELEASE SPECTRUM (increasing user exposure)                      ║
  ╟────────────────────────────────────────────────────────────────────╢
  ║                                                                    ║
  ║   [1] Dark Launch ──► code runs, output hidden                     ║
  ║         │                                                          ║
  ║   [2] Internal ─────► employees / beta segment only                ║
  ║         │                                                          ║
  ║   [3] Canary ───────► small % traffic or users                     ║
  ║         │                                                          ║
  ║   [4] Ring Deploy ──► geographic or tenant rings                   ║
  ║         │                                                          ║
  ║   [5] Full Release ► 100% users                                    ║
  ║                                                                    ║
  ╚════════════════════════════════════════════════════════════════════╝

OBSERVABILITY GATES between each step:
  → Automated: CloudWatch alarm, Prometheus burn rate, SLO error budget
  → Manual: product sign-off, support briefing
  → Rollback: automatic on gate failure (CodeDeploy, Argo Rollouts, Flagger)
```

### Canary Releases — Infrastructure-Level Progressive Delivery

```
CANARY = route a SMALL PERCENTAGE of traffic to NEW VERSION (new pods/ASG).

  ┌─────────────┐
  │     ALB     │
  └──────┬──────┘
         │
    ┌────┴────┐
    │ weights │
    ▼         ▼
  ┌─────┐   ┌─────┐
  │ v1  │   │ v2  │
  │ 95% │   │  5% │
  │ TG  │   │ TG  │
  └─────┘   └─────┘

AWS CODEDEPLOY ECS/Lambda CANARY:

  Deployment configuration:
    Canary10Percent5Minutes:
      → 10% traffic to new task set for 5 minutes
      → CloudWatch alarm monitors error rate
      → If alarm → automatic rollback to previous task set
      → If clean → continue to 100%

  Hooks:
    BeforeAllowTraffic: run integration tests against canary TG
    AfterAllowTraffic: smoke tests, synthetic canaries

ISTIO TRAFFIC SPLITTING (Kubernetes):

  apiVersion: networking.istio.io/v1beta1
  kind: VirtualService
  spec:
    http:
      - route:
          - destination: { host: checkout-svc, subset: v1 }
            weight: 95
          - destination: { host: checkout-svc, subset: v2 }
            weight: 5

METRICS TO WATCH DURING CANARY (compare v1 vs v2):

  ┌────────────────────────┬─────────────────────────────────────────┐
  │ Metric                 │ Threshold to halt canary                │
  ├────────────────────────┼─────────────────────────────────────────┤
  │ HTTP 5xx rate          │ v2 > v1 + 0.1% absolute                 │
  │ p99 latency            │ v2 > v1 × 1.2                           │
  │ Business conversion    │ v2 < v1 - 2% (pre-registered)           │
  │ Saturation             │ v2 CPU/memory > 85% at 5% traffic       │
  │                        │ (indicates can't handle full load)      │
  └────────────────────────┴─────────────────────────────────────────┘

CANARY + FEATURE FLAG COMPOSITION:

  Scenario: v2 has new checkout code, but feature not ready for all v2 users.

  Layer 1 (infra): ALB routes 10% traffic to v2 pods
  Layer 2 (app):   flag "release.new-checkout" = 50% on v2 pods only

  Effective exposure: 10% × 50% = 5% of total users

  BLAST RADIUS MATH — always multiply layers, never add.
```

### Blue-Green Deployments — Instant Switch, Hidden Complexity

```
BLUE-GREEN = two FULL environments; switch traffic at load balancer.

  ┌─────────────┐
  │     ALB     │
  └──────┬──────┘
         │
    ┌────┴────────────────┐
    ▼                     ▼
  ┌──────────┐        ┌──────────┐
  │ BLUE v1  │        │ GREEN v2 │
  │ (live)   │        │ (idle)   │
  │ 100%     │        │ 0%       │
  └──────────┘        └──────────┘

  Switch: change ALB listener rule target from blue TG to green TG.
  Rollback: switch back (seconds, not minutes).

ADVANTAGES:
  → Instant rollback (traffic switch)
  → Full environment tested before receiving traffic
  → No mixed-version responses on stateless APIs (during switch)

DISADVANTAGES:
  → 2× infrastructure cost during deployment window
  → Database schema migrations break the model
  → Cache warming: green starts cold → latency spike on switch
  → WebSocket/long-poll: existing connections stay on blue until drain

DATABASE MIGRATION WITH BLUE-GREEN (expand-contract):

  Phase 1: Deploy green with schema v2 ADDITIVE only (new nullable column)
  Phase 2: Blue writes to old column; green writes to both
  Phase 3: Backfill job copies old → new
  Phase 4: Switch traffic to green
  Phase 5: Blue decommissioned; drop old column in next release

  NEVER switch 100% to green with breaking schema change.

ALB BLUE-GREEN PATTERN (AWS):

  Listener rule priority 1: forward to green TG (weight 0 initially)
  Use weighted forward action:
    forward-config:
      target-groups:
        - target-group-arn: blue-tg, weight: 100
        - target-group-arn: green-tg, weight: 0

  Switch: update weights to blue:0, green:100
  Drain: deregistration delay (default 300s) waits for in-flight requests

ROUTE 53 FAILOVER (DNS-level blue-green):
  Primary record → blue ALB
  Secondary record → green ALB (health check gated)
  Switch: update health check or weighted routing policy
  Slower than ALB switch (DNS TTL propagation 60-300s)
```

### Dark Launches — Production Load Without User Impact

```
DARK LAUNCH = new code executes in production path but output is discarded
              or written to shadow storage.

USE CASES:
  → Validate new recommendation model against production traffic
  → Load-test new payment validator without charging cards
  → Compare old vs new query results (shadow read)

PATTERN 1: Shadow traffic (duplicate request)

  User request ──► production handler ──► response to user
                │
                └──► async: shadow handler ──► discard response
                                              └──► emit diff metrics

  ALB/API Gateway cannot do this alone — application or service mesh.

  Istio mirror traffic:
    route:
      - destination: prod-svc
    mirror:
      host: shadow-svc
    mirrorPercentage:
      value: 100.0    # mirror all prod traffic to shadow

PATTERN 2: Shadow write (dual write, read from old)

  Write path: persist to orders_v1 AND orders_v2 (v2 write async)
  Read path:  always return orders_v1
  Compare:    background job diffs v1 vs v2 reads

PATTERN 3: Feature flag "dark mode"

  Flag "recommendations-v2-dark" = true for 100% internal traffic
  Code:
    results_v2 = computeRecommendationsV2(user)
    if (!userVisibleFlag) {
      emitMetric("dark.reco.v2.latency", latency)
      emitMetric("dark.reco.v2.quality", ndcgScore)
      return results_v1   // user sees old
    }
    return results_v2

DARK LAUNCH RISKS:
  → Shadow path can overload dependencies (recommendations DB)
  → Shadow write can corrupt data if not truly isolated
  → Must use bulkhead (Week 6) on shadow path — separate thread pool
  → Circuit breaker on shadow must not trip production circuit
```

### Kill Switches — Operational Circuit Breakers for Features

```
KILL SWITCH = instant disable of a feature path without deployment.

PARALLEL TO WEEK 6 CIRCUIT BREAKERS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────────┬────────────────────┬─────────────────────┐
  │ Concept                │ Circuit Breaker    │ Kill Switch         │
  │                        │ (Week 6)           │ (this module)       │
  ├────────────────────────┼────────────────────┼─────────────────────┤
  │ Protects against       │ Dependency failure │ Feature bug /       │
  │                        │                    │ product incident    │
  │ Trips on               │ Error rate, latency│ Human decision or   │
  │                        │                    │ automated metric    │
  │ Effect                 │ Stop calls to dep  │ Stop feature code   │
  │                        │                    │ path, use fallback  │
  │ Recovery               │ Half-open probe    │ Gradual re-enable   │
  │                        │                    │ (canary % on flag)  │
  │ Default when control   │ Fail-fast (open)   │ Depends on type     │
  │ plane down             │                    │ (see defaults)      │
  └────────────────────────┴────────────────────┴─────────────────────┘

KILL SWITCH HIERARCHY (disable fastest path first):

  Level 1: Edge kill (CloudFront Function / WAF rule)
    → Block URL path /api/recommendations/* at edge
    → Fastest propagation, no app deploy
    → Coarse: kills entire endpoint

  Level 2: Flag kill (ops.enable-recommendations = false)
    → App returns cached/default recommendations
    → Seconds to propagate (SDK stream)
    → Surgical: kills feature, not unrelated paths

  Level 3: Circuit breaker (recommendations-svc)
    → Stop calling failing dependency
    → Automatic on error rate
    → Protects recommendations-svc from overload

  Level 4: Scale down / isolate
    → Remove recommendations-svc from load balancer
    → Last resort

COMPOSED INCIDENT RESPONSE:
  Bug in recommendations algorithm (bad results, not errors):
    → Circuit breaker WON'T trip (200 OK, wrong content)
    → Kill switch Level 2: flip ops.enable-recommendations
    → Fallback: popular items static list (precomputed, cached)

  recommendations-svc returning 503:
    → Circuit breaker trips automatically (Week 6)
    → Kill switch optional (redundant if fallback exists)
    → Both can run: CB protects dependency, kill switch protects UX

KILL SWITCH RUNBOOK REQUIREMENTS:
  1. Flag name documented in service README
  2. Default value when flag service unreachable
  3. Fallback behavior tested quarterly
  4. Propagation time measured (SDK stream latency)
  5. Mobile client cache TTL documented (may lag server kill)
```

### Flag Hygiene and Technical Debt

```
FLAG HYGIENE PROGRAM:
━━━━━━━━━━━━━━━━━━━━━

  REGISTRY (required fields per flag):
    flag_key, type, owner, created_date, sunset_date,
    runbook_link, services_referencing, last_evaluated_date

  CI CHECKS:
    → PR adds flag reference → must add registry entry
    → Flag past sunset_date → build fails
    → Flag at 100% rollout for 14 days → warning to remove

  QUARTERLY FLAG AUDIT:
    → Export all flags from LaunchDarkly/AppConfig
    → Cross-reference codebase (grep flag keys)
    → Orphan flags (in platform, not in code) → delete
    → Orphan code (in code, not in platform) → delete
    → Stale release flags → schedule removal sprint

TECHNICAL DEBT PATTERNS:

  DEBT 1: Nested flags
    if (flagA) {
      if (flagB) {
        if (flagC) { ... }
      }
    }
    → 2^n test combinations. Collapse into single flag or remove deps.

  DEBT 2: Flag as permanent config
    if (enableNewCheckout) { ... }  // true since 2022
    → Delete flag, make new path the only path.

  DEBT 3: Divergent defaults
    Server default: false. Mobile SDK default: true.
    → Offline mobile users get wrong behavior.

  DEBT 4: Flag in 47 microservices
    → Centralize evaluation at BFF/gateway where possible
    → Pass resolved variant in internal header (X-Feature-Variant)

  DEBT 5: Experiment without hypothesis
    → "Let's A/B test button color" with no power analysis
    → 2 weeks, inconclusive, flag stays forever

REMOVAL CHECKLIST (when rolling to 100%):
  □ Confirm 100% rollout for 7+ days
  □ Confirm no open incidents referencing flag
  □ Remove dead code branch (old path)
  □ Remove flag from SDK calls
  □ Remove flag from platform
  □ Remove registry entry
  □ Update runbook
  □ Deploy (this IS a deploy — but behavior unchanged)
```

### Connection to Week 6 — Circuit Breakers and Progressive Delivery

```
THE COMPOSITION MODEL:
━━━━━━━━━━━━━━━━━━━━

  Progressive delivery controls HOW MUCH of the new thing runs.
  Circuit breakers control WHETHER to keep calling a sick dependency.
  Kill switches control WHETHER to execute a feature path at all.

  HALF-OPEN IS A CANARY:
    Circuit breaker half-open sends 5 probe requests to recovering dep.
    Feature flag percentage rollout sends 5% users to new feature.
    Same instinct: small exposure, measure, expand or retreat.

  FALLBACK IS FLAG-OFF BEHAVIOR:
    Circuit open → fraudFallback() returns MANUAL_REVIEW
    Flag off     → return legacy checkout UI
    Both must be tested. Untested fallback = incident extends.

  RETRY STORM + PARTIAL ROLLOUT:
    New feature at 5% has a bug causing retry loop.
    5% of users × 3 retries = amplification within cohort.
    Monitor per-cohort error rates, not just global.
    Halt rollout before increasing percentage.

  BULKHEAD + DARK LAUNCH:
    Shadow recommendation path MUST have separate thread pool.
    Shadow latency must not exhaust production pool (Week 6 Failure 3).

  TIMEOUT BUDGET + FLAG EVALUATION:
    Flag SDK evaluation: <1ms local.
    If you call flag service per request (anti-pattern): add timeout
    100ms max, fallback to default, don't block checkout for flags.

  DECORATOR ORDER WITH FLAGS:
    Request → Flag evaluation → Circuit breaker → Retry → Service call
    If flag disables feature, never call service (CB stays closed).
```

---

## Concrete Examples

### LaunchDarkly — Server-Side Java SDK Integration

```java
// build.gradle
// implementation 'com.launchdarkly:launchdarkly-java-server-sdk:7.+'

@Configuration
public class LaunchDarklyConfig {

    @Bean(destroyMethod = "close")
    public LDClient ldClient(@Value("${launchdarkly.sdk-key}") String sdkKey) {
        LDConfig config = new LDConfig.Builder()
            .startWaitDuration(Duration.ofSeconds(5))
            .build();
        return new LDClient(sdkKey, config);
    }
}
```

```java
@Service
public class CheckoutService {

    private final LDClient ldClient;
    private final LegacyCheckoutHandler legacyHandler;
    private final NewCheckoutHandler newHandler;

    public CheckoutResponse processCheckout(CheckoutRequest req, User user) {
        LDContext context = LDContext.builder(String.valueOf(user.getId()))
            .kind("user")
            .set("email", user.getEmail())
            .set("country", user.getCountry())
            .set("plan", user.getPlanTier())
            .set("accountAgeDays", user.getAccountAgeDays())
            .privateAttributes("email")   // don't send email to LD analytics
            .build();

        boolean useNewCheckout = ldClient.boolVariation(
            "release.new-checkout",
            context,
            false   // safe default: legacy path
        );

        if (useNewCheckout) {
            return newHandler.process(req, user);
        }
        return legacyHandler.process(req, user);
    }
}
```

```java
// Multivariate experiment — checkout CTA copy
public String getCheckoutCtaCopy(User user) {
    LDContext context = buildContext(user);
    String variant = ldClient.stringVariation(
        "experiment.checkout-cta-q3-2026",
        context,
        "control"
    );
    return switch (variant) {
        case "urgent"       -> "Complete your order now — limited stock!";
        case "social-proof" -> "Join 2M customers who checked out today";
        default             -> "Proceed to checkout";
    };
}
```

```
LAUNCHDARKLY PRODUCTION CHECKLIST:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  □ SDK key is server-side SDK key (not client-side ID)
  □ Safe defaults match flag type (release=false, ops=true)
  □ User key is stable (userId, not sessionId)
  □ Private attributes marked for PII fields
  □ Health check: ldClient.isInitialized() before serving traffic
  □ Graceful shutdown: ldClient.close() on SIGTERM
  □ Flag keys namespaced: release.*, ops.*, experiment.*
  □ Exposure events tracked for experiment flags
```

### AWS AppConfig — Complete ECS Setup

```bash
# 1. Create AppConfig application, environment, profile
aws appconfig create-application \
  --name checkout-service \
  --description "Checkout service configuration and flags"

export APP_ID=$(aws appconfig list-applications \
  --query "Items[?Name=='checkout-service'].Id" --output text)

aws appconfig create-environment \
  --application-id $APP_ID \
  --name production \
  --description "Production environment"

export ENV_ID=$(aws appconfig list-environments \
  --application-id $APP_ID \
  --query "Items[?Name=='production'].Id" --output text)

aws appconfig create-configuration-profile \
  --application-id $APP_ID \
  --name feature-flags \
  --location-uri hosted \
  --type AWS.AppConfig.FeatureFlags

export PROFILE_ID=$(aws appconfig list-configuration-profiles \
  --application-id $APP_ID \
  --query "Items[?Name=='feature-flags'].Id" --output text)
```

```json
// feature-flags-v3.json — hosted configuration
{
  "flags": {
    "enable-recommendations": {
      "name": "enable-recommendations",
      "description": "Ops kill switch for recommendations feature"
    },
    "release-new-checkout": {
      "name": "release-new-checkout",
      "description": "Release flag for checkout v2 UI"
    }
  },
  "values": {
    "enable-recommendations": true,
    "release-new-checkout": false
  },
  "version": "3"
}
```

```bash
# 2. Create hosted configuration version
aws appconfig create-hosted-configuration-version \
  --application-id $APP_ID \
  --configuration-profile-id $PROFILE_ID \
  --content fileb://feature-flags-v3.json \
  --content-type "application/json"

export VERSION=$(aws appconfig list-hosted-configuration-versions \
  --application-id $APP_ID \
  --configuration-profile-id $PROFILE_ID \
  --query "Items[0].VersionNumber" --output text)

# 3. Create deployment strategy (linear rollout)
aws appconfig create-deployment-strategy \
  --name Linear20PercentEvery2Minutes \
  --deployment-duration-in-minutes 10 \
  --growth-factor 20 \
  --growth-type LINEAR \
  --final-bake-time-in-minutes 5 \
  --replicate-to SSM_DOCUMENT

export STRATEGY_ID=$(aws appconfig list-deployment-strategies \
  --query "Items[?Name=='Linear20PercentEvery2Minutes'].Id" --output text)

# 4. Deploy with validators
aws appconfig start-deployment \
  --application-id $APP_ID \
  --environment-id $ENV_ID \
  --configuration-profile-id $PROFILE_ID \
  --configuration-version $VERSION \
  --deployment-strategy-id $STRATEGY_ID
```

```yaml
# ECS task definition — AppConfig agent sidecar
# task-definition.json (excerpt)
containerDefinitions:
  - name: appconfig-agent
    image: public.ecr.aws/aws-appconfig/aws-appconfig-agent:2.x
    essential: true
    portMappings:
      - containerPort: 2772
        protocol: tcp
    environment:
      - name: SERVICE_REGION
        value: us-east-1
    logConfiguration:
      logDriver: awslogs
      options:
        awslogs-group: /ecs/appconfig-agent
        awslogs-region: us-east-1
        awslogs-stream-prefix: agent

  - name: checkout-service
    image: 123456789.dkr.ecr.us-east-1.amazonaws.com/checkout:v2.4.1
    dependsOn:
      - containerName: appconfig-agent
        condition: HEALTHY
    environment:
      - name: APPCONFIG_AGENT_URL
        value: http://127.0.0.1:2772
      - name: APPCONFIG_APPLICATION
        value: checkout-service
      - name: APPCONFIG_ENVIRONMENT
        value: production
      - name: APPCONFIG_PROFILE
        value: feature-flags
```

```python
# Application polling AppConfig agent (Python)
import requests
import time

AGENT_URL = "http://127.0.0.1:2772"
CONFIG_URL = (
    f"{AGENT_URL}/applications/checkout-service/"
    f"environments/production/configurations/feature-flags"
)

class FeatureFlags:
    def __init__(self):
        self._config = {}
        self._version = None
        self._load()

    def _load(self):
        resp = requests.get(CONFIG_URL, timeout=2)
        resp.raise_for_status()
        data = resp.json()
        self._config = data.get("values", {})
        self._version = data.get("version")

    def refresh(self):
        try:
            self._load()
        except Exception:
            pass  # keep stale config — agent caches last good version

    def is_enabled(self, flag_name: str, default: bool = False) -> bool:
        return self._config.get(flag_name, default)

# Background refresh every 30s
flags = FeatureFlags()
```

```bash
# Lambda extension for AppConfig (serverless)
# Add layer: arn:aws:lambda:us-east-1:027255383542:layer:AWS-AppConfig-Extension:167

# Environment variables on Lambda function:
# AWS_APPCONFIG_APPLICATION=checkout-service
# AWS_APPCONFIG_ENVIRONMENT=production
# AWS_APPCONFIG_PROFILE=feature-flags

# In Lambda handler — extension serves localhost:2772 same as agent
curl http://localhost:2772/applications/checkout-service/environments/production/configurations/feature-flags
```

### Lambda Validator — Prevent Unsafe Flag Combinations

```python
# appconfig-validator-lambda/handler.py
import json

def handler(event, context):
    """
    AppConfig Lambda validator — rejects dangerous flag combinations.
    Event contains proposed configuration content.
    """
    content = json.loads(event.get("content", "{}"))
    values = content.get("values", {})

    errors = []

    # Rule 1: new checkout requires payments v2
    if values.get("release-new-checkout") is True:
        payments_profile = load_payments_config()  # read sibling profile
        if not payments_profile.get("payments-v2-ready"):
            errors.append(
                "release-new-checkout cannot be true when payments-v2-ready is false"
            )

    # Rule 2: recommendations kill switch must have fallback configured
    if values.get("enable-recommendations") is False:
        if not values.get("static-recommendations-fallback-ready"):
            errors.append(
                "Disabling recommendations requires static-recommendations-fallback-ready"
            )

    if errors:
        return {
            "valid": False,
            "errorMessage": "; ".join(errors)
        }
    return {"valid": True}
```

### ALB Weighted Canary — Terraform

```hcl
# alb-canary.tf — weighted target groups for manual canary

resource "aws_lb_target_group" "checkout_v1" {
  name     = "checkout-v1"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = var.vpc_id
  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
  }
}

resource "aws_lb_target_group" "checkout_v2" {
  name     = "checkout-v2"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = var.vpc_id
  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold   = 3
    interval            = 15
  }
}

resource "aws_lb_listener_rule" "checkout_canary" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 100

  action {
    type = "forward"
    forward {
      target_group {
        arn    = aws_lb_target_group.checkout_v1.arn
        weight = 95
      }
      target_group {
        arn    = aws_lb_target_group.checkout_v2.arn
        weight = 5
      }
      stickiness {
        enabled  = true
        duration = 3600
      }
    }
  }

  condition {
    path_pattern {
      values = ["/checkout/*"]
    }
  }
}
```

```bash
# Shift canary weights during bake period
aws elbv2 modify-listener \
  --listener-arn $LISTENER_ARN \
  --default-actions Type=forward,ForwardConfig='{
    "TargetGroups":[
      {"TargetGroupArn":"'$V1_TG_ARN'","Weight":80},
      {"TargetGroupArn":"'$V2_TG_ARN'","Weight":20}
    ],
    "TargetGroupStickinessConfig":{"Enabled":true,"DurationSeconds":3600}
  }'
```

### CodeDeploy ECS Canary with CloudWatch Alarm Rollback

```json
// appspec.yaml for ECS
{
  "version": 0.0,
  "Resources": [
    {
      "TargetService": {
        "Type": "AWS::ECS::Service",
        "Properties": {
          "TaskDefinition": "arn:aws:ecs:us-east-1:123456789:task-definition/checkout:42",
          "LoadBalancerInfo": {
            "ContainerName": "checkout-service",
            "ContainerPort": 8080
          }
        }
      }
    }
  ]
}
```

```bash
# Deployment group with canary and alarm-based rollback
aws deploy create-deployment-group \
  --application-name checkout-ecs \
  --deployment-group-name checkout-prod \
  --service-role-arn arn:aws:iam::123456789:role/CodeDeployECSRole \
  --ecs-services clusterName=prod-cluster,serviceName=checkout-svc \
  --deployment-config-name CodeDeployDefault.ECSCanary10Percent5Minutes \
  --auto-rollback-configuration enabled=true,events=DEPLOYMENT_FAILURE,DEPLOYMENT_STOP_ON_ALARM \
  --alarm-configuration enabled=true,alarms=[{name=checkout-error-rate-alarm}]
```

### Istio — Canary + Circuit Breaker Composition

```yaml
# destination-rule-checkout.yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: checkout-svc
spec:
  host: checkout-svc.production.svc.cluster.local
  subsets:
    - name: v1
      labels: { version: v1 }
    - name: v2
      labels: { version: v2 }
  trafficPolicy:
    connectionPool:
      tcp: { maxConnections: 100 }
      http:
        http1MaxPendingRequests: 50
        maxRequestsPerConnection: 2
    outlierDetection:
      consecutive5xxErrors: 5
      interval: 10s
      baseEjectionTime: 30s
      maxEjectionPercent: 30
```

```yaml
# virtual-service-checkout-canary.yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: checkout-svc
spec:
  hosts: [checkout-svc]
  http:
    - match:
        - headers:
            x-canary-user:
              exact: "true"
      route:
        - destination: { host: checkout-svc, subset: v2 }
          weight: 100
    - route:
        - destination: { host: checkout-svc, subset: v1 }
          weight: 95
        - destination: { host: checkout-svc, subset: v2 }
          weight: 5
      timeout: 3s
```

```
NOTE: x-canary-user header set by app after flag evaluation.
Infra canary (5% to v2) × flag canary (header only on 50% of v2 users)
= precise blast radius control.
```

### Kill Switch with Circuit Breaker Fallback — Complete Java Path

```java
@Service
public class RecommendationsFacade {

    private final LDClient ldClient;
    private final RecommendationsClient recoClient;

    @CircuitBreaker(name = "recommendations", fallbackMethod = "fallbackRecommendations")
    @Bulkhead(name = "recommendations", type = Bulkhead.Type.SEMAPHORE)
    @TimeLimiter(name = "recommendations")
    public CompletableFuture<List<Item>> getRecommendations(User user) {
        if (!isRecommendationsEnabled(user)) {
            return CompletableFuture.completedFuture(getStaticFallback());
        }
        return CompletableFuture.supplyAsync(() -> recoClient.fetch(user));
    }

    private boolean isRecommendationsEnabled(User user) {
        LDContext ctx = LDContext.builder(String.valueOf(user.getId())).build();
        // Ops kill switch — default TRUE (don't kill feature when LD down)
        return ldClient.boolVariation("ops.enable-recommendations", ctx, true);
    }

    public CompletableFuture<List<Item>> fallbackRecommendations(User user, Exception ex) {
        // Circuit open OR timeout — static fallback
        log.warn("recommendations fallback for user {}: {}", user.getId(), ex.toString());
        return CompletableFuture.completedFuture(getStaticFallback());
    }

    private List<Item> getStaticFallback() {
        return StaticPopularItems.TOP_10;  // precomputed, CDN-cacheable
    }
}
```

```
THREE LAYERS IN THIS EXAMPLE:
  1. Kill switch (ops.enable-recommendations=false) → static fallback, no call
  2. Circuit breaker open → fallbackRecommendations(), static list
  3. Normal → live recommendations

TEST MATRIX (game day):
  □ Kill switch off, service healthy → live recs
  □ Kill switch off, service 503 → circuit opens → static
  □ Kill switch on, service healthy → static (no call)
  □ LD unreachable, kill switch default true → live recs attempt
  □ LD unreachable, kill switch default false → static
```

---

## Production Patterns

### Pattern 1: Trunk-Based Development with Release Flags

```
PROBLEM: Long-lived branches diverge, painful merges, delayed integration.

SOLUTION: All code on main, incomplete features behind release flags (default off).

WORKFLOW:
  Day 1:  Engineer merges checkout v2 UI behind release.new-checkout=false
  Day 5:  Backend merges payment v2 behind release.payments-v2=false
  Day 10: Enable payments-v2 for employees (segment rule)
  Day 12: Enable new-checkout for employees (prerequisite: payments-v2)
  Day 15: 1% external rollout
  Day 20: 100% → remove both flags in cleanup PR

GUARDRAILS:
  → Feature flags are NOT a substitute for code review
  → Each merge must be safe with flag OFF (default path tested in CI)
  → CI runs full test suite with all release flags false
  → Optional: CI matrix with all release flags true (integration path)
```

### Pattern 2: Ring Deployment (Geographic Progressive Delivery)

```
RING 0: Internal / staging (synthetic + employees)
RING 1: us-west-2 only (smallest prod region)
RING 2: us-east-1 (largest region — highest risk, do last or careful %)
RING 3: eu-west-1, ap-northeast-1
RING 4: Global 100%

IMPLEMENTATION OPTIONS:
  A) Separate AppConfig environments per region
  B) LaunchDarkly segment rules per AWS region attribute
  C) Separate ECS clusters per ring with independent deploy pipelines

ADVANTAGE over pure percentage:
  → Blast radius geographically bounded
  → Regulatory: EU data stays in EU ring until validated
  → Time-zone: deploy during ring's low-traffic hours

DISADVANTAGE:
  → Users traveling across regions see inconsistent features
  → Mitigate: flag evaluation uses account home region, not request region
```

### Pattern 3: Automated Rollout with Error Budget Gate

```
INTEGRATION: LaunchDarkly API + CloudWatch + Step Functions

  1. Pipeline deploys code with flag at 0%
  2. Step Function workflow:
       a. Set flag to 1%, wait 30 min
       b. Query CloudWatch: checkout_error_rate_v2 vs v1
       c. If delta < 0.1%: proceed to 5%
       d. If delta >= 0.1%: set flag to 0%, page on-call, fail pipeline
       e. Repeat until 100%
  3. Create cleanup ticket at 100%

METRIC REQUIREMENT:
  → Tag metrics with flag variant (OpenTelemetry attribute: feature.variant)
  → Without variant tags, automated gates are blind
```

### Pattern 4: Flag Evaluation at the BFF (Backend-for-Frontend)

```
PROBLEM: 12 microservices each call LaunchDarkly independently.
  → 12 SDK connections per user request (via trace)
  → Inconsistent evaluation if context differs slightly

SOLUTION: Evaluate once at API gateway / BFF, propagate resolved flags.

  api-gateway:
    context = buildContext(jwt)
    flags = {
      "new-checkout": ldClient.boolVariation("release.new-checkout", context, false),
      "reco-enabled": ldClient.boolVariation("ops.enable-recommendations", context, true)
    }
    inject headers:
      X-Feature-new-checkout: true
      X-Feature-reco-enabled: false

  downstream services:
    read headers, trust internal network boundary
    DO NOT re-evaluate (consistency)

SECURITY:
  → Strip X-Feature-* headers at ingress from internet
  → Only gateway may set them (mTLS between services)
```

### Pattern 5: Mobile Client Flag Strategy

```
MOBILE-SPECIFIC CONSTRAINTS:
  → App store release cycle: 1-7 days for user to update
  → SDK caches flag values locally (offline support)
  → Kill switch propagation delay: up to poll interval (default 15 min mobile)

RECOMMENDED SPLIT:
  ┌────────────────────────────┬─────────────────────────────────────────┐
  │ Concern                    │ Where to evaluate                       │
  ├────────────────────────────┼─────────────────────────────────────────┤
  │ UI layout experiments      │ Client-side OK (LaunchDarkly mobile SDK)│
  │ Pricing / entitlements     │ Server-side ONLY                        │
  │ Kill switches (critical)   │ Server-side + client cache short TTL    │
  │ New API endpoints          │ Server-side gate                        │
  └────────────────────────────┴─────────────────────────────────────────┘

MOBILE KILL SWITCH:
  → Server returns 503 on /api/recommendations when killed
  → Client shows cached static content
  → Do NOT rely on client-side flag alone for kill
```

### Pattern 6: Database Migration with Flags (Expand-Contract)

```
PHASE 1 — EXPAND (add new column/table):
  Deploy code that writes to BOTH orders_v1 and orders_v2
  Flag: migration.dual-write-orders = true (100% internal first)
  Read still from v1

PHASE 2 — BACKFILL:
  Batch job copies historical v1 → v2
  Verify row counts, checksum samples

PHASE 3 — SHADOW READ:
  Flag: migration.shadow-read-orders = 10%
  Read v2 async, compare to v1, emit mismatch metrics
  User still gets v1 response

PHASE 4 — CUTOVER READ:
  Flag: migration.read-orders-v2 = 1% → 100%
  Monitor error rate per cohort

PHASE 5 — CONTRACT:
  Stop dual write, read v2 only
  Remove flags, drop v1 table in separate maintenance window
```

### Pattern 7: Game Day — Kill Switch Drill

```
QUARTERLY DRILL (30 minutes):

  T+0:   Announce drill in #incidents (no customer impact expected)
  T+2:   Flip ops.enable-recommendations to false in production
  T+3:   Verify: reco API RPS drops to 0, static fallback serves
  T+5:   Verify: P99 checkout latency unchanged (no accidental coupling)
  T+7:   Verify: mobile app shows static recs within 15 min (cache TTL)
  T+10:  Flip flag back to true
  T+12:  Verify: reco RPS recovers, no circuit breaker stuck open
  T+15:  Document: actual propagation time vs runbook claim

SUCCESS CRITERIA:
  → Fallback served within 60 seconds (web)
  → Zero 5xx during drill
  → On-call runbook steps match reality
```

---

## Failure Modes

### Failure 1: Flag Stuck ON After Incident

```
SCENARIO:
  Friday 17:00: New checkout flag rolled to 100% Monday.
  Friday 17:30: Checkout bug discovered. On-call flips flag to false.
  Friday 17:31: Web users see legacy checkout. Incident mitigated.
  Monday 09:00: Bug fixed, deployed. Engineer forgets to re-enable flag.
  Tuesday: Product asks "why is new checkout not in metrics?"
  Wednesday: Someone sets flag to true without checking bug fix deployed.
  Thursday: Original bug recurs. Same incident, same flag flip.

  OR WORSE — STUCK ON VARIANT:
  Friday: Partial mitigation — reduce flag from 100% to 5% (not off).
  Weekend: 5% of users still hit bug.
  Monday: Engineer assumes flag is off. Doesn't check.
  Support tickets trickle in all weekend.

HOW TO DETECT:
  → Flag value in LaunchDarkly/AppConfig unchanged for days post-incident
  → Metric checkout_path=new flat at 0% or 5% while deploy shows v2 code
  → Grafana annotation missing for flag change during incident
  → Per-cohort error rate non-zero on "disabled" feature

FIX:
  → Incident runbook: flag changes require ticket with sunset action
  → Post-incident: explicit flag state in incident doc (current %, target %)
  → Alert: release flag at 0% for >7 days while code still references it
  → Automated: PagerDuty incident resolution triggers flag state review task
```

### Failure 2: Wrong Cohort Targeted

```
SCENARIO:
  Segment rule: "beta-testers" = email ends with @partner.com
  Typo in rule: @partners.com (extra 's')
  Intended: 200 partner users get early access
  Actual: 0 partner users; random users with @partners.com emails (3 users)
  OR: Rule uses OR instead of AND:
      country=US OR plan=premium
      Intended: US premium users only
      Actual: ALL US users + ALL global premium users (10× blast radius)

HOW TO DETECT:
  → Exposure events show unexpected user attributes
  → Support: "I see new UI but I'm not in beta"
  → Rollout percentage math doesn't match traffic split
    (flag says 5%, metrics show 12% on new path)
  → Segment member count in LaunchDarkly dashboard wrong vs expected

FIX:
  → Preview segment membership before enabling rule (LD segment export)
  → Dry-run mode: log would-match without serving new path
  → Require two-person review for production targeting changes
  → Integration test: known test users in/out of segment
```

### Failure 3: Stale Client-Side Flag Cache

```
SCENARIO:
  14:00: Kill switch flipped OFF for recommendations (server)
  14:00-14:15: Web clients using server-side eval → immediate fix
  14:00-14:45: Mobile clients cached flag=true (15 min poll interval)
  14:00-24:00: Mobile clients on airplane mode → cached flag forever
               until next network + poll

  User impact: 15-45 min continued bad recommendations on mobile
  Executive sees web fixed, mobile app store reviews still complaining

HOW TO DETECT:
  → Server-side kill effective (reco-svc RPS dropped)
  → Client analytics still show recommendation_v2 events
  → Mobile crash logs / API calls to /recommendations continue
  → Discrepancy between server flag state and client telemetry

FIX:
  → Server-side enforcement for kill switches (return 404/503 on killed API)
  → Never kill-switch UI-only on client for critical features
  → Reduce mobile poll interval for ops flags (1 min vs 15 min)
  → Force refresh endpoint: POST /api/flags/refresh on incident broadcast
```

### Failure 4: Percentage Rollout Math Error

```
SCENARIO:
  Engineer uses userId % 100 < 5 for 5% rollout.
  userId is auto-increment: recent signups (id 9,500,000+) are all
  in bucket 0-99 uniformly, but legacy users (id < 1000) are ALL in
  rollout (id % 100 < 5 for id 1-4 only — actually id 1,2,3,4 are in,
  but also id 101,102... — uniform distribution IF userId random)

  WORSE: userId % 10 < 5 → engineer thinks 5%, actual 50%.

  WORST: Multiple flags use same bucket → same users always in all experiments.

HOW TO DETECT:
  → Actual traffic split from metrics ≠ configured percentage
  → Chi-squared test on variant assignment fails uniformity
  → Same users appear in every experiment cohort (correlation)

FIX:
  → hash(flagKey + userKey) % 10000 with basis points
  → Unit test: 100K synthetic users, assert 5% ± 0.5%
  → Code review checklist for rollout logic
  → Use platform percentage rollout, not DIY
```

### Failure 5: Flag Service Outage — Wrong Defaults

```
SCENARIO:
  LaunchDarkly regional outage (rare but documented).
  Release flag default: false → safe, users stay on old checkout ✓
  Ops kill switch default: false (MISCONFIGURED — should be true)
  → Recommendations disabled for ALL users during LD outage
  → Revenue drop: no personalization, conversion -8%
  → Circuit breaker never trips (recommendations-svc healthy)

HOW TO DETECT:
  → ldClient.isInitialized() = false in health metrics
  → All users on default variant simultaneously
  → Flag evaluation latency = 0 (local default, no stream)
  → LD status page incident correlates with metric drop

FIX:
  → Audit defaults per flag type (release=false, ops=true, permission=false)
  → SDK persistent store: cache last known good values (LD supports this)
  → Alert on flag SDK initialization failure (not silent default)
  → Runbook: during LD outage, do NOT deploy (defaults dominate)
```

### Failure 6: Nested Flag Interaction Bug

```
SCENARIO:
  release.new-checkout = true (50% rollout)
  release.new-payments = true (50% rollout)
  Code requires BOTH for new flow:
    if (newCheckout && newPayments) { newFlow(); }
    else if (newCheckout) { brokenHybrid(); }  // calls v2 UI + v1 payments API
    else { legacyFlow(); }

  Probability of broken hybrid:
    P(newCheckout ∧ ¬newPayments) = 0.5 × 0.5 = 25%
    P(¬newCheckout ∧ newPayments) = 25%
  → 50% of users potentially in broken hybrid states

HOW TO DETECT:
  → Error rate spikes at 50% rollout (not gradual)
  → Support: "payment failed on new checkout screen"
  → Traces show v2 UI calling v1 payment endpoint

FIX:
  → Single flag for coupled features OR explicit prerequisite
  → LaunchDarkly prerequisite: new-checkout requires new-payments
  → Integration test matrix for flag combinations
  → Never ship orthogonal rollouts for coupled code paths
```

### Failure 7: AppConfig Deployment Without Validator

```
SCENARIO:
  Engineer deploys feature-flags config with typo:
    "enable-recommendations": "true"   (string, not boolean)
  App without schema validation parses as truthy in JavaScript (bug)
  Parses as error in Java (flag disabled — safe accident)
  Node.js service: "true" string is truthy → recommendations stay on
    when engineer intended to kill

HOW TO DETECT:
  → Config version deployed but behavior unchanged
  → Type mismatch in application logs
  → Validator would have rejected

FIX:
  → JSON Schema validator on AppConfig profile
  → Strong typing in application flag parser
  → Lambda validator for cross-flag logic
  → Never use truthy/falsy string parsing
```

### Failure 8: Canary Promoted Despite Latent Bug

```
SCENARIO:
  Canary 5% for 30 minutes. Error rate clean.
  Bug: memory leak in v2, grows over 4 hours.
  Promote to 100% at T+30min.
  T+4hr: OOMKilled pods, cascading failure.

  Canary bake time too short for slow-burn defects.

HOW TO DETECT:
  → Memory metric slope positive on v2, flat on v1
  → GC pause time growing on v2 pods only
  → Error rate clean but saturation climbing

FIX:
  → Canary bake: minimum 24h for major releases
  → Soak test: hold 5% over one full traffic cycle (includes peak)
  → Memory leak detectors in CI + canary observability
  → Automated promote only after N hours + error budget check
```

---

## SRE Diagnostic Toolkit

```
FEATURE FLAG DEBUGGING:
━━━━━━━━━━━━━━━━━━━━━━━

# Check LaunchDarkly flag state via API (production audit)
curl -s -X GET \
  "https://app.launchdarkly.com/api/v2/flags/checkout-service/release.new-checkout" \
  -H "Authorization: $LD_API_TOKEN" \
  | jq '.environments.production.on, .environments.production.fallthrough, .environments.production.rules'

# Evaluate flag for specific user (server-side debug endpoint — internal only)
curl -s -X POST "https://checkout.internal/debug/flags/evaluate" \
  -H "Content-Type: application/json" \
  -d '{"userId":"88421","flags":["release.new-checkout","ops.enable-recommendations"]}'

# Expected response:
# {
#   "release.new-checkout": { "value": false, "reason": "FALLTHROUGH", "version": 42 },
#   "ops.enable-recommendations": { "value": true, "reason": "OFF", "version": 42 }
# }


APPCONFIG DEBUGGING:
━━━━━━━━━━━━━━━━━━

# Current deployed configuration version
aws appconfig get-configuration \
  --application checkout-service \
  --environment production \
  --configuration feature-flags \
  --client-id diagnostic-$(date +%s) \
  /tmp/flags.json && cat /tmp/flags.json | jq .

# List deployment history
aws appconfig list-deployments \
  --application-id $APP_ID \
  --environment-id $ENV_ID \
  | jq '.Items[] | {DeploymentNumber, State, PercentageComplete, StartedAt}'

# Check if deployment stuck or rolling back
aws appconfig get-deployment \
  --application-id $APP_ID \
  --environment-id $ENV_ID \
  --deployment-number $DEPLOY_NUM \
  | jq '{State, PercentageComplete, ErrorMessage}'

# On ECS task — query local agent cache
aws ecs execute-command \
  --cluster prod-cluster \
  --task $TASK_ARN \
  --container checkout-service \
  --interactive \
  --command "curl -s http://127.0.0.1:2772/applications/checkout-service/environments/production/configurations/feature-flags"


METRICS TO QUERY (CloudWatch / Prometheus):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Flag evaluation count by variant (must be instrumented)
# Prometheus:
sum(rate(feature_flag_evaluation_total[5m])) by (flag, variant)

# Traffic split actual vs configured
sum(rate(http_requests_total{path="/checkout"}[5m])) by (version)
# Compare v1 vs v2 ratio against ALB weight or flag percentage

# Per-cohort error rate (critical for rollout gates)
sum(rate(http_requests_total{status=~"5..", feature_variant="new-checkout"}[5m]))
/
sum(rate(http_requests_total{feature_variant="new-checkout"}[5m]))

# LaunchDarkly SDK health
launchdarkly_sdk_initialized{service="checkout"} == 0  → page
launchdarkly_stream_disconnects_total spike → flag staleness risk

# AppConfig agent
appconfig_agent_config_load_success == 0 → using stale cache
appconfig_agent_polling_errors_total rate > 0


LOG PATTERNS (CloudWatch Logs Insights):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Flag evaluation reasons (structured log)
fields @timestamp, userId, flagKey, variant, reason
| filter flagKey = "release.new-checkout"
| stats count() by variant, reason
| sort count desc

# Users hitting unexpected code path
fields @timestamp, userId, path, feature_variant
| filter path = "/checkout/v2" and feature_variant = "legacy"
| limit 50

# Kill switch activation audit
fields @timestamp, actor, flagKey, oldValue, newValue
| filter eventType = "FLAG_CHANGE" and flagKey like /ops\./
| sort @timestamp desc


ALB CANARY DEBUGGING:
━━━━━━━━━━━━━━━━━━━━━

# Target group request count by version
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name RequestCount \
  --dimensions Name=TargetGroup,Value=targetgroup/checkout-v2/abc123 \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Sum

# Compare v1 vs v2 error rates
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name HTTPCode_Target_5XX_Count \
  --dimensions Name=TargetGroup,Value=$V2_TG \
  --period 60 --statistics Sum


CODEDEPLOY CANARY STATUS:
━━━━━━━━━━━━━━━━━━━━━━━━━

aws deploy get-deployment --deployment-id $DEPLOY_ID \
  | jq '{status: .deploymentInfo.status, error: .deploymentInfo.errorInformation}'

aws deploy list-deployment-instances --deployment-id $DEPLOY_ID \
  | jq '.instancesList[] | select(.status != "Succeeded")'


ISTIO CANARY SPLIT VERIFICATION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

kubectl exec -n production deploy/checkout-svc-v1 -c istio-proxy -- \
  pilot-agent request GET config_dump | jq '.configs[2].dynamicRouteConfigs'

# Request count by subset
istioctl proxy-stats deploy/checkout-svc-v1 -n production | grep checkout


COMMON "WHY IS THIS USER SEEING THE OLD UI?" DEBUGGING:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CHECK 1: Flag value for this user
    → Debug evaluate endpoint with userId
    → Check individual targeting overrides (user might be explicitly false)

  CHECK 2: Sticky bucket
    → hash(flagKey:userId) — user may be outside rollout %
    → User created before rollout expansion — bucket doesn't change

  CHECK 3: Client vs server evaluation mismatch
    → Mobile cached value vs server truth
    → Compare client analytics variant vs server logs

  CHECK 4: CDN caching HTML with embedded flag state
    → SSR page baked flag value into HTML at cache time
    → curl -sI page | grep -i age  → stale HTML serves old variant

  CHECK 5: Wrong environment SDK key
    → Staging SDK key in prod pod → wrong flag rules
    → grep LAUNCHDARKLY /etc/env in task definition

  CHECK 6: Prerequisite flag blocking
    → new-checkout true but payments-v2-ready false → prerequisite fails
    → LaunchDarkly evaluation reason: PREREQUISITE_FAILED
```

### Hands-On Exercises (Folded into SRE Toolkit)

```
EXERCISE 1: Evaluate Sticky Bucketing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  python3 -c "
  import hashlib
  def in_rollout(flag_key, user_id, pct):
      h = hashlib.sha256(f'{flag_key}:{user_id}'.encode()).hexdigest()
      bucket = int(h[:8], 16) % 10000
      return bucket < pct * 100
  for uid in ['alice','bob','carol','88421','99999']:
      print(uid, in_rollout('release.new-checkout', uid, 5.0))
  "
  # Run twice — same users always same result.


EXERCISE 2: Inspect AppConfig Agent Locally
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Run agent in Docker
  docker run -p 2772:2772 \
    -e SERVICE_REGION=us-east-1 \
    -e ROLE_ARN=arn:aws:iam::123456789:role/AppConfigAgentRole \
    public.ecr.aws/aws-appconfig/aws-appconfig-agent:2.x

  curl -s http://localhost:2772/applications/YOUR_APP/environments/production/configurations/feature-flags | jq .


EXERCISE 3: ALB Weight Math
━━━━━━━━━━━━━━━━━━━━━━━━━━

  # If v2 weight=5, v1 weight=95, and total RPS=10000:
  # v2 RPS ≈ 10000 × 5/(5+95) = 500
  # If flag inside v2 enables feature for 50%:
  # effective feature RPS ≈ 500 × 0.5 = 250 (2.5% of total)
```

---

## Decision Framework

```
WHICH CONTROL MECHANISM?
━━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────────────────┬─────────────────────────────────────┐
  │ Situation                      │ Use                                 │
  ├────────────────────────────────┼─────────────────────────────────────┤
  │ Hide incomplete feature on main│ Release flag (LaunchDarkly/Unleash) │
  │ Kill broken feature instantly  │ Ops flag + server-side enforcement  │
  │ A/B test button copy           │ Experiment flag (multivariate)      │
  │ Roll out new binary version    │ Canary (ALB/CodeDeploy/Istio)       │
  │ Instant rollback new version   │ Blue-green (ALB switch)             │
  │ Validate prod load, no UX      │ Dark launch (shadow traffic)        │
  │ Change DB connection pool size │ AppConfig (not a feature flag)      │
  │ Per-tenant feature entitlement │ Permission flag OR proper RBAC      │
  │ Uniform kill all API instances │ AppConfig ops flag OR edge block    │
  └────────────────────────────────┴─────────────────────────────────────┘

LAUNCHDARKLY vs AWS APPCONFIG vs SELF-HOSTED (Unleash/Flagsmith):

  ┌───────────────────┬─────────────┬─────────────┬──────────────────┐
  │ Criterion         │ LaunchDarkly│ AppConfig   │ Unleash (OSS)    │
  ├───────────────────┼─────────────┼─────────────┼──────────────────┤
  │ Per-user targeting│ Excellent   │ DIY         │ Good             │
  │ Experimentation   │ Built-in    │ DIY         │ Basic            │
  │ AWS integration   │ SDK only    │ Native      │ SDK              │
  │ Cost at scale     │ High        │ Low         │ Infra cost only  │
  │ Compliance/SaaS   │ SOC2, HIPAA │ AWS BAA     │ Self-managed     │
  │ Startup speed     │ Fastest     │ Medium      │ Medium           │
  └───────────────────┴─────────────┴─────────────┴──────────────────┘

CANARY vs BLUE-GREEN vs FEATURE FLAG ONLY:

  ┌──────────────────┬─────────────────────────────────────────────────┐
  │ Pattern          │ Choose when                                     │
  ├──────────────────┼─────────────────────────────────────────────────┤
  │ Feature flag only│ Same binary, behavior toggle, low infra cost    │
  │ Canary           │ New binary, want gradual traffic shift,         │
  │                  │ auto-rollback on metrics                        │
  │ Blue-green       │ Need instant rollback, stateless app,           │
  │                  │ can afford 2× capacity during switch            │
  │ Canary + flag    │ New binary with multiple features inside,       │
  │                  │ need precise per-user control                   │
  │ Dark launch      │ Validate prod behavior before any user exposure │
  └──────────────────┴─────────────────────────────────────────────────┘

ROLLOUT SPEED DECISION TREE:

  Is the change reversable in <60 seconds without deploy?
    YES → Feature flag rollout (fastest retreat)
    NO  → Is it a new binary with schema changes?
      YES → Canary with long bake (24h+) + migration flags
      NO  → Blue-green with pre-warmed green

KILL SWITCH vs CIRCUIT BREAKER (Week 6):

  ┌────────────────────────┬──────────────────┬───────────────────────┐
  │ Scenario               │ Kill switch      │ Circuit breaker       │
  ├────────────────────────┼──────────────────┼───────────────────────┤
  │ Dependency returning   │ Optional         │ YES (automatic)       │
  │ 503/timeouts           │                  │                       │
  │ Feature logic bug,     │ YES (manual)     │ NO (200 OK passes)    │
  │ 200 OK wrong result    │                  │                       │
  │ Planned maintenance    │ YES (pre-disable)│ Maybe (if errors)     │
  │ Load protection        │ NO               │ YES (bulkhead + CB)   │
  └────────────────────────┴──────────────────┴───────────────────────┘

  USE BOTH for critical paths: kill switch for product control,
  circuit breaker for dependency health.
```

---

## Incident Scenario

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1 (REVENUE + CUSTOMER TRUST)
Service: E-commerce checkout — new payment flow
Time: Thursday 11:47 UTC (Black Friday preview sale)
Duration: 52 minutes to mitigation, 4 hours to full resolution

ARCHITECTURE:
  web / mobile
       │
       ▼
  CloudFront (static) + ALB (api-alb)
       │
       ▼
  api-gateway (JWT, rate limit)
       │
       └──► checkout-bff
                 │
                 ├──► LaunchDarkly SDK (server-side, streaming)
                 │
                 ├──► checkout-svc v2.8.0 (20 replicas, ECS)
                 │         │
                 │         ├──► payments-svc (gRPC)
                 │         │         └──► payments-db (RDS)
                 │         │
                 │         └──► fraud-svc
                 │                   └──► external-fraud-api
                 │
                 └──► recommendations-svc (optional path)

  FLAGS (LaunchDarkly production):
    release.new-checkout:       true, 25% rollout (sticky bucket)
    release.new-payments-v2:    true, 25% rollout (INDEPENDENT bucket)
    ops.enable-recommendations: true
    ops.enable-fraud-check:     true

  RESILIENCE (Week 6 — as deployed):
    checkout-svc → payments-svc: circuit breaker (failureRate 50%),
      retry maxAttempts=3 with jitter, bulkhead maxConcurrent=50
    checkout-svc → fraud-svc: circuit breaker, timeout 2s
    Kill switch fallback: new-checkout OFF → legacy UI + legacy payments

  DEPLOYMENT STATE:
    ALB: 100% traffic to single checkout-svc task definition (no infra canary)
    CodeDeploy: not used for checkout (rolling ECS deploy last Tuesday)
    Feature flags are the ONLY progressive delivery mechanism active

TIMELINE:
  11:30  Product requests increase new-checkout rollout 10% → 25%
         Engineer updates LaunchDarkly percentage. No code deploy.
  11:38  checkout error rate: 0.3% → 1.8% (global, not per-cohort)
  11:40  Support: "Payment fails on new checkout screen" × 8 tickets
  11:42  payments-svc gRPC latency p99: 400ms → 2.1s (elevated, not critical)
  11:44  PagerDuty: checkout error rate > 1% threshold
  11:45  On-call checks ALB target health — all healthy
  11:46  On-call checks recent deploys — none in 48 hours
  11:47  You join incident bridge
  11:48  Dashboard shows fraud-svc circuit breaker CLOSED on all pods
  11:50  Engineer suggests payments-db issue — RDS CPU 52%, normal
  11:52  Error logs: "PaymentMethodV2ValidationError: invalid token format"
         only on checkout pods processing new-payments path
  11:55  Metrics tagged by feature_variant show:
           legacy path error rate: 0.3% (normal)
           new-checkout path error rate: 11.2%
  11:57  Discovery: release.new-checkout and release.new-payments-v2
         rolled independently to 25% — 50% of new-checkout users lack
         new-payments (broken hybrid path)
  11:58  On-call sets release.new-checkout to 0%. Error rate drops to 0.4%
         within 90 seconds (SDK stream propagation)
  12:00  BUT: release.new-payments-v2 still at 25%
         Some legacy-checkout users hit new payment API (orthogonal bug)
  12:02  On-call sets release.new-payments-v2 to 0%. Error rate 0.3%
  12:05  Mobile support tickets continue — mobile cached 25% rollout
  12:10  Server-side payment API enforces legacy contract for all users
         (emergency deploy — no flag dependency)
  12:15  Customer reports: "Charged twice" × 3 (retry + idempotency gap
         on new payment path only)
  12:30  Post-mortem prep begins. Flag state: both release flags at 0%.
  13:00  Product asks to re-rollout at 11:30 Friday. Engineering refuses
         without prerequisite fix.

CURRENT STATE AT 11:47 (when you join):
  - Global checkout error rate: 1.8% (threshold 1%)
  - Per-cohort data NOT on main dashboard (on-call was looking at global)
  - release.new-checkout: 25%, release.new-payments-v2: 25%
  - No infra canary — ALB 100% single version
  - fraud circuit breaker: CLOSED (fraud not the problem)
  - payments circuit breaker: CLOSED (payments returns errors but 200-ish)
  - 8 support tickets, growing
  - Mobile clients mid-cache TTL (15 min poll)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Scenario Questions

**Question 1: Cohort Analysis and Blast Radius**

The on-call looked at global error rate and ALB health. Why did that miss the root cause for 10 minutes?

- (a) Calculate the approximate % of users in the broken hybrid path given independent 25% rollouts on two flags and code that requires both for the happy path but serves broken hybrid when only one is true.
- (b) What metric tags should have been on the default dashboard to catch this at 11:38?
- (c) Draw the flag combination truth table (4 states) and identify which states are broken.
- (d) Why didn't the Week 6 circuit breaker help?

---

**Question 2: Immediate Mitigation (T+0 to T+10 minutes)**

You join at 11:47. Write your mitigation plan.

- (a) In what order do you flip release.new-checkout and release.new-payments-v2? Defend the order.
- (b) What do you do about mobile cached flags within the first 10 minutes?
- (c) Write the exact LaunchDarkly API call or CLI steps to set both flags to 0% with audit comment.
- (d) Should you open the payments-svc circuit breaker manually? Yes or no with reasoning.
- (e) What is the first command/query you run in 60 seconds?

---

**Question 3: Kill Switch vs Circuit Breaker Composition**

This incident was a logic bug (200 OK with validation error in body), not dependency failure.

- (a) Explain why fraud-svc and payments-svc circuit breakers stayed CLOSED.
- (b) Design the kill switch + fallback that would have limited blast radius to 25% max even with the nested flag bug.
- (c) Map the incident timeline to Week 6 half-open probing analogy — what was the "probe" and what was the "trip" signal?
- (d) Write the Resilience4j config change that does NOT help this incident (prove you understand the boundary).

---

**Question 4: Flag Hygiene and Prevention**

- (a) Write the LaunchDarkly prerequisite rule that prevents this class of bug.
- (b) Design the CI check that fails if two coupled release flags can roll independently.
- (c) Write the flag registry entries for both flags including correct sunset and coupling documentation.
- (d) What should the rollout procedure have been instead of independent 10% → 25% bumps?

---

**Question 5: Observability and Rollout Gates**

Design the automated gate that would have blocked the 11:30 rollout increase.

- (a) CloudWatch/Prometheus query for per-variant error rate comparison.
- (b) Threshold that catches this without false positives during normal deploys.
- (c) Step Functions or pipeline step that queries metric before LD API percentage increase.
- (d) Alert that fires when global error rate diverges from legacy cohort rate.

---

**Question 6: Double Charge and Idempotency**

Three double-charge reports arrive at 12:15 on the new payment path only.

- (a) Connect to Week 6 retry config — how did maxAttempts=3 with jitter contribute?
- (b) Design idempotency key flow for payments-v2 that works across flag on/off states.
- (c) Should you flip ops.enable-fraud-check as part of mitigation? Defend.

---

**Question 7: Post-Incident Rollout Redesign**

Product wants new checkout live by next Friday.

- (a) Design combined rollout plan: single flag vs prerequisite vs merged flag — pick one and defend.
- (b) Include infra canary (ALB) AND flag canary — specify percentages at each stage.
- (c) Game day checklist before re-rollout.
- (d) Document the kill switch runbook entry for release.new-checkout including propagation time and mobile caveats.

---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**  
> [`../answers/Week-07-Specialized-Components/Feature Flags and Progressive Delivery Answers.md`](../answers/Week-07-Specialized-Components/Feature Flags and Progressive Delivery Answers.md)

## Key Takeaways

```
╔═════════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:                ║
╟─────────────────────────────────────────────────────────────────╢
║                                                                 ║
║   1. Feature flags control behavior; canaries control           ║
║      binaries. Multiply blast radius across layers.             ║
║      Sticky hash bucketing — never random per request.          ║
║                                                                 ║
║   2. Kill switches are operational controls with safe           ║
║      defaults and server-side enforcement. They compose         ║
║      with circuit breakers (Week 6): CB for dependency          ║
║      health, kill switch for feature logic bugs.                ║
║                                                                 ║
║   3. Release flags are temporary. Delete at 100% rollout.       ║
║      Permanent flags are technical debt and test matrix         ║
║      explosions.                                                ║
║                                                                 ║
║   4. Coupled features need one flag or explicit                 ║
║      prerequisites — independent percentage rollouts on         ║
║      dependent code paths create broken hybrid states.          ║
║                                                                 ║
║   5. Monitor per-cohort metrics during rollout, not             ║
║      global aggregates. Global dashboards hide cohort           ║
║      disasters until blast radius grows.                        ║
╚═════════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading

```
REQUIRED:
  1. LaunchDarkly Documentation: "Flag types and best practices"
     https://docs.launchdarkly.com/guides/flags/flag-types
     → Release vs ops vs experiment taxonomy. 20 minutes.

  2. AWS AppConfig User Guide: "Managing feature flags"
     https://docs.aws.amazon.com/appconfig/latest/userguide/appconfig-feature-flags.html
     → Hosted flags, deployment strategies, validators. 30 minutes.

  3. AWS Architecture Blog: "Safe, automated rollouts with
     Amazon CloudWatch and AWS AppConfig"
     https://aws.amazon.com/blogs/mt/safe-automated-rollouts-with-amazon-cloudwatch-and-aws-appconfig/
     → Automated rollback pattern. 15 minutes.

OPTIONAL:
  4. "Feature Toggles (aka Feature Flags)" — Martin Fowler
     https://martinfowler.com/articles/feature-toggles.html
     → Canonical taxonomy (release, ops, experiment, permission).
     → The technical debt section is essential. 45 minutes.

  5. Google SRE Book: "Launching and Iterating" (Chapter 27)
     https://sre.google/sre-book/launching-iterating/
     → Progressive exposure and rollback culture. 30 minutes.

WEEK 6 CROSS-REFERENCE:
  6. Circuit Breakers, Bulkheads, Timeouts, Retries, and Backpressure
     → Week-06-Architecture-Patterns/Circuit Breakers Bulkheads
       Timeouts Retries and Backpressure.md
     → Read "Failure 2: Circuit Breaker Flapping" and compare
       half-open probing to feature flag percentage rollout.
```

---
