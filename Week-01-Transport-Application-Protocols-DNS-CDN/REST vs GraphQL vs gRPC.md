# Topic 3: REST vs GraphQL vs gRPC

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Diagnose whether a production issue is at the           ║
║      API layer vs transport layer vs database layer          ║
║      from metrics alone                                      ║
║                                                              ║
║   2. Identify the specific API anti-pattern causing          ║
║      a performance incident (N+1, over-fetching,             ║
║      serialization bottleneck, connection reuse)             ║
║                                                              ║
║   3. Choose REST vs GraphQL vs gRPC for a given              ║
║      component and DEFEND the choice with trade-offs         ║
║                                                              ║
║   4. Debug API-layer issues using specific tools             ║
║      and commands                                            ║
║                                                              ║
║   5. Set up monitoring and alerts that catch API             ║
║      problems BEFORE they become P1 incidents                ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

### Foundation

> Progress through Foundation → Staff → Principal stretch. Staff is the mastery gate.


```
╔═════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "REST = any HTTP API that returns JSON"              ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. REST is an architectural style with constraints:               ║
║   statelessness, cacheable responses, uniform interface, and            ║
║   resource-oriented URIs. Most "REST APIs" are RPC-over-HTTP            ║
║   with verbs in URLs — that is fine, but it is not REST.                ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "GraphQL eliminates over-fetching automatically"     ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Clients choose fields, but resolvers can still N+1             ║
║   the database. Without DataLoader/batching, GraphQL can be             ║
║   SLOWER than REST. The query flexibility shifts complexity             ║
║   to the server — it does not remove it.                                ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "gRPC is always faster than REST"                    ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Protobuf + HTTP/2 helps, but browser support is limited,       ║
║   debugging is harder, and L7 load balancers often terminate            ║
║   HTTP/2 at the edge. gRPC wins service-to-service; REST wins           ║
║   public APIs and human debuggability.                                  ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Pick one API style for the entire company"          ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Mature systems use REST at the edge, gRPC between              ║
║   services, and GraphQL for specific aggregation layers.                ║
║   The choice is per boundary: client type, latency budget, and          ║
║   who owns the schema evolution.                                        ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "REST can't do streaming or real-time"               ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. SSE, long polling, and chunked transfer over HTTP/2            ║
║   are valid REST patterns. gRPC streaming is cleaner for                ║
║   bidirectional flows, but "REST = request/response only" is            ║
║   a false constraint.                                                   ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Versioning in the URL (/v2/) is RESTful"            ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. URL versioning breaks HATEOAS and cache keys. Content-         ║
║   negotiation (Accept header) and additive schema changes are           ║
║   closer to REST principles — though pragmatic URL versioning           ║
║   is common because it is simple.                                       ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## REST: Representational State Transfer

### What REST Actually Is (Most People Get This Wrong)

REST is NOT "any API that uses HTTP and returns JSON." REST is an **architectural style** defined by Roy Fielding in his 2000 PhD dissertation. It has specific constraints:

```
REST CONSTRAINTS:

1. CLIENT-SERVER
   → Separation of concerns
   → Client handles UI, server handles data/logic
   → They evolve independently

2. STATELESS
   → Each request contains ALL information needed
   → Server stores NO client session state between requests
   → Any server can handle any request (scalability!)

3. CACHEABLE
   → Responses must declare if they're cacheable
   → Reduces unnecessary server calls

4. UNIFORM INTERFACE (the key one)
   → Resources identified by URIs
   → Resources manipulated through representations (JSON, XML)
   → Self-descriptive messages (Content-Type, etc.)
   → HATEOAS (Hypermedia As The Engine Of Application State)
     → Responses include links to related actions
     → Almost nobody implements this in practice

5. LAYERED SYSTEM
   → Client can't tell if it's talking to the
     actual server or a proxy/cache/load balancer

6. CODE ON DEMAND (optional)
   → Server can send executable code to client (JavaScript)
```

### How REST Works In Practice

```
RESOURCES are the core concept.
Everything is a resource with a URI:

  /users              → Collection of users
  /users/123          → Specific user
  /users/123/orders   → Orders belonging to user 123
  /orders/456         → Specific order

HTTP METHODS map to CRUD operations:

  GET    /users/123       → READ user 123
  POST   /users           → CREATE a new user
  PUT    /users/123       → REPLACE user 123 entirely
  PATCH  /users/123       → PARTIALLY UPDATE user 123
  DELETE /users/123       → DELETE user 123

HTTP STATUS CODES indicate results:

  200 OK                  → Success
  201 Created             → Resource created (POST)
  204 No Content          → Success, nothing to return (DELETE)
  400 Bad Request         → Client sent invalid data
  401 Unauthorized        → Not authenticated
  403 Forbidden           → Authenticated but not allowed
  404 Not Found           → Resource doesn't exist
  409 Conflict            → Conflict (e.g., duplicate)
  429 Too Many Requests   → Rate limited
  500 Internal Server Error → Server broke
  502 Bad Gateway         → Upstream server broke
  503 Service Unavailable → Server overloaded/maintenance
```

### REST Request/Response Example

```
REQUEST:
  GET /api/v1/users/123 HTTP/1.1
  Host: api.example.com
  Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
  Accept: application/json

RESPONSE:
  HTTP/1.1 200 OK
  Content-Type: application/json
  Cache-Control: max-age=300
  ETag: "a1b2c3d4"

  {
    "id": 123,
    "name": "Alice",
    "email": "alice@example.com",
    "created_at": "2024-01-15T10:30:00Z",
    "links": {
      "orders": "/api/v1/users/123/orders",
      "profile": "/api/v1/users/123/profile"
    }
  }
```

### REST's Strengths

```
1. SIMPLICITY
   → Any developer understands GET /users/123
   → No special tooling needed
   → curl, Postman, browser — all work out of the box

2. CACHING
   → HTTP caching works natively
   → CDNs can cache GET responses
   → ETags for conditional requests
   → Huge for read-heavy workloads

3. UNIVERSAL
   → Every language, framework, platform supports HTTP
   → No special client libraries needed
   → Great for public APIs (Stripe, Twilio, GitHub)

4. STATELESS SCALABILITY
   → Any server can handle any request
   → Load balancer doesn't need session affinity
   → Easy horizontal scaling

5. DISCOVERABILITY
   → Clear URL structure reveals API shape
   → Self-documenting with OpenAPI/Swagger
```

### REST's Problems

```
PROBLEM 1: OVER-FETCHING

  Client needs just a user's name for a dropdown.

  GET /users/123
  Returns:
  {
    "id": 123,
    "name": "Alice",           ← Need this
    "email": "alice@...",      ← Don't need
    "address": {...},          ← Don't need
    "preferences": {...},      ← Don't need
    "created_at": "...",       ← Don't need
    "last_login": "...",       ← Don't need
    "avatar_url": "...",       ← Don't need
    "billing_info": {...}      ← Don't need
  }

  You asked for a sip of water, REST gave you the
  entire ocean. Wasted bandwidth, especially on mobile.

