# Answer Key - CAP Theorem

> Open only after attempting the learner file questions.

# Incident Deep-Dive: Cross-Region Partition on a Financial Trading Platform

---

## Question 1: PACELC Classification of Every Component

### PACELC Refresher

```
PACELC: "If there's a Partition (P), choose Availability (A)
or Consistency (C). Else (E), choose Latency (L) or
Consistency (C)."

Every distributed system makes these choices —
explicitly or accidentally.
```

### PostgreSQL (Trade Records, Account Balances)

```
CURRENT BEHAVIOR:

  Normal operation (E):
    → EL (Else Latency)
    → Async replication: US primary commits immediately
      without waiting for EU replica to acknowledge
    → EU reads go to local replica (fast, ~1ms)
    → Trade-off: EU reads may be 50-80ms stale, but
      reads are FAST

  During partition (P):
    → PA (Partition Availability)
    → EU replica continues serving reads despite
      growing lag (4.2s → 12.8s)
    → Writes still go to US primary (succeeds for US users)
    → EU users can READ (stale data) but writes are
      routed to US primary (slow/failing due to cable)
    → System chose AVAILABILITY over CONSISTENCY:
      it serves stale balances rather than refusing reads

IS THIS THE RIGHT CHOICE?

  FOR TRADE RECORDS: PA/EL is WRONG.

  Account balances are FINANCIAL DATA. A stale read
  directly caused Alice to overdraw by $20,000. Three
  trades exceeded balance limits, creating $340,000 in
  uncontrolled exposure. In financial systems, a wrong
  answer is WORSE than no answer.

  SHOULD BE: PC/EC
    → During partition: REFUSE reads from stale replica
      for balance-critical operations (trade approval)
    → Normal operation: accept slightly higher latency
      to ensure reads reflect committed state
    → The cost of a rejected trade (user frustration,
      lost trading opportunity) is VASTLY less than the
      cost of an unauthorized overdraft (regulatory fine,
      financial loss, legal liability)

  FOR READ-ONLY QUERIES (trade history, statements):
    → PA/EL is ACCEPTABLE
    → Showing a trade history that's 4 seconds behind
      is annoying but not dangerous
    → No financial decision depends on this read
```

### Cassandra (Market Data Feed)

```
CURRENT BEHAVIOR:

  Normal operation (E):
    → EL (Else Latency)
    → LOCAL_QUORUM reads: only need quorum within
      the LOCAL datacenter
    → Fast reads (~3-5ms) from local nodes
    → Cross-DC consistency happens asynchronously

  During partition (P):
    → PA (Partition Availability)
    → LOCAL_QUORUM means each DC operates independently
    → EU-West continues serving market data from its
      local nodes
    → But that data is 320ms+ stale (cross-DC replication
      delayed by cable degradation)
    → System chose AVAILABILITY: serve stale prices
      rather than refusing market data queries

IS THIS THE RIGHT CHOICE?

  PARTIALLY RIGHT, PARTIALLY WRONG.

  For DISPLAYING prices to traders (informational):
    → PA/EL is ACCEPTABLE with a warning
    → Traders can see prices are delayed and adjust
      their behavior
    → Every trading platform has a "prices may be delayed"
      disclaimer
    → 320ms staleness should be SURFACED to the user,
      not hidden

  For EXECUTING TRADES based on these prices:
    → PA/EL is DANGEROUS
    → A trader sees a stale price and submits a market
      order expecting that price
    → By the time the order reaches the matching engine,
      the real price may have moved significantly
    → In volatile markets, 320ms of price staleness can
      mean thousands of dollars per trade
    → Trade execution should use REAL-TIME prices from
      the authoritative source, not stale cached data

  SHOULD BE: Mixed
    → Display: PA/EL (show stale prices with "delayed" flag)
    → Execution: PC/EC (trade orders must use prices from
      the authoritative market data source, even if slower)
```

### Redis (Order Book Cache, Sessions)

```
CURRENT BEHAVIOR:

  Normal operation (E):
    → EL (Else Latency)
    → Independent clusters per region
    → Local reads, ~0.3ms latency
    → No cross-region consistency needed for sessions

  During partition (P):
    → PA (Partition Availability)
    → Each Redis cluster is independent and unaffected
      by the cross-region partition
    → Sessions work fine (local only)
    → BUT: order book cache is populated from Cassandra
      market data, which is stale → order book is stale

IS THIS THE RIGHT CHOICE?

  For SESSIONS: PA/EL is CORRECT.
    → Sessions are inherently per-region
    → No cross-region dependency
    → Availability is the right choice

  For ORDER BOOK CACHE: The Redis cluster itself is fine.
    → The problem isn't Redis — it's the DATA FLOWING
      INTO Redis from stale Cassandra data
    → Redis is faithfully caching what it's told to cache
    → The staleness is upstream (Cassandra), not in Redis
    → CORRECT CHOICE: Redis should cache what it receives,
      but the APPLICATION should mark order book data with
      a staleness indicator based on the source timestamp
```

