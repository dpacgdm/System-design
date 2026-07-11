# Answer Key - DNS Resolution

> Open only after attempting the learner file Ops Sim.

## Ops Sim: Northstar Checkout DNS Failover That Did Not Fail Over

### Q1 - Layer & root cause

There are two DNS problems:

1. Public failover staleness: recursive resolvers and JVM clients keep returning the old ALB after Route 53 changed answers.
2. Internal resolver amplification: pods use bare `checkout-api` with `ndots:5`, generating multiple search-suffix queries and overwhelming CoreDNS.

These are both DNS-layer issues, but they have different mitigations.

### Q2 - Evidence

Stale public/client cache:
- Different public resolvers return different ALBs.
- Route 53 health check has been unhealthy since 12:03 but ISP-X still returns old.
- JVM `networkaddress.cache.ttl=-1` means infinite process-local DNS caching.

Internal overload:
- CoreDNS CPU 94%, QPS 410k, NXDOMAIN 61%.
- Logs show lookup timeouts to cluster DNS.
- Trace shows bare hostname causing repeated search-suffix attempts.

### Q3 - First actions

1. Stop new writes from old ALB at the application/edge layer: mark old checkout target read-only or reject/redirect mutating checkout paths.
2. Shift controlled clients through config/service discovery rather than waiting for every resolver.
3. Restart or refresh known JVM clients with infinite DNS cache if safe and scoped.
4. Scale CoreDNS and/or enable NodeLocal DNSCache while fixing bare hostnames.
5. Verify by resolver sample, ALB target split, write success rate, and duplicate-charge guardrails.

### Q4 - Bad fixes

Deleting the old ALB record is dangerous because clients with cached old answers will still connect to the old ALB by name/IP until their cache expires. If the old endpoint is not safely handling traffic, deleting DNS does not remove stale clients.

"Wait for TTL" is incomplete because some clients ignore TTLs (`networkaddress.cache.ttl=-1`) and some recursive resolvers can serve stale data. Internal CoreDNS overload also will not resolve by waiting.

### Q5 - Capacity / blast radius

With `ndots:5`, a bare hostname can generate up to 5 queries: several search-domain expansions plus the final absolute query.

```text
80,000 lookups/sec x 5 ~= 400,000 DNS queries/sec
```

That matches the observed CoreDNS QPS and can break unrelated services because CoreDNS is shared cluster infrastructure.

### Q6 - Durable fix

- Lower public TTL well before planned failovers; document the lead time.
- Set JVM `networkaddress.cache.ttl` to a bounded value such as 30-60s.
- Use FQDNs or namespace-qualified service names for cross-namespace calls.
- Set pod `ndots` intentionally for high-QPS clients.
- Deploy NodeLocal DNSCache for large EKS clusters.
- Run failover game days that sample authoritative, recursive, and application-process DNS.

### Q7 - Org / runbook

Notify incident commander, checkout owner, edge/DNS owner, database/payments owner, support, and business lead.

Pre-authorized: make old region read-only for checkout writes, shift edge routing to healthy ALB, restart scoped JVM workers with bad DNS cache, and scale CoreDNS. Escalate before changing payment idempotency/durability behavior.

---

# Incident Deep-Dive: DNS Migration Failure on Black Friday

---

## Question 1: Three DNS Problems — Root Cause, Evidence, Math

### Problem 1: Recursive Resolver TTL Non-Compliance (External DNS Caching)

**Root Cause:** The team set TTL=60 on `shop.example.com` and assumed that removing the US-East ALB from Route 53 would propagate to all users within 60 seconds. It didn't. Recursive resolvers between the authoritative nameserver and the end user — ISP resolvers, corporate resolvers, public resolvers like Google 8.8.8.8 — do **not** uniformly honor low TTLs. Many apply **minimum TTL floors** of 5-30 minutes regardless of what the authoritative server specifies.