PROBLEM 2: UNDER-FETCHING (the N+1 problem)

  Client needs: User name + their 5 most recent orders
                + each order's product details

  Request 1: GET /users/123
  Request 2: GET /users/123/orders?limit=5
  Request 3: GET /products/789  (for order 1)
  Request 4: GET /products/101  (for order 2)
  Request 5: GET /products/202  (for order 3)
  Request 6: GET /products/303  (for order 4)
  Request 7: GET /products/404  (for order 5)

  7 HTTP round trips to get data for ONE page view.
  Each round trip = network latency.
  On mobile (100ms RTT) = 700ms minimum, just for fetching.

PROBLEM 3: VERSIONING PAIN

  You need to add a field or change a response format.

  /api/v1/users/123  → Old format
  /api/v2/users/123  → New format

  Now you maintain two versions.
  For years. Because clients don't upgrade.

  Or you use header-based versioning:
  Accept: application/vnd.api.v2+json

  Still two code paths to maintain.

PROBLEM 4: NO REAL TYPE SYSTEM

  REST has no built-in schema enforcement.
  You HOPE the server returns what you expect.
  Documentation can drift from implementation.
  OpenAPI/Swagger helps but is opt-in and often stale.
```

---

## GraphQL: The Query Language for APIs

Created by Facebook in 2012 (open-sourced 2015) to solve exactly the over-fetching and under-fetching problems of REST for their mobile app.

### The Core Idea

```
Instead of the SERVER deciding what data to return
(REST), the CLIENT specifies exactly what it needs.

REST approach:
  GET /users/123        → Server decides the shape

GraphQL approach:
  POST /graphql
  {
    query {
      user(id: 123) {
        name             ← Client picks exactly these fields
        email            ← Nothing more, nothing less
      }
    }
  }
```

### How GraphQL Works

```
THREE COMPONENTS:

1. SCHEMA (defined on the server)

   type User {
     id: ID!
     name: String!
     email: String!
     orders: [Order!]!
     avatar: String
   }

   type Order {
     id: ID!
     total: Float!
     status: OrderStatus!
     products: [Product!]!
     createdAt: DateTime!
   }

   type Product {
     id: ID!
     name: String!
     price: Float!
     imageUrl: String
   }

   type Query {
     user(id: ID!): User
     users(limit: Int, offset: Int): [User!]!
     order(id: ID!): Order
   }

   type Mutation {
     createUser(input: CreateUserInput!): User!
     updateUser(id: ID!, input: UpdateUserInput!): User!
     deleteUser(id: ID!): Boolean!
   }

2. QUERY (sent by the client)

   # Remember the 7-request REST problem?
   # GraphQL does it in ONE request:

   query GetUserWithOrders {
     user(id: 123) {
       name
       orders(limit: 5) {
         id
         total
         status
         products {
           name
           price
         }
       }
     }
   }

3. RESPONSE (exactly matches query shape)

   {
     "data": {
       "user": {
         "name": "Alice",
         "orders": [
           {
             "id": "ord-1",
             "total": 59.99,
             "status": "DELIVERED",
             "products": [
               {"name": "Keyboard", "price": 49.99},
               {"name": "Mouse pad", "price": 10.00}
             ]
           },
           // ... 4 more orders
         ]
       }
     }
   }

   ONE request. Exact data needed. No over-fetching.
   No under-fetching. No N+1 round trips.
```

### GraphQL Mutations (Writes)

```
mutation CreateOrder {
  createOrder(input: {
    userId: 123,
    products: [
      {productId: 789, quantity: 2},
      {productId: 101, quantity: 1}
    ]
  }) {
    id
    total
    status
    createdAt
  }
}

Response:
{
  "data": {
    "createOrder": {
      "id": "ord-999",
      "total": 109.97,
      "status": "PENDING",
      "createdAt": "2024-01-15T10:30:00Z"
    }
  }
}
```

### GraphQL Subscriptions (Real-Time)

```
subscription OnOrderStatusChanged {
  orderStatusChanged(userId: 123) {
    orderId
    newStatus
    updatedAt
  }
}

Uses WebSockets under the hood.
Server pushes updates when order status changes.
```

### GraphQL's Strengths

```
1. NO OVER-FETCHING / UNDER-FETCHING
   → Client gets exactly what it asks for
   → Critical for mobile (bandwidth-constrained)
   → Facebook's main motivation for creating it

2. ONE ENDPOINT
   → POST /graphql handles everything
   → No URL explosion (/v2/users/123/orders/...)
   → Simpler routing

3. STRONG TYPE SYSTEM
   → Schema defines exact types
   → Auto-generated documentation
   → Client code generation (TypeScript types, Swift, etc.)
   → Schema IS the documentation (always accurate)

4. VERSIONLESS
   → Add new fields without breaking existing clients
   → Clients only query fields they know about
   → Deprecate old fields with @deprecated directive
   → No /v1 /v2 headaches

5. INTROSPECTION
   → Client can ask the server "what queries do you support?"
   → Auto-generates documentation (GraphiQL, Apollo Studio)
   → Enables powerful dev tooling

6. SOLVES THE AGGREGATION PROBLEM
   → In microservices: one GraphQL gateway can federate
     across multiple backend services
   → Client sees ONE unified API
   → Apollo Federation, Schema Stitching
```

### GraphQL's Problems (And They're Serious)

```
PROBLEM 1: CACHING IS HARD

  REST: GET /users/123 → URL is the cache key
        CDN, browser, proxy all cache based on URL
        Simple. Works everywhere.

  GraphQL: POST /graphql → EVERY request goes to same URL
           Body contains different queries
           CDNs can't cache POST requests by default
           Need specialized GraphQL caching:
           → Persisted queries (hash the query, use as cache key)
           → Response-level caching in the GraphQL server
           → Apollo Client / Relay cache on the client
           Much more complex than REST caching.

PROBLEM 2: N+1 QUERY PROBLEM (server-side)

  Query:
    users(limit: 50) {
      name
      orders {        ← For EACH user, fetch orders
        products {    ← For EACH order, fetch products
          name
        }
      }
    }

  Naive implementation:
    1 query to get 50 users
    50 queries to get each user's orders
    200 queries to get each order's products
    = 251 database queries for ONE GraphQL query!

  Solution: DataLoader pattern (batching)
    → Collect all user IDs, batch into one query
    → Collect all order IDs, batch into one query
    → 3 total database queries instead of 251

  But you MUST implement DataLoader. It's not automatic.
  Forgetting it = production database meltdown.