### API Gateway (Regional Routing)

```
CURRENT BEHAVIOR:

  Normal operation (E):
    → EL (Else Latency)
    → Routes users to nearest region
    → Minimizes latency

  During partition (P):
    → PA (Partition Availability)
    → Continues routing EU users to EU-West
    → EU-West is "available" but serving stale/dangerous data
    → Does NOT failover EU users to US-East

IS THIS THE RIGHT CHOICE?

  WRONG for trade-critical operations.

  The API gateway should be AWARE of partition conditions
  and make per-feature routing decisions:

  → Browsing, market data display: route to EU-West (PA/EL)
    → Stale but fast — acceptable with staleness indicator

  → Trade execution, balance checks: route to US-East (PC/EC)
    → Slower (320ms+ latency) but CORRECT data
    → A trade that takes 400ms is better than a trade
      that causes a $20,000 overdraft
```

### PACELC Summary Table

```
╔════════════════════════════════════════════════════════════════╗
║  COMPONENT    │ CURRENT  │ SHOULD BE│ WHY                      ║
╠════════════════════════════════════════════════════════════════╣
║  PostgreSQL   │ PA/EL    │ PC/EC    │ Stale balance reads      ║
║  (balances)   │          │ for      │ cause overdrafts.        ║
║               │          │ balance  │ Wrong answer > no answer ║
║               │          │ checks   │ is NEVER true for money. ║
╠════════════════════════════════════════════════════════════════╣
║  PostgreSQL   │ PA/EL    │ PA/EL    │ Stale trade history is   ║
║  (history)    │          │ (OK)     │ annoying, not dangerous. ║
╠════════════════════════════════════════════════════════════════╣
║  Cassandra    │ PA/EL    │ PA/EL    │ Stale price DISPLAY is   ║
║  (display)    │          │ + stale  │ OK with warning flag.    ║
║               │          │ warning  │                          ║
╠════════════════════════════════════════════════════════════════╣
║  Cassandra    │ PA/EL    │ PC/EC    │ Trade execution on stale ║
║  (execution)  │          │ for trade│ prices = financial risk. ║
║               │          │ execution│                          ║
╠════════════════════════════════════════════════════════════════╣
║  Redis        │ PA/EL    │ PA/EL    │ Sessions are local.      ║
║  (sessions)   │          │ (OK)     │ No cross-region need.    ║
╠════════════════════════════════════════════════════════════════╣
║  Redis        │ PA/EL    │ PA/EL    │ Cache is correct; the    ║
║  (order book) │          │ + stale  │ staleness is upstream.   ║
║               │          │ indicator│ Surface it, don't hide.  ║
╠════════════════════════════════════════════════════════════════╣
║  API Gateway  │ PA/EL    │ Per-     │ Route reads to local     ║
║               │          │ feature  │ (PA/EL). Route writes    ║
║               │          │ routing  │ and balance checks to    ║
║               │          │          │ primary region (PC/EC).  ║
╚════════════════════════════════════════════════════════════════╝

THE CORE LESSON:
  Not every piece of data in a system deserves the same
  PACELC treatment. The system architect must classify
  data BY CONSEQUENCE OF STALENESS:

  "What happens if this read is 5 seconds stale?"
    → Trade history: User sees old data. Annoying. → PA/EL
    → Market prices: Trader sees old price. Risky. → PA/EL with warning
    → Account balance for trade approval: Overdraft. → PC/EC
    → Balance for display: User confused. → PA/EL with warning
```

---

## Question 2: Alice's $120,000 Trade — What Went Wrong

### a) In PACELC Terms

```
The system was configured as PA/EL for account balances.

During the partition:
  → The system chose AVAILABILITY: it continued serving
    reads from the EU replica even though the replica
    was 4.2 seconds behind the primary
  → Specifically: the TRADE APPROVAL service read
    Alice's balance from the EU replica
  → The EU replica showed $150,000 (stale)
  → The US primary had $100,000 (current)
  → The trade was approved based on stale data

The system made the WRONG PA choice for this data:

  It should have been PC: during a partition, REFUSE
  to read balance data from the stale replica for
  trade approval purposes. Either:
    a) Read from the US primary (slower but correct), or
    b) Reject the trade entirely ("balance check
       unavailable, please retry")

  Alice would have been annoyed if her trade was delayed
  or rejected. But she wouldn't be $20,000 in the red.

  THE FUNDAMENTAL ERROR:
  The system treated account-balance-for-trade-approval
  the same as account-balance-for-display. These are
  DIFFERENT operations with DIFFERENT consistency
  requirements, but they read from the same table
  with the same replication configuration.
```

