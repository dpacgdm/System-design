# Week 6, Topic 3 — Microservices Patterns

> You know how messages move (Kafka module). You know how events coordinate workflows (Event-Driven Architecture). You know how to stop cascading failures (Circuit Breakers). This module answers the question those modules assume you already answered: *how do you cut a system into services in the first place — and how do you run them on AWS without building a distributed monolith with extra network hops?*

Same teaching contract as every module in this curriculum: every section answers *what do I design, what do I run, what breaks at 2 AM, and what question separates a passing answer from a principal one.*

**Prerequisites:** Message Queues and Kafka (Week 6, Topic 1), Event-Driven Architecture (Week 6, Topic 2), Database Scaling Patterns (Week 5), Consistency Models (Week 3), Circuit Breakers (Week 6, Topic 5 — read after or in parallel for resilience context).

---

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Define service boundaries using DDD bounded contexts,     ║
║      aggregates, and context maps — not CRUD tables or         ║
║      org-chart convenience                                     ║
║                                                                ║
║   2. Execute a strangler fig migration from monolith to        ║
║      services with explicit parity gates and rollback          ║
║      criteria at each phase                                    ║
║                                                                ║
║   3. Design API gateway and BFF layers with correct            ║
║      responsibility split: routing, auth, aggregation,         ║
║      and what must NEVER live in the gateway                   ║
║                                                                ║
║   4. Choose sync vs async integration per coupling             ║
║      dimension (latency, consistency, failure isolation)       ║
║      and articulate the distributed monolith failure mode      ║
║                                                                ║
║   5. Enforce data ownership: one writer per aggregate,         ║
║      no shared-database microservices, and safe read           ║
║      paths via API or replicated projections                   ║
║                                                                ║
║   6. Diagnose distributed monolith anti-patterns from          ║
║      dependency graphs, deploy coupling, and incident          ║
║      blast radius — even when every service has its own        ║
║      Dockerfile                                                ║
║                                                                ║
║   7. Align team topology (stream-aligned, enabling,            ║
║      complicated-subsystem, platform) with service             ║
║      boundaries per Conway's Law                               ║
║                                                                ║
║   8. Map ECS and EKS deployment patterns: service mesh,        ║
║      sidecars, task vs pod granularity, and when               ║
║      orchestrator choice changes decomposition economics       ║
║                                                                ║
║   9. Triage a microservices decomposition incident:            ║
║      circular dependencies, shared DB locks, deploy            ║
║      coupling, and the difference between "service down"       ║
║      and "system down"                                         ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Microservices = small services"                ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Size is irrelevant. AUTONOMY is the point. A              ║
║   "microservice" that cannot deploy, scale, or fail                ║
║   independently of five other services is a module in a            ║
║   distributed monolith — with network partitions as a bonus.       ║
║   Two teams, two databases, one bounded context = correct          ║
║   split. Twelve services, one Postgres schema = failure.           ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "We'll split by REST resource"                  ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. /users, /orders, /products as three services              ║
║   creates chatty sync chains: checkout calls User, Product,        ║
║   Inventory, Pricing, Tax, Shipping on every request.              ║
║   Boundaries follow BUSINESS CAPABILITY and change cadence,        ║
║   not HTTP noun pluralization.                                     ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Shared database is fine temporarily"           ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. "Temporarily" becomes seven years. Shared schema          ║
║   means shared migrations, shared locks, shared outages.           ║
║   Service A's index rebuild blocks Service B's checkout.           ║
║   You have not decomposed — you have distributed a monolith        ║
║   across network calls while keeping the worst coupling.           ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "API Gateway = our backend"                     ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Gateways route, authenticate, rate-limit, and             ║
║   optionally aggregate. Business logic in the gateway              ║
║   becomes an undeployable bottleneck with no owner team.           ║
║   BFFs are per-client facades owned by the client team —           ║
║   not a dumping ground for "just one more join."                   ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Async fixes coupling"                          ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Async decouples TIME and AVAILABILITY, not                ║
║   SEMANTICS (Week 6, Topic 2). If Service B's correctness          ║
║   depends on Service A's event schema, you are coupled.            ║
║   Replacing sync HTTP with Kafka without fixing boundaries         ║
║   produces an asynchronous distributed monolith.                   ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Conway's Law is folklore"                      ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Your architecture WILL mirror your communication          ║
║   structure. Four teams owning interleaved services →              ║
║   every feature touches four repos. Design team topology           ║
║   and service boundaries together, or fight Conway forever.        ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #7: "Kubernetes means we're cloud-native"           ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. EKS without service boundaries is expensive               ║
║   complexity. ECS Fargate with clear contexts may be               ║
║   the right trade. Orchestrator choice is an operational           ║
║   decision; decomposition is an organizational and domain          ║
║   decision. Do not let the platform team drive service cuts.       ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #8: "Strangler fig = rewrite in place"              ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Strangler intercepts traffic at the edge, routes          ║
║   incrementally, and maintains parity evidence before cutover.     ║
║   Big-bang extraction of the payments module while the             ║
║   monolith still writes the same tables is how CFOs learn          ║
║   about distributed transactions.                                  ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### What Microservices Actually Are (And Are Not)

```
MICROSERVICES ARCHITECTURE:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  An architectural style where the system is composed of
  independently deployable services, each:

    • Aligned to a bounded business capability
    • Owns its data (no foreign writes to another service's store)
    • Communicates via well-defined APIs (sync or async)
    • Can be developed, deployed, and scaled by a team
      without coordinating a "big bang" release with N teams

  WHAT IT OPTIMIZES FOR:
    ✓ Team autonomy and parallel delivery
    ✓ Independent scaling of hot paths
    ✓ Technology heterogeneity where justified
    ✓ Blast radius containment (when boundaries are real)

  WHAT IT COSTS:
    ✗ Distributed systems complexity (Week 3, Week 6 T5)
    ✗ Operational overhead (N deployables, N dashboards)
    ✗ Cross-service consistency requires explicit design
    ✗ Testing and local dev friction
    ✗ Network latency on former in-process calls


THE DISTRIBUTED MONOLITH (your real enemy):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Looks like microservices:
    • Separate repos ✓
    • Separate Docker images ✓
    • Kubernetes manifests ✓
    • "We have 14 services" ✓

  Behaves like a monolith:
    • Must deploy A+B+C together for any feature ✗
    • Shared database with cross-schema JOINs ✗
    • Synchronous call chains 6+ hops deep ✗
    • Circular dependencies (A→B→C→A) ✗
    • One team's schema migration breaks three services ✗

  ╔══════════════════════════════════════════════════════════════╗
  ║   LITMUS TESTS (all must pass for "real" microservice):      ║
  ╟──────────────────────────────────────────────────────────────╢
  ║   1. Can I deploy this service alone on Tuesday afternoon?   ║
  ║   2. If this service is down, do unrelated features work?    ║
  ║   3. Can I scale this service without scaling its callers?   ║
  ║   4. Does one team own this service end-to-end?              ║
  ║   5. Is there exactly one writer to each piece of mutable    ║
  ║      business state?                                         ║
  ╚══════════════════════════════════════════════════════════════╝

  Fail 2+ → you have a distributed monolith. Fix boundaries
  before adding Kafka, Istio, or a fourth environment.
```

### Service Boundaries — Domain-Driven Design