**The monitoring data that reveals this:**
```
EVIDENCE 1: dig @ns1.route53.amazonaws.com shop.example.com
  → Correctly returns ONLY EU-West and AP-NE IPs
  → The authoritative nameserver is CORRECT.
    Route 53 did its job.

EVIDENCE 2: dig @8.8.8.8 shop.example.com (from US)
  → SOMETIMES returns old US-East IP, sometimes EU-West
  → Google's recursive resolver still has STALE cached entries
  → 8.8.8.8 is not one server — it's thousands of edge nodes
  → Each edge node has its own cache, populated at different times
  → Some edges still serving the old record

EVIDENCE 3: Timeline data
  → 11:30: DNS change made (TTL=60s)
  → 11:35: 40% of US users still hitting old IP (5 minutes later)
  → 11:40: 15% of US users still hitting old IP (10 minutes later)
  → With strict TTL=60s compliance, 0% should hit old IP after 11:31
  → The decay curve (40% at 5min, 15% at 10min) reveals a
    DISTRIBUTION of cache expiration times across different
    resolver implementations — not a single 60-second cliff
```

### Problem 2: JVM Infinite DNS Caching (Application-Layer DNS Cache)

**Root Cause:** The Java-based inventory service resolved `db-primary.internal.example.com` to `10.0.1.50` when it was last restarted **3 days ago**. The JVM's default DNS caching behavior when a SecurityManager is installed is `networkaddress.cache.ttl = -1`, which means **cache DNS lookups forever** — until the JVM process is restarted. When the RDS failover occurred at 11:30 (changing the database IP), the inventory service continued connecting to the **old, now-dead IP** because the JVM never re-resolved the hostname.

**The monitoring data that reveals this:**
```
EVIDENCE 1: Inventory service logs
  → "Connection refused: 10.0.1.50:5432"
  → 10.0.1.50 is the OLD database IP
  → The RDS failover assigned a NEW IP to
    db-primary.internal.example.com
  → But the inventory service is still using 10.0.1.50

EVIDENCE 2: "The inventory service was restarted 3 days ago"
  → The JVM cached the DNS resolution at startup
  → 3 days later, it's still using that cached result
  → No TTL on earth is 3 days — this is application-layer
    caching IGNORING DNS TTL entirely

EVIDENCE 3: The pattern
  → The database endpoint HOSTNAME didn't change
    (still db-primary.internal.example.com)
  → Only the IP behind it changed (RDS failover)
  → If the JVM honored DNS TTL, it would re-resolve
    and get the new IP
  → It didn't → JVM DNS cache is infinite
```

### Problem 3: CoreDNS Overload in EU Kubernetes Cluster

**Root Cause:** When US traffic was redirected to EU-West, the EU application cluster went from handling 1x to ~3x its normal traffic. Every inbound request to the EU Kubernetes cluster generates internal DNS queries — service discovery, external API calls (Stripe, etc.), database lookups. CoreDNS, the cluster's DNS server, was provisioned for the EU region's normal query volume (~200K queries/sec). It is now handling 850K queries/sec — a 4.25x increase — and is at 98% CPU, unable to serve responses in a timely manner.

**The monitoring data that reveals this:**
```
EVIDENCE 1: CoreDNS CPU at 98%
  → DNS server is compute-saturated
  → Cannot process queries fast enough

EVIDENCE 2: CoreDNS query rate
  → Normal: 200,000 queries/sec
  → Current: 850,000 queries/sec
  → 4.25x increase (exceeds the 3x traffic increase because
    US users generate MORE DNS queries per request — they're
    being served by a foreign region that needs to resolve
    additional cross-region endpoints)

EVIDENCE 3: External API DNS resolution time
  → payments.stripe.com resolution: 500ms (normally 2ms)
  → 250x slowdown in DNS resolution
  → This cascades: every Stripe API call now takes 500ms+
    EXTRA before the HTTP request even begins
  → Payment processing latency spikes → checkout failures
    → revenue loss ON BLACK FRIDAY

EVIDENCE 4: The cascade effect
  → Slow DNS responses cause application-level timeouts
  → Timeouts trigger retries
  → Retries generate MORE DNS queries
  → CoreDNS gets even more overloaded
  → DNS responses get even slower
  → POSITIVE FEEDBACK LOOP
```

