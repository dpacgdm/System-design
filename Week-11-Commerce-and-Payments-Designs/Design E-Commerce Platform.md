
# Design E-Commerce Platform

> Week 11, Topic 2 — System Design. Catalog, search, inventory, cart, checkout,
> orders, and CDN integration per Week 1 CDN Fundamentals.

**Prerequisite mental model.** E-commerce is consistency choreography: oversell
prevention, cart merge, search freshness, checkout sagas, and CDN cache safety.


---

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════════════╗
║ AFTER THIS MODULE, YOU WILL BE ABLE TO:                                  ║
║                                                                          ║
║ 1. Design inventory reservation with TTL and flash-sale sharding         ║
║ 2. Build guest/authenticated cart with idempotent checkout               ║
║ 3. Integrate OpenSearch with CDC-driven catalog freshness                ║
║ 4. Apply CDN strategy: images, PLP/PDP, API caching, poisoning prevention║
║ 5. Diagnose flash-sale cascades, stale search, cart split-brain          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═══════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "Inventory = COUNT(*)"                           ║
║ WRONG. Sellable = on_hand - reserved - safety_stock.              ║
║ Use atomic conditional updates or reservation table.              ║
║                                                                   ║
║ MENTAL MODEL #2: "Cart in cookie"                                 ║
║ WRONG. Server-side cart in DynamoDB; cookie holds cart_id only.   ║
║                                                                   ║
║ MENTAL MODEL #3: "Search index = catalog"                         ║
║ WRONG. Postgres/Dynamo catalog is truth; OpenSearch is projection.║
║                                                                   ║
║ MENTAL MODEL #4: "CDN long TTL on PDP"                            ║
║ WRONG. Price/stock change. Short s-maxage + SWR or ESI.           ║
║ Never cache /account/* as public (CDN Fundamentals P1 incident).  ║
║                                                                   ║
║ MENTAL MODEL #5: "Checkout = one POST"                            ║
║ WRONG. Multi-step saga with compensations (Week 6).               ║
║                                                                   ║
║ MENTAL MODEL #6: "Flash sale = scale DB"                          ║
║ WRONG. Hot SKU is single-key bottleneck; shard and queue.         ║
╚═══════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching


### Step 1: Requirements

```
FUNCTIONAL:
  F1. Browse catalog (categories, PDP, PLP)
  F2. Search with filters, sort, autocomplete
  F3. Cart (add/update/remove, guest + logged-in merge)
  F4. Checkout (address, shipping, tax, payment)
  F5. Order tracking, returns initiation
  F6. Admin: product CRUD, inventory adjust, promotions

NON-FUNCTIONAL:
  NFR1. Oversell rate: 0% (hard requirement)
  NFR2. Search p99 < 200ms; PDP p99 < 300ms (CDN-assisted)
  NFR3. Flash sale: 50K add-to-cart/min on single SKU
  NFR4. Availability 99.95% (browse); checkout 99.99%
  NFR5. CDN offload > 90% bytes for static + images
```

### Step 2: Capacity

```
  20M MAU, 2M DAU
  10% DAU search: 200K searches/day ≈ 2.3/sec avg, 50/sec peak
  2% purchase: 40K orders/day ≈ 0.5/sec avg, 15/sec peak
  Flash: 500 orders/sec for 10 min on one SKU

  Images: 10M SKUs × 5 images × 200KB avg → 10 TB object storage (S3)
  CDN: 95% hit → origin 5% = manageable
  Search index: ~50 GB OpenSearch
```

### Step 3: Architecture

```
                    ┌──────── CloudFront CDN ────────┐
                    │  /static/*  /images/*  /api/public/* │
                    └───────────────┬────────────────┘
                                    │
                    ┌───────────────▼────────────────┐
                    │   ALB + WAF (api.shop.com)     │
                    └───────────────┬────────────────┘
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
   ┌─────────────┐          ┌─────────────┐          ┌─────────────┐
   │ BFF / API   │          │ Search API  │          │ Admin API   │
   │ Gateway     │          │             │          │             │
   └──────┬──────┘          └──────┬──────┘          └──────┬──────┘
          │                        │                        │
    ┌─────┴─────┬─────────┬────────┴───┬──────────┐        │
    ▼           ▼         ▼            ▼          ▼        ▼
 Catalog    Inventory   Cart      Checkout   Order    OpenSearch
 Service    Service     Service   Saga(SF)   Service   Cluster
    │           │         │            │          │
    ▼           ▼         ▼            ▼          ▼
  RDS PG    DynamoDB   DynamoDB    Payment    RDS PG   (index)
 (products) (stock)    (carts)     Platform   (orders)
                │
                └── CDC (Debezium) ──► MSK ──► Search indexer
```

### Step 4: Catalog Service

```
  products(id, sku, title, description, price_cents, currency, version)
  categories, product_categories (many-to-many)
  price_history (append-only for audit)

  Read path: cache-aside Redis, TTL 60s for PDP metadata
  Write path: admin → RDS → outbox event → MSK product.updated

  CDN (Week 1): product images at images.shop.com/{sku}/{hash}.webp
  Versioned filename = content hash → immutable, max-age=31536000
```

### Step 5: Inventory Service

```
  DynamoDB table inventory:
    PK: SKU#WIDGET-42
    SK: WAREHOUSE#US-EAST
    on_hand: 1000
    reserved: 47
    safety_stock: 50
    version: 1847  (optimistic locking)

  sellable = on_hand - reserved - safety_stock

  RESERVE (conditional update):
    ConditionExpression: sellable >= :qty
    Update: reserved += :qty
    Returns reservation_id, expires_at = now + 15min

  reservation table:
    PK: reservation_id
    sku, qty, cart_id, status: HELD|COMMITTED|RELEASED
    TTL on HELD past expires_at (DynamoDB TTL stream → release job)

  FLASH SALE — hot key mitigation:
    Partition SKU into SHARD#0..SHARD#N (N=16)
    Reserve round-robin or hash(cart_id) % N
    Sum shards for display "approximate stock" (eventual)
    OR pre-allocate pool per shard (strict per-shard cap)

  COMMIT on payment capture; RELEASE on saga compensate
```

### Step 6: Cart Service

```
  DynamoDB carts:
    PK: cart_id (UUID, guest cookie or user-linked)
    SK: ITEM#{sku}
    qty, price_snapshot_cents, added_at

  GSI: user_id → cart_id (one active cart per user)

  MERGE on login:
    guest_cart_id + user_cart_id → merge items (sum qty, cap max 99)
    Delete guest cart; set cookie to user cart

  price_snapshot: detect price change at checkout → prompt user
  Cart expiry: 30 days TTL refresh on write
```

### Step 7: Search (OpenSearch)

```
  Index: products_v1
  Fields: title^3, description, brand, category_path, price, in_stock_bool
  Facets: category, brand, price_range, rating

  Indexing pipeline:
    Debezium CDC from products + inventory → MSK topic catalog.events
    Indexer consumer: upsert/delete, bulk 500 docs/batch
    Lag SLO: p99 < 30s from product update to searchable

  in_stock_bool: updated from inventory events (reservation ≠ searchable fine)
  Stale search mitigation: checkout re-validates inventory (source of truth)

  Autocomplete: separate edge n-gram index, aggressive caching at CDN
  GET /api/public/autocomplete?q=wid  Cache-Control: public, s-maxage=60
```

### Step 8: Checkout Saga

```
  Same orchestration as Payment System module:
    ValidateCart → ReserveInventory → ComputeTax → AuthorizePayment →
    CreateOrder → CapturePayment → CommitInventory → SendConfirmation

  Compensations reverse order; ReleaseInventory before Refund when possible

  place_order idempotency_key from client (required)
```

### Step 9: CDN Strategy (Week 1 CDN Fundamentals)

```
  STATIC ASSETS (JS/CSS):
    Path: /static/{contenthash}.js
    Cache-Control: public, max-age=31536000, immutable
    CloudFront OAC → S3 origin
    (Week 1: versioned URLs = gold standard invalidation)

  PRODUCT IMAGES:
    Path: /images/{sku}/{phash}.webp
    Cache-Control: public, max-age=86400, stale-while-revalidate=3600
    Origin: S3 + Lambda@Edge optional WebP negotiation

  PLP (category pages):
    HTML shell: short TTL
    Cache-Control: public, s-maxage=120, stale-while-revalidate=60
    API-driven product grid: GET /api/public/plp?cat=shoes
      s-maxage=60 — NEVER cache with Set-Cookie

  PDP (product detail):
    Public metadata API: s-maxage=30, SWR=15
    Price in API response (not HTML) — reduces stale price risk
    Personalized recs: separate /api/private/recs Cache-Control: private

  POISONING PREVENTION (Week 1 incident):
    /account/* → origin Cache-Control: private, no-store
    CloudFront behavior: forward all cookies, no cache for /account/*
    Verify: curl -I must NOT show X-Cache: Hit for authenticated routes

  ORIGIN OFFLOAD MATH (Week 1):
    1M PDP views/day, 200KB page assets, 95% CDN hit
    Origin: 50K × 200KB = 10 GB/day vs 200 GB without CDN
```

### Step 10: Order Service

```
  orders (
    order_id UUID PK,
    user_id, cart_id, status,
    total_cents, tax_cents, shipping_cents,
    payment_intent_id, created_at
  )
  order_lines (order_id, sku, qty, unit_price_cents, snapshot_title)

  Status machine:
    PENDING_PAYMENT → PAID → FULFILLING → SHIPPED → DELIVERED
                     ↘ CANCELLED (before ship)
                     ↘ RETURN_REQUESTED → RETURNED

  Immutable price snapshot on order_lines — never retroactive price change
  Outbox: order.placed → warehouse WMS, email service, analytics
```

### Step 11: Promotions and Pricing

```
  promotions table: code, type (percent|fixed|bogo), start/end, max_redemptions
  Application order at checkout:
    1. Item-level sale price (catalog)
    2. Cart-level promo code
    3. Shipping promo
  Race: promo max_redemptions — conditional decrement in checkout saga
  Do NOT cache promo-eligible price at CDN edge without version key
```

### Step 12: Tax and Shipping

```
  Tax: integrate Avalara/Stripe Tax — address → jurisdiction → rate
  Cache tax rates by zip+sku category 24h (not per-user)
  Shipping: rate quotes from carriers API; snapshot selected rate on order
  International: duties estimate separate line item (disclaimer)
```

### Step 13: Returns and Refunds

```
  Return saga: CreateRMA → ReceiveWarehouse → Inspect → RefundPayment
  Refund amount ≤ line snapshot price; partial qty supported
  Inventory: restock good items (on_hand++); damaged → quarantine bucket
  Connects to Payment System refund API with idempotency_key=return_id
```

### Step 14: Recommendations (Optional Extension)

```
  /api/private/recs — Cache-Control: private, no-store
  Feature store or batch embeddings; never mix with public PDP cache
  "Customers also bought" — async precompute per sku, store Redis, TTL 1h
```

### Step 15: Multi-Region and DR

```
  Active-active browse: CloudFront global, origin us-east-1 + eu-west-1
  Catalog read replicas per region; writes single-primary (avoid split brain)
  Inventory: authoritative per warehouse region; cross-region ship = separate pool
  RPO orders: 0 (sync replicate); RTO: 15 min runbook failover
```

### Step 16: API Surface (BFF)

```
  GET  /api/v1/products/{sku}        — PDP aggregate (catalog+inventory hint+reviews)
  GET  /api/v1/search                 — OpenSearch proxy, rate limited
  GET  /api/v1/cart                   — Auth or cart_id header
  POST /api/v1/cart/items             — Add line
  POST /api/v1/checkout/place-order   — Idempotency-Key required
  GET  /api/v1/orders/{id}            — Order status
  POST /api/v1/returns                — Start return

  Public CDN-cacheable paths prefixed /api/public/ only
```


### API Catalog (Detailed)


```
GET /api/public/plp
  Purpose:     category listing
  CDN/cache:   s-maxage=120
  Parameters:  cat, sort, page
  Errors:      409 OUT_OF_STOCK, 422 PRICE_CHANGED, 409 IDEMPOTENCY_MISMATCH
```


```
GET /api/public/pdp
  Purpose:     product detail JSON
  CDN/cache:   s-maxage=30
  Parameters:  sku
  Errors:      409 OUT_OF_STOCK, 422 PRICE_CHANGED, 409 IDEMPOTENCY_MISMATCH
```


```
GET /api/public/autocomplete
  Purpose:     search suggest
  CDN/cache:   s-maxage=60
  Parameters:  q
  Errors:      409 OUT_OF_STOCK, 422 PRICE_CHANGED, 409 IDEMPOTENCY_MISMATCH
```


```
GET /api/v1/cart
  Purpose:     full cart
  CDN/cache:   no-store
  Parameters:  cart_id cookie
  Errors:      409 OUT_OF_STOCK, 422 PRICE_CHANGED, 409 IDEMPOTENCY_MISMATCH
```


```
POST /api/v1/cart/items
  Purpose:     add SKU
  CDN/cache:   no-store
  Parameters:  sku, qty
  Errors:      409 OUT_OF_STOCK, 422 PRICE_CHANGED, 409 IDEMPOTENCY_MISMATCH
```


```
PATCH /api/v1/cart/items/{sku}
  Purpose:     update qty
  CDN/cache:   no-store
  Parameters:  qty
  Errors:      409 OUT_OF_STOCK, 422 PRICE_CHANGED, 409 IDEMPOTENCY_MISMATCH
```


```
DELETE /api/v1/cart/items/{sku}
  Purpose:     remove line
  CDN/cache:   no-store
  Parameters:  
  Errors:      409 OUT_OF_STOCK, 422 PRICE_CHANGED, 409 IDEMPOTENCY_MISMATCH
```


```
POST /api/v1/checkout/place-order
  Purpose:     start saga
  CDN/cache:   Idempotency-Key
  Parameters:  cart_id, payment_method
  Errors:      409 OUT_OF_STOCK, 422 PRICE_CHANGED, 409 IDEMPOTENCY_MISMATCH
```


```
GET /api/v1/checkout/status/{token}
  Purpose:     async checkout poll
  CDN/cache:   no-store
  Parameters:  
  Errors:      409 OUT_OF_STOCK, 422 PRICE_CHANGED, 409 IDEMPOTENCY_MISMATCH
```


```
GET /api/v1/orders/{id}
  Purpose:     order detail
  CDN/cache:   private
  Parameters:  
  Errors:      409 OUT_OF_STOCK, 422 PRICE_CHANGED, 409 IDEMPOTENCY_MISMATCH
```

### Minute-by-Minute Interview Walkthrough (45 min)

```
MIN 0-5:   Requirements — clarify marketplace vs first-party, flash sales, geo
MIN 5-10:  Capacity — orders/sec, search QPS, storage, CDN offload math
MIN 10-18: High-level diagram — CDN in front, services, data stores
MIN 18-25: Deep dive inventory + cart (hot path, oversell prevention)
MIN 25-32: Search pipeline + freshness; checkout saga connection
MIN 32-38: CDN strategy (Week 1): static, PDP, poisoning, purge policy
MIN 38-42: Failure modes + scaling flash sale
MIN 42-45: Summary tradeoffs table
```


#### Interview follow-up question 1

```
Q1: How does guest cart merge on login?
Strong answer cites: server-side cart GSI user_id, merge sum qty, delete guest
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 2

```
Q2: What happens when search index lags 2 minutes?
Strong answer cites: checkout validates inventory; display stale in_stock with caveat
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 3

```
Q3: Draw CloudFront behaviors for this system.
Strong answer cites: /static immutable, /api/public short TTL, /account no cache
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 4

```
Q4: How do you prevent inventory oversell at 500 orders/sec?
Strong answer cites: DynamoDB conditional update + reservation TTL + checkout queue
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 5

```
Q5: How does guest cart merge on login?
Strong answer cites: server-side cart GSI user_id, merge sum qty, delete guest
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 6

```
Q6: What happens when search index lags 2 minutes?
Strong answer cites: checkout validates inventory; display stale in_stock with caveat
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 7

```
Q7: Draw CloudFront behaviors for this system.
Strong answer cites: /static immutable, /api/public short TTL, /account no cache
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 8

```
Q8: How do you prevent inventory oversell at 500 orders/sec?
Strong answer cites: DynamoDB conditional update + reservation TTL + checkout queue
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 9

```
Q9: How does guest cart merge on login?
Strong answer cites: server-side cart GSI user_id, merge sum qty, delete guest
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 10

```
Q10: What happens when search index lags 2 minutes?
Strong answer cites: checkout validates inventory; display stale in_stock with caveat
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 11

```
Q11: Draw CloudFront behaviors for this system.
Strong answer cites: /static immutable, /api/public short TTL, /account no cache
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 12

```
Q12: How do you prevent inventory oversell at 500 orders/sec?
Strong answer cites: DynamoDB conditional update + reservation TTL + checkout queue
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 13

```
Q13: How does guest cart merge on login?
Strong answer cites: server-side cart GSI user_id, merge sum qty, delete guest
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 14

```
Q14: What happens when search index lags 2 minutes?
Strong answer cites: checkout validates inventory; display stale in_stock with caveat
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 15

```
Q15: Draw CloudFront behaviors for this system.
Strong answer cites: /static immutable, /api/public short TTL, /account no cache
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 16

```
Q16: How do you prevent inventory oversell at 500 orders/sec?
Strong answer cites: DynamoDB conditional update + reservation TTL + checkout queue
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 17

```
Q17: How does guest cart merge on login?
Strong answer cites: server-side cart GSI user_id, merge sum qty, delete guest
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 18

```
Q18: What happens when search index lags 2 minutes?
Strong answer cites: checkout validates inventory; display stale in_stock with caveat
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 19

```
Q19: Draw CloudFront behaviors for this system.
Strong answer cites: /static immutable, /api/public short TTL, /account no cache
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 20

```
Q20: How do you prevent inventory oversell at 500 orders/sec?
Strong answer cites: DynamoDB conditional update + reservation TTL + checkout queue
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 21

```
Q21: How does guest cart merge on login?
Strong answer cites: server-side cart GSI user_id, merge sum qty, delete guest
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 22

```
Q22: What happens when search index lags 2 minutes?
Strong answer cites: checkout validates inventory; display stale in_stock with caveat
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 23

```
Q23: Draw CloudFront behaviors for this system.
Strong answer cites: /static immutable, /api/public short TTL, /account no cache
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 24

```
Q24: How do you prevent inventory oversell at 500 orders/sec?
Strong answer cites: DynamoDB conditional update + reservation TTL + checkout queue
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 25

```
Q25: How does guest cart merge on login?
Strong answer cites: server-side cart GSI user_id, merge sum qty, delete guest
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 26

```
Q26: What happens when search index lags 2 minutes?
Strong answer cites: checkout validates inventory; display stale in_stock with caveat
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 27

```
Q27: Draw CloudFront behaviors for this system.
Strong answer cites: /static immutable, /api/public short TTL, /account no cache
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 28

```
Q28: How do you prevent inventory oversell at 500 orders/sec?
Strong answer cites: DynamoDB conditional update + reservation TTL + checkout queue
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 29

```
Q29: How does guest cart merge on login?
Strong answer cites: server-side cart GSI user_id, merge sum qty, delete guest
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 30

```
Q30: What happens when search index lags 2 minutes?
Strong answer cites: checkout validates inventory; display stale in_stock with caveat
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 31

```
Q31: Draw CloudFront behaviors for this system.
Strong answer cites: /static immutable, /api/public short TTL, /account no cache
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 32

```
Q32: How do you prevent inventory oversell at 500 orders/sec?
Strong answer cites: DynamoDB conditional update + reservation TTL + checkout queue
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 33

```
Q33: How does guest cart merge on login?
Strong answer cites: server-side cart GSI user_id, merge sum qty, delete guest
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 34

```
Q34: What happens when search index lags 2 minutes?
Strong answer cites: checkout validates inventory; display stale in_stock with caveat
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 35

```
Q35: Draw CloudFront behaviors for this system.
Strong answer cites: /static immutable, /api/public short TTL, /account no cache
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 36

```
Q36: How do you prevent inventory oversell at 500 orders/sec?
Strong answer cites: DynamoDB conditional update + reservation TTL + checkout queue
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 37

```
Q37: How does guest cart merge on login?
Strong answer cites: server-side cart GSI user_id, merge sum qty, delete guest
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 38

```
Q38: What happens when search index lags 2 minutes?
Strong answer cites: checkout validates inventory; display stale in_stock with caveat
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 39

```
Q39: Draw CloudFront behaviors for this system.
Strong answer cites: /static immutable, /api/public short TTL, /account no cache
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```


#### Interview follow-up question 40

```
Q40: How do you prevent inventory oversell at 500 orders/sec?
Strong answer cites: DynamoDB conditional update + reservation TTL + checkout queue
Weak answer to redirect: "SELECT COUNT" or "cache everything" or "single POST checkout"
```

---

## Concrete Examples


### Example 1: CloudFront Behaviors

```
Behavior 1: /static/*
  Origin: S3 shop-static-prod
  Cache policy: CachingOptimized
  Compress: Brotli

Behavior 2: /images/*
  Origin: S3 shop-images-prod
  Cache policy: custom max TTL 1 day

Behavior 3: /api/public/*
  Origin: ALB api-origin
  Cache policy: custom — cache GET/HEAD only, query strings in cache key
  Origin request policy: forward Accept-Language for i18n (careful: key cardinality)

Behavior 4: /api/* (default)
  Origin: ALB
  Cache: disabled
  Forward: all headers, cookies, query strings

Behavior 5: /account/*
  Origin: ALB
  Cache: disabled
  Response headers policy: Cache-Control private (enforced at origin)
```

### Example 2: Reserve Inventory (DynamoDB TransactWrite)

```python
def reserve(sku, qty, cart_id):
    shard = hash(cart_id) % NUM_SHARDS
    pk = f"SKU#{sku}#SHARD#{shard}"
    reservation_id = str(uuid4())
    expires = int(time.time()) + 900

    try:
        dynamodb.transact_write_items(TransactItems=[
            {'Update': {
                'TableName': 'inventory',
                'Key': {'pk': pk},
                'UpdateExpression': 'SET reserved = reserved + :q, version = version + :1',
                'ConditionExpression': 'on_hand - reserved - safety_stock >= :q',
                'ExpressionAttributeValues': {':q': qty, ':1': 1}
            }},
            {'Put': {
                'TableName': 'reservations',
                'Item': {'id': reservation_id, 'sku': sku, 'qty': qty,
                         'cart_id': cart_id, 'status': 'HELD', 'expires': expires},
                'ConditionExpression': 'attribute_not_exists(id)'
            }}
        ])
        return reservation_id
    except ClientError as e:
        if e.response['Error']['Code'] == 'TransactionCanceledException':
            raise OutOfStock()
        raise
```

### Example 3: Search Index Document

```json
{
  "sku": "WIDGET-42",
  "title": "Ultra Widget Pro",
  "brand": "WidgetCo",
  "category_path": ["Electronics", "Gadgets"],
  "price_cents": 4999,
  "currency": "USD",
  "in_stock": true,
  "rating_avg": 4.7,
  "updated_at": "2026-07-06T10:00:00Z"
}
```

### Example 4: Full Checkout Request Flow

```
1. Browser GET /api/public/pdp?sku=SHOE-99 (CloudFront hit, 12ms)
2. POST /api/v1/cart/items { sku: SHOE-99, qty: 1 } (origin 45ms)
3. User logs in → POST /api/v1/cart/merge (consistent read)
4. POST /api/v1/checkout/place-order
     Headers: Idempotency-Key: 7b9e-...
     Body: { cart_id, payment_method_id: pm_xxx }
5. API returns 202 { checkout_token, poll_url }  (flash mode)
   OR 200 { order_id } (normal mode)
6. Step Functions CheckoutSaga executes (see Payment System module)
7. Client polls GET /api/v1/checkout/status/{token} until terminal
8. Email SQS consumer sends confirmation (idempotent by order_id)
```


### Example 5: Promo stack

```
Scenario ECOM-EX-005: documents integration test case 5 for staging.
Validation: assert inventory sellable >= 0 after 500 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 1.
```


### Example 6: OpenSearch relevancy tuning

```
Scenario ECOM-EX-006: documents integration test case 6 for staging.
Validation: assert inventory sellable >= 0 after 600 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 2.
```


### Example 7: CloudFront signed URLs for premium content

```
Scenario ECOM-EX-007: documents integration test case 7 for staging.
Validation: assert inventory sellable >= 0 after 700 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 3.
```


### Example 8: Warehouse integration

```
Scenario ECOM-EX-008: documents integration test case 8 for staging.
Validation: assert inventory sellable >= 0 after 800 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 4.
```


### Example 9: Promo stack

```
Scenario ECOM-EX-009: documents integration test case 9 for staging.
Validation: assert inventory sellable >= 0 after 900 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 5.
```


### Example 10: OpenSearch relevancy tuning

```
Scenario ECOM-EX-010: documents integration test case 10 for staging.
Validation: assert inventory sellable >= 0 after 1000 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 1.
```


### Example 11: CloudFront signed URLs for premium content

```
Scenario ECOM-EX-011: documents integration test case 11 for staging.
Validation: assert inventory sellable >= 0 after 1100 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 2.
```


### Example 12: Warehouse integration

```
Scenario ECOM-EX-012: documents integration test case 12 for staging.
Validation: assert inventory sellable >= 0 after 1200 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 3.
```


### Example 13: Promo stack

```
Scenario ECOM-EX-013: documents integration test case 13 for staging.
Validation: assert inventory sellable >= 0 after 1300 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 4.
```


### Example 14: OpenSearch relevancy tuning

```
Scenario ECOM-EX-014: documents integration test case 14 for staging.
Validation: assert inventory sellable >= 0 after 1400 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 5.
```


### Example 15: CloudFront signed URLs for premium content

```
Scenario ECOM-EX-015: documents integration test case 15 for staging.
Validation: assert inventory sellable >= 0 after 1500 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 1.
```


### Example 16: Warehouse integration

```
Scenario ECOM-EX-016: documents integration test case 16 for staging.
Validation: assert inventory sellable >= 0 after 1600 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 2.
```


### Example 17: Promo stack

```
Scenario ECOM-EX-017: documents integration test case 17 for staging.
Validation: assert inventory sellable >= 0 after 1700 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 3.
```


### Example 18: OpenSearch relevancy tuning

```
Scenario ECOM-EX-018: documents integration test case 18 for staging.
Validation: assert inventory sellable >= 0 after 1800 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 4.
```


### Example 19: CloudFront signed URLs for premium content

```
Scenario ECOM-EX-019: documents integration test case 19 for staging.
Validation: assert inventory sellable >= 0 after 1900 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 5.
```


### Example 20: Warehouse integration

```
Scenario ECOM-EX-020: documents integration test case 20 for staging.
Validation: assert inventory sellable >= 0 after 2000 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 1.
```


### Example 21: Promo stack

```
Scenario ECOM-EX-021: documents integration test case 21 for staging.
Validation: assert inventory sellable >= 0 after 2100 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 2.
```


### Example 22: OpenSearch relevancy tuning

```
Scenario ECOM-EX-022: documents integration test case 22 for staging.
Validation: assert inventory sellable >= 0 after 2200 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 3.
```


### Example 23: CloudFront signed URLs for premium content

```
Scenario ECOM-EX-023: documents integration test case 23 for staging.
Validation: assert inventory sellable >= 0 after 2300 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 4.
```


### Example 24: Warehouse integration

```
Scenario ECOM-EX-024: documents integration test case 24 for staging.
Validation: assert inventory sellable >= 0 after 2400 concurrent reserves.
CDN: verify X-Cache-Status header expectation for behavior 5.
```

---

## Production Patterns


### Pattern: Queue-Based Checkout for Flash Sales

```
Add-to-cart: synchronous (fast fail if OOS)
Place-order: enqueue SQS checkout_queue, return 202 + checkout_token
Worker pool scales on queue depth; user polls /checkout/status/{token}

Prevents thundering herd on Payment API and Order DB at second zero.
```

### Pattern: Read-Your-Writes for Cart

```
DynamoDB consistent read on cart after login merge
Avoid user sees empty cart after adding item (eventual read bug)


### Production Pattern 1: CDC lag monitoring
Pattern 1 runbook ECOM-RB-001 covers inventory shard rebalance.


### Production Pattern 2: CDN cache key discipline
Pattern 2 runbook ECOM-RB-002 covers promo price rollout.


### Production Pattern 3: Cart abandonment emails
Pattern 3 runbook ECOM-RB-003 covers return workflow.


### Production Pattern 4: E-commerce ops pattern #4
Pattern 4 runbook ECOM-RB-004 covers fraud hold queue.


### Production Pattern 5: E-commerce ops pattern #5
Pattern 5 runbook ECOM-RB-005 covers search indexer lag.


### Production Pattern 6: E-commerce ops pattern #6
Pattern 6 runbook ECOM-RB-006 covers inventory shard rebalance.


### Production Pattern 7: E-commerce ops pattern #7
Pattern 7 runbook ECOM-RB-007 covers promo price rollout.


### Production Pattern 8: E-commerce ops pattern #8
Pattern 8 runbook ECOM-RB-008 covers return workflow.


### Production Pattern 9: E-commerce ops pattern #9
Pattern 9 runbook ECOM-RB-009 covers fraud hold queue.


### Production Pattern 10: E-commerce ops pattern #10
Pattern 10 runbook ECOM-RB-010 covers search indexer lag.


### Production Pattern 11: E-commerce ops pattern #11
Pattern 11 runbook ECOM-RB-011 covers inventory shard rebalance.


### Production Pattern 12: E-commerce ops pattern #12
Pattern 12 runbook ECOM-RB-012 covers promo price rollout.


### Production Pattern 13: E-commerce ops pattern #13
Pattern 13 runbook ECOM-RB-013 covers return workflow.


### Production Pattern 14: E-commerce ops pattern #14
Pattern 14 runbook ECOM-RB-014 covers fraud hold queue.


### Production Pattern 15: E-commerce ops pattern #15
Pattern 15 runbook ECOM-RB-015 covers search indexer lag.


### Production Pattern 16: E-commerce ops pattern #16
Pattern 16 runbook ECOM-RB-016 covers inventory shard rebalance.


### Production Pattern 17: E-commerce ops pattern #17
Pattern 17 runbook ECOM-RB-017 covers promo price rollout.


### Production Pattern 18: E-commerce ops pattern #18
Pattern 18 runbook ECOM-RB-018 covers return workflow.


### Production Pattern 19: E-commerce ops pattern #19
Pattern 19 runbook ECOM-RB-019 covers fraud hold queue.


### Production Pattern 20: E-commerce ops pattern #20
Pattern 20 runbook ECOM-RB-020 covers search indexer lag.


### Production Pattern 21: E-commerce ops pattern #21
Pattern 21 runbook ECOM-RB-021 covers inventory shard rebalance.


### Production Pattern 22: E-commerce ops pattern #22
Pattern 22 runbook ECOM-RB-022 covers promo price rollout.


### Production Pattern 23: E-commerce ops pattern #23
Pattern 23 runbook ECOM-RB-023 covers return workflow.


### Production Pattern 24: E-commerce ops pattern #24
Pattern 24 runbook ECOM-RB-024 covers fraud hold queue.


### Production Pattern 25: E-commerce ops pattern #25
Pattern 25 runbook ECOM-RB-025 covers search indexer lag.

#### Commerce Deep Dive 1: Cart

```
Topic: ECOM-DEEP-0001
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_1_sla_breach_total
Runbook: ECOM-DEEP-0001

Design note 1:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 2: Search

```
Topic: ECOM-DEEP-0002
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_2_sla_breach_total
Runbook: ECOM-DEEP-0002

Design note 2:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 3: CDN

```
Topic: ECOM-DEEP-0003
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_3_sla_breach_total
Runbook: ECOM-DEEP-0003

Design note 3:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 4: Checkout

```
Topic: ECOM-DEEP-0004
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_4_sla_breach_total
Runbook: ECOM-DEEP-0004

Design note 4:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 5: Inventory

```
Topic: ECOM-DEEP-0005
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_5_sla_breach_total
Runbook: ECOM-DEEP-0005

Design note 5:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 6: Cart

```
Topic: ECOM-DEEP-0006
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_6_sla_breach_total
Runbook: ECOM-DEEP-0006

Design note 6:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 7: Search

```
Topic: ECOM-DEEP-0007
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_7_sla_breach_total
Runbook: ECOM-DEEP-0007

Design note 7:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 8: CDN

```
Topic: ECOM-DEEP-0008
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_8_sla_breach_total
Runbook: ECOM-DEEP-0008

Design note 8:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 9: Checkout

```
Topic: ECOM-DEEP-0009
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_9_sla_breach_total
Runbook: ECOM-DEEP-0009

Design note 9:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 10: Inventory

```
Topic: ECOM-DEEP-0010
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_10_sla_breach_total
Runbook: ECOM-DEEP-0010

Design note 10:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 11: Cart

```
Topic: ECOM-DEEP-0011
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_11_sla_breach_total
Runbook: ECOM-DEEP-0011

Design note 11:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 12: Search

```
Topic: ECOM-DEEP-0012
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_12_sla_breach_total
Runbook: ECOM-DEEP-0012

Design note 12:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 13: CDN

```
Topic: ECOM-DEEP-0013
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_13_sla_breach_total
Runbook: ECOM-DEEP-0013

Design note 13:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 14: Checkout

```
Topic: ECOM-DEEP-0014
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_14_sla_breach_total
Runbook: ECOM-DEEP-0014

Design note 14:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 15: Inventory

```
Topic: ECOM-DEEP-0015
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_15_sla_breach_total
Runbook: ECOM-DEEP-0015

Design note 15:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 16: Cart

```
Topic: ECOM-DEEP-0016
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_16_sla_breach_total
Runbook: ECOM-DEEP-0016

Design note 16:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 17: Search

```
Topic: ECOM-DEEP-0017
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_17_sla_breach_total
Runbook: ECOM-DEEP-0017

Design note 17:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 18: CDN

```
Topic: ECOM-DEEP-0018
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_18_sla_breach_total
Runbook: ECOM-DEEP-0018

Design note 18:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 19: Checkout

```
Topic: ECOM-DEEP-0019
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_19_sla_breach_total
Runbook: ECOM-DEEP-0019

Design note 19:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 20: Inventory

```
Topic: ECOM-DEEP-0020
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_20_sla_breach_total
Runbook: ECOM-DEEP-0020

Design note 20:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 21: Cart

```
Topic: ECOM-DEEP-0021
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_21_sla_breach_total
Runbook: ECOM-DEEP-0021

Design note 21:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 22: Search

```
Topic: ECOM-DEEP-0022
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_22_sla_breach_total
Runbook: ECOM-DEEP-0022

Design note 22:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 23: CDN

```
Topic: ECOM-DEEP-0023
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_23_sla_breach_total
Runbook: ECOM-DEEP-0023

Design note 23:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 24: Checkout

```
Topic: ECOM-DEEP-0024
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_24_sla_breach_total
Runbook: ECOM-DEEP-0024

Design note 24:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 25: Inventory

```
Topic: ECOM-DEEP-0025
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_25_sla_breach_total
Runbook: ECOM-DEEP-0025

Design note 25:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 26: Cart

```
Topic: ECOM-DEEP-0026
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_26_sla_breach_total
Runbook: ECOM-DEEP-0026

Design note 26:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 27: Search

```
Topic: ECOM-DEEP-0027
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_27_sla_breach_total
Runbook: ECOM-DEEP-0027

Design note 27:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 28: CDN

```
Topic: ECOM-DEEP-0028
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_28_sla_breach_total
Runbook: ECOM-DEEP-0028

Design note 28:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 29: Checkout

```
Topic: ECOM-DEEP-0029
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_29_sla_breach_total
Runbook: ECOM-DEEP-0029

Design note 29:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 30: Inventory

```
Topic: ECOM-DEEP-0030
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_30_sla_breach_total
Runbook: ECOM-DEEP-0030

Design note 30:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 31: Cart

```
Topic: ECOM-DEEP-0031
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_31_sla_breach_total
Runbook: ECOM-DEEP-0031

Design note 31:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 32: Search

```
Topic: ECOM-DEEP-0032
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_32_sla_breach_total
Runbook: ECOM-DEEP-0032

Design note 32:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 33: CDN

```
Topic: ECOM-DEEP-0033
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_33_sla_breach_total
Runbook: ECOM-DEEP-0033

Design note 33:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 34: Checkout

```
Topic: ECOM-DEEP-0034
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_34_sla_breach_total
Runbook: ECOM-DEEP-0034

Design note 34:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 35: Inventory

```
Topic: ECOM-DEEP-0035
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_35_sla_breach_total
Runbook: ECOM-DEEP-0035

Design note 35:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 36: Cart

```
Topic: ECOM-DEEP-0036
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_36_sla_breach_total
Runbook: ECOM-DEEP-0036

Design note 36:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 37: Search

```
Topic: ECOM-DEEP-0037
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_37_sla_breach_total
Runbook: ECOM-DEEP-0037

Design note 37:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 38: CDN

```
Topic: ECOM-DEEP-0038
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_38_sla_breach_total
Runbook: ECOM-DEEP-0038

Design note 38:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 39: Checkout

```
Topic: ECOM-DEEP-0039
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_39_sla_breach_total
Runbook: ECOM-DEEP-0039

Design note 39:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 40: Inventory

```
Topic: ECOM-DEEP-0040
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_40_sla_breach_total
Runbook: ECOM-DEEP-0040

Design note 40:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 41: Cart

```
Topic: ECOM-DEEP-0041
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_41_sla_breach_total
Runbook: ECOM-DEEP-0041

Design note 41:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 42: Search

```
Topic: ECOM-DEEP-0042
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_42_sla_breach_total
Runbook: ECOM-DEEP-0042

Design note 42:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 43: CDN

```
Topic: ECOM-DEEP-0043
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_43_sla_breach_total
Runbook: ECOM-DEEP-0043

Design note 43:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 44: Checkout

```
Topic: ECOM-DEEP-0044
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_44_sla_breach_total
Runbook: ECOM-DEEP-0044

Design note 44:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 45: Inventory

```
Topic: ECOM-DEEP-0045
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_45_sla_breach_total
Runbook: ECOM-DEEP-0045

Design note 45:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 46: Cart

```
Topic: ECOM-DEEP-0046
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_46_sla_breach_total
Runbook: ECOM-DEEP-0046

Design note 46:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 47: Search

```
Topic: ECOM-DEEP-0047
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_47_sla_breach_total
Runbook: ECOM-DEEP-0047

Design note 47:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 48: CDN

```
Topic: ECOM-DEEP-0048
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_48_sla_breach_total
Runbook: ECOM-DEEP-0048

Design note 48:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 49: Checkout

```
Topic: ECOM-DEEP-0049
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_49_sla_breach_total
Runbook: ECOM-DEEP-0049

Design note 49:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 50: Inventory

```
Topic: ECOM-DEEP-0050
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_50_sla_breach_total
Runbook: ECOM-DEEP-0050

Design note 50:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 51: Cart

```
Topic: ECOM-DEEP-0051
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_51_sla_breach_total
Runbook: ECOM-DEEP-0051

Design note 51:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 52: Search

```
Topic: ECOM-DEEP-0052
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_52_sla_breach_total
Runbook: ECOM-DEEP-0052

Design note 52:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 53: CDN

```
Topic: ECOM-DEEP-0053
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_53_sla_breach_total
Runbook: ECOM-DEEP-0053

Design note 53:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 54: Checkout

```
Topic: ECOM-DEEP-0054
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_54_sla_breach_total
Runbook: ECOM-DEEP-0054

Design note 54:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 55: Inventory

```
Topic: ECOM-DEEP-0055
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_55_sla_breach_total
Runbook: ECOM-DEEP-0055

Design note 55:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 56: Cart

```
Topic: ECOM-DEEP-0056
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_56_sla_breach_total
Runbook: ECOM-DEEP-0056

Design note 56:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 57: Search

```
Topic: ECOM-DEEP-0057
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_57_sla_breach_total
Runbook: ECOM-DEEP-0057

Design note 57:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 58: CDN

```
Topic: ECOM-DEEP-0058
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_58_sla_breach_total
Runbook: ECOM-DEEP-0058

Design note 58:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 59: Checkout

```
Topic: ECOM-DEEP-0059
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_59_sla_breach_total
Runbook: ECOM-DEEP-0059

Design note 59:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 60: Inventory

```
Topic: ECOM-DEEP-0060
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_60_sla_breach_total
Runbook: ECOM-DEEP-0060

Design note 60:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 61: Cart

```
Topic: ECOM-DEEP-0061
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_61_sla_breach_total
Runbook: ECOM-DEEP-0061

Design note 61:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 62: Search

```
Topic: ECOM-DEEP-0062
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_62_sla_breach_total
Runbook: ECOM-DEEP-0062

Design note 62:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 63: CDN

```
Topic: ECOM-DEEP-0063
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_63_sla_breach_total
Runbook: ECOM-DEEP-0063

Design note 63:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 64: Checkout

```
Topic: ECOM-DEEP-0064
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_64_sla_breach_total
Runbook: ECOM-DEEP-0064

Design note 64:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 65: Inventory

```
Topic: ECOM-DEEP-0065
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_65_sla_breach_total
Runbook: ECOM-DEEP-0065

Design note 65:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 66: Cart

```
Topic: ECOM-DEEP-0066
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_66_sla_breach_total
Runbook: ECOM-DEEP-0066

Design note 66:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 67: Search

```
Topic: ECOM-DEEP-0067
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_67_sla_breach_total
Runbook: ECOM-DEEP-0067

Design note 67:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 68: CDN

```
Topic: ECOM-DEEP-0068
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_68_sla_breach_total
Runbook: ECOM-DEEP-0068

Design note 68:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 69: Checkout

```
Topic: ECOM-DEEP-0069
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_69_sla_breach_total
Runbook: ECOM-DEEP-0069

Design note 69:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 70: Inventory

```
Topic: ECOM-DEEP-0070
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_70_sla_breach_total
Runbook: ECOM-DEEP-0070

Design note 70:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 71: Cart

```
Topic: ECOM-DEEP-0071
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_71_sla_breach_total
Runbook: ECOM-DEEP-0071

Design note 71:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 72: Search

```
Topic: ECOM-DEEP-0072
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_72_sla_breach_total
Runbook: ECOM-DEEP-0072

Design note 72:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 73: CDN

```
Topic: ECOM-DEEP-0073
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_73_sla_breach_total
Runbook: ECOM-DEEP-0073

Design note 73:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 74: Checkout

```
Topic: ECOM-DEEP-0074
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_74_sla_breach_total
Runbook: ECOM-DEEP-0074

Design note 74:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 75: Inventory

```
Topic: ECOM-DEEP-0075
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_75_sla_breach_total
Runbook: ECOM-DEEP-0075

Design note 75:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 76: Cart

```
Topic: ECOM-DEEP-0076
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_76_sla_breach_total
Runbook: ECOM-DEEP-0076

Design note 76:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 77: Search

```
Topic: ECOM-DEEP-0077
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_77_sla_breach_total
Runbook: ECOM-DEEP-0077

Design note 77:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 78: CDN

```
Topic: ECOM-DEEP-0078
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_78_sla_breach_total
Runbook: ECOM-DEEP-0078

Design note 78:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 79: Checkout

```
Topic: ECOM-DEEP-0079
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_79_sla_breach_total
Runbook: ECOM-DEEP-0079

Design note 79:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 80: Inventory

```
Topic: ECOM-DEEP-0080
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_80_sla_breach_total
Runbook: ECOM-DEEP-0080

Design note 80:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 81: Cart

```
Topic: ECOM-DEEP-0081
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_81_sla_breach_total
Runbook: ECOM-DEEP-0081

Design note 81:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 82: Search

```
Topic: ECOM-DEEP-0082
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_82_sla_breach_total
Runbook: ECOM-DEEP-0082

Design note 82:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 83: CDN

```
Topic: ECOM-DEEP-0083
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_83_sla_breach_total
Runbook: ECOM-DEEP-0083

Design note 83:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 84: Checkout

```
Topic: ECOM-DEEP-0084
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_84_sla_breach_total
Runbook: ECOM-DEEP-0084

Design note 84:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 85: Inventory

```
Topic: ECOM-DEEP-0085
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_85_sla_breach_total
Runbook: ECOM-DEEP-0085

Design note 85:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 86: Cart

```
Topic: ECOM-DEEP-0086
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_86_sla_breach_total
Runbook: ECOM-DEEP-0086

Design note 86:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 87: Search

```
Topic: ECOM-DEEP-0087
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_87_sla_breach_total
Runbook: ECOM-DEEP-0087

Design note 87:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 88: CDN

```
Topic: ECOM-DEEP-0088
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_88_sla_breach_total
Runbook: ECOM-DEEP-0088

Design note 88:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 89: Checkout

```
Topic: ECOM-DEEP-0089
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_89_sla_breach_total
Runbook: ECOM-DEEP-0089

Design note 89:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 90: Inventory

```
Topic: ECOM-DEEP-0090
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_90_sla_breach_total
Runbook: ECOM-DEEP-0090

Design note 90:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 91: Cart

```
Topic: ECOM-DEEP-0091
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_91_sla_breach_total
Runbook: ECOM-DEEP-0091

Design note 91:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 92: Search

```
Topic: ECOM-DEEP-0092
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_92_sla_breach_total
Runbook: ECOM-DEEP-0092

Design note 92:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 93: CDN

```
Topic: ECOM-DEEP-0093
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_93_sla_breach_total
Runbook: ECOM-DEEP-0093

Design note 93:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 94: Checkout

```
Topic: ECOM-DEEP-0094
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_94_sla_breach_total
Runbook: ECOM-DEEP-0094

Design note 94:
  When WMS rejects fulfill,
  the orchestrator must compensate capture and notify customer.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 95: Inventory

```
Topic: ECOM-DEEP-0095
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_95_sla_breach_total
Runbook: ECOM-DEEP-0095

Design note 95:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 96: Cart

```
Topic: ECOM-DEEP-0096
Focus: guest cart TTL
AWS: DAX optional
Metric: ecom_deep_96_sla_breach_total
Runbook: ECOM-DEEP-0096

Design note 96:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 97: Search

```
Topic: ECOM-DEEP-0097
Focus: synonym mapping brand aliases
AWS: OpenSearch UltraWarm
Metric: ecom_deep_97_sla_breach_total
Runbook: ECOM-DEEP-0097

Design note 97:
  When carrier API times out,
  the orchestrator must retry with backoff then alternate carrier.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 98: CDN

```
Topic: ECOM-DEEP-0098
Focus: image CDN OAC
AWS: CloudFront Functions A/B
Metric: ecom_deep_98_sla_breach_total
Runbook: ECOM-DEEP-0098

Design note 98:
  When reservation expires,
  the orchestrator must release reservation via TTL stream.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 99: Checkout

```
Topic: ECOM-DEEP-0099
Focus: tax computation nexus
AWS: Step Functions Express vs Standard
Metric: ecom_deep_99_sla_breach_total
Runbook: ECOM-DEEP-0099

Design note 99:
  When user abandons cart,
  the orchestrator must retain cart 30d for recovery email.
  Cross-reference Week 6 saga compensation ordering.
```


#### Commerce Deep Dive 100: Inventory

```
Topic: ECOM-DEEP-0100
Focus: shard rebalance pre-flash
AWS: DynamoDB adaptive capacity
Metric: ecom_deep_100_sla_breach_total
Runbook: ECOM-DEEP-0100

Design note 100:
  When price changes mid-checkout,
  the orchestrator must return 422 PRICE_CHANGED to client.
  Cross-reference Week 6 saga compensation ordering.
```

---

## Failure Modes

Flash sale and CDN failure catalog:

**Oversell**: Orders confirmed, warehouse cannot fulfill | Cause: Reservation TTL expired before capture; race on commit | Fix: Extend TTL; commit reservation on auth not capture

**Stale search**: PDP checkout fails OOS | Cause: Indexer lag 4 min | Fix: in_stock flag; checkout validation; lag alert

**Cache poisoning**: User A sees User B account | Cause: public cache on /account | Fix: private no-store; CF behavior

**Cart split-brain**: Items disappear | Cause: Merge bug dual cart_id | Fix: Single writer; consistent read post-merge

**CDN stampede**: Origin meltdown post-purge | Cause: Full purge during deploy | Fix: Versioned URLs only; no purge prod

**Hot partition**: DynamoDB throttling flash SKU | Cause: Single partition key | Fix: Shard reservations


```
FAILURE #7: E-commerce cascade during peak
Trigger: search lag
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: fallback DB search
```


```
FAILURE #8: E-commerce cascade during peak
Trigger: inventory shard exhaustion
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: enable checkout queue
```


```
FAILURE #9: E-commerce cascade during peak
Trigger: CDN miss storm
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: stale-if-error
```


```
FAILURE #10: E-commerce cascade during peak
Trigger: search lag
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: fallback DB search
```


```
FAILURE #11: E-commerce cascade during peak
Trigger: inventory shard exhaustion
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: enable checkout queue
```


```
FAILURE #12: E-commerce cascade during peak
Trigger: CDN miss storm
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: stale-if-error
```


```
FAILURE #13: E-commerce cascade during peak
Trigger: search lag
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: fallback DB search
```


```
FAILURE #14: E-commerce cascade during peak
Trigger: inventory shard exhaustion
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: enable checkout queue
```


```
FAILURE #15: E-commerce cascade during peak
Trigger: CDN miss storm
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: stale-if-error
```


```
FAILURE #16: E-commerce cascade during peak
Trigger: search lag
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: fallback DB search
```


```
FAILURE #17: E-commerce cascade during peak
Trigger: inventory shard exhaustion
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: enable checkout queue
```


```
FAILURE #18: E-commerce cascade during peak
Trigger: CDN miss storm
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: stale-if-error
```


```
FAILURE #19: E-commerce cascade during peak
Trigger: search lag
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: fallback DB search
```


```
FAILURE #20: E-commerce cascade during peak
Trigger: inventory shard exhaustion
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: enable checkout queue
```


```
FAILURE #21: E-commerce cascade during peak
Trigger: CDN miss storm
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: stale-if-error
```


```
FAILURE #22: E-commerce cascade during peak
Trigger: search lag
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: fallback DB search
```


```
FAILURE #23: E-commerce cascade during peak
Trigger: inventory shard exhaustion
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: enable checkout queue
```


```
FAILURE #24: E-commerce cascade during peak
Trigger: CDN miss storm
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: stale-if-error
```


```
FAILURE #25: E-commerce cascade during peak
Trigger: search lag
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: fallback DB search
```


```
FAILURE #26: E-commerce cascade during peak
Trigger: inventory shard exhaustion
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: enable checkout queue
```


```
FAILURE #27: E-commerce cascade during peak
Trigger: CDN miss storm
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: stale-if-error
```


```
FAILURE #28: E-commerce cascade during peak
Trigger: search lag
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: fallback DB search
```


```
FAILURE #29: E-commerce cascade during peak
Trigger: inventory shard exhaustion
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: enable checkout queue
```


```
FAILURE #30: E-commerce cascade during peak
Trigger: CDN miss storm
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: stale-if-error
```


```
FAILURE #31: E-commerce cascade during peak
Trigger: search lag
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: fallback DB search
```


```
FAILURE #32: E-commerce cascade during peak
Trigger: inventory shard exhaustion
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: enable checkout queue
```


```
FAILURE #33: E-commerce cascade during peak
Trigger: CDN miss storm
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: stale-if-error
```


```
FAILURE #34: E-commerce cascade during peak
Trigger: search lag
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: fallback DB search
```


```
FAILURE #35: E-commerce cascade during peak
Trigger: inventory shard exhaustion
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: enable checkout queue
```


```
FAILURE #36: E-commerce cascade during peak
Trigger: CDN miss storm
Symptom: p99 latency 10× baseline; error budget burn
Mitigation: stale-if-error
```

---

## SRE Diagnostic Toolkit


```
METRICS:
  inventory_reserve_success_total / _failure_total{reason}
  inventory_oversell_total (MUST be 0)
  search_indexer_lag_seconds
  cart_merge_conflicts_total
  checkout_saga_duration_seconds
  cloudfront_origin_requests (miss rate)
  cloudfront_cache_hit_ratio (by behavior)

COMMANDS:
  aws cloudfront get-distribution-config --id E1234
  curl -sI https://shop.example.com/api/public/pdp?sku=WIDGET-42 | grep -i cache
  aws dynamodb describe-table --table-name inventory | jq .Table.TableStatus

LOG PATTERN (oversell near-miss):
  "reserve_failed" sku=WIDGET-42 sellable=0 requested=1 cart_id=...

---

## Decision Framework


```
┌──────────────────┬─────────────────────┬────────────────────┐
│ Topic            │ Option A            │ Option B           │
├──────────────────┼─────────────────────┼────────────────────┤
│ Cart store       │ DynamoDB            │ Redis (faster,     │
│                  │ durable, TTL        │ less durable)      │
├──────────────────┼─────────────────────┼────────────────────┤
│ Inventory        │ DynamoDB conditional│ Postgres row lock  │
│                  │ flash-scale         │ simpler low scale  │
├──────────────────┼─────────────────────┼────────────────────┤
│ Search           │ OpenSearch          │ Postgres FTS       │
│                  │ faceted, scale      │ <100K SKUs OK      │
├──────────────────┼─────────────────────┼────────────────────┤
│ Flash checkout   │ Sync place-order    │ Queued checkout    │
│                  │ <100 orders/sec     │ 500+ orders/sec    │
├──────────────────┼─────────────────────┼────────────────────┤
│ PDP price        │ API short TTL CDN   │ Client fetch live  │
│                  │ 30s s-maxage        │ price (no CDN)     │
└──────────────────┴─────────────────────┴────────────────────┘

---

## Incident Scenario


```
INCIDENT: Flash Sale Friday 12:00 ET
SKU: LIMITED-SNEAKER-2026 (qty 5000, demand 200K)

12:00:00 — Traffic 80K RPS CDN (images OK), API 12K RPS
12:00:15 — inventory Reserve throttling on SHARD#3 (hot)
12:00:30 — Search still in_stock=true (indexer lag 90s)
12:00:45 — 340 checkout failures/min "OOS" after search click
12:01:00 — Social media "site broken"
12:01:30 — Origin CPU 94% (PLP API cache miss storm — deploy changed query param)

METRICS:
  inventory_throttled_requests: 18K/sec
  search_indexer_lag: 90s
  cloudfront_api_miss_rate: 78% (normally 8%)
  checkout_queue_depth: N/A (sync checkout — no queue)

YOUR ROLE: Join at 12:03. Stop oversell. Restore checkout fairness.
```

Q1: Immediate mitigations (3 actions, exact configs)
Q2: Why search lag causes UX "bait and switch" — trace one user journey
Q3: Fairness: how to prevent bots buying 500 pairs
Q4: CDN: why miss rate spiked — tie to Week 1 cache key rules
Q5: 48-hour permanent fixes

---

## Expert Analysis


### Q1: Immediate

```
1. Enable checkout queue (feature flag) — return 202, scale workers 20→200
2. Emergency inventory: cap 1 pair per user_id (DynamoDB condition on cart)
3. CloudFront: enable stale-if-error on /api/public/plp (origin failing)
4. Search: manual indexer flip in_stock=false for LIMITED-SNEAKER-2026
   (emergency override endpoint — documented break-glass)
```

### Q2: User Journey

```
User sees in_stock=true (90s stale index) → PDP CDN cached OK →
Add to cart OK (reservation competes) → Checkout fails reserve or OOS →
Anger. Fix: checkout always hits inventory truth; search lag display only.
```

### Q3: Bot fairness

```
WAF rate limit: 10 add-to-cart/min/IP
Require login 5 min before sale for high-heat SKU
Device fingerprint + CAPTCHA on checkout
Reservation tied to verified user_id max qty 1
```

### Q4: CDN miss spike

```
Deploy added ?v=2.14 to PLP API URLs → new cache key → 100% miss
Week 1 lesson: version in path not arbitrary query params for CDN keys
Rollback query param; warm cache via synthetic crawler pre-sale
```

### Q5: 48-hour fixes

```
- Mandatory checkout queue for heat-check SKUs
- Inventory shard auto-scaling + pre-warm
- Search: priority lane for in_stock updates on flash SKUs
- CDN: documented cache key policy review in deploy checklist
- Game day: flash sale rehearsal quarterly
```

### Q6: Extended analysis — inventory shard math

```
Question: Drill-down 6 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q6_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q06

Quantified example for Q6:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q7: Extended analysis — CDN cache key audit

```
Question: Drill-down 7 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q7_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q07

Quantified example for Q7:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q8: Extended analysis — search freshness SLO

```
Question: Drill-down 8 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q8_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q08

Quantified example for Q8:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q9: Extended analysis — inventory shard math

```
Question: Drill-down 9 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q9_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q09

Quantified example for Q9:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q10: Extended analysis — CDN cache key audit

```
Question: Drill-down 10 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q10_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q10

Quantified example for Q10:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q11: Extended analysis — search freshness SLO

```
Question: Drill-down 11 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q11_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q11

Quantified example for Q11:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q12: Extended analysis — inventory shard math

```
Question: Drill-down 12 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q12_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q12

Quantified example for Q12:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q13: Extended analysis — CDN cache key audit

```
Question: Drill-down 13 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q13_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q13

Quantified example for Q13:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q14: Extended analysis — search freshness SLO

```
Question: Drill-down 14 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q14_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q14

Quantified example for Q14:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q15: Extended analysis — inventory shard math

```
Question: Drill-down 15 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q15_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q15

Quantified example for Q15:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q16: Extended analysis — CDN cache key audit

```
Question: Drill-down 16 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q16_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q16

Quantified example for Q16:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q17: Extended analysis — search freshness SLO

```
Question: Drill-down 17 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q17_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q17

Quantified example for Q17:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q18: Extended analysis — inventory shard math

```
Question: Drill-down 18 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q18_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q18

Quantified example for Q18:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q19: Extended analysis — CDN cache key audit

```
Question: Drill-down 19 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q19_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q19

Quantified example for Q19:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```


### Q20: Extended analysis — search freshness SLO

```
Question: Drill-down 20 for principal-level review.

Worked answer:
  Step 1: Identify authoritative store (catalog RDS / inventory DynamoDB)
  Step 2: Measure lag or contention (CloudWatch metric ecom_q20_signal)
  Step 3: Mitigate without oversell (never bypass reservation)
  Step 4: Communicate externally if checkout degraded > 5 min
  Step 5: Post-incident: add canary + runbook ECOM-Q20

Quantified example for Q20:
  At 500 orders/sec and 16 shards, per-shard load = 31.25 reserves/sec
  DynamoDB per-partition write limit ~1000/sec — OK if keys sharded
  Without sharding: 500/sec on one key → throttling in < 1 sec
```

---

## Key Takeaways

```
╔══════════════════════════════════════════════════════════════╗
║ IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:               ║
║                                                              ║
║ 1. CATALOG DB IS TRUTH; search and CDN are projections.      ║
║ 2. RESERVE BEFORE CHARGE; TTL aligned with auth hold.        ║
║ 3. CDN: versioned static assets; never public-cache /account.║
║ 4. CHECKOUT IS A SAGA with idempotent steps.                 ║
║ 5. FLASH SALES: shard inventory, queue checkout, rate limit. ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading


```
REQUIRED:
  1. Week 1 — CDN Fundamentals.md (this repo)
     → Versioned URLs, cache poisoning incident, origin offload math

  2. Week 6 — Saga Pattern.md
     → Checkout orchestration and compensation

  3. Designing Data-Intensive Applications Ch. 3 (storage), Ch. 12 (data systems)

  4. Amazon Builder Library — Caching challenges and strategies

  5. OpenSearch — Near real-time search and refresh interval

OPTIONAL:
  6. Etsy inventory management engineering posts
  7. Shopify flash sale architecture talks
```