### b) Two Architectural Fixes with Different PACELC Tradeoffs

### Fix 1: Route Balance Checks for Trade Approval to Primary (PC/EC)

```
DESIGN:
  → Trade approval service ALWAYS reads balance from
    US-East primary, regardless of which region the
    trader is in
  → All other balance reads (display, history) can
    use the local replica

  Code:
  async def approve_trade(user_id, trade_amount):
      # CRITICAL: read from PRIMARY, not replica
      balance = await primary_db.fetch_one(
          "SELECT balance FROM accounts WHERE user_id = $1 "
          "FOR UPDATE",  # Lock the row during approval
          user_id
      )

      if balance < trade_amount:
          raise InsufficientFunds()

      # Execute trade against primary
      await primary_db.execute(
          "UPDATE accounts SET balance = balance - $1 "
          "WHERE user_id = $2",
          trade_amount, user_id
      )

PACELC CLASSIFICATION: PC/EC

  During partition (P → C):
    → EU trade approval MUST reach US primary
    → If the cable is degraded (320ms-850ms latency),
      the trade takes 320-850ms longer
    → If the cable is completely down, the trade FAILS
      ("unable to verify balance")
    → Consistency is GUARANTEED: balance check is always
      against the source of truth

  Else (E → C):
    → Even in normal operation, EU trade approvals take
      ~80ms extra (cross-Atlantic round trip to primary)
    → Every single trade has this latency cost
    → Balance is always consistent

EXPLICIT TRADEOFF:
  SACRIFICE: Latency. Every EU trade takes 80ms+ longer
  (normal) to 850ms+ longer (degraded cable). Some trades
  fail entirely during severe partitions.

  GAIN: Correctness. No trade can ever be approved based
  on stale balance data. Alice's overdraft becomes impossible.

  For a FINANCIAL PLATFORM: 80ms extra latency is invisible
  to a human trader. $20,000 overdraft is catastrophic.
  This is the correct tradeoff.
```

### Fix 2: EU-West Maintains Independent Balance Authority with Conservative Limits (PA/EC)

```
DESIGN:
  → Each region maintains an ALLOCATED TRADING LIMIT
    for each account
  → US-East primary sets: "Alice can trade up to $80,000
    through EU-West" (a conservative fraction of her
    actual $100,000 balance)
  → EU-West has a LOCAL balance ledger that tracks trades
    against this allocation
  → EU-West can approve trades LOCALLY without contacting
    US-East, as long as the allocated limit isn't exceeded
  → Periodically (every few seconds), regions reconcile
    allocations

  Code:
  # EU-West local trade approval:
  async def approve_trade_local(user_id, trade_amount):
      # Read from LOCAL allocation table (EU Redis or EU PostgreSQL)
      allocation = await local_db.fetch_one(
          "SELECT remaining_allocation FROM regional_allocations "
          "WHERE user_id = $1 FOR UPDATE",
          user_id
      )

      if allocation.remaining < trade_amount:
          # Local allocation exhausted — cannot approve locally
          # Option: try primary (slower) or reject
          raise InsufficientLocalAllocation()

      # Approve locally — deduct from allocation
      await local_db.execute(
          "UPDATE regional_allocations "
          "SET remaining_allocation = remaining_allocation - $1 "
          "WHERE user_id = $2",
          trade_amount, user_id
      )

      # Async: notify primary of the trade for reconciliation
      await event_bus.publish("trade_executed", {
          "user_id": user_id,
          "amount": trade_amount,
          "region": "eu-west"
      })

PACELC CLASSIFICATION: PA/EC

  During partition (P → A):
    → EU-West continues approving trades LOCALLY
    → No need to contact US primary
    → System remains AVAILABLE during partition
    → BUT: limited to the pre-allocated amount
    → Alice with $100K balance and $80K EU allocation
      can trade up to $80K in EU without contacting US
    → Her $120K trade would be REJECTED (exceeds $80K
      allocation), even though EU is "available"
    → Overdraft PREVENTED by the conservative allocation

  Else (E → C):
    → Normal operation: allocations are refreshed every
      few seconds via cross-region sync
    → Allocations reflect near-real-time balance
    → Slightly more complex than direct primary reads
    → Consistency maintained through allocation accounting

EXPLICIT TRADEOFF:
  SACRIFICE: Maximum trading capacity per region. Alice can
  only trade $80K in EU even though she has $100K. The other
  $20K is "reserved" for US-East trades or as safety margin.

  GAIN: Availability. EU trades continue even during a
  complete partition. No cross-region call required for
  trades within the allocation.

  ADDITIONAL COMPLEXITY: Allocation management, reconciliation
  logic, handling allocation exhaustion, rebalancing allocations
  as traders move between regions.
```

### Comparison