### Three Problems, Three Layers of the DNS Stack

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   PROBLEM 1: EXTERNAL DNS LAYER                              ║
║   Recursive resolvers (8.8.8.8, ISP DNS) ignoring            ║
║   TTL=60, serving stale US-East IP to US users               ║
║   IMPACT: 40% of US users can't reach the site               ║
║                                                              ║
║   PROBLEM 2: APPLICATION DNS LAYER                           ║
║   JVM caching db-primary.internal.example.com forever        ║
║   IMPACT: Inventory service completely broken,               ║
║   connecting to dead database IP                             ║
║                                                              ║
║   PROBLEM 3: CLUSTER DNS LAYER                               ║
║   CoreDNS overwhelmed by 4.25x query volume                  ║
║   IMPACT: All EU services degraded — 500ms DNS               ║
║   resolution means payment processing, external              ║
║   APIs, everything slows to a crawl                          ║
║                                                              ║
║   Three different DNS caches, three different                ║
║   failure modes, all triggered by ONE maintenance            ║
║   window decision.                                           ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 2: Why 40% of US Users Still Hit the Old IP at 11:35

The TTL is 60 seconds. Five minutes have passed. Why hasn't every user failed over?

**Because there is no such thing as "one DNS cache." There is a CHAIN of caches, each with its own TTL behavior, and the effective TTL is the MAXIMUM of all caches in the chain — not the minimum.**

### The DNS Resolution Chain for a US User

```
User opens shop.example.com in Chrome at 11:33

Step 1: BROWSER DNS CACHE
  Chrome maintains its own DNS cache.
  Chrome applies a MINIMUM cache time of 60 seconds,
  regardless of the record's TTL.
  If the user visited shop.example.com at 11:32,
  Chrome won't re-resolve until at least 11:33.
  → Cache: up to 60s (matches TTL, but floor-limited)

Step 2: OPERATING SYSTEM STUB RESOLVER CACHE
  If the browser cache misses, the OS resolver is queried.
  Windows DNS Client service: default cache behavior
  honors TTL, BUT has a minimum of 1 second.
  macOS: uses mDNSResponder, generally honors TTL.
  → Cache: generally 60s per TTL (minor factor)

Step 3: LOCAL NETWORK DNS (corporate/hotel/coffee shop)
  Corporate DNS servers (Active Directory DNS, Pi-hole,
  dnsmasq on home routers) often apply MINIMUM TTL floors.

  Common configurations:
    → Home router (dnsmasq): min-cache-ttl=300 (5 minutes)
    → Corporate AD DNS: may cache 10-15 minutes minimum
    → Hotel/airport captive portal DNS: highly variable

  These resolvers IGNORE the 60-second TTL and cache
  for their configured minimum.
  → Cache: 5-15 minutes regardless of TTL

Step 4: ISP RECURSIVE RESOLVER
  US ISPs (Comcast, AT&T, Verizon) run their own
  recursive resolvers. Many are known to apply
  minimum TTL floors to reduce upstream query load:

    → Comcast: historically 5-minute minimum TTL
    → Some ISPs: 10-30 minute minimums
    → Behavior varies by resolver implementation
      and configuration

  → Cache: 5-30 minutes regardless of TTL

Step 5: PUBLIC RECURSIVE RESOLVER (8.8.8.8, 1.1.1.1)
  Google 8.8.8.8 generally honors TTL well, BUT:
    → 8.8.8.8 is an ANYCAST address — thousands of
      edge servers worldwide
    → Each edge server has its own independent cache
    → When a user's request hits edge server A
      (which cached at 11:29), it gets the old IP
    → Another user hits edge server B (which cached
      at 11:30:30), it gets the new IP
    → This is why dig @8.8.8.8 returns old IP SOMETIMES
  → Cache: 0-60s per TTL, but INCONSISTENT across edges
```

### The Math: Why 40% at 11:35