```
WHY DDD FOR BOUNDARIES:
━━━━━━━━━━━━━━━━━━━━━━━

  Technical decomposition (by layer, by table, by endpoint)
  optimizes for code familiarity. DDD optimizes for CHANGE —
  the axis microservices must survive.

  A bounded context is a linguistic boundary: inside it,
  terms have one precise meaning. "Customer" in Billing ≠
  "Customer" in Shipping ≠ "Customer" in Marketing.


CORE DDD CONCEPTS FOR SYSTEM DESIGN:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  BOUNDED CONTEXT:
    A subsystem with its own ubiquitous language, models,
    and data. Services map 1:1 to bounded contexts in the
  ideal case; 1:few when contexts are tiny.

  AGGREGATE:
    A cluster of domain objects treated as one unit for
    state changes. One aggregate = one transaction boundary.
    Cross-aggregate consistency is eventual (events/sagas).

    Example — Order aggregate (Order context):
      Order (root)
        ├── OrderLine (entity)
        ├── ShippingAddress (value object)
        └── OrderStatus (value object)

      Invariants enforced inside aggregate:
        - lines cannot be empty on submit
        - total = sum(line extended price)
        - status transitions follow state machine

  AGGREGATE ROOT:
    The only entry point for mutations. External code never
    sets orderLine.quantity directly — it calls
    order.addLine(sku, qty) on the root.

  CONTEXT MAP:
    How bounded contexts relate. Drives integration pattern.

    ┌────────────────┬─────────────────────────────────────────┐
    │ Relationship   │ Integration pattern                     │
    ├────────────────┼─────────────────────────────────────────┤
    │ Partnership    │ Two teams, coordinated releases         │
    │ Customer-Suppl │ Downstream depends on upstream API      │
    │ Conformist     │ Downstream copies upstream model        │
    │ Anti-corrupt   │ Translation layer protects domain       │
    │ Shared Kernel  │ Small shared lib (dangerous at scale)   │
    │ Open Host Svc  │ Published API for many consumers        │
    │ Published Lang │ Public spec (REST/OpenAPI, events)      │
    └────────────────┴─────────────────────────────────────────┘


E-COMMERCE CONTEXT MAP (simplified):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ╔═══════════════╗         ╔═══════════════╗
  ║   Catalog     ║ ──────► ║   Checkout    ║  Customer-Supplier
  ║   (products,  ║  API    ║   (cart,      ║  Catalog publishes
  ║    pricing)   ║         ║    order)     ║  ProductPriceChanged
  ╚═══════════════╝        ═══════╤═══════╝
                                    │ events
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            ╔═══════════════╗ ╔═══════════════╗ ╔═══════════════╗
            ║  Inventory    ║ ║   Payment     ║ ║ Fulfillment   ║
            ║  (stock res.) ║ ║  (charges)    ║ ║ (ship, track) ║
            ╚═══════════════╝ ╚═══════════════╝ ╚═══════════════╝

  Anti-Corruption Layer example:
    Checkout does NOT store Stripe's PaymentIntent shape.
    It stores PaymentReference { externalId, status, amount }
    mapped from Stripe webhooks via payment-svc's ACL.


HOW TO FIND BOUNDARIES (practical workshop):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Event storming (or domain storytelling):
     List domain events: OrderPlaced, PaymentCaptured,
     InventoryReserved, ShipmentDispatched...
     Draw causality. Clusters of events that change together
     suggest one context.

  2. Change cadence:
     Catalog changes weekly (merchandising).
     Payment changes monthly (compliance, PCI).
     Split what changes at different rates.

  3. Consistency requirements:
     Strong consistency INSIDE aggregate (single DB txn).
     Eventual consistency BETWEEN contexts (events).

  4. Team ownership:
     If two teams constantly negotiate one service's backlog,
     the boundary is wrong.

  5. Volatility vs stability:
     Stable core (identity, payments) vs volatile edge
     (recommendations, experiments) → separate services.


BOUNDARY ANTI-PATTERNS:
━━━━━━━━━━━━━━━━━━━━━━━

  ✗ "User service" that owns profile, preferences, auth,
    loyalty points, and marketing consent — five change rates.

  ✗ Splitting Order read and Order write into microservices
    before you need independent scale (premature CQRS).

  ✗ Nanoservices: one aggregate per container, 200 services,
    200 deploy pipelines, 200 on-call rotations.

  ✗ Entity service: CRUD per table (ProductService,
    CategoryService, BrandService) with sync calls forming
    a graph — classic distributed monolith.
```

### The Strangler Fig Pattern

```
STRANGLER FIG (Martin Fowler / Chris Richardson):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Named after the fig vine that gradually envelops a host
  tree until the tree dies and the fig stands alone.

  Applied to legacy migration:
    Intercept traffic at the edge → route slices to new
    implementation → retire monolith paths when parity proven.


THE FOUR PHASES:
━━━━━━━━━━━━━━━━

  PHASE 0: Baseline (monolith)
  ─────────────────────────────
    Users → ALB → monolith → single Postgres

    Instrument: latency, error rate, business metrics per
    route. You need "before" to prove "after."

  PHASE 1: Intercept and observe
  ──────────────────────────────
    Users → ALB → API Gateway (or reverse proxy)
                      │
                      ├── /api/v2/catalog/* → NEW catalog-svc
                      └── /*                → monolith

    Monolith unchanged. New service handles ONE capability.
    Shadow traffic optional: duplicate reads, compare results.

  PHASE 2: Extract data path
  ───────────────────────────
    catalog-svc gets its own RDS (or DynamoDB).
    Sync via:
      • CDC from monolith DB (Debezium → MSK) — Week 6 T6
      • Dual-write with reconciliation job
      • Batch backfill + ongoing delta

    Monolith still authoritative for catalog until cutover.

  PHASE 3: Redirect writes
  ────────────────────────
    Gateway routes POST/PUT/DELETE to catalog-svc.
    Monolith reads from catalog-svc API OR replicated read
    model (temporary conformist — document exit criteria).

  PHASE 4: Retire monolith path
  ─────────────────────────────
    Delete catalog code from monolith.
    Drop catalog tables from monolith DB (after backup +
    legal hold check).

    ╔══════════════════════════════════════════════════════════╗
    ║   PARITY GATE (required before Phase 3 cutover):         ║
    ║   • 7 days shadow mode: <0.01% response diff             ║
    ║   • Load test at 2× peak on new path                     ║
    ║   • Rollback tested: flip gateway weight 100→0 in <60s   ║
    ║   • On-call runbook for new service                      ║
    ╚══════════════════════════════════════════════════════════╝


STRANGLER ROUTING ON AWS:
━━━━━━━━━━━━━━━━━━━━━━━━━

  Option A: ALB path-based rules
    /api/v2/catalog/* → target group: catalog-svc (ECS)
    /*                  → target group: monolith (ECS)

  Option B: API Gateway HTTP API
    $default → monolith integration
    GET /catalog/{id} → catalog-svc Lambda/HTTP integration

  Option C: CloudFront + Lambda@Edge
    For global strangler at CDN edge (rare for APIs)

  Weighted routing (canary):
    ALB listener rule: forward 5% to catalog-svc, 95% monolith
    CloudWatch compares 5xx, p99, business KPIs
    Increase weight 5→25→50→100 over days


WHAT NOT TO STRANGLE FIRST:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ✗ Payments (money movement, PCI scope, hardest rollback)
  ✗ Authentication (session invalidation blast radius)
  ✗ Cross-cutting reporting (reads everything, owns nothing)

  ✓ Read-heavy, leaf capabilities: catalog browse, reviews,
    recommendations, static content
  ✓ New features with no monolith code (greenfield behind gateway)


STRANGLER + TEAM TOPOLOGY:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  Each strangled slice needs a stream-aligned team owning
  the new service BEFORE cutover. "Platform extracts catalog"
  without a product team → orphan service, monolith team
  still gets paged for catalog bugs.
```

### API Gateway and Backend-for-Frontend (BFF)

```
THE EDGE LAYER PROBLEM:
━━━━━━━━━━━━━━━━━━━━━━━

  Clients (web, iOS, Android, partner API) have different:
    • Payload shapes (mobile wants minimal JSON)
    • Auth flows (cookies vs bearer vs mTLS)
    • Aggregation needs (product page = catalog + inventory +
      reviews + recommendations)
    • Release cadence (app store review vs daily web deploy)

  One generic API forces all clients to over-fetch or
  under-specify. BFF pattern: one backend per client type,
  owned by the client team.


RESPONSIBILITY SPLIT:
━━━━━━━━━━━━━━━━━━━━━

  ╔════════════════════╦═══════════════╦═══════════════════════╗
  ║ Concern            ║ API Gateway   ║ BFF                   ║
  ╠════════════════════╬═══════════════╬═══════════════════════╣
  ║ TLS termination    ║ Yes           ║ (behind gateway)      ║
  ║ Authentication     ║ JWT validate  ║ Session + client ctx  ║
  ║ Rate limiting      ║ Global/per-API║ Per-user (optional)   ║
  ║ Routing            ║ Yes           ║ Orchestration only    ║
  ║ Request validation ║ Schema (OpenAPI)║ Client-specific     ║
  ║ Aggregation        ║ NO            ║ Yes (parallel fetch)  ║
  ║ Business logic     ║ NEVER         ║ Presentation logic OK ║
  ║ Protocol transform ║ REST→HTTP     ║ GraphQL resolver OK   ║
  ╚════════════════════╩═══════════════╩═══════════════════════╝


ARCHITECTURE:
━━━━━━━━━━━━━

  Mobile App ──► mobile-bff ──┐
  Web App    ──► web-bff    ──┼──► API Gateway ──► services
  Partner    ──► partner-api ─┘         │
                                          ├── catalog-svc
                                          ├── checkout-svc
                                          └── inventory-svc

  API Gateway (AWS API Gateway / ALB + auth):
    • Single public ingress
    • WAF, throttling, API keys
    • Service-to-service auth (IAM, mTLS via mesh)

  BFF (ECS/EKS service per client):
    • Calls multiple downstream services in parallel
    • Shapes response for one client
    • Caches client-specific fragments (CDN, Redis)
    • Owned by mobile team / web team — NOT platform


BFF AGGREGATION EXAMPLE (product detail page):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  web-bff receives GET /product/WIDGET-7

  Parallel (async or Promise.all):
    catalog-svc:   GET /products/WIDGET-7
    inventory-svc: GET /availability/WIDGET-7
    reviews-svc:   GET /reviews?sku=WIDGET-7&limit=5
    pricing-svc:   GET /price/WIDGET-7?region=US

  Timeout budget: 800ms total (Week 6 T5)
    Each hop: 200ms max, circuit breaker per dependency

  Response assembly:
    {
      "sku": "WIDGET-7",
      "title": "...",
      "inStock": true,
      "price": { "amount": 29.99, "currency": "USD" },
      "reviews": { "avg": 4.2, "count": 847, "top": [...] }
    }

  BFF does NOT:
    • Calculate tax (checkout-svc)
    • Reserve inventory (inventory-svc on add-to-cart)
    • Store product data (catalog-svc owns truth)


GATEWAY ANTI-PATTERNS:
━━━━━━━━━━━━━━━━━━━━━━

  ✗ "Smart gateway" with 4000 lines of Lua/JavaScript
    implementing promo logic — undeployable, untestable

  ✗ Single BFF for web + mobile + admin — becomes god object

  ✗ BFF writes to another service's database "for performance"

  ✗ GraphQL gateway as only BFF with resolvers that N+1
    call microservices without DataLoader batching


AWS API GATEWAY PATTERNS:
━━━━━━━━━━━━━━━━━━━━━━━━━

  HTTP API (v2): lower cost, JWT authorizer, Lambda/HTTP proxy
  REST API (v1): request validation, caching, usage plans

  Private integration:
    API Gateway → VPC Link → NLB → ECS services (no public IP)

  Service-to-service:
    Prefer mesh (App Mesh, Istio) or direct NLB + IAM auth
    Gateway is for NORTH-SOUTH (client→system), not all EAST-WEST
```