```
╔════════════════════════════════════════════════════════════════╗
║                     │ FIX 1: Read from │ FIX 2: Regional       ║
║                     │ Primary (PC/EC)  │ Allocation (PA/EC)    ║
╠════════════════════════════════════════════════════════════════╣
║  During partition   │ Trades SLOW or   │ Trades FAST but       ║
║                     │ FAIL if primary  │ LIMITED to allocation ║
║                     │ unreachable      │                       ║
╠════════════════════════════════════════════════════════════════╣
║  Normal operation   │ +80ms latency on │ No extra latency      ║
║                     │ every EU trade   │ for normal trades     ║
╠════════════════════════════════════════════════════════════════╣
║  Overdraft risk     │ ZERO             │ ZERO (within alloc)   ║
╠════════════════════════════════════════════════════════════════╣
║  Complexity         │ LOW              │ HIGH (reconciliation, ║
║                     │ (route to primary│ allocation mgmt,      ║
║                     │  for approvals)  │ rebalancing)          ║
╠════════════════════════════════════════════════════════════════╣
║  Complete partition │ EU trading STOPS │ EU trading continues  ║
║  (cable cut)        │                  │ (within allocation)   ║
╠════════════════════════════════════════════════════════════════╣
║  Best for           │ Most platforms   │ High-frequency        ║
║                     │ (simple, safe)   │ trading requiring     ║
║                     │                  │ local latency         ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Question 3: Synchronous Cross-Region Replication — Good Idea?

### The Architect's Proposal

```
"Switch PostgreSQL to synchronous replication between
US-East (primary) and EU-West (replica). Every write
must be acknowledged by BOTH regions before committing."

This would mean: no write completes until the EU replica
has confirmed it received and applied the WAL.

Would this have prevented Alice's trade?
YES — the EU replica would never be behind the primary,
so Alice's balance read would have been $100,000 (correct).
```

### Arguing FOR Synchronous Replication

```
CASE FOR:

1. CONSISTENCY GUARANTEE:
   → EU replica is ALWAYS in sync with US primary
   → No stale reads, ever
   → Alice's overdraft is structurally impossible
   → All 3 trades that exceeded balance limits would
     have been correctly rejected

2. SIMPLICITY:
   → No need for per-feature routing (Q2 Fix 1)
   → No need for allocation management (Q2 Fix 2)
   → No need to classify data by consistency requirements
   → The replica IS the primary in terms of data freshness
   → Application code doesn't change

3. REGULATORY COMPLIANCE:
   → Financial regulators require accurate balance reporting
   → Synchronous replication provides the strongest
     guarantee that all reads reflect committed state
   → Simplifies audit trail: "our replica is always consistent"

PACELC: PC/EC
  → During partition: writes BLOCK until the replica
    confirms (or timeout → write fails)
  → Else: every write pays the cross-Atlantic RTT
    (80ms) for consistency
```

### Arguing AGAINST Synchronous Replication

```
CASE AGAINST:

1. LATENCY ON EVERY WRITE — ALWAYS:
   → Normal cross-Atlantic RTT: 80ms
   → EVERY write to the US primary now takes +80ms
     minimum (waiting for EU replica ACK)
   → Trade execution: 2ms → 82ms (41x slower)
   → High-frequency trading: 82ms per trade is
     UNACCEPTABLE for US traders
   → The EU consistency guarantee penalizes ALL traders,
     including US traders who don't need it

2. AVAILABILITY CLIFF DURING PARTITION:
   → When the cable degrades (320ms-850ms latency):
     → Every US write takes +320ms to +850ms
     → US traders are now penalized by EU infrastructure
     → If the cable drops completely: ALL WRITES STOP
     → The US primary CANNOT commit any trade because
       it's waiting for EU ACK that will never come
     → Timeout eventually releases the write, but until
       then, the ENTIRE PLATFORM is frozen
     → A cable problem between continents shuts down
       US domestic trading — that's absurd

   → In this specific incident:
     → 14:00: writes go from 2ms to 322ms (+320ms RTT)
     → 14:07: writes go from 2ms to 852ms (+850ms RTT)
     → At 23% packet loss: 23% of write ACKs are lost
     → Lost ACKs trigger timeouts (5-30 seconds)
     → 23% of ALL writes across the entire platform
       take 5-30 seconds or fail entirely
     → US trading grinds to a halt

3. SINGLE POINT OF FAILURE:
   → Synchronous replication makes the EU replica a
     CRITICAL dependency for US writes
   → EU datacenter power outage → US writes stop
   → EU network issue → US writes degraded
   → This VIOLATES the principle of regional independence
   → The whole point of multi-region is that one region's
     failure shouldn't cripple another

4. THIS INCIDENT SPECIFICALLY:
   → At 14:07, cable degradation worsening
   → Synchronous replication would mean:
     → US trades: 2ms → 852ms (425x slower)
     → 23% of US writes timeout entirely
     → US traders can't trade because of EU cable problem
     → You've traded Alice's $20K overdraft for
       PLATFORM-WIDE TRADING HALT
     → The cure is worse than the disease