```
At 11:30:00 — DNS change made. Route 53 authoritative
              server now returns only EU-West and AP-NE.

For a user to get the NEW IP, ALL caches in their
chain must expire. The chain is:

  Browser → OS → Local Network → ISP/Public Resolver → Authoritative

The authoritative is already correct. The bottleneck
is the SLOWEST cache in the chain.

USER POPULATION BREAKDOWN AT 11:35 (T+5min):

Category A: Users whose ENTIRE cache chain has expired
  → Modern browser + no corporate DNS + ISP that
    honors TTL + cached >60s ago
  → These users have the new IP
  → ~60% of users ✓

Category B: Users behind ISP resolvers with TTL floors
  → ISP applies 5-minute minimum TTL
  → Cache won't expire until 11:35 at earliest
  → Some ISP caches populated at 11:29 → expire 11:34 ✓
  → Some ISP caches populated at 11:30 → expire 11:35 ⚠️ BORDERLINE
  → Some ISP caches populated after 11:30 but before
    the ISP's edge refreshed → still stale
  → ~20% of users ✗

Category C: Users behind corporate/local DNS with
            minimum TTL floors of 10-15 minutes
  → Won't expire until 11:40-11:45
  → ~10% of users ✗

Category D: Users whose browser cache is hot
  → Visited the site in the last 60 seconds
  → Browser hasn't re-resolved yet
  → Small percentage, constantly rolling
  → ~5% of users ✗

Category E: Users with aggressive local caching
  → Home routers with dnsmasq min-cache-ttl=300+
  → Stale corporate proxy caches
  → ~5% of users ✗

  TOTAL AT 11:35:
    Category A:           60% → working ✓
    Categories B+C+D+E:   40% → still hitting old IP ✗

    MATCHES THE OBSERVED 40% EXACTLY.

AT 11:40 (T+10min):
    Category B (ISP 5-min floors) → mostly expired now ✓
    Category C (corporate 10-min floors) → still stale ✗
    Category D (browser) → long since expired ✓
    Category E (aggressive local) → some still stale ✗

    Remaining: ~15% → MATCHES THE OBSERVED 15%.

THE LONG TAIL:
  The decay from 40% → 15% → eventual 0% follows a
  LONG TAIL distribution, not a cliff. You will have
  stragglers for 30+ minutes because SOME resolvers
  in the wild have minimum TTLs of 30 minutes or more.

  ╔══════════════════════════════════════════════════════════════╗
  ║   % users hitting old IP                                     ║
  ║   100%│▓▓▓▓▓▓▓▓                                              ║
  ║       │        ▓▓▓▓                                          ║
  ║    40%│────────────▓▓▓▓                                      ║
  ║       │                ▓▓▓▓                                  ║
  ║    15%│────────────────────▓▓▓▓                              ║
  ║       │                        ▓▓▓▓▓                         ║
  ║     5%│                             ▓▓▓▓▓▓▓▓▓▓               ║
  ║     0%│────────────────────────────────────────              ║
  ║       11:30  11:35  11:40  11:45  11:50  12:00               ║
  ║                                                              ║
  ║   NOT a cliff at 60 seconds.                                 ║
  ║   A LONG TAIL driven by cache diversity.                     ║
  ╚══════════════════════════════════════════════════════════════╝
```

### The Core Insight

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   TTL=60 does NOT mean "all users refresh in 60s"            ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   It means: "I am REQUESTING that caches expire              ║
║   in 60 seconds."                                            ║
║                                                              ║
║   Recursive resolvers, ISP caches, corporate DNS,            ║
║   browser caches, and OS caches are free to                  ║
║   IGNORE this request. Many do.                              ║
║                                                              ║
║   The EFFECTIVE TTL for a given user is:                     ║
║   max(browser_min, os_min, local_dns_min,                    ║
║       isp_min, resolver_cache_remaining)                     ║
║                                                              ║
║   You control the TTL at the authoritative server.           ║
║   You control NOTHING about the caches between               ║
║   the authoritative and the user.                            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 3: Immediate Mitigation for Each Problem

### Problem 1 Mitigation: US Users Still Hitting Dead US-East IP

**You cannot force recursive resolvers to expire their caches.** The old IP is out there and you can't pull it back. So instead: **make the old IP work.**