### Synchronous vs Asynchronous Integration

```
THE INTEGRATION SPECTRUM:
━━━━━━━━━━━━━━━━━━━━━━━━━

  SYNC (request/response):
    HTTP REST, gRPC, GraphQL
    Caller waits. Caller fails if callee fails (unless CB).

  ASYNC (message/event):
    SQS, SNS, MSK, EventBridge
    Caller publishes and continues. Consumer processes later.

  ╔═══════════════════╦═══════════════════╦═══════════════════╗
  ║ Dimension         ║ Sync              ║ Async             ║
  ╠═══════════════════╬═══════════════════╬═══════════════════╣
  ║ Latency           ║ Lower (one RTT)   ║ Higher (queue lag)║
  ║ Coupling (time)   ║ Tight             ║ Loose             ║
  ║ Coupling (schema) ║ Tight             ║ Tight (events)    ║
  ║ Failure visibility║ Immediate to user ║ Delayed (DLQ)     ║
  ║ Consistency       ║ Easier "read own  ║ Eventual default  ║
  ║                   ║  writes"          ║                   ║
  ║ Load leveling     ║ Poor (spike hits  ║ Good (queue absorbs)║
  ║                   ║  callee directly) ║                   ║
  ║ Debugging         ║ Trace one request ║ Causality implicit║
  ╚═══════════════════╩═══════════════════╩═══════════════════╝


WHEN TO USE SYNC:
━━━━━━━━━━━━━━━━━

  ✓ User is waiting (checkout total, auth check, stock check
    on product page if "in stock" must be accurate)
  ✓ Operation is read-only idempotent query
  ✓ Chain depth ≤ 2 hops with strict timeout budget
  ✓ Strong consistency required for THIS user action
  ✓ gRPC with deadline propagation (Week 6 T5)

  Example: GET /cart → checkout-svc reads own DB only (no sync
  chain). GET /product/{id}/availability → inventory-svc
  (one hop, cacheable).


WHEN TO USE ASYNC:
━━━━━━━━━━━━━━━━

  ✓ Side effects that user doesn't wait for (email, analytics,
    search index update, fraud scoring post-order)
  ✓ Load leveling (order spike → queue → workers scale)
  ✓ Multi-subscriber fan-out (OrderPlaced → 5 consumers)
  ✓ Cross-context notification (Catalog changed → invalidate caches)
  ✓ Long-running work (generate invoice PDF, export report)

  Example: OrderPlaced event → fulfillment, analytics, CRM
  (Week 6, Topic 2 choreography/orchestration).


THE HYBRID (most real systems):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Checkout sync path:
    POST /checkout → validate cart (local)
                   → sync: inventory-svc reserve (2s timeout)
                   → sync: payment-svc charge (5s timeout)
                   → commit order (local txn)
                   → async: publish OrderPlaced (outbox)

  User sees confirmation when sync path completes.
  Fulfillment, email, search catch up via events.


SYNC CHAIN DEPTH RULE:
━━━━━━━━━━━━━━━━━━━━━━

  ┌─────────┬────────────────────────────────────────────┐
  │ Depth   │ Verdict                                    │
  ├─────────┼────────────────────────────────────────────┤
  │ 0-1 hop │ Normal                                     │
  │ 2 hops  │ Acceptable with timeouts + CB              │
  │ 3 hops  │ Smell — can you aggregate or async?        │
  │ 4+ hops │ Distributed monolith — redesign boundary   │
  └─────────┴────────────────────────────────────────────┘

  p99 latency = sum(hop p99) if serial.
  4 hops × 50ms p99 = 200ms best case; 4 × 500ms under load = 2s.


INTEGRATION MATRIX (design doc template):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  From → To          │ Pattern    │ Contract        │ On failure
  ───────────────────┼────────────┼─────────────────┼──────────────
  checkout → inventory│ sync gRPC  │ ReserveStock    │ fail checkout
  checkout → payment  │ sync HTTP  │ CapturePayment  │ fail + release
  checkout → fulfill  │ async event│ OrderPlaced     │ retry/DLQ
  catalog → search    │ async CDC  │ ProductChanged  │ lag OK 30s
  all → analytics     │ async fire │ *               │ drop OK
```

### Data Ownership

```
THE GOLDEN RULE:
━━━━━━━━━━━━━━━━

  Each service is the SOLE WRITER of its bounded context's
  mutable state. Other services read via:
    (a) published API (sync query)
    (b) subscribed events (async replica / projection)
    (c) neither — they don't need that data (best)


DATABASE PER SERVICE:
━━━━━━━━━━━━━━━━━━━━━

  ╔═══════════════╗     ╔═══════════════╗     ╔═══════════════╗
  ║ catalog-svc   ║     ║ checkout-svc  ║     ║ inventory-svc ║
  ║   RDS         ║     ║   RDS         ║     ║   DynamoDB    ║
  ║  (products)   ║     ║  (orders)     ║     ║  (stock)      ║
  ╚═══════════════╝     ╚═══════════════╝     ╚═══════════════╝

  No cross-database foreign keys.
  No shared tables.
  No "just one JOIN" in reporting — use warehouse/CDC.


CROSS-SERVICE DATA NEEDS:
━━━━━━━━━━━━━━━━━━━━━━━

  Need: checkout displays product title on order confirmation

  WRONG:
    checkout-svc JOINs catalog.products table (shared DB)

  RIGHT (snapshot at write time):
    On add-to-cart, checkout stores { sku, title, unitPrice }
    as part of cart line — denormalized snapshot.
    Price at order time is business truth for that order.

  RIGHT (read via API):
    checkout-svc calls catalog-svc GET /products/{sku}
    Caches with TTL. Stale title OK for cart display?
    Usually yes. Stale price? Usually NO — fetch fresh.

  RIGHT (read model replica):
  catalog-svc publishes ProductChanged → checkout-svc
  maintains local product_cache table updated by consumer.
  Eventually consistent; document staleness SLO.


REFERENCE BY ID, NOT BY FOREIGN KEY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  checkout order line stores:
    sku: "WIDGET-7"           (reference)
    title: "Widget Seven"     (snapshot)
    unitPriceCents: 2999       (snapshot at order time)

  NOT:
    product_id: 42 with FK to catalog.products


DISTRIBUTED QUERY PROBLEM:
━━━━━━━━━━━━━━━━━━━━━━━━

  "Show me all orders for customers in California with
   products from brand Nike"

  Spans: customer, order, product, brand contexts.

  Options:
    1. Data warehouse (CDC all → Redshift/Snowflake) — reporting
    2. BFF aggregation (slow, pagination pain)
    3. Materialized view in search (OpenSearch) — query plane
    4. Do NOT solve with sync microservice chain of 4 calls


SAGA AND OUTBOX (cross-context writes):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Business operation spans contexts → saga (Week 6 T4) or
  orchestration (Step Functions). Each step writes locally.

  Outbox ensures local commit + event publish atomic
  (Week 6 T6). Without outbox: ghost orders, phantom charges.
```

### Distributed Monolith Anti-Patterns