```

### My Recommendation

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   RECOMMENDATION: DO NOT use synchronous cross-region        ║
║   replication for the entire database.                       ║
║                                                              ║
║   INSTEAD: Use FIX 1 from Q2 (route balance checks           ║
║   to primary) for trade-critical operations ONLY.            ║
║                                                              ║
║   REASONING:                                                 ║
║                                                              ║
║   Synchronous replication is a BLUNT INSTRUMENT.             ║
║   It forces EVERY write across the entire database           ║
║   to pay the cross-region latency tax, including             ║
║   writes that don't need cross-region consistency            ║
║   (analytics events, session updates, audit logs).           ║
║                                                              ║
║   The problem isn't "all EU reads are stale."                ║
║   The problem is "BALANCE CHECKS for trade approval          ║
║   are stale." That's ONE specific read path.                 ║
║                                                              ║
║   Fix the ONE path that needs consistency (route             ║
║   balance checks to primary). Leave everything               ║
║   else async for performance.                                ║
║                                                              ║
║   This is the per-feature PACELC approach:                   ║
║   → Trade approval balance check: PC/EC (read primary)       ║
║   → Everything else: PA/EL (read local replica)              ║
║                                                              ║
║   Cost of Fix 1: +80ms on EU trade approvals                 ║
║   Cost of sync repl: +80ms on ALL writes, platform           ║
║   halt during partition, EU failure affects US               ║
║                                                              ║
║   The targeted fix is STRICTLY BETTER than the               ║
║   blunt instrument for this use case.                        ║
║                                                              ║
║   EXCEPTION: If regulatory requirements MANDATE              ║
║   synchronous replication (some financial regulators         ║
║   require it), then use synchronous replication to           ║
║   a SECOND replica within the SAME REGION, not               ║
║   cross-region. This gives durability without the            ║
║   cross-Atlantic latency penalty.                            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 4: Should EU-West Continue Operating?

### The Decision Framework: Per-Feature CAP Analysis

```
At 14:07:
  → Cross-region latency: 850ms (and worsening)
  → Packet loss: 23% (and worsening)
  → PostgreSQL replication lag: 12.8 seconds
  → 3 trades already exceeded balance limits
  → Total unauthorized exposure: $340,000
  → Cable degradation is getting WORSE, not better

The question: continue EU-West operations or redirect
EU users to US-East?

This is NOT an all-or-nothing decision. Apply the
per-feature CAP framework:
```

### Decision: SPLIT EU-West Operations by Feature

```
╔═══════════════════════════════════════════════════════════════╗
║  FEATURE             │ DECISION     │ REASONING               ║
╠═══════════════════════════════════════════════════════════════╣
║  TRADE EXECUTION     │ SHUT DOWN    │ Every trade risks       ║
║                      │ in EU-West.  │ overdraft. 12.8s stale  ║
║                      │ Route to     │ balance = no meaningful ║
║                      │ US-East.     │ balance check. $340K    ║
║                      │              │ exposure already.       ║
║                      │              │ REGULATORY RISK.        ║
║                      │              │ Latency via US: 850ms.  ║
║                      │              │ Unpleasant but SAFE.    ║
╠═══════════════════════════════════════════════════════════════╣
║  MARKET DATA         │ KEEP in      │ LOCAL_QUORUM reads      ║
║  DISPLAY             │ EU-West.     │ from local Cassandra    ║
║                      │ Add "DELAYED"│ work fine. Data is      ║
║                      │ banner.      │ 320ms+ stale but        ║
║                      │              │ traders can see prices. ║
║                      │              │ Surfacing staleness     ║
║                      │              │ lets traders decide.    ║
╠═══════════════════════════════════════════════════════════════╣
║  PORTFOLIO VIEW /    │ KEEP in      │ Stale by 12.8s.         ║
║  BALANCE DISPLAY     │ EU-West.     │ Add "BALANCE AS OF      ║
║                      │ Add staleness│ [timestamp]" indicator. ║
║                      │ indicator.   │ Not used for decisions. ║
╠═══════════════════════════════════════════════════════════════╣
║  ORDER BOOK          │ KEEP in      │ Cached from Cassandra.  ║
║  (READ-ONLY VIEW)    │ EU-West.     │ Stale but usable for    ║
║                      │ Add "DELAYED"│ market awareness.       ║
║                      │ banner.      │                         ║
╠═══════════════════════════════════════════════════════════════╣
║  ACCOUNT MANAGEMENT  │ Route to     │ Password changes,       ║
║  (WRITES)            │ US-East.     │ withdrawals, transfers  ║
║                      │              │ must hit primary.       ║
║                      │              │ 850ms latency is fine   ║
║                      │              │ for infrequent ops.     ║
╠═══════════════════════════════════════════════════════════════╣
║  SESSIONS / AUTH     │ KEEP in      │ EU Redis is independent ║
║                      │ EU-West.     │ and healthy. No reason  ║
║                      │              │ to disrupt sessions.    ║
╚═══════════════════════════════════════════════════════════════╝
```

### Justification

```
WHY NOT SHUT DOWN EU-WEST ENTIRELY?

  → Redirecting ALL EU users to US-East means:
    → 850ms latency on EVERY API call (browsing,
      viewing portfolio, checking prices)
    → At 23% packet loss, many requests will timeout
    → US-East must absorb ALL EU traffic (capacity risk)
    → Users who are just WATCHING the market (not trading)
      get a terrible experience for no safety benefit

  → The risk is specifically in TRADE EXECUTION using
    stale balance data. That's the only feature that
    needs to be shut down in EU.