```bash
# ACTION 1A: Keep the US-East ALB ALIVE and serving traffic
# DO NOT remove the US-East ALB from DNS during the migration.
# Instead, configure the US-East ALB to redirect/proxy to EU-West.

# Since the US-East ALB is still receiving traffic from stale
# DNS caches, re-add it to Route 53 IMMEDIATELY:
aws route53 change-resource-record-sets \
  --hosted-zone-id Z1234567890 \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "shop.example.com",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "Z35SXDOTRQ7X7K",
          "DNSName": "us-east-alb.us-east-1.elb.amazonaws.com",
          "EvaluateTargetHealth": false
        },
        "SetIdentifier": "us-east-failover",
        "Region": "us-east-1"
      }
    }]
  }'

# ACTION 1B: Configure the US-East ALB to return a
# maintenance page OR redirect to EU-West
#
# ALB Listener Rule — redirect all traffic to EU-West:
aws elbv2 create-rule \
  --listener-arn arn:aws:elasticloadbalancing:us-east-1:...:listener/... \
  --priority 1 \
  --conditions '[{"Field":"path-pattern","Values":["/*"]}]' \
  --actions '[{
    "Type": "redirect",
    "RedirectConfig": {
      "Host": "eu-west-shop.example.com",
      "StatusCode": "HTTP_302"
    }
  }]'

# Now users hitting the old US-East IP get:
#   → A 302 redirect to the EU-West endpoint
#   → Instead of "Connection refused"
#   → The site WORKS, just with an extra redirect hop
#   → This buys time for ALL resolver caches to expire naturally
```

**Time to implement: 2-3 minutes. Immediately resolves the 40% user impact.**

### Problem 2 Mitigation: JVM DNS Cache — Inventory Service

**The JVM has cached `db-primary.internal.example.com → 10.0.1.50` forever. The database is now at a new IP. The fix is to force a DNS re-resolution.**

```bash
# ACTION 2A: IMMEDIATE — Restart the inventory service pods
# This is the fastest way to clear the JVM's DNS cache.
# A JVM restart forces fresh DNS resolution at startup.

kubectl rollout restart deployment/inventory-service -n eu-west

# All pods will restart, resolve db-primary.internal.example.com
# to the NEW IP, and reconnect to the functioning database.
# Time: 60-90 seconds for rolling restart.

# ACTION 2B: VERIFY the new pods have the correct IP
kubectl exec -it deployment/inventory-service -n eu-west -- \
  nslookup db-primary.internal.example.com

# Should return the NEW database IP (not 10.0.1.50)

# ACTION 2C: PERMANENT FIX — Set JVM DNS TTL for all Java services
# Add to the Dockerfile or JVM startup flags so this NEVER
# happens again:

# Option 1: JVM flag (preferred — explicit and visible)
# In the Kubernetes deployment manifest:
env:
  - name: JAVA_OPTS
    value: "-Dsun.net.inetaddr.ttl=30 -Dsun.net.inetaddr.negative.ttl=10"

# Option 2: In $JAVA_HOME/conf/security/java.security:
#   networkaddress.cache.ttl=30
#   networkaddress.cache.negative.ttl=10

# This tells the JVM: "Re-resolve DNS every 30 seconds."
# Matches a reasonable internal DNS TTL.
# Negative TTL=10 means "retry failed lookups after 10 seconds."
```

### Problem 3 Mitigation: CoreDNS Overload in EU Cluster

**CoreDNS is at 98% CPU processing 850K queries/sec. It's the bottleneck for ALL services in the EU cluster — including payment processing.**

```bash
# ACTION 3A: IMMEDIATE — Scale up CoreDNS replicas
# CoreDNS is typically a Deployment in kube-system.
# It's probably running 2-3 replicas (sized for normal EU traffic).

kubectl -n kube-system get deployment coredns
# Likely shows: 2/2 or 3/3 replicas

# Scale to handle 4.25x normal load:
kubectl -n kube-system scale deployment/coredns --replicas=12

# 3 replicas at 98% CPU handling 850K qps
# 12 replicas = 4x capacity = each replica at ~25% CPU
# DNS resolution time should drop from 500ms back to ~2ms
# Payment processing immediately recovers

# ACTION 3B: Enable NodeLocal DNSCache
# This runs a DNS cache on EVERY node, so pods resolve
# DNS locally instead of making network calls to CoreDNS pods.
# Massively reduces CoreDNS central load.

# If not already deployed:
kubectl apply -f https://raw.githubusercontent.com/kubernetes/kubernetes/master/cluster/addons/dns/nodelocaldns/nodelocaldns.yaml

# NodeLocal DNSCache intercepts DNS queries at the node level,
# caches responses locally, and only forwards cache misses
# to CoreDNS. With 850K qps, most are repeat queries for
# the same hostnames (payments.stripe.com, db endpoints,
# service names). Cache hit rate will be >90%, dropping
# CoreDNS load from 850K to <100K qps.

# ACTION 3C: Verify recovery
# Watch CoreDNS CPU drop:
kubectl -n kube-system top pods -l k8s-app=kube-dns --watch

# Verify Stripe DNS resolution is back to normal:
kubectl exec -it deployment/payment-service -n eu-west -- \
  dig payments.stripe.com | grep "Query time"
# Should show: Query time: 1-5 msec (not 500ms)
```