```
ANTI-PATTERN 1: SHARED DATABASE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom:
    14 services, 1 RDS Postgres, schemas: orders, catalog,
    inventory, users — cross-schema FKs intact.

  Failure mode:
    inventory team's migration locks orders table during
    Black Friday. Everyone pages.

  Detection:
    grep migrations for schema names outside owning service
    IAM DB user has SELECT on foreign schemas


ANTI-PATTERN 2: SYNCHRONOUS MESH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom:
    Dependency graph: avg 8 outbound sync calls per request.
    Circular: pricing → catalog → inventory → pricing.

  Failure mode:
    One slow service → thread pool cascade (Week 6 T5).
    Deploy pricing v2 requires catalog + inventory compatible.

  Detection:
    Service mesh trace: depth histogram
    Deploy coupling matrix (which services in same release train)


ANTI-PATTERN 3: DISTRIBUTED BIG BALL OF MUD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom:
    "order-service" calls "order-helper" calls "order-utils"
    — three deployables, zero boundary logic.

  Failure mode:
    Same as monolith, 3× the network, 3× the dashboards.

  Detection:
    Services with no independent data store
    Services that exist only because "files got too big"


ANTI-PATTERN 4: CHATTY AGGREGATION IN WRONG LAYER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom:
    API gateway loops 50 SKUs calling inventory per SKU
    (N+1 at edge).

  Failure mode:
    Gateway timeout 29s. Inventory DDoS from own frontend.

  Fix:
    inventory-svc: POST /availability/batch { skus: [...] }
    BFF batches; gateway never loops.


ANTI-PATTERN 5: EVENT CHOREOGRAPHY WITHOUT OWNERSHIP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom:
    12 services subscribe to OrderPlaced, each applies
    different schema interpretation. No owner for "order flow."

  Failure mode:
    Schema v3 breaks 4 consumers silently. DLQ flood.

  Fix:
    Orchestrator for money path; schema registry; one
    team owns order lifecycle contract.


ANTI-PATTERN 6: PREMATURE DECOMPOSITION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom:
    Startup with 3 engineers and 9 microservices.

  Failure mode:
    All energy on K8s, Kafka, tracing — zero features.
    Network calls replace function calls for no autonomy gain.

  Rule:
    Monolith first until team or scale pain is REAL.
    Then strangler — not resume-driven microservices.


DETECTION SCORECARD:
━━━━━━━━━━━━━━━━━━━━

  Score each 0-2 (0=absent, 1=partial, 2=present):

  [ ] Shared database or cross-schema writes
  [ ] Deploy coupling (>2 services per feature release)
  [ ] Sync call depth >3 on critical path
  [ ] Circular dependencies
  [ ] No single owner per service
  [ ] Schema changes require multi-team lockstep
  [ ] Incident: "everything is down" from one service failure

  0-3:  healthy microservices (or healthy monolith)
  4-7:  distributed monolith tendencies
  8-12: full distributed monolith — stop extracting, fix boundaries
```

### Team Topology and Conway's Law

```
CONWAY'S LAW (1968):
━━━━━━━━━━━━━━━━━━━━

  "Organizations which design systems are constrained to
   produce designs which are copies of their communication
   structures."

  Implication: draw org chart and architecture diagram —
  if they disagree, the org chart wins eventually.


TEAM TOPOLOGIES (Skelton & Pais):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. STREAM-ALIGNED TEAM
     Owns a flow of work from business trigger to value.
     Maps to: checkout team, catalog team, fulfillment team.
     Owns: 1-3 services in their bounded context end-to-end.

  2. PLATFORM TEAM
     Provides internal product: K8s cluster, CI/CD, observability,
     golden paths. Reduces cognitive load for stream-aligned teams.
     NOT: a team that "owns all backend services."

  3. ENABLING TEAM
     Coaches on DDD, testing, strangler migrations. Temporary.
     Helps stream-aligned team upskill, then leaves.

  4. COMPLICATED-SUBSYSTEM TEAM
     Owns deep specialty: fraud ML, tax engine, search ranking.
     Exposes API; stream-aligned teams don't modify internals.


REVERSIBLE CONWAY (intentional):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Design desired architecture → reshape teams to match:
    • Create catalog team → migrate catalog code → gateway route
    • Split "platform" from "product" on-call
    • Colocate PM with stream-aligned team per context

  Warning: reorg without architecture plan = chaos.
  Architecture change without reorg = distributed monolith persists.


THINNEST VIABLE PLATFORM (AWS):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Stream-aligned team should get:
    • ECS/EKS deploy template (Terraform module)
    • Observability dashboard template (Grafana/CW)
    • CI pipeline with security scan
    • RDS/Dynamo provisioning with backup defaults
    • Runbook template

  NOT required on day 1:
    • Custom service mesh
    • Multi-cluster federation
    • Internal developer portal with 47 microservices


COGNITIVE LOAD BUDGET:
━━━━━━━━━━━━━━━━━━━━━━

  Each team can own ~1-2 bounded contexts sustainably.
  Adding a third context without enabling team → quality drops.

  If checkout team owns cart, orders, payments, and promotions:
    → split payments (PCI, different cadence)
    → promotions to experimentation team (feature flags, Week 7)
```

### AWS ECS and EKS Patterns for Microservices

```
ORCHESTRATOR CHOICE (pragmatic):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ECS (Fargate or EC2):
    ✓ AWS-native, lower ops burden
    ✓ Task-per-service, ALB service discovery
    ✓ Good for 5-50 services, teams new to containers
    ✓ App Mesh optional

  EKS (Kubernetes):
    ✓ Portable, rich ecosystem (Istio, Argo, Helm)
    ✓ Multi-cloud / hybrid strategy
    ✓ Pod granularity, sidecars standard
    ✗ Control plane + node ops (or Fargate profiles)
    ✗ Team needs K8s competency

  Decision is NOT "which is more microservices."
  Decision: operational maturity, hiring pool, portability.


ECS PATTERN — SERVICE PER TASK DEFINITION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌───────────────────────────────────────────────────┐
  │ VPC (10.0.0.0/16)                                 │
  │ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
  │ │ALB (public) │  │  NLB (int)  │  │  Cloud Map  │ │
  │ └─────────────┘  └─────────────┘  │    (DNS)    │ │
  │        │                │         └─────────────┘ │
  │        ┌────────────────┐                         │
  │        ▼                ▼                         │
  │ ┌───────────────────────────────────────────┐     │
  │ │           ECS Cluster (Fargate)           │     │
  │ │  ┌──────────┐  ┌──────────┐  ┌──────────┐ │     │
  │ │  │ catalog  │  │ checkout │  │inventory │ │     │
  │ │  │svc :8080 │  │svc :8080 │  │svc :8080 │ │     │
  │ │  └──────────┘  └──────────┘  └──────────┘ │     │
  │ │        ▼             ▼             ▼      │     │
  │ │  ┌──────────┐  ┌──────────┐  ┌──────────┐ │     │
  │ │  │   RDS    │  │   RDS    │  │ DynamoDB │ │     │
  │ │  │ catalog  │  │  orders  │  │  stock   │ │     │
  │ │  └──────────┘  └──────────┘  └──────────┘ │     │
  │ └───────────────────────────────────────────┘     │
  └───────────────────────────────────────────────────┘

  Service discovery:
    checkout-svc calls http://inventory.svc.local:8080
    (AWS Cloud Map private DNS namespace)

  Secrets: Secrets Manager → task definition env inject
  Config: SSM Parameter Store / AppConfig


ECS TASK DEFINITION (catalog-svc excerpt):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  {
    "family": "catalog-svc",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "512",
    "memory": "1024",
    "containerDefinitions": [{
      "name": "catalog",
      "image": "123456789012.dkr.ecr.us-east-1.amazonaws.com/catalog:v2.3.1",
      "portMappings": [{ "containerPort": 8080, "protocol": "tcp" }],
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/catalog-svc",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "catalog"
        }
      },
      "secrets": [
        { "name": "DB_PASSWORD", "valueFrom": "arn:aws:secretsmanager:..." }
      ]
    }]
  }

  Auto scaling:
    Target tracking on CPU 70% OR custom ALB request count
    Min 2 tasks (AZ spread), max 20


EKS PATTERN — NAMESPACE PER TEAM OR CONTEXT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  cluster-prod/
    namespace: catalog-team/
      deployment: catalog-svc (replicas: 3)
      deployment: catalog-worker (replicas: 2)
      service: ClusterIP
      hpa: cpu 70%
    namespace: checkout-team/
      deployment: checkout-svc
      deployment: checkout-outbox-relay

  Ingress (ALB Ingress Controller):
    /api/catalog → catalog-team/catalog-svc
    /api/checkout → checkout-team/checkout-svc

  Network policy:
    checkout-team egress → inventory-team only on :8080
    default deny east-west


SIDECAR PATTERN (EKS + Istio / ECS App Mesh):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Pod/Task:
    ┌─────────────────────────────────┐
    │  app container (checkout-svc)   │
    │  envoy sidecar (mesh proxy)     │  mTLS, retries, CB
    │  (optional) otel-collector      │  traces
    └─────────────────────────────────┘

  Mesh provides:
    • Mutual TLS service-to-service
    • Per-route retries/timeouts (Week 6 T5)
    • Traffic splitting (canary 5%)
    • Observability (golden metrics per service)

  When NOT to mesh:
    • <5 services, team overwhelmed
    • Latency-sensitive path where sidecar CPU matters
    • Fix boundaries first — mesh won't fix shared DB


DEPLOYMENT STRATEGIES:
━━━━━━━━━━━━━━━━━━━━━━

  Rolling (ECS default, K8s RollingUpdate):
    Replace tasks gradually. Simple, no extra infra.

  Blue/Green (ECS CodeDeploy, Argo Rollouts):
    Full parallel stack, flip traffic, instant rollback.

  Canary (ALB weighted, Flagger, App Mesh):
    5% → monitor → 25% → 100%. Best for risky extraction.

  Feature flags (Week 7) complement deploy:
    Deploy code dark → enable flag for 1% users → measure.


CROSS-CUTTING AWS SERVICES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────┬──────────────────────────────────────┐
  │ Concern          │ AWS service                          │
  ├──────────────────┼──────────────────────────────────────┤
  │ Ingress          │ ALB + WAF, API Gateway               │
  │ Service discovery│ Cloud Map (ECS), CoreDNS (EKS)       │
  │ Secrets          │ Secrets Manager                      │
  │ Config           │ AppConfig, SSM                       │
  │ Async            │ SQS, SNS, EventBridge, MSK           │
  │ Observability    │ CloudWatch, X-Ray, ADOT              │
  │ CI/CD            │ CodePipeline, GitHub Actions → ECR   │
  │ IaC              │ Terraform, CDK, CloudFormation       │
  └──────────────────┴──────────────────────────────────────┘
```