PROBLEM 3: QUERY COMPLEXITY ATTACKS

  Malicious client can send:

    query Evil {
      users(limit: 1000) {
        friends(limit: 1000) {
          friends(limit: 1000) {
            friends(limit: 1000) {
              name
            }
          }
        }
      }
    }

  This is 1000^4 = 1 TRILLION potential records.
  Will destroy your database and crash your server.

  Defenses:
  → Query depth limiting (max depth = 5)
  → Query complexity scoring (assign cost to each field)
  → Rate limiting per client
  → Persisted queries (only allow pre-approved queries)
  → Timeout per query

PROBLEM 4: FILE UPLOADS ARE AWKWARD

  GraphQL is designed for structured data.
  File uploads don't fit the query/mutation model well.
  Solutions exist (multipart form spec) but are clunky.
  Most teams use REST endpoints for file uploads
  alongside GraphQL for everything else.

PROBLEM 5: ERROR HANDLING IS WEIRD

  REST: HTTP status code tells you what happened
    404 = not found, 400 = bad request, 500 = server error

  GraphQL: ALWAYS returns 200 OK
    Even if the query failed!
    Errors are in the response body:
    {
      "data": null,
      "errors": [{
        "message": "User not found",
        "path": ["user"],
        "extensions": {"code": "NOT_FOUND"}
      }]
    }

    This confuses monitoring tools that check HTTP status.
    Your error rate dashboards may show 0% errors while
    GraphQL is returning errors in every response body.

    SRE IMPACT: You need GraphQL-aware monitoring.
```

---

## gRPC: Google Remote Procedure Call

Built by Google. Open-sourced in 2015. Used internally at Google for virtually all service-to-service communication. Handles **billions** of calls per second across Google's infrastructure.

### The Core Idea

```
REST: "Here's a resource, do CRUD on it"
GraphQL: "Here's a query, give me exactly this data"
gRPC: "Call this FUNCTION on that remote server"

gRPC makes calling a function on another machine
feel like calling a local function:

  // This looks like a local function call
  response = userService.GetUser(userId=123)

  // But it actually:
  // 1. Serializes the request to binary (Protobuf)
  // 2. Sends it over HTTP/2 to another machine
  // 3. Deserializes the response from binary
  // 4. Returns it as a native object
```

### Protocol Buffers (Protobuf): gRPC's Secret Weapon

```
gRPC uses Protocol Buffers for serialization.
This is the single biggest performance advantage.

STEP 1: Define your service in a .proto file

  syntax = "proto3";

  service UserService {
    rpc GetUser (GetUserRequest) returns (User);
    rpc CreateUser (CreateUserRequest) returns (User);
    rpc ListUsers (ListUsersRequest) returns (stream User);
    rpc UpdateUser (UpdateUserRequest) returns (User);
  }

  message GetUserRequest {
    int64 user_id = 1;
  }

  message User {
    int64 id = 1;
    string name = 2;
    string email = 3;
    repeated Order orders = 4;
  }

  message Order {
    int64 id = 1;
    double total = 2;
    string status = 3;
  }

STEP 2: Generate client and server code automatically

  protoc --go_out=. --go-grpc_out=. user.proto

  This generates:
  → Server interface (you implement the logic)
  → Client stub (ready-to-use client)
  → All serialization/deserialization code
  → Type-safe in your language (Go, Java, Python, etc.)

STEP 3: Implement and call

  // Server (Go)
  func (s *server) GetUser(ctx context.Context,
    req *pb.GetUserRequest) (*pb.User, error) {
    user := db.FindUser(req.UserId)
    return &pb.User{Id: user.ID, Name: user.Name}, nil
  }

  // Client (Python — different language!)
  stub = UserServiceStub(channel)
  response = stub.GetUser(GetUserRequest(user_id=123))
  print(response.name)  # Type-safe, autocomplete works
```

### Protobuf vs JSON: Why Binary Matters

```
JSON representation of a user:
{
  "id": 123,
  "name": "Alice",
  "email": "alice@example.com",
  "active": true
}
= ~70 bytes (text, human-readable)

Protobuf representation of the same user:
08 7B 12 05 41 6C 69 63 65 1A 11 61 6C 69 63 65
40 65 78 61 6D 70 6C 65 2E 63 6F 6D 20 01
= ~35 bytes (binary, NOT human-readable)

50% smaller! At billions of requests, this matters:

  JSON:     70 bytes × 1 billion requests = 70 GB
  Protobuf: 35 bytes × 1 billion requests = 35 GB

  Savings: 35 GB of network bandwidth

  Plus: Protobuf serialization/deserialization is
  6-10x FASTER than JSON parsing.

  At Google's scale (billions of RPCs/day), this saves
  enormous CPU and bandwidth.
```

### gRPC's Four Communication Patterns

```
1. UNARY (simple request/response — like REST)

   Client ──Request──► Server
   Client ◄──Response── Server

   rpc GetUser (GetUserRequest) returns (User);

2. SERVER STREAMING (server sends many responses)

   Client ──Request──────────────► Server
   Client ◄──Response 1─────────── Server
   Client ◄──Response 2─────────── Server
   Client ◄──Response 3─────────── Server
   Client ◄──Response N─────────── Server

   rpc ListUsers (ListUsersRequest) returns (stream User);

   Use case: Downloading large datasets, real-time feeds

3. CLIENT STREAMING (client sends many requests)

   Client ──Request 1──────────► Server
   Client ──Request 2──────────► Server
   Client ──Request N──────────► Server
   Client ◄──Response──────────── Server

   rpc UploadLogs (stream LogEntry) returns (UploadStatus);

   Use case: File uploads, telemetry data, log shipping

4. BIDIRECTIONAL STREAMING (both sides stream)

   Client ──Request 1──► Server
   Client ◄──Response 1── Server
   Client ──Request 2──► Server
   Client ──Request 3──► Server
   Client ◄──Response 2── Server
   Client ◄──Response 3── Server

   rpc Chat (stream ChatMessage) returns (stream ChatMessage);

   Use case: Chat, gaming, real-time collaboration
```

### gRPC's Strengths

```
1. PERFORMANCE
   → Binary serialization (Protobuf): 50% smaller, 10x faster
   → HTTP/2: multiplexing, header compression
   → Single long-lived connection per client-server pair
   → At scale: massive CPU and bandwidth savings

2. STRONG CONTRACT
   → .proto file IS the API contract
   → Both sides must agree on the schema
   → Breaking changes are caught at compile time
   → No "the API changed and nobody told us" surprises

3. CODE GENERATION
   → One .proto file → clients in 10+ languages
   → Go, Java, Python, C++, Rust, C#, Node, Dart...
   → No hand-writing HTTP clients
   → No deserialization bugs

4. STREAMING
   → First-class support for all 4 patterns
   → REST: Request/response only (need WebSockets for streaming)
   → GraphQL: Subscriptions exist but are bolted on
   → gRPC: Streaming is native and efficient