### Mitigation Summary — All Three Problems

```
╔═════════════════════════════════════════════════════════════════════╗
║  PROBLEM│ ROOT CAUSE             │ IMMEDIATE FIX        │ TIME      ║
╠═════════════════════════════════════════════════════════════════════╣
║  1      │ Recursive resolvers    │ Re-add US-East ALB   │ 2-3 min   ║
║         │ serving stale IPs      │ with redirect to     │           ║
║         │                        │ EU-West              │           ║
╠═════════════════════════════════════════════════════════════════════╣
║  2      │ JVM infinite DNS cache │ Rolling restart of   │ 60-90 sec ║
║         │ (3-day stale entry)    │ inventory service +  │           ║
║         │                        │ set JVM DNS TTL=30   │           ║
╠═════════════════════════════════════════════════════════════════════╣
║  3      │ CoreDNS overwhelmed by │ Scale CoreDNS to 12  │ 30-60 sec ║
║         │ 4.25x query volume     │ replicas + deploy    │           ║
║         │                        │ NodeLocal DNSCache   │           ║
╚═════════════════════════════════════════════════════════════════════╝

Total time to mitigate all three: ~5 minutes
The team didn't identify Problem 2 until 11:42 (12 min in)
and Problem 3 until 11:45 (15 min in).

This is a BLACK FRIDAY incident.
Every minute of degraded checkout = tens of thousands
of dollars in lost revenue.
```

---

## Question 4: The Correct Maintenance Window Runbook

This maintenance window failed because the team treated DNS as a light switch — flip it off, do the work, flip it back on. DNS is not a light switch. It's a **propagation system** with caches you don't control and latencies you can't predict.

Here's the runbook that should have been followed:

### Phase 0: Pre-Maintenance Preparation (7 days before)

```
STEP 0.1: LOWER THE TTL IN ADVANCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Current TTL: 60 seconds
  Problem: Recursive resolvers may cache for much longer

  7 DAYS before maintenance:
    → Lower TTL from 60s to 10s
    → Wait 7 days (this ensures that even the most
      aggressive caching resolver has seen the new TTL
      and will honor the 10-second expiry)

  WHY 7 DAYS?
    → Some resolvers cache based on the TTL they SAW
      when they last fetched the record
    → If a resolver fetched the record 6 days ago
      with TTL=60, it may still cache up to 60s
      from its next refresh
    → After 7 days, every resolver in the world has
      fetched the record with TTL=10 at least once
    → Effective propagation time after DNS change
      drops from 5-30 minutes to ~30-60 seconds

  aws route53 change-resource-record-sets \
    --hosted-zone-id Z1234567890 \
    --change-batch '{
      "Changes": [{
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "shop.example.com",
          "Type": "A",
          "TTL": 10,
          ...
        }
      }]
    }'

STEP 0.2: AUDIT APPLICATION-LAYER DNS CACHING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Check EVERY service that connects to
  db-primary.internal.example.com:

  → Java services: verify networkaddress.cache.ttl
    grep -r "networkaddress.cache.ttl" $JAVA_HOME/conf/

    If set to -1 (infinite) or unset (default varies):
      → Set to 30 seconds in ALL Java service deployments
      → Deploy the change BEFORE maintenance window
      → Verify with:
        jcmd <pid> VM.flags | grep inetaddr

  → Python services: socket.getaddrinfo() doesn't cache
    by default, but frameworks (requests, urllib3) may
    cache at the connection pool level. Verify.

  → Go services: net.DefaultResolver caches per the
    OS resolver. Generally safe.

  → Node.js services: dns.lookup() uses the OS cache.
    dns.resolve() bypasses it. Verify which is used.

STEP 0.3: LOAD TEST THE RECEIVING REGIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  US-East handles ~33% of global traffic.
  When US-East is removed, EU-West and AP-NE must
  absorb that traffic.

  BEFORE the maintenance window:
  → Load test EU-West at 3x normal traffic
  → Load test AP-NE at 2x normal traffic
  → Specifically verify:
    → CoreDNS capacity (queries/sec headroom)
    → Database read replica capacity
    → Application pod autoscaling response time
    → External API rate limits (Stripe, etc.)

  If CoreDNS can't handle 4x queries:
  → Pre-scale CoreDNS to 12 replicas
  → Deploy NodeLocal DNSCache BEFORE the window
  → Don't discover the bottleneck during the incident
```