### Monolith vs Microservices — When to Stay Monolithic

```
STAY MONOLITH WHEN:
━━━━━━━━━━━━━━━━━━━

  • Team < 10 engineers, single product, no independent scale needs
  • Domain model still shifting weekly (boundaries unknown)
  • No organizational pain from coordinated deploys
  • Compliance scope simpler in one audit boundary

  TRANSITION TRIGGERS (real, not resume-driven):
  ───────────────────────────────────────────────
    • Deploy queue: 3+ teams blocked on Friday release train
    • Scale: catalog read 100× checkout write — need separate scale
    • Reliability: catalog deploy breaks checkout (shared codebase)
    • Compliance: PCI scope must shrink to payment slice only
    • Acquisition: integrate bounded capability as service

  MODULAR MONOLITH (middle path):
  ───────────────────────────────
    Single deployable, module boundaries enforced in code:
      catalog/
      checkout/
      inventory/
    No network between modules. Extract to service when trigger hits.

    Tools: Java modules, NestJS monorepo packages, Go internal/
    Boundaries: no cross-module DB access, public API per module
```

### Context Mapping Workshop — Worked Boundary Decisions

```
SCENARIO: E-commerce platform planning decomposition.

STAKEHOLDER REQUESTS:
  "Split into microservices by end of Q3."

STEP 1 — List capabilities (not tables):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Catalog browsing, search, pricing, promotions
  Cart and checkout, tax calculation
  Payment capture and refunds
  Inventory reservation and warehouse sync
  Shipping and tracking
  Customer identity and auth
  Reviews and ratings
  Recommendations (ML)
  Notifications (email, SMS, push)
  Analytics and reporting

STEP 2 — Cluster by change cadence + consistency:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Cluster A (merchandising, weekly): catalog, search index, promotions
  Cluster B (transactional, daily): cart, checkout, tax
  Cluster C (money, monthly+PCI): payment, refunds
  Cluster D (fulfillment, daily): inventory, shipping
  Cluster E (identity, slow): auth, customer profile
  Cluster F (engagement): reviews, notifications
  Cluster G (ML, experimental): recommendations
  Cluster H (read-only analytics): warehouse, dashboards

STEP 3 — First extractions (strangler order):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Wave 1: recommendations (greenfield, async, failure OK)
  Wave 2: catalog read path (read-heavy, cacheable)
  Wave 3: notifications (async leaf)
  Wave 4: reviews (moderate coupling)
  NEVER wave 1: payment, auth, checkout core

STEP 4 — Context map relationships:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Checkout ──customer/supplier──► Catalog (price, title at cart time)
  Checkout ──orchestrated saga──► Inventory, Payment
  Fulfillment ──subscribes──► OrderPlaced (event)
  Analytics ──conformist──► All events (read-only copy)
  Recommendations ──anti-corruption──► Catalog API (internal model)

DECISION LOG ENTRY (template):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Boundary: inventory-svc
  Owns: stock levels, reservations, warehouse sync state
  Does NOT own: product description, order totals, shipping labels
  Integration: sync ReserveStock/ReleaseStock from checkout;
               async WarehouseStockAdjusted from WMS
  Data store: DynamoDB (high write, key=sku+warehouseId)
  Team: fulfillment stream-aligned (6 engineers)
  Extract by: Q2 via strangler on /api/inventory/*
```

---

## Concrete Examples

### Example 1: Strangler Fig — Extracting Catalog from Monolith

```
BASELINE (Month 0):
━━━━━━━━━━━━━━━━━━

  shop.example.com → ALB → monolith (ECS, 12 tasks)
  monolith → RDS Postgres (schemas: public.* everything)

  Routes:
    GET  /products/{id}     → monolith ProductController
    GET  /categories        → monolith
    POST /admin/products    → monolith (internal admin)


MONTH 1 — Intercept reads (Phase 1):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ALB rules:
    /api/v2/products/*  → TG catalog-svc (2 Fargate tasks)
    /api/v2/categories/* → TG catalog-svc
    /*                  → TG monolith

  catalog-svc: new RDS, empty. Reads fallback:
    if not in catalog DB → proxy to monolith internal API
    (temporary — max 30 days)

  Shadow mode (Lambda cron every 5 min):
    Fetch random 100 SKUs from both paths
    Diff title, price, availability flag
    CloudWatch metric: CatalogParityMismatchCount


MONTH 2 — Backfill (Phase 2):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  AWS DMS: monolith RDS → catalog RDS (products, categories)
  Debezium CDC for ongoing changes during dual-write period

  monolith admin POST /admin/products:
    writes monolith DB (still authoritative)
    CDC replicates to catalog-svc DB within 2s lag SLO


MONTH 3 — Cutover writes (Phase 3):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Admin UI → API Gateway → catalog-svc POST /products
  monolith admin route returns 301 deprecated

  Parity gate passed:
    7 days mismatch count = 0
    p99 read latency catalog-svc < monolith baseline

  Gateway weight: 100% catalog for /api/v2/products/*


MONTH 4 — Retire (Phase 4):
━━━━━━━━━━━━━━━━━━━━━━━━━━

  Delete ProductController from monolith
  Drop products, categories tables from monolith DB
  monolith DB size: -40%. PCI scope unchanged.

  Rollback artifact kept 90 days:
    ALB rule JSON with monolith TG weights
```

### Example 2: BFF Product Page — Parallel Aggregation

```
REQUEST: GET /web/product/WIDGET-7
Client: web-bff (ECS, 4 tasks behind internal ALB)

PSEUDOCODE (Node.js style):
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  async function getProductPage(sku, region, userId) {
    const deadline = Date.now() + 800; // ms budget

    const [product, availability, reviews, promos] =
      await Promise.allSettled([
        catalogClient.getProduct(sku, { timeout: 200 }),
        inventoryClient.getAvailability(sku, { timeout: 200 }),
        reviewsClient.getTopReviews(sku, 5, { timeout: 150 }),
        userId
          ? promotionsClient.getForUser(userId, sku, { timeout: 150 })
          : Promise.resolve(null),
      ]);

    // Degrade gracefully
    const p = product.status === 'fulfilled' ? product.value : null;
    if (!p) throw new ServiceUnavailable('catalog');

    return {
      sku: p.sku,
      title: p.title,
      description: p.description,
      price: p.price,
      inStock: availability.status === 'fulfilled'
        ? availability.value.inStock
        : null,  // unknown — UI shows "check availability"
      reviews: reviews.status === 'fulfilled'
        ? reviews.value
        : { avg: null, count: 0, top: [] },
      promo: promos.status === 'fulfilled' ? promos.value : null,
    };
  }

CIRCUIT BREAKER STATE (per downstream):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  catalog:     CLOSED  (required — fail page if open)
  inventory:   HALF-OPEN (degrade to null inStock)
  reviews:     OPEN → empty reviews (acceptable)
  promotions:  OPEN → null promo (acceptable)

METRICS:
  bff_product_page_latency_ms histogram
  bff_downstream_failures_total{service="inventory"}
```

### Example 3: Sync vs Async at Checkout Boundary

```
USER ACTION: Place order (user waits for confirmation)

SYNC PATH (must complete < 3s p99):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. checkout-svc: validate cart (local DB, 5ms)
  2. checkout-svc → inventory-svc gRPC ReserveStock (timeout 800ms)
  3. checkout-svc → payment-svc HTTP CapturePayment (timeout 1500ms)
  4. checkout-svc: INSERT order status=CONFIRMED (local txn)
  5. checkout-svc: INSERT outbox OrderPlaced (same txn)
  6. Return 201 { orderId, confirmationNumber } to client

  On payment failure: sync call ReleaseStock (compensation)

ASYNC PATH (after step 4 commit):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  outbox-relay → MSK topic orders.events → consumers:
    fulfillment-svc: create pick list
    analytics-svc: revenue event
    search-svc: decrement popularity index
    notification-svc: order confirmation email
    crm-svc: update customer LTV

  User does NOT wait for email or warehouse pick list.

WHY NOT async payment?
━━━━━━━━━━━━━━━━━━━━
  User needs yes/no on charge before leaving checkout.
  Async payment → "order pending" UX → support calls → worse.
  Payment is sync; fulfillment is async. Correct split.
```