5. DEADLINES & CANCELLATION
   → gRPC has built-in deadline propagation
   → Client: "I need a response within 500ms"
   → If the server chain takes too long,
     ALL servers in the chain abort work
   → Prevents wasted work in microservice chains
   → REST has no equivalent (timeout is per-hop,
     not propagated)

6. INTERCEPTORS (middleware)
   → Add authentication, logging, tracing, metrics
     at the transport level
   → Similar to HTTP middleware but more structured
```

### gRPC's Problems

```
PROBLEM 1: NOT BROWSER-FRIENDLY

  Browsers cannot make gRPC calls directly.
  Why?
  → Browsers don't expose raw HTTP/2 frames
    to JavaScript
  → gRPC uses HTTP/2 trailers (browsers don't
    support well)
  → Protobuf is binary (can't inspect in DevTools)

  Workarounds:
  → gRPC-Web: A proxy (like Envoy) translates
    between gRPC-Web and gRPC
  → Use REST/GraphQL for browser clients,
    gRPC for service-to-service
  → This is the most common pattern

PROBLEM 2: NOT HUMAN-READABLE

  REST: curl https://api.com/users/123 → readable JSON
  gRPC: Binary blobs. Need special tools.

  → grpcurl (command-line tool, like curl for gRPC)
  → Postman now supports gRPC
  → But debugging is harder than REST
  → Can't just read a packet capture

PROBLEM 3: NO NATIVE CACHING

  → REST uses HTTP caching (CDN, browser, proxy)
  → gRPC uses POST for everything (HTTP/2 POST)
  → POST requests are not cached by default
  → Need application-level caching

PROBLEM 4: SCHEMA COUPLING

  → Both client and server must have the same .proto
  → If server updates .proto without telling client
    → Old clients may break
  → Need careful versioning:
    → Never change field numbers
    → Only add new fields (backward compatible)
    → Use 'reserved' for removed fields

PROBLEM 5: LOAD BALANCING COMPLEXITY

  → gRPC uses long-lived HTTP/2 connections
  → Traditional L4 load balancers distribute TCP
    connections, not individual requests
  → If client opens ONE connection to L4 LB, ALL
    requests go to the SAME backend server
  → Need L7 load balancing (understands HTTP/2 streams)
  → Or client-side load balancing (client knows
    all server addresses)
```

---

## When to Use What: The Decision Framework

```
╔══════════════════════════════════════════════════════════════╗
║                     DECISION MATRIX                          ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   USE REST WHEN:                                             ║
║   ✓ Public-facing API (third-party developers)               ║
║   ✓ Simple CRUD operations                                   ║
║   ✓ Caching is critical (CDN, browser cache)                 ║
║   ✓ Universal compatibility needed                           ║
║   ✓ Team simplicity > performance                            ║
║   Examples: Stripe API, GitHub API, Twilio API               ║
║                                                              ║
║   USE GRAPHQL WHEN:                                          ║
║   ✓ Complex data relationships (social graphs, e-commerce)   ║
║   ✓ Multiple client types with different data needs          ║
║     (mobile needs less data than web)                        ║
║   ✓ Rapid frontend iteration (don't want to change API       ║
║     every time UI changes)                                   ║
║   ✓ Aggregating multiple microservices into one API          ║
║   Examples: Facebook, GitHub (v4), Shopify, Airbnb           ║
║                                                              ║
║   USE gRPC WHEN:                                             ║
║   ✓ Service-to-service (internal microservice communication) ║
║   ✓ High performance / low latency critical                  ║
║   ✓ Streaming needed (real-time, large data transfers)       ║
║   ✓ Polyglot environment (services in different languages)   ║
║   ✓ Strict contracts between teams                           ║
║   Examples: Google (all internal), Netflix (inter-service),  ║
║            Uber, Dropbox, Square                             ║
║                                                              ║
║   COMMON PATTERN IN PRACTICE:                                ║
║                                                              ║
║   ╭─────────╮     ╭──────────╮     ╭──────────╮              ║
║   │ Browser │────►│ GraphQL  │────►│ Service  │              ║
║   │ Mobile  │REST │ Gateway  │gRPC │ A, B, C  │              ║
║   ╰─────────╯ GQL ╰──────────╯     ╰──────────╯              ║
║                                                              ║
║   External clients: REST or GraphQL                          ║
║   Internal services: gRPC                                    ║
║   This gives you the best of all worlds.                     ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Performance Comparison

```
Benchmark (approximate, varies by payload):

                    │ Serialization │ Message Size │ Latency
────────────────────┼───────────────┼──────────────┼──────────
REST (JSON/HTTP1.1) │ Slow          │ Large (text) │ ~50ms
REST (JSON/HTTP2)   │ Slow          │ Large (text) │ ~35ms
GraphQL (JSON/HTTP2)│ Slow          │ Medium       │ ~40ms
gRPC (Proto/HTTP2)  │ Very Fast     │ Small (binary)│ ~10ms

gRPC is roughly:
  - 5-10x faster serialization than JSON
  - 50-80% smaller payloads than JSON
  - 2-5x lower latency than REST

But these numbers only matter at SCALE.
For a service doing 100 req/sec, it doesn't matter.
For a service doing 1,000,000 req/sec, it's critical.
```

---

## Real-World Architecture Example

```
UBER'S ARCHITECTURE:

External (riders/drivers):
  Mobile App ──REST──► API Gateway

API Gateway:
  Gateway ──gRPC──► Ride Service
  Gateway ──gRPC──► Pricing Service
  Gateway ──gRPC──► Location Service
  Gateway ──gRPC──► Payment Service

Between services:
  Ride Service ──gRPC──► Driver Matching
  Pricing Service ──gRPC──► Surge Calculator
  Payment Service ──gRPC──► Fraud Detection

Why this mix?
  - REST for external: universal, every device supports it
  - gRPC for internal: performance, type safety, streaming
    (location updates are a server stream)
```

---

# 🔥 SRE TROUBLESHOOTING SCENARIO — API Layer

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P2
Service: Social media platform — News Feed API

ARCHITECTURE:
  Mobile App ──GraphQL──► Feed Gateway
  Feed Gateway ──gRPC──► User Service
  Feed Gateway ──gRPC──► Post Service
  Feed Gateway ──gRPC──► Image Service

SYMPTOMS:
  - News feed loading time spiked from 400ms to 12 seconds
  - Only affects users who follow many accounts (500+)
  - Users who follow <50 accounts are fine (~500ms)
  - No errors in logs — just extreme slowness
  - Monitoring shows:
    → Feed Gateway CPU: 92% (normally 35%)
    → User Service: response time 3ms (NORMAL)
    → Post Service: response time 8ms (NORMAL)
    → Image Service: response time 5ms (NORMAL)
    → Database query times: all normal
    → Feed Gateway is making 47,000 gRPC calls per
      second (normally 3,000/sec)

RECENT CHANGE:
  A junior developer added a new "enriched feed" feature.
  The GraphQL resolver for feed now fetches:
    - Each post's author details (User Service)
    - Each post's image metadata (Image Service)
    - Each author's follower count (User Service again)

  The resolver code looks like:

  async function resolveFeed(userId) {
    const posts = await postService.GetFeed(userId);
    for (const post of posts) {
      post.author = await userService.GetUser(post.authorId);
      post.images = await imageService.GetImages(post.id);
      post.author.followers = await userService
                               .GetFollowerCount(post.authorId);
    }
    return posts;
  }
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** What is the root cause? Identify the specific anti-pattern in the code and calculate the math of why heavy-follow users are affected.

**Question 2:** Why is the Feed Gateway CPU at 92% if all downstream services are responding in single-digit milliseconds?

**Question 3:** Immediate mitigation — what do you do right now?

**Question 4:** Long-term fix — how do you redesign this properly? Give me the specific patterns/tools from what I taught you that solve this.


### Staff

## Failure Modes
These are the ways REST, GraphQL, and gRPC **actually break** in production.

### REST Failure Patterns

```
FAILURE 1: CHATTY API (Death by Round Trips)

  Microservice team splits a monolith API:

  BEFORE (monolith):
    GET /api/order/123
    → Returns order + items + shipping + payment
    → 1 request, 1 DB query with JOINs, 40ms total

  AFTER (microservices, exposed via REST):
    GET /api/order/123          → Order Service (10ms)
    GET /api/items?orderId=123  → Item Service (10ms)
    GET /api/shipping/order/123 → Shipping Service (15ms)
    GET /api/payment/order/123  → Payment Service (12ms)

    4 sequential requests = 47ms server time
    BUT: 4 × network RTT (say 20ms each) = 80ms network
    Total: 127ms (3x worse than monolith)

    On mobile (100ms RTT):
    4 × 100ms = 400ms JUST for network
    Total: 447ms (10x worse!)

  HOW TO DETECT:
    → High request count per page load
    → Latency grows with number of downstream services
    → Server response times are fast, but user
      experience is slow
    → Network time dominates server time in traces

  METRICS TO WATCH:
    → Requests-per-session (if climbing after a
      deployment, someone split an API)
    → Upstream-to-downstream request ratio
      (1 user request → N backend requests)


FAILURE 2: PAYLOAD BLOAT

  REST APIs grow over time. Fields get added,
  never removed.

  Day 1:   GET /users/123 → 200 bytes
  Year 1:  GET /users/123 → 2KB
  Year 3:  GET /users/123 → 15KB

  Nobody notices because it grows slowly.
  Then: "Why is our mobile app using so much data?"

  15KB × 50 API calls per session = 750KB
  On 3G connection: 3-4 seconds just to download

  HOW TO DETECT:
    → Monitor average response body size over time
    → Alert if p95 response size exceeds threshold
    → Track mobile data usage per session

  FIX:
    → Sparse fieldsets: GET /users/123?fields=name,email
    → Or migrate to GraphQL for that endpoint


FAILURE 3: CACHE STAMPEDE ON EXPIRY

  Popular REST endpoint cached with TTL = 300s
  10,000 users requesting GET /api/trending
  Cache expires → ALL 10,000 requests hit the server

  HOW TO DETECT:
    → Periodic spikes in backend load exactly at
      cache TTL intervals
    → Looks like a heartbeat on the graph:
      ─────╱╲─────╱╲─────╱╲─────
           5min   5min   5min

  FIX:
    → Staggered TTLs (add random jitter: 300s ± 30s)
    → Cache warming (background refresh before expiry)
    → Locking (only ONE request regenerates cache,
      others wait)
```

### GraphQL Failure Patterns

```
FAILURE 1: N+1 QUERY EXPLOSION (The #1 GraphQL Killer)

  You learned what N+1 is. Here's how it manifests
  in production and how to CATCH it:

  SYMPTOMS:
    → Database CPU spikes when specific GraphQL
      queries are made
    → Database shows thousands of identical queries
      with different IDs:

      SELECT * FROM users WHERE id = 1;
      SELECT * FROM users WHERE id = 2;
      SELECT * FROM users WHERE id = 3;
      ... (500 more)

    → GraphQL resolver response time is slow but
      each individual DB query is fast (1ms each)
    → Total = 1ms × 500 = 500ms

  HOW TO DETECT:
    → Monitor DB queries-per-GraphQL-request ratio
    → If ratio > 10, you likely have N+1
    → Enable query logging, look for repeated
      patterns with different IDs
    → Apollo Studio / GraphQL tracing shows
      resolver-level timing

  FIX:
    → DataLoader (batches individual fetches into
      one query):

      BEFORE DataLoader:
        500 queries: SELECT * FROM users WHERE id = ?

      AFTER DataLoader:
        1 query: SELECT * FROM users WHERE id IN (1,2,3,...500)

    → DataLoader collects all IDs within a single
      tick of the event loop, then fires ONE batched query


FAILURE 2: QUERY COMPLEXITY ATTACK (DoS via GraphQL)

  Unlike REST where the server controls what's returned,
  GraphQL lets CLIENTS control query shape.

  A malicious or careless client can send:

    query {
      users(first: 100) {
        posts(first: 100) {
          comments(first: 100) {
            author {
              posts(first: 100) {
                comments(first: 100) {
                  text
                }
              }
            }
          }
        }
      }
    }

  Potential records: 100 × 100 × 100 × 100 × 100
                   = 10 BILLION

  SYMPTOMS:
    → One request consumes all server CPU
    → Out of memory errors
    → Other requests starved (noisy neighbor)
    → Looks like a DDoS but from one client

  HOW TO DETECT:
    → Monitor query depth (nested levels)
    → Monitor query complexity score
    → Monitor single-request CPU time
    → Alert on any request taking > 10 seconds

  FIX:
    → Query depth limit (reject queries deeper than N)
    → Complexity scoring:

      Each field has a cost:
        users: cost = 10
        posts: cost = 5 per parent
        comments: cost = 3 per parent

      Max allowed complexity = 1000
      Query exceeding 1000 → rejected before execution

    → Persisted queries (BEST for production):
      → Client can ONLY send pre-approved query hashes
      → Unknown queries rejected
      → Eliminates arbitrary query risk entirely


FAILURE 3: GRAPHQL HIDES ERRORS FROM MONITORING

  REST:  500 status → your error rate dashboard catches it

  GraphQL: 200 status + error in body:
    {
      "data": null,
      "errors": [{"message": "Internal server error"}]
    }

  Your monitoring sees: 200 OK. Zero errors!
  But users see: broken pages.

  SYMPTOMS:
    → Users report errors
    → Monitoring shows 100% success rate
    → "Works on my machine" because curl gets 200

  HOW TO DETECT:
    → NEVER rely on HTTP status codes for GraphQL
    → Parse response body for "errors" field
    → Custom metric: graphql_errors_total
    → Alert on: graphql_errors_total / graphql_requests_total

  FIX:
    → GraphQL-aware monitoring middleware
    → Log every response that contains "errors" key
    → Custom Prometheus/Datadog metrics:

      # In your GraphQL middleware:
      if response.body.contains("errors"):
          metrics.increment("graphql.error",
            tags=["operation:GetFeed", "type:resolver"])
```

### gRPC Failure Patterns

```
FAILURE 1: LOAD BALANCER BLACK HOLE

  This is the #1 gRPC production gotcha.

  gRPC uses long-lived HTTP/2 connections.

  Setup:
    Client → L4 Load Balancer → 3 Backend Servers

  What happens:
    1. Client opens ONE TCP connection to LB
    2. LB assigns this connection to Backend-1
    3. ALL gRPC calls from this client go to Backend-1
    4. Backend-2 and Backend-3 get ZERO traffic
    5. Backend-1 is overloaded, others are idle

  WHY:
    L4 LB distributes TCP CONNECTIONS, not requests.
    One TCP connection = one backend.
    gRPC multiplexes thousands of requests on one connection.
    LB doesn't see individual requests — just one connection.

  SYMPTOMS:
    → Uneven CPU across backend servers
    → One server at 90%, others at 10%
    → Adding more servers doesn't help
    → Autoscaler spins up new servers that get no traffic

  HOW TO DETECT:
    → Monitor per-server request rate (should be ~equal)
    → Monitor per-server CPU (should be ~equal)
    → Alert on: max(server_cpu) / avg(server_cpu) > 2

  FIX:
    → Use L7 load balancer that understands HTTP/2
      (Envoy, Linkerd, gRPC-aware LB)
    → OR: Client-side load balancing
      → Client gets list of all servers from
        service discovery (Consul, etcd, k8s DNS)
      → Client opens connections to ALL servers
      → Client round-robins requests across connections
    → OR: Periodic connection cycling
      → Client closes and reopens connection every
        N minutes, gets reassigned to different backend


FAILURE 2: PROTOBUF SCHEMA MISMATCH

  Service A (client) has user.proto version 1
  Service B (server) updates to user.proto version 2

  Version 2 changes:
    - Renamed field "name" to "full_name"
    - Changed field number 3 from string to int64

  What happens:
    → Service A sends data with old field numbers
    → Service B tries to deserialize with new schema
    → Silent data corruption or crash
    → NOT a connection error — harder to detect

  SYMPTOMS:
    → Weird data showing up (wrong values in wrong fields)
    → Intermittent deserialization errors
    → Partial failures (some fields work, others don't)
    → Only happens between specific service version pairs

  HOW TO DETECT:
    → Monitor deserialization error rates per service pair
    → Monitor "unknown field" warnings in protobuf
    → Schema registry with compatibility checks

  FIX:
    → NEVER change field numbers (protobuf rule #1)
    → NEVER change field types
    → Only ADD new fields (with new field numbers)
    → Use 'reserved' keyword for removed fields:

      message User {
        int64 id = 1;
        string full_name = 2;
        reserved 3;           // was "phone", now removed
        reserved "phone";     // prevent reuse of name
        string email = 4;     // new field, new number
      }

    → Run proto-breaking-change-detector in CI/CD
    → Reject PRs that make breaking proto changes


FAILURE 3: DEADLINE PROPAGATION FAILURE

  gRPC has built-in deadline support.
  But if not configured properly:

  User request → Gateway (timeout: 5s)
    → Service A (no timeout set!)
      → Service B (no timeout set!)
        → Service C (stuck, holding DB lock)

  Gateway times out after 5s, returns error to user.
  But Services A, B, C are STILL WORKING on the request!
  They don't know the user gave up.
  They're wasting CPU, holding connections, holding DB locks.

  Multiply by thousands of requests:
    → Zombie work accumulates
    → Services slow down under phantom load
    → Cascading failure

  SYMPTOMS:
    → User-facing errors (timeouts)
    → But downstream services show HIGH load
    → Services doing work that nobody wants anymore
    → CPU/memory climbing on downstream services
    → Looks like "load is increasing" but actual
      user traffic is flat

  HOW TO DETECT:
    → Compare: user-facing error rate vs downstream
      service request rate
    → If user errors UP but downstream requests
      ALSO up → wasted work
    → Monitor "requests cancelled by client" metric
    → If near zero → deadlines not propagating

  FIX:
    → ALWAYS propagate deadlines:

      // Go example:
      ctx, cancel := context.WithTimeout(
        parentCtx,
        time.Second * 3,
      )
      defer cancel()
      response, err := serviceB.DoWork(ctx, request)

    → Each service subtracts its own processing time:
      Gateway: 5s deadline
      Service A: receives 5s, uses 0.5s, passes 4.5s
      Service B: receives 4.5s, uses 0.3s, passes 4.2s
      Service C: receives 4.2s, must finish within 4.2s

    → If any service sees remaining deadline < threshold:
      → Return immediately with DEADLINE_EXCEEDED
      → Don't even start the work
```

---

## SRE Diagnostic Toolkit

```
REST DEBUGGING:
━━━━━━━━━━━━━━

# Test endpoint response time and size
curl -w "\nTime: %{time_total}s\nSize: %{size_download} bytes\n" \
  -s -o /dev/null https://api.example.com/users/123

# Test with verbose headers (see HTTP version, caching)
curl -v https://api.example.com/users/123 2>&1 | \
  grep -E "< HTTP|< Cache|< Content-Length|< ETag"

# Load test REST endpoint (quick and dirty)
ab -n 1000 -c 50 https://api.example.com/users/123
# -n: total requests, -c: concurrent

# Check response payload size trends
# (pipe to jq for JSON response size)
curl -s https://api.example.com/users/123 | wc -c


GRAPHQL DEBUGGING:
━━━━━━━━━━━━━━━━━

# Send a GraphQL query via curl
curl -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ user(id: 123) { name email } }"}'

# Check for errors hidden in 200 response
curl -s -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ user(id: 123) { name } }"}' | \
  jq '.errors'
# If this returns non-null → you have errors
# despite 200 status

# Introspect the schema (if introspection is enabled)
curl -s -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __schema { types { name } } }"}' | \
  jq '.data.__schema.types[].name'

# Check query complexity
# (most GraphQL servers log this — check server logs)
grep "query complexity" /var/log/graphql/server.log | \
  sort -t'=' -k2 -rn | head -20


gRPC DEBUGGING:
━━━━━━━━━━━━━━

# grpcurl — curl for gRPC (install: brew install grpcurl)

# List available services
grpcurl -plaintext localhost:50051 list

# List methods on a service
grpcurl -plaintext localhost:50051 list UserService

# Call a method
grpcurl -plaintext -d '{"user_id": 123}' \
  localhost:50051 UserService/GetUser

# Check gRPC health (standard health check protocol)
grpcurl -plaintext localhost:50051 \
  grpc.health.v1.Health/Check

# Monitor gRPC connection distribution across backends
# (detect load balancer black hole)
# On each backend server:
grep "grpc.request.count" /metrics | tail -5

# Compare across servers — should be roughly equal:
for server in backend-{1..6}; do
  echo "$server: $(curl -s http://$server:9090/metrics | \
    grep grpc_server_handled_total | \
    awk '{sum+=$2} END {print sum}')"
done

# Expected good output:
#   backend-1: 15,234
#   backend-2: 15,102
#   backend-3: 14,998

# Bad output (black hole):
#   backend-1: 44,891    ← ALL traffic here
#   backend-2: 312
#   backend-3: 131


CROSS-PROTOCOL DEBUGGING:
━━━━━━━━━━━━━━━━━━━━━━━━━

# Determine if problem is API layer vs transport vs DB:

# Step 1: Check transport (is TCP/HTTP healthy?)
curl -w "DNS: %{time_namelookup}s\n\
Connect: %{time_connect}s\n\
TLS: %{time_appconnect}s\n\
FirstByte: %{time_starttransfer}s\n\
Total: %{time_total}s\n" \
  -s -o /dev/null https://api.example.com/health

# If Connect is slow → network/TCP issue
# If TLS is slow → certificate/handshake issue
# If FirstByte is slow → server processing issue
# If Total is slow but FirstByte fast → large response

# Step 2: Check application (is the API logic healthy?)
# Look at application-level metrics:
#   request_duration_seconds (histogram)
#   response_size_bytes (histogram)
#   downstream_call_count_per_request (counter)

# Step 3: Check database (is the DB healthy?)
# If API is slow but DB metrics are fine:
#   → Problem is in API layer (serialization,
#     N+1 queries, payload size)
# If DB metrics are also slow:
#   → Problem is deeper (query optimization,
#     connection pool, locks)
```

---

## Hands-On Exercises

```
EXERCISE 1: See REST Over-Fetching In Action
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Hit a real public API and measure waste:

  # Full user object from GitHub API:
  curl -s https://api.github.com/users/torvalds | wc -c
  # → ~1,500 bytes

  # But if you only needed name and bio:
  curl -s https://api.github.com/users/torvalds | \
    jq '{name, bio}' | wc -c
  # → ~80 bytes

  # That's 95% wasted bandwidth on REST.
  # THIS is why GraphQL exists.


EXERCISE 2: See N+1 Problem
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # If you have Docker:
  # Spin up a simple GraphQL server and enable
  # query logging on your database.

  # Send this query:
  # { users(limit: 10) { name posts { title } } }

  # Watch the DB logs — count the queries.
  # You should see:
  #   1 query for users
  #   10 queries for posts (one per user)
  #   = 11 total (the "N+1")

  # Now enable DataLoader and re-run.
  # You should see:
  #   1 query for users
  #   1 query for posts (batched)
  #   = 2 total


EXERCISE 3: See gRPC Load Balancer Black Hole
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # If you have Kubernetes:

  # Deploy a gRPC service with 3 replicas
  # Put an L4 Service (type: ClusterIP) in front

  # From a client pod, make 1000 gRPC requests
  # Check which backend handled each request

  # You'll see: ONE backend handled nearly all 1000
  # Because: one TCP connection → one backend

  # Now switch to Headless Service
  # (client-side LB with dns:/// scheme)
  # Re-run: requests distributed across all 3 backends
```

---

## Targeted Reading

```
READ AFTER THIS LESSON:

1. DDIA Chapter 4: "Encoding and Evolution"
   (pages 111-150)
   → Specifically the sections on:
     - Protocol Buffers encoding (page 117-121)
     - Schema evolution and compatibility (page 127-132)
   → This reinforces WHY protobuf works the way it does
     and WHY field numbers matter

2. DDIA Chapter 12: "The Future of Data Systems"
   (pages 489-500 only)
   → Section on "API design" and "service composition"
   → Reinforces the REST vs RPC trade-offs

OPTIONAL (if targeting Google/Meta):
3. Google's gRPC documentation: "Core Concepts"
   https://grpc.io/docs/what-is-grpc/core-concepts/
   → 15 minute read
   → Shows the 4 streaming patterns with sequence diagrams
```

---

## Production Failure Patterns

```
PATTERN 1: GraphQL N+1 / RESOLVER STORM
  Symptom: p99 explodes on nested queries; DB connection pool exhausted
  Fix:     DataLoader batching, query depth/complexity limits, persisted queries

PATTERN 2: gRPC LOAD BALANCER BLACK HOLE
  Symptom: one pod at 100% CPU, others idle; sticky broken connections
  Cause:   L4 LB unaware of gRPC long-lived HTTP/2 connections
  Fix:     L7 gRPC-aware LB (Envoy/Istio), client-side round_robin, max connection age

PATTERN 3: REST OVER-FETCH + CHATTY MOBILE
  Symptom: high egress, slow screens, battery drain
  Fix:     Field selection, BFF per client, or GraphQL for aggregate views

PATTERN 4: PROTOBUF SCHEMA BREAKING CHANGE
  Symptom: deserialization errors after deploy skew between services
  Fix:     Field numbering rules, backward-compatible adds, feature flags for rollout

PATTERN 5: GraphQL INTROSPECTION + DEPTH ATTACK
  Symptom: CPU spike from malicious deep queries
  Fix:     Disable introspection in prod, complexity scoring, rate limits
```

---

## Decision Framework

```
REST vs GraphQL vs gRPC:

  Public third-party API, cacheable resources     → REST + OpenAPI
  Mobile/web with varied screens, aggregation     → GraphQL (+ DataLoader)
  Internal service-to-service, high RPS           → gRPC (+ protobuf)
  Browser-facing real-time                       → REST/GraphQL + WebSocket; not raw gRPC

RULE: Match protocol to client + coupling, not team preference.
  gRPC   = performance + strong contracts + generated stubs
  GraphQL = flexible reads + single endpoint + server complexity
  REST   = simplicity + HTTP caching + universal tooling
```

---

### Principal stretch

## Ops Sim: Northstar GraphQL Fan-Out and gRPC Black Hole

**Time box:** 35 minutes
**Severity:** P1
**Service / domain:** Mobile GraphQL gateway, internal gRPC user/profile services
**Northstar system:** API

### Rules

1. Answer from memory; do not re-read the protocol comparison mid-drill.
2. Write decisions in order (T+0 -> T+60).
3. Cite a metric, log, trace, or config key for every claim.
4. Do not open the answer key until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  Heavy buyers opening the auction page see spinners for seller reputation,
  shipping ETA, and bid history. Light users are mostly fine.

WHAT ON-CALL SEES:
  `mobile-gateway` p99 450ms -> 11.8s, CPU 91%.
  `profile-grpc` has two hot pods at 88% CPU; ten pods sit near 11%.
  HTTP status checks are 200 because GraphQL returns errors in response bodies.

BUSINESS CONSTRAINT:
  Auction close cannot be delayed. It is acceptable to hide non-critical seller
  widgets, but bids and payment eligibility must stay correct.
```

### 2. Telemetry pack

```text
METRICS:
  GraphQL operation AuctionPage: p99=11.8s; error field rate=22%
  mobile_gateway_grpc_client_calls_total: 12k/s -> 176k/s
  profile-grpc pod CPU: [88, 86, 12, 11, 10, 12, 9, 13, 11, 10, 12, 11]
  bid-history REST endpoint p95: 48ms; shipping REST p95: 55ms
  DB query p95 for profile lookup: 9ms

LOG LINES:
  GraphQL 200 body: {"errors":[{"path":["auction","seller","reputation"]}]}
  mobile-gateway: resolver sellerReputation invoked 1400 times for request_id=...
  profile-grpc: stream created remote=10.2.4.18 lb=nlb-profile-grpc

TRACE:
  AuctionPage -> sellerReputation -> profile-grpc.GetUser repeated per bid row
  1,400 serialized gRPC spans for a single high-bid auction page.
```

### 3. Config pack

```yaml
# profile-grpc service
load_balancer: aws-nlb
protocol: grpc
replicas: 12

# wrong/dangerous gateway config
graphql:
  dataloader_enabled: false
  batch_profile_lookup: false
  max_resolver_calls_per_request: 5000
  report_graphql_errors_as_http_5xx: false
```

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | P1: auction page p99 is 11.8s but HTTP 5xx alert is quiet. | |
| T+5 | Trace shows 1,400 serialized profile lookups per heavy page. | |
| T+15 | Infra proposes adding 24 more `profile-grpc` pods behind the same NLB. | |
| T+60 | A gateway feature flag can hide seller widgets or enable batched lookup. | |

### 5. Questions

**Q1 - Layer & root cause:** Identify the two distinct protocol/application failures.

**Q2 - Evidence:** Which signals distinguish GraphQL body errors, N+1 fan-out, and gRPC L4 connection pinning?

**Q3 - Sequencing:** What do you do in the first 15 minutes without breaking bid correctness?

**Q4 - Bad fix gallery:** Why is "add pods behind the same NLB" dangerous/incomplete? Why is "return 500 for all GraphQL errors" also wrong?

**Q5 - Capacity / blast radius:** If 100 heavy users each trigger 1,400 profile calls and retry once, what call volume hits `profile-grpc`?

**Q6 - Durable fix:** Name the GraphQL and gRPC infrastructure changes plus acceptance criteria.

**Q7 - Org / runbook:** Who gets paged/updated during this P1, and which UI degradation is pre-authorized?

**Answer key:** [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/REST vs GraphQL vs gRPC Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/REST%20vs%20GraphQL%20vs%20gRPC%20Answers.md)

---

## Key Takeaways (5-Bullet Summary)

```
╔══════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:             ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. REST = simple, cacheable, universal.                    ║
║      Use for external/public APIs.                           ║
║      Breaks down with complex data relationships.            ║
║                                                              ║
║   2. GraphQL = flexible queries, prevents                    ║
║      over/under-fetching. Use for complex frontends.         ║
║      MUST implement DataLoader or you will kill              ║
║      your database with N+1 queries.                         ║
║                                                              ║
║   3. gRPC = fastest, strongly typed, streaming.              ║
║      Use for internal service-to-service.                    ║
║      MUST use L7 load balancing or client-side LB,           ║
║      or you get the black hole problem.                      ║
║                                                              ║
║   4. The most common production pattern:                     ║
║      External: REST or GraphQL                               ║
║      Internal: gRPC                                          ║
║      This is what Google, Uber, Netflix do.                  ║
║                                                              ║
║   5. GraphQL returns 200 for errors.                         ║
║      If your monitoring only checks HTTP status              ║
║      codes, you are BLIND to GraphQL failures.               ║
║      This has caused real outages at real companies.         ║
╚══════════════════════════════════════════════════════════════╝
```

---

# Now: The SRE Scenario

This tests everything from the original teaching PLUS the production failure patterns I just taught you. Everything you need is in what you've learned.

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P2
Service: Social media platform — News Feed API

ARCHITECTURE:
  Mobile App ──GraphQL──► Feed Gateway
  Feed Gateway ──gRPC──► User Service
  Feed Gateway ──gRPC──► Post Service
  Feed Gateway ──gRPC──► Image Service

  Feed Gateway runs behind an L4 load balancer.
  User/Post/Image Services each have 6 replicas
  behind their own L4 load balancers.

SYMPTOMS:
  - News feed loading time spiked from 400ms to 12s
  - Only affects users who follow 500+ accounts
  - Users who follow <50 accounts are fine (~500ms)
  - No errors in logs — just extreme slowness
  - Monitoring shows:
    → Feed Gateway CPU: 92% (normally 35%)
    → User Service CPU: 85% on 2 of 6 replicas,
      8% on the other 4 replicas
    → Post Service: response time 8ms (NORMAL)
    → Image Service: response time 5ms (NORMAL)
    → Database query times: all normal
    → Feed Gateway making 47,000 gRPC calls/sec
      (normally 3,000/sec)

RECENT CHANGE:
  A junior developer added a new "enriched feed"
  feature. The GraphQL resolver code:

  async function resolveFeed(userId) {
    const posts = await postService.GetFeed(userId);
    for (const post of posts) {
      post.author = await userService.GetUser(post.authorId);
      post.images = await imageService.GetImages(post.id);
      post.author.followers =
        await userService.GetFollowerCount(post.authorId);
    }
    return posts;
  }
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** What is the root cause? I see TWO distinct problems in this incident — identify BOTH. Calculate the math showing why 500+ follower users are destroyed.

**Question 2:** Explain the User Service CPU distribution (85% on 2 replicas, 8% on 4 replicas). What specific failure pattern from what I taught you causes this?

**Question 3:** Immediate mitigation — what do you do right now? Exact steps.

**Question 4:** Long-term redesign — give me the specific fix for the code AND the infrastructure. Name the exact patterns/tools.
> **Answer key (do not open until you attempt the scenario questions):**
> [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/REST%20vs%20GraphQL%20vs%20gRPC%20Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/REST%20vs%20GraphQL%20vs%20gRPC%20Answers.md)