### Phase 1: Pre-Maintenance Validation (1 hour before)

```
STEP 1.1: VERIFY TTL PROPAGATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  From multiple geographic locations, verify that
  recursive resolvers are returning TTL=10:

  # From US:
  dig shop.example.com +noall +answer
  # Verify: TTL shows ≤10

  # From EU:
  dig shop.example.com +noall +answer

  # From Asia:
  dig shop.example.com +noall +answer

  # From multiple public resolvers:
  dig @8.8.8.8 shop.example.com
  dig @1.1.1.1 shop.example.com
  dig @208.67.222.222 shop.example.com  # OpenDNS

STEP 1.2: PRE-SCALE RECEIVING REGIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  # Scale EU-West application pods for 3x traffic
  kubectl -n eu-west scale deployment/web-frontend --replicas=30
  kubectl -n eu-west scale deployment/inventory-service --replicas=20
  kubectl -n eu-west scale deployment/payment-service --replicas=15

  # Scale CoreDNS preemptively
  kubectl -n kube-system scale deployment/coredns --replicas=12

  # Scale AP-NE similarly
  kubectl -n ap-ne scale deployment/web-frontend --replicas=20
  ...

STEP 1.3: VERIFY JAVA DNS TTL SETTINGS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  For every Java service in EU-West and AP-NE:

  kubectl exec -it deployment/inventory-service -n eu-west -- \
    java -XshowSettings:all 2>&1 | grep networkaddress

  # Must show: networkaddress.cache.ttl=30
  # If it shows -1 or is absent: STOP. Fix this first.
```

### Phase 2: Execute the DNS Change (T=0)

```
STEP 2.1: DO NOT REMOVE THE US-EAST ALB FROM DNS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  This is the CRITICAL difference.

  Instead of removing US-East from Route 53
  (which creates the stale cache problem):

  KEEP the US-East ALB in DNS, but configure it
  to proxy/redirect to EU-West.

  # Configure US-East ALB to redirect all traffic:
  aws elbv2 modify-listener \
    --listener-arn $US_EAST_LISTENER_ARN \
    --default-actions '[{
      "Type": "fixed-response",
      "FixedResponseConfig": {
        "StatusCode": "302",
        "Location": "https://shop.example.com",
        "MessageBody": ""
      }
    }]'

  # OR better — use a lightweight proxy/maintenance page
  # behind the US-East ALB that forwards to EU-West.

  Result:
  → Users with stale DNS cache → hit US-East ALB
    → get redirected → site works
  → Users with fresh DNS cache → hit EU-West or AP-NE
    directly → site works
  → ZERO USERS SEE "CONNECTION REFUSED"

STEP 2.2: WAIT FOR DNS PROPAGATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  # Monitor the percentage of traffic hitting
  # US-East ALB (should be declining):
  watch -n 10 "aws cloudwatch get-metric-statistics \
    --namespace AWS/ApplicationELB \
    --metric-name RequestCount \
    --dimensions Name=LoadBalancer,Value=$US_EAST_ALB \
    --start-time $(date -u -d '-5 min' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 60 --statistics Sum"

  # Wait until US-East traffic drops to <1% of total
  # With TTL=10 pre-lowered 7 days ago, this should
  # happen within 2-3 minutes

STEP 2.3: NOW BEGIN THE DATABASE MIGRATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Only AFTER confirming traffic has drained from US-East:

  → Begin the 10-minute database migration
  → US-East ALB is still alive, redirecting the
    remaining <1% of straggler traffic
  → No user impact
```

### Phase 3: Post-Migration Recovery (T+10min)