WHY NOT KEEP EU-WEST TRADING ALIVE?

  → Replication lag is 12.8 seconds and GROWING
  → 23% packet loss means even routing to primary for
    balance checks is unreliable
  → At this degradation level, the cable may drop entirely
  → $340,000 in unauthorized exposure already exists
  → Every minute of continued EU trading adds risk
  → The REGULATORY COST of further overdrafts dwarfs
    the BUSINESS COST of EU trading being unavailable

THE DECISION IS CLEAR:
  Shut down the feature that's DANGEROUS (trade execution).
  Keep the features that are SAFE (read-only views with
  staleness indicators).

  This is the per-feature CAP approach in action:
  → Trade execution: choose CONSISTENCY (route to US primary)
  → Everything else: choose AVAILABILITY (serve from EU local)
```

### Implementation

```python
# Feature-level routing in the API Gateway:

async def route_request(request):
    partition_detected = cable_health.degraded()  # True at 14:07

    if partition_detected:
        if request.path.startswith('/api/trades/execute'):
            # TRADE EXECUTION → US-East primary
            return route_to_region('us-east', request)

        if request.path.startswith('/api/account/withdraw'):
            # FINANCIAL WRITES → US-East primary
            return route_to_region('us-east', request)

        if request.path.startswith('/api/trades/approve'):
            # TRADE APPROVAL → US-East primary
            return route_to_region('us-east', request)

        # All other requests → local EU-West (with staleness headers)
        response = await route_to_region('eu-west', request)
        response.headers['X-Data-Staleness'] = f'{replication_lag_ms}ms'
        response.headers['X-Partition-Mode'] = 'degraded'
        return response

    # Normal operation — route to nearest region
    return route_to_nearest(request)
```

---

## Question 5: Mitigation Plan

### Priority Framework

```
This is a FINANCIAL PLATFORM.
  → Incorrect balances = REGULATORY violation
  → Trades beyond limits = FINANCIAL liability
  → $340,000 in unauthorized exposure = IMMEDIATE RISK
  → Every minute adds more exposure

PRIORITY: Stop financial risk FIRST, fix infrastructure SECOND.
```

### Step 1: HALT EU-West Trade Execution (Second 0-60)

```bash
# IMMEDIATE: Stop all trade execution in EU-West.
# This prevents any further trades based on stale balances.

# Option A: Feature flag (fastest if available)
kubectl set env deployment/api-gateway -n eu-west \
  EU_TRADE_EXECUTION=disabled \
  TRADE_ROUTE_OVERRIDE=us-east

# Option B: API Gateway rule to redirect trade endpoints
# Add routing rule: /api/trades/* → us-east-alb
kubectl apply -f - <<EOF
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: trade-execution-failover
  namespace: eu-west
spec:
  hosts:
    - api.trading.example.com
  http:
    - match:
        - uri:
            prefix: /api/trades/execute
        - uri:
            prefix: /api/trades/approve
      route:
        - destination:
            host: us-east-alb.trading.internal
    - route:
        - destination:
            host: eu-west-api.trading.internal
EOF

# EU traders will now experience 850ms+ latency on trades
# but ALL trades will be checked against the primary DB.

# VERIFY:
# → No new "exceeded balance limits" alerts
# → EU trade execution latency: ~1-2 seconds
#   (850ms network + processing)
# → EU trades succeeding (slowly) or failing gracefully
#   if timeout exceeded
# → US-East trade execution: unaffected
```

**VERIFY before proceeding:**
```
→ Risk management alerts: no new balance limit violations
→ EU trade flow: executing against US-East primary
→ US-East: absorbing EU trade load without pool exhaustion
```

### Step 2: Notify Risk Management and Compliance (Second 0-120, Parallel)

```
IMMEDIATE NOTIFICATION (parallel with Step 1):

  TO: Risk Management, Compliance, Trading Floor Manager

  SUBJECT: P1 INCIDENT — Cross-region partition, unauthorized
  trade exposure

  BODY:
  - 3 trades in EU-West exceeded account balance limits
  - Total unauthorized exposure: $340,000
  - Root cause: stale balance reads from EU replica
    during cross-Atlantic cable degradation
  - Replication lag: 12.8 seconds (and growing)
  - EU trade execution has been halted/redirected to US-East
  - Affected accounts identified:
    [Alice: $20K overdraft, accounts 2 and 3: details]

  REQUIRED ACTIONS:
  - Risk team: review all EU trades from 14:00-14:07
    for potential balance violations
  - Compliance: assess regulatory notification requirements
  - Trading desk: may need to unwind affected positions