### Example 4: Data Ownership — Order Line Snapshot

```
CATALOG TEAM changes product title:
  "Widget Seven" → "Widget 7 Pro Edition"

CUSTOMER's order history must show:
  "Widget Seven" (what they bought)

CHECKOUT SCHEMA (checkout-svc owns):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CREATE TABLE order_lines (
    order_id       UUID NOT NULL,
    line_id        UUID PRIMARY KEY,
    sku            VARCHAR(32) NOT NULL,  -- reference only
    product_title  VARCHAR(256) NOT NULL, -- snapshot at order time
    unit_price_cents INT NOT NULL,        -- snapshot at order time
    quantity       INT NOT NULL,
    -- NO foreign key to catalog.products
  );

CATALOG SCHEMA (catalog-svc owns):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CREATE TABLE products (
    sku            VARCHAR(32) PRIMARY KEY,
    title          VARCHAR(256),
    ...
  );

ANTI-PATTERN:
  order_lines.product_id FK → catalog.products
  Catalog migration drops column → checkout deploy breaks.
```

### Example 5: ECS Service Discovery — Checkout Calls Inventory

```
CLOUD MAP:
━━━━━━━━━━

  Namespace: svc.local (private DNS)

  Service catalog-svc:
    DNS: catalog.svc.local
    Tasks register on healthy

  Service inventory-svc:
    DNS: inventory.svc.local

CHECKOUT CONFIG:
━━━━━━━━━━━━━━━━

  INVENTORY_BASE_URL=http://inventory.svc.local:8080

RESILIENCE (application + optional App Mesh):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  HTTP client:
    connect timeout: 200ms
    request timeout: 800ms
    retry: 0 on ReserveStock (not idempotent without token)
    circuit breaker: 50% failures in 30s → open 60s

  App Mesh virtual router:
    maxRetries: 0  # retries on reserve are dangerous
    perRetryTimeout: 0

HEALTH CHECKS:
━━━━━━━━━━━━━━

  ALB: /health on checkout (public)
  ECS: container health for task replacement
  inventory: /health includes DynamoDB connectivity check
```

### Example 6: EKS Canary with Argo Rollouts

```
checkout-svc deployment with canary:

apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: checkout-svc
  namespace: checkout-team
spec:
  replicas: 10
  strategy:
    canary:
      steps:
        - setWeight: 10
        - pause: { duration: 10m }
        - setWeight: 25
        - pause: { duration: 10m }
        - setWeight: 50
        - pause: { duration: 10m }
        - setWeight: 100
      trafficRouting:
        alb:
          ingress: checkout-ingress
          service: checkout-svc-stable
          rootService: checkout-svc-root
  selector:
    matchLabels:
      app: checkout-svc
  template:
    metadata:
      labels:
        app: checkout-svc
    spec:
      containers:
        - name: checkout
          image: 123.dkr.ecr.us-east-1.amazonaws.com/checkout:v3.2.0

Analysis during pause:
  Prometheus query: rate(http_requests_total{status=~"5.."}[5m])
  Must be < baseline + 0.1% or rollback automatic
```

### Example 7: Distributed Monolith — Dependency Graph Autopsy

```
INCIDENT POSTMORTEM SNIPPET (ShopFast, fictional):

  "We had 11 microservices but every deploy required
   coordinated release of 6 repos."

DEPENDENCY GRAPH (checkout request):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  checkout-svc
    → user-svc (auth, profile)
    → catalog-svc (product details)
    → pricing-svc (dynamic price)
    → tax-svc (jurisdiction)
    → inventory-svc (reserve)
    → payment-svc (charge)
    → promotions-svc (coupons)
    → fraud-svc (score)
    → shipping-svc (rate estimate)

  Depth: 9 serial sync calls (some parallelized to 4 waves)
  p99 latency: 2.8s normal, 12s under load

SHARED DB DISCOVERY:
━━━━━━━━━━━━━━━━━━━━

  user-svc, checkout-svc, promotions-svc → same RDS instance
  schemas: users, orders, promotions with cross-FKs

FIX (18-month program):
━━━━━━━━━━━━━━━━━━━━━━━

  1. Snapshot denormalization in checkout (remove catalog sync)
  2. Async fraud post-order (remove sync fraud)
  3. Extract payments to isolated RDS + PCI VPC
  4. Merge pricing into catalog context (one hop removed)
  5. BFF for product page aggregation (remove gateway N+1)
  6. Team reorg: 4 stream-aligned teams matching 4 contexts
```

---

## Production Patterns

### Pattern 1: Database-per-Service with CDC Read Replicas

```
PROBLEM:
  Reporting needs cross-context data.
  Teams want JOINs.

SOLUTION:
  Each service writes only to its DB.
  CDC (DMS, Debezium) streams to:
    • S3 data lake → Athena (ad-hoc)
    • Redshift (BI dashboards)
    • OpenSearch (customer-facing search)

  Services NEVER query warehouse for transactional paths.

AWS:
  RDS → DMS → S3 (Parquet) → Glue Catalog
  MSK Connect Debezium source → S3 sink

SLO:
  Warehouse lag p95 < 15 min (analytics)
  Search index lag p95 < 30s (product discovery)
```

### Pattern 2: Anti-Corruption Layer (ACL) Service

```
WHEN:
  Upstream model is legacy or external (Stripe, SAP, monolith)

ACL as separate module or thin service:
  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
  │ checkout    │────►│ payment-svc │────►│ Stripe API  │
  │ (domain)    │     │ + ACL layer │     │ (external)  │
  └─────────────┘     └─────────────┘     └─────────────┘

  checkout speaks: CapturePayment { orderId, amountCents }
  ACL translates: Stripe PaymentIntent.create(...)

  Stripe webhook → ACL → PaymentCaptured domain event

BENEFIT:
  Replace Stripe with Adyen — checkout unchanged.
```

### Pattern 3: Strangler Facade at ALB

```
Terraform-style mental model:

  listener_rule catalog_v2 {
    priority = 10
    condition { path_pattern { values = ["/api/v2/catalog/*"] } }
    action {
      forward {
        target_group { arn = aws_lb_target_group.catalog.arn weight = 100 }
      }
    }
  }

  listener_rule default_monolith {
    priority = 100
    action { forward { target_group { arn = aws_lb_target_group.monolith.arn } } }
  }

  Canary: two target groups, weighted forward block
```

### Pattern 4: Internal API vs Public API

```
Each service exposes:
  PUBLIC API (versioned, SLA, documented):
    GET /api/v1/products/{sku}
    Rate limited, backward compatible

  INTERNAL API (breaking changes allowed with notice):
    GET /internal/products/{sku}?includeCost=true
    mTLS only, not on public gateway

  Partner API (separate gateway, API keys):
    GET /partner/v1/inventory/availability

  Prevents: internal fields leaked to mobile clients
  Prevents: partner rate limits affecting consumer traffic
```

### Pattern 5: Bulkhead by Service Pool (ECS)

```
Separate ECS services for sync API vs async workers:

  checkout-svc-api     (ALB attached, 2-20 tasks)
  checkout-svc-outbox  (no ALB, 2-10 tasks, MSK consumer)

  Worker spike from DLQ replay does NOT steal CPU from API tasks.

EKS equivalent:
  deployment/checkout-api (HPA on CPU)
  deployment/checkout-worker (HPA on Kafka lag metric)
```

### Pattern 6: Contract Testing Between Services

```
PROBLEM:
  catalog-svc deploy breaks checkout-svc silently.

SOLUTION:
  Pact / consumer-driven contracts in CI:

  checkout-svc (consumer) defines expected:
    GET /products/WIDGET-7 → 200 { sku, title, price }

  catalog-svc (provider) verifies against pact file on deploy.

  Fails CI if provider removes `price` field.

  Complement with schema registry for async events (Avro).
```

### Pattern 7: Platform Golden Path (ECS)

```
Terraform module: ecs-service-standard

  Inputs: name, image, cpu, memory, port, health_path,
          env, secrets_arn, autoscale_target_cpu

  Outputs: service ARN, log group, Cloud Map registration,
           standard dashboards, alarm templates

  Stream-aligned team:
    module "catalog_svc" {
      source = "git::platform/ecs-service-standard"
      name   = "catalog-svc"
      ...
    }

  Cognitive load: team focuses on domain, not ALB idle timeout.
```

### Pattern 8: Zero-Trust East-West (EKS + Istio)

```
PeerAuthentication: STRICT mTLS mesh-wide

AuthorizationPolicy catalog-svc:
  allow:
    principals: ["cluster.local/ns/checkout-team/sa/checkout-svc"]
  to:
    operations: [{ methods: ["GET"], paths: ["/api/v1/products/*"] }]

  deny all other east-west by default.

Replaces: security group sprawl with 200 rules
Requires: identity per service account (IRSA on AWS)
```

---

## Failure Modes

### Failure 1: Shared Database Lock Contention