```
STEP 3.1: VERIFY DATABASE IS BACK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  → Confirm US-East primary database is healthy
  → Confirm replication to EU and Asia replicas resumed
  → Run health checks against the application

STEP 3.2: RESTORE US-EAST ALB TO NORMAL OPERATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  → Remove the redirect rule from US-East ALB
  → Restore normal application target groups
  → Route 53 is still configured with US-East
    (we never removed it)
  → Traffic naturally flows back as latency-based
    routing directs US users to their nearest region

STEP 3.3: RESTORE NORMAL TTL
━━━━━━━━━━━━━━━━━━━━━━━━━━━
  → Increase TTL back to 300 seconds (5 minutes)
  → Low TTLs increase DNS query volume and cost
  → Only use low TTLs when preparing for changes

STEP 3.4: SCALE DOWN RECEIVING REGIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  → Gradually reduce EU-West and AP-NE replicas
    back to normal as US-East absorbs its traffic
  → Scale CoreDNS back down (but keep NodeLocal
    DNSCache — it should always be running)
```

### The Runbook as a Checklist

```
╔══════════════════════════════════════════════════════════════╗
║   MAINTENANCE WINDOW RUNBOOK: DNS-DEPENDENT FAILOVER         ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   □ T-7 DAYS                                                 ║
║     □ Lower TTL to 10 seconds                                ║
║     □ Audit all application DNS caching (JVM, etc.)          ║
║     □ Fix any infinite/long DNS cache settings               ║
║     □ Deploy NodeLocal DNSCache in receiving clusters        ║
║     □ Load test receiving regions at expected traffic        ║
║                                                              ║
║   □ T-1 HOUR                                                 ║
║     □ Verify TTL=10 from multiple global resolvers           ║
║     □ Pre-scale receiving regions (app + CoreDNS)            ║
║     □ Verify JVM DNS TTL is 30s on all Java services         ║
║     □ Prepare US-East ALB redirect rule (don't apply yet)    ║
║                                                              ║
║   □ T=0 (MAINTENANCE START)                                  ║
║     □ Apply redirect rule to US-East ALB                     ║
║     □ DO NOT remove US-East from Route 53                    ║
║     □ Monitor: US-East traffic declining                     ║
║     □ Wait for US-East traffic < 1%                          ║
║     □ BEGIN database migration                               ║
║                                                              ║
║   □ T+10min (MIGRATION COMPLETE)                             ║
║     □ Verify database health                                 ║
║     □ Restore US-East ALB to normal operation                ║
║     □ Verify all regions serving traffic normally            ║
║     □ Restore TTL to 300 seconds                             ║
║     □ Scale down receiving regions gradually                 ║
║                                                              ║
║   □ T+1 HOUR (POST-MAINTENANCE)                              ║
║     □ Verify zero elevated error rates                       ║
║     □ Verify DNS resolution times normal in all clusters     ║
║     □ Write post-incident review                             ║
║                                                              ║
║   CRITICAL RULES:                                            ║
║     → NEVER remove a DNS record expecting instant failover   ║
║     → ALWAYS keep the old IP functional (redirect/proxy)     ║
║     → ALWAYS lower TTL days in advance, not at changetime    ║
║     → ALWAYS audit application-layer DNS caches              ║
║     → ALWAYS pre-scale for the traffic you're redirecting    ║
║     → NEVER schedule DNS-dependent maintenance on peak       ║
║       traffic days (BLACK FRIDAY) unless unavoidable         ║
╚══════════════════════════════════════════════════════════════╝
```

### The Meta-Lesson

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   DNS is not a switch. It's a PROPAGATION SYSTEM.            ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   When you change a DNS record, you are not                  ║
║   "changing where traffic goes." You are                     ║
║   "requesting that thousands of independent                  ║
║   caches around the world eventually update                  ║
║   their view of where traffic should go."                    ║
║                                                              ║
║   You don't control when they update.                        ║
║   You don't control IF they honor your TTL.                  ║
║   You don't control application-layer caches                 ║
║   that bypass DNS entirely.                                  ║
║                                                              ║
║   The ONLY safe DNS migration strategy is:                   ║
║   KEEP THE OLD PATH WORKING until you are                    ║
║   certain no cache anywhere still points to it.              ║
║                                                              ║
║   That's not 60 seconds. That's not 5 minutes.               ║
║   That's HOURS to be safe. DAYS to be certain.               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```