```

```sql
-- Identify ALL potentially affected trades:
SELECT t.trade_id, t.user_id, t.amount, t.executed_at,
       t.region, a.current_balance,
       (a.current_balance - t.amount) AS post_trade_balance
FROM trades t
JOIN accounts a ON t.user_id = a.user_id
WHERE t.region = 'eu-west'
  AND t.executed_at >= '2024-01-15 14:00:00'
  AND t.amount > a.current_balance
ORDER BY (t.amount - a.current_balance) DESC;

-- This finds all EU trades where the trade amount
-- exceeded the ACTUAL balance at time of execution
```

### Step 3: Add Staleness Indicators to EU-West Read Paths (Minute 2-5)

```python
# EU users can still browse, view prices, check portfolios.
# But all read-only endpoints should surface staleness.

# Middleware for EU-West API servers:
class StalenessIndicatorMiddleware:
    async def process_response(self, request, response):
        if CABLE_DEGRADED:
            # Calculate replication lag
            lag = await get_replication_lag()  # 12.8 seconds

            response.headers['X-Data-Staleness-Seconds'] = str(lag)
            response.headers['X-Partition-Mode'] = 'degraded'

            # Inject banner into HTML responses:
            if 'text/html' in response.content_type:
                banner = (
                    '<div class="staleness-warning">'
                    f'⚠️ Data may be up to {int(lag)} seconds delayed '
                    'due to network issues. Trade execution is routed '
                    'to the primary datacenter for accuracy.'
                    '</div>'
                )
                response.body = banner + response.body

        return response
```

```bash
kubectl set env deployment/api-service -n eu-west \
  SHOW_STALENESS_BANNER=true \
  STALENESS_BANNER_THRESHOLD_SEC=2

# VERIFY:
# → EU users see staleness banner on all pages
# → No new customer complaints about "wrong balance"
#   (they understand the delay)
```

### Step 4: Monitor Cable Recovery and Prepare Failback (Minute 5+)

```bash
# Monitor the cross-region link:
watch -n 10 "ping -c 5 eu-west-gateway.internal | tail -1; \
  echo 'PG Replication Lag:'; \
  psql -h us-east-primary -c \"SELECT now() - pg_last_xact_replay_timestamp() AS lag FROM eu_west_replica;\""

# Decision tree:
#
# IF cable improves (latency < 200ms, packet loss < 2%):
#   → Wait for replication lag to drop below 100ms
#   → Re-enable EU trade execution against local replica
#   → Remove staleness banners
#   → Monitor for 30 minutes before declaring recovery
#
# IF cable continues degrading (latency > 1s, loss > 30%):
#   → Prepare for full EU → US-East failover
#   → Pre-scale US-East to absorb all EU traffic
#   → Redirect ALL EU API traffic to US-East
#   → Keep EU CDN and static content local
#   → Communicate to traders: "EU experiencing connectivity
#     issues, trades routed via US — expect increased latency"
#
# IF cable drops completely:
#   → PostgreSQL replication breaks (replica needs manual
#     rejoin when cable restores)
#   → EU-West is fully isolated
#   → All EU traffic must go through US-East
#   → EU Cassandra may have data divergence — will need
#     repair when connectivity restores
```

### Step 5: Post-Incident — Prevent Recurrence (After Resolution)

```
ARCHITECTURAL CHANGES:

1. IMPLEMENT PER-FEATURE ROUTING (from Q4 decision):
   → Trade execution: ALWAYS read balance from primary
   → Read-only views: use local replica with staleness
     indicator
   → This should be the PERMANENT architecture, not
     just an incident response

2. AUTOMATED PARTITION DETECTION + TRADE PROTECTION:
   → Monitor replication lag continuously
   → If lag > 1 second: automatically route trade
     approvals to primary
   → If lag > 5 seconds: automatically enable staleness
     banners
   → If lag > 10 seconds: automatically halt EU trade
     execution
   → These thresholds should be configurable and tested

3. PRE-TRADE BALANCE CHECK WITH LAG AWARENESS:
   → Before approving any trade, check the replica lag
   → If lag > threshold: reject the trade with message
     "Balance verification temporarily unavailable"
   → This is a CIRCUIT BREAKER for stale balance reads