```
SCENARIO:
  inventory-svc migration adds index on shared RDS.
  checkout-svc transactions block on ACCESS EXCLUSIVE lock.

SYMPTOM:
  checkout p99 latency 50ms → 8000ms
  RDS: DatabaseConnections high, blocked_sessions > 0

ROOT CAUSE:
  Distributed monolith — shared DB anti-pattern

FIX (immediate):
  Cancel migration or use CONCURRENTLY index build

FIX (structural):
  inventory-svc → own DynamoDB or separate RDS instance
  No cross-schema migrations ever again
```

### Failure 2: Circular Dependency Deploy Deadlock

```
SCENARIO:
  pricing-svc v4 requires catalog-svc v3 response shape.
  catalog-svc v3 requires pricing-svc v4 for margin field.

SYMPTOM:
  Neither team can deploy. Feature freeze 2 weeks.

DETECTION:
  Deploy dependency graph in CI flags cycle

FIX:
  Break cycle: catalog stores cached margin snapshot,
  updated by PriceChanged event (async).
  Remove sync pricing call from catalog read path.
```

### Failure 3: BFF Becomes God Object

```
SCENARIO:
  web-bff grows to 40 endpoints, implements promo rules,
  calls 9 services, has its own Redis cache of order data.

SYMPTOM:
  Every feature needs web team + 3 backend teams.
  BFF deploy breaks mobile (unrelated code paths).

FIX:
  Split web-bff / mobile-bff
  Move promo logic to promotions-svc
  BFF only aggregates presentation
```

### Failure 4: Strangler Cutover Without Parity

```
SCENARIO:
  catalog-svc cutover at 100% traffic.
  Price sync lag 15 min from CDC stall unnoticed.

SYMPTOM:
  Customers see stale prices. Regulatory complaint.

FIX (immediate):
  Rollback ALB weights to monolith

FIX (process):
  Parity gate: automated price diff alert
  CDC lag SLO page before any weight increase
```

### Failure 5: Sync Chain Under Black Friday Load

```
SCENARIO:
  9-hop checkout chain. inventory-svc saturates at 10k RPS.

SYMPTOM:
  Thread pools cascade (Week 6 T5).
  Entire site checkout down. Catalog browse OK.

FIX (immediate):
  Circuit breaker open on non-critical hops (shipping estimate)
  Scale inventory-svc tasks 10 → 80

FIX (structural):
  Remove hops: snapshot pricing in cart
  Async fraud scoring
  Target depth ≤ 2 on checkout critical path
```

### Failure 6: Wrong Boundary — Order Data in Three Services

```
SCENARIO:
  order-svc, billing-svc, shipping-svc each store orderId
  with partial overlapping fields. No aggregate owner.

SYMPTOM:
  order status = SHIPPED in shipping-svc,
  order status = PROCESSING in order-svc.
  Customer support chaos.

FIX:
  order-svc owns Order aggregate and status state machine.
  Others store references + their context-specific data only.
  Shipping stores { orderId, trackingNumber } not full order.
```

### Failure 7: ECS Service Discovery Stale After Deploy

```
SCENARIO:
  inventory-svc deploy replaces all tasks.
  Cloud Map DNS TTL 60s. checkout-svc connection pool
  holds dead IPs for 5 min (keep-alive).

SYMPTOM:
  5% connection refused errors for 5 min post-deploy

FIX:
  Reduce client connection pool idle timeout
  Graceful draining: deregister task, wait drain, stop
  ECS minimumHealthyPercent 100, maximumPercent 200
```

### Failure 8: Namespace Blast Radius (EKS)

```
SCENARIO:
  catalog-team deployment applies ClusterRole by mistake.
  All namespaces affected.

FIX:
  RBAC: teams edit only their namespace
  Policy: OPA/Gatekeeper deny ClusterRole from app teams
  Separate clusters for prod vs exp if needed
```

---

## SRE Diagnostic Toolkit

```
MICROSERVICES INCIDENT TRIAGE — FIRST 5 MINUTES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Is it ONE service or EVERYTHING?
     → One: boundary might be working; fix that service
     → Everything: distributed monolith failure — find shared dependency

  2. Was there a deploy in last 30 min? (any of N services)

  3. Shared infrastructure? (RDS, MSK, NAT gateway, DNS)

  4. Sync chain depth on failing path? (trace)

  5. Recent schema migration on shared DB?


SERVICE HEALTH (ECS):
━━━━━━━━━━━━━━━━━━━━━

  # Service events (deploy failures, task stops)
  aws ecs describe-services \
    --cluster prod \
    --services checkout-svc catalog-svc inventory-svc \
    --query 'services[*].{name:serviceName,running:runningCount,desired:desiredCount,events:events[0:3]}'

  # Stopped task reason (OOM, health check fail)
  aws ecs list-tasks --cluster prod --service-name checkout-svc --desired-status STOPPED
  aws ecs describe-tasks --cluster prod --tasks $TASK_ARN \
    --query 'tasks[0].{stopCode:stopCode,reason:stoppedReason,containers:containers[*].reason}'

  # CPU/memory utilization
  aws cloudwatch get-metric-statistics \
    --namespace AWS/ECS \
    --metric-name CPUUtilization \
    --dimensions Name=ClusterName,Value=prod Name=ServiceName,Value=checkout-svc \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
    --period 60 --statistics Average Maximum


SERVICE HEALTH (EKS):
━━━━━━━━━━━━━━━━━━━

  kubectl get pods -n checkout-team -l app=checkout-svc
  kubectl describe pod $POD -n checkout-team | grep -A5 Events
  kubectl top pods -n checkout-team

  # HPA status
  kubectl get hpa -n checkout-team


ALB / TARGET GROUP:
━━━━━━━━━━━━━━━━━

  # Unhealthy targets
  aws elbv2 describe-target-health \
    --target-group-arn $TG_ARN

  # 5xx by target group
  aws cloudwatch get-metric-statistics \
    --namespace AWS/ApplicationELB \
    --metric-name HTTPCode_Target_5XX_Count \
    --dimensions Name=TargetGroup,Value=targetgroup/checkout/abc \
    --period 60 --statistics Sum ...


X-RAY / DISTRIBUTED TRACE:
━━━━━━━━━━━━━━━━━━━━━━━━

  Filter: service(checkout-svc) AND fault = true
  Sort by duration descending

  Look for:
    • Long downstream segment (inventory-svc 4.2s)
    • Repeated same segment (retry storm)
    • Missing segment (timeout, no response recorded)

  Trace depth > 4 on checkout → architectural smell document


RDS (SHARED DB DETECTION):
━━━━━━━━━━━━━━━━━━━━━━━━

  # Blocking queries
  SELECT pid, usename, state, wait_event_type, wait_event,
         left(query, 100) AS query
  FROM pg_stat_activity
  WHERE state != 'idle' AND wait_event_type = 'Lock';

  # Long running migrations
  SELECT * FROM pg_stat_activity
  WHERE query LIKE '%CREATE INDEX%' OR query LIKE '%ALTER TABLE%';

  # Which schema is hot?
  SELECT schemaname, relname, seq_scan, idx_scan, n_live_tup
  FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 20;

  If multiple service names in application_name column on same
  RDS instance → shared DB anti-pattern confirmed.


SERVICE MESH (App Mesh / Istio):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # 5xx rate per virtual service
  istioctl metrics checkout-svc.checkout-team.svc.cluster.local

  # Circuit breaker ejections
  envoy cluster upstream_rq_retry, upstream_cx_connect_fail


DEPLOY COUPLING AUDIT:
━━━━━━━━━━━━━━━━━━━━━━

  # Git: commits in last 24h across repos
  for repo in checkout catalog inventory payment; do
    echo "=== $repo ===" && git -C $repo log --oneline --since=24h
  done

  Correlated deploys across 4+ repos for one feature → coupling


CLOUD MAP DNS:
━━━━━━━━━━━━━━

  dig inventory.svc.local
  # Verify multiple A records during rolling deploy
  # Stale records if TTL high and tasks killed hard
```

### Reconciliation Queries — Cross-Service Drift

```
-- checkout DB: orders marked CONFIRMED without reservation ref
SELECT order_id, created_at
FROM orders
WHERE status = 'CONFIRMED'
  AND inventory_reservation_id IS NULL
  AND created_at > now() - interval '1 hour';

-- Compare order count (checkout) vs shipment count (fulfillment)
-- Run in warehouse after CDC, not cross-DB live query

-- Catalog price vs checkout cart line (staleness audit)
-- Application-level batch job, not SQL JOIN across DBs
```

### Log Patterns (CloudWatch Logs Insights)

```
# Sync timeout to inventory from checkout
fields @timestamp, @message
| filter @message like /inventory.svc.local/ and @message like /timeout/
| stats count() by bin(5m)

# Circuit breaker open events
fields @timestamp, downstream, state
| filter @message like /CircuitBreaker.*OPEN/
| sort @timestamp desc

# Deploy correlation
fields @timestamp, @message
| filter @message like /Starting application/ or @message like /version=/
| parse @message /version=(?<ver>[^\s]+)/
| stats count() by ver, bin(1m)
```

---

## Decision Framework