4. REGULATORY REVIEW:
   → Review all trades from the incident window
   → Unwind positions that exceeded balance limits
   → File necessary regulatory notifications
   → Implement reconciliation procedures for
     split-brain scenarios
```

### Complete Mitigation Timeline

```
╔══════════════════════════════════════════════════════════════╗
║  TIME     │ ACTION                                           ║
╠══════════════════════════════════════════════════════════════╣
║  0-60s    │ HALT EU trade execution                          ║
║           │ Route trade endpoints to US-East primary         ║
║           │ VERIFY: no new balance violations                ║
╠══════════════════════════════════════════════════════════════╣
║  0-120s   │ NOTIFY risk management + compliance (parallel)   ║
║  (parallel)│ Identify all affected trades and accounts       ║
║           │ Begin regulatory assessment                      ║
╠══════════════════════════════════════════════════════════════╣
║  2-5min   │ Add staleness banners to EU read-only endpoints  ║
║           │ VERIFY: EU users see delay warnings              ║
║           │ VERIFY: EU read-only features functional         ║
╠══════════════════════════════════════════════════════════════╣
║  5min+    │ Monitor cable health                             ║
║           │ Prepare for escalation (full EU→US failover)     ║
║           │ OR prepare for recovery (lag declining)          ║
╠══════════════════════════════════════════════════════════════╣
║  Recovery │ Wait for replication lag < 100ms                 ║
║           │ Re-enable EU trade execution                     ║
║           │ Remove staleness banners                         ║
║           │ Monitor 30 minutes                               ║
╠══════════════════════════════════════════════════════════════╣
║  Post-    │ Review all affected trades with risk team        ║
║  incident │ Implement per-feature routing permanently        ║
║           │ Implement lag-aware circuit breaker for trades   ║
║           │ Implement automated partition detection          ║
║           │ File regulatory notifications if required        ║
║           │ Load test EU→US failover path                    ║
╚══════════════════════════════════════════════════════════════╝

GUIDING PRINCIPLE:
  On a financial platform, the hierarchy is:

  1. FINANCIAL INTEGRITY (no unauthorized exposure)
  2. REGULATORY COMPLIANCE (report and remediate)
  3. AVAILABILITY (keep as much working as safely possible)
  4. LATENCY (accept slower trades over wrong trades)

  We sacrifice latency and partial availability to
  protect financial integrity. That's the correct
  tradeoff for this domain.
```

---

## Preserved notes from retired Northstar drill

## Ops Sim: Northstar Wallet Partition Tradeoff

### Q1 - Layer & root cause

Wallet holds are money-moving correctness operations, so they should be PC/EC: during a partition, sacrifice availability rather than accept stale or conflicting holds.

Browsing/watchlists can be AP/EL because stale or unavailable personalization is less damaging than a failed purchase. Balance display can be available only with explicit staleness badges and no authority for bidding.

### Q2 - Evidence

- us-east-1 primary is healthy.
- Cross-region RTT and packet loss are degraded.
- EU replica lag is 21s with stale-version alerts.
- Primary-routed wallet hold p99 rises due to network path, not primary CPU/error.

### Q3 - Sequencing

1. Declare P1 for money-path degradation.
2. Fail closed for `wallet_hold_for_bid` if primary/linearizable hold cannot complete within budget.
3. Keep browsing, watchlists, and read-only auction pages available.
4. Show balance display as stale/unavailable when replica lag exceeds threshold.
5. Communicate "EU bidding limited due to wallet verification" rather than "site down."
6. Watch overdraft guardrail, hold queue depth, timeout rate, and replica catch-up.

### Q4 - Bad fixes

Local replica wallet holds are dangerous because a 21s stale balance can approve bids against money already spent or withdrawn.

Global browse shutdown is overbroad because CAP decisions are per feature. Catalog reads can stay available without violating ledger correctness.

### Q5 - Capacity / blast radius

At 1.2s p99, synchronous calls hold app workers and connection slots longer. Expect rising gateway queues, retry storms, wallet API thread exhaustion, and bid timeouts. If clients retry, us-east-1 ledger can receive amplified traffic from EU.

### Q6 - Durable fix

- Encode per-feature partition policy in config and tests.
- Money holds require primary/quorum and idempotency keys.
- Read-only displays have max-staleness badges and automatic disable thresholds.
- Regional degradation mode preserves browse while blocking unsafe writes.
- Game days assert wallet holds fail closed under packet loss/lag.

### Q7 - Org / runbook

Approval/informed parties: incident commander, payments/ledger owner, checkout owner, regional GM, finance/risk, support, and legal/compliance for customer-impacting money-path changes.

Pre-authorized: fail closed wallet holds and keep non-money reads available. Escalate before allowing stale-balance bids.