```
MICROSERVICES DECISION TREE:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  START: Do you have organizational pain from monolith deploy?
    NO  → stay modular monolith
    YES → continue

  Do you know your bounded contexts (event storming done)?
    NO  → DDD workshop first; do NOT split by table
    YES → continue

  Which capability to extract first?
    Read-heavy leaf?     → strangler Phase 1 (catalog, reviews)
    Async-only consumer? → new service behind events
    Money path?          → LAST; fix boundaries on paper first

  Integration choice for this boundary:
    User waiting?              → sync (≤2 hops)
    Side effect / fan-out?     → async (outbox + event)
    Cross-context report?      → CDC to warehouse

  Data store for new service:
    Complex transactions in context? → RDS Postgres
    High write key-value stock?      → DynamoDB
    Full-text search?                → OpenSearch (projection)

  Runtime:
    Team knows K8s?  → EKS
    AWS-native ops?  → ECS Fargate
    <5 services?     → ECS often sufficient


API GATEWAY vs MESH vs DIRECT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Client → system:     API Gateway or ALB + WAF
  BFF → services:      direct (Cloud Map / ClusterIP) + CB
  Service → service:   mesh optional at 10+ services
  Batch / async:       MSK/SQS (no HTTP)


TEAM TOPOLOGY CHECK:
━━━━━━━━━━━━━━━━━━━━

  For each proposed service, answer:
    • Named stream-aligned team owner? (not "platform")
    • Team can own on-call for this context alone?
    • Cognitive load ≤ 2 bounded contexts?

  If any NO → fix team or boundary before building.


STRANGLER GO / NO-GO:
━━━━━━━━━━━━━━━━━━━━━

  GO when:
    ✓ Parity metrics defined and automated
    ✓ Rollback tested (<60s traffic flip)
    ✓ Data migration reversible or backup verified
    ✓ Owning team on-call for new service

  NO-GO when:
    ✗ "Big bang" cutover Friday 5 PM
    ✗ No shadow period for money-adjacent paths
    ✗ Shared write path to monolith DB without CDC lag SLO
```

### Integration Style Matrix

```
┌─────────────────────┬──────────────┬───────────────┬─────────────┐
│ From → To           │ User-facing? │ Consistency   │ Use         │
├─────────────────────┼──────────────┼───────────────┼─────────────┤
│ checkout → inventory│ Yes          │ Strong reserve│ Sync gRPC   │
│ checkout → payment  │ Yes          │ Strong charge │ Sync HTTP   │
│ checkout → email    │ No           │ Eventual      │ Async SQS   │
│ catalog → search    │ No           │ Eventual 30s  │ Async CDC   │
│ analytics ← all     │ No           │ Eventual hrs  │ Async MSK   │
│ admin report        │ No           │ Snapshot      │ Warehouse   │
└─────────────────────┴──────────────┴───────────────┴─────────────┘
```

---

## Ops Sim: Northstar Seller Profile Cascade

**Time box:** 50 minutes  
**Severity:** P1  
**Service / domain:** Seller profile service, GraphQL BFF, service discovery, shared Redis auth cache  
**Northstar system:** Northstar Commerce

### Practice rules

1. Answer from memory of the Microservices Patterns teaching section; do not re-read mid-drill.
2. Write decisions in order: T+0, T+5, T+15, T+30, T+60, and follow-up.
3. Tie every claim to a metric, log line, trace, query output, or config key from this packet.
4. Name the correctness invariant before proposing scale, failover, replay, or data repair.
5. Do not open the answer key until your response is written.

---

### What is happening

```text
WHAT USERS SEE:
  - Product pages show blank seller names, then whole pages 500.
  - Marketplace checkout stalls; first-party checkout works.
  - Support tool cannot load seller contact panels.
  - Seller dashboard login succeeds but every tab spins.

WHAT ON-CALL SEES:
  - Seller-profile has 40% errors, but BFF error rate is much higher.
  - Retries lift seller-profile QPS from 3k to 48k.
  - Shared Redis auth/metadata cache hits maxclients.
  - GraphQL non-null seller field bubbles failure to page root.

BUSINESS CONSTRAINT:
  Do not bypass tenant auth or compliance; seller display metadata may degrade.
```

### Root-cause mechanics

A decorative seller-profile call became mandatory in broad GraphQL fanout. Retries from product, checkout, and support saturate a shared Redis cluster used by auth.

Break it into these forces before answering:
- trigger: the release/config/data shape that started the failure
- amplifier: retry, cache, routing, projection, or observability behavior that widened it
- scarce resource: the metric that reaches a limit first
- invariant: what must remain conservative even while users see degraded experience
- repair boundary: the source of truth and operation id used after mitigation

### Change clues

- The suspicious production lever is `graphql.seller_display.nullable: false`; tie it to the first bad minute before changing capacity.
- The dashboard that stayed calm does not expose `bff_request_duration_seconds{route="product",p99}` for the damaged slice.
- The runbook move closest to "scale seller-profile 10x first" needs an explicit no-go decision on the bridge.
- The repair path is allowed only after the source-of-truth query and operation key are written down.

### Telemetry card

```text
METRICS:
  - bff_request_duration_seconds{route="product",p99}: 0.21 -> 5.4
  - checkout_marketplace_latency_seconds{p99}: 0.48 -> 6.8
  - seller_profile_error_rate: 0.4
  - seller_profile_qps: 3k -> 48k
  - upstream_retry_total{dependency="seller-profile"}: +2.8M/10m
  - redis_connected_clients{cluster="shared-auth-meta"}: 1200 -> 18000
  - auth_introspection_latency_ms{p99}: 18 -> 780
  - first_party_checkout_success_rate: 99.97%

LOG LINES:
  - bff: non-null GraphQL field seller.displayName failed; null bubbling to ProductPage
  - checkout: retry seller-profile attempt=3 reason=deadline_exceeded
  - seller-profile: compliance lookup timeout seller_id=s-441
  - redis: maxclients reached db=auth-meta
  - auth: token cache miss due redis timeout tenant=marketplace

TRACE / QUERY / INSPECTION NOTES:
  - Trace calls seller-profile before inventory/payment for marketplace checkout.
  - Readiness probe checks process health, not compliance dependency.
  - First-party checkout isolates the dependency slice.
  - Auth latency begins after metadata retry storm.
```

### Config card

```yaml
graphql.seller_display.nullable: false
seller_profile.required_for_checkout: true
retry.max_attempts: 3
redis.pool.auth_and_metadata_shared: true
service_discovery.outlier_ejection: disabled
```

### Decision table

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | Marketplace surfaces degrade; first-party checkout is fine. | Identify fanout boundary. |
| T+5 | Scale seller-profile 10x is proposed. | Cap retries first. |
| T+15 | Redis auth cache is saturated. | Reserve auth capacity. |
| T+30 | Null bubbling confirmed. | Make display data degradable. |
| T+60 | Cached display stabilizes traffic. | Repair stale metadata. |
| T+24h | Architecture review asks about boundaries. | Write dependency classification. |

### Recovery tools

- Roll back or disable the specific dangerous config from the packet.
- Shed decorative, derived, notification, or analytics work before weakening source-of-truth correctness.
- Throttle retry/replay using the narrowest downstream capacity limit.
- Keep an affected-record ledger before customer-visible repair.
- Verify recovery with the sliced SLI plus the scarce-resource metric, not a fleet average.

### Do-not-do list

For each proposal, name the concrete failure mode it creates.

- scale seller-profile 10x first
- bypass auth to restore dashboards
- return empty compliance-required data
- shut down all marketplace checkout

### Questions

**Q01.** What exact layer owns the failure and why is the most obvious graph a red herring?

**Q02.** Which config line is wrong, and what failure physics does it create?

**Q03.** Select three metrics and two log/inspection clues that prove your diagnosis.

**Q04.** What is the safe T+0 to T+5 announcement and freeze/rollback decision?

**Q05.** What do you stop first: trigger, amplifier, or repair job? Explain sequencing.

**Q06.** What invariant must remain true if every dashboard is stale?

**Q07.** Which bad fix is most tempting in this incident, and why does it make recovery worse?

**Q08.** What numeric capacity or blast-radius check is required before scale/failover/replay?

**Q09.** What is the source-of-truth query or ledger for the affected set?

**Q10.** Which derived systems may lag, and which external side effects require idempotency?

**Q11.** Write the durable config/architecture change and its acceptance test.

**Q12.** Who joins by T+10, and what is pre-authorized versus escalated?

### Self-score

| Error type | Count | Notes |
|------------|-------|-------|
| Wrong layer/root cause | | |
| Evidence gap | | |
| Unsafe first action | | |
| Capacity/blast-radius miss | | |
| Correctness invariant miss | | |
| Repair/replay mistake | | |
| Org/runbook gap | | |

**Pass bar:** correct mechanism, safe sequencing, explicit rejection of the bad fix, one numeric capacity check, and a repair plan grounded in source of truth.

**Answer key:** [answers/Week-06-Architecture-Patterns/Microservices Patterns Answers.md](../answers/Week-06-Architecture-Patterns/Microservices%20Patterns%20Answers.md)

